#define MAKHOS_TB4_NO_MAIN
#include "makhos_tb4.c"

#ifdef _OPENMP
#include <omp.h>
#endif

#define TB5_SIGNATURES 44
#define TB5_PART_MAGIC "MK5PART1"
#define TB5_PART_VERSION 1
#define TB5_PATH_CAPACITY 4096

static bool signature_part_path(
    char path[TB5_PATH_CAPACITY],
    const char *output_path,
    uint32_t signature_index,
    const char *suffix
) {
    int written = snprintf(
        path,
        TB5_PATH_CAPACITY,
        "%s.%02u.part%s",
        output_path,
        signature_index,
        suffix
    );
    return written > 0 && written < TB5_PATH_CAPACITY;
}

/* Return 1 for a valid checkpoint, 0 when absent, and -1 when invalid. */
static int read_signature_part(
    CompactTablebase *tablebase,
    uint32_t signature_index,
    uint64_t dependency_checksum,
    const char *output_path
) {
    char path[TB5_PATH_CAPACITY];
    if (!signature_part_path(path, output_path, signature_index, "")) {
        return -1;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    CompactSignature *signature = &tablebase->signatures[signature_index];
    char magic[8];
    uint32_t version;
    uint32_t no_progress_plies;
    uint32_t stored_index;
    uint8_t counts[4];
    uint64_t boards;
    uint64_t byte_count;
    uint64_t stored_dependency;
    uint64_t stored_checksum;
    bool ok =
        fread(magic, 1, 8, file) == 8 &&
        fread(&version, sizeof(version), 1, file) == 1 &&
        fread(&no_progress_plies, sizeof(no_progress_plies), 1, file) == 1 &&
        fread(&stored_index, sizeof(stored_index), 1, file) == 1 &&
        fread(counts, 1, 4, file) == 4 &&
        fread(&boards, sizeof(boards), 1, file) == 1 &&
        fread(&byte_count, sizeof(byte_count), 1, file) == 1 &&
        fread(&stored_dependency, sizeof(stored_dependency), 1, file) == 1 &&
        fread(&stored_checksum, sizeof(stored_checksum), 1, file) == 1 &&
        memcmp(magic, TB5_PART_MAGIC, 8) == 0 &&
        version == TB5_PART_VERSION &&
        no_progress_plies == tablebase->no_progress_plies &&
        stored_index == signature_index &&
        memcmp(counts, signature->count, 4) == 0 &&
        boards == signature->boards &&
        byte_count == signature->byte_count &&
        stored_dependency == dependency_checksum &&
        fread(signature->thresholds, 1, (size_t)byte_count, file) == byte_count &&
        fgetc(file) == EOF;
    fclose(file);
    if (!ok) {
        fprintf(stderr, "invalid five-piece checkpoint: %s\n", path);
        return -1;
    }
    uint64_t checksum = checksum_update(
        UINT64_C(1469598103934665603),
        signature->thresholds,
        signature->byte_count
    );
    if (checksum != stored_checksum) {
        fprintf(stderr, "five-piece checkpoint checksum mismatch: %s\n", path);
        return -1;
    }
    fprintf(stderr, "resumed signature %u from %s\n", signature_index + 1, path);
    return 1;
}

static bool write_signature_part(
    const CompactTablebase *tablebase,
    uint32_t signature_index,
    uint64_t dependency_checksum,
    const char *output_path
) {
    char path[TB5_PATH_CAPACITY];
    char temporary[TB5_PATH_CAPACITY];
    if (
        !signature_part_path(path, output_path, signature_index, "") ||
        !signature_part_path(temporary, output_path, signature_index, ".tmp")
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
    uint32_t version = TB5_PART_VERSION;
    bool ok =
        fwrite(TB5_PART_MAGIC, 1, 8, file) == 8 &&
        fwrite(&version, sizeof(version), 1, file) == 1 &&
        fwrite(&tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&signature_index, sizeof(signature_index), 1, file) == 1 &&
        fwrite(signature->count, 1, 4, file) == 4 &&
        fwrite(&signature->boards, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&signature->byte_count, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&dependency_checksum, sizeof(dependency_checksum), 1, file) == 1 &&
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
        fprintf(stderr, "unable to write five-piece checkpoint: %s\n", path);
        return false;
    }
    return true;
}

static int compare_compact_signatures(
    const void *left_pointer,
    const void *right_pointer
) {
    const CompactSignature *left = left_pointer;
    const CompactSignature *right = right_pointer;
    int left_men = left->count[TYPE_BM] + left->count[TYPE_RM];
    int right_men = right->count[TYPE_BM] + right->count[TYPE_RM];
    if (left_men != right_men) {
        return left_men - right_men;
    }
    for (int type = 0; type < 4; ++type) {
        if (left->count[type] != right->count[type]) {
            return (int)left->count[type] - (int)right->count[type];
        }
    }
    return 0;
}

static uint64_t compact_rank(
    Position position,
    const CompactSignature *signature
) {
    RankedSignature ranked;
    memset(&ranked, 0, sizeof(ranked));
    memcpy(ranked.count, signature->count, 4);
    ranked.boards = signature->boards;
    return rank_position(position, &ranked);
}

static Position compact_unrank(
    uint64_t rank,
    const CompactSignature *signature
) {
    RankedSignature ranked;
    memset(&ranked, 0, sizeof(ranked));
    memcpy(ranked.count, signature->count, 4);
    ranked.boards = signature->boards;
    return unrank_position(rank, &ranked);
}

static bool initialize_five_piece_tablebase(
    CompactTablebase *tablebase,
    int no_progress_plies
) {
    memset(tablebase, 0, sizeof(*tablebase));
    memset(tablebase->signature_index, 0xff, sizeof(tablebase->signature_index));
    tablebase->piece_count = 5;
    tablebase->no_progress_plies = (uint32_t)no_progress_plies;
    uint32_t index = 0;
    for (int bm = 0; bm <= 5; ++bm) {
        for (int bk = 0; bk <= 5 - bm; ++bk) {
            for (int rm = 0; rm <= 5 - bm - bk; ++rm) {
                int rk = 5 - bm - bk - rm;
                if (bm + bk == 0 || rm + rk == 0) {
                    continue;
                }
                if (index >= TB5_SIGNATURES) {
                    return false;
                }
                CompactSignature *signature = &tablebase->signatures[index++];
                signature->count[TYPE_BM] = (uint8_t)bm;
                signature->count[TYPE_BK] = (uint8_t)bk;
                signature->count[TYPE_RM] = (uint8_t)rm;
                signature->count[TYPE_RK] = (uint8_t)rk;
            }
        }
    }
    if (index != TB5_SIGNATURES) {
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
        int bm = signature->count[TYPE_BM];
        int bk = signature->count[TYPE_BK];
        int rm = signature->count[TYPE_RM];
        int rk = signature->count[TYPE_RK];
        signature->boards = completion_count(0, bm, bk, rm, rk);
        signature->byte_count = signature->boards * 2;
        signature->thresholds = calloc((size_t)signature->byte_count, 1);
        if (signature->thresholds == NULL) {
            return false;
        }
        tablebase->total_positions += signature->byte_count;
        tablebase->signature_index[bm][bk][rm][rk] = (int)signature_index;
    }
    tablebase->total_states = tablebase->total_positions *
        ((uint64_t)no_progress_plies + 1);
    return true;
}

typedef struct {
    uint8_t count[4];
    uint64_t roots;
    uint64_t partitions;
} SixPiecePlanRow;

static uint64_t partition_count_for_states(
    uint64_t state_count,
    uint64_t partition_states
) {
    if (state_count == 0 || partition_states == 0) {
        return 0;
    }
    return state_count / partition_states +
        (state_count % partition_states != 0 ? 1 : 0);
}

static int compare_six_plan_rows(
    const void *left_pointer,
    const void *right_pointer
) {
    const SixPiecePlanRow *left = left_pointer;
    const SixPiecePlanRow *right = right_pointer;
    if (left->roots < right->roots) return 1;
    if (left->roots > right->roots) return -1;
    return memcmp(left->count, right->count, 4);
}

static int command_plan_six(uint64_t partition_states) {
    SixPiecePlanRow rows[COMPACT_MAX_SIGNATURES];
    uint32_t row_count = 0;
    uint64_t total_roots = 0;
    uint64_t total_partitions = 0;
    for (int bm = 0; bm <= 6; ++bm) {
        for (int bk = 0; bk <= 6 - bm; ++bk) {
            for (int rm = 0; rm <= 6 - bm - bk; ++rm) {
                int rk = 6 - bm - bk - rm;
                if (bm + bk == 0 || rm + rk == 0) {
                    continue;
                }
                if (row_count >= COMPACT_MAX_SIGNATURES) {
                    fprintf(stderr, "six-piece signature overflow\n");
                    return 2;
                }
                SixPiecePlanRow *row = &rows[row_count++];
                row->count[0] = (uint8_t)bm;
                row->count[1] = (uint8_t)bk;
                row->count[2] = (uint8_t)rm;
                row->count[3] = (uint8_t)rk;
                uint64_t boards = completion_count(0, bm, bk, rm, rk);
                row->roots = boards * 2;
                row->partitions = partition_count_for_states(
                    row->roots, partition_states
                );
                total_roots += row->roots;
                total_partitions += row->partitions;
            }
        }
    }
    if (row_count != COMPACT_MAX_SIGNATURES) {
        fprintf(stderr, "unexpected six-piece signature count: %u\n", row_count);
        return 2;
    }
    qsort(rows, row_count, sizeof(rows[0]), compare_six_plan_rows);
    printf("six-piece signatures: %u\n", row_count);
    printf("six-piece placement/turn roots: %" PRIu64 "\n", total_roots);
    printf(
        "six-piece logical WDL states at no-progress 80: %" PRIu64 "\n",
        total_roots * UINT64_C(81)
    );
    printf("six-piece threshold payload bytes: %" PRIu64 "\n", total_roots);
    printf("partition state limit: %" PRIu64 "\n", partition_states);
    printf("planned rank partitions: %" PRIu64 "\n", total_partitions);
    size_t shown = row_count < 10 ? row_count : 10;
    for (size_t index = 0; index < shown; ++index) {
        const SixPiecePlanRow *row = &rows[index];
        printf(
            "signature [%u,%u,%u,%u]: roots=%" PRIu64
            " partitions=%" PRIu64 "\n",
            row->count[0], row->count[1], row->count[2], row->count[3],
            row->roots, row->partitions
        );
    }
    return 0;
}

static bool probe_compact_position(
    const CompactTablebase *tablebase,
    Position position,
    uint8_t *value
) {
    if (position.red == 0 || position.black == 0) {
        *value = 0;
        return true;
    }
    uint8_t counts[4];
    signature_for_position(position, counts);
    int signature_index = tablebase->signature_index
        [counts[0]][counts[1]][counts[2]][counts[3]];
    if (signature_index < 0) {
        return false;
    }
    const CompactSignature *signature =
        &tablebase->signatures[signature_index];
    uint64_t rank = compact_rank(position, signature);
    *value = get_compact_wdl(
        signature,
        rank,
        position.turn,
        position.reversible_plies
    );
    return true;
}

static bool probe_three_piece_readonly(
    Position position,
    uint8_t *value
) {
    ExactEntry *cached = exact_find_slot(
        &global_three_piece_tablebase, position
    );
    if (cached == NULL || !cached->used) {
        return false;
    }
    *value = (uint8_t)(cached->outcome + 1);
    return true;
}

static bool evaluate_five_piece_state(
    CompactTablebase *tablebase,
    const CompactTablebase *four_piece,
    const bool *built,
    uint32_t signature_index,
    const uint8_t *next_layer,
    Position position,
    MoveList *moves,
    uint8_t *value
) {
    generate_moves(position, moves);
    if (moves->count == 0) {
        *value = 0;
        return true;
    }
    *value = 0;
    for (uint32_t move_index = 0;
         move_index < moves->count;
         ++move_index) {
        Position child_position = moves->moves[move_index].next;
        uint8_t child_value;
        int child_pieces = count_bits(occupied(child_position));
        if (child_position.red == 0 || child_position.black == 0) {
            child_value = 0;
        } else if (child_pieces <= 3) {
            if (!probe_three_piece_readonly(child_position, &child_value)) {
                fprintf(stderr, "three-piece dependency probe failed\n");
                return false;
            }
        } else if (child_pieces == 4) {
            if (!probe_compact_position(
                    four_piece,
                    child_position,
                    &child_value
                )) {
                fprintf(stderr, "four-piece dependency probe failed\n");
                return false;
            }
        } else {
            uint8_t child_counts[4];
            signature_for_position(child_position, child_counts);
            int child_signature_index = tablebase->signature_index
                [child_counts[0]][child_counts[1]]
                [child_counts[2]][child_counts[3]];
            if (child_signature_index < 0) {
                fprintf(stderr, "five-piece signature missing\n");
                return false;
            }
            CompactSignature *child_signature =
                &tablebase->signatures[child_signature_index];
            uint64_t child_rank = compact_rank(
                child_position, child_signature
            );
            uint64_t child_turn_index =
                child_position.turn == BLACK ? 1 : 0;
            if (child_signature_index == (int)signature_index) {
                child_value = next_layer[
                    child_rank * 2 + child_turn_index
                ];
            } else {
                if (!built[child_signature_index]) {
                    fprintf(stderr, "five-piece dependency order failure\n");
                    return false;
                }
                child_value = get_compact_wdl(
                    child_signature,
                    child_rank,
                    child_position.turn,
                    child_position.reversible_plies
                );
            }
        }
        uint8_t candidate = invert_wdl(child_value);
        if (candidate > *value) {
            *value = candidate;
            if (*value == 2) {
                break;
            }
        }
    }
    return true;
}

typedef struct {
    uint32_t *offsets;
    uint32_t *children;
    uint8_t *fixed_values;
    uint64_t state_count;
    uint32_t edge_count;
} FiveTransitions;

static void destroy_five_transitions(FiveTransitions *transitions) {
    free(transitions->offsets);
    free(transitions->children);
    free(transitions->fixed_values);
    memset(transitions, 0, sizeof(*transitions));
}

static bool classify_five_child(
    CompactTablebase *tablebase,
    const CompactTablebase *four_piece,
    const bool *built,
    uint32_t signature_index,
    Position child_position,
    bool *quiet,
    uint32_t *quiet_child,
    uint8_t *static_child_value
) {
    *quiet = false;
    int child_pieces = count_bits(occupied(child_position));
    if (child_position.red == 0 || child_position.black == 0) {
        *static_child_value = 0;
        return true;
    }
    if (child_pieces <= 3) {
        if (!probe_three_piece_readonly(child_position, static_child_value)) {
            return false;
        }
        return true;
    }
    if (child_pieces == 4) {
        return probe_compact_position(
            four_piece, child_position, static_child_value
        );
    }
    uint8_t child_counts[4];
    signature_for_position(child_position, child_counts);
    int child_signature_index = tablebase->signature_index
        [child_counts[0]][child_counts[1]]
        [child_counts[2]][child_counts[3]];
    if (child_signature_index < 0) {
        return false;
    }
    CompactSignature *child_signature =
        &tablebase->signatures[child_signature_index];
    uint64_t child_rank = compact_rank(child_position, child_signature);
    uint64_t child_turn_index = child_position.turn == BLACK ? 1 : 0;
    if (child_signature_index == (int)signature_index) {
        uint64_t child_state = child_rank * 2 + child_turn_index;
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
        child_position.turn,
        child_position.reversible_plies
    );
    return true;
}

static bool build_five_transitions(
    CompactTablebase *tablebase,
    const CompactTablebase *four_piece,
    const bool *built,
    uint32_t signature_index,
    const Position *bases,
    FiveTransitions *transitions
) {
    memset(transitions, 0, sizeof(*transitions));
    CompactSignature *signature = &tablebase->signatures[signature_index];
    transitions->state_count = signature->boards * 2;
    transitions->offsets = calloc(
        (size_t)transitions->state_count + 1,
        sizeof(*transitions->offsets)
    );
    transitions->fixed_values = calloc(
        (size_t)transitions->state_count,
        sizeof(*transitions->fixed_values)
    );
    if (
        transitions->offsets == NULL ||
        transitions->fixed_values == NULL
    ) {
        destroy_five_transitions(transitions);
        return false;
    }
    uint64_t errors = 0;
#ifdef _OPENMP
#pragma omp parallel reduction(+:errors)
#endif
    {
        MoveList *moves = calloc(1, sizeof(*moves));
        if (moves == NULL) {
            ++errors;
        }
#ifdef _OPENMP
#pragma omp for schedule(static)
#endif
        for (int64_t signed_rank = 0;
             signed_rank < (int64_t)signature->boards;
             ++signed_rank) {
            if (moves == NULL) {
                continue;
            }
            uint64_t rank = (uint64_t)signed_rank;
            Position base = bases[rank];
            base.reversible_plies = 0;
            for (int turn = RED; turn <= BLACK; ++turn) {
                base.turn = (uint8_t)turn;
                uint64_t state_index = rank * 2 +
                    (turn == BLACK ? 1 : 0);
                generate_moves(base, moves);
                uint8_t fixed_value = 0;
                uint32_t quiet_count = 0;
                for (uint32_t move_index = 0;
                     move_index < moves->count;
                     ++move_index) {
                    bool quiet;
                    uint32_t quiet_child;
                    uint8_t child_value;
                    if (!classify_five_child(
                            tablebase,
                            four_piece,
                            built,
                            signature_index,
                            moves->moves[move_index].next,
                            &quiet,
                            &quiet_child,
                            &child_value
                        )) {
                        ++errors;
                        continue;
                    }
                    (void)quiet_child;
                    if (quiet) {
                        ++quiet_count;
                    } else {
                        uint8_t candidate = invert_wdl(child_value);
                        if (candidate > fixed_value) {
                            fixed_value = candidate;
                        }
                    }
                }
                if (fixed_value == 2) {
                    quiet_count = 0;
                }
                transitions->fixed_values[state_index] = fixed_value;
                transitions->offsets[state_index + 1] = quiet_count;
            }
        }
        free(moves);
    }
    if (errors != 0) {
        destroy_five_transitions(transitions);
        return false;
    }
    uint64_t edge_count = 0;
    for (uint64_t state = 0; state < transitions->state_count; ++state) {
        edge_count += transitions->offsets[state + 1];
        if (edge_count > UINT32_MAX) {
            fprintf(stderr, "five-piece transition graph exceeds 32-bit offsets\n");
            destroy_five_transitions(transitions);
            return false;
        }
        transitions->offsets[state + 1] = (uint32_t)edge_count;
    }
    transitions->edge_count = (uint32_t)edge_count;
    transitions->children = malloc(
        (size_t)transitions->edge_count * sizeof(*transitions->children)
    );
    if (transitions->edge_count != 0 && transitions->children == NULL) {
        destroy_five_transitions(transitions);
        return false;
    }
    errors = 0;
#ifdef _OPENMP
#pragma omp parallel reduction(+:errors)
#endif
    {
        MoveList *moves = calloc(1, sizeof(*moves));
        if (moves == NULL) {
            ++errors;
        }
#ifdef _OPENMP
#pragma omp for schedule(static)
#endif
        for (int64_t signed_rank = 0;
             signed_rank < (int64_t)signature->boards;
             ++signed_rank) {
            if (moves == NULL) {
                continue;
            }
            uint64_t rank = (uint64_t)signed_rank;
            Position base = bases[rank];
            base.reversible_plies = 0;
            for (int turn = RED; turn <= BLACK; ++turn) {
                base.turn = (uint8_t)turn;
                uint64_t state_index = rank * 2 +
                    (turn == BLACK ? 1 : 0);
                uint32_t cursor = transitions->offsets[state_index];
                uint32_t end = transitions->offsets[state_index + 1];
                if (cursor == end) {
                    continue;
                }
                generate_moves(base, moves);
                for (uint32_t move_index = 0;
                     move_index < moves->count;
                     ++move_index) {
                    bool quiet;
                    uint32_t quiet_child;
                    uint8_t child_value;
                    if (!classify_five_child(
                            tablebase,
                            four_piece,
                            built,
                            signature_index,
                            moves->moves[move_index].next,
                            &quiet,
                            &quiet_child,
                            &child_value
                        )) {
                        ++errors;
                        continue;
                    }
                    (void)child_value;
                    if (quiet && cursor < end) {
                        transitions->children[cursor++] = quiet_child;
                    }
                }
                if (cursor != end) {
                    ++errors;
                }
            }
        }
        free(moves);
    }
    if (errors != 0) {
        destroy_five_transitions(transitions);
        return false;
    }
    return true;
}

static bool compute_five_piece_transition_layer(
    CompactSignature *signature,
    const FiveTransitions *transitions,
    int clock,
    int no_progress_plies,
    const uint8_t *next_layer,
    uint8_t *current_layer,
    uint64_t *computed
) {
    if (clock == no_progress_plies) {
        memset(current_layer, 1, (size_t)transitions->state_count);
        *computed += transitions->state_count;
        return true;
    }
    uint64_t errors = 0;
#ifdef _OPENMP
#pragma omp parallel for schedule(static) reduction(+:errors)
#endif
    for (int64_t signed_state = 0;
         signed_state < (int64_t)transitions->state_count;
         ++signed_state) {
        uint64_t state = (uint64_t)signed_state;
        uint8_t value = transitions->fixed_values[state];
        for (uint32_t edge = transitions->offsets[state];
             edge < transitions->offsets[state + 1];
             ++edge) {
            uint8_t candidate = invert_wdl(
                next_layer[transitions->children[edge]]
            );
            if (candidate > value) {
                value = candidate;
                if (value == 2) {
                    break;
                }
            }
        }
        current_layer[state] = value;
        uint8_t encoded = signature->thresholds[state];
        if (value == 1) {
            if (encoded != 0) {
                ++errors;
            }
        } else if (encoded == 0) {
            encoded = (uint8_t)(clock + 1);
            if (value == 2) {
                encoded |= 0x80;
            }
            signature->thresholds[state] = encoded;
        } else if (((encoded & 0x80) != 0 ? 2 : 0) != value) {
            ++errors;
        }
    }
    *computed += transitions->state_count;
    if (errors != 0) {
        fprintf(stderr, "five-piece transition-layer errors: %" PRIu64 "\n", errors);
        return false;
    }
    return true;
}

static bool compute_five_piece_layer(
    CompactTablebase *tablebase,
    const CompactTablebase *four_piece,
    const bool *built,
    uint32_t signature_index,
    int clock,
    const Position *bases,
    const uint8_t *next_layer,
    uint8_t *current_layer,
    uint64_t *computed
) {
    CompactSignature *signature = &tablebase->signatures[signature_index];
    int errors = 0;
    uint64_t layer_computed = 0;
#ifdef _OPENMP
#pragma omp parallel reduction(+:errors,layer_computed)
#endif
    {
        MoveList *moves = calloc(1, sizeof(*moves));
        if (moves == NULL) {
            ++errors;
        }
#ifdef _OPENMP
#pragma omp for schedule(static)
#endif
        for (int64_t signed_rank = 0;
             signed_rank < (int64_t)signature->boards;
             ++signed_rank) {
            if (moves == NULL) {
                continue;
            }
            uint64_t rank = (uint64_t)signed_rank;
            Position base = bases[rank];
            base.reversible_plies = (uint8_t)clock;
            for (int turn = RED; turn <= BLACK; ++turn) {
                uint64_t turn_index = turn == BLACK ? 1 : 0;
                uint64_t state_index = rank * 2 + turn_index;
                uint8_t value;
                if (clock == (int)tablebase->no_progress_plies) {
                    value = 1;
                } else {
                    base.turn = (uint8_t)turn;
                    if (!evaluate_five_piece_state(
                            tablebase,
                            four_piece,
                            built,
                            signature_index,
                            next_layer,
                            base,
                            moves,
                            &value
                        )) {
                        ++errors;
                        continue;
                    }
                }
                current_layer[state_index] = value;
                uint8_t encoded = signature->thresholds[state_index];
                if (value == 1) {
                    if (encoded != 0) {
                        fprintf(stderr, "non-monotonic five-piece WDL\n");
                        ++errors;
                        continue;
                    }
                } else if (encoded == 0) {
                    encoded = (uint8_t)(clock + 1);
                    if (value == 2) {
                        encoded |= 0x80;
                    }
                    signature->thresholds[state_index] = encoded;
                } else if (((encoded & 0x80) != 0 ? 2 : 0) != value) {
                    fprintf(
                        stderr,
                        "five-piece WDL changed winner across clocks\n"
                    );
                    ++errors;
                    continue;
                }
                ++layer_computed;
            }
        }
        free(moves);
    }
    *computed += layer_computed;
    return errors == 0;
}

static bool build_five_piece_tablebase(
    CompactTablebase *tablebase,
    const CompactTablebase *four_piece,
    const char *output_path
) {
    bool *built = calloc(tablebase->signature_count, sizeof(*built));
    if (built == NULL) {
        free(built);
        return false;
    }
    uint64_t computed = 0;
    for (uint32_t signature_index = 0;
         signature_index < tablebase->signature_count;
         ++signature_index) {
        CompactSignature *signature = &tablebase->signatures[signature_index];
        int resumed = read_signature_part(
            tablebase,
            signature_index,
            four_piece->checksum,
            output_path
        );
        if (resumed < 0) {
            free(built);
            return false;
        }
        if (resumed > 0) {
            built[signature_index] = true;
            computed += signature->byte_count *
                ((uint64_t)tablebase->no_progress_plies + 1);
            continue;
        }
        uint64_t layer_size = signature->boards * 2;
        Position *bases = malloc(
            (size_t)signature->boards * sizeof(*bases)
        );
        uint8_t *next_layer = malloc((size_t)layer_size);
        uint8_t *current_layer = malloc((size_t)layer_size);
        if (bases == NULL || next_layer == NULL || current_layer == NULL) {
            free(bases);
            free(next_layer);
            free(current_layer);
            free(built);
            return false;
        }
        memset(next_layer, 1, (size_t)layer_size);
        fprintf(
            stderr,
            "signature %u/%u [%u,%u,%u,%u] boards=%" PRIu64 "\n",
            signature_index + 1,
            tablebase->signature_count,
            signature->count[0], signature->count[1],
            signature->count[2], signature->count[3],
            signature->boards
        );
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (int64_t signed_rank = 0;
             signed_rank < (int64_t)signature->boards;
             ++signed_rank) {
            bases[signed_rank] = compact_unrank(
                (uint64_t)signed_rank, signature
            );
        }
        FiveTransitions transitions;
        if (!build_five_transitions(
                tablebase,
                four_piece,
                built,
                signature_index,
                bases,
                &transitions
            )) {
            fprintf(stderr, "unable to build five-piece transition graph\n");
            free(bases);
            free(next_layer);
            free(current_layer);
            free(built);
            return false;
        }
        free(bases);
        bases = NULL;
        fprintf(
            stderr,
            "transition edges: %u\n",
            transitions.edge_count
        );
        for (int clock = (int)tablebase->no_progress_plies; clock >= 0; --clock) {
            if (!compute_five_piece_transition_layer(
                    signature,
                    &transitions,
                    clock,
                    (int)tablebase->no_progress_plies,
                    next_layer,
                    current_layer,
                    &computed
                )) {
                destroy_five_transitions(&transitions);
                free(next_layer);
                free(current_layer);
                free(built);
                return false;
            }
            uint8_t *swap = next_layer;
            next_layer = current_layer;
            current_layer = swap;
        }
        destroy_five_transitions(&transitions);
        free(next_layer);
        free(current_layer);
        if (!write_signature_part(
            tablebase,
            signature_index,
            four_piece->checksum,
            output_path
        )) {
            free(built);
            return false;
        }
        built[signature_index] = true;
    }
    free(built);
    fprintf(stderr, "computed states: %" PRIu64 "\n", computed);
    return computed == tablebase->total_states;
}

static bool write_compact_five_piece(
    CompactTablebase *tablebase,
    const char *path
) {
    uint64_t checksum = UINT64_C(1469598103934665603);
    for (uint32_t index = 0; index < tablebase->signature_count; ++index) {
        checksum = checksum_update(
            checksum,
            tablebase->signatures[index].thresholds,
            tablebase->signatures[index].byte_count
        );
    }
    FILE *file = fopen(path, "wb");
    if (file == NULL) {
        return false;
    }
    uint32_t version = COMPACT_WDL_VERSION;
    bool ok =
        fwrite(COMPACT_WDL_MAGIC, 1, 8, file) == 8 &&
        fwrite(&version, sizeof(version), 1, file) == 1 &&
        fwrite(&tablebase->piece_count, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase->signature_count, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase->total_positions, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&tablebase->total_states, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&checksum, sizeof(uint64_t), 1, file) == 1;
    for (uint32_t index = 0; ok && index < tablebase->signature_count; ++index) {
        CompactSignature *signature = &tablebase->signatures[index];
        ok =
            fwrite(signature->count, 1, 4, file) == 4 &&
            fwrite(&signature->boards, sizeof(uint64_t), 1, file) == 1 &&
            fwrite(&signature->byte_count, sizeof(uint64_t), 1, file) == 1 &&
            fwrite(
                signature->thresholds,
                1,
                (size_t)signature->byte_count,
                file
            ) == signature->byte_count;
    }
    if (fclose(file) != 0) {
        ok = false;
    }
    if (ok) {
        tablebase->checksum = checksum;
        printf("logical WDL states: %" PRIu64 "\n", tablebase->total_states);
        printf("compact positions: %" PRIu64 "\n", tablebase->total_positions);
        printf("compact checksum: %016" PRIx64 "\n", checksum);
        printf("wrote: %s\n", path);
    }
    return ok;
}

static int command_probe_five(
    const char *path,
    const char *text,
    int clock
) {
    CompactTablebase tablebase;
    if (!read_compact_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read compact five-piece tablebase\n");
        return 2;
    }
    Position position;
    if (
        tablebase.piece_count != 5 ||
        !parse_position(text, &position) ||
        count_bits(occupied(position)) != 5
    ) {
        fprintf(stderr, "probe requires a valid five-piece position\n");
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

static int command_verify_five(const char *path, int clock) {
    CompactTablebase tablebase;
    if (!read_compact_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read compact five-piece tablebase\n");
        return 2;
    }
    if (
        tablebase.piece_count != 5 ||
        clock < 0 ||
        clock > (int)tablebase.no_progress_plies
    ) {
        fprintf(stderr, "invalid five-piece tablebase or clock\n");
        compact_tablebase_destroy(&tablebase);
        return 1;
    }
    uint64_t wins = 0;
    uint64_t draws = 0;
    uint64_t losses = 0;
    uint64_t checked = 0;
    uint64_t errors = 0;
    for (uint32_t signature_index = 0;
         signature_index < tablebase.signature_count;
         ++signature_index) {
        CompactSignature *signature = &tablebase.signatures[signature_index];
#ifdef _OPENMP
#pragma omp parallel for schedule(static) reduction(+:wins,draws,losses,checked,errors)
#endif
        for (int64_t signed_rank = 0;
             signed_rank < (int64_t)signature->boards;
             ++signed_rank) {
            uint64_t rank = (uint64_t)signed_rank;
            Position base = compact_unrank(rank, signature);
            if (compact_rank(base, signature) != rank) {
                ++errors;
                continue;
            }
            base.reversible_plies = (uint8_t)clock;
            for (int turn = RED; turn <= BLACK; ++turn) {
                base.turn = (uint8_t)turn;
                uint8_t value = get_compact_wdl(
                    signature, rank, turn, clock
                );
                if (value == 2) {
                    ++wins;
                } else if (value == 1) {
                    ++draws;
                } else if (value == 0) {
                    ++losses;
                } else {
                    ++errors;
                    continue;
                }
                ++checked;
                Position transformed = rotate_and_swap(base);
                uint8_t transformed_value;
                if (
                    !probe_compact_position(
                        &tablebase, transformed, &transformed_value
                    ) ||
                    transformed_value != value
                ) {
                    ++errors;
                }
            }
        }
    }
    if (errors != 0) {
        fprintf(stderr, "five-piece exhaustive verification errors: %" PRIu64 "\n", errors);
        compact_tablebase_destroy(&tablebase);
        return 3;
    }
    printf("clock: %d\n", clock);
    printf("positions checked: %" PRIu64 "\n", checked);
    printf(
        "side-to-move W/D/L: %" PRIu64 "/%" PRIu64 "/%" PRIu64 "\n",
        wins, draws, losses
    );
    printf("rank roundtrip: PASS\n");
    printf("color-rotation symmetry: PASS\n");
    compact_tablebase_destroy(&tablebase);
    return 0;
}

static int command_build_five(
    int no_progress_plies,
    const char *four_piece_path,
    int tb3_hash_power,
    const char *output_path
) {
    CompactTablebase four_piece;
    if (!read_compact_tablebase(&four_piece, four_piece_path)) {
        fprintf(stderr, "unable to read compact four-piece dependency\n");
        return 2;
    }
    int dependency = makhos_tb3_init(no_progress_plies, tb3_hash_power);
    if (dependency != 0) {
        fprintf(stderr, "unable to initialize three-piece dependency: %d\n", dependency);
        compact_tablebase_destroy(&four_piece);
        return 2;
    }
    if (
        !compact_tablebase_has_complete_schema(&four_piece, 4) ||
        four_piece.no_progress_plies != (uint32_t)no_progress_plies
    ) {
        fprintf(stderr, "four-piece dependency rules mismatch\n");
        compact_tablebase_destroy(&four_piece);
        makhos_tb3_shutdown();
        return 2;
    }
    CompactTablebase five_piece;
    if (!initialize_five_piece_tablebase(&five_piece, no_progress_plies)) {
        fprintf(stderr, "unable to initialize five-piece tablebase\n");
        compact_tablebase_destroy(&five_piece);
        compact_tablebase_destroy(&four_piece);
        makhos_tb3_shutdown();
        return 2;
    }
    printf("logical WDL states: %" PRIu64 "\n", five_piece.total_states);
    printf("compact payload bytes: %" PRIu64 "\n", five_piece.total_positions);
#ifdef _OPENMP
    printf("worker threads: %d\n", omp_get_max_threads());
#else
    printf("worker threads: 1\n");
#endif
    bool built = build_five_piece_tablebase(
        &five_piece, &four_piece, output_path
    );
    bool written = built && write_compact_five_piece(&five_piece, output_path);
    compact_tablebase_destroy(&five_piece);
    compact_tablebase_destroy(&four_piece);
    makhos_tb3_shutdown();
    return written ? 0 : 3;
}

#ifndef MAKHOS_TB5_NO_MAIN
int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "verify-native-hardening") == 0) {
        return command_verify_native_hardening(argv[2]);
    }
    if (argc == 2 && strcmp(argv[1], "verify-dfpn-codec") == 0) {
        return command_verify_dfpn_codec();
    }
    if (argc == 3 && strcmp(argv[1], "verify-dfpn-disk-backing") == 0) {
        return command_verify_dfpn_disk_backing(argv[2]);
    }
    if (argc == 3 && strcmp(argv[1], "plan-six") == 0) {
        uint64_t partition_states;
        if (
            !parse_uint64_value(argv[2], &partition_states) ||
            partition_states < 1
        ) {
            fprintf(stderr, "plan-six requires positive PARTITION_STATES\n");
            return 1;
        }
        return command_plan_six(partition_states);
    }
    if (argc == 4 && strcmp(argv[1], "compact-dfpn") == 0) {
        return compact_dfpn_checkpoint(
            argv[2], argv[3], false, false, 0, false, 0, false, 0,
            false, (Position){0}
        );
    }
    if (argc == 6 && strcmp(argv[1], "build") == 0) {
        int no_progress_plies;
        int tb3_hash_power;
        if (
            !parse_bounded_int(argv[2], 1, 126, &no_progress_plies) ||
            !parse_bounded_int(argv[4], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid no-progress value or hash power\n");
            return 1;
        }
        return command_build_five(
            no_progress_plies, argv[3], tb3_hash_power, argv[5]
        );
    }
    if (argc == 5 && strcmp(argv[1], "probe") == 0) {
        int clock;
        if (!parse_bounded_int(argv[4], 0, 126, &clock)) {
            fprintf(stderr, "invalid clock\n");
            return 1;
        }
        return command_probe_five(argv[2], argv[3], clock);
    }
    if (argc == 4 && strcmp(argv[1], "verify") == 0) {
        int clock;
        if (!parse_bounded_int(argv[3], 0, 126, &clock)) {
            fprintf(stderr, "invalid clock\n");
            return 1;
        }
        return command_verify_five(argv[2], clock);
    }
    if ((argc >= 9 && argc <= 11) && strcmp(argv[1], "dfpn") == 0) {
        uint64_t expansion_budget;
        int hash_power;
        int tb3_hash_power;
        if (
            !parse_uint64_value(argv[6], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_bounded_int(argv[7], 16, 28, &hash_power) ||
            !parse_bounded_int(argv[8], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid DFPN budget or hash power\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[4], 0, argv[5],
            expansion_budget, (size_t)1 << (hash_power - 1),
            (size_t)1 << (hash_power - 1), tb3_hash_power,
            argc >= 10 && strcmp(argv[9], "-") != 0 ? argv[9] : NULL,
            argc == 11 ? argv[10] : NULL,
            argv[3],
            NULL,
            NULL,
            false
        );
    }
    if ((argc >= 10 && argc <= 12) && strcmp(argv[1], "dfpn-clock") == 0) {
        int reversible_plies;
        uint64_t expansion_budget;
        int hash_power;
        int tb3_hash_power;
        if (
            !parse_bounded_int(argv[5], 0, 126, &reversible_plies) ||
            !parse_uint64_value(argv[7], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_bounded_int(argv[8], 16, 28, &hash_power) ||
            !parse_bounded_int(argv[9], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid DFPN clock, budget, or hash power\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[4], reversible_plies, argv[6],
            expansion_budget, (size_t)1 << (hash_power - 1),
            (size_t)1 << (hash_power - 1), tb3_hash_power,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            argc == 12 ? argv[11] : NULL,
            argv[3],
            NULL,
            NULL,
            false
        );
    }
    if (
        (argc >= 10 && argc <= 12) &&
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
        if (
            !parse_uint64_value(argv[6], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_dfpn_hash_capacities(
                argv[7], argv[8],
                explicit_live_slots, explicit_solved_slots,
                &live_hash_slots, &solved_hash_slots
            ) ||
            !parse_bounded_int(argv[9], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid DFPN budget or hash capacity\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[4], 0, argv[5],
            expansion_budget, live_hash_slots,
            solved_hash_slots, tb3_hash_power,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            argc == 12 ? argv[11] : NULL,
            argv[3],
            NULL,
            NULL,
            false
        );
    }
    if (
        (argc >= 11 && argc <= 13) &&
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
        if (
            !parse_bounded_int(argv[5], 0, 126, &reversible_plies) ||
            !parse_uint64_value(argv[7], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_dfpn_hash_capacities(
                argv[8], argv[9],
                explicit_live_slots, explicit_solved_slots,
                &live_hash_slots, &solved_hash_slots
            ) ||
            !parse_bounded_int(argv[10], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid DFPN clock, budget, or hash capacity\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[4], reversible_plies, argv[6],
            expansion_budget, live_hash_slots,
            solved_hash_slots, tb3_hash_power,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            argc == 13 ? argv[12] : NULL,
            argv[3],
            NULL,
            NULL,
            false
        );
    }
    fprintf(
        stderr,
        "usage:\n"
        "  makhos_tb5 verify-native-hardening SCRATCH_PATH\n"
        "  makhos_tb5 verify-dfpn-codec\n"
        "  makhos_tb5 verify-dfpn-disk-backing SCRATCH_PREFIX\n"
        "  makhos_tb5 plan-six PARTITION_STATES\n"
        "  makhos_tb5 build NO_PROGRESS COMPACT_TB4 TB3_HASH_POWER OUTPUT\n"
        "  makhos_tb5 probe FILE POSITION CLOCK\n"
        "  makhos_tb5 verify FILE CLOCK\n"
        "  makhos_tb5 compact-dfpn INPUT_CHECKPOINT OUTPUT_CHECKPOINT\n"
        "  makhos_tb5 dfpn TB4_FILE TB5_FILE POSITION ROOT EXPANSION_BUDGET HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-clock TB4_FILE TB5_FILE POSITION CLOCK ROOT EXPANSION_BUDGET HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-hashes TB4_FILE TB5_FILE POSITION ROOT EXPANSION_BUDGET LIVE_HASH_POWER SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-clock-hashes TB4_FILE TB5_FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_HASH_POWER SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-live-slots TB4_FILE TB5_FILE POSITION ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-clock-live-slots TB4_FILE TB5_FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-slots TB4_FILE TB5_FILE POSITION ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_SLOTS TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
        "  makhos_tb5 dfpn-clock-slots TB4_FILE TB5_FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_SLOTS TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED]\n"
    );
    return 1;
}
#endif
