#include <threads.h>
#include <assert.h>
#include <stdio.h>
static int worker(void *p) { *(int *)p = 42; return 7; }
int main(void) {
    thrd_t thread; int value = 0, result = 0;
    assert(thrd_create(&thread, worker, &value) == thrd_success);
    assert(thrd_join(thread, &result) == thrd_success);
    assert(value == 42 && result == 7);
    puts("C11 thrd_create/join smoke PASS");
    return 0;
}
