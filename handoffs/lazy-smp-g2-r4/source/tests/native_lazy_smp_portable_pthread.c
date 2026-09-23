/* Appended to verbatim production declarations by prepare_lazy_smp_race_probe_r4.py.
 *
 * r4 revision of tests/native_lazy_smp_portable.c. The workload, assertions,
 * atomic types and memory orders are unchanged; only the thread launch/join/yield
 * adapters use pthread instead of C11 threads. Reason: the unchanged r3 C11 probe
 * and a publication-free C11 smoke both abort inside the sanitizer's function-entry
 * handling with a null thread state on the tested Clang/GCC + glibc combinations,
 * while pthread negative controls are correctly instrumented on the same runners.
 * See handoffs/lazy-smp-g2-r3/results/linux-tsan-followup-20260916/
 * HARNESS_REVISION_PROPOSAL.md. r3 stays byte-for-byte frozen.
 */
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>

static SharedMoveHintEntry slot;
static atomic_bool start;
static atomic_uint accepted;

static void *collide(void *argument) {
    uintptr_t id = (uintptr_t)argument;
    while (!atomic_load(&start)) sched_yield();
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
    return NULL;
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
    pthread_t workers[12];
    for (uintptr_t i = 0; i < 12; ++i)
        assert(pthread_create(&workers[i], NULL, collide, (void *)i) == 0);
    atomic_store(&start, true);
    for (int i = 0; i < 12; ++i) {
        void *result = (void *)(uintptr_t)1;
        assert(pthread_join(workers[i], &result) == 0);
        assert(result == NULL);
    }
    assert(atomic_load(&accepted) > 0);
    printf("production publication: 1200000 operations PASS; accepted=%u\n", atomic_load(&accepted));
    return 0;
}
