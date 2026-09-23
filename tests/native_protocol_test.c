#include <stdatomic.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#include <assert.h>

/*
 * P0-A Protocol Verification: C11 seq_cst Lock-Free Shared Move-Hint Protocol
 * Tests single-thread, forced interrupted writers, multi-writer collision on identical entry,
 * 64-bit sequence wraparound, and concurrent stress testing.
 */

typedef struct {
    _Atomic uint64_t sequence; /* bit 0 = writer lock/active; bits 1..63 = version */
    _Atomic uint64_t key;      /* strict XOR position key */
    _Atomic uint64_t data;     /* depth (8b), flags (8b), reserved (48b) */
    _Atomic uint64_t move_w0;  /* compact move word 0 (path_low) */
    _Atomic uint64_t move_w1;  /* compact move word 1 (captured_low) */
    _Atomic uint64_t move_w2;  /* compact move word 2 (meta) */
} SharedTTEntry;

_Static_assert(sizeof(SharedTTEntry) == 48, "SharedTTEntry must be exactly 48 bytes");
_Static_assert(sizeof(SharedTTEntry) % 8 == 0, "SharedTTEntry must be 64-bit aligned");

typedef struct {
    uint64_t key;
    uint64_t data;
    uint64_t move_w0;
    uint64_t move_w1;
    uint64_t move_w2;
} TTReaderSnapshot;

/* Writer protocol using strictly memory_order_seq_cst */
static inline bool shared_tt_write(SharedTTEntry *entry, uint64_t key, uint64_t data, uint64_t w0, uint64_t w1, uint64_t w2) {
    uint64_t cur_seq = atomic_load_explicit(&entry->sequence, memory_order_seq_cst);
    if ((cur_seq & 1) != 0) {
        return false; /* writer active: bounded store-skip */
    }
    uint64_t expected = cur_seq;
    if (!atomic_compare_exchange_strong_explicit(&entry->sequence, &expected, cur_seq + 1, memory_order_seq_cst, memory_order_seq_cst)) {
        return false; /* CAS lost to another writer: skip store without lock wait */
    }
    atomic_store_explicit(&entry->key, key, memory_order_seq_cst);
    atomic_store_explicit(&entry->data, data, memory_order_seq_cst);
    atomic_store_explicit(&entry->move_w0, w0, memory_order_seq_cst);
    atomic_store_explicit(&entry->move_w1, w1, memory_order_seq_cst);
    atomic_store_explicit(&entry->move_w2, w2, memory_order_seq_cst);
    atomic_store_explicit(&entry->sequence, cur_seq + 2, memory_order_seq_cst);
    return true;
}

/* Reader protocol using strictly memory_order_seq_cst */
static inline bool shared_tt_read(const SharedTTEntry *entry, uint64_t expected_key, TTReaderSnapshot *out) {
    uint64_t seq1 = atomic_load_explicit(&entry->sequence, memory_order_seq_cst);
    if ((seq1 & 1) != 0) {
        return false; /* write in progress: miss */
    }
    uint64_t k = atomic_load_explicit(&entry->key, memory_order_seq_cst);
    if (k != expected_key) {
        return false; /* key mismatch */
    }
    uint64_t d = atomic_load_explicit(&entry->data, memory_order_seq_cst);
    uint64_t w0 = atomic_load_explicit(&entry->move_w0, memory_order_seq_cst);
    uint64_t w1 = atomic_load_explicit(&entry->move_w1, memory_order_seq_cst);
    uint64_t w2 = atomic_load_explicit(&entry->move_w2, memory_order_seq_cst);
    uint64_t seq2 = atomic_load_explicit(&entry->sequence, memory_order_seq_cst);
    if (seq1 != seq2) {
        return false; /* torn read or intervening write: miss */
    }
    out->key = k;
    out->data = d;
    out->move_w0 = w0;
    out->move_w1 = w1;
    out->move_w2 = w2;
    return true;
}

/* -------------------------------------------------------------
 * Stress Test Harness
 * ------------------------------------------------------------- */
#define NUM_WRITERS 8
#define NUM_READERS 4
#define ITERS_PER_THREAD 100000

SharedTTEntry g_entry;
_Atomic bool g_start = false;
_Atomic uint64_t g_writer_success = 0;
_Atomic uint64_t g_writer_skips = 0;
_Atomic uint64_t g_reader_hits = 0;
_Atomic uint64_t g_reader_misses = 0;
_Atomic uint64_t g_torn_reads = 0;

