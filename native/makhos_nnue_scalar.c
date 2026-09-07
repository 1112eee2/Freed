#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define MAKHOS_API __declspec(dllexport)
#else
#define MAKHOS_API __attribute__((visibility("default")))
#endif

enum {
    INPUT_DIMENSIONS = 137,
    FEATURE_WIDTH = 128,
    HIDDEN_WIDTH = 32,
    OUTPUT_WIDTH = 1,
    FEATURE_SCALE = 2048,
    ACTIVATION_SCALE = 127,
    HIDDEN_WEIGHT_SCALE = 256,
    OUTPUT_WEIGHT_SCALE = 192,
    NONTERMINAL_CP_BOUND = 30000,
    MAX_ACTIVE_FEATURES = 17,
    HEADER_BYTES = 188,
    PAYLOAD_BYTES = 43684
};

typedef struct {
    int16_t feature_weights[INPUT_DIMENSIONS][FEATURE_WIDTH];
    int16_t feature_bias[FEATURE_WIDTH];
    int8_t hidden_weights[HIDDEN_WIDTH][FEATURE_WIDTH * 2];
    int32_t hidden_bias[HIDDEN_WIDTH];
    int8_t output_weights[HIDDEN_WIDTH];
    int32_t output_bias;
} MakhosNnueScalar;

typedef struct {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t block[64];
    size_t block_length;
} Sha256Context;

static char last_error[256];

static const uint8_t expected_magic[8] = {'M', 'K', 'N', 'N', 'U', 'E', '1', 0};
static const uint8_t expected_feature_sha[32] = {
    0xC6, 0x49, 0xD1, 0xEE, 0x00, 0xA3, 0x91, 0x57,
    0xDD, 0x58, 0xDB, 0x91, 0x42, 0xCE, 0x94, 0x3C,
    0x5B, 0x78, 0xCB, 0xC9, 0xF5, 0xDB, 0xA1, 0x86,
    0x40, 0x5B, 0x6F, 0x46, 0x40, 0x4D, 0x49, 0xBA
};
static const uint8_t expected_ruleset_sha[32] = {
    0x77, 0x52, 0x8A, 0xDD, 0xC0, 0xE0, 0x8B, 0x17,
    0x21, 0x73, 0x46, 0xC5, 0x11, 0xC7, 0xC4, 0x08,
    0x4B, 0xAD, 0x4A, 0xF4, 0x87, 0x89, 0x95, 0x5C,
    0x3E, 0xC8, 0x5E, 0xF7, 0x6A, 0x64, 0x87, 0x1F
};

static const uint32_t sha256_constants[64] = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
    0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
    0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
    0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U
};

static void set_error(const char *message) {
    size_t length = strlen(message);
    if (length >= sizeof(last_error)) {
        length = sizeof(last_error) - 1U;
    }
    memcpy(last_error, message, length);
    last_error[length] = '\0';
}

static uint32_t rotate_right(uint32_t value, uint32_t count) {
    return (value >> count) | (value << (32U - count));
}

static uint32_t read_be32(const uint8_t *bytes) {
    return ((uint32_t)bytes[0] << 24U) |
           ((uint32_t)bytes[1] << 16U) |
           ((uint32_t)bytes[2] << 8U) |
           (uint32_t)bytes[3];
}

static void write_be32(uint8_t *bytes, uint32_t value) {
    bytes[0] = (uint8_t)(value >> 24U);
    bytes[1] = (uint8_t)(value >> 16U);
    bytes[2] = (uint8_t)(value >> 8U);
    bytes[3] = (uint8_t)value;
}

