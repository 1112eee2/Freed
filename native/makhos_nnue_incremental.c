#include <stdatomic.h>

#include "makhos_nnue_scalar.c"

enum {
    RED_PERSPECTIVE = 1,
    BLACK_PERSPECTIVE = 2,
    ACTIVE_WORDS = (INPUT_DIMENSIONS + 63) / 64
};

static const uint64_t INCREMENTAL_MODEL_MAGIC = UINT64_C(0x4D4B4E4E5545494D);
static const uint64_t INCREMENTAL_ACCUMULATOR_MAGIC = UINT64_C(0x4D4B4E4E55454143);
static atomic_uint_fast64_t next_model_instance = 1;

typedef struct {
    uint64_t magic;
    uint64_t instance;
    MakhosNnueScalar scalar;
} MakhosNnueIncrementalModel;

typedef struct {
    uint64_t magic;
    uint64_t model_instance;
    int16_t sums[2][FEATURE_WIDTH];
    uint64_t active[2][ACTIVE_WORDS];
    uint8_t valid;
} MakhosNnueAccumulator;

static int perspective_slot(int perspective) {
    if (perspective == RED_PERSPECTIVE) return 0;
    if (perspective == BLACK_PERSPECTIVE) return 1;
    set_error("incremental perspective is invalid");
    return -1;
}

static MakhosNnueIncrementalModel *checked_model(const void *opaque_model) {
    if (opaque_model == NULL) {
        set_error("incremental model is null");
        return NULL;
    }
    MakhosNnueIncrementalModel *model =
        (MakhosNnueIncrementalModel *)(uintptr_t)opaque_model;
    if (model->magic != INCREMENTAL_MODEL_MAGIC || model->instance == 0U) {
        set_error("incremental model identity is invalid");
        return NULL;
    }
    return model;
}

static MakhosNnueAccumulator *checked_accumulator(void *opaque_accumulator) {
    if (opaque_accumulator == NULL) {
        set_error("incremental accumulator is null");
        return NULL;
    }
    MakhosNnueAccumulator *accumulator =
        (MakhosNnueAccumulator *)opaque_accumulator;
    if (accumulator->magic != INCREMENTAL_ACCUMULATOR_MAGIC) {
        set_error("incremental accumulator identity is invalid");
        return NULL;
    }
    return accumulator;
}

static int active_contains(
    const MakhosNnueAccumulator *accumulator,
    int slot,
    uint16_t index
) {
    uint64_t mask = UINT64_C(1) << (index % 64U);
    return (accumulator->active[slot][index / 64U] & mask) != 0U;
}

static void active_add(
    MakhosNnueAccumulator *accumulator,
    int slot,
    uint16_t index
) {
    accumulator->active[slot][index / 64U] |=
        UINT64_C(1) << (index % 64U);
}

static void active_remove(
    MakhosNnueAccumulator *accumulator,
    int slot,
    uint16_t index
) {
    accumulator->active[slot][index / 64U] &=
        ~(UINT64_C(1) << (index % 64U));
}

static int validate_delta_indices(const uint16_t *indices, uint32_t count) {
    if (count > MAX_ACTIVE_FEATURES || (count > 0U && indices == NULL)) {
        set_error("incremental delta feature count is invalid");
        return 0;
    }
    for (uint32_t index = 0U; index < count; ++index) {
        if (indices[index] >= INPUT_DIMENSIONS) {
            set_error("incremental delta feature index is out of range");
            return 0;
        }
        for (uint32_t previous = 0U; previous < index; ++previous) {
            if (indices[previous] == indices[index]) {
                set_error("incremental delta feature index is duplicated");
                return 0;
            }
        }
    }
    return 1;
}

static int refresh_raw(
    const MakhosNnueScalar *model,
    const uint16_t *indices,
    uint32_t count,
    int16_t output[FEATURE_WIDTH]
) {
    if (!validate_indices(indices, count)) return 0;
    for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
        int32_t sum = model->feature_bias[column];
        for (uint32_t index = 0U; index < count; ++index) {
            sum += model->feature_weights[indices[index]][column];
        }
        if (sum < INT16_MIN || sum > INT16_MAX) {
            set_error("incremental feature accumulator overflow");
            return 0;
        }
        output[column] = (int16_t)sum;
    }
    return 1;
}

