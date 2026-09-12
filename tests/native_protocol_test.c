#include <stdatomic.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#include <assert.h>

typedef struct {
    _Atomic uint64_t sequence;
    _Atomic uint64_t key;
    _Atomic uint64_t data;
    _Atomic uint64_t move_w0;
    _Atomic uint64_t move_w1;
    _Atomic uint64_t move_w2;
} SharedTTEntry;

_Static_assert(sizeof(SharedTTEntry) == 48, "SharedTTEntry must be exactly 48 bytes");

typedef struct {
    uint64_t key;
    uint64_t data;
    uint64_t move_w0;
    uint64_t move_w1;
    uint64_t move_w2;
} TTReaderSnapshot;

static inline bool shared_tt_write(SharedTTEntry *entry, uint64_t key, uint64_t data, uint64_t w0, uint64_t w1, uint64_t w2) {
    uint64_t cur_seq = atomic_load_explicit(&entry->sequence, memory_order_relaxed);
    if ((cur_seq & 1) != 0) {
        return false; /* writer active: skip store */
    }
    uint64_t expected = cur_seq;
    if (!atomic_compare_exchange_strong_explicit(&entry->sequence, &expected, cur_seq + 1, memory_order_acquire, memory_order_relaxed)) {
        return false; /* CAS lost to another writer: skip store */
    }
    atomic_store_explicit(&entry->key, key, memory_order_relaxed);
    atomic_store_explicit(&entry->data, data, memory_order_relaxed);
    atomic_store_explicit(&entry->move_w0, w0, memory_order_relaxed);
    atomic_store_explicit(&entry->move_w1, w1, memory_order_relaxed);
    atomic_store_explicit(&entry->move_w2, w2, memory_order_relaxed);
    atomic_store_explicit(&entry->sequence, cur_seq + 2, memory_order_release);
    return true;
}

static inline bool shared_tt_read(const SharedTTEntry *entry, uint64_t expected_key, TTReaderSnapshot *out) {
    uint64_t seq1 = atomic_load_explicit(&entry->sequence, memory_order_acquire);
    if ((seq1 & 1) != 0) {
        return false; /* write in progress */
    }
    uint64_t k = atomic_load_explicit(&entry->key, memory_order_relaxed);
    if (k != expected_key) {
        return false; /* key mismatch */
    }
    uint64_t d = atomic_load_explicit(&entry->data, memory_order_relaxed);
    uint64_t w0 = atomic_load_explicit(&entry->move_w0, memory_order_relaxed);
    uint64_t w1 = atomic_load_explicit(&entry->move_w1, memory_order_relaxed);
    uint64_t w2 = atomic_load_explicit(&entry->move_w2, memory_order_relaxed);
    uint64_t seq2 = atomic_load_explicit(&entry->sequence, memory_order_acquire);
    if (seq1 != seq2) {
        return false; /* torn read or intervening write */
    }
    out->key = k;
    out->data = d;
    out->move_w0 = w0;
    out->move_w1 = w1;
    out->move_w2 = w2;
    return true;
}

/* Stress test harness */
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

DWORD WINAPI WriterThread(LPVOID param) {
    uint64_t writer_id = (uint64_t)(uintptr_t)param;
    while (!atomic_load_explicit(&g_start, memory_order_acquire)) {
        YieldProcessor();
    }
    for (uint64_t i = 1; i <= ITERS_PER_THREAD; ++i) {
        uint64_t tag = (writer_id << 48) | i;
        /* In this test, key is 0xCAFEBABE00000000ULL | (i & 3) */
        uint64_t key = 0xCAFEBABE00000000ULL | (i & 3);
        if (shared_tt_write(&g_entry, key, tag, tag ^ 0x1111111111111111ULL, tag ^ 0x2222222222222222ULL, tag ^ 0x3333333333333333ULL)) {
            atomic_fetch_add_explicit(&g_writer_success, 1, memory_order_relaxed);
        } else {
            atomic_fetch_add_explicit(&g_writer_skips, 1, memory_order_relaxed);
        }
    }
    return 0;
}

