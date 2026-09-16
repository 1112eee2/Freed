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
