/* Exercise the actual implementation, not a separately copied protocol. */
#define _CRT_SECURE_NO_WARNINGS
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

static int allocation_call, fail_allocation, event_call, fail_event, thread_call, fail_thread;
static void *owned[128];
static int owned_count;

static void *checked_calloc(size_t count, size_t size) {
    if (++allocation_call == fail_allocation) return NULL;
    void *p = calloc(count, size);
    if (p != NULL) {
        assert(owned_count < 128);
        owned[owned_count++] = p;
    }
    return p;
}

static void checked_free(void *p) {
    if (p != NULL) {
        for (int i = 0; i < owned_count; ++i) {
            if (owned[i] == p) {
                owned[i] = owned[--owned_count];
                break;
            }
        }
    }
    free(p);
}

static HANDLE checked_event(LPSECURITY_ATTRIBUTES a, BOOL manual, BOOL initial, LPCSTR name) {
    if (++event_call == fail_event) return NULL;
    return CreateEventA(a, manual, initial, name);
}

static HANDLE checked_thread(LPSECURITY_ATTRIBUTES a, SIZE_T stack,
                            LPTHREAD_START_ROUTINE entry, LPVOID arg, DWORD flags, LPDWORD id) {
    if (++thread_call == fail_thread) return NULL;
    return CreateThread(a, stack, entry, arg, flags, id);
}

#define MAKHOS_NO_MAIN 1
#define MAKHOS_NATIVE_LAZY_SMP 1
#define MAKHOS_STRICT_SEARCH_POSITION_KEY 1
#define calloc checked_calloc
#define free checked_free
#define CreateEventA checked_event
#define CreateThread checked_thread
#include "../native/makhos_native.c"
#undef calloc
#undef free
#undef CreateEventA
#undef CreateThread

static SharedMoveHintEntry entry;
static atomic_uint accepted, rejected, torn;
static HANDLE start_stress;

static void reset_entry(void) {
    atomic_store(&entry.sequence, 0);
    atomic_store(&entry.key, 0);
    atomic_store(&entry.data, 0);
    atomic_store(&entry.move_w0, 0);
    atomic_store(&entry.move_w1, 0);
    atomic_store(&entry.move_w2, 0);
}

static DWORD WINAPI stress(void *arg) {
    uintptr_t id = (uintptr_t)arg;
    assert(WaitForSingleObject(start_stress, 10000) == WAIT_OBJECT_0);
    for (uint64_t i = 1; i <= 100000; ++i) {
        if (id < 8) {
            uint64_t value = (id << 32) | i;
            NativeCompactMove move = {value, ~value, (uint32_t)value, ~(uint32_t)value};
            shared_move_hint_write(&entry, 123, (UINT64_C(7) << 32) | 42, &move);
        } else {
            NativeCompactMove move;
            uint32_t depth;
            if (shared_move_hint_read(&entry, 123, 7, &move, &depth)) {
                atomic_fetch_add(&accepted, 1);
                if (move.captured_low != ~move.path_low ||
                    move.path_high_meta != (uint32_t)move.path_low ||
                    move.captured_high_meta != ~(uint32_t)move.path_low || depth != 42) {
                    atomic_fetch_add(&torn, 1);
                }
            } else atomic_fetch_add(&rejected, 1);
        }
    }
    return 0;
}

