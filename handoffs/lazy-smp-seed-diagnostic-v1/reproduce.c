/* Diagnostic only. Production declarations/functions and reader are included
 * verbatim from a verified frozen probe. No worker thread is created. */
#ifdef NDEBUG
#error Assertions must be enabled
#endif
#define main frozen_probe_main
#include FROZEN_PROBE
#undef main
#include <inttypes.h>
#include <string.h>

/* Generated verbatim from frozen main, ending before worker creation. */
static void reproduce_setup(void) {
#include "seed_setup.inc"
}

static void snapshot(const char *phase, bool want_valid) {
    NativeCompactMove got = {0};
    uint32_t depth = UINT32_MAX;
    uint64_t seq_before = atomic_load(&slot.sequence);
    bool hit = shared_move_hint_read(&slot, 123, 7, &got, &depth);
    uint64_t key = atomic_load(&slot.key), data = atomic_load(&slot.data);
    uint64_t w0 = atomic_load(&slot.move_w0), w1 = atomic_load(&slot.move_w1);
    uint64_t w2 = atomic_load(&slot.move_w2);
    uint64_t seq_after = atomic_load(&slot.sequence);
    bool low_ok = got.captured_low == ~got.path_low;
    bool high_ok = got.path_high_meta == (uint32_t)got.path_low;
    bool cap_ok = got.captured_high_meta == ~(uint32_t)got.path_low;
    bool depth_ok = depth == 42;
    /* Hex strings preserve full 64-bit values in JSON consumers. With no
     * writers, surrounding observations are stable, not concurrent resnapshots. */
    printf("{\"phase\":\"%s\",\"threads_created\":0,\"hit\":%s,"
           "\"sequence_before\":\"%016" PRIx64 "\","
           "\"sequence_after\":\"%016" PRIx64 "\","
           "\"key\":\"%016" PRIx64 "\",\"data\":\"%016" PRIx64 "\","
           "\"epoch\":%u,\"flags\":%u,\"depth\":%u,"
           "\"w0\":\"%016" PRIx64 "\",\"w1\":\"%016" PRIx64 "\","
           "\"w2\":\"%016" PRIx64 "\","
           "\"path_low\":\"%016" PRIx64 "\",\"captured_low\":\"%016" PRIx64 "\","
           "\"path_high_meta\":%u,\"captured_high_meta\":%u,"
           "\"low_ok\":%s,\"high_ok\":%s,\"captured_high_ok\":%s,\"depth_ok\":%s}\n",
           phase, hit ? "true" : "false", seq_before, seq_after, key, data,
           (uint32_t)(data >> 32), (uint32_t)((data >> 16) & 65535), depth,
           w0, w1, w2, got.path_low, got.captured_low,
           got.path_high_meta, got.captured_high_meta,
           low_ok ? "true" : "false", high_ok ? "true" : "false",
           cap_ok ? "true" : "false", depth_ok ? "true" : "false");
    fflush(stdout);
    assert(hit && key == 123 && (data >> 32) == 7);
    assert(seq_before == seq_after);
    assert(w0 == got.path_low && w1 == got.captured_low);
    assert(w2 == ((uint64_t)got.path_high_meta |
                   ((uint64_t)got.captured_high_meta << 32)));
    if (!want_valid) {
        assert(seq_before == 0 && data == (UINT64_C(7) << 32));
        assert(w0 == 1 && w1 == 2 && w2 == UINT64_C(0x0000000400000003));
        assert(got.path_high_meta == 3 && got.captured_high_meta == 4 && depth == 0);
        assert(!low_ok && !high_ok && !cap_ok && !depth_ok);
    } else {
        assert(seq_before == 2);
        assert(low_ok && high_ok && cap_ok && depth_ok);
    }
}

int main(int argc, char **argv) {
    assert(argc == 2);
    assert(sizeof(SharedMoveHintEntry) == 48 && sizeof(NativeCompactMove) == 24);
    assert(!shared_move_hint_read(&slot, 123, 7, NULL, NULL));
    reproduce_setup();
    snapshot("seed_before_workers", false);
    bool wrong_key = shared_move_hint_read(&slot, 124, 7, NULL, NULL);
    bool wrong_epoch = shared_move_hint_read(&slot, 123, 8, NULL, NULL);
    printf("{\"phase\":\"namespace_controls\",\"wrong_key_hit\":%s,\"wrong_epoch_hit\":%s}\n",
           wrong_key ? "true" : "false", wrong_epoch ? "true" : "false");
    fflush(stdout);
    assert(!wrong_key && !wrong_epoch);
    if (strcmp(argv[1], "snapshot") == 0) return 0;
    if (strcmp(argv[1], "assert-reader") == 0) {
        atomic_store(&start, true);
        /* Exact original reader executes synchronously before any writer.
         * Expected SIGABRT at the unchanged payload assertion. */
        (void)collide((void *)(uintptr_t)8);
        return 99; /* Unexpectedly surviving is a diagnostic failure. */
    }
    assert(strcmp(argv[1], "valid-control") == 0);
    uint64_t value = (UINT64_C(3) << 32) | 17;
    NativeCompactMove valid = {value, ~value, (uint32_t)value, ~(uint32_t)value};
    assert(shared_move_hint_write(&slot, 123, (UINT64_C(7) << 32) | 42, &valid));
    snapshot("after_one_valid_write", true);
    atomic_store(&start, true);
    (void)collide((void *)(uintptr_t)8);
    assert(atomic_load(&accepted) == 100000);
    printf("{\"phase\":\"valid_reader_completed\",\"accepted\":%u}\n", atomic_load(&accepted));
    return 0;
}
