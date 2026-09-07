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
typedef size_t (__cdecl *BytesFunction)(void);
typedef void *(__cdecl *LoadFunction)(const char *, const uint8_t *);
typedef void (__cdecl *FreeFunction)(void *);
typedef void *(__cdecl *CreateFunction)(void);
typedef int (__cdecl *RefreshFunction)(
    const void *, void *, const uint16_t *, uint32_t,
    const uint16_t *, uint32_t
);
typedef int (__cdecl *EvalFunction)(const void *, const void *, int, int32_t *);
typedef int (__cdecl *SupportFunction)(void);

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

static int hex_nibble(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static int parse_sha256(const char *text, uint8_t output[32]) {
    if (text == NULL || strlen(text) != 64U) return 0;
    for (size_t index = 0U; index < 32U; ++index) {
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

static double elapsed_seconds(LARGE_INTEGER start, LARGE_INTEGER finish) {
    LARGE_INTEGER frequency;
    if (!QueryPerformanceFrequency(&frequency)) return -1.0;
    return (double)(finish.QuadPart - start.QuadPart) /
           (double)frequency.QuadPart;
}

static int measure(
    EvalFunction function,
    const void *model,
    const void *accumulator,
    int turn,
    uint64_t iterations,
    double *elapsed,
    int64_t *checksum
) {
    int32_t value = 0;
    int64_t total = 0;
    LARGE_INTEGER start, finish;
    QueryPerformanceCounter(&start);
    for (uint64_t index = 0U; index < iterations; ++index) {
        if (!function(model, accumulator, turn, &value)) return 0;
        total += value;
    }
    QueryPerformanceCounter(&finish);
    *elapsed = elapsed_seconds(start, finish);
    *checksum = total;
    return *elapsed >= 0.0;
}

int main(int argc, char **argv) {
    if (argc != 9) {
        return fail(
            "usage: nnue_avx2_benchmark DLL MODEL SOURCE_SHA ITERATIONS "
            "RED_FEATURES BLACK_FEATURES TURN scalar-first|avx2-first"
        );
    }
    errno = 0;
    char *end = NULL;
    unsigned long long iterations = strtoull(argv[4], &end, 10);
    if (
        errno != 0 || end == argv[4] || *end != '\0' ||
        iterations < 1ULL || iterations > 100000000ULL
    ) {
        return fail("iterations must be in 1..100000000");
    }
    errno = 0;
    end = NULL;
    unsigned long turn = strtoul(argv[7], &end, 10);
    if (errno != 0 || end == argv[7] || *end != '\0' || (turn != 1U && turn != 2U)) {
        return fail("turn must be 1 or 2");
    }
    int avx2_first = strcmp(argv[8], "avx2-first") == 0;
    if (!avx2_first && strcmp(argv[8], "scalar-first") != 0) {
        return fail("order must be scalar-first or avx2-first");
    }
    uint8_t source_sha[32];
    uint16_t red_features[MAX_ACTIVE_FEATURES];
    uint16_t black_features[MAX_ACTIVE_FEATURES];
    uint32_t red_count, black_count;
    if (
        !parse_sha256(argv[3], source_sha) ||
        !parse_indices(argv[5], red_features, &red_count) ||
        !parse_indices(argv[6], black_features, &black_count)
    ) {
        return fail("SHA or feature arguments are invalid");
    }

    HMODULE library = LoadLibraryA(argv[1]);
    if (library == NULL) return fail("unable to load AVX2 DLL");
#define LOAD_EXPORT(type, name) \
    type name = (type)(uintptr_t)GetProcAddress(library, #name)
    LOAD_EXPORT(LastErrorFunction, makhos_nnue_scalar_last_error);
    LOAD_EXPORT(BytesFunction, makhos_nnue_incremental_model_bytes);
    LOAD_EXPORT(BytesFunction, makhos_nnue_incremental_accumulator_bytes);
    LOAD_EXPORT(LoadFunction, makhos_nnue_incremental_load);
    LOAD_EXPORT(FreeFunction, makhos_nnue_incremental_free_model);
    LOAD_EXPORT(CreateFunction, makhos_nnue_incremental_create_accumulator);
    LOAD_EXPORT(FreeFunction, makhos_nnue_incremental_free_accumulator);
    LOAD_EXPORT(RefreshFunction, makhos_nnue_incremental_refresh);
    LOAD_EXPORT(EvalFunction, makhos_nnue_incremental_eval);
    LOAD_EXPORT(SupportFunction, makhos_nnue_avx2_supported);
    LOAD_EXPORT(EvalFunction, makhos_nnue_avx2_eval);
#undef LOAD_EXPORT
    if (
        makhos_nnue_scalar_last_error == NULL ||
        makhos_nnue_incremental_model_bytes == NULL ||
        makhos_nnue_incremental_accumulator_bytes == NULL ||
        makhos_nnue_incremental_load == NULL ||
        makhos_nnue_incremental_free_model == NULL ||
        makhos_nnue_incremental_create_accumulator == NULL ||
        makhos_nnue_incremental_free_accumulator == NULL ||
        makhos_nnue_incremental_refresh == NULL ||
        makhos_nnue_incremental_eval == NULL ||
        makhos_nnue_avx2_supported == NULL ||
        makhos_nnue_avx2_eval == NULL
    ) {
        FreeLibrary(library);
        return fail("AVX2 DLL export is missing");
    }
    if (!makhos_nnue_avx2_supported()) {
        FreeLibrary(library);
        return fail("AVX2 capability gate rejected this host");
    }
    void *model = makhos_nnue_incremental_load(argv[2], source_sha);
    void *accumulator = makhos_nnue_incremental_create_accumulator();
    if (model == NULL || accumulator == NULL) {
        fprintf(stderr, "load/create failed: %s\n", makhos_nnue_scalar_last_error());
        if (accumulator != NULL) makhos_nnue_incremental_free_accumulator(accumulator);
        if (model != NULL) makhos_nnue_incremental_free_model(model);
        FreeLibrary(library);
        return 1;
    }
    if (!makhos_nnue_incremental_refresh(
            model, accumulator, red_features, red_count,
            black_features, black_count)) {
        return fail("initial refresh failed");
    }
    int32_t scalar_value = 0;
    int32_t avx2_value = 0;
    for (uint32_t index = 0U; index < 1000U; ++index) {
        if (
            !makhos_nnue_incremental_eval(model, accumulator, (int)turn, &scalar_value) ||
            !makhos_nnue_avx2_eval(model, accumulator, (int)turn, &avx2_value) ||
            scalar_value != avx2_value
        ) {
            return fail("scalar/AVX2 warmup parity failed");
        }
    }
    double scalar_seconds = 0.0;
    double avx2_seconds = 0.0;
    int64_t scalar_checksum = 0;
    int64_t avx2_checksum = 0;
    if (avx2_first) {
        if (!measure(makhos_nnue_avx2_eval, model, accumulator, (int)turn,
                     iterations, &avx2_seconds, &avx2_checksum) ||
            !measure(makhos_nnue_incremental_eval, model, accumulator, (int)turn,
                     iterations, &scalar_seconds, &scalar_checksum)) {
            return fail("AVX2-first benchmark failed");
        }
    } else {
        if (!measure(makhos_nnue_incremental_eval, model, accumulator, (int)turn,
                     iterations, &scalar_seconds, &scalar_checksum) ||
            !measure(makhos_nnue_avx2_eval, model, accumulator, (int)turn,
                     iterations, &avx2_seconds, &avx2_checksum)) {
            return fail("scalar-first benchmark failed");
        }
    }
    if (scalar_checksum != avx2_checksum) {
        return fail("scalar/AVX2 benchmark checksum differs");
    }
    double scalar_ns = scalar_seconds * 1000000000.0 / (double)iterations;
    double avx2_ns = avx2_seconds * 1000000000.0 / (double)iterations;
    printf(
        "{\"iterations\":%llu,\"order\":\"%s\",\"red_count\":%u,"
        "\"black_count\":%u,\"model_bytes\":%zu,\"accumulator_bytes\":%zu,"
        "\"scalar_eval_ns\":%.3f,\"avx2_eval_ns\":%.3f,"
        "\"speedup\":%.6f,\"checksum\":%" PRId64 "}\n",
        iterations,
        argv[8],
        red_count,
        black_count,
        makhos_nnue_incremental_model_bytes(),
        makhos_nnue_incremental_accumulator_bytes(),
        scalar_ns,
        avx2_ns,
        scalar_ns / avx2_ns,
        scalar_checksum
    );
    makhos_nnue_incremental_free_accumulator(accumulator);
    makhos_nnue_incremental_free_model(model);
    FreeLibrary(library);
    return 0;
}