static void sha256_transform(Sha256Context *context, const uint8_t block[64]) {
    uint32_t schedule[64];
    for (size_t index = 0; index < 16U; ++index) {
        schedule[index] = read_be32(block + index * 4U);
    }
    for (size_t index = 16U; index < 64U; ++index) {
        uint32_t first = schedule[index - 15U];
        uint32_t second = schedule[index - 2U];
        uint32_t sigma0 = rotate_right(first, 7U) ^ rotate_right(first, 18U) ^
                          (first >> 3U);
        uint32_t sigma1 = rotate_right(second, 17U) ^ rotate_right(second, 19U) ^
                          (second >> 10U);
        schedule[index] = schedule[index - 16U] + sigma0 + schedule[index - 7U] + sigma1;
    }
    uint32_t a = context->state[0];
    uint32_t b = context->state[1];
    uint32_t c = context->state[2];
    uint32_t d = context->state[3];
    uint32_t e = context->state[4];
    uint32_t f = context->state[5];
    uint32_t g = context->state[6];
    uint32_t h = context->state[7];
    for (size_t index = 0; index < 64U; ++index) {
        uint32_t sum1 = rotate_right(e, 6U) ^ rotate_right(e, 11U) ^ rotate_right(e, 25U);
        uint32_t choice = (e & f) ^ ((~e) & g);
        uint32_t temporary1 = h + sum1 + choice + sha256_constants[index] + schedule[index];
        uint32_t sum0 = rotate_right(a, 2U) ^ rotate_right(a, 13U) ^ rotate_right(a, 22U);
        uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temporary2 = sum0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + temporary1;
        d = c;
        c = b;
        b = a;
        a = temporary1 + temporary2;
    }
    context->state[0] += a;
    context->state[1] += b;
    context->state[2] += c;
    context->state[3] += d;
    context->state[4] += e;
    context->state[5] += f;
    context->state[6] += g;
    context->state[7] += h;
}

static void sha256_init(Sha256Context *context) {
    static const uint32_t initial[8] = {
        0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
        0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U
    };
    memcpy(context->state, initial, sizeof(initial));
    context->bit_count = 0U;
    context->block_length = 0U;
}

static void sha256_update(Sha256Context *context, const uint8_t *data, size_t length) {
    context->bit_count += (uint64_t)length * 8U;
    while (length > 0U) {
        size_t capacity = 64U - context->block_length;
        size_t take = length < capacity ? length : capacity;
        memcpy(context->block + context->block_length, data, take);
        context->block_length += take;
        data += take;
        length -= take;
        if (context->block_length == 64U) {
            sha256_transform(context, context->block);
            context->block_length = 0U;
        }
    }
}

static void sha256_final(Sha256Context *context, uint8_t digest[32]) {
    context->block[context->block_length++] = 0x80U;
    if (context->block_length > 56U) {
        memset(context->block + context->block_length, 0, 64U - context->block_length);
        sha256_transform(context, context->block);
        context->block_length = 0U;
    }
    memset(context->block + context->block_length, 0, 56U - context->block_length);
    for (size_t index = 0; index < 8U; ++index) {
        context->block[63U - index] = (uint8_t)(context->bit_count >> (index * 8U));
    }
    sha256_transform(context, context->block);
    for (size_t index = 0; index < 8U; ++index) {
        write_be32(digest + index * 4U, context->state[index]);
    }
}

static void sha256_bytes(const uint8_t *data, size_t length, uint8_t digest[32]) {
    Sha256Context context;
    sha256_init(&context);
    sha256_update(&context, data, length);
    sha256_final(&context, digest);
}

static uint16_t read_le16(const uint8_t *bytes) {
    return (uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8U);
}

static int16_t read_le_i16(const uint8_t *bytes) {
    uint16_t value = read_le16(bytes);
    int32_t signed_value = value <= INT16_MAX
        ? (int32_t)value
        : (int32_t)value - 65536;
    return (int16_t)signed_value;
}

static uint32_t read_le32(const uint8_t *bytes) {
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8U) |
           ((uint32_t)bytes[2] << 16U) |
           ((uint32_t)bytes[3] << 24U);
}