DWORD WINAPI StressWriterThread(LPVOID param) {
    uint64_t writer_id = (uint64_t)(uintptr_t)param;
    while (!atomic_load_explicit(&g_start, memory_order_seq_cst)) {
        YieldProcessor();
    }
    for (uint64_t i = 1; i <= ITERS_PER_THREAD; ++i) {
        uint64_t tag = (writer_id << 48) | i;
        uint64_t key = 0xCAFEBABE00000000ULL | (i & 3);
        if (shared_tt_write(&g_entry, key, tag, tag ^ 0x1111111111111111ULL, tag ^ 0x2222222222222222ULL, tag ^ 0x3333333333333333ULL)) {
            atomic_fetch_add_explicit(&g_writer_success, 1, memory_order_seq_cst);
        } else {
            atomic_fetch_add_explicit(&g_writer_skips, 1, memory_order_seq_cst);
        }
    }
    return 0;
}

DWORD WINAPI StressReaderThread(LPVOID param) {
    (void)param;
    while (!atomic_load_explicit(&g_start, memory_order_seq_cst)) {
        YieldProcessor();
    }
    TTReaderSnapshot snap;
    for (uint64_t i = 1; i <= ITERS_PER_THREAD; ++i) {
        uint64_t target_key = 0xCAFEBABE00000000ULL | (i & 3);
        if (shared_tt_read(&g_entry, target_key, &snap)) {
            atomic_fetch_add_explicit(&g_reader_hits, 1, memory_order_seq_cst);
            /* Verify internal coherence: all fields MUST belong to the exact same write */
            uint64_t tag = snap.data;
            if (snap.move_w0 != (tag ^ 0x1111111111111111ULL) ||
                snap.move_w1 != (tag ^ 0x2222222222222222ULL) ||
                snap.move_w2 != (tag ^ 0x3333333333333333ULL)) {
                atomic_fetch_add_explicit(&g_torn_reads, 1, memory_order_seq_cst);
            }
        } else {
            atomic_fetch_add_explicit(&g_reader_misses, 1, memory_order_seq_cst);
        }
    }
    return 0;
}