static void protocol_tests(void) {
    reset_entry();
    assert(atomic_is_lock_free(&entry.sequence));
    assert(atomic_is_lock_free(&entry.key));
    assert(atomic_is_lock_free(&entry.data));
    assert(atomic_is_lock_free(&entry.move_w0));
    assert(atomic_is_lock_free(&entry.move_w1));
    assert(atomic_is_lock_free(&entry.move_w2));
    NativeCompactMove original = {123, 456, 789, 111}, got;
    uint32_t depth;
    assert(!shared_move_hint_read(&entry, 1, 2, &got, &depth));
    assert(shared_move_hint_write(&entry, 1, (UINT64_C(2) << 32) | 99, &original));
    assert(shared_move_hint_read(&entry, 1, 2, &got, &depth));
    assert(memcmp(&got, &original, sizeof(got)) == 0 && depth == 99);
    assert(!shared_move_hint_read(&entry, 3, 2, &got, &depth));
    assert(!shared_move_hint_read(&entry, 1, 3, &got, &depth));
    assert(shared_move_hint_read(&entry, 1, 2, NULL, NULL));

    /* Paused writer: no reader accepts partial payload and competitors skip. */
    atomic_store(&entry.sequence, 3);
    atomic_store(&entry.move_w0, 999);
    assert(!shared_move_hint_read(&entry, 1, 2, &got, &depth));
    assert(!shared_move_hint_write(&entry, 1, 0, &original));
    /* Production declines a store before sequence wrap instead of permitting ABA. */
    atomic_store(&entry.sequence, UINT64_MAX - 1);
    assert(!shared_move_hint_write(&entry, 1, 0, &original));
    assert(atomic_load(&entry.sequence) == UINT64_MAX - 1);
    reset_entry();
    assert(!shared_move_hint_read(&entry, 1, 2, &got, &depth));

    NativeCompactMove seed = {1, ~UINT64_C(1), 1, ~UINT32_C(1)};
    assert(shared_move_hint_write(&entry, 123, (UINT64_C(7) << 32) | 42, &seed));
    start_stress = CreateEventA(NULL, TRUE, FALSE, NULL);
    assert(start_stress != NULL);
    HANDLE threads[12];
    for (uintptr_t i = 0; i < 12; ++i) {
        threads[i] = CreateThread(NULL, 0, stress, (void *)i, 0, NULL);
        assert(threads[i] != NULL);
    }
    assert(SetEvent(start_stress));
    assert(WaitForMultipleObjects(12, threads, TRUE, 30000) == WAIT_OBJECT_0);
    for (int i = 0; i < 12; ++i) assert(CloseHandle(threads[i]));
    assert(CloseHandle(start_stress));
    assert(atomic_load(&accepted) > 0);
    assert(atomic_load(&torn) == 0);
    printf("actual protocol: accepted=%u rejected=%u torn=%u; 1200000 operations PASS\n",
           atomic_load(&accepted), atomic_load(&rejected), atomic_load(&torn));
}

static void construction_failures(void) {
    DWORD handles_before, handles_after;
    assert(GetProcessHandleCount(GetCurrentProcess(), &handles_before));
    /* 4 workers: handle + shared table + 4 private TTs, 6 events, 3 helpers. */
    for (int kind = 0; kind < 3; ++kind) {
        int count = kind == 2 ? 3 : 6;
        for (int at = 1; at <= count; ++at) {
            allocation_call = event_call = thread_call = 0;
            fail_allocation = kind == 0 ? at : 0;
            fail_event = kind == 1 ? at : 0;
            fail_thread = kind == 2 ? at : 0;
            void *handle = makhos_lazy_smp_create_budgeted(4, 18, UINT64_C(16) << 20);
            assert(handle == NULL);
            assert(owned_count == 0);
            assert(GetProcessHandleCount(GetCurrentProcess(), &handles_after));
            assert(handles_before == handles_after);
        }
    }
    fail_allocation = fail_event = fail_thread = 0;
    for (int i = 0; i < 20; ++i) {
        NativeLazySmpHandle *handle = makhos_lazy_smp_create_budgeted(4, 18, UINT64_C(16) << 20);
        assert(handle != NULL);
        assert(makhos_lazy_smp_clear(handle) == 0);
        makhos_lazy_smp_destroy(handle);
        assert(owned_count == 0);
    }
    assert(GetProcessHandleCount(GetCurrentProcess(), &handles_after));
    assert(handles_before == handles_after);
    puts("allocation/event/thread failures and repeated teardown: PASS");
}

int main(void) {
    protocol_tests();
    construction_failures();
    return 0;
}