DWORD WINAPI ReaderThread(LPVOID param) {
    (void)param;
    while (!atomic_load_explicit(&g_start, memory_order_acquire)) {
        YieldProcessor();
    }
    TTReaderSnapshot snap;
    for (uint64_t i = 1; i <= ITERS_PER_THREAD; ++i) {
        uint64_t target_key = 0xCAFEBABE00000000ULL | (i & 3);
        if (shared_tt_read(&g_entry, target_key, &snap)) {
            atomic_fetch_add_explicit(&g_reader_hits, 1, memory_order_relaxed);
            /* Verify snapshot internal coherence */
            uint64_t tag = snap.data;
            if (snap.move_w0 != (tag ^ 0x1111111111111111ULL) ||
                snap.move_w1 != (tag ^ 0x2222222222222222ULL) ||
                snap.move_w2 != (tag ^ 0x3333333333333333ULL)) {
                atomic_fetch_add_explicit(&g_torn_reads, 1, memory_order_relaxed);
            }
        } else {
            atomic_fetch_add_explicit(&g_reader_misses, 1, memory_order_relaxed);
        }
    }
    return 0;
}

int main(void) {
    printf("=== P0-A Shared TT Publication Protocol Harness ===\n");
    printf("Entry size: %zu bytes (lock-free: %d)\n", sizeof(SharedTTEntry), atomic_is_lock_free(&g_entry.sequence));
    assert(sizeof(SharedTTEntry) == 48);
    assert(atomic_is_lock_free(&g_entry.sequence));

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

    /* 2. Paused writer test */
    atomic_store(&g_entry.sequence, 1); /* odd = write in progress */
    assert(!shared_tt_read(&g_entry, 100, &s1)); /* MUST reject with false */
    assert(!shared_tt_write(&g_entry, 200, 0xBBBB, 0x4, 0x5, 0x6)); /* writer MUST skip */
    atomic_store(&g_entry.sequence, 2); /* even again */
    printf("2. Paused writer rejection: PASS\n");

    /* 3. Sequence wraparound test */
    uint64_t near_wrap = UINT64_MAX - 1; /* even number right before wrap */
    atomic_store(&g_entry.sequence, near_wrap);
    w_ok = shared_tt_write(&g_entry, 555, 0x111, 0x222, 0x333, 0x444);
    assert(w_ok);
    /* after write, sequence wrapped around UINT64_MAX to 1 (odd) then 1 (even 0) */
    assert(shared_tt_read(&g_entry, 555, &s1));
    assert(s1.data == 0x111);
    printf("3. Sequence wraparound: PASS\n");

    /* 4. Multi-thread contention stress test */
    HANDLE writers[NUM_WRITERS];
    HANDLE readers[NUM_READERS];
    atomic_store(&g_start, false);
    for (uint64_t i = 0; i < NUM_WRITERS; ++i) {
        writers[i] = CreateThread(NULL, 0, WriterThread, (LPVOID)(uintptr_t)(i + 1), 0, NULL);
    }
    for (uint64_t i = 0; i < NUM_READERS; ++i) {
        readers[i] = CreateThread(NULL, 0, ReaderThread, (LPVOID)(uintptr_t)(i + 1), 0, NULL);
    }
    atomic_store_explicit(&g_start, true, memory_order_release);
    WaitForMultipleObjects(NUM_WRITERS, writers, TRUE, INFINITE);
    WaitForMultipleObjects(NUM_READERS, readers, TRUE, INFINITE);
    for (int i = 0; i < NUM_WRITERS; ++i) CloseHandle(writers[i]);
    for (int i = 0; i < NUM_READERS; ++i) CloseHandle(readers[i]);

    printf("4. Multi-thread race results (%d writers, %d readers, %d iters each):\n", NUM_WRITERS, NUM_READERS, ITERS_PER_THREAD);
    printf("   Writer stores: %llu, skips: %llu\n", (unsigned long long)g_writer_success, (unsigned long long)g_writer_skips);
    printf("   Reader hits: %llu, misses: %llu\n", (unsigned long long)g_reader_hits, (unsigned long long)g_reader_misses);
    printf("   TORN READS OBSERVED: %llu\n", (unsigned long long)g_torn_reads);
    assert(g_torn_reads == 0);
    printf("VERDICT: PASS_PROTOCOL_VERIFIED (0 torn reads)\n");
    return 0;
}
