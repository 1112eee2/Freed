#define MAKHOS_TB5_NO_MAIN
#include "makhos_tb5.c"

#define TB6_SIGNATURES 70
#define TB6_PART_MAGIC "MK6PART1"
#define TB6_TRANSITION_MAGIC "MK6TRN01"
#define TB6_LAYER_MAGIC "MK6LAYR1"
#define TB6_VERSION 1U
#define TB6_PATH_CAPACITY 4096

#pragma pack(push, 1)
typedef struct {
    char magic[8];
    uint32_t version;
    uint32_t no_progress_plies;
    uint32_t signature_index;
    uint32_t partition_index;
    uint8_t counts[4];
    uint64_t state_start;
    uint64_t state_count;
    uint64_t dependency_binding;
    uint64_t edge_count;
    uint64_t checksum;
} SixTransitionHeader;

typedef struct {
    char magic[8];
    uint32_t version;
    uint32_t no_progress_plies;
    uint32_t signature_index;
    uint8_t counts[4];
    uint64_t state_count;
    uint64_t dependency_binding;
    int32_t next_clock;
    uint64_t threshold_checksum;
    uint64_t layer_checksum;
} SixLayerHeader;
#pragma pack(pop)

_Static_assert(
    sizeof(SixTransitionHeader) == 68,
    "six-piece transition header layout changed"
);

_Static_assert(
    sizeof(SixLayerHeader) == 60,
    "six-piece layer header layout changed"
);

static uint64_t six_dependency_binding(
    const CompactTablebase *four_piece,
    const CompactTablebase *five_piece
) {
    uint64_t binding = four_piece->checksum;
    binding = checksum_update(
        binding,
        (const uint8_t *)&five_piece->piece_count,
        sizeof(five_piece->piece_count)
    );
    binding = checksum_update(
        binding,
        (const uint8_t *)&five_piece->checksum,
        sizeof(five_piece->checksum)
    );
    return binding;
}

static bool six_path(
    char path[TB6_PATH_CAPACITY],
    const char *output_path,
    uint32_t signature_index,
    const char *kind,
    uint32_t partition_index,
    const char *suffix
) {
    int written;
    if (partition_index == UINT32_MAX) {
        written = snprintf(
            path,
            TB6_PATH_CAPACITY,
            "%s.%02u.%s%s",
            output_path,
            signature_index,
            kind,
            suffix
        );
    } else {
        written = snprintf(
            path,
            TB6_PATH_CAPACITY,
            "%s.%02u.%s.%04u%s",
            output_path,
            signature_index,
            kind,
            partition_index,
            suffix
        );
    }
    return written > 0 && written < TB6_PATH_CAPACITY;
}

static bool initialize_six_piece_tablebase(
    CompactTablebase *tablebase,
    int no_progress_plies
) {
    memset(tablebase, 0, sizeof(*tablebase));
    memset(tablebase->signature_index, 0xff, sizeof(tablebase->signature_index));
    tablebase->piece_count = 6;
    tablebase->no_progress_plies = (uint32_t)no_progress_plies;
    uint32_t index = 0;
    for (int bm = 0; bm <= 6; ++bm) {
        for (int bk = 0; bk <= 6 - bm; ++bk) {
            for (int rm = 0; rm <= 6 - bm - bk; ++rm) {
                int rk = 6 - bm - bk - rm;
                if (bm + bk == 0 || rm + rk == 0) {
                    continue;
                }
                if (index >= TB6_SIGNATURES) {
                    return false;
                }
                CompactSignature *signature = &tablebase->signatures[index++];
                signature->count[0] = (uint8_t)bm;
                signature->count[1] = (uint8_t)bk;
                signature->count[2] = (uint8_t)rm;
                signature->count[3] = (uint8_t)rk;
            }
        }
    }
    if (index != TB6_SIGNATURES) {
        return false;
    }
    tablebase->signature_count = index;
    qsort(
        tablebase->signatures,
        tablebase->signature_count,
        sizeof(tablebase->signatures[0]),
        compare_compact_signatures
    );
    for (uint32_t signature_index = 0;
         signature_index < tablebase->signature_count;
         ++signature_index) {
        CompactSignature *signature = &tablebase->signatures[signature_index];
        int bm = signature->count[0];
        int bk = signature->count[1];
        int rm = signature->count[2];
        int rk = signature->count[3];
        signature->boards = completion_count(0, bm, bk, rm, rk);
        signature->byte_count = signature->boards * 2;
        tablebase->total_positions += signature->byte_count;
        tablebase->signature_index[bm][bk][rm][rk] = (int)signature_index;
    }
    tablebase->total_states = tablebase->total_positions *
        ((uint64_t)tablebase->no_progress_plies + 1);
    return true;
}

static bool allocate_six_thresholds(CompactSignature *signature) {
    if (signature->thresholds != NULL) {
        return true;
    }
    if (signature->byte_count > SIZE_MAX) {
        return false;
    }
    signature->thresholds = calloc((size_t)signature->byte_count, 1);
    return signature->thresholds != NULL;
}

