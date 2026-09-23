/* Independent pthread smoke: no Makhos publication code or structures.
 *
 * Validates the pthread threading path that the r4 portable harness actually uses,
 * so a sanitizer failure in the r4 probe can be separated from a sanitizer failure
 * in plain thread creation. Compile with and without -fsanitize=thread.
 */
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>

static void *worker(void *argument) {
    *(int *)argument = 42;
    return (void *)(uintptr_t)7;
}

int main(void) {
    pthread_t thread;
    int value = 0;
    void *result = NULL;
    assert(pthread_create(&thread, NULL, worker, &value) == 0);
    assert(pthread_join(thread, &result) == 0);
    assert(value == 42 && result == (void *)(uintptr_t)7);
    puts("pthread_create/join smoke PASS");
    return 0;
}