static int evaluate_accumulator_sums(
    const MakhosNnueScalar *model,
    const int16_t first[FEATURE_WIDTH],
    const int16_t second[FEATURE_WIDTH],
    int32_t *output_sum
) {
    int8_t features[FEATURE_WIDTH * 2U];
    for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
        features[column] = clipped_activation(first[column], FEATURE_SCALE);
        features[FEATURE_WIDTH + column] =
            clipped_activation(second[column], FEATURE_SCALE);
    }
    int8_t hidden[HIDDEN_WIDTH];
    for (size_t row = 0; row < HIDDEN_WIDTH; ++row) {
        int64_t sum = model->hidden_bias[row];
        for (size_t column = 0; column < FEATURE_WIDTH * 2U; ++column) {
            sum += (int32_t)model->hidden_weights[row][column] * features[column];
        }
        if (sum < INT32_MIN || sum > INT32_MAX) {
            set_error("incremental hidden dense sum overflow");
            return 0;
        }
        hidden[row] = clipped_activation(
            (int32_t)sum,
            ACTIVATION_SCALE * HIDDEN_WEIGHT_SCALE
        );
    }
    int64_t sum = model->output_bias;
    for (size_t column = 0; column < HIDDEN_WIDTH; ++column) {
        sum += (int32_t)model->output_weights[column] * hidden[column];
    }
    if (sum < INT32_MIN || sum > INT32_MAX) {
        set_error("incremental output dense sum overflow");
        return 0;
    }
    *output_sum = (int32_t)sum;
    return 1;
}

MAKHOS_API size_t makhos_nnue_incremental_model_bytes(void) {
    return sizeof(MakhosNnueIncrementalModel);
}

MAKHOS_API size_t makhos_nnue_incremental_accumulator_bytes(void) {
    return sizeof(MakhosNnueAccumulator);
}

MAKHOS_API void *makhos_nnue_incremental_load(
    const char *path,
    const uint8_t expected_source_model_sha256[32]
) {
    last_error[0] = '\0';
    MakhosNnueScalar *scalar = (MakhosNnueScalar *)makhos_nnue_scalar_load(
        path, expected_source_model_sha256);
    if (scalar == NULL) return NULL;
    MakhosNnueIncrementalModel *model =
        (MakhosNnueIncrementalModel *)malloc(sizeof(*model));
    if (model == NULL) {
        makhos_nnue_scalar_free(scalar);
        set_error("incremental model allocation failed");
        return NULL;
    }
    uint64_t instance = atomic_fetch_add_explicit(
        &next_model_instance, 1U, memory_order_relaxed);
    if (instance == 0U) {
        makhos_nnue_scalar_free(scalar);
        free(model);
        set_error("incremental model instance counter exhausted");
        return NULL;
    }
    model->magic = INCREMENTAL_MODEL_MAGIC;
    model->instance = instance;
    memcpy(&model->scalar, scalar, sizeof(model->scalar));
    makhos_nnue_scalar_free(scalar);
    return model;
}

MAKHOS_API void makhos_nnue_incremental_free_model(void *opaque_model) {
    if (opaque_model == NULL) return;
    MakhosNnueIncrementalModel *model =
        (MakhosNnueIncrementalModel *)opaque_model;
    if (model->magic == INCREMENTAL_MODEL_MAGIC) {
        memset(model, 0, sizeof(*model));
    }
    free(model);
}

MAKHOS_API void *makhos_nnue_incremental_create_accumulator(void) {
    last_error[0] = '\0';
    MakhosNnueAccumulator *accumulator =
        (MakhosNnueAccumulator *)calloc(1U, sizeof(*accumulator));
    if (accumulator == NULL) {
        set_error("incremental accumulator allocation failed");
        return NULL;
    }
    accumulator->magic = INCREMENTAL_ACCUMULATOR_MAGIC;
    return accumulator;
}

MAKHOS_API void makhos_nnue_incremental_free_accumulator(
    void *opaque_accumulator
) {
    if (opaque_accumulator == NULL) return;
    MakhosNnueAccumulator *accumulator =
        (MakhosNnueAccumulator *)opaque_accumulator;
    if (accumulator->magic == INCREMENTAL_ACCUMULATOR_MAGIC) {
        memset(accumulator, 0, sizeof(*accumulator));
    }
    free(accumulator);
}

