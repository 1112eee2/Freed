#include "makhos_nnue_avx2.c"

static MAKHOS_AVX2_TARGET int update_accumulator_sums_avx2(
    const MakhosNnueScalar *model,
    const int16_t current[FEATURE_WIDTH],
    const uint16_t *removed,
    uint32_t removed_count,
    const uint16_t *added,
    uint32_t added_count,
    int16_t output[FEATURE_WIDTH]
) {
    const __m256i maximum = _mm256_set1_epi32(INT16_MAX);
    const __m256i minimum = _mm256_set1_epi32(INT16_MIN);
    for (size_t column = 0U; column < FEATURE_WIDTH; column += 8U) {
        __m128i encoded = _mm_loadu_si128(
            (const __m128i *)(const void *)(current + column));
        __m256i sums = _mm256_cvtepi16_epi32(encoded);
        for (uint32_t index = 0U; index < removed_count; ++index) {
            __m128i weight = _mm_loadu_si128(
                (const __m128i *)(const void *)(
                    model->feature_weights[removed[index]] + column));
            sums = _mm256_sub_epi32(sums, _mm256_cvtepi16_epi32(weight));
        }
        for (uint32_t index = 0U; index < added_count; ++index) {
            __m128i weight = _mm_loadu_si128(
                (const __m128i *)(const void *)(
                    model->feature_weights[added[index]] + column));
            sums = _mm256_add_epi32(sums, _mm256_cvtepi16_epi32(weight));
        }
        __m256i above = _mm256_cmpgt_epi32(sums, maximum);
        __m256i below = _mm256_cmpgt_epi32(minimum, sums);
        if (_mm256_movemask_epi8(_mm256_or_si256(above, below)) != 0) {
            set_error("AVX2 incremental feature update overflow");
            return 0;
        }
        __m128i packed = _mm_packs_epi32(
            _mm256_castsi256_si128(sums),
            _mm256_extracti128_si256(sums, 1));
        _mm_storeu_si128((__m128i *)(void *)(output + column), packed);
    }
    return 1;
}

MAKHOS_API int makhos_nnue_avx2_update(
    const void *opaque_model,
    void *opaque_accumulator,
    int perspective,
    const uint16_t *removed,
    uint32_t removed_count,
    const uint16_t *added,
    uint32_t added_count
) {
    last_error[0] = '\0';
    if (!avx2_supported_cached()) {
        set_error("AVX2 accumulator update is unavailable on this host");
        return 0;
    }
    MakhosNnueIncrementalModel *model = checked_model(opaque_model);
    MakhosNnueAccumulator *accumulator =
        checked_accumulator(opaque_accumulator);
    int slot = perspective_slot(perspective);
    if (model == NULL || accumulator == NULL || slot < 0) return 0;
    if (!accumulator->valid || accumulator->model_instance != model->instance) {
        set_error("AVX2 accumulator requires refresh for this model");
        return 0;
    }
    if (!validate_delta_indices(removed, removed_count) ||
        !validate_delta_indices(added, added_count)) {
        return 0;
    }
    for (uint32_t index = 0U; index < removed_count; ++index) {
        if (!active_contains(accumulator, slot, removed[index])) {
            set_error("AVX2 removed feature is not active");
            return 0;
        }
        for (uint32_t added_index = 0U; added_index < added_count; ++added_index) {
            if (removed[index] == added[added_index]) {
                set_error("AVX2 feature cannot be both removed and added");
                return 0;
            }
        }
    }
    for (uint32_t index = 0U; index < added_count; ++index) {
        if (active_contains(accumulator, slot, added[index])) {
            set_error("AVX2 added feature is already active");
            return 0;
        }
    }
    int16_t sums[FEATURE_WIDTH];
    if (!update_accumulator_sums_avx2(
            &model->scalar,
            accumulator->sums[slot],
            removed,
            removed_count,
            added,
            added_count,
            sums)) {
        return 0;
    }
    memcpy(accumulator->sums[slot], sums, sizeof(sums));
    for (uint32_t index = 0U; index < removed_count; ++index) {
        active_remove(accumulator, slot, removed[index]);
    }
    for (uint32_t index = 0U; index < added_count; ++index) {
        active_add(accumulator, slot, added[index]);
    }
    return 1;
}
