#define WIN32_LEAN_AND_MEAN
#if defined(_WIN32)
#include <windows.h>
#endif
#include <immintrin.h>

#include "makhos_nnue_incremental.c"

#ifndef MAKHOS_NNUE_FORCE_NO_AVX2
#define MAKHOS_NNUE_FORCE_NO_AVX2 0
#endif

#if defined(__clang__) || defined(__GNUC__)
#define MAKHOS_AVX2_TARGET __attribute__((target("avx2")))
#else
#define MAKHOS_AVX2_TARGET
#endif

#if defined(_WIN32) && !defined(PF_AVX2_INSTRUCTIONS_AVAILABLE)
#define PF_AVX2_INSTRUCTIONS_AVAILABLE 40
#endif

static atomic_int cached_avx2_support = 0;

static int detect_avx2_support(void) {
#if MAKHOS_NNUE_FORCE_NO_AVX2
    return 0;
#elif defined(_WIN32)
    return IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE) != 0;
#elif defined(__clang__) || defined(__GNUC__)
    __builtin_cpu_init();
    return __builtin_cpu_supports("avx2") != 0;
#else
    return 0;
#endif
}

static int avx2_supported_cached(void) {
    int state = atomic_load_explicit(&cached_avx2_support, memory_order_relaxed);
    if (state == 0) {
        int detected = detect_avx2_support() ? 2 : 1;
        int expected = 0;
        if (!atomic_compare_exchange_strong_explicit(
                &cached_avx2_support,
                &expected,
                detected,
                memory_order_relaxed,
                memory_order_relaxed)) {
            state = expected;
        } else {
            state = detected;
        }
    }
    return state == 2;
}

static MAKHOS_AVX2_TARGET void activate_accumulator_avx2(
    const int16_t input[FEATURE_WIDTH],
    int8_t output[FEATURE_WIDTH]
) {
    const __m256i zero = _mm256_setzero_si256();
    const __m256i maximum = _mm256_set1_epi32(FEATURE_SCALE);
    const __m256i multiplier = _mm256_set1_epi32(ACTIVATION_SCALE);
    const __m256i rounding = _mm256_set1_epi32(FEATURE_SCALE / 2);
    const __m128i zero128 = _mm_setzero_si128();
    for (size_t column = 0U; column < FEATURE_WIDTH; column += 8U) {
        __m128i encoded = _mm_loadu_si128(
            (const __m128i *)(const void *)(input + column));
        __m256i values = _mm256_cvtepi16_epi32(encoded);
        values = _mm256_max_epi32(values, zero);
        values = _mm256_min_epi32(values, maximum);
        values = _mm256_mullo_epi32(values, multiplier);
        values = _mm256_add_epi32(values, rounding);
        values = _mm256_srli_epi32(values, 11);
        __m128i low = _mm256_castsi256_si128(values);
        __m128i high = _mm256_extracti128_si256(values, 1);
        __m128i packed16 = _mm_packs_epi32(low, high);
        __m128i packed8 = _mm_packus_epi16(packed16, zero128);
        _mm_storel_epi64((__m128i *)(void *)(output + column), packed8);
    }
}

static MAKHOS_AVX2_TARGET int32_t dot_u8_s8_avx2(
    const int8_t *activations,
    const int8_t *weights,
    size_t count
) {
    const __m256i ones = _mm256_set1_epi16(1);
    __m256i sums = _mm256_setzero_si256();
    for (size_t column = 0U; column < count; column += 32U) {
        __m256i input = _mm256_loadu_si256(
            (const __m256i *)(const void *)(activations + column));
        __m256i weight = _mm256_loadu_si256(
            (const __m256i *)(const void *)(weights + column));
        __m256i pair_sums = _mm256_maddubs_epi16(input, weight);
        __m256i group_sums = _mm256_madd_epi16(pair_sums, ones);
        sums = _mm256_add_epi32(sums, group_sums);
    }
    __m128i total = _mm_add_epi32(
        _mm256_castsi256_si128(sums),
        _mm256_extracti128_si256(sums, 1));
    total = _mm_hadd_epi32(total, total);
    total = _mm_hadd_epi32(total, total);
    return _mm_cvtsi128_si32(total);
}

static MAKHOS_AVX2_TARGET int evaluate_accumulator_sums_avx2(
    const MakhosNnueScalar *model,
    const int16_t first[FEATURE_WIDTH],
    const int16_t second[FEATURE_WIDTH],
    int32_t *output_sum
) {
    int8_t features[FEATURE_WIDTH * 2U];
    activate_accumulator_avx2(first, features);
    activate_accumulator_avx2(second, features + FEATURE_WIDTH);
    int8_t hidden[HIDDEN_WIDTH];
    for (size_t row = 0U; row < HIDDEN_WIDTH; ++row) {
        int32_t sum = model->hidden_bias[row] + dot_u8_s8_avx2(
            features,
            model->hidden_weights[row],
            FEATURE_WIDTH * 2U
        );
        hidden[row] = clipped_activation(
            sum,
            ACTIVATION_SCALE * HIDDEN_WEIGHT_SCALE
        );
    }
    *output_sum = model->output_bias + dot_u8_s8_avx2(
        hidden, model->output_weights, HIDDEN_WIDTH);
    return 1;
}

MAKHOS_API int makhos_nnue_avx2_supported(void) {
    last_error[0] = '\0';
    return avx2_supported_cached();
}

MAKHOS_API int makhos_nnue_avx2_eval(
    const void *opaque_model,
    const void *opaque_accumulator,
    int side_to_move,
    int32_t *output_sum
) {
    last_error[0] = '\0';
    if (!avx2_supported_cached()) {
        set_error("AVX2 dense evaluation is unavailable on this host");
        return 0;
    }
    MakhosNnueIncrementalModel *model = checked_model(opaque_model);
    MakhosNnueAccumulator *accumulator = checked_accumulator(
        (void *)(uintptr_t)opaque_accumulator);
    int first = perspective_slot(side_to_move);
    if (model == NULL || accumulator == NULL || first < 0 || output_sum == NULL) {
        if (output_sum == NULL) set_error("AVX2 output is null");
        return 0;
    }
    if (!accumulator->valid || accumulator->model_instance != model->instance) {
        set_error("AVX2 accumulator requires refresh for this model");
        return 0;
    }
    int second = first == 0 ? 1 : 0;
    return evaluate_accumulator_sums_avx2(
        &model->scalar,
        accumulator->sums[first],
        accumulator->sums[second],
        output_sum
    );
}