MAKHOS_API int makhos_nnue_incremental_refresh(
    const void *opaque_model,
    void *opaque_accumulator,
    const uint16_t *red_indices,
    uint32_t red_count,
    const uint16_t *black_indices,
    uint32_t black_count
) {
    last_error[0] = '\0';
    MakhosNnueIncrementalModel *model = checked_model(opaque_model);
    MakhosNnueAccumulator *accumulator =
        checked_accumulator(opaque_accumulator);
    if (model == NULL || accumulator == NULL) return 0;
    MakhosNnueAccumulator candidate;
    memset(&candidate, 0, sizeof(candidate));
    candidate.magic = INCREMENTAL_ACCUMULATOR_MAGIC;
    candidate.model_instance = model->instance;
    if (!refresh_raw(
            &model->scalar, red_indices, red_count, candidate.sums[0]) ||
        !refresh_raw(
            &model->scalar, black_indices, black_count, candidate.sums[1])) {
        return 0;
    }
    for (uint32_t index = 0U; index < red_count; ++index) {
        active_add(&candidate, 0, red_indices[index]);
    }
    for (uint32_t index = 0U; index < black_count; ++index) {
        active_add(&candidate, 1, black_indices[index]);
    }
    candidate.valid = 1U;
    *accumulator = candidate;
    return 1;
}

MAKHOS_API int makhos_nnue_incremental_update(
    const void *opaque_model,
    void *opaque_accumulator,
    int perspective,
    const uint16_t *removed,
    uint32_t removed_count,
    const uint16_t *added,
    uint32_t added_count
) {
    last_error[0] = '\0';
    MakhosNnueIncrementalModel *model = checked_model(opaque_model);
    MakhosNnueAccumulator *accumulator =
        checked_accumulator(opaque_accumulator);
    int slot = perspective_slot(perspective);
    if (model == NULL || accumulator == NULL || slot < 0) return 0;
    if (!accumulator->valid || accumulator->model_instance != model->instance) {
        set_error("incremental accumulator requires refresh for this model");
        return 0;
    }
    if (!validate_delta_indices(removed, removed_count) ||
        !validate_delta_indices(added, added_count)) {
        return 0;
    }
    for (uint32_t index = 0U; index < removed_count; ++index) {
        if (!active_contains(accumulator, slot, removed[index])) {
            set_error("incremental removed feature is not active");
            return 0;
        }
        for (uint32_t added_index = 0U; added_index < added_count; ++added_index) {
            if (removed[index] == added[added_index]) {
                set_error("incremental feature cannot be both removed and added");
                return 0;
            }
        }
    }
    for (uint32_t index = 0U; index < added_count; ++index) {
        if (active_contains(accumulator, slot, added[index])) {
            set_error("incremental added feature is already active");
            return 0;
        }
    }
    int16_t sums[FEATURE_WIDTH];
    for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
        int32_t sum = accumulator->sums[slot][column];
        for (uint32_t index = 0U; index < removed_count; ++index) {
            sum -= model->scalar.feature_weights[removed[index]][column];
        }
        for (uint32_t index = 0U; index < added_count; ++index) {
            sum += model->scalar.feature_weights[added[index]][column];
        }
        if (sum < INT16_MIN || sum > INT16_MAX) {
            set_error("incremental feature update overflow");
            return 0;
        }
        sums[column] = (int16_t)sum;
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

MAKHOS_API int makhos_nnue_incremental_eval(
    const void *opaque_model,
    const void *opaque_accumulator,
    int side_to_move,
    int32_t *output_sum
) {
    last_error[0] = '\0';
    MakhosNnueIncrementalModel *model = checked_model(opaque_model);
    MakhosNnueAccumulator *accumulator = checked_accumulator(
        (void *)(uintptr_t)opaque_accumulator);
    int first = perspective_slot(side_to_move);
    if (model == NULL || accumulator == NULL || first < 0 || output_sum == NULL) {
        if (output_sum == NULL) set_error("incremental output is null");
        return 0;
    }
    if (!accumulator->valid || accumulator->model_instance != model->instance) {
        set_error("incremental accumulator requires refresh for this model");
        return 0;
    }
    int second = first == 0 ? 1 : 0;
    return evaluate_accumulator_sums(
        &model->scalar,
        accumulator->sums[first],
        accumulator->sums[second],
        output_sum
    );
}

MAKHOS_API int makhos_nnue_incremental_eval_full(
    const void *opaque_model,
    const uint16_t *red_indices,
    uint32_t red_count,
    const uint16_t *black_indices,
    uint32_t black_count,
    int side_to_move,
    int32_t *output_sum
) {
    last_error[0] = '\0';
    MakhosNnueIncrementalModel *model = checked_model(opaque_model);
    int side = perspective_slot(side_to_move);
    if (model == NULL || side < 0) return 0;
    if (side_to_move == RED_PERSPECTIVE) {
        return makhos_nnue_scalar_eval(
            &model->scalar,
            red_indices,
            red_count,
            black_indices,
            black_count,
            output_sum
        );
    }
    return makhos_nnue_scalar_eval(
        &model->scalar,
        black_indices,
        black_count,
        red_indices,
        red_count,
        output_sum
    );
}