static int32_t read_le_i32(const uint8_t *bytes) {
    uint32_t value = read_le32(bytes);
    int64_t signed_value = value <= INT32_MAX
        ? (int64_t)value
        : (int64_t)value - INT64_C(4294967296);
    return (int32_t)signed_value;
}

static uint64_t read_le64(const uint8_t *bytes) {
    uint64_t result = 0U;
    for (size_t index = 0; index < 8U; ++index) {
        result |= (uint64_t)bytes[index] << (index * 8U);
    }
    return result;
}

static FILE *open_binary_read(const char *path) {
#if defined(_WIN32)
    FILE *stream = NULL;
    if (fopen_s(&stream, path, "rb") != 0) {
        return NULL;
    }
    return stream;
#else
    return fopen(path, "rb");
#endif
}

static int read_file(const char *path, uint8_t **encoded, size_t *length) {
    FILE *stream = open_binary_read(path);
    if (stream == NULL) {
        set_error("unable to open quantized model");
        return 0;
    }
    if (fseek(stream, 0L, SEEK_END) != 0) {
        fclose(stream);
        set_error("unable to seek quantized model");
        return 0;
    }
    long measured = ftell(stream);
    if (measured < 0L || measured > 1048576L || fseek(stream, 0L, SEEK_SET) != 0) {
        fclose(stream);
        set_error("quantized model size is invalid");
        return 0;
    }
    size_t size = (size_t)measured;
    uint8_t *buffer = (uint8_t *)malloc(size > 0U ? size : 1U);
    if (buffer == NULL) {
        fclose(stream);
        set_error("quantized model allocation failed");
        return 0;
    }
    size_t bytes_read = fread(buffer, 1U, size, stream);
    int close_status = fclose(stream);
    if (bytes_read != size || close_status != 0) {
        free(buffer);
        set_error("quantized model read failed");
        return 0;
    }
    *encoded = buffer;
    *length = size;
    return 1;
}

static int validate_header(
    const uint8_t *encoded,
    size_t length,
    const uint8_t expected_source_model_sha256[32]
) {
    if (length != (size_t)(HEADER_BYTES + PAYLOAD_BYTES)) {
        set_error("quantized model is truncated or has extra bytes");
        return 0;
    }
    if (memcmp(encoded, expected_magic, sizeof(expected_magic)) != 0 ||
        read_le32(encoded + 8U) != 1U ||
        read_le32(encoded + 12U) != HEADER_BYTES ||
        read_le32(encoded + 16U) != INPUT_DIMENSIONS ||
        read_le32(encoded + 20U) != FEATURE_WIDTH ||
        read_le32(encoded + 24U) != HIDDEN_WIDTH ||
        read_le32(encoded + 28U) != OUTPUT_WIDTH ||
        read_le32(encoded + 32U) != FEATURE_SCALE ||
        read_le32(encoded + 36U) != ACTIVATION_SCALE ||
        read_le32(encoded + 40U) != HIDDEN_WEIGHT_SCALE ||
        read_le32(encoded + 44U) != OUTPUT_WEIGHT_SCALE ||
        read_le32(encoded + 48U) != NONTERMINAL_CP_BOUND ||
        read_le64(encoded + 148U) != PAYLOAD_BYTES) {
        set_error("quantized model header is incompatible");
        return 0;
    }
    if (memcmp(encoded + 52U, expected_feature_sha, 32U) != 0 ||
        memcmp(encoded + 84U, expected_ruleset_sha, 32U) != 0) {
        set_error("feature or ruleset identity differs");
        return 0;
    }
    if (expected_source_model_sha256 == NULL ||
        memcmp(encoded + 116U, expected_source_model_sha256, 32U) != 0) {
        set_error("source model identity differs");
        return 0;
    }
    uint8_t digest[32];
    sha256_bytes(encoded + HEADER_BYTES, PAYLOAD_BYTES, digest);
    if (memcmp(digest, encoded + 156U, 32U) != 0) {
        set_error("quantized model payload checksum differs");
        return 0;
    }
    return 1;
}

