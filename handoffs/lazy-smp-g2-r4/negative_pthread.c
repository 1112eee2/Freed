/* Deliberately racy pthread negative control for the r4 race-detector run.
 *
 * No Makhos code. Two threads increment a non-atomic counter concurrently, so a
 * working ThreadSanitizer must emit a genuine data-race report. A nonzero exit
 * alone is not accepted as calibration: the runner must confirm the report text.
 * The r3 run used a C11 control that never produced a usable report.
 */
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>

static atomic_int ready;
static atomic_bool start;
static volatile unsigned counter;

static void *race(void *argument) {
    (void)argument;
    atomic_fetch_add(&ready, 1);
    while (!atomic_load(&start)) sched_yield();
    for (unsigned i = 0; i < 100000; ++i) counter++;
    return NULL;
}

int main(void) {
    pthread_t a, b;
    assert(pthread_create(&a, NULL, race, NULL) == 0);
    assert(pthread_create(&b, NULL, race, NULL) == 0);
    while (atomic_load(&ready) != 2) sched_yield();
    atomic_store(&start, 1);
    assert(pthread_join(a, NULL) == 0);
    assert(pthread_join(b, NULL) == 0);
    printf("pthread negative counter=%u\n", counter);
    return 0;
}
