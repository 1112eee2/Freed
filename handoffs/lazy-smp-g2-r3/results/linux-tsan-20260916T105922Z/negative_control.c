#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>
#include <stdio.h>

static atomic_int ready;
static atomic_bool start;
static volatile unsigned counter;

static void *race(void *unused) {
    (void)unused;
    atomic_fetch_add(&ready, 1);
    while (!atomic_load(&start)) { }
    for (unsigned i = 0; i < 100000; ++i) counter++;
    return NULL;
}

int main(void) {
    pthread_t a, b;
    assert(pthread_create(&a, NULL, race, NULL) == 0);
    assert(pthread_create(&b, NULL, race, NULL) == 0);
    while (atomic_load(&ready) != 2) { }
    atomic_store(&start, 1);
    assert(pthread_join(a, NULL) == 0);
    assert(pthread_join(b, NULL) == 0);
    printf("negative control counter=%u\n", counter);
    return 0;
}