static int decode_payload(MakhosNnueScalar *model, const uint8_t *payload) {
    size_t offset = 0U;
    for (size_t row = 0; row < INPUT_DIMENSIONS; ++row) {
        for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
            model->feature_weights[row][column] = read_le_i16(payload + offset);
            offset += 2U;
        }
    }
    for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
        model->feature_bias[column] = read_le_i16(payload + offset);
        offset += 2U;
    }
    for (size_t row = 0; row < HIDDEN_WIDTH; ++row) {
        for (size_t column = 0; column < FEATURE_WIDTH * 2U; ++column) {
            model->hidden_weights[row][column] = (int8_t)payload[offset++];
        }
    }
    for (size_t row = 0; row < HIDDEN_WIDTH; ++row) {
        model->hidden_bias[row] = read_le_i32(payload + offset);
        offset += 4U;
    }
    for (size_t column = 0; column < HIDDEN_WIDTH; ++column) {
        model->output_weights[column] = (int8_t)payload[offset++];
    }
    model->output_bias = read_le_i32(payload + offset);
    offset += 4U;
    if (offset != PAYLOAD_BYTES) {
        set_error("quantized model payload layout differs");
        return 0;
    }
    return 1;
}

static int64_t absolute_i32(int32_t value) {
    return value < 0 ? -(int64_t)value : (int64_t)value;
}

static int validate_model_bounds(const MakhosNnueScalar *model) {
    for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
        int64_t maximum_weight = 0;
        for (size_t row = 0; row < INPUT_DIMENSIONS; ++row) {
            int64_t weight = absolute_i32(model->feature_weights[row][column]);
            if (weight > maximum_weight) {
                maximum_weight = weight;
            }
        }
        int64_t bound = absolute_i32(model->feature_bias[column]) +
                        MAX_ACTIVE_FEATURES * maximum_weight;
        if (bound > INT16_MAX) {
            set_error("quantized model feature accumulator bound is unsafe");
            return 0;
        }
    }
    for (size_t row = 0; row < HIDDEN_WIDTH; ++row) {
        int64_t weight_sum = 0;
        for (size_t column = 0; column < FEATURE_WIDTH * 2U; ++column) {
            weight_sum += absolute_i32(model->hidden_weights[row][column]);
        }
        int64_t bound = absolute_i32(model->hidden_bias[row]) +
                        ACTIVATION_SCALE * weight_sum;
        if (bound > INT32_MAX) {
            set_error("quantized model hidden dense bound is unsafe");
            return 0;
        }
    }
    int64_t output_weight_sum = 0;
    for (size_t column = 0; column < HIDDEN_WIDTH; ++column) {
        output_weight_sum += absolute_i32(model->output_weights[column]);
    }
    int64_t output_bound = absolute_i32(model->output_bias) +
                           ACTIVATION_SCALE * output_weight_sum;
    if (output_bound > INT32_MAX) {
        set_error("quantized model output dense bound is unsafe");
        return 0;
    }
    return 1;
}

static int validate_indices(const uint16_t *indices, uint32_t count) {
    if (indices == NULL || count < 1U || count > MAX_ACTIVE_FEATURES) {
        set_error("active feature count is invalid");
        return 0;
    }
    for (uint32_t index = 0U; index < count; ++index) {
        if (indices[index] >= INPUT_DIMENSIONS) {
            set_error("active feature index is out of range");
            return 0;
        }
        for (uint32_t previous = 0U; previous < index; ++previous) {
            if (indices[previous] == indices[index]) {
                set_error("active feature index is duplicated");
                return 0;
            }
        }
    }
    return 1;
}

