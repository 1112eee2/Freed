#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdatomic.h>
typedef struct {
    uint64_t path_low;
    uint64_t captured_low;
    uint32_t path_high_meta;
    uint32_t captured_high_meta;
} NativeCompactMove;

typedef struct {
    _Atomic uint64_t sequence; /* bit 0 = writer active; bits 1..63 = version */
    _Atomic uint64_t key;      /* strict XOR position key */
    _Atomic uint64_t data;     /* depth (16b), flags (16b), epoch (32b) */
    _Atomic uint64_t move_w0;  /* compact move word 0 (path_low) */
    _Atomic uint64_t move_w1;  /* compact move word 1 (captured_low) */
    _Atomic uint64_t move_w2;  /* compact move word 2 (meta) */
} SharedMoveHintEntry;

static inline bool shared_move_hint_write(
    SharedMoveHintEntry *entry,
    uint64_t key,
    uint64_t data,
    const NativeCompactMove *move
) {
    uint64_t cur_seq = atomic_load_explicit(&entry->sequence, memory_order_seq_cst);
    if ((cur_seq & 1) != 0 || cur_seq >= UINT64_MAX - 4) {
        return false; /* writer active or sequence near exhaustion: bounded store-skip */
    }
    uint64_t expected = cur_seq;
    if (!atomic_compare_exchange_strong_explicit(
        &entry->sequence,
        &expected,
        cur_seq + 1,
        memory_order_seq_cst,
        memory_order_seq_cst
    )) {
        return false; /* CAS lost to another writer: skip store without lock wait */
    }
    uint64_t w0 = move->path_low;
    uint64_t w1 = move->captured_low;
    uint64_t w2 = (uint64_t)move->path_high_meta | ((uint64_t)move->captured_high_meta << 32);

    atomic_store_explicit(&entry->key, key, memory_order_seq_cst);
    atomic_store_explicit(&entry->data, data, memory_order_seq_cst);
    atomic_store_explicit(&entry->move_w0, w0, memory_order_seq_cst);
    atomic_store_explicit(&entry->move_w1, w1, memory_order_seq_cst);
    atomic_store_explicit(&entry->move_w2, w2, memory_order_seq_cst);
    atomic_store_explicit(&entry->sequence, cur_seq + 2, memory_order_seq_cst);
    return true;
}

static inline bool shared_move_hint_read(
    const SharedMoveHintEntry *entry,
    uint64_t expected_key,
    uint32_t expected_epoch,
    NativeCompactMove *out_move,
    uint32_t *out_depth
) {
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
        return false; /* torn read detected: miss */
    }
    uint32_t epoch = (uint32_t)(d >> 32);
    if (expected_epoch != 0 && epoch != expected_epoch) {
        return false; /* stale epoch hint */
    }
    if (out_depth != NULL) {
        *out_depth = (uint32_t)(d & 0xFFFF);
    }
    if (out_move != NULL) {
        out_move->path_low = w0;
        out_move->captured_low = w1;
        out_move->path_high_meta = (uint32_t)(w2 & 0xFFFFFFFF);
        out_move->captured_high_meta = (uint32_t)(w2 >> 32);
    }
    return true;
}
/* Appended to verbatim production declarations by prepare_lazy_smp_race_probe.py. */
#include <assert.h>
#include <stdio.h>
#include <threads.h>

static SharedMoveHintEntry slot;
static atomic_bool start;
static atomic_uint accepted;

static int collide(void *argument) {
    uintptr_t id = (uintptr_t)argument;
    while (!atomic_load(&start)) thrd_yield();
    for (uint64_t i = 1; i <= 100000; ++i) {
        if (id < 8) {
            uint64_t value = (id << 32) | i;
            NativeCompactMove move = {value, ~value, (uint32_t)value, ~(uint32_t)value};
            shared_move_hint_write(&slot, 123, (UINT64_C(7) << 32) | 42, &move);
        } else {
            NativeCompactMove move;
            uint32_t depth;
            if (shared_move_hint_read(&slot, 123, 7, &move, &depth)) {
                assert(move.captured_low == ~move.path_low);
                assert(move.path_high_meta == (uint32_t)move.path_low);
                assert(move.captured_high_meta == ~(uint32_t)move.path_low);
                assert(depth == 42);
                atomic_fetch_add(&accepted, 1);
            }
        }
    }
    return 0;
}

int main(void) {
    _Static_assert(sizeof(SharedMoveHintEntry) == 48, "production entry ABI");
    _Static_assert(sizeof(NativeCompactMove) == 24, "production move ABI");
    NativeCompactMove move = {1, 2, 3, 4};
    assert(shared_move_hint_write(&slot, 123, UINT64_C(7) << 32, &move));
    assert(!shared_move_hint_read(&slot, 124, 7, NULL, NULL));
    assert(!shared_move_hint_read(&slot, 123, 8, NULL, NULL));
    atomic_store(&slot.sequence, 3);
    assert(!shared_move_hint_write(&slot, 123, 0, &move));
    assert(!shared_move_hint_read(&slot, 123, 7, NULL, NULL));
    atomic_store(&slot.sequence, UINT64_MAX - 1);
    assert(!shared_move_hint_write(&slot, 123, 0, &move));
    atomic_store(&slot.sequence, 0);
    thrd_t workers[12];
    for (uintptr_t i = 0; i < 12; ++i)
        assert(thrd_create(&workers[i], collide, (void *)i) == thrd_success);
    atomic_store(&start, true);
    for (int i = 0; i < 12; ++i) {
        int result;
        assert(thrd_join(workers[i], &result) == thrd_success);
        assert(result == 0);
    }
    assert(atomic_load(&accepted) > 0);
    printf("production publication: 1200000 operations PASS; accepted=%u\n", atomic_load(&accepted));
    return 0;
}
