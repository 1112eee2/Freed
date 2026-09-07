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
typedef int (__cdecl *UpdateFunction)(
    const void *, void *, int, const uint16_t *, uint32_t,
    const uint16_t *, uint32_t
);
typedef int (__cdecl *EvalFunction)(const void *, const void *, int, int32_t *);

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

int main(int argc, char **argv) {
    if (argc != 12) {
        return fail(
            "usage: nnue_incremental_benchmark DLL MODEL SOURCE_SHA ITERATIONS "
            "RED_FEATURES BLACK_FEATURES RED_REMOVED RED_ADDED "
            "BLACK_REMOVED BLACK_ADDED TURN"
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
    unsigned long turn = strtoul(argv[11], &end, 10);
    if (errno != 0 || end == argv[11] || *end != '\0' || (turn != 1U && turn != 2U)) {
        return fail("turn must be 1 or 2");
    }
    uint8_t source_sha[32];
    uint16_t red_features[MAX_ACTIVE_FEATURES];
    uint16_t black_features[MAX_ACTIVE_FEATURES];
    uint16_t red_removed[MAX_ACTIVE_FEATURES];
    uint16_t red_added[MAX_ACTIVE_FEATURES];
    uint16_t black_removed[MAX_ACTIVE_FEATURES];
    uint16_t black_added[MAX_ACTIVE_FEATURES];
    uint32_t red_count, black_count, red_removed_count, red_added_count;
    uint32_t black_removed_count, black_added_count;
    if (
        !parse_sha256(argv[3], source_sha) ||
        !parse_indices(argv[5], red_features, &red_count) ||
        !parse_indices(argv[6], black_features, &black_count) ||
        !parse_indices(argv[7], red_removed, &red_removed_count) ||
        !parse_indices(argv[8], red_added, &red_added_count) ||
        !parse_indices(argv[9], black_removed, &black_removed_count) ||
        !parse_indices(argv[10], black_added, &black_added_count)
    ) {
        return fail("SHA or feature arguments are invalid");
    }

    HMODULE library = LoadLibraryA(argv[1]);
    if (library == NULL) return fail("unable to load incremental DLL");
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
    LOAD_EXPORT(UpdateFunction, makhos_nnue_incremental_update);
    LOAD_EXPORT(EvalFunction, makhos_nnue_incremental_eval);
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
        makhos_nnue_incremental_update == NULL ||
        makhos_nnue_incremental_eval == NULL
    ) {
        FreeLibrary(library);
        return fail("incremental DLL export is missing");
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
#define REFRESH() makhos_nnue_incremental_refresh( \
    model, accumulator, red_features, red_count, black_features, black_count)
#define UPDATE_RED_FORWARD() makhos_nnue_incremental_update( \
    model, accumulator, 1, red_removed, red_removed_count, red_added, red_added_count)
#define UPDATE_BLACK_FORWARD() makhos_nnue_incremental_update( \
    model, accumulator, 2, black_removed, black_removed_count, black_added, black_added_count)
#define UPDATE_RED_REVERSE() makhos_nnue_incremental_update( \
    model, accumulator, 1, red_added, red_added_count, red_removed, red_removed_count)
#define UPDATE_BLACK_REVERSE() makhos_nnue_incremental_update( \
    model, accumulator, 2, black_added, black_added_count, black_removed, black_removed_count)
    if (!REFRESH()) return fail("initial refresh failed");
    int32_t value = 0;
    int64_t checksum = 0;
    for (uint32_t index = 0U; index < 1000U; ++index) {
        if (
            !UPDATE_RED_FORWARD() || !UPDATE_BLACK_FORWARD() ||
            !makhos_nnue_incremental_eval(model, accumulator, (int)turn, &value) ||
            !UPDATE_BLACK_REVERSE() || !UPDATE_RED_REVERSE()
        ) {
            return fail("incremental warmup failed");
        }
        checksum += value;
    }
    if (!REFRESH()) return fail("post-warmup refresh failed");

    LARGE_INTEGER start, finish;
    QueryPerformanceCounter(&start);
    for (uint64_t index = 0U; index < iterations; ++index) {
        if (!REFRESH()) return fail("refresh benchmark failed");
    }
    QueryPerformanceCounter(&finish);
    double refresh_seconds = elapsed_seconds(start, finish);

    QueryPerformanceCounter(&start);
    for (uint64_t index = 0U; index < iterations; ++index) {
        if (!makhos_nnue_incremental_eval(model, accumulator, (int)turn, &value)) {
            return fail("eval benchmark failed");
        }
        checksum += value;
    }
    QueryPerformanceCounter(&finish);
    double eval_seconds = elapsed_seconds(start, finish);

    QueryPerformanceCounter(&start);
    for (uint64_t index = 0U; index < iterations; ++index) {
        if (
            !UPDATE_RED_FORWARD() || !UPDATE_BLACK_FORWARD() ||
            !UPDATE_BLACK_REVERSE() || !UPDATE_RED_REVERSE()
        ) {
            return fail("update benchmark failed");
        }
    }
    QueryPerformanceCounter(&finish);
    double update_seconds = elapsed_seconds(start, finish);
    if (!makhos_nnue_incremental_eval(model, accumulator, (int)turn, &value)) {
        return fail("final accumulator validation failed");
    }
    checksum += value;
    double refresh_ns = refresh_seconds * 1000000000.0 / (double)iterations;
    double eval_ns = eval_seconds * 1000000000.0 / (double)iterations;
    double update_per_perspective_ns =
        update_seconds * 1000000000.0 / ((double)iterations * 4.0);
    double move_update_ns =
        update_seconds * 1000000000.0 / ((double)iterations * 2.0);
    printf(
        "{\"iterations\":%llu,\"red_count\":%u,\"black_count\":%u,"
        "\"red_removed\":%u,\"red_added\":%u,\"black_removed\":%u,"
        "\"black_added\":%u,\"model_bytes\":%zu,\"accumulator_bytes\":%zu,"
        "\"refresh_ns\":%.3f,\"eval_ns\":%.3f,"
        "\"full_refresh_eval_ns\":%.3f,\"update_per_perspective_ns\":%.3f,"
        "\"move_update_both_perspectives_ns\":%.3f,\"checksum\":%" PRId64 "}\n",
        iterations,
        red_count,
        black_count,
        red_removed_count,
        red_added_count,
        black_removed_count,
        black_added_count,
        makhos_nnue_incremental_model_bytes(),
        makhos_nnue_incremental_accumulator_bytes(),
        refresh_ns,
        eval_ns,
        refresh_ns + eval_ns,
        update_per_perspective_ns,
        move_update_ns,
        checksum
    );
    makhos_nnue_incremental_free_accumulator(accumulator);
    makhos_nnue_incremental_free_model(model);
    FreeLibrary(library);
    return 0;
#undef REFRESH
#undef UPDATE_RED_FORWARD
#undef UPDATE_BLACK_FORWARD
#undef UPDATE_RED_REVERSE
#undef UPDATE_BLACK_REVERSE
}
