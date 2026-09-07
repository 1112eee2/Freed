#define _CRT_SECURE_NO_WARNINGS
#define MAKHOS_NO_MAIN
#include <errno.h>
#include <limits.h>
#include <time.h>
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
#include <immintrin.h>
#endif
#include "makhos_native.c"
#if !defined(_WIN32)
#include <sys/mman.h>
#include <sys/stat.h>
#endif

#define TB4_MAGIC "MKT4WDL1"
#define TB4_VERSION 1U
#define TB4_SIGNATURES 25
#define PROOF_CHECKPOINT_MAGIC "MKPFTT01"
#define PROOF_CHECKPOINT_VERSION 1U
#define PROOF_PREFERRED_LINE_MAX 128
#define DFPN_CHECKPOINT_MAGIC "MKDFPN01"
#define DFPN_CHECKPOINT_VERSION_V1 1U
#define DFPN_CHECKPOINT_VERSION 2U
#define DFPN_CHECKPOINT_RECORD_V1_BYTES 24U
#define DFPN_CHECKPOINT_RECORD_BYTES 16U
#define COMPACT_WDL_MAGIC "MKTCWDL1"
#define COMPACT_WDL_VERSION 1U
#define COMPACT_MAX_SIGNATURES 70
#define COMPACT_MAX_PIECES 6
#define DFPN_STRATEGY_MAGIC "MKSTRAT1"
#define DFPN_STRATEGY_VERSION 1U
#define DFPN_STRATEGY_HEADER_BYTES 104U
#define DFPN_CHECKPOINT_LOAD_PROGRESS_INTERVAL UINT64_C(25000000)
#define DFPN_SEARCH_PROGRESS_INTERVAL UINT64_C(10000000)
#define DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL ((size_t)50000000)

enum {
    TYPE_BM = 0,
    TYPE_BK = 1,
    TYPE_RM = 2,
    TYPE_RK = 3
};

typedef struct {
    uint8_t count[4];
    uint64_t boards;
    uint64_t state_count;
    uint64_t byte_count;
    uint8_t *wdl;
} RankedSignature;

typedef struct {
    uint32_t no_progress_plies;
    uint32_t signature_count;
    uint64_t total_states;
    uint64_t checksum;
    RankedSignature signatures[TB4_SIGNATURES];
    int signature_index[5][5][5][5];
} RankedTablebase;

static uint64_t completion_memo[33][7][7][7][7];
static uint8_t completion_seen[33][7][7][7][7];

typedef struct {
    uint8_t count[4];
    uint64_t boards;
    uint64_t byte_count;
    uint8_t *thresholds;
} CompactSignature;

typedef struct {
    uint32_t piece_count;
    uint32_t no_progress_plies;
    uint32_t signature_count;
    uint64_t total_positions;
    uint64_t total_states;
    uint64_t checksum;
    CompactSignature signatures[COMPACT_MAX_SIGNATURES];
    int signature_index[7][7][7][7];
    uint8_t *mapped_base;
    size_t mapped_length;
#if defined(_WIN32)
    HANDLE mapped_file;
#endif
    bool mapped_backing;
} CompactTablebase;

static bool type_allowed(int type, int square) {
    int row;
    int col;
    index_to_coord(square, &row, &col);
    (void)col;
    if (type == TYPE_BM) {
        return row != 0;
    }
    if (type == TYPE_RM) {
        return row != 7;
    }
    return true;
}

static uint64_t completion_count(
    int square,
    int bm,
    int bk,
    int rm,
    int rk
) {
    if (bm < 0 || bk < 0 || rm < 0 || rk < 0) {
        return 0;
    }
    if (square == 32) {
        return (bm | bk | rm | rk) == 0 ? 1 : 0;
    }
    if (completion_seen[square][bm][bk][rm][rk]) {
        return completion_memo[square][bm][bk][rm][rk];
    }
    uint64_t result = completion_count(square + 1, bm, bk, rm, rk);
    int remaining[4] = {bm, bk, rm, rk};
    for (int type = 0; type < 4; ++type) {
        if (remaining[type] > 0 && type_allowed(type, square)) {
            int next[4] = {bm, bk, rm, rk};
            --next[type];
            result += completion_count(
                square + 1, next[0], next[1], next[2], next[3]
            );
        }
    }
    completion_seen[square][bm][bk][rm][rk] = 1;
    completion_memo[square][bm][bk][rm][rk] = result;
    return result;
}

static int square_type(Position position, int square) {
    uint32_t bit = bit_at(square);
    if ((position.black & bit) != 0) {
        return (position.kings & bit) != 0 ? TYPE_BK : TYPE_BM;
    }
    if ((position.red & bit) != 0) {
        return (position.kings & bit) != 0 ? TYPE_RK : TYPE_RM;
    }
    return -1;
}

static uint64_t rank_position(Position position, const RankedSignature *signature) {
    int remaining[4] = {
        signature->count[TYPE_BM],
        signature->count[TYPE_BK],
        signature->count[TYPE_RM],
        signature->count[TYPE_RK]
    };
    uint64_t rank = 0;
    for (int square = 0; square < 32; ++square) {
        int actual = square_type(position, square);
        /* Empty sorts before all four piece types. */
        if (actual >= 0) {
            rank += completion_count(
                square + 1,
                remaining[0],
                remaining[1],
                remaining[2],
                remaining[3]
            );
            for (int candidate = 0; candidate < actual; ++candidate) {
                if (remaining[candidate] <= 0 || !type_allowed(candidate, square)) {
                    continue;
                }
                int next[4] = {
                    remaining[0], remaining[1], remaining[2], remaining[3]
                };
                --next[candidate];
                rank += completion_count(
                    square + 1, next[0], next[1], next[2], next[3]
                );
            }
            --remaining[actual];
        }
    }
    return rank;
}

static Position unrank_position(uint64_t rank, const RankedSignature *signature) {
    Position position;
    memset(&position, 0, sizeof(position));
    int remaining[4] = {
        signature->count[TYPE_BM],
        signature->count[TYPE_BK],
        signature->count[TYPE_RM],
        signature->count[TYPE_RK]
    };
    for (int square = 0; square < 32; ++square) {
        uint64_t empty_block = completion_count(
            square + 1,
            remaining[0],
            remaining[1],
            remaining[2],
            remaining[3]
        );
        if (rank < empty_block) {
            continue;
        }
        rank -= empty_block;
        bool selected = false;
        for (int type = 0; type < 4; ++type) {
            if (remaining[type] <= 0 || !type_allowed(type, square)) {
                continue;
            }
            int next[4] = {
                remaining[0], remaining[1], remaining[2], remaining[3]
            };
            --next[type];
            uint64_t block = completion_count(
                square + 1, next[0], next[1], next[2], next[3]
            );
            if (rank >= block) {
                rank -= block;
                continue;
            }
            uint32_t bit = bit_at(square);
            if (type == TYPE_BM || type == TYPE_BK) {
                position.black |= bit;
            } else {
                position.red |= bit;
            }
            if (type == TYPE_BK || type == TYPE_RK) {
                position.kings |= bit;
            }
            --remaining[type];
            selected = true;
            break;
        }
        if (!selected) {
            fprintf(stderr, "unrank failed at square %d\n", square);
            exit(5);
        }
    }
    return position;
}

static bool verify_rank_roundtrips(const RankedSignature *signature) {
    if (signature->boards == 0) {
        return false;
    }
    uint64_t samples[67] = {
        0,
        signature->boards / 2,
        signature->boards - 1
    };
    uint64_t generator = UINT64_C(0x9e3779b97f4a7c15);
    for (int index = 3; index < 67; ++index) {
        generator = generator * UINT64_C(6364136223846793005) + 1;
        samples[index] = generator % signature->boards;
    }
    for (int index = 0; index < 67; ++index) {
        Position position = unrank_position(samples[index], signature);
        if (rank_position(position, signature) != samples[index]) {
            return false;
        }
    }
    return true;
}

static void signature_for_position(Position position, uint8_t counts[4]) {
    counts[TYPE_BM] = (uint8_t)count_bits(position.black & ~position.kings);
    counts[TYPE_BK] = (uint8_t)count_bits(position.black & position.kings);
    counts[TYPE_RM] = (uint8_t)count_bits(position.red & ~position.kings);
    counts[TYPE_RK] = (uint8_t)count_bits(position.red & position.kings);
}

static int compare_signature_count_vectors(
    const uint8_t left[4],
    const uint8_t right[4]
) {
    int left_men = left[TYPE_BM] + left[TYPE_RM];
    int right_men = right[TYPE_BM] + right[TYPE_RM];
    if (left_men != right_men) {
        return left_men - right_men;
    }
    for (int type = 0; type < 4; ++type) {
        if (left[type] != right[type]) {
            return (int)left[type] - (int)right[type];
        }
    }
    return 0;
}

static int compare_canonical_signature_counts(
    const void *left_pointer,
    const void *right_pointer
) {
    return compare_signature_count_vectors(left_pointer, right_pointer);
}

/*
 * Produce the one canonical on-disk signature order shared by the ranked and
 * compact formats.  Full readers use this to reject permutations, omissions,
 * and substituted metadata even when payload totals/checksums are coherent.
 */
static uint32_t canonical_signature_counts(
    uint32_t piece_count,
    uint8_t counts[COMPACT_MAX_SIGNATURES][4]
) {
    if (piece_count < 4 || piece_count > COMPACT_MAX_PIECES) {
        return 0;
    }
    uint32_t index = 0;
    for (uint32_t bm = 0; bm <= piece_count; ++bm) {
        for (uint32_t bk = 0; bk <= piece_count - bm; ++bk) {
            for (uint32_t rm = 0; rm <= piece_count - bm - bk; ++rm) {
                uint32_t rk = piece_count - bm - bk - rm;
                if (bm + bk == 0 || rm + rk == 0) {
                    continue;
                }
                if (index >= COMPACT_MAX_SIGNATURES) {
                    return 0;
                }
                counts[index][TYPE_BM] = (uint8_t)bm;
                counts[index][TYPE_BK] = (uint8_t)bk;
                counts[index][TYPE_RM] = (uint8_t)rm;
                counts[index][TYPE_RK] = (uint8_t)rk;
                ++index;
            }
        }
    }
    qsort(
        counts,
        index,
        sizeof(counts[0]),
        compare_canonical_signature_counts
    );
    return index;
}

static int compare_signatures(const void *left_pointer, const void *right_pointer) {
    const RankedSignature *left = left_pointer;
    const RankedSignature *right = right_pointer;
    return compare_signature_count_vectors(left->count, right->count);
}

static bool tablebase_init(RankedTablebase *tablebase, int no_progress_plies) {
    memset(tablebase, 0, sizeof(*tablebase));
    memset(tablebase->signature_index, 0xff, sizeof(tablebase->signature_index));
    tablebase->no_progress_plies = (uint32_t)no_progress_plies;
    uint32_t index = 0;
    for (int bm = 0; bm <= 4; ++bm) {
        for (int bk = 0; bk <= 4 - bm; ++bk) {
            for (int rm = 0; rm <= 4 - bm - bk; ++rm) {
                int rk = 4 - bm - bk - rm;
                if (bm + bk == 0 || rm + rk == 0) {
                    continue;
                }
                RankedSignature *signature = &tablebase->signatures[index++];
                signature->count[TYPE_BM] = (uint8_t)bm;
                signature->count[TYPE_BK] = (uint8_t)bk;
                signature->count[TYPE_RM] = (uint8_t)rm;
                signature->count[TYPE_RK] = (uint8_t)rk;
            }
        }
    }
    if (index != TB4_SIGNATURES) {
        return false;
    }
    tablebase->signature_count = index;
    qsort(
        tablebase->signatures,
        tablebase->signature_count,
        sizeof(tablebase->signatures[0]),
        compare_signatures
    );
    for (uint32_t signature_index = 0;
         signature_index < tablebase->signature_count;
         ++signature_index) {
        RankedSignature *signature = &tablebase->signatures[signature_index];
        int bm = signature->count[TYPE_BM];
        int bk = signature->count[TYPE_BK];
        int rm = signature->count[TYPE_RM];
        int rk = signature->count[TYPE_RK];
        signature->boards = completion_count(0, bm, bk, rm, rk);
        if (!verify_rank_roundtrips(signature)) {
            fprintf(
                stderr,
                "rank/unrank self-check failed for [%d,%d,%d,%d]\n",
                bm, bk, rm, rk
            );
            return false;
        }
        signature->state_count =
            signature->boards * 2 * ((uint64_t)no_progress_plies + 1);
        signature->byte_count = (signature->state_count + 3) / 4;
        signature->wdl = calloc((size_t)signature->byte_count, 1);
        if (signature->wdl == NULL) {
            return false;
        }
        tablebase->total_states += signature->state_count;
        tablebase->signature_index[bm][bk][rm][rk] = (int)signature_index;
    }
    return true;
}

static void tablebase_destroy(RankedTablebase *tablebase) {
    for (uint32_t index = 0; index < tablebase->signature_count; ++index) {
        free(tablebase->signatures[index].wdl);
    }
    memset(tablebase, 0, sizeof(*tablebase));
}

static uint64_t state_index(
    const RankedSignature *signature,
    uint64_t rank,
    int turn,
    int clock
) {
    uint64_t turn_index = turn == BLACK ? 1 : 0;
    return (((uint64_t)clock * signature->boards + rank) * 2) + turn_index;
}

static uint8_t get_wdl(
    const RankedSignature *signature,
    uint64_t rank,
    int turn,
    int clock
) {
    uint64_t index = state_index(signature, rank, turn, clock);
    return (signature->wdl[index >> 2] >> ((index & 3) * 2)) & 3;
}

static void set_wdl(
    RankedSignature *signature,
    uint64_t rank,
    int turn,
    int clock,
    uint8_t value
) {
    uint64_t index = state_index(signature, rank, turn, clock);
    uint8_t shift = (uint8_t)((index & 3) * 2);
    uint8_t mask = (uint8_t)(3U << shift);
    signature->wdl[index >> 2] =
        (uint8_t)((signature->wdl[index >> 2] & ~mask) | (value << shift));
}

static uint8_t invert_wdl(uint8_t value) {
    return (uint8_t)(2 - value);
}

static uint8_t probe_child(RankedTablebase *tablebase, Position child) {
    int pieces = count_bits(occupied(child));
    if (pieces <= 3) {
        int outcome;
        int distance;
        int result = makhos_tb3_probe(
            child.red,
            child.black,
            child.kings,
            child.turn,
            child.reversible_plies,
            &outcome,
            &distance
        );
        (void)distance;
        if (result != 0) {
            fprintf(stderr, "3-piece probe failed with code %d\n", result);
            exit(6);
        }
        return (uint8_t)(outcome + 1);
    }
    uint8_t counts[4];
    signature_for_position(child, counts);
    int signature_index = tablebase->signature_index
        [counts[0]][counts[1]][counts[2]][counts[3]];
    if (signature_index < 0) {
        fprintf(stderr, "missing 4-piece signature\n");
        exit(7);
    }
    RankedSignature *signature = &tablebase->signatures[signature_index];
    uint64_t rank = rank_position(child, signature);
    return get_wdl(
        signature,
        rank,
        child.turn,
        child.reversible_plies
    );
}

static bool build_tablebase(RankedTablebase *tablebase, int tb3_hash_power) {
    int result = makhos_tb3_init((int)tablebase->no_progress_plies, tb3_hash_power);
    if (result != 0) {
        fprintf(stderr, "unable to initialize 3-piece dependency: %d\n", result);
        return false;
    }
    MoveList *moves = calloc(1, sizeof(*moves));
    if (moves == NULL) {
        return false;
    }
    uint64_t completed = 0;
    for (uint32_t signature_index = 0;
         signature_index < tablebase->signature_count;
         ++signature_index) {
        RankedSignature *signature = &tablebase->signatures[signature_index];
        fprintf(
            stderr,
            "signature %u/%u [%u,%u,%u,%u] boards=%" PRIu64 "\n",
            signature_index + 1,
            tablebase->signature_count,
            signature->count[0], signature->count[1],
            signature->count[2], signature->count[3],
            signature->boards
        );
        for (int clock = (int)tablebase->no_progress_plies; clock >= 0; --clock) {
            for (uint64_t rank = 0; rank < signature->boards; ++rank) {
                Position base = unrank_position(rank, signature);
                base.reversible_plies = (uint8_t)clock;
                for (int turn = RED; turn <= BLACK; ++turn) {
                    uint8_t value;
                    if (clock == (int)tablebase->no_progress_plies) {
                        value = 1; /* draw */
                    } else {
                        base.turn = (uint8_t)turn;
                        generate_moves(base, moves);
                        if (moves->count == 0) {
                            value = 0; /* loss */
                        } else {
                            value = 0;
                            for (uint32_t move_index = 0;
                                 move_index < moves->count;
                                 ++move_index) {
                                uint8_t child = probe_child(
                                    tablebase, moves->moves[move_index].next
                                );
                                uint8_t candidate = invert_wdl(child);
                                if (candidate > value) {
                                    value = candidate;
                                    if (value == 2) {
                                        break;
                                    }
                                }
                            }
                        }
                    }
                    set_wdl(signature, rank, turn, clock, value);
                    ++completed;
                }
            }
        }
    }
    fprintf(stderr, "computed states: %" PRIu64 "\n", completed);
    free(moves);
    return completed == tablebase->total_states;
}

