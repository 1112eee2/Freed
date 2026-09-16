#include <threads.h>
#include <stdatomic.h>
#include <assert.h>
#include <stdio.h>
static atomic_int ready;
static atomic_bool start;
static volatile unsigned counter;
static int race(void *p) {
    (void)p;
    atomic_fetch_add(&ready, 1);
    while (!atomic_load(&start)) thrd_yield();
    for (unsigned i = 0; i < 100000; ++i) counter++;
    return 0;
}
int main(void) {
    thrd_t a, b; int result;
    assert(thrd_create(&a, race, NULL) == thrd_success);
    assert(thrd_create(&b, race, NULL) == thrd_success);
    while (atomic_load(&ready) != 2) thrd_yield();
    atomic_store(&start, 1);
    assert(thrd_join(a, &result) == thrd_success);
    assert(thrd_join(b, &result) == thrd_success);
    printf("C11 negative counter=%u\n", counter);
    return 0;
}