int main(void) {
    printf("=== P0-A Shared TT Publication Protocol Harness (seq_cst) ===\n");
    printf("Entry size: %zu bytes (lock-free: %d)\n", sizeof(SharedTTEntry), atomic_is_lock_free(&g_entry.sequence));
    assert(sizeof(SharedTTEntry) == 48);
    assert(atomic_is_lock_free(&g_entry.sequence));
    assert(atomic_is_lock_free(&g_entry.key));
    assert(atomic_is_lock_free(&g_entry.data));
    assert(atomic_is_lock_free(&g_entry.move_w0));
    assert(atomic_is_lock_free(&g_entry.move_w1));
    assert(atomic_is_lock_free(&g_entry.move_w2));

    atomic_init(&g_entry.sequence, 0);
    atomic_init(&g_entry.key, 0);
    atomic_init(&g_entry.data, 0);
    atomic_init(&g_entry.move_w0, 0);
    atomic_init(&g_entry.move_w1, 0);
    atomic_init(&g_entry.move_w2, 0);

    /* 1. Basic Single-Thread test */
    TTReaderSnapshot s1;
    assert(!shared_tt_read(&g_entry, 100, &s1));
    bool w_ok = shared_tt_write(&g_entry, 100, 0xAAAA, 0x1, 0x2, 0x3);
    assert(w_ok);
    assert(shared_tt_read(&g_entry, 100, &s1));
    assert(s1.key == 100 && s1.data == 0xAAAA && s1.move_w0 == 0x1 && s1.move_w1 == 0x2 && s1.move_w2 == 0x3);
    printf("1. Single-thread read/write: PASS\n");

    /* 2. Forced Interrupted Writer test (midway during payload write) */
    uint64_t seq = atomic_load(&g_entry.sequence);
    /* Simulate writer CAS winning (seq becomes odd) */
    atomic_store(&g_entry.sequence, seq + 1);
    /* Writer wrote partial fields */
    atomic_store(&g_entry.key, 999);
    atomic_store(&g_entry.data, 0x9999);
    /* Writer paused before writing move_w0..w2 */
    assert(!shared_tt_read(&g_entry, 999, &s1)); /* Reader MUST reject (odd sequence) */
    assert(!shared_tt_write(&g_entry, 888, 0x8888, 0, 0, 0)); /* Other writer MUST skip (odd sequence) */
    /* Writer resumes, completes write */
    atomic_store(&g_entry.move_w0, 0x11);
    atomic_store(&g_entry.move_w1, 0x22);
    atomic_store(&g_entry.move_w2, 0x33);
    atomic_store(&g_entry.sequence, seq + 2); /* Sequence is even again */
    assert(shared_tt_read(&g_entry, 999, &s1));
    assert(s1.move_w0 == 0x11 && s1.move_w1 == 0x22 && s1.move_w2 == 0x33);
    printf("2. Forced Interrupted Writer rejection: PASS\n");

    /* 3. Multi-Writer Collision on Identical Entry */
    /* Two writers simulate CAS competition on same sequence */
    uint64_t base_seq = atomic_load(&g_entry.sequence);
    uint64_t exp1 = base_seq;
    uint64_t exp2 = base_seq;
    bool cas1 = atomic_compare_exchange_strong(&g_entry.sequence, &exp1, base_seq + 1);
    bool cas2 = atomic_compare_exchange_strong(&g_entry.sequence, &exp2, base_seq + 1);
    /* Exactly one writer MUST win, other MUST lose */
    assert(cas1 != cas2);
    if (cas1) {
        atomic_store(&g_entry.key, 777);
        atomic_store(&g_entry.data, 0x7777);
        atomic_store(&g_entry.move_w0, 0x71);
        atomic_store(&g_entry.move_w1, 0x72);
        atomic_store(&g_entry.move_w2, 0x73);
        atomic_store(&g_entry.sequence, base_seq + 2);
    } else {
        atomic_store(&g_entry.key, 666);
        atomic_store(&g_entry.data, 0x6666);
        atomic_store(&g_entry.move_w0, 0x61);
        atomic_store(&g_entry.move_w1, 0x62);
        atomic_store(&g_entry.move_w2, 0x63);
        atomic_store(&g_entry.sequence, base_seq + 2);
    }
    assert(shared_tt_read(&g_entry, cas1 ? 777 : 666, &s1));
    assert(!shared_tt_read(&g_entry, cas1 ? 666 : 777, &s1));
    printf("3. Multi-writer collision CAS mutual exclusion: PASS\n");

    /* 4. Sequence wraparound across UINT64_MAX */
    uint64_t near_wrap = UINT64_MAX - 1; /* even number right before wrap */
    atomic_store(&g_entry.sequence, near_wrap);
    w_ok = shared_tt_write(&g_entry, 555, 0x111, 0x222, 0x333, 0x444);
    assert(w_ok);
    /* after write, sequence wrapped around UINT64_MAX to 1 (odd) then 0 (even) */
    assert(shared_tt_read(&g_entry, 555, &s1));
    assert(s1.data == 0x111 && s1.move_w0 == 0x222);
    printf("4. 64-bit Sequence wraparound across UINT64_MAX: PASS\n");

    /* 5. Multi-threaded high-contention stress test */
    HANDLE writers[NUM_WRITERS];
    HANDLE readers[NUM_READERS];
    atomic_store(&g_start, false);
    for (uint64_t i = 0; i < NUM_WRITERS; ++i) {
        writers[i] = CreateThread(NULL, 0, StressWriterThread, (LPVOID)(uintptr_t)(i + 1), 0, NULL);
    }
    for (uint64_t i = 0; i < NUM_READERS; ++i) {
        readers[i] = CreateThread(NULL, 0, StressReaderThread, (LPVOID)(uintptr_t)(i + 1), 0, NULL);
    }
    atomic_store_explicit(&g_start, true, memory_order_seq_cst);
    WaitForMultipleObjects(NUM_WRITERS, writers, TRUE, INFINITE);
    WaitForMultipleObjects(NUM_READERS, readers, TRUE, INFINITE);
    for (int i = 0; i < NUM_WRITERS; ++i) CloseHandle(writers[i]);
    for (int i = 0; i < NUM_READERS; ++i) CloseHandle(readers[i]);

    printf("5. Multi-threaded race test (%d writers, %d readers, %d iters each):\n", NUM_WRITERS, NUM_READERS, ITERS_PER_THREAD);
    printf("   Writer stores: %llu, skips: %llu\n", (unsigned long long)g_writer_success, (unsigned long long)g_writer_skips);
    printf("   Reader hits: %llu, misses: %llu\n", (unsigned long long)g_reader_hits, (unsigned long long)g_reader_misses);
    printf("   TORN READS OBSERVED: %llu\n", (unsigned long long)g_torn_reads);
    assert(g_torn_reads == 0);
    printf("VERDICT: PASS_PROTOCOL_VERIFIED (0 torn reads, all forced interleavings passed)\n");
    return 0;
}
