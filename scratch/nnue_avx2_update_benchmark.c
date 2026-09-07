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
typedef int (__cdecl *SupportFunction)(void);

typedef struct {
    HMODULE module;
    LastErrorFunction last_error;
    LoadFunction load;
    FreeFunction free_model;
    CreateFunction create_accumulator;
    FreeFunction free_accumulator;
    RefreshFunction refresh;
    UpdateFunction scalar_update;
    UpdateFunction avx2_update;
    EvalFunction eval;
    SupportFunction avx2_supported;
} Api;

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

static int load_api(const char *path, int require_avx2, Api *api) {
    memset(api, 0, sizeof(*api));
    api->module = LoadLibraryA(path);
    if (api->module == NULL) return 0;
#define LOAD_FIELD(field, type, symbol) \
    api->field = (type)(uintptr_t)GetProcAddress(api->module, symbol)
    LOAD_FIELD(last_error, LastErrorFunction, "makhos_nnue_scalar_last_error");
    LOAD_FIELD(load, LoadFunction, "makhos_nnue_incremental_load");
    LOAD_FIELD(free_model, FreeFunction, "makhos_nnue_incremental_free_model");
    LOAD_FIELD(create_accumulator, CreateFunction, "makhos_nnue_incremental_create_accumulator");
    LOAD_FIELD(free_accumulator, FreeFunction, "makhos_nnue_incremental_free_accumulator");
    LOAD_FIELD(refresh, RefreshFunction, "makhos_nnue_incremental_refresh");
    LOAD_FIELD(scalar_update, UpdateFunction, "makhos_nnue_incremental_update");
    LOAD_FIELD(eval, EvalFunction, "makhos_nnue_incremental_eval");
    if (require_avx2) {
        LOAD_FIELD(avx2_update, UpdateFunction, "makhos_nnue_avx2_update");
        LOAD_FIELD(avx2_supported, SupportFunction, "makhos_nnue_avx2_supported");
    }
#undef LOAD_FIELD
    if (
        api->last_error == NULL || api->load == NULL || api->free_model == NULL ||
        api->create_accumulator == NULL || api->free_accumulator == NULL ||
        api->refresh == NULL || api->scalar_update == NULL || api->eval == NULL ||
        (require_avx2 && (api->avx2_update == NULL || api->avx2_supported == NULL))
    ) {
        FreeLibrary(api->module);
        memset(api, 0, sizeof(*api));
        return 0;
    }
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

static int update_cycle(
    UpdateFunction update,
    const void *model,
    void *accumulator,
    const uint16_t *red_removed,
    uint32_t red_removed_count,
    const uint16_t *red_added,
    uint32_t red_added_count,
    const uint16_t *black_removed,
    uint32_t black_removed_count,
    const uint16_t *black_added,
    uint32_t black_added_count
) {
    return
        update(model, accumulator, 1, red_removed, red_removed_count,
               red_added, red_added_count) &&
        update(model, accumulator, 2, black_removed, black_removed_count,
               black_added, black_added_count) &&
        update(model, accumulator, 2, black_added, black_added_count,
               black_removed, black_removed_count) &&
        update(model, accumulator, 1, red_added, red_added_count,
               red_removed, red_removed_count);
}

static double elapsed_seconds(LARGE_INTEGER start, LARGE_INTEGER finish) {
    LARGE_INTEGER frequency;
    if (!QueryPerformanceFrequency(&frequency)) return -1.0;
    return (double)(finish.QuadPart - start.QuadPart) /
           (double)frequency.QuadPart;
}

static int measure_updates(
    UpdateFunction update,
    const void *model,
    void *accumulator,
    uint64_t iterations,
    const uint16_t *red_removed,
    uint32_t red_removed_count,
    const uint16_t *red_added,
    uint32_t red_added_count,
    const uint16_t *black_removed,
    uint32_t black_removed_count,
    const uint16_t *black_added,
    uint32_t black_added_count,
    double *elapsed
) {
    LARGE_INTEGER start, finish;
    QueryPerformanceCounter(&start);
    for (uint64_t index = 0U; index < iterations; ++index) {
        if (!update_cycle(
                update, model, accumulator,
                red_removed, red_removed_count, red_added, red_added_count,
                black_removed, black_removed_count, black_added, black_added_count)) {
            return 0;
        }
    }
    QueryPerformanceCounter(&finish);
    *elapsed = elapsed_seconds(start, finish);
    return *elapsed >= 0.0;
}

int main(int argc, char **argv) {
    if (argc != 14) {
        return fail(
            "usage: nnue_avx2_update_benchmark SCALAR_DLL AVX2_DLL MODEL "
            "SOURCE_SHA ITERATIONS RED_FEATURES BLACK_FEATURES RED_REMOVED "
            "RED_ADDED BLACK_REMOVED BLACK_ADDED TURN scalar-first|avx2-first"
        );
    }
    errno = 0;
    char *end = NULL;
    unsigned long long iterations = strtoull(argv[5], &end, 10);
    if (errno != 0 || end == argv[5] || *end != '\0' || iterations < 1ULL) {
        return fail("iterations are invalid");
    }
    errno = 0;
    end = NULL;
    unsigned long turn = strtoul(argv[12], &end, 10);
    if (errno != 0 || end == argv[12] || *end != '\0' || (turn != 1U && turn != 2U)) {
        return fail("turn must be 1 or 2");
    }
    int avx2_first = strcmp(argv[13], "avx2-first") == 0;
    if (!avx2_first && strcmp(argv[13], "scalar-first") != 0) {
        return fail("order is invalid");
    }
    uint8_t source_sha[32];
    uint16_t red_features[MAX_ACTIVE_FEATURES], black_features[MAX_ACTIVE_FEATURES];
    uint16_t red_removed[MAX_ACTIVE_FEATURES], red_added[MAX_ACTIVE_FEATURES];
    uint16_t black_removed[MAX_ACTIVE_FEATURES], black_added[MAX_ACTIVE_FEATURES];
    uint32_t red_count, black_count, rr_count, ra_count, br_count, ba_count;
    if (
        !parse_sha256(argv[4], source_sha) ||
        !parse_indices(argv[6], red_features, &red_count) ||
        !parse_indices(argv[7], black_features, &black_count) ||
        !parse_indices(argv[8], red_removed, &rr_count) ||
        !parse_indices(argv[9], red_added, &ra_count) ||
        !parse_indices(argv[10], black_removed, &br_count) ||
        !parse_indices(argv[11], black_added, &ba_count)
    ) {
        return fail("SHA or feature arguments are invalid");
    }

    Api scalar_api, avx2_api;
    if (!load_api(argv[1], 0, &scalar_api) || !load_api(argv[2], 1, &avx2_api)) {
        return fail("required DLL export is missing");
    }
    if (!avx2_api.avx2_supported()) return fail("AVX2 capability gate rejected host");
    void *scalar_model = scalar_api.load(argv[3], source_sha);
    void *avx2_model = avx2_api.load(argv[3], source_sha);
    void *scalar_accumulator = scalar_api.create_accumulator();
    void *avx2_accumulator = avx2_api.create_accumulator();
    if (
        scalar_model == NULL || avx2_model == NULL ||
        scalar_accumulator == NULL || avx2_accumulator == NULL
    ) {
        return fail("model or accumulator creation failed");
    }
    if (
        !scalar_api.refresh(scalar_model, scalar_accumulator,
                            red_features, red_count, black_features, black_count) ||
        !avx2_api.refresh(avx2_model, avx2_accumulator,
                          red_features, red_count, black_features, black_count)
    ) {
        return fail("initial refresh failed");
    }
    for (uint32_t index = 0U; index < 1000U; ++index) {
        if (
            !update_cycle(scalar_api.scalar_update, scalar_model, scalar_accumulator,
                          red_removed, rr_count, red_added, ra_count,
                          black_removed, br_count, black_added, ba_count) ||
            !update_cycle(avx2_api.avx2_update, avx2_model, avx2_accumulator,
                          red_removed, rr_count, red_added, ra_count,
                          black_removed, br_count, black_added, ba_count)
        ) {
            return fail("update warmup failed");
        }
    }
    double scalar_seconds = 0.0, avx2_seconds = 0.0;
    if (avx2_first) {
        if (!measure_updates(avx2_api.avx2_update, avx2_model, avx2_accumulator,
                             iterations, red_removed, rr_count, red_added, ra_count,
                             black_removed, br_count, black_added, ba_count, &avx2_seconds) ||
            !measure_updates(scalar_api.scalar_update, scalar_model, scalar_accumulator,
                             iterations, red_removed, rr_count, red_added, ra_count,
                             black_removed, br_count, black_added, ba_count, &scalar_seconds)) {
            return fail("AVX2-first update benchmark failed");
        }
    } else {
        if (!measure_updates(scalar_api.scalar_update, scalar_model, scalar_accumulator,
                             iterations, red_removed, rr_count, red_added, ra_count,
                             black_removed, br_count, black_added, ba_count, &scalar_seconds) ||
            !measure_updates(avx2_api.avx2_update, avx2_model, avx2_accumulator,
                             iterations, red_removed, rr_count, red_added, ra_count,
                             black_removed, br_count, black_added, ba_count, &avx2_seconds)) {
            return fail("scalar-first update benchmark failed");
        }
    }
    int32_t scalar_value = 0, avx2_value = 0;
    if (
        !scalar_api.eval(scalar_model, scalar_accumulator, (int)turn, &scalar_value) ||
        !avx2_api.eval(avx2_model, avx2_accumulator, (int)turn, &avx2_value) ||
        scalar_value != avx2_value
    ) {
        return fail("post-benchmark accumulator parity failed");
    }
    double scalar_ns = scalar_seconds * 1000000000.0 / ((double)iterations * 2.0);
    double avx2_ns = avx2_seconds * 1000000000.0 / ((double)iterations * 2.0);
    printf(
        "{\"iterations\":%llu,\"order\":\"%s\",\"red_removed\":%u,"
        "\"red_added\":%u,\"black_removed\":%u,\"black_added\":%u,"
        "\"scalar_move_update_ns\":%.3f,\"avx2_move_update_ns\":%.3f,"
        "\"speedup\":%.6f,\"checksum\":%d}\n",
        iterations, argv[13], rr_count, ra_count, br_count, ba_count,
        scalar_ns, avx2_ns, scalar_ns / avx2_ns, scalar_value
    );
    scalar_api.free_accumulator(scalar_accumulator);
    scalar_api.free_model(scalar_model);
    avx2_api.free_accumulator(avx2_accumulator);
    avx2_api.free_model(avx2_model);
    FreeLibrary(scalar_api.module);
    FreeLibrary(avx2_api.module);
    return 0;
}
