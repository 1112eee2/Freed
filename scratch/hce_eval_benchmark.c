#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef int (__cdecl *EvaluateFunction)(
    uint32_t,
    uint32_t,
    uint32_t,
    int,
    int,
    int *
);

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

static int parse_u64(const char *text, uint64_t maximum, uint64_t *output) {
    errno = 0;
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value > maximum) return 0;
    *output = (uint64_t)value;
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 8) {
        return fail(
            "usage: hce_eval_benchmark DLL ITERATIONS RED BLACK KINGS TURN CLOCK"
        );
    }
    uint64_t iterations;
    uint64_t red;
    uint64_t black;
    uint64_t kings;
    uint64_t turn;
    uint64_t clock;
    if (
        !parse_u64(argv[2], 1000000000ULL, &iterations) || iterations < 1U ||
        !parse_u64(argv[3], UINT32_MAX, &red) ||
        !parse_u64(argv[4], UINT32_MAX, &black) ||
        !parse_u64(argv[5], UINT32_MAX, &kings) ||
        !parse_u64(argv[6], 2U, &turn) || (turn != 1U && turn != 2U) ||
        !parse_u64(argv[7], 79U, &clock) ||
        (red & black) != 0U || (kings & ~(red | black)) != 0U
    ) {
        return fail("benchmark arguments are invalid");
    }
    HMODULE library = LoadLibraryA(argv[1]);
    if (library == NULL) return fail("unable to load HCE DLL");
    EvaluateFunction evaluate = (EvaluateFunction)(uintptr_t)GetProcAddress(
        library, "makhos_evaluate");
    if (evaluate == NULL) {
        FreeLibrary(library);
        return fail("makhos_evaluate export is missing");
    }

    int score = 0;
    int64_t checksum = 0;
    const uint32_t warmup = 10000U;
    for (uint32_t index = 0U; index < warmup; ++index) {
        if (evaluate(
                (uint32_t)red,
                (uint32_t)black,
                (uint32_t)kings,
                (int)turn,
                (int)clock,
                &score) != 0) {
            FreeLibrary(library);
            return fail("HCE warmup failed");
        }
        checksum += score;
    }

    LARGE_INTEGER frequency;
    LARGE_INTEGER start;
    LARGE_INTEGER finish;
    if (!QueryPerformanceFrequency(&frequency) || !QueryPerformanceCounter(&start)) {
        FreeLibrary(library);
        return fail("performance counter is unavailable");
    }
    for (uint64_t index = 0U; index < iterations; ++index) {
        if (evaluate(
                (uint32_t)red,
                (uint32_t)black,
                (uint32_t)kings,
                (int)turn,
                (int)clock,
                &score) != 0) {
            FreeLibrary(library);
            return fail("HCE benchmark evaluation failed");
        }
        checksum += score;
    }
    if (!QueryPerformanceCounter(&finish)) {
        FreeLibrary(library);
        return fail("performance counter read failed");
    }
    double seconds = (double)(finish.QuadPart - start.QuadPart) /
                     (double)frequency.QuadPart;
    double nanoseconds_per_eval = seconds * 1000000000.0 / (double)iterations;
    double evals_per_second = (double)iterations / seconds;
    printf(
        "{\"iterations\":%" PRIu64 ",\"seconds\":%.9f,"
        "\"ns_per_eval\":%.3f,\"evals_per_second\":%.3f,"
        "\"checksum\":%" PRId64 "}\n",
        iterations,
        seconds,
        nanoseconds_per_eval,
        evals_per_second,
        checksum
    );
    FreeLibrary(library);
    return 0;
}