static int8_t clipped_activation(int32_t value, int32_t input_scale) {
    if (value <= 0) {
        return 0;
    }
    if (value >= input_scale) {
        return ACTIVATION_SCALE;
    }
    return (int8_t)(((int64_t)value * ACTIVATION_SCALE + input_scale / 2) /
                    input_scale);
}

static int refresh_accumulator(
    const MakhosNnueScalar *model,
    const uint16_t *indices,
    uint32_t count,
    int8_t output[FEATURE_WIDTH]
) {
    for (size_t column = 0; column < FEATURE_WIDTH; ++column) {
        int32_t sum = model->feature_bias[column];
        for (uint32_t index = 0U; index < count; ++index) {
            sum += model->feature_weights[indices[index]][column];
        }
        if (sum < INT16_MIN || sum > INT16_MAX) {
            set_error("feature accumulator overflow");
            return 0;
        }
        output[column] = clipped_activation(sum, FEATURE_SCALE);
    }
    return 1;
}

MAKHOS_API const char *makhos_nnue_scalar_last_error(void) {
    return last_error;
}

MAKHOS_API size_t makhos_nnue_scalar_model_bytes(void) {
    return sizeof(MakhosNnueScalar);
}

MAKHOS_API void *makhos_nnue_scalar_load(
    const char *path,
    const uint8_t expected_source_model_sha256[32]
) {
    last_error[0] = '\0';
    if (path == NULL) {
        set_error("quantized model path is null");
        return NULL;
    }
    uint8_t *encoded = NULL;
    size_t length = 0U;
    if (!read_file(path, &encoded, &length)) {
        return NULL;
    }
    if (!validate_header(encoded, length, expected_source_model_sha256)) {
        free(encoded);
        return NULL;
    }
    MakhosNnueScalar *model = (MakhosNnueScalar *)malloc(sizeof(*model));
    if (model == NULL) {
        free(encoded);
        set_error("native scalar model allocation failed");
        return NULL;
    }
    if (!decode_payload(model, encoded + HEADER_BYTES) ||
        !validate_model_bounds(model)) {
        memset(model, 0, sizeof(*model));
        free(model);
        free(encoded);
        return NULL;
    }
    free(encoded);
    return model;
}

MAKHOS_API void makhos_nnue_scalar_free(void *opaque_model) {
    if (opaque_model != NULL) {
        memset(opaque_model, 0, sizeof(MakhosNnueScalar));
        free(opaque_model);
    }
}

MAKHOS_API int makhos_nnue_scalar_eval(
    const void *opaque_model,
    const uint16_t *side_to_move_indices,
    uint32_t side_to_move_count,
    const uint16_t *opponent_indices,
    uint32_t opponent_count,
    int32_t *output_sum
) {
    last_error[0] = '\0';
    if (opaque_model == NULL || output_sum == NULL) {
        set_error("native scalar eval argument is null");
        return 0;
    }
    if (!validate_indices(side_to_move_indices, side_to_move_count) ||
        !validate_indices(opponent_indices, opponent_count)) {
        return 0;
    }
    const MakhosNnueScalar *model = (const MakhosNnueScalar *)opaque_model;
    int8_t features[FEATURE_WIDTH * 2U];
    if (!refresh_accumulator(
            model, side_to_move_indices, side_to_move_count, features) ||
        !refresh_accumulator(
            model, opponent_indices, opponent_count, features + FEATURE_WIDTH)) {
        return 0;
    }
    int8_t hidden[HIDDEN_WIDTH];
    for (size_t row = 0; row < HIDDEN_WIDTH; ++row) {
        int64_t sum = model->hidden_bias[row];
        for (size_t column = 0; column < FEATURE_WIDTH * 2U; ++column) {
            sum += (int32_t)model->hidden_weights[row][column] * features[column];
        }
        if (sum < INT32_MIN || sum > INT32_MAX) {
            set_error("hidden dense sum overflow");
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
        set_error("output dense sum overflow");
        return 0;
    }
    *output_sum = (int32_t)sum;
    return 1;
}