/* Return 1 for a valid completed signature, 0 when absent, -1 on error. */
static int read_six_signature_part(
    CompactTablebase *tablebase,
    uint32_t signature_index,
    uint64_t dependency_binding,
    const char *output_path
) {
    char path[TB6_PATH_CAPACITY];
    if (!six_path(
            path, output_path, signature_index,
            "sixpart", UINT32_MAX, ""
        )) {
        return -1;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    CompactSignature *signature = &tablebase->signatures[signature_index];
    if (!allocate_six_thresholds(signature)) {
        fclose(file);
        return -1;
    }
    char magic[8];
    uint32_t version;
    uint32_t no_progress;
    uint32_t stored_index;
    uint8_t counts[4];
    uint64_t boards;
    uint64_t byte_count;
    uint64_t stored_dependency;
    uint64_t expected_checksum;
    bool ok =
        fread(magic, 1, 8, file) == 8 &&
        memcmp(magic, TB6_PART_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, file) == 1 &&
        version == TB6_VERSION &&
        fread(&no_progress, sizeof(no_progress), 1, file) == 1 &&
        no_progress == tablebase->no_progress_plies &&
        fread(&stored_index, sizeof(stored_index), 1, file) == 1 &&
        stored_index == signature_index &&
        fread(counts, 1, 4, file) == 4 &&
        memcmp(counts, signature->count, 4) == 0 &&
        fread(&boards, sizeof(boards), 1, file) == 1 &&
        boards == signature->boards &&
        fread(&byte_count, sizeof(byte_count), 1, file) == 1 &&
        byte_count == signature->byte_count &&
        fread(&stored_dependency, sizeof(stored_dependency), 1, file) == 1 &&
        stored_dependency == dependency_binding &&
        fread(&expected_checksum, sizeof(expected_checksum), 1, file) == 1 &&
        fread(
            signature->thresholds,
            1,
            (size_t)signature->byte_count,
            file
        ) == signature->byte_count &&
        fgetc(file) == EOF;
    fclose(file);
    if (!ok) {
        return -1;
    }
    uint64_t checksum = checksum_update(
        UINT64_C(1469598103934665603),
        signature->thresholds,
        signature->byte_count
    );
    if (checksum != expected_checksum) {
        return -1;
    }
    fprintf(stderr, "resumed six-piece signature %u from %s\n",
        signature_index + 1, path);
    return 1;
}

static bool write_six_signature_part(
    const CompactTablebase *tablebase,
    uint32_t signature_index,
    uint64_t dependency_binding,
    const char *output_path
) {
    char path[TB6_PATH_CAPACITY];
    char temporary[TB6_PATH_CAPACITY];
    if (
        !six_path(path, output_path, signature_index,
            "sixpart", UINT32_MAX, "") ||
        !six_path(temporary, output_path, signature_index,
            "sixpart", UINT32_MAX, ".tmp")
    ) {
        return false;
    }
    const CompactSignature *signature = &tablebase->signatures[signature_index];
    uint64_t checksum = checksum_update(
        UINT64_C(1469598103934665603),
        signature->thresholds,
        signature->byte_count
    );
    FILE *file = fopen(temporary, "wb");
    if (file == NULL) {
        return false;
    }
    uint32_t version = TB6_VERSION;
    bool ok =
        fwrite(TB6_PART_MAGIC, 1, 8, file) == 8 &&
        fwrite(&version, sizeof(version), 1, file) == 1 &&
        fwrite(&tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&signature_index, sizeof(signature_index), 1, file) == 1 &&
        fwrite(signature->count, 1, 4, file) == 4 &&
        fwrite(&signature->boards, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&signature->byte_count, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&dependency_binding, sizeof(dependency_binding), 1, file) == 1 &&
        fwrite(&checksum, sizeof(checksum), 1, file) == 1 &&
        fwrite(
            signature->thresholds,
            1,
            (size_t)signature->byte_count,
            file
        ) == signature->byte_count;
    if (fclose(file) != 0) {
        ok = false;
    }
    if (!ok || !makhos_replace_file_atomically(temporary, path)) {
        remove(temporary);
        return false;
    }
    return true;
}

static bool six_layer_path(
    char path[TB6_PATH_CAPACITY],
    const char *output_path,
    uint32_t signature_index,
    int next_clock,
    const char *suffix
) {
    return six_path(
        path,
        output_path,
        signature_index,
        "layer",
        (uint32_t)(next_clock + 1),
        suffix
    );
}

static void remove_six_layer_checkpoints(
    const CompactTablebase *tablebase,
    uint32_t signature_index,
    int keep_next_clock,
    const char *output_path
) {
    for (int next_clock = -1;
         next_clock < (int)tablebase->no_progress_plies;
         ++next_clock) {
        if (next_clock == keep_next_clock) continue;
        char path[TB6_PATH_CAPACITY];
        if (six_layer_path(
                path,
                output_path,
                signature_index,
                next_clock,
                ""
            )) {
            remove(path);
        }
    }
}

static bool validate_six_layer_state(
    const CompactTablebase *tablebase,
    const CompactSignature *signature,
    int next_clock,
    const uint8_t *next_layer
) {
    int minimum_boundary = next_clock + 2;
    for (uint64_t state = 0; state < signature->byte_count; ++state) {
        uint8_t encoded = signature->thresholds[state];
        uint8_t layer_value = next_layer[state];
        if (layer_value > 2) return false;
        if (encoded == 0) {
            if (layer_value != 1) return false;
            continue;
        }
        int boundary = encoded & UINT8_C(0x7f);
        uint8_t threshold_value =
            (encoded & UINT8_C(0x80)) != 0 ? 2 : 0;
        if (
            boundary < minimum_boundary ||
            boundary > (int)tablebase->no_progress_plies ||
            layer_value != threshold_value
        ) {
            return false;
        }
    }
    return true;
}

/* Return 1 for a valid checkpoint, 0 when absent, -1 on error. */
static int read_six_layer_checkpoint(
    CompactTablebase *tablebase,
    uint32_t signature_index,
    uint64_t dependency_binding,
    const char *output_path,
    uint8_t *next_layer,
    int *next_clock
) {
    CompactSignature *signature = &tablebase->signatures[signature_index];
    for (int candidate = -1;
         candidate < (int)tablebase->no_progress_plies;
         ++candidate) {
        char path[TB6_PATH_CAPACITY];
        if (!six_layer_path(
                path,
                output_path,
                signature_index,
                candidate,
                ""
            )) {
            return -1;
        }
        FILE *file = fopen(path, "rb");
        if (file == NULL) continue;
        SixLayerHeader header;
        bool ok =
            fread(&header, 1, sizeof(header), file) == sizeof(header) &&
            memcmp(header.magic, TB6_LAYER_MAGIC, 8) == 0 &&
            header.version == TB6_VERSION &&
            header.no_progress_plies == tablebase->no_progress_plies &&
            header.signature_index == signature_index &&
            memcmp(header.counts, signature->count, 4) == 0 &&
            header.state_count == signature->byte_count &&
            header.dependency_binding == dependency_binding &&
            header.next_clock == candidate &&
            fread(
                signature->thresholds,
                1,
                (size_t)signature->byte_count,
                file
            ) == signature->byte_count &&
            fread(
                next_layer,
                1,
                (size_t)signature->byte_count,
                file
            ) == signature->byte_count &&
            fgetc(file) == EOF;
        fclose(file);
        uint64_t threshold_checksum = 0;
        uint64_t layer_checksum = 0;
        if (ok) {
            threshold_checksum = checksum_update(
                UINT64_C(1469598103934665603),
                signature->thresholds,
                signature->byte_count
            );
            layer_checksum = checksum_update(
                UINT64_C(1469598103934665603),
                next_layer,
                signature->byte_count
            );
            ok =
                threshold_checksum == header.threshold_checksum &&
                layer_checksum == header.layer_checksum &&
                validate_six_layer_state(
                    tablebase,
                    signature,
                    candidate,
                    next_layer
                );
        }
        if (!ok) {
            fprintf(stderr, "invalid six-piece layer checkpoint: %s\n", path);
            return -1;
        }
        *next_clock = candidate;
        fprintf(
            stderr,
            "resumed six signature %u at clock %d from %s\n",
            signature_index + 1,
            candidate,
            path
        );
        return 1;
    }
    return 0;
}

static bool write_six_layer_checkpoint(
    const CompactTablebase *tablebase,
    uint32_t signature_index,
    uint64_t dependency_binding,
    const char *output_path,
    int next_clock,
    const uint8_t *next_layer
) {
    char path[TB6_PATH_CAPACITY];
    char temporary[TB6_PATH_CAPACITY];
    if (
        !six_layer_path(
            path,
            output_path,
            signature_index,
            next_clock,
            ""
        ) ||
        !six_layer_path(
            temporary,
            output_path,
            signature_index,
            next_clock,
            ".tmp"
        )
    ) {
        return false;
    }
    remove(temporary);
    const CompactSignature *signature =
        &tablebase->signatures[signature_index];
    SixLayerHeader header;
    memset(&header, 0, sizeof(header));
    memcpy(header.magic, TB6_LAYER_MAGIC, 8);
    header.version = TB6_VERSION;
    header.no_progress_plies = tablebase->no_progress_plies;
    header.signature_index = signature_index;
    memcpy(header.counts, signature->count, 4);
    header.state_count = signature->byte_count;
    header.dependency_binding = dependency_binding;
    header.next_clock = next_clock;
    header.threshold_checksum = checksum_update(
        UINT64_C(1469598103934665603),
        signature->thresholds,
        signature->byte_count
    );
    header.layer_checksum = checksum_update(
        UINT64_C(1469598103934665603),
        next_layer,
        signature->byte_count
    );
    FILE *file = fopen(temporary, "wb");
    if (file == NULL) return false;
    bool ok =
        fwrite(&header, 1, sizeof(header), file) == sizeof(header) &&
        fwrite(
            signature->thresholds,
            1,
            (size_t)signature->byte_count,
            file
        ) == signature->byte_count &&
        fwrite(
            next_layer,
            1,
            (size_t)signature->byte_count,
            file
        ) == signature->byte_count;
    if (fclose(file) != 0) ok = false;
    if (!ok || !makhos_replace_file_atomically(temporary, path)) {
        remove(temporary);
        return false;
    }
    remove_six_layer_checkpoints(
        tablebase,
        signature_index,
        next_clock,
        output_path
    );
    fprintf(
        stderr,
        "checkpointed six signature %u; next clock %d\n",
        signature_index + 1,
        next_clock
    );
    return true;
}

static bool classify_six_child(
    CompactTablebase *six_piece,
    const CompactTablebase *four_piece,
    const CompactTablebase *five_piece,
    const bool *built,
    uint32_t signature_index,
    Position child,
    bool *quiet,
    uint32_t *quiet_child,
    uint8_t *static_child_value
) {
    *quiet = false;
    if (child.red == 0 || child.black == 0) {
        *static_child_value = 0;
        return true;
    }
    int pieces = count_bits(occupied(child));
    if (pieces <= 3) {
        return probe_three_piece_readonly(child, static_child_value);
    }
    if (pieces == 4) {
        return probe_compact_position(
            four_piece, child, static_child_value
        );
    }
    if (pieces == 5) {
        return probe_compact_position(
            five_piece, child, static_child_value
        );
    }
    if (pieces != 6) {
        return false;
    }
    uint8_t child_counts[4];
    signature_for_position(child, child_counts);
    int child_signature_index = six_piece->signature_index
        [child_counts[0]][child_counts[1]]
        [child_counts[2]][child_counts[3]];
    if (child_signature_index < 0) {
        return false;
    }
    CompactSignature *child_signature =
        &six_piece->signatures[child_signature_index];
    uint64_t child_rank = compact_rank(child, child_signature);
    uint64_t child_state = child_rank * 2 +
        (child.turn == BLACK ? 1 : 0);
    if (child_signature_index == (int)signature_index) {
        if (child_state > UINT32_MAX) {
            return false;
        }
        *quiet = true;
        *quiet_child = (uint32_t)child_state;
        return true;
    }
    if (!built[child_signature_index]) {
        return false;
    }
    *static_child_value = get_compact_wdl(
        child_signature,
        child_rank,
        child.turn,
        child.reversible_plies
    );
    return true;
}

static bool read_six_transition_header(
    FILE *file,
    const CompactTablebase *tablebase,
    uint32_t signature_index,
    uint32_t partition_index,
    uint64_t state_start,
    uint64_t state_count,
    uint64_t dependency_binding,
    SixTransitionHeader *header
) {
    const CompactSignature *signature =
        &tablebase->signatures[signature_index];
    return
        fread(header, 1, sizeof(*header), file) == sizeof(*header) &&
        memcmp(header->magic, TB6_TRANSITION_MAGIC, 8) == 0 &&
        header->version == TB6_VERSION &&
        header->no_progress_plies == tablebase->no_progress_plies &&
        header->signature_index == signature_index &&
        header->partition_index == partition_index &&
        memcmp(header->counts, signature->count, 4) == 0 &&
        header->state_start == state_start &&
        header->state_count == state_count &&
        header->dependency_binding == dependency_binding;
}

/* Return 1 for valid, 0 for absent, -1 for invalid. */
static int verify_six_transition_part(
    const CompactTablebase *tablebase,
    uint32_t signature_index,
    uint32_t partition_index,
    uint64_t state_start,
    uint64_t state_count,
    uint64_t dependency_binding,
    const char *output_path
) {
    char path[TB6_PATH_CAPACITY];
    if (!six_path(
            path, output_path, signature_index,
            "transition", partition_index, ""
        )) {
        return -1;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    SixTransitionHeader header;
    bool ok = read_six_transition_header(
        file,
        tablebase,
        signature_index,
        partition_index,
        state_start,
        state_count,
        dependency_binding,
        &header
    );
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint64_t edges = 0;
    for (uint64_t state = 0; ok && state < state_count; ++state) {
        uint8_t fixed_value;
        uint16_t quiet_count;
        ok =
            fread(&fixed_value, 1, 1, file) == 1 &&
            fread(&quiet_count, sizeof(quiet_count), 1, file) == 1 &&
            fixed_value <= 2 &&
            quiet_count <= MAX_MOVES;
        if (!ok) break;
        checksum = checksum_update(checksum, &fixed_value, 1);
        checksum = checksum_update(
            checksum, (const uint8_t *)&quiet_count, sizeof(quiet_count)
        );
        if (fixed_value == 2 && quiet_count != 0) {
            ok = false;
            break;
        }
        for (uint16_t edge = 0; ok && edge < quiet_count; ++edge) {
            uint32_t child;
            ok = fread(&child, sizeof(child), 1, file) == 1 &&
                child < tablebase->signatures[signature_index].byte_count;
            if (!ok) break;
            checksum = checksum_update(
                checksum, (const uint8_t *)&child, sizeof(child)
            );
            ++edges;
        }
    }
    if (ok && fgetc(file) != EOF) {
        ok = false;
    }
    fclose(file);
    if (!ok || edges != header.edge_count || checksum != header.checksum) {
        return -1;
    }
    return 1;
}

static bool build_six_transition_part(
    CompactTablebase *six_piece,
    const CompactTablebase *four_piece,
    const CompactTablebase *five_piece,
    const bool *built,
    uint32_t signature_index,
    uint32_t partition_index,
    uint64_t state_start,
    uint64_t state_count,
    uint64_t dependency_binding,
    const char *output_path
) {
    int existing = verify_six_transition_part(
        six_piece,
        signature_index,
        partition_index,
        state_start,
        state_count,
        dependency_binding,
        output_path
    );
    if (existing != 0) {
        return existing > 0;
    }
    char path[TB6_PATH_CAPACITY];
    char temporary[TB6_PATH_CAPACITY];
    if (
        !six_path(path, output_path, signature_index,
            "transition", partition_index, "") ||
        !six_path(temporary, output_path, signature_index,
            "transition", partition_index, ".tmp")
    ) {
        return false;
    }
    FILE *file = fopen(temporary, "wb+");
    if (file == NULL) {
        return false;
    }
    SixTransitionHeader header;
    memset(&header, 0, sizeof(header));
    memcpy(header.magic, TB6_TRANSITION_MAGIC, 8);
    header.version = TB6_VERSION;
    header.no_progress_plies = six_piece->no_progress_plies;
    header.signature_index = signature_index;
    header.partition_index = partition_index;
    memcpy(
        header.counts,
        six_piece->signatures[signature_index].count,
        4
    );
    header.state_start = state_start;
    header.state_count = state_count;
    header.dependency_binding = dependency_binding;
    bool ok = fwrite(&header, 1, sizeof(header), file) == sizeof(header);
    MoveList *moves = calloc(1, sizeof(*moves));
    uint32_t *quiet_children = malloc(
        (size_t)MAX_MOVES * sizeof(*quiet_children)
    );
    if (moves == NULL || quiet_children == NULL) {
        ok = false;
    }
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint64_t edge_count = 0;
    uint64_t cached_rank = UINT64_MAX;
    Position base;
    memset(&base, 0, sizeof(base));
    CompactSignature *signature =
        &six_piece->signatures[signature_index];
    for (uint64_t offset = 0; ok && offset < state_count; ++offset) {
        uint64_t state = state_start + offset;
        uint64_t rank = state / 2;
        if (rank != cached_rank) {
            base = compact_unrank(rank, signature);
            base.reversible_plies = 0;
            cached_rank = rank;
        }
        Position position = base;
        position.turn = (state & 1) != 0 ? BLACK : RED;
        generate_moves(position, moves);
        uint8_t fixed_value = 0;
        uint16_t quiet_count = 0;
        for (uint32_t move_index = 0;
             move_index < moves->count;
             ++move_index) {
            bool quiet;
            uint32_t quiet_child;
            uint8_t child_value;
            if (!classify_six_child(
                    six_piece,
                    four_piece,
                    five_piece,
                    built,
                    signature_index,
                    moves->moves[move_index].next,
                    &quiet,
                    &quiet_child,
                    &child_value
                )) {
                ok = false;
                break;
            }
            if (quiet) {
                if (quiet_count >= MAX_MOVES) {
                    ok = false;
                    break;
                }
                quiet_children[quiet_count++] = quiet_child;
            } else {
                uint8_t candidate = invert_wdl(child_value);
                if (candidate > fixed_value) {
                    fixed_value = candidate;
                }
            }
        }
        if (!ok) break;
        if (fixed_value == 2) {
            quiet_count = 0;
        }
        ok =
            fwrite(&fixed_value, 1, 1, file) == 1 &&
            fwrite(&quiet_count, sizeof(quiet_count), 1, file) == 1;
        checksum = checksum_update(checksum, &fixed_value, 1);
        checksum = checksum_update(
            checksum, (const uint8_t *)&quiet_count, sizeof(quiet_count)
        );
        if (
            ok && quiet_count != 0 &&
            fwrite(
                quiet_children,
                sizeof(*quiet_children),
                quiet_count,
                file
            ) != quiet_count
        ) {
            ok = false;
        }
        if (ok && quiet_count != 0) {
            checksum = checksum_update(
                checksum,
                (const uint8_t *)quiet_children,
                (size_t)quiet_count * sizeof(*quiet_children)
            );
            edge_count += quiet_count;
        }
    }
    free(quiet_children);
    free(moves);
    header.edge_count = edge_count;
    header.checksum = checksum;
    if (ok && fseek(file, 0, SEEK_SET) != 0) {
        ok = false;
    }
    if (ok && fwrite(&header, 1, sizeof(header), file) != sizeof(header)) {
        ok = false;
    }
    if (fclose(file) != 0) {
        ok = false;
    }
    if (!ok || !makhos_replace_file_atomically(temporary, path)) {
        remove(temporary);
        return false;
    }
    return true;
}

static bool evaluate_six_transition_part(
    CompactSignature *signature,
    uint32_t no_progress_plies,
    uint32_t signature_index,
    uint32_t partition_index,
    uint64_t state_start,
    uint64_t state_count,
    uint64_t dependency_binding,
    const char *output_path,
    int clock,
    const uint8_t *next_layer,
    uint8_t *current_layer
) {
    char path[TB6_PATH_CAPACITY];
    if (!six_path(
            path, output_path, signature_index,
            "transition", partition_index, ""
        )) {
        return false;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return false;
    }
    CompactTablebase header_tablebase;
    memset(&header_tablebase, 0, sizeof(header_tablebase));
    header_tablebase.no_progress_plies = no_progress_plies;
    header_tablebase.signatures[signature_index] = *signature;
    SixTransitionHeader header;
    bool ok = read_six_transition_header(
        file,
        &header_tablebase,
        signature_index,
        partition_index,
        state_start,
        state_count,
        dependency_binding,
        &header
    );
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint64_t edges = 0;
    for (uint64_t offset = 0; ok && offset < state_count; ++offset) {
        uint8_t fixed_value;
        uint16_t quiet_count;
        ok =
            fread(&fixed_value, 1, 1, file) == 1 &&
            fread(&quiet_count, sizeof(quiet_count), 1, file) == 1 &&
            fixed_value <= 2 &&
            quiet_count <= MAX_MOVES;
        if (!ok) break;
        checksum = checksum_update(checksum, &fixed_value, 1);
        checksum = checksum_update(
            checksum, (const uint8_t *)&quiet_count, sizeof(quiet_count)
        );
        uint8_t value = fixed_value;
        for (uint16_t edge = 0; ok && edge < quiet_count; ++edge) {
            uint32_t child;
            ok = fread(&child, sizeof(child), 1, file) == 1 &&
                child < signature->byte_count;
            if (!ok) break;
            checksum = checksum_update(
                checksum, (const uint8_t *)&child, sizeof(child)
            );
            uint8_t candidate = invert_wdl(next_layer[child]);
            if (candidate > value) {
                value = candidate;
            }
            ++edges;
        }
        if (!ok) break;
        uint64_t state = state_start + offset;
        current_layer[state] = value;
        uint8_t encoded = signature->thresholds[state];
        if (value == 1) {
            if (encoded != 0) {
                ok = false;
                break;
            }
        } else if (encoded == 0) {
            encoded = (uint8_t)(clock + 1);
            if (value == 2) {
                encoded |= UINT8_C(0x80);
            }
            signature->thresholds[state] = encoded;
        } else if (((encoded & UINT8_C(0x80)) != 0 ? 2 : 0) != value) {
            ok = false;
            break;
        }
    }
    if (ok && fgetc(file) != EOF) {
        ok = false;
    }
    fclose(file);
    return ok && edges == header.edge_count && checksum == header.checksum;
}

static bool build_six_signature(
    CompactTablebase *six_piece,
    const CompactTablebase *four_piece,
    const CompactTablebase *five_piece,
    const bool *built,
    uint32_t signature_index,
    uint64_t partition_states,
    uint32_t layer_checkpoint_interval,
    uint64_t dependency_binding,
    const char *output_path
) {
    CompactSignature *signature = &six_piece->signatures[signature_index];
    if (!allocate_six_thresholds(signature)) {
        return false;
    }
    uint64_t state_count = signature->byte_count;
    uint64_t partition_count = partition_count_for_states(
        state_count, partition_states
    );
    if (partition_count == 0 || partition_count > UINT32_MAX) {
        return false;
    }
    fprintf(
        stderr,
        "six signature %u/%u [%u,%u,%u,%u] roots=%" PRIu64
        " partitions=%" PRIu64 "\n",
        signature_index + 1,
        six_piece->signature_count,
        signature->count[0], signature->count[1],
        signature->count[2], signature->count[3],
        state_count,
        partition_count
    );
    uint64_t transition_errors = 0;
#ifdef _OPENMP
#pragma omp parallel for schedule(dynamic) reduction(+:transition_errors)
#endif
    for (int64_t signed_partition = 0;
         signed_partition < (int64_t)partition_count;
         ++signed_partition) {
        uint32_t partition_index = (uint32_t)signed_partition;
        uint64_t state_start =
            (uint64_t)partition_index * partition_states;
        uint64_t count = state_count - state_start;
        if (count > partition_states) count = partition_states;
        if (!build_six_transition_part(
                six_piece,
                four_piece,
                five_piece,
                built,
                signature_index,
                partition_index,
                state_start,
                count,
                dependency_binding,
                output_path
            )) {
            ++transition_errors;
        }
    }
    if (transition_errors != 0) {
        fprintf(stderr, "six transition part failures: %" PRIu64 "\n",
            transition_errors);
        return false;
    }
    uint8_t *next_layer = malloc((size_t)state_count);
    uint8_t *current_layer = malloc((size_t)state_count);
    if (next_layer == NULL || current_layer == NULL) {
        free(next_layer);
        free(current_layer);
        return false;
    }
    memset(next_layer, 1, (size_t)state_count);
    int start_clock = (int)six_piece->no_progress_plies - 1;
    int resumed = read_six_layer_checkpoint(
        six_piece,
        signature_index,
        dependency_binding,
        output_path,
        next_layer,
        &start_clock
    );
    if (resumed < 0) {
        free(next_layer);
        free(current_layer);
        return false;
    }
    for (int clock = start_clock;
         clock >= 0;
         --clock) {
        uint64_t layer_errors = 0;
#ifdef _OPENMP
#pragma omp parallel for schedule(dynamic) reduction(+:layer_errors)
#endif
        for (int64_t signed_partition = 0;
             signed_partition < (int64_t)partition_count;
             ++signed_partition) {
            uint32_t partition_index = (uint32_t)signed_partition;
            uint64_t state_start =
                (uint64_t)partition_index * partition_states;
            uint64_t count = state_count - state_start;
            if (count > partition_states) count = partition_states;
            if (!evaluate_six_transition_part(
                    signature,
                    six_piece->no_progress_plies,
                    signature_index,
                    partition_index,
                    state_start,
                    count,
                    dependency_binding,
                    output_path,
                    clock,
                    next_layer,
                    current_layer
                )) {
                ++layer_errors;
            }
        }
        if (layer_errors != 0) {
            fprintf(stderr, "six layer %d failures: %" PRIu64 "\n",
                clock, layer_errors);
            free(next_layer);
            free(current_layer);
            return false;
        }
        uint8_t *swap = next_layer;
        next_layer = current_layer;
        current_layer = swap;
        fprintf(stderr, "six signature %u clock %d complete\n",
            signature_index + 1, clock);
        uint32_t completed_layers =
            six_piece->no_progress_plies - (uint32_t)clock;
        if (
            completed_layers % layer_checkpoint_interval == 0 ||
            clock == 0
        ) {
            if (!write_six_layer_checkpoint(
                    six_piece,
                    signature_index,
                    dependency_binding,
                    output_path,
                    clock - 1,
                    next_layer
                )) {
                free(next_layer);
                free(current_layer);
                return false;
            }
        }
    }
    free(next_layer);
    free(current_layer);
    if (!write_six_signature_part(
            six_piece,
            signature_index,
            dependency_binding,
            output_path
        )) {
        return false;
    }
    remove_six_layer_checkpoints(
        six_piece,
        signature_index,
        -2,
        output_path
    );
    for (uint32_t partition_index = 0;
         partition_index < (uint32_t)partition_count;
         ++partition_index) {
        char path[TB6_PATH_CAPACITY];
        if (six_path(
                path, output_path, signature_index,
                "transition", partition_index, ""
            )) {
            remove(path);
        }
    }
    return true;
}

static int command_build_six(
    int no_progress_plies,
    const char *four_path,
    const char *five_path,
    int tb3_hash_power,
    uint64_t partition_states,
    uint32_t layer_checkpoint_interval,
    uint32_t signature_limit,
    const char *output_path
) {
    CompactTablebase four_piece = {0};
    CompactTablebase five_piece = {0};
    CompactTablebase six_piece = {0};
    if (
        !read_compact_tablebase(&four_piece, four_path) ||
        !compact_tablebase_has_complete_schema(&four_piece, 4) ||
        (int)four_piece.no_progress_plies != no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible compact four-piece tablebase\n");
        return 2;
    }
    if (
        !read_compact_tablebase(&five_piece, five_path) ||
        !compact_tablebase_has_complete_schema(&five_piece, 5) ||
        (int)five_piece.no_progress_plies != no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible compact five-piece tablebase\n");
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    int dependency = makhos_tb3_init(no_progress_plies, tb3_hash_power);
    if (dependency != 0) {
        fprintf(stderr, "unable to initialize three-piece dependency: %d\n",
            dependency);
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (!initialize_six_piece_tablebase(&six_piece, no_progress_plies)) {
        makhos_tb3_shutdown();
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    uint64_t binding = six_dependency_binding(&four_piece, &five_piece);
    bool built[TB6_SIGNATURES] = {false};
    bool ok = true;
    for (uint32_t signature_index = 0;
         ok && signature_index < signature_limit;
         ++signature_index) {
        int resumed = read_six_signature_part(
            &six_piece,
            signature_index,
            binding,
            output_path
        );
        if (resumed < 0) {
            ok = false;
            break;
        }
        if (resumed == 0) {
            ok = build_six_signature(
                &six_piece,
                &four_piece,
                &five_piece,
                built,
                signature_index,
                partition_states,
                layer_checkpoint_interval,
                binding,
                output_path
            );
        }
        if (ok) built[signature_index] = true;
    }
    if (ok && signature_limit == TB6_SIGNATURES) {
        ok = write_compact_five_piece(&six_piece, output_path);
    }
    compact_tablebase_destroy(&six_piece);
    makhos_tb3_shutdown();
    compact_tablebase_destroy(&five_piece);
    compact_tablebase_destroy(&four_piece);
    return ok ? 0 : 3;
}

static bool evaluate_six_direct(
    const CompactTablebase *six_piece,
    const CompactTablebase *four_piece,
    const CompactTablebase *five_piece,
    const bool *built,
    Position position,
    MoveList *moves,
    uint8_t *value
) {
    if (position.reversible_plies >= six_piece->no_progress_plies) {
        *value = 1;
        return true;
    }
    generate_moves(position, moves);
    if (moves->count == 0) {
        *value = 0;
        return true;
    }
    *value = 0;
    for (uint32_t move_index = 0;
         move_index < moves->count;
         ++move_index) {
        Position child = moves->moves[move_index].next;
        uint8_t child_value;
        if (child.red == 0 || child.black == 0) {
            child_value = 0;
        } else {
            int pieces = count_bits(occupied(child));
            if (pieces <= 3) {
                if (!probe_three_piece_readonly(child, &child_value)) {
                    return false;
                }
            } else if (pieces == 4) {
                if (!probe_compact_position(
                        four_piece, child, &child_value
                    )) {
                    return false;
                }
            } else if (pieces == 5) {
                if (!probe_compact_position(
                        five_piece, child, &child_value
                    )) {
                    return false;
                }
            } else if (pieces == 6) {
                uint8_t counts[4];
                signature_for_position(child, counts);
                int child_signature_index = six_piece->signature_index
                    [counts[0]][counts[1]][counts[2]][counts[3]];
                if (
                    child_signature_index < 0 ||
                    !built[child_signature_index]
                ) {
                    return false;
                }
                const CompactSignature *child_signature =
                    &six_piece->signatures[child_signature_index];
                uint64_t child_rank = compact_rank(child, child_signature);
                child_value = get_compact_wdl(
                    child_signature,
                    child_rank,
                    child.turn,
                    child.reversible_plies
                );
            } else {
                return false;
            }
        }
        uint8_t candidate = invert_wdl(child_value);
        if (candidate > *value) {
            *value = candidate;
            if (*value == 2) break;
        }
    }
    return true;
}

/*
 * A compact WDL byte is a single decisive-to-draw threshold.  Captures,
 * promotions, and moves to a lower material table reset the clock and are
 * represented by fixed_value.  Same-signature quiet moves consult their
 * child byte one clock later.  This derives the complete Bellman result for
 * every clock without iterating over all no-progress layers.
 */
static bool derive_six_threshold(
    uint32_t no_progress_plies,
    uint8_t fixed_value,
    const uint8_t *quiet_children,
    uint32_t quiet_count,
    uint8_t *encoded_output
) {
    if (
        no_progress_plies < 1 ||
        no_progress_plies > 126 ||
        fixed_value > 2 ||
        quiet_count > MAX_MOVES ||
        encoded_output == NULL ||
        (quiet_count != 0 && quiet_children == NULL)
    ) {
        return false;
    }
    for (uint32_t index = 0; index < quiet_count; ++index) {
        uint8_t encoded = quiet_children[index];
        if (
            encoded != 0 &&
            ((encoded & UINT8_C(0x7f)) == 0 ||
             (encoded & UINT8_C(0x7f)) > no_progress_plies)
        ) {
            return false;
        }
    }

    if (fixed_value == 2) {
        *encoded_output = UINT8_C(0x80) | (uint8_t)no_progress_plies;
        return true;
    }

    uint8_t win_boundary = 0;
    for (uint32_t index = 0; index < quiet_count; ++index) {
        uint8_t encoded = quiet_children[index];
        uint8_t boundary = encoded & UINT8_C(0x7f);
        if (
            encoded != 0 &&
            (encoded & UINT8_C(0x80)) == 0 &&
            boundary >= 2
        ) {
            uint8_t candidate = (uint8_t)(boundary - 1);
            if (candidate > win_boundary) {
                win_boundary = candidate;
            }
        }
    }
    if (win_boundary != 0) {
        *encoded_output = UINT8_C(0x80) | win_boundary;
        return true;
    }
    if (fixed_value == 1) {
        *encoded_output = 0;
        return true;
    }
    if (quiet_count == 0) {
        *encoded_output = (uint8_t)no_progress_plies;
        return true;
    }

    uint8_t loss_boundary = (uint8_t)no_progress_plies;
    for (uint32_t index = 0; index < quiet_count; ++index) {
        uint8_t encoded = quiet_children[index];
        uint8_t boundary = encoded & UINT8_C(0x7f);
        if (
            encoded == 0 ||
            (encoded & UINT8_C(0x80)) == 0 ||
            boundary < 2
        ) {
            *encoded_output = 0;
            return true;
        }
        uint8_t candidate = (uint8_t)(boundary - 1);
        if (candidate < loss_boundary) {
            loss_boundary = candidate;
        }
    }
    *encoded_output = loss_boundary;
    return true;
}

static uint8_t six_threshold_value_at(uint8_t encoded, uint32_t clock) {
    if (
        encoded == 0 ||
        clock >= (uint32_t)(encoded & UINT8_C(0x7f))
    ) {
        return 1;
    }
    return (encoded & UINT8_C(0x80)) != 0 ? 2 : 0;
}

static bool brute_force_six_threshold(
    uint32_t no_progress_plies,
    uint8_t fixed_value,
    const uint8_t *quiet_children,
    uint32_t quiet_count,
    uint8_t *encoded_output
) {
    uint8_t decisive_value = 1;
    uint8_t boundary = 0;
    bool draw_seen = false;
    for (uint32_t clock = 0; clock < no_progress_plies; ++clock) {
        uint8_t value = fixed_value;
        for (uint32_t index = 0; index < quiet_count; ++index) {
            uint8_t candidate = invert_wdl(
                six_threshold_value_at(quiet_children[index], clock + 1)
            );
            if (candidate > value) value = candidate;
        }
        if (clock == 0) decisive_value = value;
        if (decisive_value == 1) {
            if (value != 1) return false;
            continue;
        }
        if (value == decisive_value && !draw_seen) {
            ++boundary;
        } else if (value == 1) {
            draw_seen = true;
        } else {
            return false;
        }
    }
    if (decisive_value == 1) {
        *encoded_output = 0;
    } else {
        *encoded_output = boundary |
            (decisive_value == 2 ? UINT8_C(0x80) : 0);
    }
    return true;
}

static bool six_threshold_expected(
    uint32_t no_progress_plies,
    uint8_t fixed_value,
    const uint8_t *quiet_children,
    uint32_t quiet_count,
    uint8_t expected
) {
    uint8_t actual = 0;
    return derive_six_threshold(
        no_progress_plies,
        fixed_value,
        quiet_children,
        quiet_count,
        &actual
    ) && actual == expected;
}

static int command_verify_six_threshold_logic(void) {
    const uint8_t loss_10[] = {10};
    const uint8_t losses_10_20[] = {10, 20};
    const uint8_t wins_10_20[] = {
        UINT8_C(0x80) | 10,
        UINT8_C(0x80) | 20
    };
    const uint8_t win_1[] = {UINT8_C(0x80) | 1};
    const uint8_t win_10_draw[] = {UINT8_C(0x80) | 10, 0};
    if (
        !six_threshold_expected(80, 0, NULL, 0, 80) ||
        !six_threshold_expected(80, 2, NULL, 0, UINT8_C(0x80) | 80) ||
        !six_threshold_expected(80, 1, NULL, 0, 0) ||
        !six_threshold_expected(80, 0, loss_10, 1, UINT8_C(0x80) | 9) ||
        !six_threshold_expected(
            80, 0, losses_10_20, 2, UINT8_C(0x80) | 19
        ) ||
        !six_threshold_expected(80, 0, wins_10_20, 2, 9) ||
        !six_threshold_expected(80, 0, win_1, 1, 0) ||
        !six_threshold_expected(80, 0, win_10_draw, 2, 0) ||
        !six_threshold_expected(80, 1, loss_10, 1, UINT8_C(0x80) | 9) ||
        !six_threshold_expected(1, 0, win_1, 1, 0)
    ) {
        fprintf(stderr, "six threshold unit vector failed\n");
        return 3;
    }

    uint64_t checked = 0;
    for (uint32_t no_progress = 1; no_progress <= 6; ++no_progress) {
        uint8_t variants[13];
        uint32_t variant_count = 0;
        variants[variant_count++] = 0;
        for (uint32_t boundary = 1; boundary <= no_progress; ++boundary) {
            variants[variant_count++] = (uint8_t)boundary;
            variants[variant_count++] =
                UINT8_C(0x80) | (uint8_t)boundary;
        }
        for (uint8_t fixed_value = 0; fixed_value <= 2; ++fixed_value) {
            for (uint32_t quiet_count = 0; quiet_count <= 3; ++quiet_count) {
                uint64_t combinations = 1;
                for (uint32_t index = 0; index < quiet_count; ++index) {
                    combinations *= variant_count;
                }
                for (uint64_t code = 0; code < combinations; ++code) {
                    uint8_t quiet_children[3] = {0, 0, 0};
                    uint64_t remaining = code;
                    for (uint32_t index = 0; index < quiet_count; ++index) {
                        quiet_children[index] = variants[
                            remaining % variant_count
                        ];
                        remaining /= variant_count;
                    }
                    uint8_t derived;
                    uint8_t brute;
                    if (
                        !derive_six_threshold(
                            no_progress,
                            fixed_value,
                            quiet_children,
                            quiet_count,
                            &derived
                        ) ||
                        !brute_force_six_threshold(
                            no_progress,
                            fixed_value,
                            quiet_children,
                            quiet_count,
                            &brute
                        ) ||
                        derived != brute
                    ) {
                        fprintf(
                            stderr,
                            "six threshold exhaustive case failed "
                            "N=%u fixed=%u quiet=%u code=%" PRIu64 "\n",
                            no_progress,
                            fixed_value,
                            quiet_count,
                            code
                        );
                        return 3;
                    }
                    ++checked;
                }
            }
        }
    }
    uint8_t invalid = UINT8_C(0x80);
    uint8_t ignored;
    if (
        derive_six_threshold(0, 0, NULL, 0, &ignored) ||
        derive_six_threshold(127, 0, NULL, 0, &ignored) ||
        derive_six_threshold(80, 3, NULL, 0, &ignored) ||
        derive_six_threshold(80, 0, &invalid, 1, &ignored)
    ) {
        fprintf(stderr, "six threshold invalid-input check failed\n");
        return 3;
    }
    printf("six threshold unit vectors: PASS\n");
    printf("six threshold exhaustive formula cases: %" PRIu64 "\n", checked);
    return 0;
}

static int command_verify_six_prefix(
    int no_progress_plies,
    const char *four_path,
    const char *five_path,
    int tb3_hash_power,
    uint32_t signature_limit,
    int clock,
    const char *output_path
) {
    CompactTablebase four_piece;
    CompactTablebase five_piece;
    CompactTablebase six_piece;
    if (
        !read_compact_tablebase(&four_piece, four_path) ||
        !compact_tablebase_has_complete_schema(&four_piece, 4) ||
        (int)four_piece.no_progress_plies != no_progress_plies
    ) {
        return 2;
    }
    if (
        !read_compact_tablebase(&five_piece, five_path) ||
        !compact_tablebase_has_complete_schema(&five_piece, 5) ||
        (int)five_piece.no_progress_plies != no_progress_plies
    ) {
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (makhos_tb3_init(no_progress_plies, tb3_hash_power) != 0) {
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (!initialize_six_piece_tablebase(&six_piece, no_progress_plies)) {
        makhos_tb3_shutdown();
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    uint64_t binding = six_dependency_binding(&four_piece, &five_piece);
    bool built[TB6_SIGNATURES] = {false};
    bool ok = true;
    for (uint32_t signature_index = 0;
         ok && signature_index < signature_limit;
         ++signature_index) {
        int resumed = read_six_signature_part(
            &six_piece, signature_index, binding, output_path
        );
        if (resumed != 1) {
            ok = false;
        } else {
            built[signature_index] = true;
        }
    }
    uint64_t counts[3] = {0, 0, 0};
    uint64_t checked = 0;
    uint64_t errors = 0;
    for (uint32_t signature_index = 0;
         ok && signature_index < signature_limit;
         ++signature_index) {
        CompactSignature *signature =
            &six_piece.signatures[signature_index];
        uint64_t signature_counts[3] = {0, 0, 0};
        uint64_t signature_checked = 0;
        uint64_t signature_errors = 0;
#ifdef _OPENMP
#pragma omp parallel reduction(+:signature_checked,signature_errors) \
    reduction(+:signature_counts[:3])
#endif
        {
            MoveList *moves = calloc(1, sizeof(*moves));
            if (moves == NULL) {
                ++signature_errors;
            }
#ifdef _OPENMP
#pragma omp for schedule(static)
#endif
            for (int64_t signed_rank = 0;
                 signed_rank < (int64_t)signature->boards;
                 ++signed_rank) {
                if (moves == NULL) continue;
                uint64_t rank = (uint64_t)signed_rank;
                Position base = compact_unrank(rank, signature);
                base.reversible_plies = (uint8_t)clock;
                for (int turn = RED; turn <= BLACK; ++turn) {
                    Position position = base;
                    position.turn = (uint8_t)turn;
                    uint8_t expected;
                    if (!evaluate_six_direct(
                            &six_piece,
                            &four_piece,
                            &five_piece,
                            built,
                            position,
                            moves,
                            &expected
                        )) {
                        ++signature_errors;
                        continue;
                    }
                    uint8_t actual = get_compact_wdl(
                        signature, rank, turn, clock
                    );
                    if (actual != expected) {
                        ++signature_errors;
                    } else {
                        ++signature_counts[actual];
                    }
                    ++signature_checked;
                }
            }
            free(moves);
        }
        counts[0] += signature_counts[0];
        counts[1] += signature_counts[1];
        counts[2] += signature_counts[2];
        checked += signature_checked;
        errors += signature_errors;
        printf(
            "verified six signature %u roots=%" PRIu64
            " errors=%" PRIu64 "\n",
            signature_index + 1,
            signature_checked,
            signature_errors
        );
    }
    printf("six-piece roots checked: %" PRIu64 "\n", checked);
    printf("six-piece W/D/L: %" PRIu64 "/%" PRIu64 "/%" PRIu64 "\n",
        counts[2], counts[1], counts[0]);
    printf("six-piece verification errors: %" PRIu64 "\n", errors);
    compact_tablebase_destroy(&six_piece);
    makhos_tb3_shutdown();
    compact_tablebase_destroy(&five_piece);
    compact_tablebase_destroy(&four_piece);
    return ok && errors == 0 ? 0 : 3;
}

static int command_verify_six_thresholds(
    const char *four_path,
    const char *five_path,
    const char *six_pathname,
    int tb3_hash_power,
    uint64_t rank_stride
) {
    CompactTablebase four_piece = {0};
    CompactTablebase five_piece = {0};
    CompactTablebase six_piece = {0};
    if (
        !read_compact_tablebase(&four_piece, four_path) ||
        four_piece.piece_count != 4 ||
        four_piece.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read complete compact four-piece tablebase\n");
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (
        !read_compact_tablebase(&five_piece, five_path) ||
        five_piece.piece_count != 5 ||
        five_piece.signature_count != TB5_SIGNATURES ||
        five_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read complete compatible five-piece tablebase\n");
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (
        !read_compact_tablebase(&six_piece, six_pathname) ||
        six_piece.piece_count != 6 ||
        six_piece.signature_count != TB6_SIGNATURES ||
        six_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read complete compatible six-piece tablebase\n");
        compact_tablebase_destroy(&six_piece);
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (rank_stride == 0 || rank_stride > (uint64_t)INT64_MAX) {
        fprintf(stderr, "invalid six-piece threshold rank stride\n");
        compact_tablebase_destroy(&six_piece);
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 1;
    }
    int dependency = makhos_tb3_init(
        (int)six_piece.no_progress_plies, tb3_hash_power
    );
    if (dependency != 0) {
        fprintf(
            stderr,
            "unable to initialize three-piece dependency: %d\n",
            dependency
        );
        compact_tablebase_destroy(&six_piece);
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }

    bool built[TB6_SIGNATURES];
    for (uint32_t index = 0; index < TB6_SIGNATURES; ++index) {
        built[index] = true;
    }
    uint64_t checked = 0;
    uint64_t errors = 0;
    uint64_t rank_errors = 0;
    for (uint32_t signature_index = 0;
         signature_index < six_piece.signature_count;
         ++signature_index) {
        CompactSignature *signature =
            &six_piece.signatures[signature_index];
        uint64_t signature_checked = 0;
        uint64_t signature_errors = 0;
        uint64_t signature_rank_errors = 0;
#ifdef _OPENMP
#pragma omp parallel reduction(+:signature_checked,signature_errors,signature_rank_errors)
#endif
        {
            MoveList *moves = calloc(1, sizeof(*moves));
            if (moves == NULL) {
                ++signature_errors;
            }
#ifdef _OPENMP
#pragma omp for schedule(static)
#endif
            for (int64_t signed_rank = 0;
                 signed_rank < (int64_t)signature->boards;
                 signed_rank += (int64_t)rank_stride) {
                uint64_t rank = (uint64_t)signed_rank;
                Position base = compact_unrank(rank, signature);
                if (compact_rank(base, signature) != rank) {
                    ++signature_rank_errors;
                    signature_checked += 2;
                    continue;
                }
                if (moves == NULL) {
                    signature_checked += 2;
                    continue;
                }
                base.reversible_plies = 0;
                for (int turn = RED; turn <= BLACK; ++turn) {
                    Position position = base;
                    position.turn = (uint8_t)turn;
                    generate_moves(position, moves);
                    uint8_t fixed_value = 0;
                    uint8_t quiet_children[MAX_MOVES];
                    uint32_t quiet_count = 0;
                    bool state_ok = true;
                    for (uint32_t move_index = 0;
                         move_index < moves->count;
                         ++move_index) {
                        Position child = moves->moves[move_index].next;
                        bool quiet;
                        uint32_t quiet_child;
                        uint8_t child_value;
                        if (!classify_six_child(
                                &six_piece,
                                &four_piece,
                                &five_piece,
                                built,
                                signature_index,
                                child,
                                &quiet,
                                &quiet_child,
                                &child_value
                            )) {
                            state_ok = false;
                            break;
                        }
                        if (quiet) {
                            if (
                                child.reversible_plies != 1 ||
                                quiet_count >= MAX_MOVES ||
                                quiet_child >= signature->byte_count
                            ) {
                                state_ok = false;
                                break;
                            }
                            quiet_children[quiet_count++] =
                                signature->thresholds[quiet_child];
                        } else {
                            if (child.reversible_plies != 0) {
                                state_ok = false;
                                break;
                            }
                            uint8_t candidate = invert_wdl(child_value);
                            if (candidate > fixed_value) {
                                fixed_value = candidate;
                            }
                        }
                    }
                    uint8_t expected = 0;
                    if (
                        !state_ok ||
                        !derive_six_threshold(
                            six_piece.no_progress_plies,
                            fixed_value,
                            quiet_children,
                            quiet_count,
                            &expected
                        ) ||
                        expected != signature->thresholds[
                            rank * 2 + (turn == BLACK ? 1 : 0)
                        ]
                    ) {
                        ++signature_errors;
                    }
                    ++signature_checked;
                }
            }
            free(moves);
        }
        checked += signature_checked;
        errors += signature_errors;
        rank_errors += signature_rank_errors;
        printf(
            "verified six thresholds %u roots=%" PRIu64
            " errors=%" PRIu64 " rank-errors=%" PRIu64 "\n",
            signature_index + 1,
            signature_checked,
            signature_errors,
            signature_rank_errors
        );
    }
    printf("six-piece threshold roots checked: %" PRIu64 "\n", checked);
    printf("six-piece threshold Bellman errors: %" PRIu64 "\n", errors);
    printf("six-piece rank roundtrip errors: %" PRIu64 "\n", rank_errors);
    printf("six-piece threshold rank stride: %" PRIu64 "\n", rank_stride);
    makhos_tb3_shutdown();
    compact_tablebase_destroy(&six_piece);
    compact_tablebase_destroy(&five_piece);
    compact_tablebase_destroy(&four_piece);
    return errors == 0 && rank_errors == 0 ? 0 : 3;
}

static int command_probe_six(
    const char *path,
    const char *text,
    int clock
) {
    CompactTablebase tablebase;
    if (!read_compact_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read compact six-piece tablebase\n");
        return 2;
    }
    Position position;
    if (
        tablebase.piece_count != 6 ||
        !parse_position(text, &position) ||
        count_bits(occupied(position)) != 6
    ) {
        fprintf(stderr, "probe requires a valid six-piece position\n");
        compact_tablebase_destroy(&tablebase);
        return 1;
    }
    if (clock < 0 || clock > (int)tablebase.no_progress_plies) {
        fprintf(stderr, "clock outside tablebase range\n");
        compact_tablebase_destroy(&tablebase);
        return 1;
    }
    position.reversible_plies = (uint8_t)clock;
    uint8_t value;
    if (!probe_compact_position(&tablebase, position, &value)) {
        fprintf(stderr, "position must contain pieces from both sides\n");
        compact_tablebase_destroy(&tablebase);
        return 1;
    }
    printf("outcome: %s\n", wdl_name(value));
    compact_tablebase_destroy(&tablebase);
    return 0;
}

static uint32_t rotate_six_bits(uint32_t bits) {
    uint32_t rotated = 0;
    for (int square = 0; square < 32; ++square) {
        if ((bits & (UINT32_C(1) << square)) != 0) {
            rotated |= UINT32_C(1) << (31 - square);
        }
    }
    return rotated;
}

static Position rotate_and_swap_six_position(Position position) {
    Position transformed;
    transformed.red = rotate_six_bits(position.black);
    transformed.black = rotate_six_bits(position.red);
    transformed.kings = rotate_six_bits(position.kings);
    transformed.turn = other(position.turn);
    transformed.reversible_plies = position.reversible_plies;
    return transformed;
}

static int command_verify_six_symmetry(
    const char *path,
    int clock,
    uint64_t rank_stride
) {
    CompactTablebase tablebase;
    if (!read_compact_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read compact six-piece tablebase\n");
        return 2;
    }
    if (
        tablebase.piece_count != 6 ||
        clock < 0 ||
        clock > (int)tablebase.no_progress_plies ||
        rank_stride == 0
    ) {
        fprintf(stderr, "invalid six-piece tablebase, clock, or stride\n");
        compact_tablebase_destroy(&tablebase);
        return 1;
    }
    uint64_t checked = 0;
    uint64_t errors = 0;
    for (uint32_t signature_index = 0;
         signature_index < tablebase.signature_count;
         ++signature_index) {
        CompactSignature *signature = &tablebase.signatures[signature_index];
        uint64_t signature_checked = 0;
        uint64_t signature_errors = 0;
#ifdef _OPENMP
#pragma omp parallel for schedule(static) reduction(+:signature_checked,signature_errors)
#endif
        for (int64_t signed_rank = 0;
             signed_rank < (int64_t)signature->boards;
             signed_rank += (int64_t)rank_stride) {
            uint64_t rank = (uint64_t)signed_rank;
            Position base = compact_unrank(rank, signature);
            base.reversible_plies = (uint8_t)clock;
            for (int turn = RED; turn <= BLACK; ++turn) {
                base.turn = (uint8_t)turn;
                uint8_t actual = get_compact_wdl(
                    signature,
                    rank,
                    turn,
                    clock
                );
                Position transformed = rotate_and_swap_six_position(base);
                uint8_t symmetric;
                if (
                    !probe_compact_position(
                        &tablebase,
                        transformed,
                        &symmetric
                    ) ||
                    symmetric != actual
                ) {
                    ++signature_errors;
                }
                ++signature_checked;
            }
        }
        checked += signature_checked;
        errors += signature_errors;
        printf(
            "verified six symmetry %u states=%" PRIu64
            " errors=%" PRIu64 "\n",
            signature_index + 1,
            signature_checked,
            signature_errors
        );
    }
    printf("six-piece symmetry states checked: %" PRIu64 "\n", checked);
    printf("six-piece symmetry errors: %" PRIu64 "\n", errors);
    compact_tablebase_destroy(&tablebase);
    return errors == 0 ? 0 : 3;
}

static int command_rebase_six_dfpn(
    const char *four_path,
    const char *five_path,
    const char *six_pathname,
    const char *input_path,
    const char *output_path
) {
    RankedTablebase four_piece;
    CompactTablebase five_piece;
    CompactTablebase six_piece;
    if (
        !read_tablebase(&four_piece, four_path) ||
        four_piece.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read full four-piece tablebase\n");
        return 2;
    }
    if (
        !read_compact_tablebase(&five_piece, five_path) ||
        !compact_tablebase_has_complete_schema(&five_piece, 5) ||
        five_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible five-piece frontier\n");
        compact_tablebase_destroy(&five_piece);
        tablebase_destroy(&four_piece);
        return 2;
    }
    if (
        !read_compact_tablebase(&six_piece, six_pathname) ||
        !compact_tablebase_has_complete_schema(&six_piece, 6) ||
        six_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible six-piece frontier\n");
        compact_tablebase_destroy(&six_piece);
        compact_tablebase_destroy(&five_piece);
        tablebase_destroy(&four_piece);
        return 2;
    }
    DfpnContext context;
    memset(&context, 0, sizeof(context));
    context.tablebase = &four_piece;
    context.frontiers[0] = &five_piece;
    context.frontier_count = 1;
    uint64_t input_binding = dfpn_tablebase_binding(&context);
    context.frontiers[1] = &six_piece;
    context.frontier_count = 2;
    uint64_t binding = dfpn_tablebase_binding(&context);
    int result = compact_dfpn_checkpoint(
        input_path,
        output_path,
        true,
        true,
        binding,
        true,
        input_binding,
        true,
        four_piece.no_progress_plies,
        false,
        (Position){0}
    );
    if (result == 0) {
        printf("DFPN checkpoint input tablebases: %016" PRIx64 "\n",
            input_binding);
        printf("DFPN checkpoint rebound tablebases: %016" PRIx64 "\n",
            binding);
    }
    compact_tablebase_destroy(&six_piece);
    compact_tablebase_destroy(&five_piece);
    tablebase_destroy(&four_piece);
    return result;
}

static int command_retarget_six_dfpn(
    const char *four_path,
    const char *five_path,
    const char *six_pathname,
    const char *input_path,
    const char *output_path,
    const char *position_text,
    const char *clock_text
) {
    Position replacement_root;
    int clock;
    if (
        strcmp(input_path, output_path) == 0 ||
        !parse_position(position_text, &replacement_root) ||
        !parse_bounded_int(clock_text, 0, 126, &clock)
    ) {
        fprintf(stderr, "invalid distinct output path, position, or clock\n");
        return 1;
    }

    RankedTablebase four_piece;
    CompactTablebase five_piece;
    CompactTablebase six_piece;
    if (
        !read_tablebase(&four_piece, four_path) ||
        four_piece.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read full four-piece tablebase\n");
        return 2;
    }
    if (
        !read_compact_tablebase(&five_piece, five_path) ||
        !compact_tablebase_has_complete_schema(&five_piece, 5) ||
        five_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible five-piece frontier\n");
        compact_tablebase_destroy(&five_piece);
        tablebase_destroy(&four_piece);
        return 2;
    }
    if (
        !read_compact_tablebase(&six_piece, six_pathname) ||
        !compact_tablebase_has_complete_schema(&six_piece, 6) ||
        six_piece.no_progress_plies != four_piece.no_progress_plies ||
        clock > (int)four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible six-piece frontier or clock\n");
        compact_tablebase_destroy(&six_piece);
        compact_tablebase_destroy(&five_piece);
        tablebase_destroy(&four_piece);
        return 2;
    }
    replacement_root.reversible_plies = (uint8_t)clock;

    DfpnContext context;
    memset(&context, 0, sizeof(context));
    context.tablebase = &four_piece;
    context.frontiers[0] = &five_piece;
    context.frontiers[1] = &six_piece;
    context.frontier_count = 2;
    uint64_t binding = dfpn_tablebase_binding(&context);
    int result = compact_dfpn_checkpoint(
        input_path,
        output_path,
        true,
        false,
        0,
        true,
        binding,
        true,
        four_piece.no_progress_plies,
        true,
        replacement_root
    );
    if (result == 0) {
        printf("DFPN checkpoint tablebases: %016" PRIx64 "\n", binding);
        printf("DFPN checkpoint retained exact solved seed only\n");
    }
    compact_tablebase_destroy(&six_piece);
    compact_tablebase_destroy(&five_piece);
    tablebase_destroy(&four_piece);
    return result;
}

static int command_export_six_strategy(
    const char *four_path,
    const char *five_path,
    const char *six_pathname,
    const char *checkpoint_path,
    const char *output_path,
    int hash_power,
    bool all_choices
) {
    RankedTablebase four_piece;
    CompactTablebase five_piece;
    CompactTablebase six_piece;
    if (
        !read_tablebase(&four_piece, four_path) ||
        four_piece.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read full four-piece tablebase\n");
        return 2;
    }
    if (
        !read_compact_tablebase(&five_piece, five_path) ||
        !compact_tablebase_has_complete_schema(&five_piece, 5) ||
        five_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible five-piece frontier\n");
        compact_tablebase_destroy(&five_piece);
        tablebase_destroy(&four_piece);
        return 2;
    }
    if (
        !read_compact_tablebase(&six_piece, six_pathname) ||
        !compact_tablebase_has_complete_schema(&six_piece, 6) ||
        six_piece.no_progress_plies != four_piece.no_progress_plies
    ) {
        fprintf(stderr, "unable to read compatible six-piece frontier\n");
        compact_tablebase_destroy(&six_piece);
        compact_tablebase_destroy(&five_piece);
        tablebase_destroy(&four_piece);
        return 2;
    }
    DfpnContext context;
    memset(&context, 0, sizeof(context));
    context.tablebase = &four_piece;
    context.frontiers[0] = &five_piece;
    context.frontiers[1] = &six_piece;
    context.frontier_count = 2;
    int result = export_dfpn_strategy(
        checkpoint_path,
        output_path,
        hash_power,
        dfpn_tablebase_binding(&context),
        four_piece.checksum,
        five_piece.checksum,
        six_piece.checksum,
        four_piece.no_progress_plies,
        all_choices
    );
    compact_tablebase_destroy(&six_piece);
    compact_tablebase_destroy(&five_piece);
    tablebase_destroy(&four_piece);
    return result;
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "verify-native-hardening") == 0) {
        return command_verify_native_hardening(argv[2]);
    }
    if (argc == 3 && strcmp(argv[1], "verify-dfpn-disk-backing") == 0) {
        return command_verify_dfpn_disk_backing(argv[2]);
    }
    if (argc == 2 && strcmp(argv[1], "verify-threshold-logic") == 0) {
        return command_verify_six_threshold_logic();
    }
    if (argc == 7 && strcmp(argv[1], "rebase-dfpn") == 0) {
        return command_rebase_six_dfpn(
            argv[2], argv[3], argv[4], argv[5], argv[6]
        );
    }
    if (argc == 9 && strcmp(argv[1], "retarget-dfpn-solved") == 0) {
        return command_retarget_six_dfpn(
            argv[2], argv[3], argv[4], argv[5], argv[6], argv[7], argv[8]
        );
    }
    if (argc == 9 && strcmp(argv[1], "export-strategy") == 0) {
        int hash_power;
        int all_choices;
        if (
            !parse_bounded_int(argv[7], 16, 29, &hash_power) ||
            !parse_bounded_int(argv[8], 0, 1, &all_choices)
        ) {
            fprintf(stderr, "invalid strategy hash power or choice mode\n");
            return 1;
        }
        return command_export_six_strategy(
            argv[2], argv[3], argv[4], argv[5], argv[6],
            hash_power, all_choices != 0
        );
    }
    if (argc == 5 && strcmp(argv[1], "probe") == 0) {
        int clock;
        if (!parse_bounded_int(argv[4], 0, 126, &clock)) {
            fprintf(stderr, "invalid clock\n");
            return 1;
        }
        return command_probe_six(argv[2], argv[3], clock);
    }
    if (
        (argc == 4 || argc == 5) &&
        strcmp(argv[1], "verify-symmetry") == 0
    ) {
        int clock;
        uint64_t rank_stride = 1;
        if (
            !parse_bounded_int(argv[3], 0, 126, &clock) ||
            (argc == 5 && (
                !parse_uint64_value(argv[4], &rank_stride) ||
                rank_stride == 0
            ))
        ) {
            fprintf(stderr, "invalid symmetry clock or stride\n");
            return 1;
        }
        return command_verify_six_symmetry(
            argv[2], clock, rank_stride
        );
    }
    if (
        (argc == 6 || argc == 7) &&
        strcmp(argv[1], "verify-thresholds") == 0
    ) {
        int tb3_hash_power;
        uint64_t rank_stride = 1;
        if (
            !parse_bounded_int(argv[5], 16, 28, &tb3_hash_power) ||
            (argc == 7 && (
                !parse_uint64_value(argv[6], &rank_stride) ||
                rank_stride == 0 ||
                rank_stride > (uint64_t)INT64_MAX
            ))
        ) {
            fprintf(stderr, "invalid threshold hash power or stride\n");
            return 1;
        }
        return command_verify_six_thresholds(
            argv[2], argv[3], argv[4], tb3_hash_power, rank_stride
        );
    }
    if ((argc == 9 || argc == 10) && strcmp(argv[1], "build") == 0) {
        int no_progress_plies;
        int tb3_hash_power;
        uint64_t partition_states;
        int signature_limit;
        int layer_checkpoint_interval = 1;
        if (
            !parse_bounded_int(argv[2], 1, 126, &no_progress_plies) ||
            !parse_bounded_int(argv[5], 16, 28, &tb3_hash_power) ||
            !parse_uint64_value(argv[6], &partition_states) ||
            partition_states < 2 ||
            (partition_states & 1) != 0 ||
            !parse_bounded_int(argv[7], 1, TB6_SIGNATURES, &signature_limit) ||
            (argc == 10 && !parse_bounded_int(
                argv[9], 1, no_progress_plies, &layer_checkpoint_interval
            ))
        ) {
            fprintf(stderr, "invalid six-piece build arguments\n");
            return 1;
        }
        return command_build_six(
            no_progress_plies,
            argv[3],
            argv[4],
            tb3_hash_power,
            partition_states,
            (uint32_t)layer_checkpoint_interval,
            (uint32_t)signature_limit,
            argv[8]
        );
    }
    if (argc == 9 && strcmp(argv[1], "verify-prefix") == 0) {
        int no_progress_plies;
        int tb3_hash_power;
        int signature_limit;
        int clock;
        if (
            !parse_bounded_int(argv[2], 1, 126, &no_progress_plies) ||
            !parse_bounded_int(argv[5], 16, 28, &tb3_hash_power) ||
            !parse_bounded_int(argv[6], 1, TB6_SIGNATURES, &signature_limit) ||
            !parse_bounded_int(argv[7], 0, no_progress_plies, &clock)
        ) {
            fprintf(stderr, "invalid six-piece verify arguments\n");
            return 1;
        }
        return command_verify_six_prefix(
            no_progress_plies,
            argv[3],
            argv[4],
            tb3_hash_power,
            (uint32_t)signature_limit,
            clock,
            argv[8]
        );
    }
    if ((argc >= 10 && argc <= 14) && strcmp(argv[1], "dfpn") == 0) {
        uint64_t expansion_budget;
        int hash_power;
        int tb3_hash_power;
        int certificate_all_choices = 0;
        if (
            !parse_uint64_value(argv[7], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_bounded_int(argv[8], 16, 28, &hash_power) ||
            !parse_bounded_int(argv[9], 16, 28, &tb3_hash_power) ||
            (argc == 14 && !parse_bounded_int(
                argv[13], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN budget or hash power\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[5], 0, argv[6],
            expansion_budget, (size_t)1 << (hash_power - 1),
            (size_t)1 << (hash_power - 1), tb3_hash_power,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            argv[3],
            argv[4],
            argc >= 13 && strcmp(argv[12], "-") != 0 ? argv[12] : NULL,
            certificate_all_choices != 0
        );
    }
    if (
        (argc >= 11 && argc <= 15) &&
        strcmp(argv[1], "dfpn-clock") == 0
    ) {
        int reversible_plies;
        uint64_t expansion_budget;
        int hash_power;
        int tb3_hash_power;
        int certificate_all_choices = 0;
        if (
            !parse_bounded_int(argv[6], 0, 126, &reversible_plies) ||
            !parse_uint64_value(argv[8], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_bounded_int(argv[9], 16, 28, &hash_power) ||
            !parse_bounded_int(argv[10], 16, 28, &tb3_hash_power) ||
            (argc == 15 && !parse_bounded_int(
                argv[14], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN clock, budget, or hash power\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[5], reversible_plies, argv[7],
            expansion_budget, (size_t)1 << (hash_power - 1),
            (size_t)1 << (hash_power - 1), tb3_hash_power,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            argc >= 13 && strcmp(argv[12], "-") != 0 ? argv[12] : NULL,
            argv[3],
            argv[4],
            argc >= 14 && strcmp(argv[13], "-") != 0 ? argv[13] : NULL,
            certificate_all_choices != 0
        );
    }
    if (
        (argc >= 11 && argc <= 15) &&
        (strcmp(argv[1], "dfpn-hashes") == 0 ||
         strcmp(argv[1], "dfpn-live-slots") == 0 ||
         strcmp(argv[1], "dfpn-slots") == 0)
    ) {
        bool explicit_live_slots =
            strcmp(argv[1], "dfpn-hashes") != 0;
        bool explicit_solved_slots =
            strcmp(argv[1], "dfpn-slots") == 0;
        uint64_t expansion_budget;
        size_t live_hash_slots = 0;
        size_t solved_hash_slots = 0;
        int tb3_hash_power;
        int certificate_all_choices = 0;
        if (
            !parse_uint64_value(argv[7], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_dfpn_hash_capacities(
                argv[8], argv[9],
                explicit_live_slots, explicit_solved_slots,
                &live_hash_slots, &solved_hash_slots
            ) ||
            !parse_bounded_int(argv[10], 16, 28, &tb3_hash_power) ||
            (argc == 15 && !parse_bounded_int(
                argv[14], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN budget or hash capacity\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[5], 0, argv[6],
            expansion_budget, live_hash_slots,
            solved_hash_slots, tb3_hash_power,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            argc >= 13 && strcmp(argv[12], "-") != 0 ? argv[12] : NULL,
            argv[3],
            argv[4],
            argc >= 14 && strcmp(argv[13], "-") != 0 ? argv[13] : NULL,
            certificate_all_choices != 0
        );
    }
    if (
        (argc >= 12 && argc <= 16) &&
        (strcmp(argv[1], "dfpn-clock-hashes") == 0 ||
         strcmp(argv[1], "dfpn-clock-live-slots") == 0 ||
         strcmp(argv[1], "dfpn-clock-slots") == 0)
    ) {
        bool explicit_live_slots =
            strcmp(argv[1], "dfpn-clock-hashes") != 0;
        bool explicit_solved_slots =
            strcmp(argv[1], "dfpn-clock-slots") == 0;
        int reversible_plies;
        uint64_t expansion_budget;
        size_t live_hash_slots = 0;
        size_t solved_hash_slots = 0;
        int tb3_hash_power;
        int certificate_all_choices = 0;
        if (
            !parse_bounded_int(argv[6], 0, 126, &reversible_plies) ||
            !parse_uint64_value(argv[8], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_dfpn_hash_capacities(
                argv[9], argv[10],
                explicit_live_slots, explicit_solved_slots,
                &live_hash_slots, &solved_hash_slots
            ) ||
            !parse_bounded_int(argv[11], 16, 28, &tb3_hash_power) ||
            (argc == 16 && !parse_bounded_int(
                argv[15], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN clock, budget, or hash capacity\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[5], reversible_plies, argv[7],
            expansion_budget, live_hash_slots,
            solved_hash_slots, tb3_hash_power,
            argc >= 13 && strcmp(argv[12], "-") != 0 ? argv[12] : NULL,
            argc >= 14 && strcmp(argv[13], "-") != 0 ? argv[13] : NULL,
            argv[3],
            argv[4],
            argc >= 15 && strcmp(argv[14], "-") != 0 ? argv[14] : NULL,
            certificate_all_choices != 0
        );
    }
    fprintf(
        stderr,
        "usage:\n"
        "  makhos_tb6 verify-native-hardening SCRATCH_PATH\n"
        "  makhos_tb6 verify-dfpn-disk-backing SCRATCH_PREFIX\n"
        "  makhos_tb6 rebase-dfpn TB4_FILE TB5_FILE TB6_FILE INPUT_CHECKPOINT OUTPUT_CHECKPOINT\n"
        "  makhos_tb6 retarget-dfpn-solved TB4_FILE TB5_FILE TB6_FILE INPUT_CHECKPOINT OUTPUT_CHECKPOINT POSITION CLOCK\n"
        "  makhos_tb6 export-strategy TB4_FILE TB5_FILE TB6_FILE DFPN_CHECKPOINT OUTPUT HASH_POWER ALL_CHOICES_0_OR_1\n"
        "  makhos_tb6 probe FILE POSITION CLOCK\n"
        "  makhos_tb6 verify-symmetry FILE CLOCK [RANK_STRIDE]\n"
        "  makhos_tb6 verify-threshold-logic\n"
        "  makhos_tb6 verify-thresholds COMPACT_TB4 COMPACT_TB5 TB6_FILE TB3_HASH_POWER [RANK_STRIDE]\n"
        "  makhos_tb6 build NO_PROGRESS COMPACT_TB4 COMPACT_TB5 TB3_HASH_POWER PARTITION_STATES SIGNATURE_LIMIT OUTPUT [LAYER_CHECKPOINT_INTERVAL]\n"
        "  makhos_tb6 verify-prefix NO_PROGRESS COMPACT_TB4 COMPACT_TB5 TB3_HASH_POWER SIGNATURE_LIMIT CLOCK OUTPUT\n"
        "  makhos_tb6 dfpn TB4_FILE TB5_FILE TB6_FILE POSITION ROOT EXPANSION_BUDGET HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-clock TB4_FILE TB5_FILE TB6_FILE POSITION CLOCK ROOT EXPANSION_BUDGET HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-hashes TB4_FILE TB5_FILE TB6_FILE POSITION ROOT EXPANSION_BUDGET LIVE_HASH_POWER SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-clock-hashes TB4_FILE TB5_FILE TB6_FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_HASH_POWER SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-live-slots TB4_FILE TB5_FILE TB6_FILE POSITION ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-clock-live-slots TB4_FILE TB5_FILE TB6_FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-slots TB4_FILE TB5_FILE TB6_FILE POSITION ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_SLOTS TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb6 dfpn-clock-slots TB4_FILE TB5_FILE TB6_FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_SLOTS TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
    );
    return 1;
}
