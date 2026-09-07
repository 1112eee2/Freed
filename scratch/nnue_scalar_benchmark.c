#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { MAX_ACTIVE_FEATURES = 17 };

typedef const char *(__cdecl *LastErrorFunction)(void);
typedef size_t (__cdecl *ModelBytesFunction)(void);
typedef void *(__cdecl *LoadFunction)(const char *, const uint8_t *);
typedef void (__cdecl *FreeFunction)(void *);
typedef int (__cdecl *EvalFunction)(
    const void *,
    const uint16_t *,
    uint32_t,
    const uint16_t *,
    uint32_t,
    int32_t *
);

static int hex_nibble(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static int parse_sha256(const char *text, uint8_t output[32]) {
    if (text == NULL || strlen(text) != 64U) return 0;
    for (size_t index = 0; index < 32U; ++index) {
        int high = hex_nibble(text[index * 2U]);
        int low = hex_nibble(text[index * 2U + 1U]);
        if (high < 0 || low < 0) return 0;
        output[index] = (uint8_t)((high << 4) | low);
    }
    return 1;
}

static int parse_indices(
    const char *text,
    uint16_t output[MAX_ACTIVE_FEATURES],
    uint32_t *count
) {
    if (text == NULL || *text == '\0') return 0;
    const char *cursor = text;
    uint32_t length = 0U;
    while (*cursor != '\0') {
        if (length >= MAX_ACTIVE_FEATURES) return 0;
        errno = 0;
        char *end = NULL;
        unsigned long value = strtoul(cursor, &end, 10);
        if (errno != 0 || end == cursor || value >= 137UL) return 0;
        output[length++] = (uint16_t)value;
        if (*end == '\0') break;
        if (*end != ',') return 0;
        cursor = end + 1;
        if (*cursor == '\0') return 0;
    }
    *count = length;
    return length > 0U;
}

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 7) {
        return fail(
            "usage: nnue_scalar_benchmark DLL MODEL SOURCE_SHA ITERATIONS "
            "SIDE_TO_MOVE_CSV OPPONENT_CSV"
        );
    }
    errno = 0;
    char *iterations_end = NULL;
    unsigned long long requested = strtoull(argv[4], &iterations_end, 10);
    if (
        errno != 0 || iterations_end == argv[4] || *iterations_end != '\0' ||
        requested < 1ULL || requested > 100000000ULL
    ) {
        return fail("iterations must be in 1..100000000");
    }
    uint8_t source_sha[32];
    uint16_t first[MAX_ACTIVE_FEATURES];
    uint16_t second[MAX_ACTIVE_FEATURES];
    uint32_t first_count = 0U;
    uint32_t second_count = 0U;
    if (!parse_sha256(argv[3], source_sha)) {
        return fail("source model SHA-256 is invalid");
    }
    if (
        !parse_indices(argv[5], first, &first_count) ||
        !parse_indices(argv[6], second, &second_count)
    ) {
        return fail("feature indices are invalid");
    }

    HMODULE library = LoadLibraryA(argv[1]);
    if (library == NULL) return fail("unable to load scalar DLL");
    LastErrorFunction last_error_function =
        (LastErrorFunction)(uintptr_t)GetProcAddress(
            library, "makhos_nnue_scalar_last_error");
    ModelBytesFunction model_bytes_function =
        (ModelBytesFunction)(uintptr_t)GetProcAddress(
            library, "makhos_nnue_scalar_model_bytes");
    LoadFunction load_function = (LoadFunction)(uintptr_t)GetProcAddress(
        library, "makhos_nnue_scalar_load");
    FreeFunction free_function = (FreeFunction)(uintptr_t)GetProcAddress(
        library, "makhos_nnue_scalar_free");
    EvalFunction eval_function = (EvalFunction)(uintptr_t)GetProcAddress(
        library, "makhos_nnue_scalar_eval");
    if (
        last_error_function == NULL || model_bytes_function == NULL ||
        load_function == NULL || free_function == NULL || eval_function == NULL
    ) {
        FreeLibrary(library);
        return fail("scalar DLL export is missing");
    }

    void *model = load_function(argv[2], source_sha);
    if (model == NULL) {
        const char *message = last_error_function();
        fprintf(stderr, "model load failed: %s\n", message != NULL ? message : "unknown");
        FreeLibrary(library);
        return 1;
    }
    int32_t value = 0;
    int64_t checksum = 0;
    const uint32_t warmup = 10000U;
    for (uint32_t index = 0U; index < warmup; ++index) {
        if (!eval_function(model, first, first_count, second, second_count, &value)) {
            free_function(model);
            FreeLibrary(library);
            return fail("scalar warmup failed");
        }
        checksum += value;
    }

    LARGE_INTEGER frequency;
    LARGE_INTEGER start;
    LARGE_INTEGER finish;
    if (!QueryPerformanceFrequency(&frequency) || !QueryPerformanceCounter(&start)) {
        free_function(model);
        FreeLibrary(library);
        return fail("performance counter is unavailable");
    }
    for (uint64_t index = 0U; index < (uint64_t)requested; ++index) {
        if (!eval_function(model, first, first_count, second, second_count, &value)) {
            free_function(model);
            FreeLibrary(library);
            return fail("scalar benchmark evaluation failed");
        }
        checksum += value;
    }
    if (!QueryPerformanceCounter(&finish)) {
        free_function(model);
        FreeLibrary(library);
        return fail("performance counter read failed");
    }
    double seconds = (double)(finish.QuadPart - start.QuadPart) /
                     (double)frequency.QuadPart;
    double nanoseconds_per_eval = seconds * 1000000000.0 / (double)requested;
    double evals_per_second = (double)requested / seconds;
    printf(
        "{\"iterations\":%llu,\"first_count\":%u,\"second_count\":%u,"
        "\"model_bytes\":%zu,\"seconds\":%.9f,\"ns_per_eval\":%.3f,"
        "\"evals_per_second\":%.3f,\"checksum\":%" PRId64 "}\n",
        requested,
        first_count,
        second_count,
        model_bytes_function(),
        seconds,
        nanoseconds_per_eval,
        evals_per_second,
        checksum
    );
    free_function(model);
    FreeLibrary(library);
    return 0;
}