static uint64_t checksum_update(uint64_t hash, const uint8_t *data, uint64_t length) {
    for (uint64_t index = 0; index < length; ++index) {
        hash ^= data[index];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static bool write_tablebase(const RankedTablebase *tablebase, const char *path) {
    FILE *file = fopen(path, "wb");
    if (file == NULL) {
        return false;
    }
    uint64_t checksum = UINT64_C(1469598103934665603);
    for (uint32_t index = 0; index < tablebase->signature_count; ++index) {
        const RankedSignature *signature = &tablebase->signatures[index];
        checksum = checksum_update(checksum, signature->wdl, signature->byte_count);
    }
    bool ok =
        fwrite(TB4_MAGIC, 1, 8, file) == 8 &&
        fwrite(&(uint32_t){TB4_VERSION}, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase->signature_count, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase->total_states, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&checksum, sizeof(uint64_t), 1, file) == 1;
    for (uint32_t index = 0; ok && index < tablebase->signature_count; ++index) {
        const RankedSignature *signature = &tablebase->signatures[index];
        ok =
            fwrite(signature->count, 1, 4, file) == 4 &&
            fwrite(&signature->boards, sizeof(uint64_t), 1, file) == 1 &&
            fwrite(&signature->byte_count, sizeof(uint64_t), 1, file) == 1 &&
            fwrite(signature->wdl, 1, (size_t)signature->byte_count, file) ==
                signature->byte_count;
    }
    fclose(file);
    if (ok) {
        printf("checksum: %016" PRIx64 "\n", checksum);
    }
    return ok;
}

static bool read_tablebase(RankedTablebase *tablebase, const char *path) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return false;
    }
    char magic[8];
    uint32_t version = 0;
    uint64_t expected_checksum;
    uint8_t canonical_counts[COMPACT_MAX_SIGNATURES][4] = {{0}};
    uint32_t canonical_count = canonical_signature_counts(
        4, canonical_counts
    );
    memset(tablebase, 0, sizeof(*tablebase));
    memset(tablebase->signature_index, 0xff, sizeof(tablebase->signature_index));
    bool ok =
        fread(magic, 1, 8, file) == 8 &&
        memcmp(magic, TB4_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, file) == 1 &&
        version == TB4_VERSION &&
        fread(&tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        tablebase->no_progress_plies >= 1 &&
        tablebase->no_progress_plies <= 200 &&
        fread(&tablebase->signature_count, sizeof(uint32_t), 1, file) == 1 &&
        canonical_count == TB4_SIGNATURES &&
        tablebase->signature_count == canonical_count &&
        fread(&tablebase->total_states, sizeof(uint64_t), 1, file) == 1 &&
        fread(&expected_checksum, sizeof(uint64_t), 1, file) == 1;
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint64_t computed_total_states = 0;
    for (uint32_t index = 0; ok && index < tablebase->signature_count; ++index) {
        RankedSignature *signature = &tablebase->signatures[index];
        ok =
            fread(signature->count, 1, 4, file) == 4 &&
            fread(&signature->boards, sizeof(uint64_t), 1, file) == 1 &&
            fread(&signature->byte_count, sizeof(uint64_t), 1, file) == 1;
        if (!ok) {
            break;
        }
        int bm = signature->count[TYPE_BM];
        int bk = signature->count[TYPE_BK];
        int rm = signature->count[TYPE_RM];
        int rk = signature->count[TYPE_RK];
        if (
            memcmp(signature->count, canonical_counts[index], 4) != 0 ||
            tablebase->signature_index[bm][bk][rm][rk] >= 0 ||
            signature->boards != completion_count(0, bm, bk, rm, rk)
        ) {
            ok = false;
            break;
        }
        signature->state_count = signature->boards * 2 *
            ((uint64_t)tablebase->no_progress_plies + 1);
        if (signature->byte_count != (signature->state_count + 3) / 4) {
            ok = false;
            break;
        }
        computed_total_states += signature->state_count;
        signature->wdl = malloc((size_t)signature->byte_count);
        if (
            signature->wdl == NULL ||
            fread(signature->wdl, 1, (size_t)signature->byte_count, file) !=
                signature->byte_count
        ) {
            ok = false;
            break;
        }
        checksum = checksum_update(checksum, signature->wdl, signature->byte_count);
        tablebase->signature_index[bm][bk][rm][rk] = (int)index;
    }
    if (ok && fgetc(file) != EOF) {
        ok = false;
    }
    fclose(file);
    bool verified =
        ok &&
        computed_total_states == tablebase->total_states &&
        checksum == expected_checksum;
    if (verified) {
        tablebase->checksum = expected_checksum;
    }
    return verified;
}

typedef struct {
    FILE *file;
    const uint8_t *cursor;
    size_t remaining;
    bool mapped;
} CompactInput;

static bool compact_try_map_readonly(
    CompactTablebase *tablebase,
    const char *path
) {
#if defined(_WIN32)
    HANDLE file = CreateFileA(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_DELETE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (file == INVALID_HANDLE_VALUE) {
        return false;
    }
    LARGE_INTEGER file_size;
    if (
        !GetFileSizeEx(file, &file_size) ||
        file_size.QuadPart <= 0 ||
        (uintmax_t)file_size.QuadPart > (uintmax_t)SIZE_MAX
    ) {
        CloseHandle(file);
        return false;
    }
    HANDLE mapping = CreateFileMappingA(
        file, NULL, PAGE_READONLY, 0, 0, NULL
    );
    if (mapping == NULL) {
        CloseHandle(file);
        return false;
    }
    void *base = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
    CloseHandle(mapping);
    if (base == NULL) {
        CloseHandle(file);
        return false;
    }
    tablebase->mapped_base = base;
    tablebase->mapped_length = (size_t)file_size.QuadPart;
    tablebase->mapped_file = file;
#else
    int file = open(path, O_RDONLY);
    if (file < 0) {
        return false;
    }
    struct stat metadata;
    if (
        fstat(file, &metadata) != 0 || metadata.st_size <= 0 ||
        (uintmax_t)metadata.st_size > (uintmax_t)SIZE_MAX
    ) {
        close(file);
        return false;
    }
    size_t length = (size_t)metadata.st_size;
    void *base = mmap(NULL, length, PROT_READ, MAP_PRIVATE, file, 0);
    close(file);
    if (base == MAP_FAILED) {
        return false;
    }
    tablebase->mapped_base = base;
    tablebase->mapped_length = length;
#endif
    tablebase->mapped_backing = true;
    return true;
}

static void compact_unmap_readonly(CompactTablebase *tablebase) {
    if (!tablebase->mapped_backing) {
        return;
    }
#if defined(_WIN32)
    if (tablebase->mapped_base != NULL) {
        UnmapViewOfFile(tablebase->mapped_base);
    }
    if (
        tablebase->mapped_file != NULL &&
        tablebase->mapped_file != INVALID_HANDLE_VALUE
    ) {
        CloseHandle(tablebase->mapped_file);
    }
#else
    if (tablebase->mapped_base != NULL && tablebase->mapped_length != 0) {
        munmap(tablebase->mapped_base, tablebase->mapped_length);
    }
#endif
}

static bool compact_input_read(
    CompactInput *input,
    void *output,
    size_t length
) {
    if (!input->mapped) {
        return fread(output, 1, length, input->file) == length;
    }
    if (length > input->remaining) {
        return false;
    }
    memcpy(output, input->cursor, length);
    input->cursor += length;
    input->remaining -= length;
    return true;
}

static bool compact_input_take_payload(
    CompactInput *input,
    uint64_t byte_count,
    uint8_t **payload
) {
    if (byte_count == 0 || byte_count > (uint64_t)SIZE_MAX) {
        return false;
    }
    size_t length = (size_t)byte_count;
    if (input->mapped) {
        if (length > input->remaining) {
            return false;
        }
        *payload = (uint8_t *)input->cursor;
        input->cursor += length;
        input->remaining -= length;
        return true;
    }
    *payload = malloc(length);
    return
        *payload != NULL &&
        fread(*payload, 1, length, input->file) == length;
}

static bool compact_input_at_end(CompactInput *input) {
    if (input->mapped) {
        return input->remaining == 0;
    }
    return fgetc(input->file) == EOF && !ferror(input->file);
}

static bool compact_input_close(CompactInput *input) {
    if (input->file == NULL) {
        return true;
    }
    bool ok = fclose(input->file) == 0;
    input->file = NULL;
    return ok;
}

static void compact_tablebase_destroy(CompactTablebase *tablebase) {
    if (tablebase->mapped_backing) {
        compact_unmap_readonly(tablebase);
    } else {
        for (uint32_t index = 0;
             index < tablebase->signature_count;
             ++index) {
            free(tablebase->signatures[index].thresholds);
        }
    }
    memset(tablebase, 0, sizeof(*tablebase));
}

static bool read_compact_tablebase_mode(
    CompactTablebase *tablebase,
    const char *path,
    bool allow_mapping
) {
    memset(tablebase, 0, sizeof(*tablebase));
    memset(tablebase->signature_index, 0xff, sizeof(tablebase->signature_index));
    CompactInput input;
    memset(&input, 0, sizeof(input));
    if (allow_mapping && compact_try_map_readonly(tablebase, path)) {
        input.cursor = tablebase->mapped_base;
        input.remaining = tablebase->mapped_length;
        input.mapped = true;
    } else {
        input.file = fopen(path, "rb");
        if (input.file == NULL) {
            return false;
        }
    }

    char magic[8];
    uint32_t version;
    uint8_t canonical_counts[COMPACT_MAX_SIGNATURES][4] = {{0}};
    uint32_t canonical_count = 0;
    bool ok =
        compact_input_read(&input, magic, 8) &&
        memcmp(magic, COMPACT_WDL_MAGIC, 8) == 0 &&
        compact_input_read(&input, &version, sizeof(version)) &&
        version == COMPACT_WDL_VERSION &&
        compact_input_read(
            &input, &tablebase->piece_count, sizeof(uint32_t)
        ) &&
        (tablebase->piece_count >= 4 &&
         tablebase->piece_count <= COMPACT_MAX_PIECES) &&
        compact_input_read(
            &input, &tablebase->no_progress_plies, sizeof(uint32_t)
        ) &&
        tablebase->no_progress_plies >= 1 &&
        tablebase->no_progress_plies <= 126 &&
        compact_input_read(
            &input, &tablebase->signature_count, sizeof(uint32_t)
        ) &&
        tablebase->signature_count <= COMPACT_MAX_SIGNATURES &&
        compact_input_read(
            &input, &tablebase->total_positions, sizeof(uint64_t)
        ) &&
        compact_input_read(
            &input, &tablebase->total_states, sizeof(uint64_t)
        ) &&
        compact_input_read(
            &input, &tablebase->checksum, sizeof(uint64_t)
        );
    if (ok) {
        canonical_count = canonical_signature_counts(
            tablebase->piece_count, canonical_counts
        );
        ok = canonical_count != 0 &&
            tablebase->signature_count == canonical_count;
    }
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint64_t computed_positions = 0;
    for (uint32_t index = 0; ok && index < tablebase->signature_count; ++index) {
        CompactSignature *signature = &tablebase->signatures[index];
        ok =
            compact_input_read(&input, signature->count, 4) &&
            compact_input_read(
                &input, &signature->boards, sizeof(uint64_t)
            ) &&
            compact_input_read(
                &input, &signature->byte_count, sizeof(uint64_t)
            );
        if (!ok) {
            break;
        }
        int bm = signature->count[TYPE_BM];
        int bk = signature->count[TYPE_BK];
        int rm = signature->count[TYPE_RM];
        int rk = signature->count[TYPE_RK];
        if (
            memcmp(signature->count, canonical_counts[index], 4) != 0 ||
            tablebase->signature_index[bm][bk][rm][rk] >= 0 ||
            signature->boards > UINT64_MAX / 2 ||
            signature->byte_count != signature->boards * 2 ||
            signature->byte_count > (uint64_t)SIZE_MAX ||
            signature->boards != completion_count(0, bm, bk, rm, rk) ||
            computed_positions > UINT64_MAX - signature->byte_count
        ) {
            ok = false;
            break;
        }
        if (!compact_input_take_payload(
                &input,
                signature->byte_count,
                &signature->thresholds
            )) {
            ok = false;
            break;
        }
        for (uint64_t byte = 0; byte < signature->byte_count; ++byte) {
            uint8_t encoded = signature->thresholds[byte];
            if (
                encoded != 0 &&
                ((encoded & 0x7f) == 0 ||
                 (encoded & 0x7f) > tablebase->no_progress_plies)
            ) {
                ok = false;
                break;
            }
        }
        if (!ok) {
            break;
        }
        checksum = checksum_update(
            checksum, signature->thresholds, signature->byte_count
        );
        computed_positions += signature->byte_count;
        tablebase->signature_index[bm][bk][rm][rk] = (int)index;
    }
    if (ok && !compact_input_at_end(&input)) {
        ok = false;
    }
    if (!compact_input_close(&input)) {
        ok = false;
    }
    uint64_t clock_count =
        (uint64_t)tablebase->no_progress_plies + 1;
    bool verified =
        ok &&
        computed_positions == tablebase->total_positions &&
        computed_positions <= UINT64_MAX / clock_count &&
        tablebase->total_states == computed_positions * clock_count &&
        checksum == tablebase->checksum;
    if (!verified) {
        compact_tablebase_destroy(tablebase);
    }
    return verified;
}

static bool read_compact_tablebase(CompactTablebase *tablebase, const char *path) {
    return read_compact_tablebase_mode(tablebase, path, true);
}

static bool compact_tablebase_has_complete_schema(
    const CompactTablebase *tablebase,
    uint32_t piece_count
) {
    uint8_t canonical_counts[COMPACT_MAX_SIGNATURES][4] = {{0}};
    uint32_t expected = canonical_signature_counts(
        piece_count, canonical_counts
    );
    return
        expected != 0 &&
        tablebase->piece_count == piece_count &&
        tablebase->signature_count == expected;
}

static uint8_t get_compact_wdl(
    const CompactSignature *signature,
    uint64_t rank,
    int turn,
    int clock
) {
    uint64_t turn_index = turn == BLACK ? 1 : 0;
    uint8_t encoded = signature->thresholds[rank * 2 + turn_index];
    if (encoded == 0 || clock > (int)((encoded & 0x7f) - 1)) {
        return 1;
    }
    return (encoded & 0x80) != 0 ? 2 : 0;
}

static const char *wdl_name(uint8_t value) {
    if (value == 2) {
        return "WIN";
    }
    if (value == 1) {
        return "DRAW";
    }
    return "LOSS";
}

static int command_build(int no_progress, int hash_power, const char *path) {
    RankedTablebase tablebase;
    if (!tablebase_init(&tablebase, no_progress)) {
        fprintf(stderr, "unable to allocate ranked tablebase\n");
        return 2;
    }
    printf("total states: %" PRIu64 "\n", tablebase.total_states);
    printf("packed bytes: %" PRIu64 "\n", (tablebase.total_states + 3) / 4);
    if (!build_tablebase(&tablebase, hash_power)) {
        tablebase_destroy(&tablebase);
        makhos_tb3_shutdown();
        return 3;
    }
    bool written = write_tablebase(&tablebase, path);
    tablebase_destroy(&tablebase);
    makhos_tb3_shutdown();
    if (!written) {
        fprintf(stderr, "failed to write %s\n", path);
        return 4;
    }
    printf("wrote: %s\n", path);
    return 0;
}

static int command_probe(const char *path, const char *text, int clock) {
    RankedTablebase tablebase;
    if (
        !read_tablebase(&tablebase, path) ||
        tablebase.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read or verify %s\n", path);
        return 2;
    }
    Position position;
    if (!parse_position(text, &position) || count_bits(occupied(position)) != 4) {
        fprintf(stderr, "probe requires a valid four-piece position\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    if (clock < 0 || clock > (int)tablebase.no_progress_plies) {
        fprintf(stderr, "clock outside tablebase range\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    uint8_t counts[4];
    signature_for_position(position, counts);
    int signature_index = tablebase.signature_index
        [counts[0]][counts[1]][counts[2]][counts[3]];
    if (signature_index < 0) {
        fprintf(stderr, "position must contain pieces from both sides\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    RankedSignature *signature = &tablebase.signatures[signature_index];
    uint64_t rank = rank_position(position, signature);
    uint8_t value = get_wdl(signature, rank, position.turn, clock);
    printf("outcome: %s\n", wdl_name(value));
    printf("rank: %" PRIu64 "\n", rank);
    tablebase_destroy(&tablebase);
    return 0;
}

static Position rotate_and_swap(Position position) {
    Position transformed;
    memset(&transformed, 0, sizeof(transformed));
    transformed.turn = other(position.turn);
    transformed.reversible_plies = position.reversible_plies;
    for (int square = 0; square < 32; ++square) {
        int row;
        int col;
        index_to_coord(square, &row, &col);
        int target = coord_to_index(7 - row, 7 - col);
        uint32_t source_bit = bit_at(square);
        uint32_t target_bit = bit_at(target);
        if ((position.black & source_bit) != 0) {
            transformed.red |= target_bit;
        } else if ((position.red & source_bit) != 0) {
            transformed.black |= target_bit;
        }
        if ((position.kings & source_bit) != 0) {
            transformed.kings |= target_bit;
        }
    }
    return transformed;
}

static int command_verify(const char *path, int clock) {
    RankedTablebase tablebase;
    if (!read_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read or verify %s\n", path);
        return 2;
    }
    if (clock < 0 || clock > (int)tablebase.no_progress_plies) {
        fprintf(stderr, "clock outside tablebase range\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    uint64_t outcomes[3] = {0, 0, 0};
    uint64_t checked = 0;
    for (uint32_t signature_index = 0;
         signature_index < tablebase.signature_count;
         ++signature_index) {
        RankedSignature *signature = &tablebase.signatures[signature_index];
        for (uint64_t rank = 0; rank < signature->boards; ++rank) {
            Position base = unrank_position(rank, signature);
            if (rank_position(base, signature) != rank) {
                fprintf(stderr, "exhaustive rank roundtrip failed\n");
                tablebase_destroy(&tablebase);
                return 3;
            }
            base.reversible_plies = (uint8_t)clock;
            for (int turn = RED; turn <= BLACK; ++turn) {
                base.turn = (uint8_t)turn;
                uint8_t value = get_wdl(signature, rank, turn, clock);
                if (value > 2) {
                    fprintf(stderr, "invalid WDL value\n");
                    tablebase_destroy(&tablebase);
                    return 3;
                }
                ++outcomes[value];
                ++checked;

                Position transformed = rotate_and_swap(base);
                uint8_t transformed_counts[4];
                signature_for_position(transformed, transformed_counts);
                int transformed_signature_index = tablebase.signature_index
                    [transformed_counts[0]][transformed_counts[1]]
                    [transformed_counts[2]][transformed_counts[3]];
                if (transformed_signature_index < 0) {
                    fprintf(stderr, "symmetry signature missing\n");
                    tablebase_destroy(&tablebase);
                    return 3;
                }
                RankedSignature *transformed_signature =
                    &tablebase.signatures[transformed_signature_index];
                uint64_t transformed_rank = rank_position(
                    transformed, transformed_signature
                );
                uint8_t transformed_value = get_wdl(
                    transformed_signature,
                    transformed_rank,
                    transformed.turn,
                    clock
                );
                if (transformed_value != value) {
                    fprintf(
                        stderr,
                        "color-rotation symmetry mismatch at signature %u rank %" PRIu64
                        " turn %d\n",
                        signature_index,
                        rank,
                        turn
                    );
                    tablebase_destroy(&tablebase);
                    return 3;
                }
            }
        }
    }
    printf("clock: %d\n", clock);
    printf("positions checked: %" PRIu64 "\n", checked);
    printf(
        "side-to-move W/D/L: %" PRIu64 "/%" PRIu64 "/%" PRIu64 "\n",
        outcomes[2], outcomes[1], outcomes[0]
    );
    printf("rank roundtrip: PASS\n");
    printf("color-rotation symmetry: PASS\n");
    tablebase_destroy(&tablebase);
    return 0;
}

static int command_verify_monotonic(const char *path) {
    RankedTablebase tablebase;
    if (!read_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read or verify %s\n", path);
        return 2;
    }
    uint64_t positions = 0;
    uint64_t always_draw = 0;
    uint64_t resolves_win = 0;
    uint64_t resolves_loss = 0;
    uint64_t threshold_counts[201];
    memset(threshold_counts, 0, sizeof(threshold_counts));
    for (uint32_t signature_index = 0;
         signature_index < tablebase.signature_count;
         ++signature_index) {
        RankedSignature *signature = &tablebase.signatures[signature_index];
        for (uint64_t rank = 0; rank < signature->boards; ++rank) {
            for (int turn = RED; turn <= BLACK; ++turn) {
                uint8_t resolved = 1;
                int threshold = -1;
                for (int clock = (int)tablebase.no_progress_plies;
                     clock >= 0;
                     --clock) {
                    uint8_t value = get_wdl(signature, rank, turn, clock);
                    if (value > 2) {
                        fprintf(stderr, "invalid WDL value during monotonic check\n");
                        tablebase_destroy(&tablebase);
                        return 3;
                    }
                    if (resolved == 1 && value != 1) {
                        resolved = value;
                        threshold = clock;
                    } else if (resolved != 1 && value != resolved) {
                        fprintf(
                            stderr,
                            "non-monotonic WDL at signature %u rank %" PRIu64
                            " turn %d clock %d\n",
                            signature_index,
                            rank,
                            turn,
                            clock
                        );
                        tablebase_destroy(&tablebase);
                        return 3;
                    }
                }
                ++positions;
                if (resolved == 1) {
                    ++always_draw;
                } else {
                    ++threshold_counts[threshold];
                    if (resolved == 2) {
                        ++resolves_win;
                    } else {
                        ++resolves_loss;
                    }
                }
            }
        }
    }
    printf("positions checked: %" PRIu64 "\n", positions);
    printf(
        "always-draw/win/loss: %" PRIu64 "/%" PRIu64 "/%" PRIu64 "\n",
        always_draw,
        resolves_win,
        resolves_loss
    );
    printf("one-byte threshold payload: %" PRIu64 " bytes\n", positions);
    printf("WDL clock monotonicity: PASS\n");
    printf("non-draw threshold distribution:\n");
    for (uint32_t clock = 0; clock < tablebase.no_progress_plies; ++clock) {
        if (threshold_counts[clock] > 0) {
            printf("  clock %u: %" PRIu64 "\n", clock, threshold_counts[clock]);
        }
    }
    tablebase_destroy(&tablebase);
    return 0;
}

static int command_compress(const char *input_path, const char *output_path) {
    RankedTablebase tablebase;
    if (!read_tablebase(&tablebase, input_path)) {
        fprintf(stderr, "unable to read or verify %s\n", input_path);
        return 2;
    }
    if (tablebase.no_progress_plies > 126) {
        fprintf(stderr, "one-byte compact format supports at most 126 plies\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    FILE *file = fopen(output_path, "wb");
    if (file == NULL) {
        tablebase_destroy(&tablebase);
        return 2;
    }
    uint32_t version = COMPACT_WDL_VERSION;
    uint32_t piece_count = 4;
    uint64_t logical_states = tablebase.total_states;
    uint64_t total_positions = 0;
    for (uint32_t index = 0; index < tablebase.signature_count; ++index) {
        total_positions += tablebase.signatures[index].boards * 2;
    }
    uint64_t checksum = 0;
    bool ok =
        fwrite(COMPACT_WDL_MAGIC, 1, 8, file) == 8 &&
        fwrite(&version, sizeof(version), 1, file) == 1 &&
        fwrite(&piece_count, sizeof(piece_count), 1, file) == 1 &&
        fwrite(&tablebase.no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&tablebase.signature_count, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&total_positions, sizeof(total_positions), 1, file) == 1 &&
        fwrite(&logical_states, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&checksum, sizeof(checksum), 1, file) == 1;
    checksum = UINT64_C(1469598103934665603);
    for (uint32_t signature_index = 0;
         ok && signature_index < tablebase.signature_count;
         ++signature_index) {
        RankedSignature *signature = &tablebase.signatures[signature_index];
        uint64_t byte_count = signature->boards * 2;
        uint8_t *compact = malloc((size_t)byte_count);
        if (compact == NULL) {
            ok = false;
            break;
        }
        for (uint64_t rank = 0; rank < signature->boards; ++rank) {
            for (int turn = RED; turn <= BLACK; ++turn) {
                uint8_t resolved = 1;
                int threshold = -1;
                for (int clock = (int)tablebase.no_progress_plies;
                     clock >= 0;
                     --clock) {
                    uint8_t value = get_wdl(signature, rank, turn, clock);
                    if (resolved == 1 && value != 1) {
                        resolved = value;
                        threshold = clock;
                    } else if (resolved != 1 && value != resolved) {
                        fprintf(stderr, "cannot compress non-monotonic WDL sequence\n");
                        free(compact);
                        fclose(file);
                        tablebase_destroy(&tablebase);
                        return 3;
                    }
                }
                uint8_t encoded = 0;
                if (resolved != 1) {
                    encoded = (uint8_t)(threshold + 1);
                    if (resolved == 2) {
                        encoded |= 0x80;
                    }
                }
                uint64_t turn_index = turn == BLACK ? 1 : 0;
                compact[rank * 2 + turn_index] = encoded;
            }
        }
        checksum = checksum_update(checksum, compact, byte_count);
        ok =
            fwrite(signature->count, 1, 4, file) == 4 &&
            fwrite(&signature->boards, sizeof(uint64_t), 1, file) == 1 &&
            fwrite(&byte_count, sizeof(uint64_t), 1, file) == 1 &&
            fwrite(compact, 1, (size_t)byte_count, file) == byte_count;
        free(compact);
    }
    if (ok) {
        ok = fseek(file, 40, SEEK_SET) == 0 &&
            fwrite(&checksum, sizeof(checksum), 1, file) == 1;
    }
    if (fclose(file) != 0) {
        ok = false;
    }
    tablebase_destroy(&tablebase);
    if (!ok) {
        fprintf(stderr, "failed to write compact tablebase\n");
        return 2;
    }
    printf("logical WDL states: %" PRIu64 "\n", logical_states);
    printf("compact positions: %" PRIu64 "\n", total_positions);
    printf("compact checksum: %016" PRIx64 "\n", checksum);
    printf("wrote: %s\n", output_path);
    return 0;
}

static int command_compare_compact(
    const char *full_path,
    const char *compact_path
) {
    RankedTablebase full;
    CompactTablebase compact;
    if (!read_tablebase(&full, full_path)) {
        fprintf(stderr, "unable to read full tablebase\n");
        return 2;
    }
    if (!read_compact_tablebase(&compact, compact_path)) {
        fprintf(stderr, "unable to read compact tablebase\n");
        tablebase_destroy(&full);
        return 2;
    }
    if (
        compact.piece_count != 4 ||
        compact.no_progress_plies != full.no_progress_plies ||
        compact.total_states != full.total_states
    ) {
        fprintf(stderr, "full/compact metadata mismatch\n");
        compact_tablebase_destroy(&compact);
        tablebase_destroy(&full);
        return 3;
    }
    uint64_t compared = 0;
    for (uint32_t full_index = 0;
         full_index < full.signature_count;
         ++full_index) {
        RankedSignature *full_signature = &full.signatures[full_index];
        int compact_index = compact.signature_index
            [full_signature->count[0]][full_signature->count[1]]
            [full_signature->count[2]][full_signature->count[3]];
        if (compact_index < 0) {
            fprintf(stderr, "compact signature missing\n");
            compact_tablebase_destroy(&compact);
            tablebase_destroy(&full);
            return 3;
        }
        CompactSignature *compact_signature =
            &compact.signatures[compact_index];
        for (uint64_t rank = 0; rank < full_signature->boards; ++rank) {
            for (int turn = RED; turn <= BLACK; ++turn) {
                for (uint32_t clock = 0;
                     clock <= full.no_progress_plies;
                     ++clock) {
                    uint8_t expected = get_wdl(
                        full_signature, rank, turn, (int)clock
                    );
                    uint8_t actual = get_compact_wdl(
                        compact_signature, rank, turn, (int)clock
                    );
                    if (actual != expected) {
                        fprintf(
                            stderr,
                            "compact mismatch at signature %u rank %" PRIu64
                            " turn %d clock %u\n",
                            full_index,
                            rank,
                            turn,
                            clock
                        );
                        compact_tablebase_destroy(&compact);
                        tablebase_destroy(&full);
                        return 3;
                    }
                    ++compared;
                }
            }
        }
    }
    printf("WDL values compared: %" PRIu64 "\n", compared);
    printf("full checksum: %016" PRIx64 "\n", full.checksum);
    printf("compact checksum: %016" PRIx64 "\n", compact.checksum);
    printf("full/compact differential: PASS\n");
    compact_tablebase_destroy(&compact);
    tablebase_destroy(&full);
    return 0;
}

enum {
    PROOF_DISPROVEN = 0,
    PROOF_PROVEN = 1
};

typedef struct {
    Position position;
    uint8_t value;
    uint8_t used;
} ProofEntry;

typedef struct {
    Position position;
    int score;
    uint64_t tie_break;
    bool preferred;
} ProofChild;

typedef struct {
    RankedTablebase *tablebase;
    CompactTablebase *frontier;
    ProofEntry *entries;
    size_t capacity;
    size_t count;
    MoveList *generator;
    uint64_t node_budget;
    uint64_t nodes;
    uint64_t cache_hits;
    uint64_t tablebase_hits;
    size_t maximum_depth;
    uint8_t root_player;
    Position preferred_line[PROOF_PREFERRED_LINE_MAX];
    size_t preferred_line_length;
    bool failed;
    const char *failure_reason;
} ProofContext;

static ProofEntry *proof_find_slot(
    ProofContext *context,
    Position position,
    bool create
) {
    size_t mask = context->capacity - 1;
    size_t slot = (size_t)(hash_position(position) & mask);
    for (size_t probe = 0; probe < context->capacity; ++probe) {
        ProofEntry *entry = &context->entries[slot];
        if (!entry->used) {
            return create ? entry : NULL;
        }
        if (same_exact_key(entry->position, position)) {
            return entry;
        }
        slot = (slot + 1) & mask;
    }
    context->failed = true;
    context->failure_reason = "proof transposition table is full";
    return NULL;
}

static bool proof_store(
    ProofContext *context,
    Position position,
    uint8_t value
) {
    ProofEntry *entry = proof_find_slot(context, position, true);
    if (entry == NULL) {
        return false;
    }
    if (!entry->used) {
        entry->used = 1;
        entry->position = position;
        ++context->count;
    }
    entry->value = value;
    return true;
}

static int proof_material_score(Position position, uint8_t root_player) {
    int score = 0;
    for (int square = 0; square < 32; ++square) {
        uint32_t bit = bit_at(square);
        uint8_t owner;
        if ((position.black & bit) != 0) {
            owner = BLACK;
        } else if ((position.red & bit) != 0) {
            owner = RED;
        } else {
            continue;
        }
        int value = (position.kings & bit) != 0 ? 330 : 100;
        score += owner == root_player ? value : -value;
    }
    return score;
}

static int compare_proof_children(const void *left_pointer, const void *right_pointer) {
    const ProofChild *left = left_pointer;
    const ProofChild *right = right_pointer;
    if (left->preferred != right->preferred) {
        return left->preferred ? -1 : 1;
    }
    if (left->score != right->score) {
        return left->score < right->score ? 1 : -1;
    }
    if (left->tie_break < right->tie_break) {
        return -1;
    }
    if (left->tie_break > right->tie_break) {
        return 1;
    }
    return 0;
}

static bool proof_probe_tablebase(
    ProofContext *context,
    Position position,
    uint8_t *value
) {
    int pieces = count_bits(occupied(position));
    int side_outcome;
    if (pieces <= 3) {
        int distance;
        int result = makhos_tb3_probe(
            position.red,
            position.black,
            position.kings,
            position.turn,
            position.reversible_plies,
            &side_outcome,
            &distance
        );
        (void)distance;
        if (result != 0) {
            context->failed = true;
            context->failure_reason = "three-piece tablebase probe failed";
            return false;
        }
    } else if (pieces == 4) {
        uint8_t counts[4];
        signature_for_position(position, counts);
        int signature_index = context->tablebase->signature_index
            [counts[0]][counts[1]][counts[2]][counts[3]];
        if (signature_index < 0) {
            context->failed = true;
            context->failure_reason = "four-piece tablebase signature missing";
            return false;
        }
        RankedSignature *signature =
            &context->tablebase->signatures[signature_index];
        uint64_t rank = rank_position(position, signature);
        uint8_t packed = get_wdl(
            signature,
            rank,
            position.turn,
            position.reversible_plies
        );
        side_outcome = (int)packed - 1;
    } else {
        return false;
    }
    ++context->tablebase_hits;
    int root_outcome =
        position.turn == context->root_player ? side_outcome : -side_outcome;
    *value = root_outcome >= OUTCOME_DRAW ? PROOF_PROVEN : PROOF_DISPROVEN;
    return true;
}

static bool proof_solve(
    ProofContext *context,
    Position position,
    size_t depth,
    uint8_t *output
) {
    ProofEntry *cached = proof_find_slot(context, position, false);
    if (cached != NULL) {
        ++context->cache_hits;
        *output = cached->value;
        return true;
    }
    if (context->failed) {
        return false;
    }
    if (context->nodes >= context->node_budget) {
        context->failed = true;
        context->failure_reason = "proof node budget exhausted";
        return false;
    }
    ++context->nodes;
    if (depth > context->maximum_depth) {
        context->maximum_depth = depth;
    }
    if (position.reversible_plies >= context->tablebase->no_progress_plies) {
        *output = PROOF_PROVEN;
        return proof_store(context, position, *output);
    }

    generate_moves(position, context->generator);
    if (context->generator->count == 0) {
        uint8_t winner = other(position.turn);
        *output = winner == context->root_player
            ? PROOF_PROVEN
            : PROOF_DISPROVEN;
        return proof_store(context, position, *output);
    }
    if (count_bits(occupied(position)) <= 4) {
        if (!proof_probe_tablebase(context, position, output)) {
            return false;
        }
        return proof_store(context, position, *output);
    }

    uint32_t child_count = context->generator->count;
    ProofChild *children = malloc((size_t)child_count * sizeof(*children));
    if (children == NULL) {
        context->failed = true;
        context->failure_reason = "unable to allocate proof children";
        return false;
    }
    for (uint32_t index = 0; index < child_count; ++index) {
        children[index].position = context->generator->moves[index].next;
        children[index].score = proof_material_score(
            children[index].position, context->root_player
        );
        children[index].tie_break = hash_position(children[index].position);
        children[index].preferred =
            depth + 1 < context->preferred_line_length &&
            same_exact_key(position, context->preferred_line[depth]) &&
            same_exact_key(
                children[index].position, context->preferred_line[depth + 1]
            );
        if (position.turn != context->root_player) {
            children[index].score = -children[index].score;
        }
    }
    qsort(children, child_count, sizeof(*children), compare_proof_children);

    bool root_choice = position.turn == context->root_player;
    uint8_t result = root_choice ? PROOF_DISPROVEN : PROOF_PROVEN;
    for (uint32_t index = 0; index < child_count; ++index) {
        uint8_t child_value;
        if (!proof_solve(context, children[index].position, depth + 1, &child_value)) {
            free(children);
            return false;
        }
        if (root_choice && child_value == PROOF_PROVEN) {
            result = PROOF_PROVEN;
            break;
        }
        if (!root_choice && child_value == PROOF_DISPROVEN) {
            result = PROOF_DISPROVEN;
            break;
        }
    }
    free(children);
    *output = result;
    return proof_store(context, position, result);
}

static bool parse_uint64_value(const char *text, uint64_t *value) {
    if (text == NULL || *text == '\0' || *text == '-') {
        return false;
    }
    char *end = NULL;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0') {
        return false;
    }
#if ULLONG_MAX > UINT64_MAX
    if (parsed > (unsigned long long)UINT64_MAX) {
        return false;
    }
#endif
    *value = (uint64_t)parsed;
    return true;
}

static void print_proof_move(const Move *move) {
    char separator = move->capture_count > 0 ? 'x' : '-';
    for (uint8_t index = 0; index < move->path_len; ++index) {
        if (index > 0) {
            putchar(separator);
        }
        printf("%u", (unsigned)move->path[index] + 1);
    }
}

static bool proof_move_format(const Move *move, char *buffer, size_t buffer_size) {
    size_t used = 0;
    char separator = move->capture_count > 0 ? 'x' : '-';
    for (uint8_t index = 0; index < move->path_len; ++index) {
        int written;
        if (index == 0) {
            written = snprintf(
                buffer + used,
                buffer_size - used,
                "%u",
                (unsigned)move->path[index] + 1
            );
        } else {
            written = snprintf(
                buffer + used,
                buffer_size - used,
                "%c%u",
                separator,
                (unsigned)move->path[index] + 1
            );
        }
        if (written < 0 || (size_t)written >= buffer_size - used) {
            return false;
        }
        used += (size_t)written;
    }
    return true;
}

static bool proof_move_matches(const Move *move, const char *text) {
    char buffer[128];
    if (!proof_move_format(move, buffer, sizeof(buffer))) {
        return false;
    }
    return strcmp(buffer, text) == 0;
}

static void print_root_proof_progress(ProofContext *context, Position root) {
    generate_moves(root, context->generator);
    uint32_t proven = 0;
    uint32_t disproven = 0;
    uint32_t unknown = 0;
    for (uint32_t index = 0; index < context->generator->count; ++index) {
        Move *move = &context->generator->moves[index];
        ProofEntry *entry = proof_find_slot(context, move->next, false);
        const char *status;
        if (entry == NULL) {
            status = "UNKNOWN";
            ++unknown;
        } else if (entry->value == PROOF_PROVEN) {
            status = "PROVEN_NON_LOSS";
            ++proven;
        } else {
            status = "FORCED_LOSS";
            ++disproven;
        }
        printf("root move ");
        print_proof_move(move);
        printf(": %s\n", status);
    }
    printf(
        "root moves proven/disproven/unknown: %u/%u/%u\n",
        proven, disproven, unknown
    );
}

static void proof_record_encode(const ProofEntry *entry, uint8_t record[16]) {
    memset(record, 0, 16);
    memcpy(record, &entry->position.red, 4);
    memcpy(record + 4, &entry->position.black, 4);
    memcpy(record + 8, &entry->position.kings, 4);
    record[12] = entry->position.turn;
    record[13] = entry->position.reversible_plies;
    record[14] = entry->value;
}

static bool write_proof_checkpoint(
    const ProofContext *context,
    Position root,
    const char *path
) {
    size_t temporary_length = strlen(path) + 5;
    char *temporary_path = malloc(temporary_length);
    if (temporary_path == NULL) {
        return false;
    }
    snprintf(temporary_path, temporary_length, "%s.tmp", path);
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint8_t record[16];
    uint64_t entry_count = 0;
    for (size_t index = 0; index < context->capacity; ++index) {
        if (!context->entries[index].used) {
            continue;
        }
        proof_record_encode(&context->entries[index], record);
        checksum = checksum_update(checksum, record, sizeof(record));
        ++entry_count;
    }
    FILE *file = fopen(temporary_path, "wb");
    if (file == NULL) {
        free(temporary_path);
        return false;
    }
    uint32_t version = PROOF_CHECKPOINT_VERSION;
    uint32_t root_player = context->root_player;
    uint64_t capacity = context->capacity;
    bool ok =
        fwrite(PROOF_CHECKPOINT_MAGIC, 1, 8, file) == 8 &&
        fwrite(&version, sizeof(version), 1, file) == 1 &&
        fwrite(&context->tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&root_player, sizeof(root_player), 1, file) == 1 &&
        fwrite(&capacity, sizeof(capacity), 1, file) == 1 &&
        fwrite(&entry_count, sizeof(entry_count), 1, file) == 1 &&
        fwrite(&context->tablebase->checksum, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&checksum, sizeof(checksum), 1, file) == 1 &&
        fwrite(&root.red, sizeof(root.red), 1, file) == 1 &&
        fwrite(&root.black, sizeof(root.black), 1, file) == 1 &&
        fwrite(&root.kings, sizeof(root.kings), 1, file) == 1 &&
        fwrite(&root.turn, sizeof(root.turn), 1, file) == 1 &&
        fwrite(&root.reversible_plies, sizeof(root.reversible_plies), 1, file) == 1;
    for (size_t index = 0; ok && index < context->capacity; ++index) {
        if (!context->entries[index].used) {
            continue;
        }
        proof_record_encode(&context->entries[index], record);
        ok = fwrite(record, 1, sizeof(record), file) == sizeof(record);
    }
    if (fclose(file) != 0) {
        ok = false;
    }
    if (ok) {
        ok = makhos_replace_file_atomically(temporary_path, path);
    }
    if (!ok) {
        remove(temporary_path);
    }
    free(temporary_path);
    if (ok) {
        printf("checkpoint entries: %" PRIu64 "\n", entry_count);
        printf("checkpoint checksum: %016" PRIx64 "\n", checksum);
        printf("checkpoint wrote: %s\n", path);
    }
    return ok;
}

/* 0 = absent, 1 = loaded, -1 = invalid/error. */
static int read_proof_checkpoint(
    ProofContext *context,
    Position expected_root,
    const char *path
) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    char magic[8];
    uint32_t version;
    uint32_t no_progress;
    uint32_t root_player;
    uint64_t saved_capacity;
    uint64_t entry_count = 0;
    uint64_t tablebase_checksum;
    uint64_t expected_checksum;
    Position root;
    memset(&root, 0, sizeof(root));
    bool ok =
        fread(magic, 1, 8, file) == 8 &&
        memcmp(magic, PROOF_CHECKPOINT_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, file) == 1 &&
        version == PROOF_CHECKPOINT_VERSION &&
        fread(&no_progress, sizeof(no_progress), 1, file) == 1 &&
        no_progress == context->tablebase->no_progress_plies &&
        fread(&root_player, sizeof(root_player), 1, file) == 1 &&
        root_player == context->root_player &&
        fread(&saved_capacity, sizeof(saved_capacity), 1, file) == 1 &&
        fread(&entry_count, sizeof(entry_count), 1, file) == 1 &&
        entry_count < context->capacity * 85 / 100 &&
        fread(&tablebase_checksum, sizeof(tablebase_checksum), 1, file) == 1 &&
        tablebase_checksum == context->tablebase->checksum &&
        fread(&expected_checksum, sizeof(expected_checksum), 1, file) == 1 &&
        fread(&root.red, sizeof(root.red), 1, file) == 1 &&
        fread(&root.black, sizeof(root.black), 1, file) == 1 &&
        fread(&root.kings, sizeof(root.kings), 1, file) == 1 &&
        fread(&root.turn, sizeof(root.turn), 1, file) == 1 &&
        fread(&root.reversible_plies, sizeof(root.reversible_plies), 1, file) == 1 &&
        same_exact_key(root, expected_root);
    (void)saved_capacity;
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint8_t record[16];
    for (uint64_t index = 0; ok && index < entry_count; ++index) {
        if (fread(record, 1, sizeof(record), file) != sizeof(record)) {
            ok = false;
            break;
        }
        checksum = checksum_update(checksum, record, sizeof(record));
        ProofEntry entry;
        memset(&entry, 0, sizeof(entry));
        memcpy(&entry.position.red, record, 4);
        memcpy(&entry.position.black, record + 4, 4);
        memcpy(&entry.position.kings, record + 8, 4);
        entry.position.turn = record[12];
        entry.position.reversible_plies = record[13];
        entry.value = record[14];
        if (
            (entry.position.red & entry.position.black) != 0 ||
            (entry.position.kings & ~occupied(entry.position)) != 0 ||
            (entry.position.turn != RED && entry.position.turn != BLACK) ||
            entry.position.reversible_plies > no_progress ||
            entry.value > PROOF_PROVEN ||
            !proof_store(context, entry.position, entry.value)
        ) {
            ok = false;
            break;
        }
    }
    if (ok && fgetc(file) != EOF) {
        ok = false;
    }
    fclose(file);
    if (!ok || checksum != expected_checksum || context->count != entry_count) {
        return -1;
    }
    printf("checkpoint loaded: %s\n", path);
    printf("checkpoint entries: %" PRIu64 "\n", entry_count);
    printf("checkpoint checksum: %016" PRIx64 "\n", checksum);
    return 1;
}

static int command_prove(
    const char *path,
    const char *position_text,
    const char *root_text,
    uint64_t node_budget,
    int proof_hash_power,
    int tb3_hash_power,
    const char *checkpoint_path,
    const char *preferred_line
) {
    RankedTablebase tablebase;
    if (
        !read_tablebase(&tablebase, path) ||
        tablebase.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read or verify %s\n", path);
        return 2;
    }
    Position position;
    if (!parse_position(position_text, &position)) {
        fprintf(stderr, "invalid proof position\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    uint8_t root_player;
    if (
        strcmp(root_text, "black") == 0 ||
        strcmp(root_text, "BLACK") == 0 ||
        strcmp(root_text, "b") == 0 ||
        strcmp(root_text, "B") == 0
    ) {
        root_player = BLACK;
    } else if (
        strcmp(root_text, "red") == 0 ||
        strcmp(root_text, "RED") == 0 ||
        strcmp(root_text, "r") == 0 ||
        strcmp(root_text, "R") == 0
    ) {
        root_player = RED;
    } else {
        fprintf(stderr, "root player must be black or red\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    int dependency = makhos_tb3_init(
        (int)tablebase.no_progress_plies, tb3_hash_power
    );
    if (dependency != 0) {
        fprintf(stderr, "unable to initialize three-piece dependency: %d\n", dependency);
        tablebase_destroy(&tablebase);
        return 2;
    }
    ProofContext context;
    memset(&context, 0, sizeof(context));
    context.tablebase = &tablebase;
    context.capacity = (size_t)1 << proof_hash_power;
    context.entries = calloc(context.capacity, sizeof(*context.entries));
    context.generator = calloc(1, sizeof(*context.generator));
    context.node_budget = node_budget;
    context.root_player = root_player;
    if (context.entries == NULL || context.generator == NULL) {
        fprintf(stderr, "unable to allocate proof workspace\n");
        free(context.entries);
        free(context.generator);
        makhos_tb3_shutdown();
        tablebase_destroy(&tablebase);
        return 2;
    }

    if (preferred_line != NULL) {
        size_t line_length = strlen(preferred_line);
        char *line_copy = malloc(line_length + 1);
        if (line_copy == NULL) {
            fprintf(stderr, "unable to allocate preferred line\n");
            free(context.entries);
            free(context.generator);
            makhos_tb3_shutdown();
            tablebase_destroy(&tablebase);
            return 2;
        }
        memcpy(line_copy, preferred_line, line_length + 1);
        Position cursor_position = position;
        context.preferred_line[0] = position;
        context.preferred_line_length = 1;
        char *cursor = line_copy;
        bool valid_line = true;
        while (*cursor != '\0') {
            if (context.preferred_line_length >= PROOF_PREFERRED_LINE_MAX) {
                valid_line = false;
                break;
            }
            char *separator = strchr(cursor, ',');
            if (separator != NULL) {
                *separator = '\0';
            }
            generate_moves(cursor_position, context.generator);
            bool matched = false;
            for (uint32_t index = 0; index < context.generator->count; ++index) {
                Move *move = &context.generator->moves[index];
                if (proof_move_matches(move, cursor)) {
                    cursor_position = move->next;
                    context.preferred_line[context.preferred_line_length++] =
                        cursor_position;
                    matched = true;
                    break;
                }
            }
            if (!matched) {
                valid_line = false;
                break;
            }
            if (separator == NULL) {
                break;
            }
            cursor = separator + 1;
        }
        free(line_copy);
        if (!valid_line) {
            fprintf(stderr, "preferred line contains an illegal move\n");
            free(context.entries);
            free(context.generator);
            makhos_tb3_shutdown();
            tablebase_destroy(&tablebase);
            return 1;
        }
        printf(
            "preferred line (%zu plies): %s\n",
            context.preferred_line_length - 1,
            preferred_line
        );
    }

    if (checkpoint_path != NULL) {
        int loaded = read_proof_checkpoint(&context, position, checkpoint_path);
        if (loaded < 0) {
            fprintf(stderr, "invalid or incompatible proof checkpoint\n");
            free(context.entries);
            free(context.generator);
            makhos_tb3_shutdown();
            tablebase_destroy(&tablebase);
            return 2;
        }
    }

    uint8_t value;
    clock_t started = clock();
    bool completed = proof_solve(&context, position, 0, &value);
    double elapsed = (double)(clock() - started) / CLOCKS_PER_SEC;
    printf("nodes: %" PRIu64 "\n", context.nodes);
    printf("stored states: %zu\n", context.count);
    printf("cache hits: %" PRIu64 "\n", context.cache_hits);
    printf("tablebase hits: %" PRIu64 "\n", context.tablebase_hits);
    printf("maximum depth: %zu\n", context.maximum_depth);
    printf("time: %.3f seconds\n", elapsed);
    print_root_proof_progress(&context, position);
    int return_code;
    if (!completed) {
        printf("result: UNKNOWN\n");
        printf(
            "reason: %s\n",
            context.failure_reason != NULL
                ? context.failure_reason
                : "proof search failed"
        );
        return_code = 3;
    } else if (value == PROOF_PROVEN) {
        printf("result: PROVEN NON-LOSS\n");
        return_code = 0;
    } else {
        printf("result: FORCED LOSS\n");
        return_code = 1;
    }
    if (
        checkpoint_path != NULL &&
        !write_proof_checkpoint(&context, position, checkpoint_path)
    ) {
        fprintf(stderr, "failed to write proof checkpoint\n");
        return_code = 2;
    }
    free(context.entries);
    free(context.generator);
    makhos_tb3_shutdown();
    tablebase_destroy(&tablebase);
    return return_code;
}

static bool parse_player_text(const char *text, uint8_t *player) {
    if (
        strcmp(text, "black") == 0 ||
        strcmp(text, "BLACK") == 0 ||
        strcmp(text, "b") == 0 ||
        strcmp(text, "B") == 0
    ) {
        *player = BLACK;
        return true;
    }
    if (
        strcmp(text, "red") == 0 ||
        strcmp(text, "RED") == 0 ||
        strcmp(text, "r") == 0 ||
        strcmp(text, "R") == 0
    ) {
        *player = RED;
        return true;
    }
    return false;
}

static int command_survey(
    const char *path,
    const char *position_text,
    const char *root_text,
    const char *root_move_text,
    uint64_t node_budget,
    int proof_hash_power,
    int tb3_hash_power,
    const char *checkpoint_prefix
) {
    RankedTablebase tablebase;
    if (!read_tablebase(&tablebase, path)) {
        fprintf(stderr, "unable to read or verify %s\n", path);
        return 2;
    }
    Position position;
    uint8_t root_player;
    if (
        !parse_position(position_text, &position) ||
        !parse_player_text(root_text, &root_player) ||
        position.turn != root_player
    ) {
        fprintf(stderr, "invalid survey root position or player\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    int dependency = makhos_tb3_init(
        (int)tablebase.no_progress_plies, tb3_hash_power
    );
    if (dependency != 0) {
        fprintf(stderr, "unable to initialize three-piece dependency: %d\n", dependency);
        tablebase_destroy(&tablebase);
        return 2;
    }
    MoveList *moves = calloc(1, sizeof(*moves));
    if (moves == NULL) {
        makhos_tb3_shutdown();
        tablebase_destroy(&tablebase);
        return 2;
    }
    generate_moves(position, moves);
    Position after_root;
    bool found = false;
    for (uint32_t index = 0; index < moves->count; ++index) {
        if (proof_move_matches(&moves->moves[index], root_move_text)) {
            after_root = moves->moves[index].next;
            found = true;
            break;
        }
    }
    if (!found) {
        fprintf(stderr, "survey root move is not legal\n");
        free(moves);
        makhos_tb3_shutdown();
        tablebase_destroy(&tablebase);
        return 1;
    }
    generate_moves(after_root, moves);
    uint32_t reply_count = moves->count;
    Move *replies = malloc((size_t)reply_count * sizeof(*replies));
    if (reply_count > 0 && replies == NULL) {
        free(moves);
        makhos_tb3_shutdown();
        tablebase_destroy(&tablebase);
        return 2;
    }
    if (reply_count > 0) {
        memcpy(replies, moves->moves, (size_t)reply_count * sizeof(*replies));
    }
    free(moves);

    uint32_t proven = 0;
    uint32_t disproven = 0;
    uint32_t unknown = 0;
    printf("survey root move: %s\n", root_move_text);
    printf("opponent replies: %u\n", reply_count);
    for (uint32_t reply_index = 0; reply_index < reply_count; ++reply_index) {
        ProofContext context;
        memset(&context, 0, sizeof(context));
        context.tablebase = &tablebase;
        context.capacity = (size_t)1 << proof_hash_power;
        context.entries = calloc(context.capacity, sizeof(*context.entries));
        context.generator = calloc(1, sizeof(*context.generator));
        context.node_budget = node_budget;
        context.root_player = root_player;
        if (context.entries == NULL || context.generator == NULL) {
            free(context.entries);
            free(context.generator);
            free(replies);
            makhos_tb3_shutdown();
            tablebase_destroy(&tablebase);
            return 2;
        }
        char *checkpoint_path = NULL;
        if (checkpoint_prefix != NULL) {
            char notation[128];
            if (!proof_move_format(&replies[reply_index], notation, sizeof(notation))) {
                free(context.entries);
                free(context.generator);
                free(replies);
                makhos_tb3_shutdown();
                tablebase_destroy(&tablebase);
                return 2;
            }
            size_t checkpoint_length =
                strlen(checkpoint_prefix) + strlen(notation) + 5;
            checkpoint_path = malloc(checkpoint_length);
            if (checkpoint_path == NULL) {
                free(context.entries);
                free(context.generator);
                free(replies);
                makhos_tb3_shutdown();
                tablebase_destroy(&tablebase);
                return 2;
            }
            snprintf(
                checkpoint_path,
                checkpoint_length,
                "%s_%s.tt",
                checkpoint_prefix,
                notation
            );
            int loaded = read_proof_checkpoint(
                &context, replies[reply_index].next, checkpoint_path
            );
            if (loaded < 0) {
                fprintf(stderr, "invalid survey reply checkpoint\n");
                free(checkpoint_path);
                free(context.entries);
                free(context.generator);
                free(replies);
                makhos_tb3_shutdown();
                tablebase_destroy(&tablebase);
                return 2;
            }
        }
        uint8_t value;
        clock_t started = clock();
        bool completed = proof_solve(
            &context, replies[reply_index].next, 0, &value
        );
        double elapsed = (double)(clock() - started) / CLOCKS_PER_SEC;
        printf("reply ");
        print_proof_move(&replies[reply_index]);
        if (!completed) {
            printf(": UNKNOWN");
            ++unknown;
        } else if (value == PROOF_PROVEN) {
            printf(": PROVEN_NON_LOSS");
            ++proven;
        } else {
            printf(": FORCED_LOSS");
            ++disproven;
        }
        printf(
            " nodes=%" PRIu64 " cache=%" PRIu64 " tb=%" PRIu64
            " depth=%zu time=%.3f\n",
            context.nodes,
            context.cache_hits,
            context.tablebase_hits,
            context.maximum_depth,
            elapsed
        );
        if (
            checkpoint_path != NULL &&
            !write_proof_checkpoint(
                &context, replies[reply_index].next, checkpoint_path
            )
        ) {
            fprintf(stderr, "failed to write survey reply checkpoint\n");
            free(checkpoint_path);
            free(context.entries);
            free(context.generator);
            free(replies);
            makhos_tb3_shutdown();
            tablebase_destroy(&tablebase);
            return 2;
        }
        free(checkpoint_path);
        free(context.entries);
        free(context.generator);
    }
    free(replies);
    printf(
        "reply proofs proven/disproven/unknown: %u/%u/%u\n",
        proven, disproven, unknown
    );
    int result;
    if (disproven > 0) {
        printf("root move result: FORCED LOSS\n");
        result = 1;
    } else if (unknown == 0) {
        printf("root move result: PROVEN NON-LOSS\n");
        result = 0;
    } else {
        printf("root move result: UNKNOWN\n");
        result = 3;
    }
    makhos_tb3_shutdown();
    tablebase_destroy(&tablebase);
    return result;
}

#define DFPN_INFINITY UINT32_C(1000000000)
#define DFPN_META_TURN_STRIDE UINT8_C(127)

/*
 * The board starts with at most sixteen pieces.  Store king status in the
 * order of the occupied squares instead of keeping a third 32-bit bitboard.
 * This is a bijection for every position reachable from the initial setup.
 *
 * Proof and disproof numbers are search-ordering quantities: only zero and
 * DFPN_INFINITY have game-theoretic meaning.  The 16-bit representation is
 * exact through 32767 and then uses an integer block-float with at least ten
 * mantissa bits.  Finite values never encode as infinity, so compression can
 * change scheduling but cannot manufacture a proof or disproof.
 */
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
__attribute__((target("bmi2")))
static uint16_t dfpn_compress_kings_bmi2(Position position) {
    return (uint16_t)_pext_u32(position.kings, occupied(position));
}

__attribute__((target("bmi2")))
static uint32_t dfpn_expand_kings_bmi2(
    uint32_t red,
    uint32_t black,
    uint16_t packed
) {
    return _pdep_u32((uint32_t)packed, red | black);
}

static bool dfpn_cpu_has_bmi2(void) {
    static int supported = -1;
    if (supported < 0) {
        int registers[4];
        __cpuidex(registers, 7, 0);
        supported = (registers[1] & (1 << 8)) != 0;
    }
    return supported != 0;
}
#endif

static uint16_t dfpn_compress_kings(Position position) {
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if (dfpn_cpu_has_bmi2()) {
        return dfpn_compress_kings_bmi2(position);
    }
#endif
    uint32_t remaining = occupied(position);
    uint16_t packed = 0;
    unsigned index = 0;
    while (remaining != 0) {
        uint32_t bit = remaining & (UINT32_C(0) - remaining);
        if ((position.kings & bit) != 0) {
            packed |= (uint16_t)(UINT16_C(1) << index);
        }
        remaining &= remaining - 1;
        ++index;
    }
    return packed;
}

static uint32_t dfpn_expand_kings(
    uint32_t red,
    uint32_t black,
    uint16_t packed
) {
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if (dfpn_cpu_has_bmi2()) {
        return dfpn_expand_kings_bmi2(red, black, packed);
    }
#endif
    uint32_t remaining = red | black;
    uint32_t kings = 0;
    unsigned index = 0;
    while (remaining != 0) {
        uint32_t bit = remaining & (UINT32_C(0) - remaining);
        if ((packed & (uint16_t)(UINT16_C(1) << index)) != 0) {
            kings |= bit;
        }
        remaining &= remaining - 1;
        ++index;
    }
    return kings;
}

#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
__attribute__((target("bmi2")))
static uint16_t dfpn_compress_black_bmi2(Position position) {
    return (uint16_t)_pext_u32(position.black, occupied(position));
}

__attribute__((target("bmi2")))
static uint32_t dfpn_expand_black_bmi2(
    uint32_t occupancy,
    uint16_t packed
) {
    return _pdep_u32((uint32_t)packed, occupancy);
}
#endif

/* Store colour in occupied-square order, just like king status.  Reachable
   positions contain at most sixteen pieces, so this is an exact bijection and
   saves two bytes in every live and solved in-memory DFPN entry. */
static uint16_t dfpn_compress_black(Position position) {
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if (dfpn_cpu_has_bmi2()) {
        return dfpn_compress_black_bmi2(position);
    }
#endif
    uint32_t remaining = occupied(position);
    uint16_t packed = 0;
    unsigned index = 0;
    while (remaining != 0) {
        uint32_t bit = remaining & (UINT32_C(0) - remaining);
        if ((position.black & bit) != 0) {
            packed |= (uint16_t)(UINT16_C(1) << index);
        }
        remaining &= remaining - 1;
        ++index;
    }
    return packed;
}

static void dfpn_expand_colours(
    uint32_t occupancy,
    uint16_t black_flags,
    uint32_t *red,
    uint32_t *black
) {
#if defined(__x86_64__) && (defined(__clang__) || defined(__GNUC__))
    if (dfpn_cpu_has_bmi2()) {
        *black = dfpn_expand_black_bmi2(occupancy, black_flags);
        *red = occupancy & ~*black;
        return;
    }
#endif
    uint32_t remaining = occupancy;
    uint32_t expanded_black = 0;
    unsigned index = 0;
    while (remaining != 0) {
        uint32_t bit = remaining & (UINT32_C(0) - remaining);
        if ((black_flags & (uint16_t)(UINT16_C(1) << index)) != 0) {
            expanded_black |= bit;
        }
        remaining &= remaining - 1;
        ++index;
    }
    *black = expanded_black;
    *red = occupancy & ~expanded_black;
}

static uint8_t dfpn_position_meta(Position position) {
    return (uint8_t)(
        1 + position.reversible_plies +
        (position.turn == BLACK ? DFPN_META_TURN_STRIDE : 0)
    );
}

static uint8_t dfpn_meta_turn(uint8_t meta) {
    return (meta - 1) >= DFPN_META_TURN_STRIDE ? BLACK : RED;
}

static uint8_t dfpn_meta_clock(uint8_t meta) {
    return (uint8_t)((meta - 1) % DFPN_META_TURN_STRIDE);
}

static uint16_t dfpn_number_encode(uint32_t value) {
    if (value >= DFPN_INFINITY) {
        return UINT16_MAX;
    }
    if (value <= UINT32_C(32767)) {
        return (uint16_t)value;
    }
    unsigned shift = 0;
    while ((value >> shift) > UINT32_C(2047)) {
        ++shift;
    }
    uint32_t mantissa = value >> shift;
    return (uint16_t)(
        UINT16_C(0x8000) |
        ((uint16_t)shift << 10) |
        (uint16_t)(mantissa - UINT32_C(1024))
    );
}

static uint32_t dfpn_number_decode(uint16_t code) {
    if (code == UINT16_MAX) {
        return DFPN_INFINITY;
    }
    if ((code & UINT16_C(0x8000)) == 0) {
        return code;
    }
    unsigned shift = (unsigned)((code >> 10) & UINT16_C(31));
    uint32_t mantissa = UINT32_C(1024) + (code & UINT16_C(1023));
    return mantissa << shift;
}

#define DFPN_UNEXPANDED_PROOF_CODE UINT16_C(0x8000)

#pragma pack(push, 1)

typedef struct {
    uint32_t occupied;
    uint16_t black_flags;
    uint16_t king_flags;
    uint16_t proof_code;
    uint16_t disproof_code;
    uint8_t meta;
} DfpnEntry;

_Static_assert(
    sizeof(DfpnEntry) == 13,
    "DFPN live entry layout changed"
);

/* Exact terminal entries need only a full key and one Boolean result. */
typedef struct {
    uint32_t occupied;
    uint16_t black_flags;
    uint16_t king_flags;
    uint8_t meta;
    uint8_t proven;
} DfpnSolvedEntry;

#pragma pack(pop)

_Static_assert(
    sizeof(DfpnSolvedEntry) == 10,
    "DFPN solved entry must remain compact"
);

typedef struct {
    Position position;
    uint32_t proof_number;
    uint32_t disproof_number;
} DfpnChild;

typedef struct {
    RankedTablebase *tablebase;
    CompactTablebase *frontiers[2];
    size_t frontier_count;
    DfpnEntry *entries;
    size_t capacity;
    size_t count;
    DfpnSolvedEntry *solved_entries;
    size_t solved_capacity;
    size_t solved_count;
    MoveList *generator;
    uint64_t expansion_budget;
    uint64_t expansions;
    uint64_t next_progress_expansion;
    uint64_t cache_hits;
    uint64_t tablebase_hits;
    uint64_t six_piece_expansions[7][7][7][7];
    uint64_t frontier_hits_by_signature[7][7][7][7];
    size_t maximum_depth;
    clock_t search_started;
    uint8_t root_player;
    bool failed;
    const char *failure_reason;
} DfpnContext;

#define DFPN_MIN_HASH_SLOTS ((size_t)1 << 16)

/* Avoid capacity * 85 overflowing for explicit, non-power-of-two tables. */
static size_t dfpn_hash_load_limit(size_t capacity) {
    return
        (capacity / 100) * 85 +
        ((capacity % 100) * 85) / 100;
}

static bool dfpn_hash_below_load_guard(size_t count, size_t capacity) {
    return count < dfpn_hash_load_limit(capacity);
}

static bool dfpn_hash_can_insert(size_t count, size_t capacity) {
    size_t limit = dfpn_hash_load_limit(capacity);
    return limit > 0 && count < limit - 1;
}

static bool parse_dfpn_live_slots(const char *text, size_t *capacity) {
    uint64_t parsed;
    if (
        !parse_uint64_value(text, &parsed) ||
        parsed < (uint64_t)DFPN_MIN_HASH_SLOTS ||
        (uintmax_t)parsed > (uintmax_t)(SIZE_MAX / sizeof(DfpnEntry))
    ) {
        return false;
    }
    *capacity = (size_t)parsed;
    return true;
}

static bool parse_dfpn_solved_slots(const char *text, size_t *capacity) {
    uint64_t parsed;
    if (
        !parse_uint64_value(text, &parsed) ||
        parsed < (uint64_t)DFPN_MIN_HASH_SLOTS ||
        (uintmax_t)parsed >
            (uintmax_t)(SIZE_MAX / sizeof(DfpnSolvedEntry))
    ) {
        return false;
    }
    *capacity = (size_t)parsed;
    return true;
}

static bool parse_dfpn_hash_capacities(
    const char *live_text,
    const char *solved_text,
    bool explicit_live_slots,
    bool explicit_solved_slots,
    size_t *live_capacity,
    size_t *solved_capacity
) {
    int live_power = 0;
    int solved_power = 0;
    if (
        (explicit_live_slots
            ? !parse_dfpn_live_slots(live_text, live_capacity)
            : !parse_bounded_int(live_text, 16, 29, &live_power)) ||
        (explicit_solved_slots
            ? !parse_dfpn_solved_slots(solved_text, solved_capacity)
            : !parse_bounded_int(solved_text, 16, 28, &solved_power))
    ) {
        return false;
    }
    if (!explicit_live_slots) {
        *live_capacity = (size_t)1 << live_power;
    }
    if (!explicit_solved_slots) {
        *solved_capacity = (size_t)1 << solved_power;
    }
    return true;
}

static size_t dfpn_bitset_bytes(size_t capacity) {
    return capacity / 8 + (capacity % 8 != 0 ? 1 : 0);
}

static bool dfpn_hash_is_power_of_two(size_t capacity) {
    return capacity != 0 && (capacity & (capacity - 1)) == 0;
}

static size_t dfpn_hash_initial_slot(Position position, size_t capacity) {
    uint64_t hash = hash_position(position);
    if (dfpn_hash_is_power_of_two(capacity)) {
        return (size_t)(hash & (capacity - 1));
    }
    return (size_t)(hash % (uint64_t)capacity);
}

static size_t dfpn_hash_next_slot(
    size_t slot,
    size_t capacity,
    bool power_of_two
) {
    if (power_of_two) {
        return (slot + 1) & (capacity - 1);
    }
    ++slot;
    return slot == capacity ? 0 : slot;
}

typedef struct {
    uint8_t counts[4];
    uint64_t value;
} DfpnMaterialCount;

static int compare_dfpn_material_count(
    const void *left_pointer,
    const void *right_pointer
) {
    const DfpnMaterialCount *left = left_pointer;
    const DfpnMaterialCount *right = right_pointer;
    if (left->value < right->value) return 1;
    if (left->value > right->value) return -1;
    return memcmp(left->counts, right->counts, 4);
}

static void dfpn_print_material_profile(
    const char *label,
    uint64_t counts[7][7][7][7]
) {
    DfpnMaterialCount materials[2401];
    size_t material_count = 0;
    for (int bm = 0; bm <= 6; ++bm) {
        for (int bk = 0; bk <= 6; ++bk) {
            for (int rm = 0; rm <= 6; ++rm) {
                for (int rk = 0; rk <= 6; ++rk) {
                    uint64_t value = counts[bm][bk][rm][rk];
                    if (value == 0) continue;
                    DfpnMaterialCount *material =
                        &materials[material_count++];
                    material->counts[0] = (uint8_t)bm;
                    material->counts[1] = (uint8_t)bk;
                    material->counts[2] = (uint8_t)rm;
                    material->counts[3] = (uint8_t)rk;
                    material->value = value;
                }
            }
        }
    }
    qsort(
        materials,
        material_count,
        sizeof(materials[0]),
        compare_dfpn_material_count
    );
    size_t shown = material_count < 10 ? material_count : 10;
    for (size_t index = 0; index < shown; ++index) {
        DfpnMaterialCount *material = &materials[index];
        printf(
            "%s [%u,%u,%u,%u]: %" PRIu64 "\n",
            label,
            material->counts[0], material->counts[1],
            material->counts[2], material->counts[3],
            material->value
        );
    }
}

static uint64_t dfpn_tablebase_binding(const DfpnContext *context) {
    uint64_t binding = context->tablebase->checksum;
    for (size_t index = 0; index < context->frontier_count; ++index) {
        const CompactTablebase *frontier = context->frontiers[index];
        binding = checksum_update(
            binding,
            (const uint8_t *)&frontier->piece_count,
            sizeof(frontier->piece_count)
        );
        binding = checksum_update(
            binding,
            (const uint8_t *)&frontier->checksum,
            sizeof(frontier->checksum)
        );
    }
    return binding;
}

static uint32_t dfpn_saturating_add(uint32_t left, uint32_t right) {
    if (left >= DFPN_INFINITY || right >= DFPN_INFINITY - left) {
        return DFPN_INFINITY;
    }
    return left + right;
}

static bool same_solved_key(
    const DfpnSolvedEntry *entry,
    Position position
) {
    return
        entry->occupied == occupied(position) &&
        entry->black_flags == dfpn_compress_black(position) &&
        entry->king_flags == dfpn_compress_kings(position) &&
        entry->meta == dfpn_position_meta(position);
}

static bool same_dfpn_entry_key(
    const DfpnEntry *entry,
    Position position
) {
    return
        entry->occupied == occupied(position) &&
        entry->black_flags == dfpn_compress_black(position) &&
        entry->king_flags == dfpn_compress_kings(position) &&
        entry->meta == dfpn_position_meta(position);
}

static void dfpn_entry_set_position(
    DfpnEntry *entry,
    Position position
) {
    entry->occupied = occupied(position);
    entry->black_flags = dfpn_compress_black(position);
    entry->king_flags = dfpn_compress_kings(position);
    entry->meta = dfpn_position_meta(position);
}

static uint32_t dfpn_entry_proof(const DfpnEntry *entry) {
    if (entry->proof_code == DFPN_UNEXPANDED_PROOF_CODE) {
        return 1;
    }
    return dfpn_number_decode(entry->proof_code);
}

static uint32_t dfpn_entry_disproof(const DfpnEntry *entry) {
    return dfpn_number_decode(entry->disproof_code);
}

static bool dfpn_entry_is_expanded(const DfpnEntry *entry) {
    return entry->proof_code != DFPN_UNEXPANDED_PROOF_CODE;
}

static void dfpn_entry_mark_unexpanded(DfpnEntry *entry) {
    entry->proof_code = DFPN_UNEXPANDED_PROOF_CODE;
    entry->disproof_code = dfpn_number_encode(1);
}

static void dfpn_entry_set_numbers(
    DfpnEntry *entry,
    uint32_t proof_number,
    uint32_t disproof_number
) {
    entry->proof_code = dfpn_number_encode(proof_number);
    entry->disproof_code = dfpn_number_encode(disproof_number);
}

static DfpnSolvedEntry *dfpn_find_solved(
    DfpnContext *context,
    Position position,
    bool create,
    bool proven
) {
    if (
        count_bits(occupied(position)) > 16 ||
        position.reversible_plies >= DFPN_META_TURN_STRIDE
    ) {
        context->failed = true;
        context->failure_reason = "DFPN position exceeds compact-key bounds";
        return NULL;
    }
    if (context->solved_capacity == 0) {
        context->failed = true;
        context->failure_reason =
            "DFPN solved transposition table has zero slots";
        return NULL;
    }
    bool power_of_two = dfpn_hash_is_power_of_two(
        context->solved_capacity
    );
    size_t slot = dfpn_hash_initial_slot(
        position, context->solved_capacity
    );
    for (size_t probe = 0; probe < context->solved_capacity; ++probe) {
        DfpnSolvedEntry *entry = &context->solved_entries[slot];
        if (entry->meta == 0) {
            if (!create) {
                return NULL;
            }
            if (!dfpn_hash_can_insert(
                    context->solved_count,
                    context->solved_capacity
                )) {
                context->failed = true;
                context->failure_reason =
                    "DFPN solved transposition table reached 85% load guard";
                return NULL;
            }
            entry->occupied = occupied(position);
            entry->black_flags = dfpn_compress_black(position);
            entry->king_flags = dfpn_compress_kings(position);
            entry->meta = dfpn_position_meta(position);
            entry->proven = proven ? 1 : 0;
            ++context->solved_count;
            return entry;
        }
        if (same_solved_key(entry, position)) {
            ++context->cache_hits;
            if (create && entry->proven != (uint8_t)(proven ? 1 : 0)) {
                context->failed = true;
                context->failure_reason = "conflicting solved DFPN result";
                return NULL;
            }
            return entry;
        }
        slot = dfpn_hash_next_slot(
            slot, context->solved_capacity, power_of_two
        );
    }
    context->failed = true;
    context->failure_reason = "DFPN solved transposition table is full";
    return NULL;
}

static DfpnEntry *dfpn_find_entry(
    DfpnContext *context,
    Position position,
    bool create
) {
    if (
        count_bits(occupied(position)) > 16 ||
        position.reversible_plies >= DFPN_META_TURN_STRIDE
    ) {
        context->failed = true;
        context->failure_reason = "DFPN position exceeds compact-key bounds";
        return NULL;
    }
    if (context->capacity == 0) {
        context->failed = true;
        context->failure_reason = "DFPN live transposition table has zero slots";
        return NULL;
    }
    bool power_of_two = dfpn_hash_is_power_of_two(context->capacity);
    size_t slot = dfpn_hash_initial_slot(position, context->capacity);
    for (size_t probe = 0; probe < context->capacity; ++probe) {
        DfpnEntry *entry = &context->entries[slot];
        if (entry->meta == 0) {
            if (!create) {
                return NULL;
            }
            if (!dfpn_hash_can_insert(context->count, context->capacity)) {
                context->failed = true;
                context->failure_reason =
                    "DFPN live transposition table reached 85% load guard";
                return NULL;
            }
            dfpn_entry_set_position(entry, position);
            dfpn_entry_mark_unexpanded(entry);
            ++context->count;
            return entry;
        }
        if (same_dfpn_entry_key(entry, position)) {
            ++context->cache_hits;
            return entry;
        }
        slot = dfpn_hash_next_slot(
            slot, context->capacity, power_of_two
        );
    }
    context->failed = true;
    context->failure_reason = "DFPN transposition table is full";
    return NULL;
}

static bool dfpn_lookup_numbers(
    DfpnContext *context,
    Position position,
    bool create,
    uint32_t *proof_number,
    uint32_t *disproof_number
) {
    DfpnEntry *entry = dfpn_find_entry(context, position, false);
    if (entry != NULL) {
        *proof_number = dfpn_entry_proof(entry);
        *disproof_number = dfpn_entry_disproof(entry);
        return true;
    }
    DfpnSolvedEntry *solved = dfpn_find_solved(
        context, position, false, false
    );
    if (solved != NULL) {
        *proof_number = solved->proven ? 0 : DFPN_INFINITY;
        *disproof_number = solved->proven ? DFPN_INFINITY : 0;
        return true;
    }
    entry = dfpn_find_entry(context, position, create);
    if (entry == NULL) {
        return false;
    }
    *proof_number = dfpn_entry_proof(entry);
    *disproof_number = dfpn_entry_disproof(entry);
    return true;
}

static bool dfpn_set_terminal(
    DfpnEntry *entry,
    bool proven
) {
    dfpn_entry_set_numbers(
        entry,
        proven ? 0 : DFPN_INFINITY,
        proven ? DFPN_INFINITY : 0
    );
    return true;
}

static bool dfpn_probe_tablebase_outcome(
    DfpnContext *context,
    Position position,
    int *side_outcome_output
) {
    int pieces = count_bits(occupied(position));
    int side_outcome;
    CompactTablebase *compact_frontier = NULL;
    for (size_t index = 0; index < context->frontier_count; ++index) {
        if (pieces == (int)context->frontiers[index]->piece_count) {
            compact_frontier = context->frontiers[index];
            break;
        }
    }
    if (pieces <= 3) {
        int distance;
        int result = makhos_tb3_probe(
            position.red,
            position.black,
            position.kings,
            position.turn,
            position.reversible_plies,
            &side_outcome,
            &distance
        );
        (void)distance;
        if (result != 0) {
            context->failed = true;
            context->failure_reason = "DFPN three-piece tablebase probe failed";
            return false;
        }
    } else if (pieces == 4) {
        uint8_t counts[4];
        signature_for_position(position, counts);
        int signature_index = context->tablebase->signature_index
            [counts[0]][counts[1]][counts[2]][counts[3]];
        if (signature_index < 0) {
            context->failed = true;
            context->failure_reason = "DFPN four-piece signature missing";
            return false;
        }
        RankedSignature *signature =
            &context->tablebase->signatures[signature_index];
        uint64_t rank = rank_position(position, signature);
        uint8_t packed = get_wdl(
            signature,
            rank,
            position.turn,
            position.reversible_plies
        );
        if (packed > 2) {
            context->failed = true;
            context->failure_reason = "DFPN invalid four-piece WDL value";
            return false;
        }
        side_outcome = (int)packed - 1;
    } else if (compact_frontier != NULL) {
        uint8_t counts[4];
        signature_for_position(position, counts);
        int signature_index = compact_frontier->signature_index
            [counts[0]][counts[1]][counts[2]][counts[3]];
        if (signature_index < 0) {
            context->failed = true;
            context->failure_reason = "DFPN compact frontier signature missing";
            return false;
        }
        CompactSignature *signature =
            &compact_frontier->signatures[signature_index];
        RankedSignature ranked;
        memset(&ranked, 0, sizeof(ranked));
        memcpy(ranked.count, signature->count, 4);
        ranked.boards = signature->boards;
        uint64_t rank = rank_position(position, &ranked);
        uint8_t packed = get_compact_wdl(
            signature,
            rank,
            position.turn,
            position.reversible_plies
        );
        side_outcome = (int)packed - 1;
    } else {
        return false;
    }
    ++context->tablebase_hits;
    if (pieces >= 5 && pieces <= 6) {
        uint8_t counts[4];
        signature_for_position(position, counts);
        ++context->frontier_hits_by_signature
            [counts[0]][counts[1]][counts[2]][counts[3]];
    }
    *side_outcome_output = side_outcome;
    return true;
}

static bool dfpn_probe_tablebase(
    DfpnContext *context,
    Position position,
    bool *proven
) {
    int side_outcome;
    if (!dfpn_probe_tablebase_outcome(context, position, &side_outcome)) {
        return false;
    }
    int root_outcome =
        position.turn == context->root_player ? side_outcome : -side_outcome;
    *proven = root_outcome >= OUTCOME_DRAW;
    return true;
}

static bool dfpn_build_children(
    DfpnContext *context,
    Position position,
    DfpnChild **output,
    uint32_t *output_count
) {
    generate_moves(position, context->generator);
    uint32_t count = context->generator->count;
    DfpnChild *children = NULL;
    if (count > 0) {
        children = malloc((size_t)count * sizeof(*children));
        if (children == NULL) {
            context->failed = true;
            context->failure_reason = "unable to allocate DFPN children";
            return false;
        }
    }
    for (uint32_t index = 0; index < count; ++index) {
        Position child = context->generator->moves[index].next;
        uint32_t proof_number;
        uint32_t disproof_number;
        if (!dfpn_lookup_numbers(
                context,
                child,
                false,
                &proof_number,
                &disproof_number
            )) {
            if (context->failed) {
                free(children);
                return false;
            }
            /*
             * An unseen child is the canonical unexpanded DFPN frontier
             * value.  Do not occupy a hash slot until the search actually
             * selects and expands it; the value is exactly reconstructible
             * whenever a parent regenerates its legal moves.
             */
            proof_number = 1;
            disproof_number = 1;
        }
        children[index].position = child;
        children[index].proof_number = proof_number;
        children[index].disproof_number = disproof_number;
    }
    *output = children;
    *output_count = count;
    return true;
}

static void dfpn_update_numbers(
    DfpnEntry *entry,
    const DfpnChild *children,
    uint32_t count,
    bool or_node
) {
    if (or_node) {
        uint32_t proof = DFPN_INFINITY;
        uint32_t disproof = 0;
        for (uint32_t index = 0; index < count; ++index) {
            if (children[index].proof_number < proof) {
                proof = children[index].proof_number;
            }
            disproof = dfpn_saturating_add(
                disproof, children[index].disproof_number
            );
        }
        dfpn_entry_set_numbers(entry, proof, disproof);
    } else {
        uint32_t proof = 0;
        uint32_t disproof = DFPN_INFINITY;
        for (uint32_t index = 0; index < count; ++index) {
            proof = dfpn_saturating_add(
                proof, children[index].proof_number
            );
            if (children[index].disproof_number < disproof) {
                disproof = children[index].disproof_number;
            }
        }
        dfpn_entry_set_numbers(entry, proof, disproof);
    }
}

/*
 * DFPN_INFINITY is both the exact solved sentinel and the saturating ceiling
 * for large, still-unresolved aggregates.  A saturated live value must remain
 * searchable when its threshold is also infinite; the opposite number being
 * zero is what distinguishes an exact solved node.
 */
static bool dfpn_below_threshold(
    uint32_t value,
    uint32_t threshold,
    uint32_t opposite
) {
    return
        value < threshold ||
        (
            value >= DFPN_INFINITY &&
            threshold >= DFPN_INFINITY &&
            opposite != 0
        );
}

static uint32_t dfpn_select_child(
    const DfpnChild *children,
    uint32_t child_count,
    bool or_node,
    uint32_t *best_output,
    uint32_t *second_output
) {
    uint32_t selected = 0;
    uint32_t best = DFPN_INFINITY;
    uint32_t second = DFPN_INFINITY;
    uint32_t selected_opposite = 0;
    for (uint32_t index = 0; index < child_count; ++index) {
        uint32_t candidate = or_node
            ? children[index].proof_number
            : children[index].disproof_number;
        uint32_t opposite = or_node
            ? children[index].disproof_number
            : children[index].proof_number;
        if (candidate < best) {
            second = best;
            best = candidate;
            selected = index;
            selected_opposite = opposite;
        } else {
            if (candidate < second) {
                second = candidate;
            }
            /*
             * When every primary number is saturated, prefer an unresolved
             * child over an exact child whose opposite number is zero.  This
             * prevents repeatedly selecting an already solved child.
             */
            if (
                candidate >= DFPN_INFINITY &&
                candidate == best &&
                opposite > selected_opposite
            ) {
                selected = index;
                selected_opposite = opposite;
            }
        }
    }
    *best_output = best;
    *second_output = second;
    return selected;
}

static bool dfpn_search(
    DfpnContext *context,
    Position position,
    uint32_t proof_threshold,
    uint32_t disproof_threshold,
    size_t depth
) {
    DfpnEntry *entry = dfpn_find_entry(context, position, false);
    if (entry == NULL) {
        if (dfpn_find_solved(context, position, false, false) != NULL) {
            return true;
        }
        entry = dfpn_find_entry(context, position, true);
    }
    if (entry == NULL) {
        return false;
    }
    if (depth > context->maximum_depth) {
        context->maximum_depth = depth;
    }
    if (!dfpn_entry_is_expanded(entry)) {
        if (context->expansions >= context->expansion_budget) {
            context->failed = true;
            context->failure_reason = "DFPN expansion budget exhausted";
            return false;
        }
        ++context->expansions;
        if (
            context->next_progress_expansion != 0 &&
            context->expansions >= context->next_progress_expansion
        ) {
            double elapsed = (double)(clock() - context->search_started) /
                CLOCKS_PER_SEC;
            printf(
                "DFPN search progress: expansions=%" PRIu64
                " live=%zu resolved=%zu depth=%zu elapsed=%.3f seconds\n",
                context->expansions,
                context->count,
                context->solved_count,
                context->maximum_depth,
                elapsed
            );
            fflush(stdout);
            if (
                UINT64_MAX - context->next_progress_expansion <
                DFPN_SEARCH_PROGRESS_INTERVAL
            ) {
                context->next_progress_expansion = 0;
            } else {
                context->next_progress_expansion +=
                    DFPN_SEARCH_PROGRESS_INTERVAL;
            }
        }
        if (count_bits(occupied(position)) == 6) {
            uint8_t counts[4];
            signature_for_position(position, counts);
            ++context->six_piece_expansions
                [counts[0]][counts[1]][counts[2]][counts[3]];
        }
        if (position.reversible_plies >= context->tablebase->no_progress_plies) {
            return dfpn_set_terminal(entry, true);
        }
        int frontier_pieces = 4;
        for (size_t index = 0; index < context->frontier_count; ++index) {
            int candidate = (int)context->frontiers[index]->piece_count;
            if (candidate > frontier_pieces) frontier_pieces = candidate;
        }
        if (count_bits(occupied(position)) <= frontier_pieces) {
            generate_moves(position, context->generator);
            if (context->generator->count == 0) {
                bool proven = other(position.turn) == context->root_player;
                return dfpn_set_terminal(entry, proven);
            }
            bool proven;
            if (!dfpn_probe_tablebase(context, position, &proven)) {
                return false;
            }
            return dfpn_set_terminal(entry, proven);
        }
        DfpnChild *initial_children;
        uint32_t initial_count;
        if (!dfpn_build_children(
                context, position, &initial_children, &initial_count
            )) {
            return false;
        }
        if (initial_count == 0) {
            bool proven = other(position.turn) == context->root_player;
            free(initial_children);
            return dfpn_set_terminal(entry, proven);
        }
        dfpn_update_numbers(
            entry,
            initial_children,
            initial_count,
            position.turn == context->root_player
        );
        free(initial_children);
    }

    while (dfpn_below_threshold(
            dfpn_entry_proof(entry),
            proof_threshold,
            dfpn_entry_disproof(entry)
        ) && dfpn_below_threshold(
            dfpn_entry_disproof(entry),
            disproof_threshold,
            dfpn_entry_proof(entry)
        )) {
        DfpnChild *children;
        uint32_t child_count;
        if (!dfpn_build_children(context, position, &children, &child_count)) {
            return false;
        }
        if (child_count == 0) {
            free(children);
            context->failed = true;
            context->failure_reason = "DFPN expanded node changed legal moves";
            return false;
        }
        bool or_node = position.turn == context->root_player;
        dfpn_update_numbers(entry, children, child_count, or_node);
        if (!dfpn_below_threshold(
                dfpn_entry_proof(entry),
                proof_threshold,
                dfpn_entry_disproof(entry)
            ) || !dfpn_below_threshold(
                dfpn_entry_disproof(entry),
                disproof_threshold,
                dfpn_entry_proof(entry)
            )) {
            free(children);
            break;
        }

        uint32_t best;
        uint32_t second;
        uint32_t selected = dfpn_select_child(
            children, child_count, or_node, &best, &second
        );
#if defined(DFPN_TIEBREAK_MAX_OPPOSITE) && DFPN_TIEBREAK_MAX_OPPOSITE
        /*
         * Keep the primary best/second values above byte-for-byte identical:
         * second controls the DFPN threshold.  This optional experiment only
         * changes which exact-primary-tied child receives that threshold.
         */
        uint32_t tiebreak_opposite = or_node
            ? children[selected].disproof_number
            : children[selected].proof_number;
        for (uint32_t index = 0; index < child_count; ++index) {
            uint32_t candidate = or_node
                ? children[index].proof_number
                : children[index].disproof_number;
            uint32_t opposite = or_node
                ? children[index].disproof_number
                : children[index].proof_number;
            if (candidate == best && opposite > tiebreak_opposite) {
                selected = index;
                tiebreak_opposite = opposite;
            }
        }
#endif

        uint32_t child_proof_threshold;
        uint32_t child_disproof_threshold;
        if (or_node) {
            uint32_t alternative = second >= DFPN_INFINITY
                ? DFPN_INFINITY
                : second + 1;
            child_proof_threshold = proof_threshold < alternative
                ? proof_threshold
                : alternative;
            uint32_t sibling_disproof =
                dfpn_entry_disproof(entry) -
                children[selected].disproof_number;
            child_disproof_threshold = disproof_threshold >= DFPN_INFINITY
                ? DFPN_INFINITY
                : disproof_threshold - sibling_disproof;
        } else {
            uint32_t sibling_proof =
                dfpn_entry_proof(entry) - children[selected].proof_number;
            child_proof_threshold = proof_threshold >= DFPN_INFINITY
                ? DFPN_INFINITY
                : proof_threshold - sibling_proof;
            uint32_t alternative = second >= DFPN_INFINITY
                ? DFPN_INFINITY
                : second + 1;
            child_disproof_threshold = disproof_threshold < alternative
                ? disproof_threshold
                : alternative;
        }
        Position selected_position = children[selected].position;
        free(children);
        if (!dfpn_search(
                context,
                selected_position,
                child_proof_threshold,
                child_disproof_threshold,
                depth + 1
            )) {
            return false;
        }
        entry = dfpn_find_entry(context, position, false);
        if (entry == NULL) {
            context->failed = true;
            context->failure_reason = "DFPN parent entry disappeared";
            return false;
        }
    }
    return true;
}

static void dfpn_print_root_moves(DfpnContext *context, Position root) {
    generate_moves(root, context->generator);
    for (uint32_t index = 0; index < context->generator->count; ++index) {
        Move *move = &context->generator->moves[index];
        uint32_t proof_number;
        uint32_t disproof_number;
        bool found = dfpn_lookup_numbers(
            context,
            move->next,
            false,
            &proof_number,
            &disproof_number
        );
        printf("root move ");
        print_proof_move(move);
        if (!found) {
            printf(": pn=1 dn=1\n");
        } else {
            printf(
                ": pn=%u dn=%u%s\n",
                proof_number,
                disproof_number,
                proof_number == 0 ? " PROVEN_NON_LOSS" :
                disproof_number == 0 ? " FORCED_LOSS" : ""
            );
        }
    }
}

typedef struct {
    DfpnContext *context;
    FILE *file;
    uint8_t *live_seen;
    uint8_t *solved_seen;
    uint64_t node_count;
    bool first_node;
    bool all_choices;
    const char *failure_reason;
} DfpnCertificateWriter;

static void dfpn_certificate_node_id(
    Position position,
    char buffer[64]
) {
    snprintf(
        buffer,
        64,
        "%08" PRIx32 "-%08" PRIx32 "-%08" PRIx32 "-%u-%u",
        position.red,
        position.black,
        position.kings,
        (unsigned)position.turn,
        (unsigned)position.reversible_plies
    );
}

static void dfpn_certificate_write_position(FILE *file, Position position) {
    fputc(position.turn == BLACK ? 'B' : 'R', file);
    const uint32_t masks[4] = {
        position.black & ~position.kings,
        position.black & position.kings,
        position.red & ~position.kings,
        position.red & position.kings
    };
    const char *prefixes[4] = {"BM", "BK", "RM", "RK"};
    for (size_t type = 0; type < 4; ++type) {
        if (masks[type] == 0) continue;
        fprintf(file, ":%s", prefixes[type]);
        bool first = true;
        for (unsigned square = 0; square < 32; ++square) {
            if ((masks[type] & bit_at((int)square)) == 0) continue;
            fprintf(file, "%s%u", first ? "" : ",", square + 1);
            first = false;
        }
    }
}

static bool dfpn_certificate_mark_new(
    DfpnCertificateWriter *writer,
    Position position,
    bool *is_new
) {
    DfpnEntry *live = dfpn_find_entry(writer->context, position, false);
    if (live != NULL) {
        size_t index = (size_t)(live - writer->context->entries);
        uint8_t mask = (uint8_t)(1U << (index & 7));
        uint8_t *byte = &writer->live_seen[index >> 3];
        *is_new = (*byte & mask) == 0;
        *byte |= mask;
        return true;
    }
    DfpnSolvedEntry *solved = dfpn_find_solved(
        writer->context, position, false, false
    );
    if (solved != NULL) {
        size_t index = (size_t)(solved - writer->context->solved_entries);
        uint8_t mask = (uint8_t)(1U << (index & 7));
        uint8_t *byte = &writer->solved_seen[index >> 3];
        *is_new = (*byte & mask) == 0;
        *byte |= mask;
        return true;
    }
    writer->failure_reason = "proof node is absent from DFPN checkpoint";
    return false;
}

static bool dfpn_certificate_visit(
    DfpnCertificateWriter *writer,
    Position position
) {
    uint32_t proof_number;
    uint32_t disproof_number;
    if (
        !dfpn_lookup_numbers(
            writer->context,
            position,
            false,
            &proof_number,
            &disproof_number
        ) ||
        proof_number != 0
    ) {
        writer->failure_reason =
            "certificate traversal reached an unproven DFPN node";
        return false;
    }
    (void)disproof_number;
    bool is_new;
    if (!dfpn_certificate_mark_new(writer, position, &is_new)) {
        return false;
    }
    if (!is_new) {
        return true;
    }

    char node_id[64];
    dfpn_certificate_node_id(position, node_id);
    if (!writer->first_node) {
        fputs(",\n", writer->file);
    }
    writer->first_node = false;
    fprintf(writer->file, "    \"%s\": {\"position\":\"", node_id);
    dfpn_certificate_write_position(writer->file, position);
    fprintf(
        writer->file,
        "\",\"clock\":%u,",
        (unsigned)position.reversible_plies
    );

    if (
        position.reversible_plies >=
        writer->context->tablebase->no_progress_plies
    ) {
        fputs(
            "\"kind\":\"terminal\",\"reason\":\"no_progress\","
            "\"winner\":null}",
            writer->file
        );
        ++writer->node_count;
        return !ferror(writer->file);
    }

    generate_moves(position, writer->context->generator);
    uint32_t move_count = writer->context->generator->count;
    Move *moves = NULL;
    if (move_count > 0) {
        moves = malloc((size_t)move_count * sizeof(*moves));
        if (moves == NULL) {
            writer->failure_reason =
                "unable to allocate certificate move list";
            return false;
        }
        memcpy(
            moves,
            writer->context->generator->moves,
            (size_t)move_count * sizeof(*moves)
        );
    }
    if (move_count == 0) {
        const char *winner = other(position.turn) == BLACK ? "BLACK" : "RED";
        fprintf(
            writer->file,
            "\"kind\":\"terminal\",\"reason\":\"no_legal_move\","
            "\"winner\":\"%s\"}",
            winner
        );
        ++writer->node_count;
        free(moves);
        return !ferror(writer->file);
    }

    int frontier_pieces = 4;
    for (size_t index = 0;
         index < writer->context->frontier_count;
         ++index) {
        int candidate =
            (int)writer->context->frontiers[index]->piece_count;
        if (candidate > frontier_pieces) frontier_pieces = candidate;
    }
    if (count_bits(occupied(position)) <= frontier_pieces) {
        int side_outcome;
        if (!dfpn_probe_tablebase_outcome(
                writer->context, position, &side_outcome
            )) {
            writer->failure_reason = "certificate tablebase probe failed";
            free(moves);
            return false;
        }
        const char *outcome = side_outcome == OUTCOME_WIN
            ? "WIN"
            : side_outcome == OUTCOME_DRAW ? "DRAW" : "LOSS";
        fprintf(
            writer->file,
            "\"kind\":\"tablebase\",\"outcome\":\"%s\"}",
            outcome
        );
        ++writer->node_count;
        free(moves);
        return !ferror(writer->file);
    }

    bool choice = position.turn == writer->context->root_player;
    uint8_t *selected = calloc(move_count, sizeof(*selected));
    if (selected == NULL) {
        writer->failure_reason =
            "unable to allocate certificate edge selection";
        free(moves);
        return false;
    }
    uint32_t selected_count = 0;
    for (uint32_t index = 0; index < move_count; ++index) {
        uint32_t child_proof;
        uint32_t child_disproof;
        bool found = dfpn_lookup_numbers(
            writer->context,
            moves[index].next,
            false,
            &child_proof,
            &child_disproof
        );
        (void)child_disproof;
        if (choice) {
            if (found && child_proof == 0) {
                selected[index] = 1;
                ++selected_count;
                if (!writer->all_choices) break;
            }
        } else if (!found || child_proof != 0) {
            writer->failure_reason =
                "opponent DFPN node lacks a proven legal reply";
            free(selected);
            free(moves);
            return false;
        } else {
            selected[index] = 1;
            ++selected_count;
        }
    }
    if (selected_count == 0) {
        writer->failure_reason =
            "engine DFPN node has no proven safe choice";
        free(selected);
        free(moves);
        return false;
    }

    fprintf(
        writer->file,
        "\"kind\":\"%s\",\"edges\":[",
        choice ? "choice" : "all"
    );
    bool first_edge = true;
    for (uint32_t index = 0; index < move_count; ++index) {
        if (!selected[index]) continue;
        char child_id[64];
        char notation[128];
        dfpn_certificate_node_id(moves[index].next, child_id);
        if (!proof_move_format(&moves[index], notation, sizeof(notation))) {
            writer->failure_reason = "certificate move notation overflow";
            free(selected);
            free(moves);
            return false;
        }
        fprintf(
            writer->file,
            "%s{\"move\":\"%s\",\"child\":\"%s\"}",
            first_edge ? "" : ",",
            notation,
            child_id
        );
        first_edge = false;
    }
    fputs("]}", writer->file);
    ++writer->node_count;
    if (ferror(writer->file)) {
        writer->failure_reason = "unable to write proof certificate";
        free(selected);
        free(moves);
        return false;
    }
    for (uint32_t index = 0; index < move_count; ++index) {
        if (
            selected[index] &&
            !dfpn_certificate_visit(writer, moves[index].next)
        ) {
            free(selected);
            free(moves);
            return false;
        }
    }
    free(selected);
    free(moves);
    return true;
}

static bool write_dfpn_certificate(
    DfpnContext *context,
    Position root,
    const char *path,
    bool all_choices
) {
    size_t temporary_length = strlen(path) + 5;
    char *temporary_path = malloc(temporary_length);
    size_t live_seen_bytes = dfpn_bitset_bytes(context->capacity);
    size_t solved_seen_bytes = dfpn_bitset_bytes(
        context->solved_capacity
    );
    uint8_t *live_seen = calloc(live_seen_bytes, 1);
    uint8_t *solved_seen = calloc(solved_seen_bytes, 1);
    if (
        temporary_path == NULL ||
        live_seen == NULL ||
        solved_seen == NULL
    ) {
        free(temporary_path);
        free(live_seen);
        free(solved_seen);
        return false;
    }
    snprintf(temporary_path, temporary_length, "%s.tmp", path);
    FILE *file = fopen(temporary_path, "wb");
    if (file == NULL) {
        free(temporary_path);
        free(live_seen);
        free(solved_seen);
        return false;
    }
    char root_id[64];
    dfpn_certificate_node_id(root, root_id);
    fprintf(
        file,
        "{\n  \"format\":\"makhos-nonloss-proof-v2\",\n"
        "  \"rules\":{\"repetition_limit\":null,"
        "\"no_progress_plies\":%u},\n"
        "  \"root_player\":\"%s\",\n"
        "  \"root\":\"%s\",\n"
        "  \"ranked_tablebase_checksums\":{\"4\":\"%016" PRIx64 "\"",
        context->tablebase->no_progress_plies,
        context->root_player == BLACK ? "BLACK" : "RED",
        root_id,
        context->tablebase->checksum
    );
    for (size_t index = 0; index < context->frontier_count; ++index) {
        fprintf(
            file,
            ",\"%u\":\"%016" PRIx64 "\"",
            context->frontiers[index]->piece_count,
            context->frontiers[index]->checksum
        );
    }
    fputs("},\n  \"nodes\":{\n", file);

    DfpnCertificateWriter writer;
    memset(&writer, 0, sizeof(writer));
    writer.context = context;
    writer.file = file;
    writer.live_seen = live_seen;
    writer.solved_seen = solved_seen;
    writer.first_node = true;
    writer.all_choices = all_choices;
    bool ok = !ferror(file) && dfpn_certificate_visit(&writer, root);
    if (ok) {
        fputs("\n  }\n}\n", file);
        ok = !ferror(file);
    }
    if (fclose(file) != 0) {
        ok = false;
    }
    if (ok) {
        ok = makhos_replace_file_atomically(temporary_path, path);
    }
    if (!ok) {
        remove(temporary_path);
        fprintf(
            stderr,
            "failed to export DFPN certificate: %s\n",
            writer.failure_reason != NULL
                ? writer.failure_reason
                : "file or memory error"
        );
    } else {
        printf("DFPN certificate nodes: %" PRIu64 "\n", writer.node_count);
        printf("DFPN certificate wrote: %s\n", path);
    }
    free(temporary_path);
    free(live_seen);
    free(solved_seen);
    return ok;
}

static int dfpn_import_proof_checkpoint(
    DfpnContext *context,
    Position expected_root,
    const char *path
) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    char magic[8];
    uint32_t version;
    uint32_t no_progress;
    uint32_t root_player;
    uint64_t saved_capacity;
    uint64_t entry_count = 0;
    uint64_t tablebase_checksum;
    uint64_t expected_checksum;
    Position root;
    memset(&root, 0, sizeof(root));
    bool ok =
        fread(magic, 1, 8, file) == 8 &&
        memcmp(magic, PROOF_CHECKPOINT_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, file) == 1 &&
        version == PROOF_CHECKPOINT_VERSION &&
        fread(&no_progress, sizeof(no_progress), 1, file) == 1 &&
        no_progress == context->tablebase->no_progress_plies &&
        fread(&root_player, sizeof(root_player), 1, file) == 1 &&
        root_player == context->root_player &&
        fread(&saved_capacity, sizeof(saved_capacity), 1, file) == 1 &&
        fread(&entry_count, sizeof(entry_count), 1, file) == 1 &&
        entry_count <
            (uint64_t)dfpn_hash_load_limit(context->solved_capacity) &&
        fread(&tablebase_checksum, sizeof(tablebase_checksum), 1, file) == 1 &&
        tablebase_checksum == context->tablebase->checksum &&
        fread(&expected_checksum, sizeof(expected_checksum), 1, file) == 1 &&
        fread(&root.red, sizeof(root.red), 1, file) == 1 &&
        fread(&root.black, sizeof(root.black), 1, file) == 1 &&
        fread(&root.kings, sizeof(root.kings), 1, file) == 1 &&
        fread(&root.turn, sizeof(root.turn), 1, file) == 1 &&
        fread(&root.reversible_plies, sizeof(root.reversible_plies), 1, file) == 1 &&
        same_exact_key(root, expected_root);
    (void)saved_capacity;
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint8_t record[16];
    size_t count_before = context->solved_count;
    for (uint64_t index = 0; ok && index < entry_count; ++index) {
        if (fread(record, 1, sizeof(record), file) != sizeof(record)) {
            ok = false;
            break;
        }
        checksum = checksum_update(checksum, record, sizeof(record));
        Position imported;
        memset(&imported, 0, sizeof(imported));
        memcpy(&imported.red, record, 4);
        memcpy(&imported.black, record + 4, 4);
        memcpy(&imported.kings, record + 8, 4);
        imported.turn = record[12];
        imported.reversible_plies = record[13];
        uint8_t value = record[14];
        if (
            (imported.red & imported.black) != 0 ||
            (imported.kings & ~occupied(imported)) != 0 ||
            (imported.turn != RED && imported.turn != BLACK) ||
            imported.reversible_plies > no_progress ||
            value > PROOF_PROVEN
        ) {
            ok = false;
            break;
        }
        if (
            dfpn_find_solved(context, imported, false, false) != NULL ||
            dfpn_find_entry(context, imported, false) != NULL ||
            dfpn_find_solved(
                context,
                imported,
                true,
                value == PROOF_PROVEN
            ) == NULL
        ) {
            ok = false;
            break;
        }
    }
    if (ok && fgetc(file) != EOF) {
        ok = false;
    }
    fclose(file);
    if (
        !ok ||
        checksum != expected_checksum ||
        context->solved_count - count_before != entry_count
    ) {
        return -1;
    }
    printf("DFPN seed loaded: %s\n", path);
    printf("DFPN seed entries: %" PRIu64 "\n", entry_count);
    printf("DFPN seed checksum: %016" PRIx64 "\n", checksum);
    return 1;
}

static void dfpn_record_encode(const DfpnEntry *entry, uint8_t record[24]) {
    memset(record, 0, 24);
    uint32_t red;
    uint32_t black;
    dfpn_expand_colours(
        entry->occupied, entry->black_flags, &red, &black
    );
    memcpy(record, &red, 4);
    memcpy(record + 4, &black, 4);
    uint32_t kings = dfpn_expand_kings(
        red, black, entry->king_flags
    );
    memcpy(record + 8, &kings, 4);
    record[12] = dfpn_meta_turn(entry->meta);
    record[13] = dfpn_meta_clock(entry->meta);
    record[14] = dfpn_entry_is_expanded(entry) ? 1 : 0;
    uint32_t proof_number = dfpn_entry_proof(entry);
    uint32_t disproof_number = dfpn_entry_disproof(entry);
    memcpy(record + 16, &proof_number, 4);
    memcpy(record + 20, &disproof_number, 4);
}

static void dfpn_solved_record_encode(
    const DfpnSolvedEntry *entry,
    uint8_t record[24]
) {
    memset(record, 0, 24);
    uint32_t red;
    uint32_t black;
    dfpn_expand_colours(
        entry->occupied, entry->black_flags, &red, &black
    );
    memcpy(record, &red, 4);
    memcpy(record + 4, &black, 4);
    uint32_t kings = dfpn_expand_kings(
        red, black, entry->king_flags
    );
    memcpy(record + 8, &kings, 4);
    record[12] = dfpn_meta_turn(entry->meta);
    record[13] = dfpn_meta_clock(entry->meta);
    record[14] = 1;
    uint32_t proof_number = entry->proven ? 0 : DFPN_INFINITY;
    uint32_t disproof_number = entry->proven ? DFPN_INFINITY : 0;
    memcpy(record + 16, &proof_number, 4);
    memcpy(record + 20, &disproof_number, 4);
}

static void dfpn_record_v2_encode(
    const DfpnEntry *entry,
    uint8_t record[DFPN_CHECKPOINT_RECORD_BYTES]
) {
    memset(record, 0, DFPN_CHECKPOINT_RECORD_BYTES);
    uint32_t red;
    uint32_t black;
    dfpn_expand_colours(
        entry->occupied, entry->black_flags, &red, &black
    );
    memcpy(record, &red, 4);
    memcpy(record + 4, &black, 4);
    memcpy(record + 8, &entry->king_flags, 2);
    record[10] = entry->meta;
    record[11] = dfpn_entry_is_expanded(entry) ? 1 : 0;
    memcpy(record + 12, &entry->proof_code, 2);
    memcpy(record + 14, &entry->disproof_code, 2);
}

static void dfpn_solved_record_v2_encode(
    const DfpnSolvedEntry *entry,
    uint8_t record[DFPN_CHECKPOINT_RECORD_BYTES]
) {
    memset(record, 0, DFPN_CHECKPOINT_RECORD_BYTES);
    uint32_t red;
    uint32_t black;
    dfpn_expand_colours(
        entry->occupied, entry->black_flags, &red, &black
    );
    memcpy(record, &red, 4);
    memcpy(record + 4, &black, 4);
    memcpy(record + 8, &entry->king_flags, 2);
    record[10] = entry->meta;
    record[11] = 1;
    uint16_t proof_code = dfpn_number_encode(
        entry->proven ? 0 : DFPN_INFINITY
    );
    uint16_t disproof_code = dfpn_number_encode(
        entry->proven ? DFPN_INFINITY : 0
    );
    memcpy(record + 12, &proof_code, 2);
    memcpy(record + 14, &disproof_code, 2);
}

static bool dfpn_number_code_valid(uint16_t code) {
    if (code == UINT16_MAX || (code & UINT16_C(0x8000)) == 0) {
        return true;
    }
    unsigned shift = (unsigned)((code >> 10) & UINT16_C(31));
    return shift >= 5 && shift <= 19;
}

static bool dfpn_record_v2_shape_valid(
    const uint8_t record[DFPN_CHECKPOINT_RECORD_BYTES],
    uint32_t no_progress
) {
    uint32_t red;
    uint32_t black;
    uint16_t king_flags;
    uint16_t proof_code;
    uint16_t disproof_code;
    memcpy(&red, record, 4);
    memcpy(&black, record + 4, 4);
    memcpy(&king_flags, record + 8, 2);
    uint8_t meta = record[10];
    uint8_t expanded = record[11];
    memcpy(&proof_code, record + 12, 2);
    memcpy(&disproof_code, record + 14, 2);
    int pieces = count_bits(red | black);
    if (
        (red & black) != 0 ||
        pieces > 16 ||
        (pieces < 16 && (king_flags >> pieces) != 0) ||
        meta == 0 ||
        dfpn_meta_clock(meta) > no_progress ||
        expanded > 1 ||
        !dfpn_number_code_valid(proof_code) ||
        !dfpn_number_code_valid(disproof_code)
    ) {
        return false;
    }
    uint32_t proof_number = dfpn_number_decode(proof_code);
    uint32_t disproof_number = dfpn_number_decode(disproof_code);
    return
        !(proof_number == 0 && disproof_number != DFPN_INFINITY) &&
        !(disproof_number == 0 && proof_number != DFPN_INFINITY) &&
        (expanded || (proof_number == 1 && disproof_number == 1));
}

static bool dfpn_record_shape_valid(
    const uint8_t record[24],
    uint32_t no_progress
) {
    Position position;
    memset(&position, 0, sizeof(position));
    memcpy(&position.red, record, 4);
    memcpy(&position.black, record + 4, 4);
    memcpy(&position.kings, record + 8, 4);
    position.turn = record[12];
    position.reversible_plies = record[13];
    uint8_t expanded = record[14];
    uint32_t proof_number;
    uint32_t disproof_number;
    memcpy(&proof_number, record + 16, 4);
    memcpy(&disproof_number, record + 20, 4);
    bool number_shape_ok =
        proof_number <= DFPN_INFINITY &&
        disproof_number <= DFPN_INFINITY &&
        !(proof_number == 0 && disproof_number != DFPN_INFINITY) &&
        !(disproof_number == 0 && proof_number != DFPN_INFINITY);
    return
        (position.red & position.black) == 0 &&
        (position.kings & ~occupied(position)) == 0 &&
        count_bits(occupied(position)) <= 16 &&
        (position.turn == RED || position.turn == BLACK) &&
        position.reversible_plies <= no_progress &&
        position.reversible_plies < DFPN_META_TURN_STRIDE &&
        expanded <= 1 &&
        number_shape_ok &&
        (expanded || (proof_number == 1 && disproof_number == 1));
}

/*
 * Unexpanded records contain only the default (pn=1,dn=1) frontier value and
 * are recreated exactly when an expanded parent enumerates its legal moves.
 * Omitting them from persistent checkpoints is therefore lossless and avoids
 * spending most of the fixed hash table on a disposable search boundary.
 */
static int compact_dfpn_checkpoint(
    const char *input_path,
    const char *output_path,
    bool resolved_only,
    bool replace_tablebase_binding,
    uint64_t replacement_tablebase_binding,
    bool require_tablebase_binding,
    uint64_t required_tablebase_binding,
    bool require_no_progress,
    uint32_t required_no_progress,
    bool replace_root,
    Position replacement_root
) {
    FILE *input = fopen(input_path, "rb");
    if (input == NULL) {
        fprintf(stderr, "unable to open DFPN checkpoint: %s\n", input_path);
        return 2;
    }
    char magic[8];
    uint32_t version = 0;
    uint32_t no_progress;
    uint32_t root_player;
    uint64_t saved_capacity;
    uint64_t entry_count;
    uint64_t tablebase_checksum;
    uint64_t expected_checksum;
    Position root;
    memset(&root, 0, sizeof(root));
    bool ok =
        fread(magic, 1, 8, input) == 8 &&
        memcmp(magic, DFPN_CHECKPOINT_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, input) == 1 &&
        (version == DFPN_CHECKPOINT_VERSION_V1 ||
         version == DFPN_CHECKPOINT_VERSION) &&
        fread(&no_progress, sizeof(no_progress), 1, input) == 1 &&
        (!require_no_progress || no_progress == required_no_progress) &&
        fread(&root_player, sizeof(root_player), 1, input) == 1 &&
        (root_player == RED || root_player == BLACK) &&
        fread(&saved_capacity, sizeof(saved_capacity), 1, input) == 1 &&
        fread(&entry_count, sizeof(entry_count), 1, input) == 1 &&
        fread(&tablebase_checksum, sizeof(tablebase_checksum), 1, input) == 1 &&
        (!require_tablebase_binding ||
         tablebase_checksum == required_tablebase_binding) &&
        fread(&expected_checksum, sizeof(expected_checksum), 1, input) == 1 &&
        fread(&root.red, sizeof(root.red), 1, input) == 1 &&
        fread(&root.black, sizeof(root.black), 1, input) == 1 &&
        fread(&root.kings, sizeof(root.kings), 1, input) == 1 &&
        fread(&root.turn, sizeof(root.turn), 1, input) == 1 &&
        fread(&root.reversible_plies, sizeof(root.reversible_plies), 1, input) == 1;
    size_t temporary_length = strlen(output_path) + 5;
    char *temporary_path = malloc(temporary_length);
    if (!ok || temporary_path == NULL) {
        fclose(input);
        free(temporary_path);
        fprintf(stderr, "invalid DFPN checkpoint header\n");
        return 2;
    }
    snprintf(temporary_path, temporary_length, "%s.tmp", output_path);
    FILE *output = fopen(temporary_path, "wb+");
    if (output == NULL) {
        fclose(input);
        free(temporary_path);
        fprintf(stderr, "unable to create compact DFPN checkpoint\n");
        return 2;
    }
    uint8_t zero_header[66] = {0};
    ok = fwrite(zero_header, 1, sizeof(zero_header), output) == sizeof(zero_header);
    uint64_t input_checksum = UINT64_C(1469598103934665603);
    uint64_t output_checksum = UINT64_C(1469598103934665603);
    uint64_t retained = 0;
    uint64_t resolved = 0;
    uint8_t input_record[DFPN_CHECKPOINT_RECORD_V1_BYTES];
    uint8_t output_record[DFPN_CHECKPOINT_RECORD_BYTES];
    size_t input_record_size = version == DFPN_CHECKPOINT_VERSION_V1
        ? DFPN_CHECKPOINT_RECORD_V1_BYTES
        : DFPN_CHECKPOINT_RECORD_BYTES;
    for (uint64_t index = 0; ok && index < entry_count; ++index) {
        if (
            fread(input_record, 1, input_record_size, input) !=
            input_record_size
        ) {
            ok = false;
            break;
        }
        input_checksum = checksum_update(
            input_checksum, input_record, input_record_size
        );
        uint8_t expanded;
        uint32_t proof_number;
        uint32_t disproof_number;
        if (version == DFPN_CHECKPOINT_VERSION_V1) {
            if (!dfpn_record_shape_valid(input_record, no_progress)) {
                ok = false;
                break;
            }
            expanded = input_record[14];
            memcpy(&proof_number, input_record + 16, 4);
            memcpy(&disproof_number, input_record + 20, 4);
            if (expanded) {
                Position loaded;
                memset(&loaded, 0, sizeof(loaded));
                memcpy(&loaded.red, input_record, 4);
                memcpy(&loaded.black, input_record + 4, 4);
                memcpy(&loaded.kings, input_record + 8, 4);
                loaded.turn = input_record[12];
                loaded.reversible_plies = input_record[13];
                DfpnEntry converted;
                memset(&converted, 0, sizeof(converted));
                dfpn_entry_set_position(&converted, loaded);
                dfpn_entry_set_numbers(
                    &converted, proof_number, disproof_number
                );
                dfpn_record_v2_encode(&converted, output_record);
            }
        } else {
            if (!dfpn_record_v2_shape_valid(input_record, no_progress)) {
                ok = false;
                break;
            }
            expanded = input_record[11];
            uint16_t proof_code;
            uint16_t disproof_code;
            memcpy(&proof_code, input_record + 12, 2);
            memcpy(&disproof_code, input_record + 14, 2);
            proof_number = dfpn_number_decode(proof_code);
            disproof_number = dfpn_number_decode(disproof_code);
            if (expanded) {
                memcpy(
                    output_record,
                    input_record,
                    DFPN_CHECKPOINT_RECORD_BYTES
                );
            }
        }
        if (!expanded) {
            continue;
        }
        bool is_resolved = proof_number == 0 || disproof_number == 0;
        if (resolved_only && !is_resolved) {
            continue;
        }
        if (is_resolved) {
            ++resolved;
        }
        output_checksum = checksum_update(
            output_checksum,
            output_record,
            DFPN_CHECKPOINT_RECORD_BYTES
        );
        ok = fwrite(
            output_record,
            1,
            DFPN_CHECKPOINT_RECORD_BYTES,
            output
        ) == DFPN_CHECKPOINT_RECORD_BYTES;
        ++retained;
    }
    if (ok && fgetc(input) != EOF) {
        ok = false;
    }
    if (fclose(input) != 0) {
        ok = false;
    }
    if (input_checksum != expected_checksum) {
        ok = false;
    }
    if (ok && fseek(output, 0, SEEK_SET) != 0) {
        ok = false;
    }
    if (ok) {
        uint32_t output_version = DFPN_CHECKPOINT_VERSION;
        uint64_t output_tablebase_binding = replace_tablebase_binding
            ? replacement_tablebase_binding
            : tablebase_checksum;
        Position output_root = replace_root ? replacement_root : root;
        ok =
            fwrite(DFPN_CHECKPOINT_MAGIC, 1, 8, output) == 8 &&
            fwrite(&output_version, sizeof(output_version), 1, output) == 1 &&
            fwrite(&no_progress, sizeof(no_progress), 1, output) == 1 &&
            fwrite(&root_player, sizeof(root_player), 1, output) == 1 &&
            fwrite(&saved_capacity, sizeof(saved_capacity), 1, output) == 1 &&
            fwrite(&retained, sizeof(retained), 1, output) == 1 &&
            fwrite(&output_tablebase_binding, sizeof(output_tablebase_binding), 1, output) == 1 &&
            fwrite(&output_checksum, sizeof(output_checksum), 1, output) == 1 &&
            fwrite(&output_root.red, sizeof(output_root.red), 1, output) == 1 &&
            fwrite(&output_root.black, sizeof(output_root.black), 1, output) == 1 &&
            fwrite(&output_root.kings, sizeof(output_root.kings), 1, output) == 1 &&
            fwrite(&output_root.turn, sizeof(output_root.turn), 1, output) == 1 &&
            fwrite(&output_root.reversible_plies, sizeof(output_root.reversible_plies), 1, output) == 1;
    }
    if (fclose(output) != 0) {
        ok = false;
    }
    if (ok) {
        ok = makhos_replace_file_atomically(temporary_path, output_path);
    }
    if (!ok) {
        remove(temporary_path);
        fprintf(stderr, "invalid or truncated DFPN checkpoint\n");
        free(temporary_path);
        return 2;
    }
    free(temporary_path);
    printf("DFPN checkpoint input entries: %" PRIu64 "\n", entry_count);
    printf("DFPN checkpoint retained expanded: %" PRIu64 "\n", retained);
    printf("DFPN checkpoint resolved: %" PRIu64 "\n", resolved);
    printf("DFPN checkpoint omitted records: %" PRIu64 "\n",
        entry_count - retained);
    printf("DFPN checkpoint checksum: %016" PRIx64 "\n", output_checksum);
    if (replace_root) {
        printf(
            "DFPN checkpoint root retargeted: red=%08" PRIx32
            " black=%08" PRIx32 " kings=%08" PRIx32
            " turn=%u clock=%u\n",
            replacement_root.red,
            replacement_root.black,
            replacement_root.kings,
            replacement_root.turn,
            replacement_root.reversible_plies
        );
    }
    printf("DFPN checkpoint wrote: %s\n", output_path);
    return 0;
}

#pragma pack(push, 1)

typedef struct {
    uint32_t red;
    uint32_t black;
    uint16_t king_flags;
    uint8_t meta;
    uint8_t padding;
} DfpnStrategyEntry;

#pragma pack(pop)

_Static_assert(
    sizeof(DfpnStrategyEntry) == 12,
    "DFPN strategy entry must remain compact"
);

static DfpnStrategyEntry *dfpn_strategy_find(
    DfpnStrategyEntry *entries,
    size_t capacity,
    Position position,
    bool create,
    bool *created
) {
    size_t mask = capacity - 1;
    size_t slot = (size_t)hash_position(position) & mask;
    uint16_t king_flags = dfpn_compress_kings(position);
    uint8_t meta = dfpn_position_meta(position);
    for (size_t probe = 0; probe < capacity; ++probe) {
        DfpnStrategyEntry *entry = &entries[slot];
        if (entry->meta == 0) {
            if (!create) return NULL;
            entry->red = position.red;
            entry->black = position.black;
            entry->king_flags = king_flags;
            entry->meta = meta;
            entry->padding = 0;
            if (created != NULL) *created = true;
            return entry;
        }
        if (
            entry->red == position.red &&
            entry->black == position.black &&
            entry->king_flags == king_flags &&
            entry->meta == meta
        ) {
            if (created != NULL) *created = false;
            return entry;
        }
        slot = (slot + 1) & mask;
    }
    return NULL;
}

static int export_dfpn_strategy(
    const char *input_path,
    const char *output_path,
    int hash_power,
    uint64_t required_binding,
    uint64_t four_checksum,
    uint64_t five_checksum,
    uint64_t six_checksum,
    uint32_t required_no_progress,
    bool all_choices
) {
    FILE *input = fopen(input_path, "rb");
    if (input == NULL) {
        fprintf(stderr, "unable to open DFPN checkpoint: %s\n", input_path);
        return 2;
    }
    char magic[8];
    uint32_t version = 0;
    uint32_t no_progress;
    uint32_t root_player;
    uint64_t saved_capacity;
    uint64_t entry_count;
    uint64_t tablebase_binding;
    uint64_t expected_checksum;
    Position root;
    memset(&root, 0, sizeof(root));
    bool ok =
        fread(magic, 1, 8, input) == 8 &&
        memcmp(magic, DFPN_CHECKPOINT_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, input) == 1 &&
        (version == DFPN_CHECKPOINT_VERSION_V1 ||
         version == DFPN_CHECKPOINT_VERSION) &&
        fread(&no_progress, sizeof(no_progress), 1, input) == 1 &&
        no_progress == required_no_progress &&
        no_progress < DFPN_META_TURN_STRIDE &&
        fread(&root_player, sizeof(root_player), 1, input) == 1 &&
        (root_player == RED || root_player == BLACK) &&
        fread(&saved_capacity, sizeof(saved_capacity), 1, input) == 1 &&
        fread(&entry_count, sizeof(entry_count), 1, input) == 1 &&
        fread(&tablebase_binding, sizeof(tablebase_binding), 1, input) == 1 &&
        tablebase_binding == required_binding &&
        fread(&expected_checksum, sizeof(expected_checksum), 1, input) == 1 &&
        fread(&root.red, sizeof(root.red), 1, input) == 1 &&
        fread(&root.black, sizeof(root.black), 1, input) == 1 &&
        fread(&root.kings, sizeof(root.kings), 1, input) == 1 &&
        fread(&root.turn, sizeof(root.turn), 1, input) == 1 &&
        fread(&root.reversible_plies, sizeof(root.reversible_plies), 1, input) == 1 &&
        (root.red & root.black) == 0 &&
        (root.kings & ~occupied(root)) == 0 &&
        (root.turn == RED || root.turn == BLACK) &&
        root.reversible_plies <= no_progress;
    (void)saved_capacity;
    if (!ok) {
        fclose(input);
        fprintf(stderr, "invalid or incompatible DFPN checkpoint header\n");
        return 2;
    }

    size_t capacity = (size_t)1 << hash_power;
    DfpnStrategyEntry *entries = calloc(capacity, sizeof(*entries));
    if (entries == NULL) {
        fclose(input);
        fprintf(stderr, "unable to allocate DFPN strategy hash\n");
        return 2;
    }
    uint64_t input_checksum = UINT64_C(1469598103934665603);
    uint64_t retained = 0;
    uint8_t record[DFPN_CHECKPOINT_RECORD_V1_BYTES];
    size_t record_size = version == DFPN_CHECKPOINT_VERSION_V1
        ? DFPN_CHECKPOINT_RECORD_V1_BYTES
        : DFPN_CHECKPOINT_RECORD_BYTES;
    for (uint64_t index = 0; ok && index < entry_count; ++index) {
        if (fread(record, 1, record_size, input) != record_size) {
            ok = false;
            break;
        }
        input_checksum = checksum_update(input_checksum, record, record_size);
        Position loaded;
        memset(&loaded, 0, sizeof(loaded));
        uint32_t proof_number;
        if (version == DFPN_CHECKPOINT_VERSION_V1) {
            if (!dfpn_record_shape_valid(record, no_progress)) {
                ok = false;
                break;
            }
            memcpy(&loaded.red, record, 4);
            memcpy(&loaded.black, record + 4, 4);
            memcpy(&loaded.kings, record + 8, 4);
            loaded.turn = record[12];
            loaded.reversible_plies = record[13];
            memcpy(&proof_number, record + 16, 4);
        } else {
            if (!dfpn_record_v2_shape_valid(record, no_progress)) {
                ok = false;
                break;
            }
            uint16_t king_flags;
            uint16_t proof_code;
            memcpy(&loaded.red, record, 4);
            memcpy(&loaded.black, record + 4, 4);
            memcpy(&king_flags, record + 8, 2);
            uint8_t meta = record[10];
            loaded.kings = dfpn_expand_kings(
                loaded.red, loaded.black, king_flags
            );
            loaded.turn = dfpn_meta_turn(meta);
            loaded.reversible_plies = dfpn_meta_clock(meta);
            memcpy(&proof_code, record + 12, 2);
            proof_number = dfpn_number_decode(proof_code);
        }
        if (proof_number != 0) continue;
        bool created = false;
        if (
            retained >= (uint64_t)(capacity * 85 / 100) ||
            dfpn_strategy_find(
                entries, capacity, loaded, true, &created
            ) == NULL
        ) {
            ok = false;
            break;
        }
        if (created) ++retained;
    }
    if (ok && fgetc(input) != EOF) ok = false;
    if (fclose(input) != 0) ok = false;
    if (input_checksum != expected_checksum) ok = false;
    if (
        ok &&
        dfpn_strategy_find(entries, capacity, root, false, NULL) == NULL
    ) {
        fprintf(stderr, "DFPN checkpoint root is not proven non-loss\n");
        ok = false;
    }
    if (!ok) {
        free(entries);
        fprintf(stderr, "invalid, truncated, or oversized DFPN strategy input\n");
        return 2;
    }

    uint64_t payload_checksum = checksum_update(
        UINT64_C(1469598103934665603),
        (const uint8_t *)entries,
        capacity * sizeof(*entries)
    );
    size_t temporary_length = strlen(output_path) + 5;
    char *temporary_path = malloc(temporary_length);
    if (temporary_path == NULL) {
        free(entries);
        return 2;
    }
    snprintf(temporary_path, temporary_length, "%s.tmp", output_path);
    FILE *output = fopen(temporary_path, "wb");
    if (output == NULL) {
        free(temporary_path);
        free(entries);
        fprintf(stderr, "unable to create DFPN strategy file\n");
        return 2;
    }
    uint32_t strategy_version = DFPN_STRATEGY_VERSION;
    uint32_t header_bytes = DFPN_STRATEGY_HEADER_BYTES;
    uint32_t power = (uint32_t)hash_power;
    uint32_t flags = all_choices ? UINT32_C(1) : UINT32_C(0);
    uint64_t capacity64 = (uint64_t)capacity;
    uint16_t padding = 0;
    ok =
        fwrite(DFPN_STRATEGY_MAGIC, 1, 8, output) == 8 &&
        fwrite(&strategy_version, 4, 1, output) == 1 &&
        fwrite(&header_bytes, 4, 1, output) == 1 &&
        fwrite(&no_progress, 4, 1, output) == 1 &&
        fwrite(&root_player, 4, 1, output) == 1 &&
        fwrite(&power, 4, 1, output) == 1 &&
        fwrite(&flags, 4, 1, output) == 1 &&
        fwrite(&capacity64, 8, 1, output) == 1 &&
        fwrite(&retained, 8, 1, output) == 1 &&
        fwrite(&tablebase_binding, 8, 1, output) == 1 &&
        fwrite(&four_checksum, 8, 1, output) == 1 &&
        fwrite(&five_checksum, 8, 1, output) == 1 &&
        fwrite(&six_checksum, 8, 1, output) == 1 &&
        fwrite(&payload_checksum, 8, 1, output) == 1 &&
        fwrite(&root.red, 4, 1, output) == 1 &&
        fwrite(&root.black, 4, 1, output) == 1 &&
        fwrite(&root.kings, 4, 1, output) == 1 &&
        fwrite(&root.turn, 1, 1, output) == 1 &&
        fwrite(&root.reversible_plies, 1, 1, output) == 1 &&
        fwrite(&padding, 2, 1, output) == 1 &&
        fwrite(entries, sizeof(*entries), capacity, output) == capacity;
    if (fclose(output) != 0) ok = false;
    if (ok) {
        ok = makhos_replace_file_atomically(temporary_path, output_path);
    }
    if (!ok) {
        remove(temporary_path);
        fprintf(stderr, "unable to write DFPN strategy file\n");
    } else {
        printf("DFPN strategy entries: %" PRIu64 "\n", retained);
        printf("DFPN strategy capacity: %" PRIu64 "\n", capacity64);
        printf("DFPN strategy checksum: %016" PRIx64 "\n", payload_checksum);
        printf("DFPN strategy wrote: %s\n", output_path);
    }
    free(temporary_path);
    free(entries);
    return ok ? 0 : 2;
}

static bool dfpn_write_checkpoint_header(
    FILE *file,
    const DfpnContext *context,
    Position root,
    uint64_t capacity,
    uint64_t entry_count,
    uint64_t checksum
) {
    uint32_t version = DFPN_CHECKPOINT_VERSION;
    uint32_t root_player = context->root_player;
    return
        fwrite(DFPN_CHECKPOINT_MAGIC, 1, 8, file) == 8 &&
        fwrite(&version, sizeof(version), 1, file) == 1 &&
        fwrite(&context->tablebase->no_progress_plies, sizeof(uint32_t), 1, file) == 1 &&
        fwrite(&root_player, sizeof(root_player), 1, file) == 1 &&
        fwrite(&capacity, sizeof(capacity), 1, file) == 1 &&
        fwrite(&entry_count, sizeof(entry_count), 1, file) == 1 &&
        fwrite(&(uint64_t){dfpn_tablebase_binding(context)}, sizeof(uint64_t), 1, file) == 1 &&
        fwrite(&checksum, sizeof(checksum), 1, file) == 1 &&
        fwrite(&root.red, sizeof(root.red), 1, file) == 1 &&
        fwrite(&root.black, sizeof(root.black), 1, file) == 1 &&
        fwrite(&root.kings, sizeof(root.kings), 1, file) == 1 &&
        fwrite(&root.turn, sizeof(root.turn), 1, file) == 1 &&
        fwrite(&root.reversible_plies, sizeof(root.reversible_plies), 1, file) == 1;
}

static void dfpn_print_checkpoint_write_progress(
    const char *phase,
    size_t scanned,
    size_t capacity,
    uint64_t written
) {
    printf(
        "DFPN checkpoint write progress: %s %zu/%zu slots "
        "(records %" PRIu64 ")\n",
        phase,
        scanned,
        capacity,
        written
    );
    fflush(stdout);
}

static bool write_dfpn_checkpoint(
    const DfpnContext *context,
    Position root,
    const char *path
) {
    size_t temporary_length = strlen(path) + 5;
    char *temporary_path = malloc(temporary_length);
    if (temporary_path == NULL) {
        return false;
    }
    snprintf(temporary_path, temporary_length, "%s.tmp", path);
    FILE *file = fopen(temporary_path, "wb");
    if (file == NULL) {
        free(temporary_path);
        return false;
    }
    uint64_t capacity = context->capacity + context->solved_capacity;
    uint64_t entry_count = 0;
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint64_t live_written = 0;
    uint64_t resolved_written = context->solved_count;
    uint8_t record[DFPN_CHECKPOINT_RECORD_BYTES];
    bool ok = dfpn_write_checkpoint_header(
        file, context, root, capacity, 0, 0
    );

    size_t next_progress = context->solved_capacity <
        DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL
        ? context->solved_capacity
        : DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL;
    for (size_t index = 0;
         ok && index < context->solved_capacity;
         ++index) {
        if (context->solved_entries[index].meta == 0) {
            /* Keep reporting scan progress even across empty slots. */
        } else {
            dfpn_solved_record_v2_encode(
                &context->solved_entries[index], record
            );
            checksum = checksum_update(checksum, record, sizeof(record));
            ok = fwrite(record, 1, sizeof(record), file) == sizeof(record);
            ++entry_count;
        }
        size_t scanned = index + 1;
        if (ok && next_progress != 0 && scanned >= next_progress) {
            dfpn_print_checkpoint_write_progress(
                "resolved", scanned, context->solved_capacity, entry_count
            );
            if (next_progress >= context->solved_capacity) {
                next_progress = 0;
            } else {
                size_t remaining = context->solved_capacity - next_progress;
                next_progress += remaining <
                    DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL
                    ? remaining
                    : DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL;
            }
        }
    }

    next_progress = context->capacity <
        DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL
        ? context->capacity
        : DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL;
    for (size_t index = 0;
         ok && index < context->capacity;
         ++index) {
        if (
            context->entries[index].meta == 0 ||
            !dfpn_entry_is_expanded(&context->entries[index])
        ) {
            /* Keep reporting scan progress even across empty slots. */
        } else {
            dfpn_record_v2_encode(&context->entries[index], record);
            checksum = checksum_update(checksum, record, sizeof(record));
            ok = fwrite(record, 1, sizeof(record), file) == sizeof(record);
            ++entry_count;
            ++live_written;
            if (
                dfpn_entry_proof(&context->entries[index]) == 0 ||
                dfpn_entry_disproof(&context->entries[index]) == 0
            ) {
                ++resolved_written;
            }
        }
        size_t scanned = index + 1;
        if (ok && next_progress != 0 && scanned >= next_progress) {
            dfpn_print_checkpoint_write_progress(
                "live", scanned, context->capacity, entry_count
            );
            if (next_progress >= context->capacity) {
                next_progress = 0;
            } else {
                size_t remaining = context->capacity - next_progress;
                next_progress += remaining <
                    DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL
                    ? remaining
                    : DFPN_CHECKPOINT_WRITE_PROGRESS_INTERVAL;
            }
        }
    }
    if (ok && fflush(file) != 0) {
        ok = false;
    }
    if (ok && fseek(file, 0, SEEK_SET) != 0) {
        ok = false;
    }
    if (ok) {
        ok = dfpn_write_checkpoint_header(
            file, context, root, capacity, entry_count, checksum
        );
    }
    if (fclose(file) != 0) {
        ok = false;
    }
    if (ok) {
        ok = makhos_replace_file_atomically(temporary_path, path);
    }
    if (!ok) {
        remove(temporary_path);
    }
    free(temporary_path);
    if (ok) {
        printf("DFPN checkpoint entries: %" PRIu64 "\n", entry_count);
        printf("DFPN checkpoint resolved: %" PRIu64 "\n", resolved_written);
        printf(
            "DFPN checkpoint omitted unexpanded: %zu\n",
            context->count - (size_t)live_written
        );
        printf("DFPN checkpoint checksum: %016" PRIx64 "\n", checksum);
        printf("DFPN checkpoint wrote: %s\n", path);
    }
    return ok;
}

/* 0 = absent, 1 = loaded, -1 = invalid/error. */
static int read_dfpn_checkpoint(
    DfpnContext *context,
    Position expected_root,
    const char *path
) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    char magic[8];
    uint32_t version = 0;
    uint32_t no_progress;
    uint32_t root_player;
    uint64_t saved_capacity;
    uint64_t entry_count = 0;
    uint64_t tablebase_checksum;
    uint64_t expected_checksum;
    Position root;
    memset(&root, 0, sizeof(root));
    bool ok =
        fread(magic, 1, 8, file) == 8 &&
        memcmp(magic, DFPN_CHECKPOINT_MAGIC, 8) == 0 &&
        fread(&version, sizeof(version), 1, file) == 1 &&
        (version == DFPN_CHECKPOINT_VERSION_V1 ||
         version == DFPN_CHECKPOINT_VERSION) &&
        fread(&no_progress, sizeof(no_progress), 1, file) == 1 &&
        no_progress == context->tablebase->no_progress_plies &&
        fread(&root_player, sizeof(root_player), 1, file) == 1 &&
        root_player == context->root_player &&
        fread(&saved_capacity, sizeof(saved_capacity), 1, file) == 1 &&
        fread(&entry_count, sizeof(entry_count), 1, file) == 1 &&
        fread(&tablebase_checksum, sizeof(tablebase_checksum), 1, file) == 1 &&
        tablebase_checksum == dfpn_tablebase_binding(context) &&
        fread(&expected_checksum, sizeof(expected_checksum), 1, file) == 1 &&
        fread(&root.red, sizeof(root.red), 1, file) == 1 &&
        fread(&root.black, sizeof(root.black), 1, file) == 1 &&
        fread(&root.kings, sizeof(root.kings), 1, file) == 1 &&
        fread(&root.turn, sizeof(root.turn), 1, file) == 1 &&
        fread(&root.reversible_plies, sizeof(root.reversible_plies), 1, file) == 1 &&
        same_exact_key(root, expected_root);
    (void)saved_capacity;
    uint64_t checksum = UINT64_C(1469598103934665603);
    uint8_t record[24];
    size_t record_size = version == DFPN_CHECKPOINT_VERSION_V1
        ? DFPN_CHECKPOINT_RECORD_V1_BYTES
        : DFPN_CHECKPOINT_RECORD_BYTES;
    uint64_t next_progress = entry_count <
        DFPN_CHECKPOINT_LOAD_PROGRESS_INTERVAL
        ? entry_count
        : DFPN_CHECKPOINT_LOAD_PROGRESS_INTERVAL;
    for (uint64_t index = 0; ok && index < entry_count; ++index) {
        if (fread(record, 1, record_size, file) != record_size) {
            ok = false;
            break;
        }
        checksum = checksum_update(checksum, record, record_size);
        Position loaded;
        memset(&loaded, 0, sizeof(loaded));
        uint8_t expanded;
        uint32_t proof_number;
        uint32_t disproof_number;
        if (version == DFPN_CHECKPOINT_VERSION_V1) {
            memcpy(&loaded.red, record, 4);
            memcpy(&loaded.black, record + 4, 4);
            memcpy(&loaded.kings, record + 8, 4);
            loaded.turn = record[12];
            loaded.reversible_plies = record[13];
            expanded = record[14];
            memcpy(&proof_number, record + 16, 4);
            memcpy(&disproof_number, record + 20, 4);
            if (!dfpn_record_shape_valid(record, no_progress)) {
                ok = false;
                break;
            }
        } else {
            if (!dfpn_record_v2_shape_valid(record, no_progress)) {
                ok = false;
                break;
            }
            uint16_t king_flags;
            uint16_t proof_code;
            uint16_t disproof_code;
            memcpy(&loaded.red, record, 4);
            memcpy(&loaded.black, record + 4, 4);
            memcpy(&king_flags, record + 8, 2);
            uint8_t meta = record[10];
            loaded.kings = dfpn_expand_kings(
                loaded.red, loaded.black, king_flags
            );
            loaded.turn = dfpn_meta_turn(meta);
            loaded.reversible_plies = dfpn_meta_clock(meta);
            expanded = record[11];
            memcpy(&proof_code, record + 12, 2);
            memcpy(&disproof_code, record + 14, 2);
            proof_number = dfpn_number_decode(proof_code);
            disproof_number = dfpn_number_decode(disproof_code);
        }
        if (
            dfpn_find_solved(context, loaded, false, false) != NULL ||
            dfpn_find_entry(context, loaded, false) != NULL
        ) {
            ok = false;
            break;
        }
        if (proof_number == 0 || disproof_number == 0) {
            if (dfpn_find_solved(
                    context,
                    loaded,
                    true,
                    proof_number == 0
                ) == NULL) {
                ok = false;
                break;
            }
        } else {
            DfpnEntry *entry = dfpn_find_entry(context, loaded, true);
            if (entry == NULL) {
                ok = false;
                break;
            }
            if (expanded) {
                dfpn_entry_set_numbers(entry, proof_number, disproof_number);
            } else {
                dfpn_entry_mark_unexpanded(entry);
            }
        }
        uint64_t loaded_records = index + 1;
        if (next_progress != 0 && loaded_records >= next_progress) {
            printf(
                "DFPN checkpoint load progress: %" PRIu64 "/%" PRIu64
                " (live %zu, resolved %zu)\n",
                loaded_records,
                entry_count,
                context->count,
                context->solved_count
            );
            fflush(stdout);
            if (next_progress >= entry_count) {
                next_progress = 0;
            } else {
                uint64_t remaining = entry_count - next_progress;
                next_progress += remaining <
                    DFPN_CHECKPOINT_LOAD_PROGRESS_INTERVAL
                    ? remaining
                    : DFPN_CHECKPOINT_LOAD_PROGRESS_INTERVAL;
            }
        }
    }
    if (ok && fgetc(file) != EOF) {
        ok = false;
    }
    fclose(file);
    if (
        !ok ||
        checksum != expected_checksum ||
        context->count + context->solved_count != entry_count ||
        !dfpn_hash_below_load_guard(
            context->count, context->capacity
        ) ||
        !dfpn_hash_below_load_guard(
            context->solved_count, context->solved_capacity
        )
    ) {
        return -1;
    }
    printf("DFPN checkpoint loaded: %s\n", path);
    printf("DFPN checkpoint entries: %" PRIu64 "\n", entry_count);
    printf("DFPN checkpoint resolved: %zu\n", context->solved_count);
    printf("DFPN checkpoint checksum: %016" PRIx64 "\n", checksum);
    return 1;
}

static void destroy_dfpn_frontiers(
    CompactTablebase frontiers[2],
    size_t frontier_count
) {
    for (size_t index = 0; index < frontier_count; ++index) {
        compact_tablebase_destroy(&frontiers[index]);
    }
}

typedef struct {
    void *live;
    void *solved;
    size_t live_bytes;
    size_t solved_bytes;
    bool disk_backed;
#if defined(_WIN32)
    HANDLE live_file;
    HANDLE solved_file;
#endif
} DfpnHashStorage;

static char *dfpn_hash_scratch_path(
    const char *prefix,
    const char *kind
) {
    size_t length = strlen(prefix) + strlen(kind) + 64;
    char *path = malloc(length);
    if (path == NULL) return NULL;
#if defined(_WIN32)
    unsigned long process_id = (unsigned long)GetCurrentProcessId();
#else
    unsigned long process_id = (unsigned long)getpid();
#endif
    snprintf(path, length, "%s.%s.%lu.tmp", prefix, kind, process_id);
    return path;
}

static bool dfpn_map_scratch_file(
    const char *path,
    size_t length,
    void **base
#if defined(_WIN32)
    , HANDLE *file_handle
#endif
) {
    if (length == 0) return false;
#if defined(_WIN32)
    HANDLE file = CreateFileA(
        path,
        GENERIC_READ | GENERIC_WRITE,
        0,
        NULL,
        CREATE_NEW,
        FILE_ATTRIBUTE_TEMPORARY |
            FILE_FLAG_RANDOM_ACCESS |
            FILE_FLAG_DELETE_ON_CLOSE,
        NULL
    );
    if (file == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER file_size;
    file_size.QuadPart = (__int64)length;
    if (
        !SetFilePointerEx(file, file_size, NULL, FILE_BEGIN) ||
        !SetEndOfFile(file)
    ) {
        CloseHandle(file);
        return false;
    }
    HANDLE mapping = CreateFileMappingA(
        file,
        NULL,
        PAGE_READWRITE,
        (DWORD)(((uint64_t)length) >> 32),
        (DWORD)((uint64_t)length),
        NULL
    );
    if (mapping == NULL) {
        CloseHandle(file);
        return false;
    }
    void *mapped = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    CloseHandle(mapping);
    if (mapped == NULL) {
        CloseHandle(file);
        return false;
    }
    *base = mapped;
    *file_handle = file;
    return true;
#else
    if ((uintmax_t)length > (uintmax_t)INT64_MAX) return false;
    int file = open(path, O_RDWR | O_CREAT | O_EXCL, 0600);
    if (file < 0) return false;
    bool sized = ftruncate(file, (off_t)length) == 0;
    void *mapped = sized
        ? mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED, file, 0)
        : MAP_FAILED;
    if (mapped != MAP_FAILED) {
        (void)unlink(path);
    }
    (void)close(file);
    if (mapped == MAP_FAILED) {
        (void)unlink(path);
        return false;
    }
    *base = mapped;
    return true;
#endif
}

static void dfpn_hash_storage_destroy(DfpnHashStorage *storage) {
    if (!storage->disk_backed) {
        free(storage->live);
        free(storage->solved);
        memset(storage, 0, sizeof(*storage));
        return;
    }
#if defined(_WIN32)
    if (storage->live != NULL) UnmapViewOfFile(storage->live);
    if (storage->solved != NULL) UnmapViewOfFile(storage->solved);
    if (
        storage->live_file != NULL &&
        storage->live_file != INVALID_HANDLE_VALUE
    ) {
        CloseHandle(storage->live_file);
    }
    if (
        storage->solved_file != NULL &&
        storage->solved_file != INVALID_HANDLE_VALUE
    ) {
        CloseHandle(storage->solved_file);
    }
#else
    if (storage->live != NULL) {
        munmap(storage->live, storage->live_bytes);
    }
    if (storage->solved != NULL) {
        munmap(storage->solved, storage->solved_bytes);
    }
#endif
    memset(storage, 0, sizeof(*storage));
}

static bool dfpn_hash_storage_init(
    DfpnHashStorage *storage,
    size_t live_slots,
    size_t solved_slots,
    const char *scratch_prefix
) {
    memset(storage, 0, sizeof(*storage));
#if defined(_WIN32)
    storage->live_file = INVALID_HANDLE_VALUE;
    storage->solved_file = INVALID_HANDLE_VALUE;
#endif
    storage->live_bytes = live_slots * sizeof(DfpnEntry);
    storage->solved_bytes = solved_slots * sizeof(DfpnSolvedEntry);
    if (scratch_prefix == NULL || scratch_prefix[0] == '\0') {
        storage->live = calloc(live_slots, sizeof(DfpnEntry));
        storage->solved = calloc(solved_slots, sizeof(DfpnSolvedEntry));
        if (storage->live == NULL || storage->solved == NULL) {
            dfpn_hash_storage_destroy(storage);
            return false;
        }
        return true;
    }

    storage->disk_backed = true;
    char *live_path = dfpn_hash_scratch_path(scratch_prefix, "live");
    char *solved_path = dfpn_hash_scratch_path(scratch_prefix, "solved");
    bool ok = live_path != NULL && solved_path != NULL;
    if (ok) {
        ok = dfpn_map_scratch_file(
            live_path,
            storage->live_bytes,
            &storage->live
#if defined(_WIN32)
            , &storage->live_file
#endif
        );
    }
    if (ok) {
        ok = dfpn_map_scratch_file(
            solved_path,
            storage->solved_bytes,
            &storage->solved
#if defined(_WIN32)
            , &storage->solved_file
#endif
        );
    }
    if (ok) {
        printf("DFPN disk-backed live hash: %s (%zu bytes)\n",
            live_path, storage->live_bytes);
        printf("DFPN disk-backed solved hash: %s (%zu bytes)\n",
            solved_path, storage->solved_bytes);
        fflush(stdout);
    }
    free(live_path);
    free(solved_path);
    if (!ok) {
        dfpn_hash_storage_destroy(storage);
        return false;
    }
    return true;
}

static int command_dfpn(
    const char *path,
    const char *position_text,
    int reversible_plies,
    const char *root_text,
    uint64_t expansion_budget,
    size_t live_hash_slots,
    size_t solved_hash_slots,
    int tb3_hash_power,
    const char *checkpoint_path,
    const char *seed_checkpoint,
    const char *frontier_path,
    const char *second_frontier_path,
    const char *certificate_path,
    bool certificate_all_choices
) {
    if (
        live_hash_slots == 0 ||
        live_hash_slots > SIZE_MAX / sizeof(DfpnEntry) ||
        solved_hash_slots == 0 ||
        solved_hash_slots > SIZE_MAX / sizeof(DfpnSolvedEntry)
    ) {
        fprintf(stderr, "invalid DFPN hash capacity\n");
        return 1;
    }
    if (live_hash_slots > SIZE_MAX - solved_hash_slots) {
        fprintf(stderr, "DFPN combined hash capacity overflows\n");
        return 1;
    }
    RankedTablebase tablebase;
    if (
        !read_tablebase(&tablebase, path) ||
        tablebase.signature_count != TB4_SIGNATURES
    ) {
        fprintf(stderr, "unable to read or verify %s\n", path);
        return 2;
    }
    Position position;
    uint8_t root_player;
    if (
        !parse_position(position_text, &position) ||
        !parse_player_text(root_text, &root_player)
    ) {
        fprintf(stderr, "invalid DFPN root position or player\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    if (
        reversible_plies < 0 ||
        reversible_plies > (int)tablebase.no_progress_plies
    ) {
        fprintf(stderr, "DFPN clock outside tablebase range\n");
        tablebase_destroy(&tablebase);
        return 1;
    }
    position.reversible_plies = (uint8_t)reversible_plies;
    CompactTablebase frontiers[2];
    memset(frontiers, 0, sizeof(frontiers));
    const char *frontier_paths[2] = {
        frontier_path,
        second_frontier_path
    };
    size_t frontier_count = 0;
    if (second_frontier_path != NULL && frontier_path == NULL) {
        fprintf(stderr, "six-piece frontier requires five-piece frontier\n");
        tablebase_destroy(&tablebase);
        return 2;
    }
    for (size_t index = 0; index < 2 && frontier_paths[index] != NULL; ++index) {
        if (
            !read_compact_tablebase(&frontiers[index], frontier_paths[index]) ||
            !compact_tablebase_has_complete_schema(
                &frontiers[index], (uint32_t)(5 + index)
            ) ||
            frontiers[index].no_progress_plies != tablebase.no_progress_plies
        ) {
            fprintf(
                stderr,
                "unable to read compatible %zu-piece frontier\n",
                index + 5
            );
            compact_tablebase_destroy(&frontiers[index]);
            destroy_dfpn_frontiers(frontiers, frontier_count);
            tablebase_destroy(&tablebase);
            return 2;
        }
        ++frontier_count;
    }
    int dependency = makhos_tb3_init(
        (int)tablebase.no_progress_plies, tb3_hash_power
    );
    if (dependency != 0) {
        fprintf(stderr, "unable to initialize three-piece dependency: %d\n", dependency);
        destroy_dfpn_frontiers(frontiers, frontier_count);
        tablebase_destroy(&tablebase);
        return 2;
    }
    DfpnContext context;
    memset(&context, 0, sizeof(context));
    context.tablebase = &tablebase;
    context.frontier_count = frontier_count;
    for (size_t index = 0; index < frontier_count; ++index) {
        context.frontiers[index] = &frontiers[index];
    }
    context.capacity = live_hash_slots;
    context.solved_capacity = solved_hash_slots;
    const char *scratch_prefix = getenv("MAKHOS_DFPN_HASH_BACKING");
    DfpnHashStorage hash_storage;
    bool hash_storage_ready = dfpn_hash_storage_init(
        &hash_storage,
        context.capacity,
        context.solved_capacity,
        scratch_prefix
    );
    context.entries = hash_storage_ready
        ? (DfpnEntry *)hash_storage.live
        : NULL;
    context.solved_entries = hash_storage_ready
        ? (DfpnSolvedEntry *)hash_storage.solved
        : NULL;
    context.generator = calloc(1, sizeof(*context.generator));
    context.expansion_budget = expansion_budget;
    context.next_progress_expansion = DFPN_SEARCH_PROGRESS_INTERVAL;
    context.root_player = root_player;
    if (
        context.entries == NULL ||
        context.solved_entries == NULL ||
        context.generator == NULL
    ) {
        fprintf(stderr, "unable to allocate DFPN workspace\n");
        dfpn_hash_storage_destroy(&hash_storage);
        free(context.generator);
        makhos_tb3_shutdown();
        destroy_dfpn_frontiers(frontiers, frontier_count);
        tablebase_destroy(&tablebase);
        return 2;
    }
    int checkpoint_loaded = 0;
    if (checkpoint_path != NULL) {
        checkpoint_loaded = read_dfpn_checkpoint(
            &context, position, checkpoint_path
        );
        if (checkpoint_loaded < 0) {
            fprintf(stderr, "invalid or incompatible DFPN checkpoint\n");
            dfpn_hash_storage_destroy(&hash_storage);
            free(context.generator);
            makhos_tb3_shutdown();
            destroy_dfpn_frontiers(frontiers, frontier_count);
            tablebase_destroy(&tablebase);
            return 2;
        }
    }
    if (checkpoint_loaded == 0 && seed_checkpoint != NULL) {
        int imported = dfpn_import_proof_checkpoint(
            &context, position, seed_checkpoint
        );
        if (imported <= 0) {
            fprintf(stderr, "unable to import DFPN proof checkpoint seed\n");
            dfpn_hash_storage_destroy(&hash_storage);
            free(context.generator);
            makhos_tb3_shutdown();
            destroy_dfpn_frontiers(frontiers, frontier_count);
            tablebase_destroy(&tablebase);
            return 2;
        }
    }
    printf(
        "DFPN hash slots live/resolved: %zu/%zu\n",
        context.capacity,
        context.solved_capacity
    );
    fflush(stdout);
    context.search_started = clock();
    clock_t started = context.search_started;
    bool completed = dfpn_search(
        &context,
        position,
        DFPN_INFINITY,
        DFPN_INFINITY,
        0
    );
    double elapsed = (double)(clock() - started) / CLOCKS_PER_SEC;
    uint32_t root_proof_number = 1;
    uint32_t root_disproof_number = 1;
    bool root_found = dfpn_lookup_numbers(
        &context,
        position,
        false,
        &root_proof_number,
        &root_disproof_number
    );
    printf("expansions: %" PRIu64 "\n", context.expansions);
    printf(
        "stored states: %zu (live %zu, resolved %zu)\n",
        context.count + context.solved_count,
        context.count,
        context.solved_count
    );
    printf("cache hits: %" PRIu64 "\n", context.cache_hits);
    printf("tablebase hits: %" PRIu64 "\n", context.tablebase_hits);
    printf("maximum depth: %zu\n", context.maximum_depth);
    dfpn_print_material_profile(
        "six-piece expansions", context.six_piece_expansions
    );
    dfpn_print_material_profile(
        "compact frontier hits", context.frontier_hits_by_signature
    );
    printf("time: %.3f seconds\n", elapsed);
    if (root_found) {
        printf(
            "root proof/disproof: %u/%u\n",
            root_proof_number,
            root_disproof_number
        );
    }
    dfpn_print_root_moves(&context, position);
    int result;
    if (root_found && root_proof_number == 0) {
        printf("result: PROVEN NON-LOSS\n");
        result = 0;
    } else if (root_found && root_disproof_number == 0) {
        printf("result: FORCED LOSS\n");
        result = 1;
    } else {
        printf("result: UNKNOWN\n");
        if (!completed) {
            printf(
                "reason: %s\n",
                context.failure_reason != NULL
                    ? context.failure_reason
                    : "DFPN search interrupted"
            );
        }
        result = 3;
    }
    if (
        checkpoint_path != NULL &&
        !write_dfpn_checkpoint(&context, position, checkpoint_path)
    ) {
        fprintf(stderr, "failed to write DFPN checkpoint\n");
        result = 2;
    }
    if (
        result == 0 &&
        certificate_path != NULL &&
        !write_dfpn_certificate(
            &context,
            position,
            certificate_path,
            certificate_all_choices
        )
    ) {
        result = 2;
    }
    dfpn_hash_storage_destroy(&hash_storage);
    free(context.generator);
    makhos_tb3_shutdown();
    destroy_dfpn_frontiers(frontiers, frontier_count);
    tablebase_destroy(&tablebase);
    return result;
}

static bool hardening_file_exists(const char *path) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return false;
    }
    fclose(file);
    return true;
}

static bool hardening_write_text(const char *path, const char *text) {
    FILE *file = fopen(path, "wb");
    if (file == NULL) {
        return false;
    }
    size_t length = strlen(text);
    bool ok = fwrite(text, 1, length, file) == length;
    if (fclose(file) != 0) {
        ok = false;
    }
    return ok;
}

static bool hardening_file_equals(const char *path, const char *text) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return false;
    }
    size_t length = strlen(text);
    char buffer[32];
    bool ok = length < sizeof(buffer) &&
        fread(buffer, 1, length, file) == length &&
        fgetc(file) == EOF &&
        memcmp(buffer, text, length) == 0;
    fclose(file);
    return ok;
}

static bool hardening_bytes_are_zero(const void *data, size_t length) {
    const uint8_t *bytes = data;
    for (size_t index = 0; index < length; ++index) {
        if (bytes[index] != 0) return false;
    }
    return true;
}

static int command_verify_dfpn_disk_backing(const char *scratch_prefix) {
    const size_t live_slots = 65536;
    const size_t solved_slots = 65536;
    char *live_path = dfpn_hash_scratch_path(scratch_prefix, "live");
    char *solved_path = dfpn_hash_scratch_path(scratch_prefix, "solved");
    if (live_path == NULL || solved_path == NULL) {
        free(live_path);
        free(solved_path);
        return 2;
    }
    if (
        hardening_file_exists(live_path) ||
        hardening_file_exists(solved_path)
    ) {
        fprintf(stderr, "DFPN disk-backing scratch files already exist\n");
        free(live_path);
        free(solved_path);
        return 1;
    }

    DfpnHashStorage storage;
    bool ok = dfpn_hash_storage_init(
        &storage, live_slots, solved_slots, scratch_prefix
    );
    if (ok) {
        ok = storage.disk_backed &&
            storage.live != NULL &&
            storage.solved != NULL &&
            storage.live_bytes == live_slots * sizeof(DfpnEntry) &&
            storage.solved_bytes == solved_slots * sizeof(DfpnSolvedEntry) &&
            hardening_bytes_are_zero(storage.live, storage.live_bytes) &&
            hardening_bytes_are_zero(storage.solved, storage.solved_bytes);
    }
    if (ok) {
        uint8_t *live = storage.live;
        uint8_t *solved = storage.solved;
        live[0] = UINT8_C(0x5a);
        live[storage.live_bytes - 1] = UINT8_C(0xa5);
        solved[0] = UINT8_C(0x3c);
        solved[storage.solved_bytes - 1] = UINT8_C(0xc3);
        ok = live[0] == UINT8_C(0x5a) &&
            live[storage.live_bytes - 1] == UINT8_C(0xa5) &&
            solved[0] == UINT8_C(0x3c) &&
            solved[storage.solved_bytes - 1] == UINT8_C(0xc3);
    }
    dfpn_hash_storage_destroy(&storage);
    if (
        hardening_file_exists(live_path) ||
        hardening_file_exists(solved_path)
    ) {
        ok = false;
    }

    /* A partial initialization failure must clean up the live mapping. */
    if (ok) {
        ok = hardening_write_text(solved_path, "occupied") &&
            !dfpn_hash_storage_init(
                &storage, live_slots, solved_slots, scratch_prefix
            ) &&
            !hardening_file_exists(live_path) &&
            hardening_file_equals(solved_path, "occupied");
    }
    dfpn_hash_storage_destroy(&storage);
    remove(live_path);
    remove(solved_path);
    free(live_path);
    free(solved_path);
    if (!ok) {
        fprintf(stderr, "DFPN disk-backing verification failed\n");
        return 2;
    }
    printf("DFPN disk-backed zero initialization: PASS\n");
    printf("DFPN disk-backed boundary writes: PASS\n");
    printf("DFPN disk-backed cleanup and partial-failure cleanup: PASS\n");
    return 0;
}

static int command_verify_native_hardening(const char *scratch_path) {
    const uint32_t pieces[] = {4, 5, 6};
    const uint32_t expected_counts[] = {25, 44, 70};
    for (size_t piece_index = 0; piece_index < 3; ++piece_index) {
        uint8_t counts[COMPACT_MAX_SIGNATURES][4] = {{0}};
        uint32_t count = canonical_signature_counts(
            pieces[piece_index], counts
        );
        if (count != expected_counts[piece_index]) {
            fprintf(stderr, "canonical signature count mismatch\n");
            return 2;
        }
        for (uint32_t index = 0; index < count; ++index) {
            uint32_t black = counts[index][TYPE_BM] +
                counts[index][TYPE_BK];
            uint32_t red = counts[index][TYPE_RM] +
                counts[index][TYPE_RK];
            uint32_t total = black + red;
            if (
                total != pieces[piece_index] ||
                black == 0 || red == 0 ||
                (index != 0 && compare_signature_count_vectors(
                    counts[index - 1], counts[index]
                ) >= 0)
            ) {
                fprintf(stderr, "canonical signature order mismatch\n");
                return 2;
            }
        }
    }

    Position position;
    if (
        parse_position("B:BM1:RK5", &position) ||
        parse_position("R:RM29:BK5", &position) ||
        !parse_position("B:BM5:RK1", &position) ||
        !parse_position("R:RM28:BK32", &position)
    ) {
        fprintf(stderr, "promotion-row parser verification failed\n");
        return 2;
    }

    size_t path_length = strlen(scratch_path);
    char *temporary_path = malloc(path_length + 9);
    char *missing_path = malloc(path_length + 13);
    if (temporary_path == NULL || missing_path == NULL) {
        free(temporary_path);
        free(missing_path);
        return 2;
    }
    snprintf(temporary_path, path_length + 9, "%s.tmp", scratch_path);
    snprintf(missing_path, path_length + 13, "%s.missing", scratch_path);
    if (
        hardening_file_exists(scratch_path) ||
        hardening_file_exists(temporary_path) ||
        hardening_file_exists(missing_path)
    ) {
        fprintf(stderr, "hardening scratch paths must not already exist\n");
        free(temporary_path);
        free(missing_path);
        return 1;
    }

    bool ok = hardening_write_text(scratch_path, "old-checkpoint") &&
        hardening_write_text(temporary_path, "new-checkpoint") &&
        makhos_replace_file_atomically(temporary_path, scratch_path) &&
        hardening_file_equals(scratch_path, "new-checkpoint") &&
        !hardening_file_exists(temporary_path);
    if (ok) {
        /* A failed attempt must leave the previously committed output intact. */
        ok = !makhos_replace_file_atomically(missing_path, scratch_path) &&
            hardening_file_equals(scratch_path, "new-checkpoint");
    }
    remove(temporary_path);
    remove(scratch_path);
    free(temporary_path);
    free(missing_path);
    if (!ok) {
        fprintf(stderr, "atomic replacement verification failed\n");
        return 2;
    }
    printf("canonical signature counts: 25/44/70\n");
    printf("promotion-row parsing: PASS\n");
    printf("atomic checkpoint replacement: PASS\n");
    return 0;
}

static int command_verify_dfpn_codec(void) {
    Position position;
    memset(&position, 0, sizeof(position));
    position.red = UINT32_C(0x000000ff);
    position.black = UINT32_C(0xff000000);
    uint32_t fixed_occupancy = occupied(position);
    for (uint32_t flags = 0; flags <= UINT16_MAX; ++flags) {
        position.kings = dfpn_expand_kings(
            position.red, position.black, (uint16_t)flags
        );
        if (dfpn_compress_kings(position) != (uint16_t)flags) {
            fprintf(stderr, "DFPN king codec mismatch at %u\n", flags);
            return 2;
        }
    }
    for (uint32_t flags = 0; flags <= UINT16_MAX; ++flags) {
        dfpn_expand_colours(
            fixed_occupancy,
            (uint16_t)flags,
            &position.red,
            &position.black
        );
        if (
            occupied(position) != fixed_occupancy ||
            (position.red & position.black) != 0 ||
            dfpn_compress_black(position) != (uint16_t)flags
        ) {
            fprintf(stderr, "DFPN colour codec mismatch at %u\n", flags);
            return 2;
        }
    }
    for (int turn = RED; turn <= BLACK; ++turn) {
        position.turn = (uint8_t)turn;
        for (int clock = 0; clock <= 80; ++clock) {
            position.reversible_plies = (uint8_t)clock;
            uint8_t meta = dfpn_position_meta(position);
            if (
                meta == 0 ||
                dfpn_meta_turn(meta) != position.turn ||
                dfpn_meta_clock(meta) != position.reversible_plies
            ) {
                fprintf(stderr, "DFPN metadata codec mismatch\n");
                return 2;
            }
        }
    }
    uint32_t previous = 0;
    for (uint32_t value = 0; value <= UINT32_C(1000000); ++value) {
        uint32_t decoded = dfpn_number_decode(dfpn_number_encode(value));
        if (
            decoded > value ||
            decoded < previous ||
            (value != 0 && decoded == 0) ||
            decoded >= DFPN_INFINITY
        ) {
            fprintf(stderr, "DFPN number codec mismatch at %u\n", value);
            return 2;
        }
        previous = decoded;
    }
    const uint32_t large_values[] = {
        UINT32_C(1000001), UINT32_C(10000000), UINT32_C(100000000),
        DFPN_INFINITY - 1
    };
    for (size_t index = 0;
         index < sizeof(large_values) / sizeof(large_values[0]);
         ++index) {
        uint32_t value = large_values[index];
        uint32_t decoded = dfpn_number_decode(dfpn_number_encode(value));
        if (decoded == 0 || decoded > value || decoded >= DFPN_INFINITY) {
            fprintf(stderr, "DFPN large-number codec mismatch at %u\n", value);
            return 2;
        }
    }
    if (
        dfpn_number_decode(dfpn_number_encode(DFPN_INFINITY)) !=
        DFPN_INFINITY
    ) {
        fprintf(stderr, "DFPN infinity codec mismatch\n");
        return 2;
    }
    if (
        !dfpn_below_threshold(999, 1000, 1) ||
        dfpn_below_threshold(1000, 1000, 1) ||
        !dfpn_below_threshold(DFPN_INFINITY, DFPN_INFINITY, 1) ||
        dfpn_below_threshold(DFPN_INFINITY, DFPN_INFINITY, 0)
    ) {
        fprintf(stderr, "DFPN saturated-threshold classification mismatch\n");
        return 2;
    }
    DfpnChild saturated_children[2];
    memset(saturated_children, 0, sizeof(saturated_children));
    saturated_children[0].proof_number = DFPN_INFINITY;
    saturated_children[0].disproof_number = 0;
    saturated_children[1].proof_number = DFPN_INFINITY;
    saturated_children[1].disproof_number = 7;
    uint32_t saturated_best;
    uint32_t saturated_second;
    if (
        dfpn_select_child(
            saturated_children,
            2,
            true,
            &saturated_best,
            &saturated_second
        ) != 1 ||
        saturated_best != DFPN_INFINITY ||
        saturated_second != DFPN_INFINITY
    ) {
        fprintf(stderr, "DFPN saturated OR selection mismatch\n");
        return 2;
    }
    saturated_children[0].proof_number = 0;
    saturated_children[0].disproof_number = DFPN_INFINITY;
    saturated_children[1].proof_number = 7;
    saturated_children[1].disproof_number = DFPN_INFINITY;
    if (dfpn_select_child(
            saturated_children,
            2,
            false,
            &saturated_best,
            &saturated_second
        ) != 1) {
        fprintf(stderr, "DFPN saturated AND selection mismatch\n");
        return 2;
    }
    DfpnEntry marker_entry;
    memset(&marker_entry, 0, sizeof(marker_entry));
    dfpn_entry_mark_unexpanded(&marker_entry);
    if (
        dfpn_entry_is_expanded(&marker_entry) ||
        dfpn_entry_proof(&marker_entry) != 1 ||
        dfpn_entry_disproof(&marker_entry) != 1
    ) {
        fprintf(stderr, "DFPN unexpanded marker mismatch\n");
        return 2;
    }
    dfpn_entry_set_numbers(&marker_entry, 1, 1);
    if (!dfpn_entry_is_expanded(&marker_entry)) {
        fprintf(stderr, "DFPN expanded marker transition mismatch\n");
        return 2;
    }
    printf("DFPN king flags checked: 65536\n");
    printf("DFPN colour flags checked: 65536\n");
    printf("DFPN finite numbers checked: 1000005\n");
    printf("DFPN live/solved entry bytes: %zu/%zu\n",
        sizeof(DfpnEntry), sizeof(DfpnSolvedEntry));
    printf("DFPN codec verification: PASS\n");
    return 0;
}

static int command_verify_compact_reader(
    const char *path,
    uint32_t expected_piece_count
) {
    CompactTablebase mapped;
    CompactTablebase buffered;
    memset(&mapped, 0, sizeof(mapped));
    memset(&buffered, 0, sizeof(buffered));
    bool ok = read_compact_tablebase_mode(&mapped, path, true) &&
        mapped.mapped_backing &&
        read_compact_tablebase_mode(&buffered, path, false) &&
        !buffered.mapped_backing &&
        mapped.piece_count == expected_piece_count &&
        mapped.piece_count == buffered.piece_count &&
        mapped.no_progress_plies == buffered.no_progress_plies &&
        mapped.signature_count == buffered.signature_count &&
        mapped.total_positions == buffered.total_positions &&
        mapped.total_states == buffered.total_states &&
        mapped.checksum == buffered.checksum;
    uintptr_t mapped_start = (uintptr_t)mapped.mapped_base;
    uintptr_t mapped_end = mapped_start + mapped.mapped_length;
    if (mapped_end < mapped_start) {
        ok = false;
    }
    for (uint32_t index = 0;
         ok && index < mapped.signature_count;
         ++index) {
        const CompactSignature *left = &mapped.signatures[index];
        const CompactSignature *right = &buffered.signatures[index];
        uintptr_t payload_start = (uintptr_t)left->thresholds;
        if (
            memcmp(left->count, right->count, 4) != 0 ||
            left->boards != right->boards ||
            left->byte_count != right->byte_count ||
            left->byte_count > (uint64_t)SIZE_MAX ||
            payload_start < mapped_start || payload_start > mapped_end ||
            (size_t)(mapped_end - payload_start) <
                (size_t)left->byte_count ||
            memcmp(
                left->thresholds,
                right->thresholds,
                (size_t)left->byte_count
            ) != 0
        ) {
            ok = false;
        }
    }
    size_t mapped_length = mapped.mapped_length;
    compact_tablebase_destroy(&mapped);
    compact_tablebase_destroy(&mapped);
    compact_tablebase_destroy(&buffered);
    compact_tablebase_destroy(&buffered);
    if (!ok) {
        fprintf(stderr, "compact mapped/buffered reader mismatch\n");
        return 2;
    }
    printf("compact mapped bytes: %zu\n", mapped_length);
    printf("compact buffered fallback equivalence: PASS\n");
    printf("compact reader lifetime cleanup: PASS\n");
    return 0;
}

static bool dfpn_collect_wraparound_collisions(
    Position output[3],
    size_t capacity,
    uint8_t turn,
    uint8_t reversible_plies
) {
    size_t found = 0;
    for (unsigned red_square = 0; red_square < 32 && found < 3;
         ++red_square) {
        for (unsigned black_square = 0;
             black_square < 32 && found < 3;
             ++black_square) {
            if (red_square == black_square) {
                continue;
            }
            Position position;
            memset(&position, 0, sizeof(position));
            position.red = UINT32_C(1) << red_square;
            position.black = UINT32_C(1) << black_square;
            position.kings = position.red | position.black;
            position.turn = turn;
            position.reversible_plies = reversible_plies;
            if (
                dfpn_hash_initial_slot(position, capacity) == capacity - 1
            ) {
                output[found++] = position;
            }
        }
    }
    return found == 3;
}

static int command_verify_dfpn_capacity(const char *scratch_path) {
    size_t parsed_live_slots = 0;
    size_t parsed_solved_slots = 0;
    char too_many_live_slots[64];
    char too_many_solved_slots[64];
    uintmax_t maximum_live_slots =
        (uintmax_t)(SIZE_MAX / sizeof(DfpnEntry));
    uintmax_t maximum_solved_slots =
        (uintmax_t)(SIZE_MAX / sizeof(DfpnSolvedEntry));
    snprintf(
        too_many_live_slots,
        sizeof(too_many_live_slots),
        "%" PRIuMAX,
        maximum_live_slots + 1
    );
    snprintf(
        too_many_solved_slots,
        sizeof(too_many_solved_slots),
        "%" PRIuMAX,
        maximum_solved_slots + 1
    );
    if (
        !parse_dfpn_live_slots("603979776", &parsed_live_slots) ||
        parsed_live_slots != (size_t)603979776 ||
        !parse_dfpn_live_slots("671088640", &parsed_live_slots) ||
        parsed_live_slots != (size_t)671088640 ||
        !parse_dfpn_solved_slots("160000000", &parsed_solved_slots) ||
        parsed_solved_slots != (size_t)160000000 ||
        parse_dfpn_live_slots("65535", &parsed_live_slots) ||
        parse_dfpn_solved_slots("65535", &parsed_solved_slots) ||
        parse_dfpn_live_slots(
            "18446744073709551616", &parsed_live_slots
        ) ||
        parse_dfpn_solved_slots(
            "18446744073709551616", &parsed_solved_slots
        ) ||
        parse_dfpn_live_slots(
            too_many_live_slots, &parsed_live_slots
        ) ||
        parse_dfpn_solved_slots(
            too_many_solved_slots, &parsed_solved_slots
        )
    ) {
        fprintf(stderr, "DFPN slot parser verification failed\n");
        return 2;
    }
    size_t live_capacity = 0;
    size_t solved_capacity = 0;
    if (
        !parse_dfpn_hash_capacities(
            "29", "28", false, false,
            &live_capacity, &solved_capacity
        ) ||
        live_capacity != ((size_t)1 << 29) ||
        solved_capacity != ((size_t)1 << 28) ||
        !parse_dfpn_hash_capacities(
            "603979776", "28", true, false,
            &live_capacity, &solved_capacity
        ) ||
        live_capacity != (size_t)603979776 ||
        solved_capacity != ((size_t)1 << 28) ||
        !parse_dfpn_hash_capacities(
            "603979776", "160000000", true, true,
            &live_capacity, &solved_capacity
        ) ||
        live_capacity != (size_t)603979776 ||
        solved_capacity != (size_t)160000000
    ) {
        fprintf(stderr, "DFPN capacity mode compatibility failed\n");
        return 2;
    }
    if (
        dfpn_hash_load_limit(100) != 85 ||
        !dfpn_hash_below_load_guard(84, 100) ||
        dfpn_hash_below_load_guard(85, 100) ||
        !dfpn_hash_can_insert(83, 100) ||
        dfpn_hash_can_insert(84, 100) ||
        dfpn_hash_load_limit(SIZE_MAX) < SIZE_MAX / 2 ||
        dfpn_hash_load_limit(SIZE_MAX) >= SIZE_MAX
    ) {
        fprintf(stderr, "DFPN 85%% load guard verification failed\n");
        return 2;
    }

    Position collisions[3];
    Position solved_collisions[3];
    if (
        !dfpn_collect_wraparound_collisions(
            collisions, 17, BLACK, 0
        ) ||
        !dfpn_collect_wraparound_collisions(
            solved_collisions, 17, RED, 1
        )
    ) {
        fprintf(stderr, "unable to construct DFPN collision fixture\n");
        return 2;
    }

    RankedTablebase tablebase;
    memset(&tablebase, 0, sizeof(tablebase));
    tablebase.no_progress_plies = 80;
    tablebase.checksum = UINT64_C(0x5a17d9c341e20b6f);

    DfpnEntry source_entries[16];
    DfpnSolvedEntry source_solved[16];
    memset(source_entries, 0, sizeof(source_entries));
    memset(source_solved, 0, sizeof(source_solved));
    DfpnContext source;
    memset(&source, 0, sizeof(source));
    source.tablebase = &tablebase;
    source.entries = source_entries;
    source.capacity = 16;
    source.solved_entries = source_solved;
    source.solved_capacity = 16;
    source.root_player = BLACK;
    for (size_t index = 0; index < 3; ++index) {
        DfpnEntry *entry = dfpn_find_entry(
            &source, collisions[index], true
        );
        if (entry == NULL) {
            fprintf(stderr, "unable to create DFPN collision fixture\n");
            return 2;
        }
        dfpn_entry_set_numbers(
            entry,
            (uint32_t)(index + 2),
            (uint32_t)(index + 7)
        );
    }
    Position unexpanded = collisions[0];
    ++unexpanded.reversible_plies;
    DfpnEntry *unexpanded_entry = dfpn_find_entry(
        &source, unexpanded, true
    );
    if (
        unexpanded_entry == NULL ||
        dfpn_entry_is_expanded(unexpanded_entry) ||
        dfpn_entry_proof(unexpanded_entry) != 1 ||
        dfpn_entry_disproof(unexpanded_entry) != 1
    ) {
        fprintf(stderr, "unable to create DFPN unexpanded fixture\n");
        return 2;
    }
    for (size_t index = 0; index < 3; ++index) {
        if (dfpn_find_solved(
                &source,
                solved_collisions[index],
                true,
                index % 2 == 0
            ) == NULL) {
            fprintf(stderr, "unable to create DFPN solved fixture\n");
            return 2;
        }
    }

    size_t scratch_length = strlen(scratch_path);
    if (scratch_length > SIZE_MAX - 10) {
        fprintf(stderr, "DFPN checkpoint scratch path is too long\n");
        return 1;
    }
    char *temporary_path = malloc(scratch_length + 5);
    char *retarget_path = malloc(scratch_length + 10);
    if (temporary_path == NULL || retarget_path == NULL) {
        free(temporary_path);
        free(retarget_path);
        return 2;
    }
    snprintf(temporary_path, scratch_length + 5, "%s.tmp", scratch_path);
    snprintf(retarget_path, scratch_length + 10, "%s.retarget", scratch_path);
    if (
        hardening_file_exists(scratch_path) ||
        hardening_file_exists(temporary_path) ||
        hardening_file_exists(retarget_path)
    ) {
        fprintf(stderr, "DFPN checkpoint scratch paths must not exist\n");
        free(temporary_path);
        free(retarget_path);
        return 1;
    }

    DfpnEntry target_entries[17];
    DfpnSolvedEntry target_solved[17];
    memset(target_entries, 0, sizeof(target_entries));
    memset(target_solved, 0, sizeof(target_solved));
    DfpnContext target;
    memset(&target, 0, sizeof(target));
    target.tablebase = &tablebase;
    target.entries = target_entries;
    target.capacity = 17;
    target.solved_entries = target_solved;
    target.solved_capacity = 17;
    target.root_player = BLACK;

    bool ok = write_dfpn_checkpoint(
        &source, collisions[0], scratch_path
    );
    if (!ok) {
        fprintf(stderr, "DFPN capacity fixture checkpoint write failed\n");
    }
    if (ok) {
        int loaded = read_dfpn_checkpoint(
            &target, collisions[0], scratch_path
        );
        ok = loaded == 1;
        if (!ok) {
            fprintf(
                stderr,
                "DFPN capacity fixture checkpoint reload failed: %d\n",
                loaded
            );
        }
    }
    bool occupied_slots[17] = {false};
    for (size_t index = 0; ok && index < 3; ++index) {
        DfpnEntry *entry = dfpn_find_entry(
            &target, collisions[index], false
        );
        if (
            entry == NULL || !dfpn_entry_is_expanded(entry) ||
            dfpn_entry_proof(entry) != (uint32_t)(index + 2) ||
            dfpn_entry_disproof(entry) != (uint32_t)(index + 7)
        ) {
            fprintf(
                stderr,
                "DFPN capacity fixture live record mismatch: %zu\n",
                index
            );
            ok = false;
            break;
        }
        occupied_slots[(size_t)(entry - target_entries)] = true;
    }
    if (
        ok &&
        (!occupied_slots[16] || !occupied_slots[0] || !occupied_slots[1])
    ) {
        fprintf(
            stderr,
            "DFPN capacity fixture wrap mismatch: %d/%d/%d\n",
            occupied_slots[16], occupied_slots[0], occupied_slots[1]
        );
        ok = false;
    }
    if (
        ok &&
        (dfpn_find_entry(&target, unexpanded, false) != NULL ||
         target.count != 3)
    ) {
        fprintf(stderr, "DFPN unexpanded checkpoint omission mismatch\n");
        ok = false;
    }
    bool solved_occupied_slots[17] = {false};
    for (size_t index = 0; ok && index < 3; ++index) {
        DfpnSolvedEntry *loaded = dfpn_find_solved(
            &target, solved_collisions[index], false, false
        );
        if (
            loaded == NULL ||
            loaded->proven != (uint8_t)(index % 2 == 0 ? 1 : 0)
        ) {
            fprintf(
                stderr,
                "DFPN capacity fixture solved record mismatch: %zu\n",
                index
            );
            ok = false;
            break;
        }
        solved_occupied_slots[
            (size_t)(loaded - target_solved)
        ] = true;
    }
    if (
        ok &&
        (!solved_occupied_slots[16] ||
         !solved_occupied_slots[0] ||
         !solved_occupied_slots[1])
    ) {
        fprintf(stderr, "DFPN solved capacity fixture wrap mismatch\n");
        ok = false;
    }
    if (
        ok &&
        (target.count != 3 || target.solved_count != 3 || target.failed)
    ) {
        fprintf(
            stderr,
            "DFPN capacity fixture counts mismatch: %zu/%zu/%d\n",
            target.count, target.solved_count, target.failed
        );
        ok = false;
    }

    Position retargeted_root = collisions[2];
    ++retargeted_root.reversible_plies;
    DfpnEntry retarget_entries[17];
    DfpnSolvedEntry retarget_solved[17];
    memset(retarget_entries, 0, sizeof(retarget_entries));
    memset(retarget_solved, 0, sizeof(retarget_solved));
    DfpnContext retarget;
    memset(&retarget, 0, sizeof(retarget));
    retarget.tablebase = &tablebase;
    retarget.entries = retarget_entries;
    retarget.capacity = 17;
    retarget.solved_entries = retarget_solved;
    retarget.solved_capacity = 17;
    retarget.root_player = BLACK;
    if (ok) {
        ok = compact_dfpn_checkpoint(
            scratch_path,
            retarget_path,
            true,
            false,
            0,
            false,
            0,
            false,
            0,
            true,
            retargeted_root
        ) == 0;
    }
    if (ok) {
        ok = read_dfpn_checkpoint(
            &retarget, retargeted_root, retarget_path
        ) == 1;
    }
    if (
        ok &&
        (retarget.count != 0 || retarget.solved_count != 3 ||
         retarget.failed ||
         read_dfpn_checkpoint(&retarget, collisions[0], retarget_path) != -1)
    ) {
        fprintf(stderr, "DFPN solved-only retarget fixture mismatch\n");
        ok = false;
    }

    DfpnEntry guard_entries[100];
    memset(guard_entries, 0, sizeof(guard_entries));
    DfpnContext guard;
    memset(&guard, 0, sizeof(guard));
    guard.entries = guard_entries;
    guard.capacity = 100;
    guard.count = 84;
    if (
        dfpn_find_entry(&guard, collisions[0], true) != NULL ||
        !guard.failed ||
        guard.failure_reason == NULL
    ) {
        fprintf(stderr, "DFPN capacity fixture load guard mismatch\n");
        ok = false;
    }

    DfpnSolvedEntry solved_guard_entries[100];
    memset(solved_guard_entries, 0, sizeof(solved_guard_entries));
    DfpnContext solved_guard;
    memset(&solved_guard, 0, sizeof(solved_guard));
    solved_guard.solved_entries = solved_guard_entries;
    solved_guard.solved_capacity = 100;
    DfpnSolvedEntry *existing_solved = dfpn_find_solved(
        &solved_guard, solved_collisions[0], true, true
    );
    solved_guard.solved_count = 84;
    if (
        existing_solved == NULL ||
        dfpn_find_solved(
            &solved_guard, solved_collisions[0], false, false
        ) != existing_solved ||
        dfpn_find_solved(
            &solved_guard, solved_collisions[1], true, false
        ) != NULL ||
        !solved_guard.failed || solved_guard.failure_reason == NULL
    ) {
        fprintf(stderr, "DFPN solved load guard mismatch\n");
        ok = false;
    }

    DfpnSolvedEntry conflict_entries[17];
    memset(conflict_entries, 0, sizeof(conflict_entries));
    DfpnContext conflict;
    memset(&conflict, 0, sizeof(conflict));
    conflict.solved_entries = conflict_entries;
    conflict.solved_capacity = 17;
    if (
        dfpn_find_solved(
            &conflict, solved_collisions[0], true, true
        ) == NULL ||
        dfpn_find_solved(
            &conflict, solved_collisions[0], true, false
        ) != NULL ||
        !conflict.failed || conflict.failure_reason == NULL
    ) {
        fprintf(stderr, "DFPN solved conflict guard mismatch\n");
        ok = false;
    }

    DfpnContext zero_solved;
    memset(&zero_solved, 0, sizeof(zero_solved));
    if (
        dfpn_find_solved(
            &zero_solved, solved_collisions[0], false, false
        ) != NULL ||
        !zero_solved.failed || zero_solved.failure_reason == NULL
    ) {
        fprintf(stderr, "DFPN zero solved-capacity guard mismatch\n");
        ok = false;
    }

    remove(temporary_path);
    remove(scratch_path);
    remove(retarget_path);
    free(temporary_path);
    free(retarget_path);
    if (!ok) {
        fprintf(stderr, "DFPN capacity verification failed\n");
        return 2;
    }
    printf("DFPN explicit live/solved slot parsers: PASS\n");
    printf("DFPN legacy/live-only/full slot modes: PASS\n");
    printf("DFPN non-power-of-two live/solved probing: PASS\n");
    printf("DFPN live/solved 85%% load guards: PASS\n");
    printf("DFPN v2 dual-table power-to-non-power reload: PASS\n");
    printf("DFPN solved-only root retarget: PASS\n");
    return 0;
}

#ifndef MAKHOS_TB4_NO_MAIN
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
    if (argc == 4 && strcmp(argv[1], "verify-compact-reader") == 0) {
        int piece_count;
        if (!parse_bounded_int(argv[3], 4, 6, &piece_count)) {
            fprintf(stderr, "invalid compact piece count\n");
            return 1;
        }
        return command_verify_compact_reader(
            argv[2], (uint32_t)piece_count
        );
    }
    if (argc == 3 && strcmp(argv[1], "verify-dfpn-capacity") == 0) {
        return command_verify_dfpn_capacity(argv[2]);
    }
    if (argc == 4 && strcmp(argv[1], "compact-dfpn") == 0) {
        return compact_dfpn_checkpoint(
            argv[2], argv[3], false, false, 0, false, 0, false, 0,
            false, (Position){0}
        );
    }
    if (argc == 5 && strcmp(argv[1], "build") == 0) {
        int no_progress;
        int hash_power;
        if (
            !parse_bounded_int(argv[2], 1, 200, &no_progress) ||
            !parse_bounded_int(argv[3], 16, 28, &hash_power)
        ) {
            fprintf(stderr, "build requires NO_PROGRESS 1..200 and HASH_POWER 16..28\n");
            return 1;
        }
        return command_build(no_progress, hash_power, argv[4]);
    }
    if (argc == 5 && strcmp(argv[1], "probe") == 0) {
        int clock;
        if (!parse_bounded_int(argv[4], 0, 200, &clock)) {
            fprintf(stderr, "invalid clock\n");
            return 1;
        }
        return command_probe(argv[2], argv[3], clock);
    }
    if (argc == 4 && strcmp(argv[1], "verify") == 0) {
        int clock;
        if (!parse_bounded_int(argv[3], 0, 200, &clock)) {
            fprintf(stderr, "invalid clock\n");
            return 1;
        }
        return command_verify(argv[2], clock);
    }
    if (argc == 3 && strcmp(argv[1], "verify-monotonic") == 0) {
        return command_verify_monotonic(argv[2]);
    }
    if (argc == 4 && strcmp(argv[1], "compress") == 0) {
        return command_compress(argv[2], argv[3]);
    }
    if (argc == 4 && strcmp(argv[1], "compare-compact") == 0) {
        return command_compare_compact(argv[2], argv[3]);
    }
    if ((argc >= 8 && argc <= 10) && strcmp(argv[1], "prove") == 0) {
        uint64_t node_budget;
        int proof_hash_power;
        int tb3_hash_power;
        if (
            !parse_uint64_value(argv[5], &node_budget) ||
            node_budget < 1 ||
            !parse_bounded_int(argv[6], 16, 28, &proof_hash_power) ||
            !parse_bounded_int(argv[7], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid proof budget or hash power\n");
            return 1;
        }
        return command_prove(
            argv[2], argv[3], argv[4], node_budget,
            proof_hash_power, tb3_hash_power,
            argc >= 9 && strcmp(argv[8], "-") != 0 ? argv[8] : NULL,
            argc == 10 ? argv[9] : NULL
        );
    }
    if ((argc == 9 || argc == 10) && strcmp(argv[1], "survey") == 0) {
        uint64_t node_budget;
        int proof_hash_power;
        int tb3_hash_power;
        if (
            !parse_uint64_value(argv[6], &node_budget) ||
            node_budget < 1 ||
            !parse_bounded_int(argv[7], 16, 28, &proof_hash_power) ||
            !parse_bounded_int(argv[8], 16, 28, &tb3_hash_power)
        ) {
            fprintf(stderr, "invalid survey budget or hash power\n");
            return 1;
        }
        return command_survey(
            argv[2], argv[3], argv[4], argv[5],
            node_budget, proof_hash_power, tb3_hash_power,
            argc == 10 ? argv[9] : NULL
        );
    }
    if ((argc >= 8 && argc <= 12) && strcmp(argv[1], "dfpn") == 0) {
        uint64_t expansion_budget;
        int hash_power;
        int tb3_hash_power;
        int certificate_all_choices = 0;
        if (
            !parse_uint64_value(argv[5], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_bounded_int(argv[6], 16, 28, &hash_power) ||
            !parse_bounded_int(argv[7], 16, 28, &tb3_hash_power) ||
            (argc == 12 && !parse_bounded_int(
                argv[11], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN budget or hash power\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[3], 0, argv[4],
            expansion_budget, (size_t)1 << (hash_power - 1),
            (size_t)1 << (hash_power - 1), tb3_hash_power,
            argc >= 9 && strcmp(argv[8], "-") != 0 ? argv[8] : NULL,
            argc >= 10 && strcmp(argv[9], "-") != 0 ? argv[9] : NULL,
            NULL,
            NULL,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            certificate_all_choices != 0
        );
    }
    if ((argc >= 9 && argc <= 13) && strcmp(argv[1], "dfpn-clock") == 0) {
        int reversible_plies;
        uint64_t expansion_budget;
        int hash_power;
        int tb3_hash_power;
        int certificate_all_choices = 0;
        if (
            !parse_bounded_int(argv[4], 0, 200, &reversible_plies) ||
            !parse_uint64_value(argv[6], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_bounded_int(argv[7], 16, 28, &hash_power) ||
            !parse_bounded_int(argv[8], 16, 28, &tb3_hash_power) ||
            (argc == 13 && !parse_bounded_int(
                argv[12], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN clock, budget, or hash power\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[3], reversible_plies, argv[5],
            expansion_budget, (size_t)1 << (hash_power - 1),
            (size_t)1 << (hash_power - 1), tb3_hash_power,
            argc >= 10 && strcmp(argv[9], "-") != 0 ? argv[9] : NULL,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            NULL,
            NULL,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            certificate_all_choices != 0
        );
    }
    if (
        (argc >= 9 && argc <= 13) &&
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
            !parse_uint64_value(argv[5], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_dfpn_hash_capacities(
                argv[6], argv[7],
                explicit_live_slots, explicit_solved_slots,
                &live_hash_slots, &solved_hash_slots
            ) ||
            !parse_bounded_int(argv[8], 16, 28, &tb3_hash_power) ||
            (argc == 13 && !parse_bounded_int(
                argv[12], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN budget or hash capacity\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[3], 0, argv[4],
            expansion_budget, live_hash_slots,
            solved_hash_slots, tb3_hash_power,
            argc >= 10 && strcmp(argv[9], "-") != 0 ? argv[9] : NULL,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            NULL,
            NULL,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            certificate_all_choices != 0
        );
    }
    if (
        (argc >= 10 && argc <= 14) &&
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
            !parse_bounded_int(argv[4], 0, 200, &reversible_plies) ||
            !parse_uint64_value(argv[6], &expansion_budget) ||
            expansion_budget < 1 ||
            !parse_dfpn_hash_capacities(
                argv[7], argv[8],
                explicit_live_slots, explicit_solved_slots,
                &live_hash_slots, &solved_hash_slots
            ) ||
            !parse_bounded_int(argv[9], 16, 28, &tb3_hash_power) ||
            (argc == 14 && !parse_bounded_int(
                argv[13], 0, 1, &certificate_all_choices
            ))
        ) {
            fprintf(stderr, "invalid DFPN clock, budget, or hash capacity\n");
            return 1;
        }
        return command_dfpn(
            argv[2], argv[3], reversible_plies, argv[5],
            expansion_budget, live_hash_slots,
            solved_hash_slots, tb3_hash_power,
            argc >= 11 && strcmp(argv[10], "-") != 0 ? argv[10] : NULL,
            argc >= 12 && strcmp(argv[11], "-") != 0 ? argv[11] : NULL,
            NULL,
            NULL,
            argc >= 13 && strcmp(argv[12], "-") != 0 ? argv[12] : NULL,
            certificate_all_choices != 0
        );
    }
    fprintf(
        stderr,
        "usage:\n"
        "  makhos_tb4 verify-native-hardening SCRATCH_PATH\n"
        "  makhos_tb4 verify-dfpn-codec\n"
        "  makhos_tb4 verify-dfpn-disk-backing SCRATCH_PREFIX\n"
        "  makhos_tb4 verify-dfpn-capacity SCRATCH_PATH\n"
        "  makhos_tb4 verify-compact-reader FILE PIECE_COUNT\n"
        "  makhos_tb4 build NO_PROGRESS TB3_HASH_POWER OUTPUT\n"
        "  makhos_tb4 probe FILE POSITION CLOCK\n"
        "  makhos_tb4 verify FILE CLOCK\n"
        "  makhos_tb4 verify-monotonic FILE\n"
        "  makhos_tb4 compress FULL_FILE COMPACT_FILE\n"
        "  makhos_tb4 compare-compact FULL_FILE COMPACT_FILE\n"
        "  makhos_tb4 compact-dfpn INPUT_CHECKPOINT OUTPUT_CHECKPOINT\n"
        "  makhos_tb4 prove FILE POSITION ROOT NODE_BUDGET PROOF_HASH_POWER TB3_HASH_POWER [CHECKPOINT|-] [PREFERRED_LINE]\n"
        "  makhos_tb4 survey FILE POSITION ROOT ROOT_MOVE NODE_BUDGET PROOF_HASH_POWER TB3_HASH_POWER [CHECKPOINT_PREFIX]\n"
        "  makhos_tb4 dfpn FILE POSITION ROOT EXPANSION_BUDGET HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-clock FILE POSITION CLOCK ROOT EXPANSION_BUDGET HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-hashes FILE POSITION ROOT EXPANSION_BUDGET LIVE_HASH_POWER SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-clock-hashes FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_HASH_POWER SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-live-slots FILE POSITION ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-clock-live-slots FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_HASH_POWER TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-slots FILE POSITION ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_SLOTS TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
        "  makhos_tb4 dfpn-clock-slots FILE POSITION CLOCK ROOT EXPANSION_BUDGET LIVE_SLOTS SOLVED_SLOTS TB3_HASH_POWER [DFPN_CHECKPOINT|-] [PROOF_CHECKPOINT_SEED|-] [CERTIFICATE|-] [ALL_CHOICES_0_OR_1]\n"
    );
    return 1;
}
#endif
