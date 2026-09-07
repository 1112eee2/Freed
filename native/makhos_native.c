#define _CRT_SECURE_NO_WARNINGS
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif
#include <inttypes.h>
#include <math.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#if !defined(_WIN32)
#include <sys/types.h>
#endif

/*
 * Tablebase/checkpoint programs include this file with MAKHOS_NO_MAIN.  Keep
 * their durable replacement helper here so every native writer has identical
 * same-volume replacement semantics without adding it to the small standalone
 * move-generator binary.
 */
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#elif defined(MAKHOS_NO_MAIN)
#include <fcntl.h>
#include <unistd.h>
#endif

#if defined(_MSC_VER)
#include <intrin.h>
#endif

#define RED 1
#define BLACK 2
#define MAX_MOVES 4096
#define MAKHOS_MAX_PATH 17
#define MAKHOS_SEARCH_MAX_PLY 96

#ifndef MAKHOS_NNUE_SEARCH_CANDIDATE
#define MAKHOS_NNUE_SEARCH_CANDIDATE 0
#endif
#ifndef MAKHOS_NNUE_PARITY_GUARD
#define MAKHOS_NNUE_PARITY_GUARD 0
#endif

#if MAKHOS_NNUE_SEARCH_CANDIDATE && !defined(MAKHOS_NNUE_RUNTIME_INCLUDED)
#error "NNUE search candidate must be built through makhos_native_nnue.c"
#endif

typedef struct {
    uint32_t red;
    uint32_t black;
    uint32_t kings;
    uint8_t turn;
    uint8_t reversible_plies;
} Position;

#if MAKHOS_NNUE_SEARCH_CANDIDATE
static MakhosNnueIncrementalModel *native_nnue_model = NULL;
static const uint8_t native_nnue_source_model_sha256[32] = {
    0x5f, 0xd8, 0x7a, 0xbd, 0x2f, 0x9c, 0xaa, 0xc8,
    0x10, 0x45, 0xa5, 0x8a, 0xea, 0x42, 0x04, 0x45,
    0xb9, 0x0c, 0xac, 0x9a, 0x70, 0xd5, 0xff, 0xbd,
    0xfc, 0x56, 0x94, 0xba, 0x13, 0x38, 0xca, 0x4e
};
static const uint8_t native_nnue_binary_sha256[32] = {
    0x07, 0xb9, 0xab, 0x0f, 0x83, 0xe2, 0x53, 0xcb,
    0x74, 0xb2, 0xac, 0xd2, 0xbd, 0x52, 0x91, 0xf5,
    0xf9, 0x1e, 0xb0, 0x86, 0xe0, 0x42, 0x79, 0x0f,
    0x33, 0xea, 0x0a, 0x8c, 0x09, 0x14, 0x16, 0x4c
};
#endif

typedef struct {
    Position next;
    uint8_t path[MAKHOS_MAX_PATH];
    uint8_t captured[MAKHOS_MAX_PATH - 1];
    uint8_t path_len;
    uint8_t capture_count;
    uint8_t promotes;
} Move;

typedef struct {
    Move moves[MAX_MOVES];
    uint32_t count;
} MoveList;

typedef struct {
    Position position;
    uint16_t distance;
    int8_t outcome;
    uint8_t used;
} ExactEntry;

typedef struct {
    ExactEntry *entries;
    size_t capacity;
    size_t count;
    MoveList *workspace;
    size_t workspace_depth;
    uint8_t no_progress_plies;
    bool failed;
} ExactContext;

typedef struct {
    int8_t outcome;
    uint16_t distance;
} ExactValue;

typedef struct {
    uint64_t roots;
    uint64_t wins;
    uint64_t draws;
    uint64_t losses;
} ExactCounts;

enum {
    OUTCOME_LOSS = -1,
    OUTCOME_DRAW = 0,
    OUTCOME_WIN = 1
};

#if defined(MAKHOS_NO_MAIN)
/*
 * Flush a closed stdio temporary file, then replace the destination without
 * first unlinking it.  A failed replacement therefore leaves the previous
 * checkpoint usable and the caller can remove only the temporary file.
 */
static bool makhos_replace_file_atomically(
    const char *temporary_path,
    const char *destination_path
) {
#if defined(_WIN32)
    HANDLE temporary = CreateFileA(
        temporary_path,
        GENERIC_WRITE,
        FILE_SHARE_READ,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (temporary == INVALID_HANDLE_VALUE) {
        return false;
    }
    BOOL flushed = FlushFileBuffers(temporary);
    BOOL closed = CloseHandle(temporary);
    if (!flushed || !closed) {
        return false;
    }
    return MoveFileExA(
        temporary_path,
        destination_path,
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
    ) != 0;
#else
    int temporary = open(temporary_path, O_RDONLY);
    if (temporary < 0) {
        return false;
    }
    bool durable = fsync(temporary) == 0;
    if (close(temporary) != 0) {
        durable = false;
    }
    if (!durable || rename(temporary_path, destination_path) != 0) {
        return false;
    }

    /* The rename is already atomic.  Persist its directory entry if the host
       supports directory fsync; failure here is intentionally best-effort. */
    size_t length = strlen(destination_path);
    char *directory = malloc(length + 2);
    if (directory != NULL) {
        const char *slash = strrchr(destination_path, '/');
        if (slash == NULL) {
            memcpy(directory, ".", 2);
        } else if (slash == destination_path) {
            memcpy(directory, "/", 2);
        } else {
            size_t directory_length = (size_t)(slash - destination_path);
            memcpy(directory, destination_path, directory_length);
            directory[directory_length] = '\0';
        }
        int flags = O_RDONLY;
#if defined(O_DIRECTORY)
        flags |= O_DIRECTORY;
#endif
        int directory_fd = open(directory, flags);
        if (directory_fd >= 0) {
            (void)fsync(directory_fd);
            (void)close(directory_fd);
        }
        free(directory);
    }
    return true;
#endif
}
#endif

static inline uint32_t bit_at(int square) {
    return UINT32_C(1) << square;
}

static inline uint8_t other(uint8_t player) {
    return player == RED ? BLACK : RED;
}

static inline uint32_t occupied(Position position) {
    return position.red | position.black;
}

static inline uint32_t pieces_for(Position position, uint8_t player) {
    return player == RED ? position.red : position.black;
}

static int pop_lsb(uint32_t *bits) {
#if defined(_MSC_VER)
    unsigned long index;
    _BitScanForward(&index, *bits);
    *bits &= *bits - 1;
    return (int)index;
#else
    int index = __builtin_ctz(*bits);
    *bits &= *bits - 1;
    return index;
#endif
}

static void index_to_coord(int square, int *row, int *col) {
    *row = square / 4;
    int offset = square % 4;
    *col = offset * 2 + ((*row % 2) == 0 ? 1 : 0);
}

static int coord_to_index(int row, int col) {
    if (row < 0 || row >= 8 || col < 0 || col >= 8 || ((row + col) & 1) != 1) {
        return -1;
    }
    return row * 4 + col / 2;
}

static bool is_promotion_square(uint8_t player, int square) {
    int row;
    int col;
    index_to_coord(square, &row, &col);
    (void)col;
    return player == RED ? row == 7 : row == 0;
}

static Position move_and_capture(
    Position position,
    uint8_t player,
    int from,
    int landing,
    int captured,
    bool king,
    bool promotes
) {
    uint32_t from_bit = bit_at(from);
    uint32_t landing_bit = bit_at(landing);
    uint32_t captured_bit = bit_at(captured);
    if (player == RED) {
        position.red = (position.red & ~from_bit) | landing_bit;
        position.black &= ~captured_bit;
    } else {
        position.black = (position.black & ~from_bit) | landing_bit;
        position.red &= ~captured_bit;
    }
    position.kings &= ~(from_bit | captured_bit);
    if (king || promotes) {
        position.kings |= landing_bit;
    }
    position.reversible_plies = 0;
    return position;
}

static Position quiet_move(
    Position position,
    uint8_t player,
    int from,
    int landing,
    bool king,
    bool promotes
) {
    uint32_t from_bit = bit_at(from);
    uint32_t landing_bit = bit_at(landing);
    if (player == RED) {
        position.red = (position.red & ~from_bit) | landing_bit;
    } else {
        position.black = (position.black & ~from_bit) | landing_bit;
    }
    position.kings &= ~from_bit;
    if (king || promotes) {
        position.kings |= landing_bit;
    }
    position.reversible_plies = promotes ? 0 : (uint8_t)(position.reversible_plies + 1);
    position.turn = other(player);
    return position;
}

static void append_move(MoveList *list, const Move *move, Position terminal_position) {
    if (list->count >= MAX_MOVES) {
        fprintf(stderr, "move-list capacity exceeded (%d)\n", MAX_MOVES);
        exit(3);
    }
    Move stored = *move;
    stored.next = terminal_position;
    stored.next.turn = other(terminal_position.turn);
    list->moves[list->count++] = stored;
}

/* Experimental fast geometry for qsearch only. The normal generator uses
 * reference_capture_recursive below. */
static void qsearch_capture_recursive(
    Position position,
    int square,
    bool king,
    Move partial,
    MoveList *output
) {
#if MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
    static const int8_t captured_steps[4][32] = {
        {-1, -1, -1, -1, -1, 0, 1, 2, 4, 5, 6, 7, -1, 8, 9, 10, 12, 13, 14, 15, -1, 16, 17, 18, 20, 21, 22, 23, -1, 24, 25, 26},
        {-1, -1, -1, -1, 0, 1, 2, 3, 5, 6, 7, -1, 8, 9, 10, 11, 13, 14, 15, -1, 16, 17, 18, 19, 21, 22, 23, -1, 24, 25, 26, 27},
        {4, 5, 6, 7, -1, 8, 9, 10, 12, 13, 14, 15, -1, 16, 17, 18, 20, 21, 22, 23, -1, 24, 25, 26, 28, 29, 30, 31, -1, -1, -1, -1},
        {5, 6, 7, -1, 8, 9, 10, 11, 13, 14, 15, -1, 16, 17, 18, 19, 21, 22, 23, -1, 24, 25, 26, 27, 29, 30, 31, -1, -1, -1, -1, -1}
    };
    static const int8_t landing_steps[4][32] = {
        {-1, -1, -1, -1, -1, -1, -1, -1, -1, 0, 1, 2, -1, 4, 5, 6, -1, 8, 9, 10, -1, 12, 13, 14, -1, 16, 17, 18, -1, 20, 21, 22},
        {-1, -1, -1, -1, -1, -1, -1, -1, 1, 2, 3, -1, 5, 6, 7, -1, 9, 10, 11, -1, 13, 14, 15, -1, 17, 18, 19, -1, 21, 22, 23, -1},
        {-1, 8, 9, 10, -1, 12, 13, 14, -1, 16, 17, 18, -1, 20, 21, 22, -1, 24, 25, 26, -1, 28, 29, 30, -1, -1, -1, -1, -1, -1, -1, -1},
        {9, 10, 11, -1, 13, 14, 15, -1, 17, 18, 19, -1, 21, 22, 23, -1, 25, 26, 27, -1, 29, 30, 31, -1, -1, -1, -1, -1, -1, -1, -1, -1}
    };
#endif
#if MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY
    static const int8_t king_rays[4][32][7] = {
        {
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            { 0, -1, -1, -1, -1, -1, -1},
            { 1, -1, -1, -1, -1, -1, -1},
            { 2, -1, -1, -1, -1, -1, -1},
            { 4, -1, -1, -1, -1, -1, -1},
            { 5,  0, -1, -1, -1, -1, -1},
            { 6,  1, -1, -1, -1, -1, -1},
            { 7,  2, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            { 8,  4, -1, -1, -1, -1, -1},
            { 9,  5,  0, -1, -1, -1, -1},
            {10,  6,  1, -1, -1, -1, -1},
            {12, -1, -1, -1, -1, -1, -1},
            {13,  8,  4, -1, -1, -1, -1},
            {14,  9,  5,  0, -1, -1, -1},
            {15, 10,  6,  1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {16, 12, -1, -1, -1, -1, -1},
            {17, 13,  8,  4, -1, -1, -1},
            {18, 14,  9,  5,  0, -1, -1},
            {20, -1, -1, -1, -1, -1, -1},
            {21, 16, 12, -1, -1, -1, -1},
            {22, 17, 13,  8,  4, -1, -1},
            {23, 18, 14,  9,  5,  0, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {24, 20, -1, -1, -1, -1, -1},
            {25, 21, 16, 12, -1, -1, -1},
            {26, 22, 17, 13,  8,  4, -1}
        },
        {
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            { 0, -1, -1, -1, -1, -1, -1},
            { 1, -1, -1, -1, -1, -1, -1},
            { 2, -1, -1, -1, -1, -1, -1},
            { 3, -1, -1, -1, -1, -1, -1},
            { 5,  1, -1, -1, -1, -1, -1},
            { 6,  2, -1, -1, -1, -1, -1},
            { 7,  3, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            { 8,  5,  1, -1, -1, -1, -1},
            { 9,  6,  2, -1, -1, -1, -1},
            {10,  7,  3, -1, -1, -1, -1},
            {11, -1, -1, -1, -1, -1, -1},
            {13,  9,  6,  2, -1, -1, -1},
            {14, 10,  7,  3, -1, -1, -1},
            {15, 11, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {16, 13,  9,  6,  2, -1, -1},
            {17, 14, 10,  7,  3, -1, -1},
            {18, 15, 11, -1, -1, -1, -1},
            {19, -1, -1, -1, -1, -1, -1},
            {21, 17, 14, 10,  7,  3, -1},
            {22, 18, 15, 11, -1, -1, -1},
            {23, 19, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {24, 21, 17, 14, 10,  7,  3},
            {25, 22, 18, 15, 11, -1, -1},
            {26, 23, 19, -1, -1, -1, -1},
            {27, -1, -1, -1, -1, -1, -1}
        },
        {
            { 4, -1, -1, -1, -1, -1, -1},
            { 5,  8, 12, -1, -1, -1, -1},
            { 6,  9, 13, 16, 20, -1, -1},
            { 7, 10, 14, 17, 21, 24, 28},
            {-1, -1, -1, -1, -1, -1, -1},
            { 8, 12, -1, -1, -1, -1, -1},
            { 9, 13, 16, 20, -1, -1, -1},
            {10, 14, 17, 21, 24, 28, -1},
            {12, -1, -1, -1, -1, -1, -1},
            {13, 16, 20, -1, -1, -1, -1},
            {14, 17, 21, 24, 28, -1, -1},
            {15, 18, 22, 25, 29, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {16, 20, -1, -1, -1, -1, -1},
            {17, 21, 24, 28, -1, -1, -1},
            {18, 22, 25, 29, -1, -1, -1},
            {20, -1, -1, -1, -1, -1, -1},
            {21, 24, 28, -1, -1, -1, -1},
            {22, 25, 29, -1, -1, -1, -1},
            {23, 26, 30, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {24, 28, -1, -1, -1, -1, -1},
            {25, 29, -1, -1, -1, -1, -1},
            {26, 30, -1, -1, -1, -1, -1},
            {28, -1, -1, -1, -1, -1, -1},
            {29, -1, -1, -1, -1, -1, -1},
            {30, -1, -1, -1, -1, -1, -1},
            {31, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1}
        },
        {
            { 5,  9, 14, 18, 23, 27, -1},
            { 6, 10, 15, 19, -1, -1, -1},
            { 7, 11, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            { 8, 13, 17, 22, 26, 31, -1},
            { 9, 14, 18, 23, 27, -1, -1},
            {10, 15, 19, -1, -1, -1, -1},
            {11, -1, -1, -1, -1, -1, -1},
            {13, 17, 22, 26, 31, -1, -1},
            {14, 18, 23, 27, -1, -1, -1},
            {15, 19, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {16, 21, 25, 30, -1, -1, -1},
            {17, 22, 26, 31, -1, -1, -1},
            {18, 23, 27, -1, -1, -1, -1},
            {19, -1, -1, -1, -1, -1, -1},
            {21, 25, 30, -1, -1, -1, -1},
            {22, 26, 31, -1, -1, -1, -1},
            {23, 27, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {24, 29, -1, -1, -1, -1, -1},
            {25, 30, -1, -1, -1, -1, -1},
            {26, 31, -1, -1, -1, -1, -1},
            {27, -1, -1, -1, -1, -1, -1},
            {29, -1, -1, -1, -1, -1, -1},
            {30, -1, -1, -1, -1, -1, -1},
            {31, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1},
            {-1, -1, -1, -1, -1, -1, -1}
        }
    };
#endif
#if !MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY || !MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
#endif
    bool continued = false;
    uint8_t player = position.turn;
    uint32_t enemy = pieces_for(position, other(player));
#if !MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY || !MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
    int row;
    int col;
    index_to_coord(square, &row, &col);
#endif

    int begin = 0;
    int end = 4;
    if (!king) {
        begin = player == RED ? 2 : 0;
        end = player == RED ? 4 : 2;
    }

    for (int direction_index = begin; direction_index < end; ++direction_index) {
#if !MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY || !MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
        int dr = directions[direction_index][0];
        int dc = directions[direction_index][1];
#endif
        int captured = -1;
        int landing = -1;

        if (!king) {
#if MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
            captured = captured_steps[direction_index][square];
            landing = landing_steps[direction_index][square];
#else
            captured = coord_to_index(row + dr, col + dc);
            landing = coord_to_index(row + 2 * dr, col + 2 * dc);
#endif
            if (
                captured < 0 || landing < 0 ||
                (enemy & bit_at(captured)) == 0 ||
                (occupied(position) & bit_at(landing)) != 0
            ) {
                continue;
            }
        } else {
#if MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY
            for (int ray_step = 0; ray_step < 7; ++ray_step) {
                int target = king_rays[direction_index][square][ray_step];
                if (target < 0) {
                    break;
                }
                uint32_t target_bit = bit_at(target);
                if ((occupied(position) & target_bit) == 0) {
                    continue;
                }
                if ((enemy & target_bit) != 0) {
                    int immediate = ray_step < 6
                        ? king_rays[direction_index][square][ray_step + 1]
                        : -1;
                    if (immediate >= 0 && (occupied(position) & bit_at(immediate)) == 0) {
                        captured = target;
                        landing = immediate; /* Thai king-halt rule. */
                    }
                }
                break;
            }
#endif
#if !MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY
            int scan_row = row + dr;
            int scan_col = col + dc;
            while (true) {
                int target = coord_to_index(scan_row, scan_col);
                if (target < 0) {
                    break;
                }
                uint32_t target_bit = bit_at(target);
                if ((occupied(position) & target_bit) == 0) {
                    scan_row += dr;
                    scan_col += dc;
                    continue;
                }
                if ((enemy & target_bit) != 0) {
                    int immediate = coord_to_index(scan_row + dr, scan_col + dc);
                    if (immediate >= 0 && (occupied(position) & bit_at(immediate)) == 0) {
                        captured = target;
                        landing = immediate; /* Thai king-halt rule. */
                    }
                }
                break;
            }
#endif
            if (captured < 0) {
                continue;
            }
        }

        continued = true;
        bool promotes = !king && is_promotion_square(player, landing);
        Position next = move_and_capture(
            position, player, square, landing, captured, king, promotes
        );
        Move branch = partial;
        if (
            branch.path_len >= MAKHOS_MAX_PATH ||
            branch.capture_count >= MAKHOS_MAX_PATH - 1
        ) {
            fprintf(stderr, "capture path capacity exceeded\n");
            exit(4);
        }
        branch.path[branch.path_len++] = (uint8_t)landing;
        branch.captured[branch.capture_count++] = (uint8_t)captured;
        branch.promotes = promotes ? 1 : 0;

        if (promotes) {
            append_move(output, &branch, next);
        } else {
            qsearch_capture_recursive(next, landing, king, branch, output);
        }
    }

    if (!continued && partial.capture_count > 0) {
        append_move(output, &partial, position);
    }
}

#if MAKHOS_QSEARCH_CAPTURE_ONLY
/* Quiescence never explores quiet turns; keep its capture path separate from
 * the authoritative full generator used by normal search and the rules tests.
 */
static void generate_capture_moves(Position position, MoveList *output) {
    output->count = 0;
    uint32_t remaining = pieces_for(position, position.turn);
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        Move partial;
        memset(&partial, 0, sizeof(partial));
        partial.path[0] = (uint8_t)square;
        partial.path_len = 1;
        bool king = (position.kings & bit_at(square)) != 0;
        qsearch_capture_recursive(position, square, king, partial, output);
    }
}
#endif

/* The authoritative full generator deliberately retains the coordinate-based
 * capture recursion. Experimental qsearch geometry stays in
 * qsearch_capture_recursive above and is reached only through
 * generate_capture_moves. */
static void reference_capture_recursive(
    Position position,
    int square,
    bool king,
    Move partial,
    MoveList *output
) {
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
    bool continued = false;
    uint8_t player = position.turn;
    uint32_t enemy = pieces_for(position, other(player));
    int row;
    int col;
    index_to_coord(square, &row, &col);

    int begin = 0;
    int end = 4;
    if (!king) {
        begin = player == RED ? 2 : 0;
        end = player == RED ? 4 : 2;
    }

    for (int direction_index = begin; direction_index < end; ++direction_index) {
        int dr = directions[direction_index][0];
        int dc = directions[direction_index][1];
        int captured = -1;
        int landing = -1;

        if (!king) {
            captured = coord_to_index(row + dr, col + dc);
            landing = coord_to_index(row + 2 * dr, col + 2 * dc);
            if (
                captured < 0 || landing < 0 ||
                (enemy & bit_at(captured)) == 0 ||
                (occupied(position) & bit_at(landing)) != 0
            ) {
                continue;
            }
        } else {
            int scan_row = row + dr;
            int scan_col = col + dc;
            while (true) {
                int target = coord_to_index(scan_row, scan_col);
                if (target < 0) {
                    break;
                }
                uint32_t target_bit = bit_at(target);
                if ((occupied(position) & target_bit) == 0) {
                    scan_row += dr;
                    scan_col += dc;
                    continue;
                }
                if ((enemy & target_bit) != 0) {
                    int immediate = coord_to_index(scan_row + dr, scan_col + dc);
                    if (immediate >= 0 && (occupied(position) & bit_at(immediate)) == 0) {
                        captured = target;
                        landing = immediate; /* Thai king-halt rule. */
                    }
                }
                break;
            }
            if (captured < 0) {
                continue;
            }
        }

        continued = true;
        bool promotes = !king && is_promotion_square(player, landing);
        Position next = move_and_capture(
            position, player, square, landing, captured, king, promotes
        );
        Move branch = partial;
        if (
            branch.path_len >= MAKHOS_MAX_PATH ||
            branch.capture_count >= MAKHOS_MAX_PATH - 1
        ) {
            fprintf(stderr, "capture path capacity exceeded\n");
            exit(4);
        }
        branch.path[branch.path_len++] = (uint8_t)landing;
        branch.captured[branch.capture_count++] = (uint8_t)captured;
        branch.promotes = promotes ? 1 : 0;

        if (promotes) {
            append_move(output, &branch, next);
        } else {
            reference_capture_recursive(next, landing, king, branch, output);
        }
    }

    if (!continued && partial.capture_count > 0) {
        append_move(output, &partial, position);
    }
}

static void generate_moves(Position position, MoveList *output) {
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
    output->count = 0;
    uint32_t own = pieces_for(position, position.turn);
    uint32_t remaining = own;

    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        Move partial;
        memset(&partial, 0, sizeof(partial));
        partial.path[0] = (uint8_t)square;
        partial.path_len = 1;
        bool king = (position.kings & bit_at(square)) != 0;
        reference_capture_recursive(position, square, king, partial, output);
    }
    if (output->count > 0) {
        return;
    }

    remaining = own;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        bool king = (position.kings & bit_at(square)) != 0;
        int row;
        int col;
        index_to_coord(square, &row, &col);
        int begin = 0;
        int end = 4;
        if (!king) {
            begin = position.turn == RED ? 2 : 0;
            end = position.turn == RED ? 4 : 2;
        }
        for (int direction_index = begin; direction_index < end; ++direction_index) {
            int dr = directions[direction_index][0];
            int dc = directions[direction_index][1];
            int scan_row = row + dr;
            int scan_col = col + dc;
            while (true) {
                int landing = coord_to_index(scan_row, scan_col);
                if (landing < 0 || (occupied(position) & bit_at(landing)) != 0) {
                    break;
                }
                bool promotes = !king && is_promotion_square(position.turn, landing);
                Move move;
                memset(&move, 0, sizeof(move));
                move.path[0] = (uint8_t)square;
                move.path[1] = (uint8_t)landing;
                move.path_len = 2;
                move.promotes = promotes ? 1 : 0;
                move.next = quiet_move(
                    position, position.turn, square, landing, king, promotes
                );
                if (output->count >= MAX_MOVES) {
                    fprintf(stderr, "move-list capacity exceeded (%d)\n", MAX_MOVES);
                    exit(3);
                }
                output->moves[output->count++] = move;
                if (!king) {
                    break;
                }
                scan_row += dr;
                scan_col += dc;
            }
        }
    }
}

static Position initial_position(void) {
    Position position;
    position.red = UINT32_C(0x000000ff);
    position.black = UINT32_C(0xff000000);
    position.kings = 0;
    position.turn = BLACK;
    position.reversible_plies = 0;
    return position;
}

static bool parse_piece_group(Position *position, const char *group) {
    if (strlen(group) < 3) {
        return false;
    }
    uint8_t player;
    if (group[0] == 'B') {
        player = BLACK;
    } else if (group[0] == 'R') {
        player = RED;
    } else {
        return false;
    }
    bool king;
    if (group[1] == 'K') {
        king = true;
    } else if (group[1] == 'M') {
        king = false;
    } else {
        return false;
    }
    const char *cursor = group + 2;
    if (*cursor == '=') {
        ++cursor;
    }
    if (*cursor == '\0') {
        return true;
    }
    while (*cursor != '\0') {
        char *end = NULL;
        long number = strtol(cursor, &end, 10);
        if (end == cursor || number < 1 || number > 32) {
            return false;
        }
        int square = (int)number - 1;
        uint32_t square_bit = bit_at(square);
        if ((occupied(*position) & square_bit) != 0) {
            return false;
        }
        if (player == RED) {
            position->red |= square_bit;
        } else {
            position->black |= square_bit;
        }
        if (king) {
            position->kings |= square_bit;
        }
        if (*end == '\0') {
            break;
        }
        if (*end != ',') {
            return false;
        }
        cursor = end + 1;
    }
    return true;
}

static bool parse_position(const char *text, Position *position) {
    size_t length = strlen(text);
    char *copy = malloc(length + 1);
    if (copy == NULL) {
        return false;
    }
    memcpy(copy, text, length + 1);
    memset(position, 0, sizeof(*position));

    if (
        (copy[0] != 'B' && copy[0] != 'R') ||
        (copy[1] != '\0' && copy[1] != ':')
    ) {
        free(copy);
        return false;
    }
    position->turn = copy[0] == 'B' ? BLACK : RED;
    char *cursor = copy + 1;
    while (*cursor != '\0') {
        if (*cursor != ':') {
            free(copy);
            return false;
        }
        ++cursor;
        char *separator = strchr(cursor, ':');
        if (separator != NULL) {
            *separator = '\0';
        }
        if (*cursor == '\0' || !parse_piece_group(position, cursor)) {
            free(copy);
            return false;
        }
        if (separator == NULL) {
            break;
        }
        cursor = separator;
        *cursor = ':';
    }
    free(copy);

    /*
     * A man promotes as soon as it reaches its far rank, so a serialized
     * position containing an unpromoted man there is not a reachable/rankable
     * state.  The ranked tablebases exclude exactly these states.
     */
    uint32_t black_men = position->black & ~position->kings;
    uint32_t red_men = position->red & ~position->kings;
    for (int square = 0; square < 32; ++square) {
        int row;
        int col;
        index_to_coord(square, &row, &col);
        (void)col;
        uint32_t bit = bit_at(square);
        if (
            ((black_men & bit) != 0 && row == 0) ||
            ((red_men & bit) != 0 && row == 7)
        ) {
            return false;
        }
    }
    return true;
}

static void print_move_notation(const Move *move) {
    char separator = move->capture_count > 0 ? 'x' : '-';
    for (uint8_t path_index = 0; path_index < move->path_len; ++path_index) {
        if (path_index > 0) {
            putchar(separator);
        }
        printf("%u", (unsigned)move->path[path_index] + 1);
    }
}

static int command_moves(const char *position_text) {
    Position position;
    if (!parse_position(position_text, &position)) {
        fprintf(stderr, "invalid position: %s\n", position_text);
        return 1;
    }
    MoveList *moves = calloc(1, sizeof(*moves));
    if (moves == NULL) {
        fprintf(stderr, "unable to allocate move list\n");
        return 2;
    }
    generate_moves(position, moves);
    for (uint32_t move_index = 0; move_index < moves->count; ++move_index) {
        Move *move = &moves->moves[move_index];
        print_move_notation(move);
        putchar('\n');
    }
    free(moves);
    return 0;
}

/*
 * Diagnostic output for cross-language verification.  Each line has six
 * tab-separated fields in a fixed order:
 *
 *   NOTATION  red=XXXXXXXX  black=XXXXXXXX  kings=XXXXXXXX  turn=N  clock=N
 *
 * The hexadecimal bitboards are always eight lowercase digits.  The regular
 * `moves` command deliberately remains unchanged for human-facing callers.
 */
static int command_move_states(const char *position_text, int reversible_plies) {
    Position position;
    if (!parse_position(position_text, &position)) {
        fprintf(stderr, "invalid position: %s\n", position_text);
        return 1;
    }
    position.reversible_plies = (uint8_t)reversible_plies;
    MoveList *moves = calloc(1, sizeof(*moves));
    if (moves == NULL) {
        fprintf(stderr, "unable to allocate move list\n");
        return 2;
    }
    generate_moves(position, moves);
    for (uint32_t move_index = 0; move_index < moves->count; ++move_index) {
        Move *move = &moves->moves[move_index];
        print_move_notation(move);
        printf(
            "\tred=%08" PRIx32
            "\tblack=%08" PRIx32
            "\tkings=%08" PRIx32
            "\tturn=%u\tclock=%u\n",
            move->next.red,
            move->next.black,
            move->next.kings,
            (unsigned)move->next.turn,
            (unsigned)move->next.reversible_plies
        );
    }
    free(moves);
    return 0;
}

static uint64_t perft(Position position, int depth, MoveList *workspace, int ply) {
    if (depth == 0) {
        return UINT64_C(1);
    }
    MoveList *moves = &workspace[ply];
    generate_moves(position, moves);
    if (depth == 1) {
        return moves->count;
    }
    uint64_t leaves = 0;
    for (uint32_t index = 0; index < moves->count; ++index) {
        leaves += perft(moves->moves[index].next, depth - 1, workspace, ply + 1);
    }
    return leaves;
}

static int command_perft(int depth) {
    MoveList *workspace = calloc((size_t)depth + 1, sizeof(*workspace));
    if (workspace == NULL) {
        fprintf(stderr, "unable to allocate perft workspace\n");
        return 2;
    }
    Position start = initial_position();
    for (int current = 1; current <= depth; ++current) {
        uint64_t leaves = perft(start, current, workspace, 0);
        printf("depth %d: %" PRIu64 "\n", current, leaves);
    }
    free(workspace);
    return 0;
}

static int command_position_perft(const char *position_text, int depth) {
    Position position;
    if (!parse_position(position_text, &position)) {
        fprintf(stderr, "invalid position: %s\n", position_text);
        return 1;
    }
    MoveList *workspace = calloc((size_t)depth + 1, sizeof(*workspace));
    if (workspace == NULL) {
        fprintf(stderr, "unable to allocate perft workspace\n");
        return 2;
    }
    uint64_t leaves = perft(position, depth, workspace, 0);
    printf("depth %d: %" PRIu64 "\n", depth, leaves);
    free(workspace);
    return 0;
}

static bool parse_depth(const char *text, int *depth) {
    char *end = NULL;
    long value = strtol(text, &end, 10);
    if (end == text || *end != '\0' || value < 1 || value > 15) {
        return false;
    }
    *depth = (int)value;
    return true;
}

static uint64_t mix64(uint64_t value) {
    value ^= value >> 30;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value *= UINT64_C(0x94d049bb133111eb);
    value ^= value >> 31;
    return value;
}

static uint64_t hash_position(Position position) {
    uint64_t hash = mix64(position.red);
    hash ^= mix64((uint64_t)position.black + UINT64_C(0x9e3779b97f4a7c15));
    hash ^= mix64((uint64_t)position.kings + UINT64_C(0x3c6ef372fe94f82a));
    hash ^= mix64(
        ((uint64_t)position.turn << 8) | position.reversible_plies |
        UINT64_C(0xa54ff53a5f1d36f1)
    );
    return hash;
}

static bool same_exact_key(Position left, Position right) {
    return
        left.red == right.red &&
        left.black == right.black &&
        left.kings == right.kings &&
        left.turn == right.turn &&
        left.reversible_plies == right.reversible_plies;
}

static ExactEntry *exact_find_slot(ExactContext *context, Position position) {
    size_t mask = context->capacity - 1;
    size_t index = (size_t)hash_position(position) & mask;
    for (size_t probes = 0; probes < context->capacity; ++probes) {
        ExactEntry *entry = &context->entries[index];
        if (!entry->used || same_exact_key(entry->position, position)) {
            return entry;
        }
        index = (index + 1) & mask;
    }
    return NULL;
}

static bool exact_store(ExactContext *context, Position position, ExactValue value) {
    if (context->count * 10 >= context->capacity * 7) {
        context->failed = true;
        return false;
    }
    ExactEntry *entry = exact_find_slot(context, position);
    if (entry == NULL) {
        context->failed = true;
        return false;
    }
    if (!entry->used) {
        entry->used = 1;
        entry->position = position;
        ++context->count;
    }
    entry->outcome = value.outcome;
    entry->distance = value.distance;
    return true;
}

static bool exact_solve(
    ExactContext *context,
    Position position,
    size_t ply,
    ExactValue *output
) {
    ExactEntry *cached = exact_find_slot(context, position);
    if (cached != NULL && cached->used) {
        output->outcome = cached->outcome;
        output->distance = cached->distance;
        return true;
    }
    if (ply >= context->workspace_depth) {
        context->failed = true;
        return false;
    }
    if (position.reversible_plies >= context->no_progress_plies) {
        ExactValue draw = {OUTCOME_DRAW, 0};
        if (!exact_store(context, position, draw)) {
            return false;
        }
        *output = draw;
        return true;
    }

    MoveList *moves = &context->workspace[ply];
    generate_moves(position, moves);
    if (moves->count == 0) {
        ExactValue loss = {OUTCOME_LOSS, 0};
        if (!exact_store(context, position, loss)) {
            return false;
        }
        *output = loss;
        return true;
    }

    bool has_losing_child = false;
    bool has_drawing_child = false;
    uint16_t shortest_win = UINT16_MAX;
    uint16_t longest_loss = 0;
    for (uint32_t index = 0; index < moves->count; ++index) {
        ExactValue child;
        if (!exact_solve(context, moves->moves[index].next, ply + 1, &child)) {
            return false;
        }
        if (child.outcome == OUTCOME_LOSS) {
            has_losing_child = true;
            if (child.distance < shortest_win) {
                shortest_win = child.distance;
            }
        } else if (child.outcome == OUTCOME_DRAW) {
            has_drawing_child = true;
        } else if (child.distance > longest_loss) {
            longest_loss = child.distance;
        }
    }

    ExactValue value;
    if (has_losing_child) {
        value.outcome = OUTCOME_WIN;
        value.distance = (uint16_t)(shortest_win + 1);
    } else if (has_drawing_child) {
        value.outcome = OUTCOME_DRAW;
        value.distance = 0;
    } else {
        value.outcome = OUTCOME_LOSS;
        value.distance = (uint16_t)(longest_loss + 1);
    }
    if (!exact_store(context, position, value)) {
        return false;
    }
    *output = value;
    return true;
}

static bool exact_context_init(
    ExactContext *context,
    int no_progress_plies,
    int hash_power,
    int maximum_pieces
) {
    if (
        no_progress_plies < 1 || no_progress_plies > 200 ||
        hash_power < 16 || hash_power > 28 ||
        maximum_pieces < 1 || maximum_pieces > 16
    ) {
        return false;
    }
    memset(context, 0, sizeof(*context));
    context->capacity = (size_t)1 << hash_power;
    context->no_progress_plies = (uint8_t)no_progress_plies;
    context->workspace_depth =
        (size_t)no_progress_plies * (size_t)(maximum_pieces * 2 + 2) + 64;
    context->entries = calloc(context->capacity, sizeof(*context->entries));
    context->workspace = calloc(context->workspace_depth, sizeof(*context->workspace));
    if (context->entries == NULL || context->workspace == NULL) {
        free(context->entries);
        free(context->workspace);
        memset(context, 0, sizeof(*context));
        return false;
    }
    return true;
}

static void exact_context_destroy(ExactContext *context) {
    free(context->entries);
    free(context->workspace);
    memset(context, 0, sizeof(*context));
}

static bool valid_man_square(uint8_t player, int square) {
    int row;
    int col;
    index_to_coord(square, &row, &col);
    (void)col;
    return player == BLACK ? row != 0 : row != 7;
}

static int count_bits(uint32_t bits) {
    int count = 0;
    while (bits != 0) {
        bits &= bits - 1;
        ++count;
    }
    return count;
}

static const char *outcome_name(int8_t outcome) {
    if (outcome == OUTCOME_WIN) {
        return "WIN";
    }
    if (outcome == OUTCOME_DRAW) {
        return "DRAW";
    }
    return "LOSS";
}

static int command_exact_position(
    const char *position_text,
    int no_progress_plies,
    int hash_power
) {
    Position position;
    if (!parse_position(position_text, &position)) {
        fprintf(stderr, "invalid position: %s\n", position_text);
        return 1;
    }
    int piece_count = count_bits(occupied(position));
    if (piece_count < 1) {
        fprintf(stderr, "exact solve requires at least one piece\n");
        return 1;
    }
    ExactContext context;
    if (!exact_context_init(&context, no_progress_plies, hash_power, piece_count)) {
        fprintf(stderr, "unable to allocate exact solver (try another hash power)\n");
        return 2;
    }
    ExactValue value;
    if (!exact_solve(&context, position, 0, &value)) {
        fprintf(stderr, "exact solver capacity exceeded after %zu states\n", context.count);
        exact_context_destroy(&context);
        return 3;
    }
    printf("outcome: %s\n", outcome_name(value.outcome));
    if (value.outcome == OUTCOME_DRAW) {
        printf("distance: -\n");
    } else {
        printf("distance: %u\n", (unsigned)value.distance);
    }
    printf("unique solved states: %zu\n", context.count);
    exact_context_destroy(&context);
    return 0;
}

static int command_verify_one_vs_one(int no_progress_plies, int hash_power) {
    ExactContext context;
    if (!exact_context_init(&context, no_progress_plies, hash_power, 2)) {
        fprintf(stderr, "unable to allocate exact solver (try another hash power)\n");
        return 2;
    }
    uint64_t wins = 0;
    uint64_t draws = 0;
    uint64_t losses = 0;
    uint64_t roots = 0;

    for (int black_king = 0; black_king <= 1; ++black_king) {
        for (int red_king = 0; red_king <= 1; ++red_king) {
            for (int black_square = 0; black_square < 32; ++black_square) {
                if (!black_king && !valid_man_square(BLACK, black_square)) {
                    continue;
                }
                for (int red_square = 0; red_square < 32; ++red_square) {
                    if (
                        black_square == red_square ||
                        (!red_king && !valid_man_square(RED, red_square))
                    ) {
                        continue;
                    }
                    for (uint8_t turn = RED; turn <= BLACK; ++turn) {
                        Position position;
                        memset(&position, 0, sizeof(position));
                        position.black = bit_at(black_square);
                        position.red = bit_at(red_square);
                        position.kings =
                            (black_king ? bit_at(black_square) : 0) |
                            (red_king ? bit_at(red_square) : 0);
                        position.turn = turn;
                        ExactValue value;
                        if (!exact_solve(&context, position, 0, &value)) {
                            fprintf(
                                stderr,
                                "exact solver capacity exceeded after %zu states\n",
                                context.count
                            );
                            exact_context_destroy(&context);
                            return 3;
                        }
                        ++roots;
                        if (value.outcome == OUTCOME_WIN) {
                            ++wins;
                        } else if (value.outcome == OUTCOME_DRAW) {
                            ++draws;
                        } else {
                            ++losses;
                        }
                    }
                }
            }
        }
    }
    printf("root positions: %" PRIu64 "\n", roots);
    printf("side-to-move W/D/L: %" PRIu64 "/%" PRIu64 "/%" PRIu64 "\n", wins, draws, losses);
    printf("unique solved states: %zu\n", context.count);
    exact_context_destroy(&context);
    return 0;
}

static bool solve_three_piece_roots(ExactContext *context, ExactCounts *counts) {
    memset(counts, 0, sizeof(*counts));
    for (int square0 = 0; square0 < 30; ++square0) {
        for (int square1 = square0 + 1; square1 < 31; ++square1) {
            for (int square2 = square1 + 1; square2 < 32; ++square2) {
                int squares[3] = {square0, square1, square2};
                /* owner_mask has either one or two black pieces. */
                for (int owner_mask = 1; owner_mask < 7; ++owner_mask) {
                    int black_count =
                        ((owner_mask >> 0) & 1) +
                        ((owner_mask >> 1) & 1) +
                        ((owner_mask >> 2) & 1);
                    if (black_count != 1 && black_count != 2) {
                        continue;
                    }
                    for (int king_mask = 0; king_mask < 8; ++king_mask) {
                        Position position;
                        memset(&position, 0, sizeof(position));
                        bool valid = true;
                        for (int piece_index = 0; piece_index < 3; ++piece_index) {
                            int square = squares[piece_index];
                            uint8_t player =
                                ((owner_mask >> piece_index) & 1) ? BLACK : RED;
                            bool king = ((king_mask >> piece_index) & 1) != 0;
                            if (!king && !valid_man_square(player, square)) {
                                valid = false;
                                break;
                            }
                            if (player == BLACK) {
                                position.black |= bit_at(square);
                            } else {
                                position.red |= bit_at(square);
                            }
                            if (king) {
                                position.kings |= bit_at(square);
                            }
                        }
                        if (!valid) {
                            continue;
                        }
                        for (uint8_t turn = RED; turn <= BLACK; ++turn) {
                            position.turn = turn;
                            position.reversible_plies = 0;
                            ExactValue value;
                            if (!exact_solve(context, position, 0, &value)) {
                                return false;
                            }
                            ++counts->roots;
                            if (value.outcome == OUTCOME_WIN) {
                                ++counts->wins;
                            } else if (value.outcome == OUTCOME_DRAW) {
                                ++counts->draws;
                            } else {
                                ++counts->losses;
                            }
                        }
                    }
                }
            }
        }
    }
    return true;
}

static int command_verify_three_piece(int no_progress_plies, int hash_power) {
    ExactContext context;
    if (!exact_context_init(&context, no_progress_plies, hash_power, 3)) {
        fprintf(stderr, "unable to allocate exact solver (try another hash power)\n");
        return 2;
    }
    ExactCounts counts;
    if (!solve_three_piece_roots(&context, &counts)) {
        fprintf(
            stderr,
            "exact solver capacity exceeded after %zu states and %" PRIu64 " roots\n",
            context.count,
            counts.roots
        );
        exact_context_destroy(&context);
        return 3;
    }
    printf("root positions: %" PRIu64 "\n", counts.roots);
    printf(
        "side-to-move W/D/L: %" PRIu64 "/%" PRIu64 "/%" PRIu64 "\n",
        counts.wins,
        counts.draws,
        counts.losses
    );
    printf("unique solved states: %zu\n", context.count);
    exact_context_destroy(&context);
    return 0;
}

static bool parse_bounded_int(const char *text, int minimum, int maximum, int *value) {
    char *end = NULL;
    long parsed = strtol(text, &end, 10);
    if (end == text || *end != '\0' || parsed < minimum || parsed > maximum) {
        return false;
    }
    *value = (int)parsed;
    return true;
}

/*
 * Tournament search core
 * ----------------------
 *
 * This search deliberately reuses generate_moves() above.  That generator is
 * independently checked against the Python reference by perft, so the fast
 * search cannot silently acquire a second interpretation of the rules.
 */
#define MAKHOS_SEARCH_INFINITY 2000000
#define MAKHOS_SEARCH_MATE 1000000
#ifndef MAKHOS_HISTORY_GRAVITY
#define MAKHOS_HISTORY_GRAVITY 0
#endif
#define MAKHOS_HISTORY_GRAVITY_MAX 16384
#ifndef MAKHOS_COMPACT_TT
#define MAKHOS_COMPACT_TT 1
#endif
#ifndef MAKHOS_STABLE_TT_MOVE
#define MAKHOS_STABLE_TT_MOVE 0
#endif
#ifndef MAKHOS_PRECOMPUTED_ORDERING
#define MAKHOS_PRECOMPUTED_ORDERING 1
#endif
#ifndef MAKHOS_EARLY_TT_CUTOFF
#define MAKHOS_EARLY_TT_CUTOFF 1
#endif
#ifndef MAKHOS_COMPACT_PV
#define MAKHOS_COMPACT_PV 1
#endif
#ifndef MAKHOS_COMPACT_KILLERS
#define MAKHOS_COMPACT_KILLERS 1
#endif
#ifndef MAKHOS_SEARCH_TELEMETRY
#define MAKHOS_SEARCH_TELEMETRY 0
#endif
#ifndef MAKHOS_IIR_CENSUS
#define MAKHOS_IIR_CENSUS 0
#endif
#ifndef MAKHOS_REPETITION_CENSUS
#define MAKHOS_REPETITION_CENSUS 0
#endif
#ifndef MAKHOS_LMR_SECOND_REDUCTION
#define MAKHOS_LMR_SECOND_REDUCTION 1
#endif
#ifndef MAKHOS_NULL_MOVE
#define MAKHOS_NULL_MOVE 1
#endif
#ifndef MAKHOS_NULL_DEEP_REDUCTION
#define MAKHOS_NULL_DEEP_REDUCTION 3
#endif
#ifndef MAKHOS_SHARED_TT
#define MAKHOS_SHARED_TT 0
#endif
#ifndef MAKHOS_ENDGAME_KING_VALUE
#define MAKHOS_ENDGAME_KING_VALUE 330
#endif
#ifndef MAKHOS_ENDGAME_KING_EDGE
#define MAKHOS_ENDGAME_KING_EDGE -12
#endif
#ifndef MAKHOS_FITTED_ENDGAME_EVAL
#define MAKHOS_FITTED_ENDGAME_EVAL 0
#endif
#ifndef MAKHOS_QSEARCH_CAPTURE_ONLY
#define MAKHOS_QSEARCH_CAPTURE_ONLY 0
#endif
#ifndef MAKHOS_FAST_QUIET_MOBILITY
#define MAKHOS_FAST_QUIET_MOBILITY 0
#endif
#ifndef MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
#define MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY 0
#endif
#ifndef MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY
#define MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY 0
#endif
#ifndef MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS
#define MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS 0
#endif
#ifndef MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY
#define MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY 0
#endif
#ifndef MAKHOS_QSEARCH_SINGLE_MOVE_FASTPATH
#define MAKHOS_QSEARCH_SINGLE_MOVE_FASTPATH 1
#endif
#ifndef MAKHOS_QSEARCH_TT_CENSUS
#define MAKHOS_QSEARCH_TT_CENSUS 0
#endif
#ifndef MAKHOS_QSEARCH_PVS
#define MAKHOS_QSEARCH_PVS 0
#endif
#ifndef MAKHOS_TT_KEEP_DEEP_STALE_SAME_KEY
#define MAKHOS_TT_KEEP_DEEP_STALE_SAME_KEY 0
#endif
#ifndef MAKHOS_STRICT_SEARCH_POSITION_KEY
#define MAKHOS_STRICT_SEARCH_POSITION_KEY 0
#endif
#ifndef MAKHOS_STRICT_SEARCH_POSITION_KEY_COMPAT
#define MAKHOS_STRICT_SEARCH_POSITION_KEY_COMPAT 0
#endif
#ifndef MAKHOS_STRICT_SEARCH_POSITION_KEY_LEGACY_TT_INDEX
#define MAKHOS_STRICT_SEARCH_POSITION_KEY_LEGACY_TT_INDEX 0
#endif
#ifndef MAKHOS_SEARCH_KEY_TEST_API
#define MAKHOS_SEARCH_KEY_TEST_API 0
#endif
#ifndef MAKHOS_EXPERIMENTAL_SEARCH_APIS
#define MAKHOS_EXPERIMENTAL_SEARCH_APIS 1
#endif
#ifndef MAKHOS_ITERATIVE_SESSION
#define MAKHOS_ITERATIVE_SESSION 0
#endif
#ifndef MAKHOS_NATIVE_LAZY_SMP
#define MAKHOS_NATIVE_LAZY_SMP 0
#endif
#ifndef MAKHOS_NATIVE_LAZY_SMP_ROOT_ROTATION
#define MAKHOS_NATIVE_LAZY_SMP_ROOT_ROTATION 1
#endif
#ifndef MAKHOS_NATIVE_ROOT_PVS_SMP
#define MAKHOS_NATIVE_ROOT_PVS_SMP 0
#endif
#if MAKHOS_NATIVE_ROOT_PVS_SMP && !defined(_WIN32)
#error "MAKHOS_NATIVE_ROOT_PVS_SMP currently requires Win32 worker primitives"
#endif
#if MAKHOS_QSEARCH_TT_CENSUS && MAKHOS_SHARED_TT
#error "MAKHOS_QSEARCH_TT_CENSUS requires private search contexts"
#endif

enum {
    SEARCH_TT_EMPTY = 0,
    SEARCH_TT_EXACT = 1,
    SEARCH_TT_LOWER = 2,
    SEARCH_TT_UPPER = 3
};

typedef struct {
    uint8_t path[MAKHOS_MAX_PATH];
    uint8_t captured[MAKHOS_MAX_PATH - 1];
    uint8_t path_len;
    uint8_t capture_count;
    uint8_t promotes;
} MakhosPackedMove;

typedef struct {
    uint32_t red;
    uint32_t black;
    uint32_t kings;
    uint8_t turn;
    uint8_t count;
    uint8_t reserved[2];
} MakhosHistoryEntry;

typedef struct {
    uint64_t key;
    MakhosHistoryEntry entry;
} NativeHistoryLookupEntry;

typedef struct {
    int32_t score;
    uint32_t depth;
    uint64_t nodes;
    uint32_t elapsed_ms;
    uint32_t pv_len;
    MakhosPackedMove best_move;
    MakhosPackedMove pv[MAKHOS_SEARCH_MAX_PLY];
} MakhosSearchResult;

typedef struct {
    uint64_t path_low;
    uint64_t captured_low;
    uint32_t path_high_meta;
    uint32_t captured_high_meta;
} NativeCompactMove;

typedef struct {
    uint64_t key;
    int32_t score;
    int16_t depth;
    uint8_t flag;
    uint8_t generation;
#if MAKHOS_COMPACT_TT
    NativeCompactMove best_move;
#else
    Move best_move;
#endif
} NativeTTEntry;

#if MAKHOS_SHARED_TT
#define MAKHOS_SHARED_TT_LOCKS 4096
typedef struct {
    atomic_flag flag;
    uint8_t padding[63];
} NativeTTLock;
typedef struct {
    NativeTTEntry *entries;
    size_t count;
    atomic_uint references;
    atomic_uint generation;
    NativeTTLock locks[MAKHOS_SHARED_TT_LOCKS];
} NativeSharedTT;
_Static_assert(sizeof(NativeTTLock) == 64, "shared TT lock must fill a cache line");
#endif

typedef struct {
    uint64_t qnodes;
    uint64_t movegen_calls;
    uint64_t moves_generated;
    uint64_t ordering_calls;
    uint64_t moves_ordered;
    uint64_t tt_probes;
    uint64_t tt_hits;
    uint64_t tt_cutoffs;
    uint64_t tt_collisions;
    uint64_t tt_stores;
    uint64_t tt_replacements;
    uint64_t null_attempts;
    uint64_t null_cutoffs;
    uint64_t beta_cutoffs;
    uint64_t beta_cutoff_first;
    uint64_t beta_cutoff_index_sum;
    uint64_t q_beta_cutoffs;
    uint64_t pvs_researches;
    uint64_t lmr_researches;
} MakhosSearchTelemetry;

#if MAKHOS_IIR_CENSUS
/*
 * Measurement-only census for deciding whether internal iterative reduction
 * has enough scope to justify a behavioral experiment.  The counters are
 * recorded only after a normal node survives its TT cutoff and terminal-move
 * checks, matching the point where an IIR candidate would be applied.
 */
typedef struct {
    uint64_t post_tt_nodes;
    uint64_t eligible_nodes;
    uint64_t depth_ge6_nodes;
    uint64_t full_window_nodes;
    uint64_t null_window_nodes;
    uint64_t capture_nodes;
    uint64_t quiet_nodes;
    uint64_t with_tt_move;
    uint64_t without_tt_move;
    uint64_t missing_full_window;
    uint64_t missing_null_window;
    uint64_t missing_capture;
    uint64_t missing_quiet;
    uint64_t missing_depth4;
    uint64_t missing_depth5;
    uint64_t missing_depth6_plus;
    uint64_t missing_depth_sum;
} MakhosIirCensusTelemetry;
#endif

#if MAKHOS_REPETITION_CENSUS
/*
 * Measurement-only census for the exact history/line scans used to adjudicate
 * threefold repetition.  It changes no comparison, cutoff, or search state.
 */
typedef struct {
    uint64_t calls;
    uint64_t normal_calls;
    uint64_t qsearch_calls;
    uint64_t initial_linear_calls;
    uint64_t initial_linear_entries;
    uint64_t initial_hash_calls;
    uint64_t initial_hash_probes;
    uint64_t initial_hits;
    uint64_t line_entries;
    uint64_t line_matches;
    uint64_t draw_hits;
    uint64_t span_zero;
    uint64_t span_1_4;
    uint64_t span_5_16;
    uint64_t span_17_plus;
} MakhosRepetitionCensusTelemetry;
#endif

#if MAKHOS_QSEARCH_TT_CENSUS
typedef struct {
    uint64_t key;
    uint8_t generation;
    uint8_t reserved[7];
} NativeQttCensusEntry;

typedef struct {
    uint64_t capture_nodes;
    uint64_t probes;
    uint64_t same_key_hits;
    uint64_t collisions;
    uint64_t stores;
    uint64_t table_entries;
} MakhosQttCensusTelemetry;

_Static_assert(
    sizeof(NativeQttCensusEntry) == 16,
    "qsearch census entry layout drifted"
);
#endif

#if MAKHOS_COMPACT_PV
/*
 * PV lines never need Move.next.  MakhosPackedMove keeps the path bytes in a
 * directly copyable form, avoiding the bit-packing cost that is worthwhile in
 * the much larger TT but repeatably slowed the hot PV update path.
 */
typedef MakhosPackedMove NativePVMove;
#else
typedef Move NativePVMove;
#endif

_Static_assert(sizeof(MakhosPackedMove) == 36, "packed move layout drifted");
_Static_assert(
    offsetof(Move, path) + sizeof(MakhosPackedMove) == sizeof(Move),
    "Move path metadata is no longer a contiguous packed move"
);

#if MAKHOS_COMPACT_TT
_Static_assert(sizeof(NativeCompactMove) == 24, "compact move layout drifted");
_Static_assert(sizeof(NativeTTEntry) == 40, "TT entry layout drifted");
#endif

#if MAKHOS_NATIVE_LAZY_SMP
typedef struct NativeLazySmpControl NativeLazySmpControl;
#endif
#if MAKHOS_NATIVE_ROOT_PVS_SMP
typedef struct NativeRootPvsControl NativeRootPvsControl;
typedef struct NativeRootPvsHandle NativeRootPvsHandle;
#endif

typedef struct {
    NativeTTEntry *tt;
    size_t tt_count;
#if MAKHOS_SHARED_TT
    NativeSharedTT *shared_tt;
    bool owns_shared_tt;
    bool tt_requires_lock;
#endif
    MoveList *workspace[MAKHOS_SEARCH_MAX_PLY];
    size_t workspace_count;
    uint64_t nodes;
#if MAKHOS_SEARCH_TELEMETRY
    MakhosSearchTelemetry telemetry;
#endif
#if MAKHOS_IIR_CENSUS
    MakhosIirCensusTelemetry iir_census_telemetry;
#endif
#if MAKHOS_REPETITION_CENSUS
    MakhosRepetitionCensusTelemetry repetition_census_telemetry;
#endif
#if MAKHOS_QSEARCH_TT_CENSUS
    NativeQttCensusEntry *qtt_census;
    size_t qtt_census_count;
    MakhosQttCensusTelemetry qtt_census_telemetry;
#endif
    double start;
    double deadline;
    bool has_deadline;
    bool stopped;
    bool allocation_failed;
#if MAKHOS_NATIVE_LAZY_SMP
    NativeLazySmpControl *lazy_smp_control;
#endif
#if MAKHOS_NATIVE_ROOT_PVS_SMP
    NativeRootPvsControl *root_pvs_control;
#endif
    uint8_t no_progress_plies;
    uint8_t repetition_limit;
    uint8_t generation;
    const MakhosHistoryEntry *initial_history;
    uint32_t initial_history_count;
    NativeHistoryLookupEntry *history_lookup;
    size_t history_lookup_capacity;
    bool history_lookup_ready;
    Position line[MAKHOS_SEARCH_MAX_PLY + 1];
#if MAKHOS_COMPACT_KILLERS
    MakhosPackedMove killers[MAKHOS_SEARCH_MAX_PLY][2];
#else
    Move killers[MAKHOS_SEARCH_MAX_PLY][2];
#endif
    uint8_t killer_count[MAKHOS_SEARCH_MAX_PLY];
    int32_t history[3][32][32];
    uint64_t cached_root_key;
    Move cached_root_best;
    bool has_cached_root_best;
#if MAKHOS_ITERATIVE_SESSION
    bool session_active;
    Position session_root;
    uint64_t session_root_key;
    uint32_t session_completed_depth;
    Move session_completed_move;
    int session_completed_score;
    NativePVMove session_completed_pv[MAKHOS_SEARCH_MAX_PLY];
    uint8_t session_completed_pv_length;
    Move session_previous_best;
    bool session_has_previous_best;
    MakhosHistoryEntry *session_history;
    uint32_t session_history_count;
    size_t session_history_capacity;
#endif
    NativePVMove pv[MAKHOS_SEARCH_MAX_PLY][MAKHOS_SEARCH_MAX_PLY];
    uint8_t pv_length[MAKHOS_SEARCH_MAX_PLY];
    uint8_t repetition_dependent[MAKHOS_SEARCH_MAX_PLY];
#if MAKHOS_PRECOMPUTED_ORDERING
    int32_t order_scores[MAX_MOVES];
#endif
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    MakhosNnueAccumulator nnue_stack[MAKHOS_SEARCH_MAX_PLY + 1];
    uint8_t nnue_valid[MAKHOS_SEARCH_MAX_PLY + 1];
    uint64_t nnue_refreshes;
    uint64_t nnue_updates;
    uint64_t nnue_evaluations;
#endif
} NativeSearchContext;

#if MAKHOS_NNUE_SEARCH_CANDIDATE
enum {
    MAKHOS_NNUE_INPUT_DIMENSIONS = 137,
    MAKHOS_NNUE_MAX_ACTIVE = 17,
    MAKHOS_NNUE_CLOCK_OFFSET = 128,
    MAKHOS_NNUE_CP_CLIP = 2000
};

static uint16_t native_nnue_piece_feature(
    Position position,
    int square,
    uint8_t perspective
) {
    uint32_t bit = UINT32_C(1) << square;
    bool red_piece = (position.red & bit) != 0U;
    bool own_piece = perspective == RED ? red_piece : !red_piece;
    bool king = (position.kings & bit) != 0U;
    uint16_t category;
    if (own_piece) {
        category = king ? 1U : 0U;
    } else {
        category = king ? 3U : 2U;
    }
    uint16_t canonical = perspective == BLACK
        ? (uint16_t)square
        : (uint16_t)(31 - square);
    return (uint16_t)(category * 32U + canonical);
}

static bool native_nnue_features(
    Position position,
    uint8_t perspective,
    uint16_t output[MAKHOS_NNUE_MAX_ACTIVE],
    uint32_t *count
) {
    if (
        output == NULL || count == NULL ||
        (perspective != RED && perspective != BLACK) ||
        position.reversible_plies >= 80
    ) {
        set_error("NNUE position cannot be encoded");
        return false;
    }
    uint32_t occupied_bits = position.red | position.black;
    uint32_t used = 0U;
    for (int square = 0; square < 32; ++square) {
        if ((occupied_bits & (UINT32_C(1) << square)) == 0U) continue;
        if (used >= MAKHOS_NNUE_MAX_ACTIVE - 1U) {
            set_error("NNUE active feature count exceeds v1 contract");
            return false;
        }
        output[used++] = native_nnue_piece_feature(
            position, square, perspective);
    }
    uint16_t bucket = position.reversible_plies == 0
        ? 0U
        : (uint16_t)(1U + position.reversible_plies / 10U);
    output[used++] = (uint16_t)(MAKHOS_NNUE_CLOCK_OFFSET + bucket);
    *count = used;
    return true;
}

static void native_nnue_initialize_stack(NativeSearchContext *context) {
    for (size_t ply = 0U; ply <= MAKHOS_SEARCH_MAX_PLY; ++ply) {
        context->nnue_stack[ply].magic = INCREMENTAL_ACCUMULATOR_MAGIC;
    }
}

static bool native_nnue_refresh_root(
    NativeSearchContext *context,
    Position root
) {
    uint16_t red[MAKHOS_NNUE_MAX_ACTIVE];
    uint16_t black[MAKHOS_NNUE_MAX_ACTIVE];
    uint32_t red_count = 0U;
    uint32_t black_count = 0U;
    if (
        native_nnue_model == NULL ||
        !native_nnue_features(root, RED, red, &red_count) ||
        !native_nnue_features(root, BLACK, black, &black_count) ||
        !makhos_nnue_incremental_refresh(
            native_nnue_model,
            &context->nnue_stack[0],
            red,
            red_count,
            black,
            black_count
        )
    ) {
        context->allocation_failed = true;
        context->stopped = true;
        return false;
    }
    memset(context->nnue_valid, 0, sizeof(context->nnue_valid));
    context->nnue_valid[0] = 1U;
    ++context->nnue_refreshes;
    return true;
}

static bool native_nnue_perspective_delta(
    Position parent,
    Position child,
    uint8_t perspective,
    uint16_t removed[MAKHOS_NNUE_MAX_ACTIVE],
    uint32_t *removed_count,
    uint16_t added[MAKHOS_NNUE_MAX_ACTIVE],
    uint32_t *added_count
) {
    if (
        (perspective != RED && perspective != BLACK) ||
        parent.reversible_plies >= 80 || child.reversible_plies >= 80
    ) {
        set_error("NNUE delta position cannot be encoded");
        return false;
    }
    *removed_count = 0U;
    *added_count = 0U;
    uint32_t parent_occupied = parent.red | parent.black;
    uint32_t child_occupied = child.red | child.black;
    uint32_t changed =
        (parent.red ^ child.red) |
        (parent.black ^ child.black) |
        (parent.kings ^ child.kings);
    while (changed != 0U) {
        int square = pop_lsb(&changed);
        uint32_t bit = UINT32_C(1) << square;
        if ((parent_occupied & bit) != 0U) {
            removed[(*removed_count)++] = native_nnue_piece_feature(
                parent, square, perspective);
        }
        if ((child_occupied & bit) != 0U) {
            added[(*added_count)++] = native_nnue_piece_feature(
                child, square, perspective);
        }
    }
    uint16_t parent_bucket = parent.reversible_plies == 0
        ? 0U
        : (uint16_t)(1U + parent.reversible_plies / 10U);
    uint16_t child_bucket = child.reversible_plies == 0
        ? 0U
        : (uint16_t)(1U + child.reversible_plies / 10U);
    if (parent_bucket != child_bucket) {
        removed[(*removed_count)++] = (uint16_t)(
            MAKHOS_NNUE_CLOCK_OFFSET + parent_bucket);
        added[(*added_count)++] = (uint16_t)(
            MAKHOS_NNUE_CLOCK_OFFSET + child_bucket);
    }
    return true;
}

static bool native_nnue_materialize_child(
    NativeSearchContext *context,
    Position child,
    int child_ply
) {
    if (child_ply < 1 || child_ply > MAKHOS_SEARCH_MAX_PLY) {
        set_error("NNUE child ply is invalid");
        context->allocation_failed = true;
        context->stopped = true;
        return false;
    }
    if (child.reversible_plies >= 80) {
        memset(&context->nnue_stack[child_ply], 0, sizeof(context->nnue_stack[child_ply]));
        context->nnue_stack[child_ply].magic = INCREMENTAL_ACCUMULATOR_MAGIC;
        return true;
    }
    MakhosNnueAccumulator candidate = context->nnue_stack[child_ply - 1];
    Position parent = context->line[child_ply - 1];
    uint16_t removed[MAKHOS_NNUE_MAX_ACTIVE];
    uint16_t added[MAKHOS_NNUE_MAX_ACTIVE];
    uint32_t removed_count;
    uint32_t added_count;
    if (
        !native_nnue_perspective_delta(
            parent,
            child,
            RED,
            removed,
            &removed_count,
            added,
            &added_count
        ) ||
        !makhos_nnue_avx2_update(
            native_nnue_model,
            &candidate,
            RED,
            removed,
            removed_count,
            added,
            added_count
        ) ||
        !native_nnue_perspective_delta(
            parent,
            child,
            BLACK,
            removed,
            &removed_count,
            added,
            &added_count
        ) ||
        !makhos_nnue_avx2_update(
            native_nnue_model,
            &candidate,
            BLACK,
            removed,
            removed_count,
            added,
            added_count
        )
    ) {
        context->allocation_failed = true;
        context->stopped = true;
        return false;
    }
    context->nnue_stack[child_ply] = candidate;
    context->nnue_valid[child_ply] = 1U;
    ++context->nnue_updates;
    return true;
}

static bool native_nnue_ensure_accumulator(
    NativeSearchContext *context,
    int ply
) {
    if (ply < 0 || ply > MAKHOS_SEARCH_MAX_PLY) {
        set_error("NNUE accumulator ply is invalid");
        context->allocation_failed = true;
        context->stopped = true;
        return false;
    }
    if (context->nnue_valid[ply]) return true;
    if (
        ply == 0 ||
        !native_nnue_ensure_accumulator(context, ply - 1) ||
        !native_nnue_materialize_child(context, context->line[ply], ply)
    ) {
        context->allocation_failed = true;
        context->stopped = true;
        return false;
    }
    return true;
}

static bool native_nnue_prepare_child(
    NativeSearchContext *context,
    Position child,
    int child_ply
) {
    (void)child;
    if (child_ply < 1 || child_ply > MAKHOS_SEARCH_MAX_PLY) {
        set_error("NNUE child ply is invalid");
        context->allocation_failed = true;
        context->stopped = true;
        return false;
    }
    context->nnue_valid[child_ply] = 0U;
    return true;
}

static int native_nnue_score_from_sum(int32_t output_sum) {
    const double normalized = (double)output_sum / (127.0 * 192.0);
    const double normalized_clip = 0.9974579674738373; /* tanh(2000 / 600) */
    if (normalized >= normalized_clip) return MAKHOS_NNUE_CP_CLIP;
    if (normalized <= -normalized_clip) return -MAKHOS_NNUE_CP_CLIP;
    const double centipawns = 600.0 * atanh(normalized);
    return centipawns >= 0.0
        ? (int)floor(centipawns + 0.5)
        : (int)ceil(centipawns - 0.5);
}

static int native_nnue_evaluate(
    NativeSearchContext *context,
    Position position,
    uint8_t perspective,
    int ply
) {
    if (position.reversible_plies >= 80) return 0;
    int32_t output_sum = 0;
    if (
        context == NULL || ply < 0 || ply > MAKHOS_SEARCH_MAX_PLY ||
        !native_nnue_ensure_accumulator(context, ply) ||
        !makhos_nnue_avx2_eval(
            native_nnue_model,
            &context->nnue_stack[ply],
            perspective,
            &output_sum
        )
    ) {
        if (context != NULL) {
            context->allocation_failed = true;
            context->stopped = true;
        }
        return 0;
    }
#if MAKHOS_NNUE_PARITY_GUARD
    uint16_t red[MAKHOS_NNUE_MAX_ACTIVE];
    uint16_t black[MAKHOS_NNUE_MAX_ACTIVE];
    uint32_t red_count = 0U;
    uint32_t black_count = 0U;
    int32_t refreshed_sum = 0;
    if (
        !native_nnue_features(position, RED, red, &red_count) ||
        !native_nnue_features(position, BLACK, black, &black_count) ||
        !makhos_nnue_incremental_eval_full(
            native_nnue_model,
            red,
            red_count,
            black,
            black_count,
            perspective,
            &refreshed_sum
        ) ||
        refreshed_sum != output_sum
    ) {
        set_error("NNUE search accumulator differs from full refresh");
        context->allocation_failed = true;
        context->stopped = true;
        return 0;
    }
#endif
    ++context->nnue_evaluations;
    return native_nnue_score_from_sum(output_sum);
}
#endif

#if MAKHOS_NATIVE_ROOT_PVS_SMP
#define MAKHOS_NATIVE_ROOT_PVS_MAX_THREADS 12
#define MAKHOS_NATIVE_ROOT_PVS_MAX_HELPERS \
    (MAKHOS_NATIVE_ROOT_PVS_MAX_THREADS - 1)

struct NativeRootPvsControl {
    atomic_bool stop;
};

typedef struct {
    uint32_t requested_threads;
    uint32_t effective_threads;
    uint32_t active_helpers;
    uint32_t completed_depth;
    uint32_t attempted_depth;
    uint32_t main_hash_power;
    uint32_t helper_hash_power;
    uint32_t shadow_iterations;
    uint64_t allocated_tt_bytes;
    uint64_t main_nodes;
    uint64_t helper_nodes;
    uint64_t scout_tasks_started;
    uint64_t scout_tasks_completed;
    uint64_t scout_fail_highs;
    uint64_t scout_ready_before_main;
    uint64_t scout_ready_fail_highs;
    uint64_t scout_ready_above_current_alpha;
    uint64_t scout_tasks_aborted;
    uint64_t worker_failures;
    uint64_t main_wait_us;
} MakhosRootPvsStats;

typedef struct {
    NativeRootPvsHandle *owner;
    uint32_t index;
    uint64_t tasks_started;
    uint64_t tasks_completed;
    uint64_t fail_highs;
    uint64_t tasks_aborted;
    uint64_t failures;
} NativeRootPvsWorker;

struct NativeRootPvsHandle {
    NativeRootPvsControl control;
    atomic_bool shutdown;
    NativeSearchContext main_context;
    NativeSearchContext helpers[MAKHOS_NATIVE_ROOT_PVS_MAX_HELPERS];
    NativeRootPvsWorker workers[MAKHOS_NATIVE_ROOT_PVS_MAX_HELPERS];
    HANDLE start_events[MAKHOS_NATIVE_ROOT_PVS_MAX_HELPERS];
    HANDLE done_events[MAKHOS_NATIVE_ROOT_PVS_MAX_HELPERS];
    HANDLE worker_threads[MAKHOS_NATIVE_ROOT_PVS_MAX_HELPERS];
    Position task_root;
    Move task_moves[MAX_MOVES];
    atomic_uint task_states[MAX_MOVES];
    int32_t task_scores[MAX_MOVES];
    uint32_t task_move_count;
    uint32_t active_helpers;
    int task_depth;
    int task_alpha;
    uint32_t requested_threads;
    uint32_t effective_threads;
    uint32_t helper_count;
    uint32_t allocated_helpers;
    uint32_t created_helpers;
    int main_hash_power;
    int helper_hash_power;
    bool main_allocated;
    bool running;
    MakhosRootPvsStats stats;
};
#endif

#if MAKHOS_NATIVE_LAZY_SMP
struct NativeLazySmpControl {
    atomic_bool stop;
    double deadline;
    bool has_deadline;
};
#endif

#if MAKHOS_NATIVE_LAZY_SMP
#define MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS 12

typedef struct {
    uint32_t requested_threads;
    uint32_t completed_threads;
    uint64_t aggregate_nodes;
    uint64_t leader_nodes;
    uint32_t leader_depth;
    uint64_t worker_nodes[MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS];
    uint32_t worker_depth[MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS];
} MakhosLazySmpStats;

typedef struct {
    NativeLazySmpControl control;
    NativeSearchContext workers[MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS];
    MakhosLazySmpStats stats;
    uint32_t threads;
    bool running;
} NativeLazySmpHandle;
#endif

#if MAKHOS_SEARCH_TELEMETRY
#define SEARCH_TELEMETRY_INC(context, field) (++(context)->telemetry.field)
#define SEARCH_TELEMETRY_ADD(context, field, value) \
    ((context)->telemetry.field += (uint64_t)(value))
#else
#define SEARCH_TELEMETRY_INC(context, field) ((void)0)
#define SEARCH_TELEMETRY_ADD(context, field, value) ((void)0)
#endif

#if MAKHOS_IIR_CENSUS
static void record_iir_census(
    NativeSearchContext *context,
    int depth,
    int alpha,
    int beta,
    int ply,
    const Move *tt_move,
    bool has_capture
) {
    MakhosIirCensusTelemetry *telemetry = &context->iir_census_telemetry;
    ++telemetry->post_tt_nodes;
    if (ply <= 0 || depth < 4) return;

    bool full_window = beta - alpha > 1;
    ++telemetry->eligible_nodes;
    telemetry->depth_ge6_nodes += depth >= 6;
    telemetry->full_window_nodes += full_window;
    telemetry->null_window_nodes += !full_window;
    telemetry->capture_nodes += has_capture;
    telemetry->quiet_nodes += !has_capture;
    if (tt_move != NULL) {
        ++telemetry->with_tt_move;
        return;
    }

    ++telemetry->without_tt_move;
    telemetry->missing_full_window += full_window;
    telemetry->missing_null_window += !full_window;
    telemetry->missing_capture += has_capture;
    telemetry->missing_quiet += !has_capture;
    telemetry->missing_depth4 += depth == 4;
    telemetry->missing_depth5 += depth == 5;
    telemetry->missing_depth6_plus += depth >= 6;
    telemetry->missing_depth_sum += (uint64_t)depth;
}
#endif

#if MAKHOS_SHARED_TT
static void lock_native_tt(NativeSearchContext *context, size_t index) {
    if (!context->tt_requires_lock) return;
    atomic_flag *lock = &context->shared_tt->locks[
        index & (MAKHOS_SHARED_TT_LOCKS - 1)
    ].flag;
    while (atomic_flag_test_and_set_explicit(lock, memory_order_acquire)) {
        /* TT critical sections only copy or replace one 40-byte entry. */
    }
}

static void unlock_native_tt(NativeSearchContext *context, size_t index) {
    if (!context->tt_requires_lock) return;
    atomic_flag_clear_explicit(
        &context->shared_tt->locks[
            index & (MAKHOS_SHARED_TT_LOCKS - 1)
        ].flag,
        memory_order_release
    );
}

static void load_native_tt_entry(
    NativeSearchContext *context,
    size_t index,
    NativeTTEntry *output
) {
    lock_native_tt(context, index);
    *output = context->tt[index];
    unlock_native_tt(context, index);
}
#endif

static int native_count_bits(uint32_t bits) {
#if defined(_MSC_VER)
    return (int)__popcnt(bits);
#else
    return __builtin_popcount(bits);
#endif
}

static bool same_search_position(Position left, Position right) {
    return
        left.red == right.red &&
        left.black == right.black &&
        left.kings == right.kings &&
        left.turn == right.turn;
}

static bool same_move(const Move *left, const Move *right) {
    return
        left->path_len == right->path_len &&
        left->capture_count == right->capture_count &&
        left->promotes == right->promotes &&
        memcmp(left->path, right->path, left->path_len) == 0 &&
        memcmp(left->captured, right->captured, left->capture_count) == 0;
}

#if MAKHOS_COMPACT_KILLERS
static bool same_packed_killer(
    const Move *move,
    const MakhosPackedMove *packed
) {
    return
        move->path_len == packed->path_len &&
        move->capture_count == packed->capture_count &&
        move->promotes == packed->promotes &&
        memcmp(move->path, packed->path, move->path_len) == 0 &&
        memcmp(move->captured, packed->captured, move->capture_count) == 0;
}
#endif

static void compact_tt_move(NativeCompactMove *output, const Move *move) {
    memset(output, 0, sizeof(*output));
    uint8_t low_path_count = move->path_len < 12 ? move->path_len : 12;
    for (uint8_t index = 0; index < low_path_count; ++index) {
        output->path_low |=
            (uint64_t)(move->path[index] & 31) << (index * 5);
    }
    for (uint8_t index = 12; index < move->path_len; ++index) {
        output->path_high_meta |=
            (uint32_t)(move->path[index] & 31) << ((index - 12) * 5);
    }
    uint8_t low_capture_count =
        move->capture_count < 12 ? move->capture_count : 12;
    for (uint8_t index = 0; index < low_capture_count; ++index) {
        output->captured_low |=
            (uint64_t)(move->captured[index] & 31) << (index * 5);
    }
    for (uint8_t index = 12; index < move->capture_count; ++index) {
        output->captured_high_meta |=
            (uint32_t)(move->captured[index] & 31) << ((index - 12) * 5);
    }
    output->path_high_meta |= (uint32_t)move->path_len << 25;
    output->path_high_meta |= (uint32_t)(move->promotes != 0) << 30;
    output->captured_high_meta |= (uint32_t)move->capture_count << 20;
}

static bool same_compact_tt_move(
    const Move *move,
    const NativeCompactMove *compact
) {
    uint8_t path_len = (uint8_t)((compact->path_high_meta >> 25) & 31);
    uint8_t capture_count =
        (uint8_t)((compact->captured_high_meta >> 20) & 31);
    uint8_t promotes = (uint8_t)((compact->path_high_meta >> 30) & 1);
    if (
        move->path_len != path_len ||
        move->capture_count != capture_count ||
        move->promotes != promotes
    ) {
        return false;
    }
    for (uint8_t index = 0; index < move->path_len; ++index) {
        uint8_t square = index < 12
            ? (uint8_t)((compact->path_low >> (index * 5)) & 31)
            : (uint8_t)(
                (compact->path_high_meta >> ((index - 12) * 5)) & 31
            );
        if (move->path[index] != square) return false;
    }
    for (uint8_t index = 0; index < move->capture_count; ++index) {
        uint8_t square = index < 12
            ? (uint8_t)((compact->captured_low >> (index * 5)) & 31)
            : (uint8_t)(
                (compact->captured_high_meta >> ((index - 12) * 5)) & 31
            );
        if (move->captured[index] != square) return false;
    }
    return true;
}

static void expand_compact_tt_move(
    Move *output,
    const NativeCompactMove *compact
) {
    memset(&output->next, 0, sizeof(output->next));
    output->path_len = (uint8_t)((compact->path_high_meta >> 25) & 31);
    output->capture_count =
        (uint8_t)((compact->captured_high_meta >> 20) & 31);
    output->promotes = (uint8_t)((compact->path_high_meta >> 30) & 1);
    uint8_t low_path_count = output->path_len < 12 ? output->path_len : 12;
    for (uint8_t index = 0; index < low_path_count; ++index) {
        output->path[index] =
            (uint8_t)((compact->path_low >> (index * 5)) & 31);
    }
    for (uint8_t index = 12; index < output->path_len; ++index) {
        output->path[index] = (uint8_t)(
            (compact->path_high_meta >> ((index - 12) * 5)) & 31
        );
    }
    uint8_t low_capture_count =
        output->capture_count < 12 ? output->capture_count : 12;
    for (uint8_t index = 0; index < low_capture_count; ++index) {
        output->captured[index] =
            (uint8_t)((compact->captured_low >> (index * 5)) & 31);
    }
    for (uint8_t index = 12; index < output->capture_count; ++index) {
        output->captured[index] = (uint8_t)(
            (compact->captured_high_meta >> ((index - 12) * 5)) & 31
        );
    }
}

static bool generate_search_moves(
    NativeSearchContext *context,
    Position position,
    int ply,
    MoveList **moves
) {
    if (context->workspace[ply] == NULL) {
        context->workspace[ply] = malloc(sizeof(*context->workspace[ply]));
        if (context->workspace[ply] == NULL) {
            context->allocation_failed = true;
            context->stopped = true;
            return false;
        }
        ++context->workspace_count;
    }
    generate_moves(position, context->workspace[ply]);
    SEARCH_TELEMETRY_INC(context, movegen_calls);
    SEARCH_TELEMETRY_ADD(
        context, moves_generated, context->workspace[ply]->count
    );
    *moves = context->workspace[ply];
    return true;
}

#if MAKHOS_EARLY_TT_CUTOFF
/*
 * Determine terminality without materializing every legal move.  A first
 * capture is enough: every capture removes a piece, so its mandatory sequence
 * must eventually end in a complete legal move.  For a flying king, one empty
 * adjacent square is likewise enough to prove that a quiet landing exists.
 * Keep this logic beside the search-only optimization; generate_moves remains
 * the authoritative move generator.
 */
static bool native_has_capture(Position position) {
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
    uint32_t own = pieces_for(position, position.turn);
    uint32_t enemy = pieces_for(position, other(position.turn));
    uint32_t occupancy = occupied(position);
    uint32_t remaining = own;

    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        bool king = (position.kings & bit_at(square)) != 0;
        int row;
        int col;
        index_to_coord(square, &row, &col);
        int begin = king ? 0 : (position.turn == RED ? 2 : 0);
        int end = king ? 4 : (position.turn == RED ? 4 : 2);

        for (int direction_index = begin; direction_index < end; ++direction_index) {
            int dr = directions[direction_index][0];
            int dc = directions[direction_index][1];
            if (!king) {
                int captured = coord_to_index(row + dr, col + dc);
                int landing = coord_to_index(row + 2 * dr, col + 2 * dc);
                if (
                    captured >= 0 && landing >= 0 &&
                    (enemy & bit_at(captured)) != 0 &&
                    (occupancy & bit_at(landing)) == 0
                ) {
                    return true;
                }
                continue;
            }

            int scan_row = row + dr;
            int scan_col = col + dc;
            while (true) {
                int target = coord_to_index(scan_row, scan_col);
                if (target < 0) break;
                uint32_t target_bit = bit_at(target);
                if ((occupancy & target_bit) == 0) {
                    scan_row += dr;
                    scan_col += dc;
                    continue;
                }
                if ((enemy & target_bit) != 0) {
                    int landing = coord_to_index(scan_row + dr, scan_col + dc);
                    if (
                        landing >= 0 &&
                        (occupancy & bit_at(landing)) == 0
                    ) {
                        return true;
                    }
                }
                break;
            }
        }
    }

    return false;
}

#if MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY && MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
/* Qsearch calls capture existence at every captureless leaf.  Preserve the
 * coordinate reference helper above for normal-search terminality; this
 * scoped version replaces only the man coordinate conversion with the same
 * precomputed jump geometry already used by qsearch capture generation.
 * Kings deliberately retain the coordinate scan here until a separately
 * measured, directly differential-tested king-existence implementation exists. */
static bool qsearch_has_capture_fast_man_geometry(Position position) {
    static const int8_t captured_steps[4][32] = {
        {-1, -1, -1, -1, -1, 0, 1, 2, 4, 5, 6, 7, -1, 8, 9, 10, 12, 13, 14, 15, -1, 16, 17, 18, 20, 21, 22, 23, -1, 24, 25, 26},
        {-1, -1, -1, -1, 0, 1, 2, 3, 5, 6, 7, -1, 8, 9, 10, 11, 13, 14, 15, -1, 16, 17, 18, 19, 21, 22, 23, -1, 24, 25, 26, 27},
        {4, 5, 6, 7, -1, 8, 9, 10, 12, 13, 14, 15, -1, 16, 17, 18, 20, 21, 22, 23, -1, 24, 25, 26, 28, 29, 30, 31, -1, -1, -1, -1},
        {5, 6, 7, -1, 8, 9, 10, 11, 13, 14, 15, -1, 16, 17, 18, 19, 21, 22, 23, -1, 24, 25, 26, 27, 29, 30, 31, -1, -1, -1, -1, -1}
    };
    static const int8_t landing_steps[4][32] = {
        {-1, -1, -1, -1, -1, -1, -1, -1, -1, 0, 1, 2, -1, 4, 5, 6, -1, 8, 9, 10, -1, 12, 13, 14, -1, 16, 17, 18, -1, 20, 21, 22},
        {-1, -1, -1, -1, -1, -1, -1, -1, 1, 2, 3, -1, 5, 6, 7, -1, 9, 10, 11, -1, 13, 14, 15, -1, 17, 18, 19, -1, 21, 22, 23, -1},
        {-1, 8, 9, 10, -1, 12, 13, 14, -1, 16, 17, 18, -1, 20, 21, 22, -1, 24, 25, 26, -1, 28, 29, 30, -1, -1, -1, -1, -1, -1, -1, -1},
        {9, 10, 11, -1, 13, 14, 15, -1, 17, 18, 19, -1, 21, 22, 23, -1, 25, 26, 27, -1, 29, 30, 31, -1, -1, -1, -1, -1, -1, -1, -1, -1}
    };
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
    uint32_t own = pieces_for(position, position.turn);
    uint32_t enemy = pieces_for(position, other(position.turn));
    uint32_t occupancy = occupied(position);
    uint32_t remaining = own & ~position.kings;
    int begin = position.turn == RED ? 2 : 0;
    int end = position.turn == RED ? 4 : 2;

    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        for (int direction_index = begin; direction_index < end; ++direction_index) {
            int captured = captured_steps[direction_index][square];
            int landing = landing_steps[direction_index][square];
            if (
                captured >= 0 && landing >= 0 &&
                (enemy & bit_at(captured)) != 0 &&
                (occupancy & bit_at(landing)) == 0
            ) {
                return true;
            }
        }
    }

    remaining = own & position.kings;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        int row;
        int col;
        index_to_coord(square, &row, &col);
        for (int direction_index = 0; direction_index < 4; ++direction_index) {
            int dr = directions[direction_index][0];
            int dc = directions[direction_index][1];
            int scan_row = row + dr;
            int scan_col = col + dc;
            while (true) {
                int target = coord_to_index(scan_row, scan_col);
                if (target < 0) break;
                uint32_t target_bit = bit_at(target);
                if ((occupancy & target_bit) == 0) {
                    scan_row += dr;
                    scan_col += dc;
                    continue;
                }
                if ((enemy & target_bit) != 0) {
                    int landing = coord_to_index(scan_row + dr, scan_col + dc);
                    if (
                        landing >= 0 &&
                        (occupancy & bit_at(landing)) == 0
                    ) {
                        return true;
                    }
                }
                break;
            }
        }
    }

    return false;
}
#endif

static bool native_has_legal_move(Position position) {
    if (native_has_capture(position)) return true;
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
    uint32_t own = pieces_for(position, position.turn);
    uint32_t occupancy = occupied(position);
    uint32_t remaining = own;

    remaining = own;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        bool king = (position.kings & bit_at(square)) != 0;
        int row;
        int col;
        index_to_coord(square, &row, &col);
        int begin = king ? 0 : (position.turn == RED ? 2 : 0);
        int end = king ? 4 : (position.turn == RED ? 4 : 2);
        for (int direction_index = begin; direction_index < end; ++direction_index) {
            int landing = coord_to_index(
                row + directions[direction_index][0],
                col + directions[direction_index][1]
            );
            if (landing >= 0 && (occupancy & bit_at(landing)) == 0) {
                return true;
            }
        }
    }
    return false;
}

/* Qsearch's capture-only path has already proved that no capture exists.
 * Check only quiet mobility before declaring a terminal loss; rescanning all
 * capture rays here would duplicate the work just performed by the capture
 * generator.  This helper is intentionally search-only and does not replace
 * the authoritative full move generator. */
static bool native_has_quiet_move(Position position) {
#if MAKHOS_FAST_QUIET_MOBILITY
    static const uint32_t red_targets[32] = {
        UINT32_C(0x00000030), UINT32_C(0x00000060), UINT32_C(0x000000c0), UINT32_C(0x00000080),
        UINT32_C(0x00000100), UINT32_C(0x00000300), UINT32_C(0x00000600), UINT32_C(0x00000c00),
        UINT32_C(0x00003000), UINT32_C(0x00006000), UINT32_C(0x0000c000), UINT32_C(0x00008000),
        UINT32_C(0x00010000), UINT32_C(0x00030000), UINT32_C(0x00060000), UINT32_C(0x000c0000),
        UINT32_C(0x00300000), UINT32_C(0x00600000), UINT32_C(0x00c00000), UINT32_C(0x00800000),
        UINT32_C(0x01000000), UINT32_C(0x03000000), UINT32_C(0x06000000), UINT32_C(0x0c000000),
        UINT32_C(0x30000000), UINT32_C(0x60000000), UINT32_C(0xc0000000), UINT32_C(0x80000000),
        UINT32_C(0x00000000), UINT32_C(0x00000000), UINT32_C(0x00000000), UINT32_C(0x00000000)
    };
    static const uint32_t black_targets[32] = {
        UINT32_C(0x00000000), UINT32_C(0x00000000), UINT32_C(0x00000000), UINT32_C(0x00000000),
        UINT32_C(0x00000001), UINT32_C(0x00000003), UINT32_C(0x00000006), UINT32_C(0x0000000c),
        UINT32_C(0x00000030), UINT32_C(0x00000060), UINT32_C(0x000000c0), UINT32_C(0x00000080),
        UINT32_C(0x00000100), UINT32_C(0x00000300), UINT32_C(0x00000600), UINT32_C(0x00000c00),
        UINT32_C(0x00003000), UINT32_C(0x00006000), UINT32_C(0x0000c000), UINT32_C(0x00008000),
        UINT32_C(0x00010000), UINT32_C(0x00030000), UINT32_C(0x00060000), UINT32_C(0x000c0000),
        UINT32_C(0x00300000), UINT32_C(0x00600000), UINT32_C(0x00c00000), UINT32_C(0x00800000),
        UINT32_C(0x01000000), UINT32_C(0x03000000), UINT32_C(0x06000000), UINT32_C(0x0c000000)
    };
    static const uint32_t king_targets[32] = {
        UINT32_C(0x00000030), UINT32_C(0x00000060), UINT32_C(0x000000c0), UINT32_C(0x00000080),
        UINT32_C(0x00000101), UINT32_C(0x00000303), UINT32_C(0x00000606), UINT32_C(0x00000c0c),
        UINT32_C(0x00003030), UINT32_C(0x00006060), UINT32_C(0x0000c0c0), UINT32_C(0x00008080),
        UINT32_C(0x00010100), UINT32_C(0x00030300), UINT32_C(0x00060600), UINT32_C(0x000c0c00),
        UINT32_C(0x00303000), UINT32_C(0x00606000), UINT32_C(0x00c0c000), UINT32_C(0x00808000),
        UINT32_C(0x01010000), UINT32_C(0x03030000), UINT32_C(0x06060000), UINT32_C(0x0c0c0000),
        UINT32_C(0x30300000), UINT32_C(0x60600000), UINT32_C(0xc0c00000), UINT32_C(0x80800000),
        UINT32_C(0x01000000), UINT32_C(0x03000000), UINT32_C(0x06000000), UINT32_C(0x0c000000)
    };
    uint32_t own = pieces_for(position, position.turn);
    uint32_t occupancy = occupied(position);
    uint32_t remaining = own & ~position.kings;
    const uint32_t *man_targets = position.turn == RED
        ? red_targets
        : black_targets;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        if ((man_targets[square] & ~occupancy) != 0) return true;
    }
    remaining = own & position.kings;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        if ((king_targets[square] & ~occupancy) != 0) return true;
    }
    return false;
#else
    static const int directions[4][2] = {
        {-1, -1}, {-1, 1}, {1, -1}, {1, 1}
    };
    uint32_t own = pieces_for(position, position.turn);
    uint32_t occupancy = occupied(position);
    uint32_t remaining = own;

    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        bool king = (position.kings & bit_at(square)) != 0;
        int row;
        int col;
        index_to_coord(square, &row, &col);
        int begin = king ? 0 : (position.turn == RED ? 2 : 0);
        int end = king ? 4 : (position.turn == RED ? 4 : 2);
        for (int direction_index = begin; direction_index < end; ++direction_index) {
            int landing = coord_to_index(
                row + directions[direction_index][0],
                col + directions[direction_index][1]
            );
            if (landing >= 0 && (occupancy & bit_at(landing)) == 0) {
                return true;
            }
        }
    }
    return false;
#endif
}
#endif

static void pack_move(MakhosPackedMove *output, const Move *move) {
    memset(output, 0, sizeof(*output));
    output->path_len = move->path_len;
    output->capture_count = move->capture_count;
    output->promotes = move->promotes;
    memcpy(output->path, move->path, move->path_len);
    memcpy(output->captured, move->captured, move->capture_count);
}

static void store_native_pv_move(NativePVMove *output, const Move *move) {
#if MAKHOS_COMPACT_PV
    memcpy(output, &move->path[0], sizeof(*output));
#else
    *output = *move;
#endif
}

static void pack_native_pv_move(
    MakhosPackedMove *output,
    const NativePVMove *move
) {
#if MAKHOS_COMPACT_PV
    *output = *move;
#else
    pack_move(output, move);
#endif
}

static uint64_t search_mix64(uint64_t value) {
    value ^= value >> 30;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value *= UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
}

static uint64_t search_position_board_component(Position position) {
    return search_mix64(((uint64_t)position.black << 32) | position.red);
}

static uint64_t search_position_state_component(Position position) {
    return
        ((uint64_t)position.kings << 17) |
        ((uint64_t)position.turn << 9) |
        position.reversible_plies;
}

static uint64_t search_position_key_from_components(
    uint64_t board_component,
    uint64_t state_component
) {
    uint64_t key = board_component ^ search_mix64(state_component);
    return key == 0 ? UINT64_C(1) : key;
}

static uint64_t search_position_state_input(uint64_t state) {
    const uint64_t state_salt = UINT64_C(0x9e3779b97f4a7c15);
#if MAKHOS_STRICT_SEARCH_POSITION_KEY
#if MAKHOS_STRICT_SEARCH_POSITION_KEY_COMPAT
    /* This matches strict XOR on the king/clock fields, but preserves the
     * redundant BLACK turn bit.  RED=1 and BLACK=2 remain injective through
     * turn bit 9, while common Black roots retain their legacy key. */
    return (state | state_salt) ^
        (state & (state_salt &
            ((UINT64_C(0xffffffff) << 17) | UINT64_C(0xff))));
#else
    /* The packed fields must be salted bijectively.  OR would erase every
     * state bit that is also set in the salt, creating deterministic TT
     * aliases between different king masks and reversible clocks. */
    return state ^ state_salt;
#endif
#else
    return state | state_salt;
#endif
}

static uint64_t search_position_key(Position position) {
    return search_position_key_from_components(
        search_position_board_component(position),
        search_position_state_input(search_position_state_component(position))
    );
}

#if MAKHOS_QSEARCH_TT_CENSUS
/* The census is deliberately keyed with the injective state encoding even
 * when the production main TT is still using its legacy OR-salt key.  This
 * prevents the measurement table from turning a correctness defect into a
 * false transposition signal. */
static uint64_t search_qtt_census_key(Position position) {
    return search_position_key_from_components(
        search_position_board_component(position),
        search_position_state_component(position) ^
            UINT64_C(0x9e3779b97f4a7c15)
    );
}

static void record_qtt_census(
    NativeSearchContext *context,
    Position position
) {
    if (
        context->qtt_census == NULL ||
        context->qtt_census_count == 0 ||
        context->repetition_limit != 0
    ) {
        return;
    }
    uint64_t key = search_qtt_census_key(position);
    size_t index = (size_t)(key & (context->qtt_census_count - 1));
    NativeQttCensusEntry *entry = &context->qtt_census[index];
    ++context->qtt_census_telemetry.capture_nodes;
    ++context->qtt_census_telemetry.probes;
    if (entry->generation == context->generation) {
        if (entry->key == key) {
            ++context->qtt_census_telemetry.same_key_hits;
        } else if (entry->key != 0) {
            ++context->qtt_census_telemetry.collisions;
        }
    }
    entry->key = key;
    entry->generation = context->generation;
    ++context->qtt_census_telemetry.stores;
}
#endif

#if MAKHOS_STRICT_SEARCH_POSITION_KEY_LEGACY_TT_INDEX
static void search_position_key_with_legacy_tt_index(
    Position position,
    uint64_t *key,
    uint64_t *legacy_index_key
) {
    const uint64_t state_salt = UINT64_C(0x9e3779b97f4a7c15);
    uint64_t board_component = search_position_board_component(position);
    uint64_t state = search_position_state_component(position);
    *key = search_position_key_from_components(
        board_component, search_position_state_input(state)
    );
    *legacy_index_key = search_position_key_from_components(
        board_component, state | state_salt
    );
}
#endif

static uint64_t search_repetition_key(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    uint8_t turn
) {
    uint64_t key = search_mix64(((uint64_t)black << 32) | red);
    key ^= search_mix64(
        ((uint64_t)kings << 17) |
        ((uint64_t)turn << 9) |
        UINT64_C(0xd1b54a32d192ed03)
    );
    return key == 0 ? UINT64_C(1) : key;
}

static bool same_history_entry(
    const MakhosHistoryEntry *entry,
    Position position
) {
    return
        entry->red == position.red &&
        entry->black == position.black &&
        entry->kings == position.kings &&
        entry->turn == position.turn;
}

static void prepare_history_lookup(NativeSearchContext *context) {
    context->history_lookup_ready = false;
    if (
        context->repetition_limit == 0 ||
        context->initial_history == NULL ||
        context->initial_history_count < 32
    ) {
        return;
    }
    if ((size_t)context->initial_history_count > SIZE_MAX / 2) return;
    size_t wanted = 16;
    while (wanted < (size_t)context->initial_history_count * 2) {
        if (wanted > SIZE_MAX / 2) return;
        wanted *= 2;
    }
    if (wanted > SIZE_MAX / sizeof(*context->history_lookup)) return;
    if (context->history_lookup_capacity < wanted) {
        NativeHistoryLookupEntry *resized = realloc(
            context->history_lookup,
            wanted * sizeof(*resized)
        );
        if (resized == NULL) return;
        context->history_lookup = resized;
        context->history_lookup_capacity = wanted;
    }
    memset(
        context->history_lookup,
        0,
        context->history_lookup_capacity * sizeof(*context->history_lookup)
    );
    size_t mask = context->history_lookup_capacity - 1;
    for (uint32_t index = 0; index < context->initial_history_count; ++index) {
        MakhosHistoryEntry entry = context->initial_history[index];
        uint64_t key = search_repetition_key(
            entry.red, entry.black, entry.kings, entry.turn
        );
        size_t slot = (size_t)key & mask;
        while (context->history_lookup[slot].key != 0) {
            const MakhosHistoryEntry *stored =
                &context->history_lookup[slot].entry;
            if (
                stored->red == entry.red && stored->black == entry.black &&
                stored->kings == entry.kings && stored->turn == entry.turn
            ) {
                /* Preserve the original first-match behavior for duplicates. */
                key = 0;
                break;
            }
            slot = (slot + 1) & mask;
        }
        if (key != 0) {
            context->history_lookup[slot].key = key;
            context->history_lookup[slot].entry = entry;
        }
    }
    context->history_lookup_ready = true;
}

static int search_repetition_count(
    const NativeSearchContext *context,
    Position position,
    int ply
#if MAKHOS_REPETITION_CENSUS
    ,
    bool qsearch
#endif
) {
    int count = 0;
#if MAKHOS_REPETITION_CENSUS
    NativeSearchContext *mutable_context = (NativeSearchContext *)context;
    MakhosRepetitionCensusTelemetry *census =
        &mutable_context->repetition_census_telemetry;
    ++census->calls;
    if (qsearch) {
        ++census->qsearch_calls;
    } else {
        ++census->normal_calls;
    }
#endif
    if (context->history_lookup_ready) {
#if MAKHOS_REPETITION_CENSUS
        ++census->initial_hash_calls;
#endif
        uint64_t key = search_repetition_key(
            position.red, position.black, position.kings, position.turn
        );
        size_t mask = context->history_lookup_capacity - 1;
        size_t slot = (size_t)key & mask;
        while (context->history_lookup[slot].key != 0) {
#if MAKHOS_REPETITION_CENSUS
            ++census->initial_hash_probes;
#endif
            const MakhosHistoryEntry *entry =
                &context->history_lookup[slot].entry;
            if (same_history_entry(entry, position)) {
                count += entry->count;
#if MAKHOS_REPETITION_CENSUS
                ++census->initial_hits;
#endif
                break;
            }
            slot = (slot + 1) & mask;
        }
    } else if (context->initial_history != NULL) {
#if MAKHOS_REPETITION_CENSUS
        ++census->initial_linear_calls;
#endif
        for (uint32_t index = 0; index < context->initial_history_count; ++index) {
#if MAKHOS_REPETITION_CENSUS
            ++census->initial_linear_entries;
#endif
            const MakhosHistoryEntry *entry = &context->initial_history[index];
            if (same_history_entry(entry, position)) {
                count += entry->count;
#if MAKHOS_REPETITION_CENSUS
                ++census->initial_hits;
#endif
                break;
            }
        }
    }
    int line_begin = context->initial_history != NULL ? 1 : 0;
    int earliest = ply - (int)position.reversible_plies;
    if (earliest < line_begin) earliest = line_begin;
#if MAKHOS_REPETITION_CENSUS
    uint64_t line_entries = 0;
#endif
    for (int index = ply; index >= earliest; index -= 2) {
#if MAKHOS_REPETITION_CENSUS
        ++line_entries;
#endif
        if (same_search_position(context->line[index], position)) {
            ++count;
#if MAKHOS_REPETITION_CENSUS
            ++census->line_matches;
#endif
        }
    }
#if MAKHOS_REPETITION_CENSUS
    census->line_entries += line_entries;
    if (line_entries == 0) {
        ++census->span_zero;
    } else if (line_entries <= 4) {
        ++census->span_1_4;
    } else if (line_entries <= 16) {
        ++census->span_5_16;
    } else {
        ++census->span_17_plus;
    }
    if (count >= context->repetition_limit) {
        ++census->draw_hits;
    }
#endif
    return count;
}

static double search_now_seconds(void) {
#if defined(_WIN32)
    LARGE_INTEGER counter;
    LARGE_INTEGER frequency;
    if (
        QueryPerformanceFrequency(&frequency) != 0 &&
        QueryPerformanceCounter(&counter) != 0
    ) {
        return (double)counter.QuadPart / (double)frequency.QuadPart;
    }
#else
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) == 0) {
        return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
    }
#endif
    return (double)clock() / (double)CLOCKS_PER_SEC;
}

static bool search_time_expired(NativeSearchContext *context) {
    if (context->stopped) return true;
#if MAKHOS_NATIVE_LAZY_SMP
    if (
        context->lazy_smp_control != NULL &&
        atomic_load_explicit(
            &context->lazy_smp_control->stop,
            memory_order_acquire
        )
    ) {
        context->stopped = true;
        return true;
    }
#endif
#if MAKHOS_NATIVE_ROOT_PVS_SMP
    if (
        context->root_pvs_control != NULL &&
        atomic_load_explicit(
            &context->root_pvs_control->stop,
            memory_order_acquire
        )
    ) {
        context->stopped = true;
        return true;
    }
#endif
    if (
        context->has_deadline &&
        (context->nodes & UINT64_C(1023)) == 0 &&
        search_now_seconds() >= context->deadline
    ) {
        context->stopped = true;
#if MAKHOS_NATIVE_LAZY_SMP
        if (context->lazy_smp_control != NULL) {
            atomic_store_explicit(
                &context->lazy_smp_control->stop,
                true,
                memory_order_release
            );
        }
#endif
    }
    return context->stopped;
}

static const int16_t search_red_man_score[32] = {
    111, 111, 111, 111, 101, 107, 107, 107,
    114, 118, 118, 108, 118, 128, 128, 124,
    137, 141, 141, 131, 151, 161, 161, 157,
    182, 182, 182, 176, 96, 96, 96, 96
};
static const int16_t search_black_man_score[32] = {
    96, 96, 96, 96, 176, 182, 182, 182,
    157, 161, 161, 151, 131, 141, 141, 137,
    124, 128, 128, 118, 108, 118, 118, 114,
    107, 107, 107, 101, 111, 111, 111, 111
};
/* Includes the PST edge penalty and the king-activity edge penalty. */
static const int16_t search_king_score[32] = {
    310, 310, 310, 322, 310, 330, 330, 342,
    330, 350, 362, 310, 310, 350, 362, 330,
    330, 362, 350, 310, 310, 362, 350, 330,
    342, 330, 330, 310, 322, 310, 310, 310
};
static const uint32_t search_red_support[32] = {
    0, 0, 0, 0,
    UINT32_C(0x00000001), UINT32_C(0x00000003), UINT32_C(0x00000006), UINT32_C(0x0000000c),
    UINT32_C(0x00000030), UINT32_C(0x00000060), UINT32_C(0x000000c0), UINT32_C(0x00000080),
    UINT32_C(0x00000100), UINT32_C(0x00000300), UINT32_C(0x00000600), UINT32_C(0x00000c00),
    UINT32_C(0x00003000), UINT32_C(0x00006000), UINT32_C(0x0000c000), UINT32_C(0x00008000),
    UINT32_C(0x00010000), UINT32_C(0x00030000), UINT32_C(0x00060000), UINT32_C(0x000c0000),
    UINT32_C(0x00300000), UINT32_C(0x00600000), UINT32_C(0x00c00000), UINT32_C(0x00800000),
    UINT32_C(0x01000000), UINT32_C(0x03000000), UINT32_C(0x06000000), UINT32_C(0x0c000000)
};
static const uint32_t search_black_support[32] = {
    UINT32_C(0x00000030), UINT32_C(0x00000060), UINT32_C(0x000000c0), UINT32_C(0x00000080),
    UINT32_C(0x00000100), UINT32_C(0x00000300), UINT32_C(0x00000600), UINT32_C(0x00000c00),
    UINT32_C(0x00003000), UINT32_C(0x00006000), UINT32_C(0x0000c000), UINT32_C(0x00008000),
    UINT32_C(0x00010000), UINT32_C(0x00030000), UINT32_C(0x00060000), UINT32_C(0x000c0000),
    UINT32_C(0x00300000), UINT32_C(0x00600000), UINT32_C(0x00c00000), UINT32_C(0x00800000),
    UINT32_C(0x01000000), UINT32_C(0x03000000), UINT32_C(0x06000000), UINT32_C(0x0c000000),
    UINT32_C(0x30000000), UINT32_C(0x60000000), UINT32_C(0xc0000000), UINT32_C(0x80000000),
    0, 0, 0, 0
};
static const uint32_t search_red_passed_cone[32] = {
    UINT32_C(0x08844230), UINT32_C(0x00089560), UINT32_C(0x00112ac0), UINT32_C(0x11224480),
    UINT32_C(0x84422100), UINT32_C(0x08845300), UINT32_C(0x0019a600), UINT32_C(0x11224c00),
    UINT32_C(0x84423000), UINT32_C(0x08956000), UINT32_C(0x112ac000), UINT32_C(0x22448000),
    UINT32_C(0x42210000), UINT32_C(0x84530000), UINT32_C(0x19a60000), UINT32_C(0x224c0000),
    UINT32_C(0x42300000), UINT32_C(0x95600000), UINT32_C(0x2ac00000), UINT32_C(0x44800000),
    UINT32_C(0x21000000), UINT32_C(0x53000000), UINT32_C(0xa6000000), UINT32_C(0x4c000000),
    UINT32_C(0x30000000), UINT32_C(0x60000000), UINT32_C(0xc0000000), UINT32_C(0x80000000),
    0, 0, 0, 0
};
static const uint32_t search_black_passed_cone[32] = {
    0, 0, 0, 0,
    UINT32_C(0x00000001), UINT32_C(0x00000003), UINT32_C(0x00000006), UINT32_C(0x0000000c),
    UINT32_C(0x00000032), UINT32_C(0x00000065), UINT32_C(0x000000ca), UINT32_C(0x00000084),
    UINT32_C(0x00000122), UINT32_C(0x00000354), UINT32_C(0x000006a9), UINT32_C(0x00000c42),
    UINT32_C(0x00003244), UINT32_C(0x00006598), UINT32_C(0x0000ca21), UINT32_C(0x00008442),
    UINT32_C(0x00012244), UINT32_C(0x00035488), UINT32_C(0x0006a910), UINT32_C(0x000c4221),
    UINT32_C(0x00324488), UINT32_C(0x00659800), UINT32_C(0x00ca2110), UINT32_C(0x00844221),
    UINT32_C(0x01224488), UINT32_C(0x03548800), UINT32_C(0x06a91000), UINT32_C(0x0c422110)
};
static const uint32_t search_diagonal_neighbors[32] = {
    UINT32_C(0x00000030), UINT32_C(0x00000060), UINT32_C(0x000000c0), UINT32_C(0x00000080),
    UINT32_C(0x00000101), UINT32_C(0x00000303), UINT32_C(0x00000606), UINT32_C(0x00000c0c),
    UINT32_C(0x00003030), UINT32_C(0x00006060), UINT32_C(0x0000c0c0), UINT32_C(0x00008080),
    UINT32_C(0x00010100), UINT32_C(0x00030300), UINT32_C(0x00060600), UINT32_C(0x000c0c00),
    UINT32_C(0x00303000), UINT32_C(0x00606000), UINT32_C(0x00c0c000), UINT32_C(0x00808000),
    UINT32_C(0x01010000), UINT32_C(0x03030000), UINT32_C(0x06060000), UINT32_C(0x0c0c0000),
    UINT32_C(0x30300000), UINT32_C(0x60600000), UINT32_C(0xc0c00000), UINT32_C(0x80800000),
    UINT32_C(0x01000000), UINT32_C(0x03000000), UINT32_C(0x06000000), UINT32_C(0x0c000000)
};
static const int16_t search_red_passed_bonus[32] = {
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    30, 30, 30, 30, 50, 50, 50, 50, 70, 70, 70, 70, 90, 90, 90, 90
};
static const int16_t search_black_passed_bonus[32] = {
    90, 90, 90, 90, 70, 70, 70, 70, 50, 50, 50, 50, 30, 30, 30, 30,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

static int native_evaluate(Position position, uint8_t perspective) {
    uint32_t red_men = position.red & ~position.kings;
    uint32_t black_men = position.black & ~position.kings;
    uint32_t red_kings = position.red & position.kings;
    uint32_t black_kings = position.black & position.kings;
    int red_man_count = native_count_bits(red_men);
    int black_man_count = native_count_bits(black_men);
    int red_king_count = native_count_bits(red_kings);
    int black_king_count = native_count_bits(black_kings);
    int red_total = red_man_count + red_king_count;
    int black_total = black_man_count + black_king_count;
    if (red_total == 0) return perspective == RED ? -999999 : 999999;
    if (black_total == 0) return perspective == RED ? 999999 : -999999;

    int red_score = 0;
    int black_score = 0;
    uint32_t remaining = red_men;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        red_score += search_red_man_score[square];
        if ((position.red & search_red_support[square]) != 0) {
            red_score += 8;
        }
        if (
            search_red_passed_bonus[square] != 0 &&
            (position.black & search_red_passed_cone[square]) == 0
        ) {
            red_score += search_red_passed_bonus[square];
        }
    }
    remaining = black_men;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        black_score += search_black_man_score[square];
        if ((position.black & search_black_support[square]) != 0) {
            black_score += 8;
        }
        if (
            search_black_passed_bonus[square] != 0 &&
            (position.red & search_black_passed_cone[square]) == 0
        ) {
            black_score += search_black_passed_bonus[square];
        }
    }

    if (black_man_count > 0) {
        int back_count = native_count_bits(red_men & UINT32_C(0x0000000f));
        if (back_count >= 2) red_score += 15;
    }
    if (red_man_count > 0) {
        int back_count = native_count_bits(black_men & UINT32_C(0xf0000000));
        if (back_count >= 2) black_score += 15;
    }

    int material_difference =
        red_man_count * 100 + red_king_count * 330 -
        black_man_count * 100 - black_king_count * 330;
    int total_pieces = red_total + black_total;
    if (total_pieces <= 8 && material_difference != 0) {
        int simplification = (16 - total_pieces) * 6;
        if (material_difference > 0) red_score += simplification;
        else black_score += simplification;
    }

    uint32_t empty = ~occupied(position);
    remaining = red_kings;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        red_score += search_king_score[square];
        red_score += native_count_bits(
            search_diagonal_neighbors[square] & empty
        ) * 4;
    }
    remaining = black_kings;
    while (remaining != 0) {
        int square = pop_lsb(&remaining);
        black_score += search_king_score[square];
        black_score += native_count_bits(
            search_diagonal_neighbors[square] & empty
        ) * 4;
    }

#if MAKHOS_ENDGAME_KING_VALUE != 330 || MAKHOS_ENDGAME_KING_EDGE != -12
    /*
     * Exact 4/5/6-piece WDL labels support different Thai-king endgame terms.
     * Apply them fully through seven pieces and taper back to the accepted
     * middlegame values by thirteen pieces.  Compile-time switches keep each
     * strength experiment isolated from the production-default evaluator.
     */
    if (total_pieces <= 12) {
        int blend = total_pieces <= 7 ? 6 : 13 - total_pieces;
#if MAKHOS_ENDGAME_KING_VALUE != 330
        int correction = (MAKHOS_ENDGAME_KING_VALUE - 330) * blend / 6;
        red_score += red_king_count * correction;
        black_score += black_king_count * correction;
#endif
#if MAKHOS_ENDGAME_KING_EDGE != -12
        int edge_correction = (MAKHOS_ENDGAME_KING_EDGE + 12) * blend / 6;
        red_score += native_count_bits(red_kings & UINT32_C(0xf818181f))
            * edge_correction;
        black_score += native_count_bits(black_kings & UINT32_C(0xf818181f))
            * edge_correction;
#endif
    }
#endif

#if MAKHOS_FITTED_ENDGAME_EVAL
    /*
     * Exact-WDL fit, restricted to the sampled 4/5/6-piece region.  The
     * fixed-point weights are rounded from build/exact_wdl_eval_fit_v1.json
     * and deliberately replace the complete handcrafted feature vector only
     * in this endgame gate; the accepted middlegame evaluator is untouched.
     */
    if (total_pieces <= 6) {
        enum {
            FIT_SCALE = 1000,
            FIT_KINGS = 204300,
            FIT_MAN_PST = 1116,
            FIT_KING_PST = -219,
            FIT_SUPPORT = 835,
            FIT_BACK_RANK = 1283,
            FIT_PASSED = 610,
            FIT_SIMPLIFICATION = 1211,
            FIT_KING_EDGE = 30700,
            FIT_KING_MOBILITY = 10455
        };
        int red_man_pst = 0;
        int black_man_pst = 0;
        int red_support = 0;
        int black_support = 0;
        int red_passed = 0;
        int black_passed = 0;
        uint32_t fit_remaining = red_men;
        while (fit_remaining != 0) {
            int square = pop_lsb(&fit_remaining);
            red_man_pst += search_red_man_score[square] - 100;
            if ((position.red & search_red_support[square]) != 0) {
                ++red_support;
            }
            if (search_red_passed_bonus[square] != 0 &&
                (position.black & search_red_passed_cone[square]) == 0) {
                red_passed += search_red_passed_bonus[square];
            }
        }
        fit_remaining = black_men;
        while (fit_remaining != 0) {
            int square = pop_lsb(&fit_remaining);
            black_man_pst += search_black_man_score[square] - 100;
            if ((position.black & search_black_support[square]) != 0) {
                ++black_support;
            }
            if (search_black_passed_bonus[square] != 0 &&
                (position.red & search_black_passed_cone[square]) == 0) {
                black_passed += search_black_passed_bonus[square];
            }
        }
        int red_back_rank = black_man_count > 0 &&
            native_count_bits(red_men & UINT32_C(0x0000000f)) >= 2;
        int black_back_rank = red_man_count > 0 &&
            native_count_bits(black_men & UINT32_C(0xf0000000)) >= 2;
        int red_simplification = 0;
        int black_simplification = 0;
        if (material_difference != 0) {
            int simplification = 16 - total_pieces;
            if (material_difference > 0) red_simplification = simplification;
            else black_simplification = simplification;
        }
        int red_king_pst = 0;
        int black_king_pst = 0;
        int red_edge_count = 0;
        int black_edge_count = 0;
        int red_mobility = 0;
        int black_mobility = 0;
        fit_remaining = red_kings;
        while (fit_remaining != 0) {
            int square = pop_lsb(&fit_remaining);
            bool edge = (UINT32_C(0xf818181f) & bit_at(square)) != 0;
            int king_pst = search_king_score[square] - 330 + (edge ? 12 : 0);
            red_king_pst += king_pst;
            red_edge_count += edge;
            red_mobility += native_count_bits(
                search_diagonal_neighbors[square] & empty
            );
        }
        fit_remaining = black_kings;
        while (fit_remaining != 0) {
            int square = pop_lsb(&fit_remaining);
            bool edge = (UINT32_C(0xf818181f) & bit_at(square)) != 0;
            int king_pst = search_king_score[square] - 330 + (edge ? 12 : 0);
            black_king_pst += king_pst;
            black_edge_count += edge;
            black_mobility += native_count_bits(
                search_diagonal_neighbors[square] & empty
            );
        }
        int direction = perspective == RED ? 1 : -1;
        int men_feature = direction * (red_man_count - black_man_count);
        int kings_feature = direction * (red_king_count - black_king_count);
        int man_pst_feature = direction * (red_man_pst - black_man_pst);
        int king_pst_feature = direction * (red_king_pst - black_king_pst);
        int support_feature = direction * (red_support - black_support);
        int back_rank_feature = direction * (red_back_rank - black_back_rank);
        int passed_feature = direction * (red_passed - black_passed);
        int simplification_feature = direction *
            (red_simplification - black_simplification);
        int edge_score = direction *
            (-12 * red_edge_count + 12 * black_edge_count);
        int edge_feature = edge_score / -12;
        int mobility_feature = direction * (red_mobility - black_mobility);
        int64_t fitted_scaled =
            (int64_t)men_feature * 100 * FIT_SCALE +
            (int64_t)kings_feature * FIT_KINGS +
            (int64_t)man_pst_feature * FIT_MAN_PST +
            (int64_t)king_pst_feature * FIT_KING_PST +
            (int64_t)support_feature * FIT_SUPPORT +
            (int64_t)back_rank_feature * FIT_BACK_RANK +
            (int64_t)passed_feature * FIT_PASSED +
            (int64_t)simplification_feature * FIT_SIMPLIFICATION +
            (int64_t)edge_feature * FIT_KING_EDGE +
            (int64_t)mobility_feature * FIT_KING_MOBILITY;
        return (int)(fitted_scaled / FIT_SCALE);
    }
#endif

    int score = red_score - black_score;
    return perspective == RED ? score : -score;
}

static int native_search_evaluate(
    NativeSearchContext *context,
    Position position,
    uint8_t perspective,
    int ply
) {
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    return native_nnue_evaluate(context, position, perspective, ply);
#else
    (void)context;
    (void)ply;
    return native_evaluate(position, perspective);
#endif
}

static bool native_search_prepare_child(
    NativeSearchContext *context,
    Position child,
    int child_ply
) {
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    return native_nnue_prepare_child(context, child, child_ply);
#else
    (void)context;
    (void)child;
    (void)child_ply;
    return true;
#endif
}

static bool native_search_refresh_root(
    NativeSearchContext *context,
    Position root
) {
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    return native_nnue_refresh_root(context, root);
#else
    (void)context;
    (void)root;
    return true;
#endif
}

static int move_order_weight(
    NativeSearchContext *context,
    Position position,
    const Move *move,
    const Move *tt_move,
    int ply
) {
    if (tt_move != NULL && same_move(move, tt_move)) return 10000000;
    if (move->capture_count > 0) {
        int king_captures = 0;
        for (uint8_t index = 0; index < move->capture_count; ++index) {
            if ((position.kings & bit_at(move->captured[index])) != 0) {
                ++king_captures;
            }
        }
        return 1000000 + move->capture_count * 10000 + king_captures * 100;
    }
    if (move->promotes) return 500000;
    if (ply < MAKHOS_SEARCH_MAX_PLY) {
        for (uint8_t index = 0; index < context->killer_count[ply]; ++index) {
#if MAKHOS_COMPACT_KILLERS
            if (same_packed_killer(move, &context->killers[ply][index])) {
#else
            if (same_move(move, &context->killers[ply][index])) {
#endif
                return index == 0 ? 100000 : 50000;
            }
        }
    }
    return context->history[position.turn][move->path[0]][move->path[move->path_len - 1]];
}

static void order_search_moves(
    NativeSearchContext *context,
    Position position,
    Move *moves,
    uint32_t move_count,
    const Move *tt_move,
    int ply
) {
    SEARCH_TELEMETRY_INC(context, ordering_calls);
    SEARCH_TELEMETRY_ADD(context, moves_ordered, move_count);
#if MAKHOS_PRECOMPUTED_ORDERING
    for (uint32_t index = 0; index < move_count; ++index) {
        context->order_scores[index] = move_order_weight(
            context, position, &moves[index], tt_move, ply
        );
    }
    for (uint32_t index = 1; index < move_count; ++index) {
        Move candidate = moves[index];
        int32_t candidate_weight = context->order_scores[index];
        uint32_t cursor = index;
        while (
            cursor > 0 &&
            context->order_scores[cursor - 1] < candidate_weight
        ) {
            moves[cursor] = moves[cursor - 1];
            context->order_scores[cursor] =
                context->order_scores[cursor - 1];
            --cursor;
        }
        moves[cursor] = candidate;
        context->order_scores[cursor] = candidate_weight;
    }
#else
    for (uint32_t index = 1; index < move_count; ++index) {
        Move candidate = moves[index];
        int candidate_weight = move_order_weight(
            context, position, &candidate, tt_move, ply
        );
        uint32_t cursor = index;
        while (cursor > 0) {
            int previous_weight = move_order_weight(
                context, position, &moves[cursor - 1], tt_move, ply
            );
            if (previous_weight >= candidate_weight) break;
            moves[cursor] = moves[cursor - 1];
            --cursor;
        }
        moves[cursor] = candidate;
    }
#endif
}

static void record_search_cutoff(
    NativeSearchContext *context,
    Position position,
    const Move *move,
    int depth,
    int ply
) {
    if (move->capture_count > 0 || ply >= MAKHOS_SEARCH_MAX_PLY) return;
    if (
        context->killer_count[ply] == 0 ||
#if MAKHOS_COMPACT_KILLERS
        !same_packed_killer(move, &context->killers[ply][0])
#else
        !same_move(move, &context->killers[ply][0])
#endif
    ) {
        if (context->killer_count[ply] > 0) {
            context->killers[ply][1] = context->killers[ply][0];
        }
#if MAKHOS_COMPACT_KILLERS
        pack_move(&context->killers[ply][0], move);
#else
        context->killers[ply][0] = *move;
#endif
        if (context->killer_count[ply] < 2) ++context->killer_count[ply];
    }
    int32_t *history = &context->history[
        position.turn
    ][move->path[0]][move->path[move->path_len - 1]];
#if MAKHOS_HISTORY_GRAVITY
    int bonus = depth * depth * 32;
    if (bonus > MAKHOS_HISTORY_GRAVITY_MAX) {
        bonus = MAKHOS_HISTORY_GRAVITY_MAX;
    }
    *history += bonus - (*history * bonus) / MAKHOS_HISTORY_GRAVITY_MAX;
#else
    int bonus = depth * depth;
    *history = *history > 1000000 - bonus ? 1000000 : *history + bonus;
#endif
}

static int score_from_tt(int score, int ply) {
    if (score >= MAKHOS_SEARCH_MATE - 1000) return score - ply;
    if (score <= -MAKHOS_SEARCH_MATE + 1000) return score + ply;
    return score;
}

static int score_to_tt(int score, int ply) {
    if (score >= MAKHOS_SEARCH_MATE - 1000) return score + ply;
    if (score <= -MAKHOS_SEARCH_MATE + 1000) return score - ply;
    return score;
}

#if MAKHOS_SHARED_TT
static int store_native_tt_entry(
    NativeSearchContext *context,
    size_t index,
    uint64_t key,
    int score,
    int depth,
    uint8_t flag,
    const Move *best_move,
    int ply
) {
    lock_native_tt(context, index);
    NativeTTEntry *entry = &context->tt[index];
    bool replace =
        entry->key != key ||
        depth >= entry->depth;
    if (!replace) {
        unlock_native_tt(context, index);
        return 0;
    }
    bool collision = entry->flag != SEARCH_TT_EMPTY && entry->key != key;
    entry->key = key;
    entry->score = score_to_tt(score, ply);
    entry->depth = (int16_t)depth;
    entry->flag = flag;
    entry->generation = context->generation;
#if MAKHOS_COMPACT_TT
    compact_tt_move(&entry->best_move, best_move);
#else
    entry->best_move = *best_move;
#endif
    unlock_native_tt(context, index);
    return collision ? 2 : 1;
}
#endif

static int native_quiescence(
    NativeSearchContext *context,
    Position position,
    int alpha,
    int beta,
    int ply
);

static int native_negamax(
    NativeSearchContext *context,
    Position position,
    int depth,
    int alpha,
    int beta,
    int ply,
    bool allow_null
) {
    if (ply >= MAKHOS_SEARCH_MAX_PLY - 1) {
        return native_search_evaluate(context, position, position.turn, ply);
    }
    context->repetition_dependent[ply] = 0;
    if (depth <= 0) {
        return native_quiescence(context, position, alpha, beta, ply);
    }
    context->pv_length[ply] = 0;
    ++context->nodes;
    if (search_time_expired(context)) return 0;
    int repetition_count = context->repetition_limit > 0
        ? search_repetition_count(
            context,
            position,
            ply
#if MAKHOS_REPETITION_CENSUS
            ,
            false
#endif
        )
        : 1;
    if (
        context->repetition_limit > 0 &&
        repetition_count >= context->repetition_limit
    ) {
        context->repetition_dependent[ply] = 1;
        context->pv_length[ply] = 0;
        return 0;
    }
    if (position.reversible_plies >= context->no_progress_plies) {
        context->pv_length[ply] = 0;
        return 0;
    }

    MoveList *moves;
#if !MAKHOS_EARLY_TT_CUTOFF
    if (!generate_search_moves(context, position, ply, &moves)) {
        return 0;
    }
    if (moves->count == 0) {
        context->pv_length[ply] = 0;
        return -MAKHOS_SEARCH_MATE + ply;
    }
#endif

    uint64_t key;
#if MAKHOS_STRICT_SEARCH_POSITION_KEY_LEGACY_TT_INDEX
    uint64_t legacy_index_key;
    search_position_key_with_legacy_tt_index(
        position, &key, &legacy_index_key
    );
    size_t tt_index = (size_t)(legacy_index_key & (context->tt_count - 1));
#else
    key = search_position_key(position);
    size_t tt_index = (size_t)(key & (context->tt_count - 1));
#endif
#if MAKHOS_SHARED_TT
    NativeTTEntry entry_snapshot;
    load_native_tt_entry(context, tt_index, &entry_snapshot);
    NativeTTEntry *entry = &entry_snapshot;
#else
    NativeTTEntry *entry = &context->tt[tt_index];
#endif
    SEARCH_TELEMETRY_INC(context, tt_probes);
    if (entry->flag != SEARCH_TT_EMPTY && entry->key != key) {
        SEARCH_TELEMETRY_INC(context, tt_collisions);
    }
    Move *tt_move = NULL;
#if MAKHOS_COMPACT_TT
    Move tt_move_storage;
    NativeCompactMove tt_compact_snapshot;
#if !MAKHOS_STABLE_TT_MOVE
    bool has_tt_compact_snapshot = false;
#endif
#endif
    if (entry->key == key && entry->flag != SEARCH_TT_EMPTY) {
        SEARCH_TELEMETRY_INC(context, tt_hits);
#if MAKHOS_COMPACT_TT
        tt_compact_snapshot = entry->best_move;
#if !MAKHOS_STABLE_TT_MOVE
        has_tt_compact_snapshot = true;
#endif
        expand_compact_tt_move(&tt_move_storage, &tt_compact_snapshot);
        tt_move = &tt_move_storage;
#else
        tt_move = &entry->best_move;
#endif
        if (tt_move != NULL) {
            store_native_pv_move(&context->pv[ply][0], tt_move);
            context->pv_length[ply] = 1;
        }
        if (
            entry->depth >= depth &&
            repetition_count <= 1 &&
            position.reversible_plies + depth < context->no_progress_plies
        ) {
            int tt_score = score_from_tt(entry->score, ply);
            bool tt_cutoff =
                entry->flag == SEARCH_TT_EXACT ||
                (entry->flag == SEARCH_TT_LOWER && tt_score >= beta) ||
                (entry->flag == SEARCH_TT_UPPER && tt_score <= alpha);
            if (tt_cutoff) {
#if MAKHOS_EARLY_TT_CUTOFF
                /*
                 * The accepted ordering checks terminality before trusting a
                 * 64-bit TT key.  Preserve that collision-safe precedence,
                 * but pay for the lightweight check only on an actual cutoff.
                 */
                if (!native_has_legal_move(position)) {
                    context->pv_length[ply] = 0;
                    return -MAKHOS_SEARCH_MATE + ply;
                }
#endif
                SEARCH_TELEMETRY_INC(context, tt_cutoffs);
                return tt_score;
            }
        }
    }

#if MAKHOS_EARLY_TT_CUTOFF
    if (!generate_search_moves(context, position, ply, &moves)) {
        return 0;
    }
    if (moves->count == 0) {
        /* Defensive agreement check with native_has_legal_move(). */
        context->pv_length[ply] = 0;
        return -MAKHOS_SEARCH_MATE + ply;
    }
#endif

#if MAKHOS_IIR_CENSUS
    record_iir_census(
        context,
        depth,
        alpha,
        beta,
        ply,
        tt_move,
        moves->moves[0].capture_count != 0
    );
#endif

    if (
        MAKHOS_NULL_MOVE && allow_null && depth >= 3 && ply > 0 &&
        moves->moves[0].capture_count == 0 &&
        native_count_bits(occupied(position)) > 6 &&
        repetition_count <= 1
    ) {
        SEARCH_TELEMETRY_INC(context, null_attempts);
        int reduction = depth >= 6 ? MAKHOS_NULL_DEEP_REDUCTION : 2;
        Position null_position = position;
        null_position.turn = other(position.turn);
        ++null_position.reversible_plies;
        context->line[ply + 1] = null_position;
        if (!native_search_prepare_child(context, null_position, ply + 1)) {
            return 0;
        }
        int null_score = -native_negamax(
            context,
            null_position,
            depth - 1 - reduction,
            -beta,
            -beta + 1,
            ply + 1,
            false
        );
        if (context->repetition_dependent[ply + 1]) {
            context->repetition_dependent[ply] = 1;
        }
        if (context->stopped) {
            return 0;
        }
        if (null_score >= beta) {
            SEARCH_TELEMETRY_INC(context, null_cutoffs);
            return beta;
        }
    }

#if MAKHOS_COMPACT_TT && !MAKHOS_STABLE_TT_MOVE
    /*
     * The accepted full-Move TT keeps tt_move as a pointer into the direct-map
     * entry. A null search can replace that entry before ordering, so refresh
     * only when the compact payload changed to preserve node-for-node behavior.
     * Stabilizing this pointer is a separate search experiment, not part of the
     * representation refactor.
     */
    NativeCompactMove current_tt_move;
#if MAKHOS_SHARED_TT
    NativeTTEntry refreshed_entry;
    load_native_tt_entry(context, tt_index, &refreshed_entry);
    current_tt_move = refreshed_entry.best_move;
#else
    current_tt_move = entry->best_move;
#endif
    if (
        has_tt_compact_snapshot &&
        memcmp(
            &tt_compact_snapshot,
            &current_tt_move,
            sizeof(tt_compact_snapshot)
        ) != 0
    ) {
        tt_compact_snapshot = current_tt_move;
        expand_compact_tt_move(&tt_move_storage, &tt_compact_snapshot);
        tt_move = &tt_move_storage;
    }
#endif

    order_search_moves(
        context,
        position,
        moves->moves,
        moves->count,
        tt_move,
        ply
    );
    int original_alpha = alpha;
    int best_score = -MAKHOS_SEARCH_INFINITY;
    Move best_move;
    memset(&best_move, 0, sizeof(best_move));
    context->pv_length[ply] = 0;

    for (uint32_t index = 0; index < moves->count; ++index) {
        Move *move = &moves->moves[index];
        context->line[ply + 1] = move->next;
        if (!native_search_prepare_child(context, move->next, ply + 1)) {
            return 0;
        }
        int score;
        if (index == 0) {
            score = -native_negamax(
                context, move->next, depth - 1, -beta, -alpha, ply + 1, true
            );
        } else {
            bool quiet = move->capture_count == 0 && !move->promotes;
            int reduction = quiet && index >= 3 && depth >= 3
                ? 1 + (MAKHOS_LMR_SECOND_REDUCTION && index >= 6 ? 1 : 0)
                : 0;
            score = -native_negamax(
                context,
                move->next,
                depth - 1 - reduction,
                -alpha - 1,
                -alpha,
                ply + 1,
                true
            );
            if (!context->stopped && score > alpha) {
                SEARCH_TELEMETRY_INC(context, pvs_researches);
                if (reduction > 0) {
                    SEARCH_TELEMETRY_INC(context, lmr_researches);
                }
                score = -native_negamax(
                    context,
                    move->next,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    true
                );
            }
        }
        if (context->repetition_dependent[ply + 1]) {
            context->repetition_dependent[ply] = 1;
        }
        if (context->stopped) {
            return 0;
        }
        if (score > best_score) {
            best_score = score;
            best_move = *move;
            store_native_pv_move(&context->pv[ply][0], move);
            uint8_t child_length = context->pv_length[ply + 1];
            if (child_length > MAKHOS_SEARCH_MAX_PLY - ply - 1) {
                child_length = (uint8_t)(MAKHOS_SEARCH_MAX_PLY - ply - 1);
            }
            if (child_length > 0) {
                memcpy(
                    &context->pv[ply][1],
                    &context->pv[ply + 1][0],
                    (size_t)child_length * sizeof(NativePVMove)
                );
            }
            context->pv_length[ply] = (uint8_t)(child_length + 1);
        }
        if (score > alpha) alpha = score;
        if (alpha >= beta) {
            SEARCH_TELEMETRY_INC(context, beta_cutoffs);
            SEARCH_TELEMETRY_ADD(context, beta_cutoff_index_sum, index);
            if (index == 0) {
                SEARCH_TELEMETRY_INC(context, beta_cutoff_first);
            }
            record_search_cutoff(context, position, move, depth, ply);
            break;
        }
    }

    uint8_t flag = best_score >= beta
        ? SEARCH_TT_LOWER
        : (best_score > original_alpha ? SEARCH_TT_EXACT : SEARCH_TT_UPPER);
    if (!context->repetition_dependent[ply]) {
#if MAKHOS_SHARED_TT
        int store_status = store_native_tt_entry(
            context,
            tt_index,
            key,
            best_score,
            depth,
            flag,
            &best_move,
            ply
        );
        if (store_status != 0) {
            SEARCH_TELEMETRY_INC(context, tt_stores);
            if (store_status == 2) {
                SEARCH_TELEMETRY_INC(context, tt_replacements);
            }
        }
#else
        if (
            entry->key != key ||
#if !MAKHOS_TT_KEEP_DEEP_STALE_SAME_KEY
            entry->generation != context->generation ||
#endif
            depth >= entry->depth
        ) {
        SEARCH_TELEMETRY_INC(context, tt_stores);
        if (entry->flag != SEARCH_TT_EMPTY && entry->key != key) {
            SEARCH_TELEMETRY_INC(context, tt_replacements);
        }
        entry->key = key;
        entry->score = score_to_tt(best_score, ply);
        entry->depth = (int16_t)depth;
        entry->flag = flag;
        entry->generation = context->generation;
#if MAKHOS_COMPACT_TT
        compact_tt_move(&entry->best_move, &best_move);
#else
        entry->best_move = best_move;
#endif
        }
#endif
    }
    return best_score;
}

static int native_quiescence(
    NativeSearchContext *context,
    Position position,
    int alpha,
    int beta,
    int ply
) {
    if (ply >= MAKHOS_SEARCH_MAX_PLY - 1) {
        return native_search_evaluate(context, position, position.turn, ply);
    }
    context->repetition_dependent[ply] = 0;
    ++context->nodes;
    SEARCH_TELEMETRY_INC(context, qnodes);
    if (search_time_expired(context)) return 0;
    if (
        context->repetition_limit > 0 &&
        search_repetition_count(
            context,
            position,
            ply
#if MAKHOS_REPETITION_CENSUS
            ,
            true
#endif
        ) >= context->repetition_limit
    ) {
        context->repetition_dependent[ply] = 1;
        context->pv_length[ply] = 0;
        return 0;
    }
    if (position.reversible_plies >= context->no_progress_plies) {
        context->pv_length[ply] = 0;
        return 0;
    }
#if MAKHOS_QSEARCH_CAPTURE_ONLY && MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS && MAKHOS_EARLY_TT_CUTOFF
    /* Most qnodes have no mandatory capture.  Prove that cheaply before
     * allocating or filling a full MoveList; if a capture exists, keep the
     * authoritative qsearch generator and ordering path unchanged. */
#if MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY && MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
    if (!qsearch_has_capture_fast_man_geometry(position)) {
#else
    if (!native_has_capture(position)) {
#endif
        if (!native_has_quiet_move(position)) {
            context->pv_length[ply] = 0;
            return -MAKHOS_SEARCH_MATE + ply;
        }
        context->pv_length[ply] = 0;
        return native_search_evaluate(context, position, position.turn, ply);
    }
#endif
    MoveList *moves;
#if MAKHOS_QSEARCH_CAPTURE_ONLY
    if (context->workspace[ply] == NULL) {
        context->workspace[ply] = malloc(sizeof(*context->workspace[ply]));
        if (context->workspace[ply] == NULL) {
            context->allocation_failed = true;
            context->stopped = true;
            return 0;
        }
        ++context->workspace_count;
    }
    generate_capture_moves(position, context->workspace[ply]);
    SEARCH_TELEMETRY_INC(context, movegen_calls);
    SEARCH_TELEMETRY_ADD(
        context, moves_generated, context->workspace[ply]->count
    );
    moves = context->workspace[ply];
#else
    if (!generate_search_moves(context, position, ply, &moves)) {
        return 0;
    }
#endif
    if (moves->count == 0) {
#if MAKHOS_QSEARCH_CAPTURE_ONLY
#if MAKHOS_EARLY_TT_CUTOFF
        if (!native_has_quiet_move(position)) {
            context->pv_length[ply] = 0;
            return -MAKHOS_SEARCH_MATE + ply;
        }
#else
        if (!generate_search_moves(context, position, ply, &moves)) {
            return 0;
        }
        if (moves->count == 0) {
            context->pv_length[ply] = 0;
            return -MAKHOS_SEARCH_MATE + ply;
        }
#endif
#endif
        context->pv_length[ply] = 0;
#if MAKHOS_QSEARCH_CAPTURE_ONLY
        return native_search_evaluate(context, position, position.turn, ply);
#else
        return -MAKHOS_SEARCH_MATE + ply;
#endif
    }
#if MAKHOS_QSEARCH_TT_CENSUS
    /* Only capture qnodes are candidates for a qsearch TT.  A quiet qnode is
     * already a static leaf, and recording it would measure irrelevant work.
     * The repetition-disabled guard keeps the census semantics independent of
     * the prior game history; project-rule searches require a history-aware
     * key and are intentionally excluded from this experiment. */
    if (
        context->repetition_limit == 0 &&
        moves->moves[0].capture_count != 0
    ) {
        record_qtt_census(context, position);
    }
#endif
#if !MAKHOS_QSEARCH_CAPTURE_ONLY
    if (moves->moves[0].capture_count == 0) {
        context->pv_length[ply] = 0;
        return native_search_evaluate(context, position, position.turn, ply);
    }
#endif

#if MAKHOS_QSEARCH_SINGLE_MOVE_FASTPATH
    if (moves->count > 1) {
        order_search_moves(
            context,
            position,
            moves->moves,
            moves->count,
            NULL,
            ply
        );
    }
#else
    order_search_moves(
        context,
        position,
        moves->moves,
        moves->count,
        NULL,
        ply
    );
#endif
    int best_score = -MAKHOS_SEARCH_INFINITY;
    context->pv_length[ply] = 0;
    for (uint32_t index = 0; index < moves->count; ++index) {
        Move *move = &moves->moves[index];
        context->line[ply + 1] = move->next;
        if (!native_search_prepare_child(context, move->next, ply + 1)) {
            return 0;
        }
        int score;
#if MAKHOS_QSEARCH_PVS
        if (index == 0) {
            score = -native_quiescence(
                context, move->next, -beta, -alpha, ply + 1
            );
        } else {
            score = -native_quiescence(
                context, move->next, -alpha - 1, -alpha, ply + 1
            );
            /* A null-window fail-high that also reaches beta is already a
             * valid cutoff.  Re-search only a possible new principal line. */
            if (!context->stopped && score > alpha && score < beta) {
                SEARCH_TELEMETRY_INC(context, pvs_researches);
                score = -native_quiescence(
                    context, move->next, -beta, -alpha, ply + 1
                );
            }
        }
#else
        score = -native_quiescence(
            context, move->next, -beta, -alpha, ply + 1
        );
#endif
        if (context->repetition_dependent[ply + 1]) {
            context->repetition_dependent[ply] = 1;
        }
        if (context->stopped) {
            return 0;
        }
        if (score > best_score) {
            best_score = score;
            store_native_pv_move(&context->pv[ply][0], move);
            uint8_t child_length = context->pv_length[ply + 1];
            if (child_length > MAKHOS_SEARCH_MAX_PLY - ply - 1) {
                child_length = (uint8_t)(MAKHOS_SEARCH_MAX_PLY - ply - 1);
            }
            if (child_length > 0) {
                memcpy(
                    &context->pv[ply][1],
                    &context->pv[ply + 1][0],
                    (size_t)child_length * sizeof(NativePVMove)
                );
            }
            context->pv_length[ply] = (uint8_t)(child_length + 1);
        }
        if (score > alpha) alpha = score;
        if (alpha >= beta) {
            SEARCH_TELEMETRY_INC(context, q_beta_cutoffs);
            break;
        }
    }
    return best_score;
}

static uint32_t search_elapsed_ms(const NativeSearchContext *context) {
    double elapsed = search_now_seconds() - context->start;
    if (elapsed <= 0) return 0;
    double milliseconds = elapsed * 1000.0;
    return milliseconds >= (double)UINT32_MAX
        ? UINT32_MAX
        : (uint32_t)(milliseconds + 0.5);
}

static bool allocate_native_search(
    NativeSearchContext *context,
    int hash_power
) {
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    if (native_nnue_model == NULL || !avx2_supported_cached()) return false;
#endif
    memset(context, 0, sizeof(*context));
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    native_nnue_initialize_stack(context);
#endif
    context->tt_count = (size_t)1 << hash_power;
#if MAKHOS_SHARED_TT
    NativeSharedTT *shared = calloc(1, sizeof(*shared));
    if (shared == NULL) {
        memset(context, 0, sizeof(*context));
        return false;
    }
    shared->entries = calloc(context->tt_count, sizeof(*shared->entries));
    if (shared->entries == NULL) {
        free(shared);
        memset(context, 0, sizeof(*context));
        return false;
    }
    shared->count = context->tt_count;
    atomic_init(&shared->references, 1);
    atomic_init(&shared->generation, 1);
    for (size_t index = 0; index < MAKHOS_SHARED_TT_LOCKS; ++index) {
        atomic_flag_clear(&shared->locks[index].flag);
    }
    context->shared_tt = shared;
    context->owns_shared_tt = true;
    context->tt_requires_lock = false;
    context->tt = shared->entries;
#else
    context->tt = calloc(context->tt_count, sizeof(*context->tt));
    if (context->tt == NULL) {
        memset(context, 0, sizeof(*context));
        return false;
    }
#endif
#if MAKHOS_QSEARCH_TT_CENSUS
    context->qtt_census_count = context->tt_count >> 4;
    if (context->qtt_census_count < 256) {
        context->qtt_census_count = 256;
    }
    context->qtt_census = calloc(
        context->qtt_census_count,
        sizeof(*context->qtt_census)
    );
    if (context->qtt_census == NULL) {
        free(context->tt);
        memset(context, 0, sizeof(*context));
        return false;
    }
#endif
    context->generation = 1;
    return true;
}

#if MAKHOS_SHARED_TT
static bool allocate_native_search_shared(
    NativeSearchContext *context,
    NativeSearchContext *owner
) {
    if (owner == NULL || owner->shared_tt == NULL) return false;
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    if (native_nnue_model == NULL || !avx2_supported_cached()) return false;
#endif
    memset(context, 0, sizeof(*context));
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    native_nnue_initialize_stack(context);
#endif
    context->shared_tt = owner->shared_tt;
    context->tt = context->shared_tt->entries;
    context->tt_count = context->shared_tt->count;
    context->owns_shared_tt = false;
    context->tt_requires_lock = true;
    owner->tt_requires_lock = true;
    atomic_fetch_add_explicit(
        &context->shared_tt->references,
        1,
        memory_order_relaxed
    );
    context->generation = 1;
    return true;
}
#endif

static void prepare_native_search(
    NativeSearchContext *context,
    int no_progress_plies,
    int repetition_limit,
    int time_ms,
    const MakhosHistoryEntry *history,
    uint32_t history_count
) {
    context->nodes = 0;
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    context->nnue_refreshes = 0U;
    context->nnue_updates = 0U;
    context->nnue_evaluations = 0U;
#endif
#if MAKHOS_SEARCH_TELEMETRY
    memset(&context->telemetry, 0, sizeof(context->telemetry));
#endif
#if MAKHOS_IIR_CENSUS
    memset(
        &context->iir_census_telemetry,
        0,
        sizeof(context->iir_census_telemetry)
    );
#endif
#if MAKHOS_REPETITION_CENSUS
    memset(
        &context->repetition_census_telemetry,
        0,
        sizeof(context->repetition_census_telemetry)
    );
#endif
    context->stopped = false;
    context->allocation_failed = false;
    context->has_deadline = false;
    context->start = search_now_seconds();
    context->no_progress_plies = (uint8_t)no_progress_plies;
    context->repetition_limit = (uint8_t)repetition_limit;
#if MAKHOS_SHARED_TT
    unsigned int generation = atomic_fetch_add_explicit(
        &context->shared_tt->generation,
        1,
        memory_order_relaxed
    ) + 1;
    context->generation = (uint8_t)generation;
    if (context->generation == 0) context->generation = 1;
#else
    ++context->generation;
    if (context->generation == 0) {
        context->generation = 1;
#if MAKHOS_QSEARCH_TT_CENSUS
        memset(
            context->qtt_census,
            0,
            context->qtt_census_count * sizeof(*context->qtt_census)
        );
#endif
    }
#endif
    context->initial_history = history;
    context->initial_history_count = history_count;
    prepare_history_lookup(context);
    memset(context->pv_length, 0, sizeof(context->pv_length));
    if (time_ms > 0) {
        context->has_deadline = true;
        context->deadline = context->start + (double)time_ms / 1000.0;
    }
}

static bool initialize_native_search(
    NativeSearchContext *context,
    int hash_power,
    int no_progress_plies,
    int repetition_limit,
    int time_ms,
    const MakhosHistoryEntry *history,
    uint32_t history_count
) {
    if (!allocate_native_search(context, hash_power)) return false;
    prepare_native_search(
        context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history,
        history_count
    );
    return true;
}

static void destroy_native_search(NativeSearchContext *context) {
#if MAKHOS_SHARED_TT
    NativeSharedTT *shared = context->shared_tt;
    if (
        shared != NULL &&
        atomic_fetch_sub_explicit(
            &shared->references,
            1,
            memory_order_acq_rel
        ) == 1
    ) {
        free(shared->entries);
        free(shared);
    }
#else
    free(context->tt);
#endif
#if MAKHOS_QSEARCH_TT_CENSUS
    free(context->qtt_census);
    context->qtt_census = NULL;
    context->qtt_census_count = 0;
#endif
    free(context->history_lookup);
#if MAKHOS_ITERATIVE_SESSION
    free(context->session_history);
    context->session_history = NULL;
    context->session_history_count = 0;
    context->session_history_capacity = 0;
    context->session_active = false;
#endif
    for (size_t ply = 0; ply < MAKHOS_SEARCH_MAX_PLY; ++ply) {
        free(context->workspace[ply]);
        context->workspace[ply] = NULL;
    }
    context->tt = NULL;
#if MAKHOS_SHARED_TT
    context->shared_tt = NULL;
#endif
    context->history_lookup = NULL;
    context->history_lookup_capacity = 0;
    context->history_lookup_ready = false;
    context->workspace_count = 0;
}

static int validate_native_search_inputs(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result,
    Position *root
) {
    uint32_t all = red | black;
    if (
        result == NULL || root == NULL ||
        (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 || reversible_plies > 255 ||
        max_depth < 1 || max_depth >= MAKHOS_SEARCH_MAX_PLY - 1 ||
        time_ms < 0 || time_ms > 3600000 ||
        no_progress_plies < 1 || no_progress_plies > 255 ||
        (repetition_limit != 0 &&
         (repetition_limit < 2 || repetition_limit > 20)) ||
        (history_count > 0 && history == NULL)
    ) {
        return 1;
    }
    for (uint32_t index = 0; index < history_count; ++index) {
        uint32_t history_all = history[index].red | history[index].black;
        if (
            (history[index].red & history[index].black) != 0 ||
            (history[index].kings & ~history_all) != 0 ||
            (history[index].turn != RED && history[index].turn != BLACK) ||
            history[index].count == 0
        ) {
            return 1;
        }
    }
    root->red = red;
    root->black = black;
    root->kings = kings;
    root->turn = (uint8_t)turn;
    root->reversible_plies = (uint8_t)reversible_plies;
    if (root->reversible_plies >= no_progress_plies) return 4;
    memset(result, 0, sizeof(*result));
    return 0;
}

#if MAKHOS_NATIVE_ROOT_PVS_SMP
static DWORD WINAPI run_native_root_pvs_worker(void *argument) {
    NativeRootPvsWorker *worker = argument;
    NativeRootPvsHandle *handle = worker->owner;
    NativeSearchContext *context = &handle->helpers[worker->index];
    for (;;) {
        DWORD waited = WaitForSingleObject(
            handle->start_events[worker->index],
            INFINITE
        );
        if (waited != WAIT_OBJECT_0) {
            ++worker->failures;
            return 0;
        }
        if (atomic_load_explicit(&handle->shutdown, memory_order_acquire)) {
            return 0;
        }

        uint32_t stride = handle->active_helpers;
        for (
            uint32_t move_index = worker->index + 1;
            move_index < handle->task_move_count;
            move_index += stride
        ) {
            if (atomic_load_explicit(
                &handle->control.stop,
                memory_order_acquire
            )) {
                break;
            }
            Move *move = &handle->task_moves[move_index];
            context->stopped = false;
            context->line[0] = handle->task_root;
            context->line[1] = move->next;
#if MAKHOS_NNUE_SEARCH_CANDIDATE
            if (
                !native_nnue_refresh_root(context, handle->task_root) ||
                !native_search_prepare_child(context, move->next, 1)
            ) {
                ++worker->failures;
                atomic_store_explicit(
                    &handle->task_states[move_index],
                    3,
                    memory_order_release
                );
                break;
            }
#endif
            atomic_store_explicit(
                &handle->task_states[move_index],
                1,
                memory_order_release
            );
            ++worker->tasks_started;
            int score = -native_negamax(
                context,
                move->next,
                handle->task_depth - 1,
                -handle->task_alpha - 1,
                -handle->task_alpha,
                1,
                true
            );
            if (context->allocation_failed) {
                ++worker->failures;
                atomic_store_explicit(
                    &handle->task_states[move_index],
                    3,
                    memory_order_release
                );
                break;
            }
            if (context->stopped) {
                ++worker->tasks_aborted;
                atomic_store_explicit(
                    &handle->task_states[move_index],
                    3,
                    memory_order_release
                );
                break;
            }
            handle->task_scores[move_index] = score;
            atomic_store_explicit(
                &handle->task_states[move_index],
                2,
                memory_order_release
            );
            ++worker->tasks_completed;
            if (score > handle->task_alpha) ++worker->fail_highs;
        }
        if (SetEvent(handle->done_events[worker->index]) == 0) {
            ++worker->failures;
            return 0;
        }
    }
}

static bool begin_native_root_pvs_shadow_iteration(
    NativeRootPvsHandle *handle,
    Position root,
    const MoveList *root_moves,
    int depth,
    int alpha
) {
    if (
        handle == NULL || handle->helper_count == 0 ||
        root_moves->count <= 1
    ) {
        return false;
    }
    uint32_t active = root_moves->count - 1;
    if (active > handle->helper_count) active = handle->helper_count;
    handle->task_root = root;
    handle->task_move_count = root_moves->count;
    memcpy(
        handle->task_moves,
        root_moves->moves,
        (size_t)root_moves->count * sizeof(*handle->task_moves)
    );
    handle->task_depth = depth;
    handle->task_alpha = alpha;
    handle->active_helpers = active;
    for (uint32_t index = 0; index < root_moves->count; ++index) {
        atomic_store_explicit(
            &handle->task_states[index],
            0,
            memory_order_relaxed
        );
        handle->task_scores[index] = 0;
    }
    if (active > handle->stats.active_helpers) {
        handle->stats.active_helpers = active;
    }
    atomic_store_explicit(&handle->control.stop, false, memory_order_release);
    for (uint32_t index = 0; index < active; ++index) {
        handle->helpers[index].stopped = false;
    }
    uint32_t started = 0;
    for (; started < active; ++started) {
        if (SetEvent(handle->start_events[started]) == 0) break;
    }
    if (started != active) {
        ++handle->stats.worker_failures;
        atomic_store_explicit(&handle->control.stop, true, memory_order_release);
        for (uint32_t index = 0; index < started; ++index) {
            WaitForSingleObject(handle->done_events[index], INFINITE);
        }
        handle->active_helpers = 0;
        return false;
    }
    ++handle->stats.shadow_iterations;
    return true;
}

static void record_native_root_pvs_shadow_readiness(
    NativeRootPvsHandle *handle,
    uint32_t move_index,
    int current_alpha
) {
    if (
        handle == NULL || move_index >= handle->task_move_count ||
        atomic_load_explicit(
            &handle->task_states[move_index],
            memory_order_acquire
        ) != 2
    ) {
        return;
    }
    ++handle->stats.scout_ready_before_main;
    int scout_score = handle->task_scores[move_index];
    if (scout_score > handle->task_alpha) {
        ++handle->stats.scout_ready_fail_highs;
    }
    if (scout_score > current_alpha) {
        ++handle->stats.scout_ready_above_current_alpha;
    }
}

static void finish_native_root_pvs_shadow_iteration(
    NativeRootPvsHandle *handle
) {
    if (handle == NULL || handle->active_helpers == 0) return;
    double wait_start = search_now_seconds();
    atomic_store_explicit(&handle->control.stop, true, memory_order_release);
    for (uint32_t index = 0; index < handle->active_helpers; ++index) {
        if (
            WaitForSingleObject(handle->done_events[index], INFINITE) !=
            WAIT_OBJECT_0
        ) {
            ++handle->stats.worker_failures;
        }
    }
    double waited = search_now_seconds() - wait_start;
    if (waited > 0.0) {
        handle->stats.main_wait_us += (uint64_t)(waited * 1000000.0);
    }
    handle->active_helpers = 0;
}
#endif

static int execute_native_search_impl(
    NativeSearchContext *context,
    Position root,
    int start_depth,
    int max_depth,
    uint32_t root_order_rotation,
#if MAKHOS_NATIVE_ROOT_PVS_SMP
    NativeRootPvsHandle *root_pvs,
#endif
    MakhosSearchResult *result
) {
    context->line[0] = root;
    if (!native_search_refresh_root(context, root)) return 2;
    MoveList *root_moves;
    if (!generate_search_moves(context, root, 0, &root_moves)) {
        return 2;
    }
    if (root_moves->count == 0) return 4;

    Move completed_move = root_moves->moves[0];
    context->line[1] = completed_move.next;
    if (!native_search_prepare_child(context, completed_move.next, 1)) return 2;
    int completed_score = -native_search_evaluate(
        context,
        completed_move.next,
        completed_move.next.turn,
        1
    );
    NativePVMove completed_pv[MAKHOS_SEARCH_MAX_PLY];
    store_native_pv_move(&completed_pv[0], &completed_move);
    uint8_t completed_pv_length = 1;
    uint32_t completed_depth = 0;
    Move previous_best;
    memset(&previous_best, 0, sizeof(previous_best));
    bool has_previous_best = false;
    uint64_t root_key = search_position_key(root);
    if (
        start_depth > 1 &&
        context->has_cached_root_best &&
        context->cached_root_key == root_key
    ) {
        previous_best = context->cached_root_best;
        completed_move = previous_best;
        has_previous_best = true;
    }

    for (int depth = start_depth; depth <= max_depth; ++depth) {
#if MAKHOS_NATIVE_ROOT_PVS_SMP
        bool shadow_started = false;
        if (root_pvs != NULL) root_pvs->stats.attempted_depth = (uint32_t)depth;
#endif
        order_search_moves(
            context,
            root,
            root_moves->moves,
            root_moves->count,
            has_previous_best ? &previous_best : NULL,
            0
        );
#if MAKHOS_NATIVE_LAZY_SMP
        /* Worker zero retains the ordinary root order.  Helpers use a small,
         * deterministic rotation only at the root to diversify TT discovery
         * without sharing mutable history, PV, or move lists. */
        if (root_order_rotation != 0 && root_moves->count > 1) {
            uint32_t rotation = root_order_rotation % root_moves->count;
            while (rotation-- > 0) {
                Move first = root_moves->moves[0];
                memmove(
                    &root_moves->moves[0],
                    &root_moves->moves[1],
                    (size_t)(root_moves->count - 1) * sizeof(root_moves->moves[0])
                );
                root_moves->moves[root_moves->count - 1] = first;
            }
        }
#else
        (void)root_order_rotation;
#endif

        int alpha = -MAKHOS_SEARCH_INFINITY;
        int iteration_score = -MAKHOS_SEARCH_INFINITY;
        Move iteration_move;
        NativePVMove iteration_pv[MAKHOS_SEARCH_MAX_PLY];
        uint8_t iteration_pv_length = 0;
        for (uint32_t index = 0; index < root_moves->count; ++index) {
#if MAKHOS_NATIVE_ROOT_PVS_SMP
            if (shadow_started && index > 0) {
                record_native_root_pvs_shadow_readiness(root_pvs, index, alpha);
            }
#endif
            Move *move = &root_moves->moves[index];
            context->line[1] = move->next;
            if (!native_search_prepare_child(context, move->next, 1)) return 2;
            int score;
            if (index == 0) {
                score = -native_negamax(
                    context,
                    move->next,
                    depth - 1,
                    -MAKHOS_SEARCH_INFINITY,
                    -alpha,
                    1,
                    true
                );
            } else {
                score = -native_negamax(
                    context,
                    move->next,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    1,
                    true
                );
                if (!context->stopped && score > alpha) {
                    SEARCH_TELEMETRY_INC(context, pvs_researches);
                    score = -native_negamax(
                        context,
                        move->next,
                        depth - 1,
                        -MAKHOS_SEARCH_INFINITY,
                        -alpha,
                        1,
                        true
                    );
                }
            }
            if (context->stopped) break;
#if MAKHOS_NATIVE_ROOT_PVS_SMP
            if (index == 0 && root_pvs != NULL) {
                shadow_started = begin_native_root_pvs_shadow_iteration(
                    root_pvs,
                    root,
                    root_moves,
                    depth,
                    score
                );
            }
#endif
            if (score > iteration_score) {
                iteration_score = score;
                iteration_move = *move;
                store_native_pv_move(&iteration_pv[0], move);
                uint8_t child_length = context->pv_length[1];
                if (child_length > MAKHOS_SEARCH_MAX_PLY - 1) {
                    child_length = MAKHOS_SEARCH_MAX_PLY - 1;
                }
                if (child_length > 0) {
                    memcpy(
                        &iteration_pv[1],
                        &context->pv[1][0],
                        (size_t)child_length * sizeof(NativePVMove)
                    );
                }
                iteration_pv_length = (uint8_t)(child_length + 1);
            }
            if (score > alpha) alpha = score;
        }
#if MAKHOS_NATIVE_ROOT_PVS_SMP
        if (shadow_started) finish_native_root_pvs_shadow_iteration(root_pvs);
#endif
        if (context->stopped) break;

        completed_move = iteration_move;
        completed_score = iteration_score;
        completed_pv_length = iteration_pv_length;
        memcpy(
            completed_pv,
            iteration_pv,
            (size_t)iteration_pv_length * sizeof(NativePVMove)
        );
        completed_depth = (uint32_t)depth;
#if MAKHOS_NATIVE_ROOT_PVS_SMP
        if (root_pvs != NULL) root_pvs->stats.completed_depth = completed_depth;
#endif
        previous_best = iteration_move;
        has_previous_best = true;
        context->cached_root_key = root_key;
        context->cached_root_best = iteration_move;
        context->has_cached_root_best = true;
    }

    if (context->allocation_failed) {
        return 2;
    }

    result->score = completed_score;
    result->depth = completed_depth;
    result->nodes = context->nodes;
    result->elapsed_ms = search_elapsed_ms(context);
    result->pv_len = completed_pv_length;
    pack_move(&result->best_move, &completed_move);
    for (uint8_t index = 0; index < completed_pv_length; ++index) {
        pack_native_pv_move(&result->pv[index], &completed_pv[index]);
    }
    return 0;
}

static int execute_native_search(
    NativeSearchContext *context,
    Position root,
    int start_depth,
    int max_depth,
    uint32_t root_order_rotation,
    MakhosSearchResult *result
) {
    return execute_native_search_impl(
        context,
        root,
        start_depth,
        max_depth,
        root_order_rotation,
#if MAKHOS_NATIVE_ROOT_PVS_SMP
        NULL,
#endif
        result
    );
}

#if MAKHOS_NATIVE_LAZY_SMP
typedef struct {
    NativeSearchContext *context;
    Position root;
    int max_depth;
    uint32_t root_order_rotation;
    HANDLE start_event;
    MakhosSearchResult result;
    int status;
} NativeLazySmpJob;

static DWORD WINAPI run_native_lazy_smp_worker(void *argument) {
    NativeLazySmpJob *job = argument;
    for (;;) {
        DWORD start_wait = WaitForSingleObject(job->start_event, 25);
        if (start_wait == WAIT_OBJECT_0) break;
        if (start_wait == WAIT_TIMEOUT) {
            if (atomic_load_explicit(
                &job->context->lazy_smp_control->stop,
                memory_order_acquire
            )) {
                job->status = 0;
                return 0;
            }
            continue;
        }
        job->status = 2;
        atomic_store_explicit(
            &job->context->lazy_smp_control->stop,
            true,
            memory_order_release
        );
        return 0;
    }
    if (atomic_load_explicit(
        &job->context->lazy_smp_control->stop,
        memory_order_acquire
    )) {
        job->status = 0;
        return 0;
    }
    job->status = execute_native_search(
        job->context,
        job->root,
        1,
        job->max_depth,
        job->root_order_rotation,
        &job->result
    );
    if (job->status == 2) {
        atomic_store_explicit(
            &job->context->lazy_smp_control->stop,
            true,
            memory_order_release
        );
    }
    return 0;
}
#endif

#if MAKHOS_ITERATIVE_SESSION
/* A session advances the ordinary iterative root loop one completed depth at a
 * time without rebuilding earlier layers.  It is candidate-only: the public
 * one-shot search path above remains the production reference. */
static bool copy_session_history(
    NativeSearchContext *context,
    const MakhosHistoryEntry *history,
    uint32_t history_count
) {
    if ((size_t)history_count > SIZE_MAX / sizeof(*context->session_history)) {
        return false;
    }
    if ((size_t)history_count > context->session_history_capacity) {
        MakhosHistoryEntry *resized = realloc(
            context->session_history,
            (size_t)history_count * sizeof(*resized)
        );
        if (resized == NULL) return false;
        context->session_history = resized;
        context->session_history_capacity = history_count;
    }
    if (history_count > 0) {
        memcpy(
            context->session_history,
            history,
            (size_t)history_count * sizeof(*history)
        );
    }
    context->session_history_count = history_count;
    return true;
}

static void write_native_session_result(
    const NativeSearchContext *context,
    MakhosSearchResult *result
) {
    result->score = context->session_completed_score;
    result->depth = context->session_completed_depth;
    result->nodes = context->nodes;
    result->elapsed_ms = search_elapsed_ms(context);
    result->pv_len = context->session_completed_pv_length;
    pack_move(&result->best_move, &context->session_completed_move);
    for (
        uint8_t index = 0;
        index < context->session_completed_pv_length;
        ++index
    ) {
        pack_native_pv_move(
            &result->pv[index],
            &context->session_completed_pv[index]
        );
    }
}

static int advance_native_search_session(
    NativeSearchContext *context,
    int max_depth,
    MakhosSearchResult *result
) {
    if (
        result == NULL || !context->session_active ||
        max_depth < 1 || max_depth >= MAKHOS_SEARCH_MAX_PLY - 1
    ) {
        return 1;
    }
    memset(result, 0, sizeof(*result));
    MoveList *root_moves = context->workspace[0];
    if (root_moves == NULL || root_moves->count == 0) return 4;
    context->line[0] = context->session_root;
    if (!native_search_refresh_root(context, context->session_root)) return 2;

    for (
        int depth = (int)context->session_completed_depth + 1;
        depth <= max_depth;
        ++depth
    ) {
        order_search_moves(
            context,
            context->session_root,
            root_moves->moves,
            root_moves->count,
            context->session_has_previous_best
                ? &context->session_previous_best
                : NULL,
            0
        );
        int alpha = -MAKHOS_SEARCH_INFINITY;
        int iteration_score = -MAKHOS_SEARCH_INFINITY;
        Move iteration_move;
        NativePVMove iteration_pv[MAKHOS_SEARCH_MAX_PLY];
        uint8_t iteration_pv_length = 0;
        for (uint32_t index = 0; index < root_moves->count; ++index) {
            Move *move = &root_moves->moves[index];
            context->line[1] = move->next;
            if (!native_search_prepare_child(context, move->next, 1)) return 2;
            int score;
            if (index == 0) {
                score = -native_negamax(
                    context,
                    move->next,
                    depth - 1,
                    -MAKHOS_SEARCH_INFINITY,
                    -alpha,
                    1,
                    true
                );
            } else {
                score = -native_negamax(
                    context,
                    move->next,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    1,
                    true
                );
                if (!context->stopped && score > alpha) {
                    SEARCH_TELEMETRY_INC(context, pvs_researches);
                    score = -native_negamax(
                        context,
                        move->next,
                        depth - 1,
                        -MAKHOS_SEARCH_INFINITY,
                        -alpha,
                        1,
                        true
                    );
                }
            }
            if (context->stopped) break;
            if (score > iteration_score) {
                iteration_score = score;
                iteration_move = *move;
                store_native_pv_move(&iteration_pv[0], move);
                uint8_t child_length = context->pv_length[1];
                if (child_length > MAKHOS_SEARCH_MAX_PLY - 1) {
                    child_length = MAKHOS_SEARCH_MAX_PLY - 1;
                }
                if (child_length > 0) {
                    memcpy(
                        &iteration_pv[1],
                        &context->pv[1][0],
                        (size_t)child_length * sizeof(NativePVMove)
                    );
                }
                iteration_pv_length = (uint8_t)(child_length + 1);
            }
            if (score > alpha) alpha = score;
        }
        if (context->stopped) break;
        context->session_completed_move = iteration_move;
        context->session_completed_score = iteration_score;
        context->session_completed_pv_length = iteration_pv_length;
        memcpy(
            context->session_completed_pv,
            iteration_pv,
            (size_t)iteration_pv_length * sizeof(NativePVMove)
        );
        context->session_completed_depth = (uint32_t)depth;
        context->session_previous_best = iteration_move;
        context->session_has_previous_best = true;
        context->cached_root_key = context->session_root_key;
        context->cached_root_best = iteration_move;
        context->has_cached_root_best = true;
    }

    if (context->allocation_failed) return 2;
    write_native_session_result(context, result);
    return 0;
}

static int begin_native_search_session(
    NativeSearchContext *context,
    Position root,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (!copy_session_history(context, history, history_count)) return 2;
    prepare_native_search(
        context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history_count > 0 ? context->session_history : NULL,
        history_count
    );
    context->session_active = false;
    context->session_root = root;
    context->session_root_key = search_position_key(root);
    context->line[0] = root;
    if (!native_search_refresh_root(context, root)) return 2;
    MoveList *root_moves;
    if (!generate_search_moves(context, root, 0, &root_moves)) return 2;
    if (root_moves->count == 0) return 4;
    context->session_completed_move = root_moves->moves[0];
    context->line[1] = context->session_completed_move.next;
    if (!native_search_prepare_child(
            context, context->session_completed_move.next, 1)) return 2;
    context->session_completed_score = -native_search_evaluate(
        context,
        context->session_completed_move.next,
        context->session_completed_move.next.turn,
        1
    );
    store_native_pv_move(
        &context->session_completed_pv[0],
        &context->session_completed_move
    );
    context->session_completed_pv_length = 1;
    context->session_completed_depth = 0;
    memset(&context->session_previous_best, 0, sizeof(context->session_previous_best));
    context->session_has_previous_best = false;
    context->session_active = true;
    return advance_native_search_session(context, max_depth, result);
}

/* Attach after an ordinary completed iterative search on the same persistent
 * context.  That preserves its warmed TT/killer/history state and uses the
 * cached completed root move only as the next iteration's ordering hint. */
static int attach_native_search_session(
    NativeSearchContext *context,
    Position root,
    int completed_depth,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (completed_depth < 1 || completed_depth >= max_depth) return 1;
    uint64_t root_key = search_position_key(root);
    bool has_cached_best =
        context->has_cached_root_best && context->cached_root_key == root_key;
    Move cached_best;
    if (has_cached_best) cached_best = context->cached_root_best;
    if (!copy_session_history(context, history, history_count)) return 2;
    prepare_native_search(
        context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history_count > 0 ? context->session_history : NULL,
        history_count
    );
    context->session_active = false;
    context->session_root = root;
    context->session_root_key = root_key;
    context->line[0] = root;
    if (!native_search_refresh_root(context, root)) return 2;
    MoveList *root_moves;
    if (!generate_search_moves(context, root, 0, &root_moves)) return 2;
    if (root_moves->count == 0) return 4;
    context->session_completed_move = has_cached_best
        ? cached_best
        : root_moves->moves[0];
    context->line[1] = context->session_completed_move.next;
    if (!native_search_prepare_child(
            context, context->session_completed_move.next, 1)) return 2;
    context->session_completed_score = -native_search_evaluate(
        context,
        context->session_completed_move.next,
        context->session_completed_move.next.turn,
        1
    );
    store_native_pv_move(
        &context->session_completed_pv[0],
        &context->session_completed_move
    );
    context->session_completed_pv_length = 1;
    context->session_completed_depth = (uint32_t)completed_depth;
    context->session_previous_best = context->session_completed_move;
    context->session_has_previous_best = has_cached_best;
    context->session_active = true;
    return advance_native_search_session(context, max_depth, result);
}

static void end_native_search_session(NativeSearchContext *context) {
    context->session_active = false;
    context->session_history_count = 0;
    context->initial_history = NULL;
    context->initial_history_count = 0;
    context->history_lookup_ready = false;
}
#endif

#if MAKHOS_EXPERIMENTAL_SEARCH_APIS
static int execute_native_window_search(
    NativeSearchContext *context,
    Position root,
    int depth,
    int alpha,
    int beta,
    MakhosSearchResult *result
) {
    context->line[0] = root;
    if (!native_search_refresh_root(context, root)) return 2;
    int score = native_negamax(context, root, depth, alpha, beta, 0, true);
    if (context->allocation_failed) return 2;
    if (context->stopped) return 5;

    uint8_t pv_length = context->pv_length[0];
    if (pv_length == 0) {
        MoveList *root_moves;
        if (!generate_search_moves(context, root, 0, &root_moves)) return 2;
        if (root_moves->count == 0) return 4;
        pack_move(&result->best_move, &root_moves->moves[0]);
        result->pv_len = 1;
        result->pv[0] = result->best_move;
    } else {
        result->pv_len = pv_length;
        pack_native_pv_move(&result->best_move, &context->pv[0][0]);
        for (uint8_t index = 0; index < pv_length; ++index) {
            pack_native_pv_move(&result->pv[index], &context->pv[0][index]);
        }
    }
    result->score = score;
    result->depth = (uint32_t)depth;
    result->nodes = context->nodes;
    result->elapsed_ms = search_elapsed_ms(context);
    return 0;
}
#endif

#if defined(_WIN32)
#define MAKHOS_API __declspec(dllexport)
#else
#define MAKHOS_API __attribute__((visibility("default")))
#endif

#if MAKHOS_NNUE_SEARCH_CANDIDATE
MAKHOS_API int makhos_search_nnue_load_model(const char *path) {
    last_error[0] = '\0';
    if (path == NULL) {
        set_error("NNUE search model path is null");
        return 1;
    }
    if (native_nnue_model != NULL) return 0;
    uint8_t *encoded = NULL;
    size_t length = 0U;
    uint8_t digest[32];
    if (!read_file(path, &encoded, &length)) return 2;
    sha256_bytes(encoded, length, digest);
    free(encoded);
    if (memcmp(digest, native_nnue_binary_sha256, sizeof(digest)) != 0) {
        set_error("NNUE search model SHA-256 differs from KEEP artifact");
        return 3;
    }
    MakhosNnueIncrementalModel *loaded = makhos_nnue_incremental_load(
        path,
        native_nnue_source_model_sha256
    );
    if (loaded == NULL) return 4;
    if (!avx2_supported_cached()) {
        makhos_nnue_incremental_free_model(loaded);
        set_error("NNUE search candidate requires AVX2");
        return 5;
    }
    native_nnue_model = loaded;
    return 0;
}

MAKHOS_API int makhos_search_nnue_ready(void) {
    return native_nnue_model != NULL && avx2_supported_cached();
}

MAKHOS_API const char *makhos_search_nnue_feature_abi(void) {
    return "thai-makhos-shared-137-v1";
}

MAKHOS_API const char *makhos_search_nnue_model_sha256(void) {
    return "07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C";
}

MAKHOS_API const char *makhos_search_nnue_source_model_sha256(void) {
    return "5FD87ABD2F9CAAC81045A58AEA420445B90CAC9A70D5FFBDFC5694BA1338CA4E";
}

MAKHOS_API const char *makhos_search_nnue_last_error(void) {
    return makhos_nnue_scalar_last_error();
}

MAKHOS_API int makhos_search_nnue_raw_to_cp(int32_t output_sum) {
    return native_nnue_score_from_sum(output_sum);
}

MAKHOS_API int makhos_search_nnue_telemetry(
    const void *handle,
    uint64_t *refreshes,
    uint64_t *updates,
    uint64_t *evaluations
) {
    if (
        handle == NULL || refreshes == NULL || updates == NULL ||
        evaluations == NULL
    ) {
        return 1;
    }
    const NativeSearchContext *context = handle;
    *refreshes = context->nnue_refreshes;
    *updates = context->nnue_updates;
    *evaluations = context->nnue_evaluations;
    return 0;
}
#endif

MAKHOS_API int makhos_search_abi_version(void) {
#if MAKHOS_SEARCH_TELEMETRY
    return 6;
#elif MAKHOS_COMPACT_TT
    return 5;
#else
    return 4;
#endif
}

MAKHOS_API int makhos_evaluate(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int *score
) {
    uint32_t all = red | black;
    if (
        score == NULL || (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 || reversible_plies > 255
    ) {
        return 1;
    }
    Position position;
    position.red = red;
    position.black = black;
    position.kings = kings;
    position.turn = (uint8_t)turn;
    position.reversible_plies = (uint8_t)reversible_plies;
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    if (native_nnue_model == NULL || !avx2_supported_cached()) return 2;
    if (red == 0U || black == 0U) {
        *score = native_evaluate(position, position.turn);
        return 0;
    }
    if (position.reversible_plies >= 80) {
        *score = 0;
        return 0;
    }
    MakhosNnueAccumulator accumulator;
    memset(&accumulator, 0, sizeof(accumulator));
    accumulator.magic = INCREMENTAL_ACCUMULATOR_MAGIC;
    uint16_t red_features[MAKHOS_NNUE_MAX_ACTIVE];
    uint16_t black_features[MAKHOS_NNUE_MAX_ACTIVE];
    uint32_t red_count = 0U;
    uint32_t black_count = 0U;
    int32_t output_sum = 0;
    if (
        !native_nnue_features(position, RED, red_features, &red_count) ||
        !native_nnue_features(position, BLACK, black_features, &black_count) ||
        !makhos_nnue_incremental_refresh(
            native_nnue_model,
            &accumulator,
            red_features,
            red_count,
            black_features,
            black_count
        ) ||
        !makhos_nnue_avx2_eval(
            native_nnue_model,
            &accumulator,
            position.turn,
            &output_sum
        )
    ) {
        return 3;
    }
    *score = native_nnue_score_from_sum(output_sum);
#else
    *score = native_evaluate(position, position.turn);
#endif
    return 0;
}

#if MAKHOS_SEARCH_KEY_TEST_API
/* Candidate-only regression hook.  It makes the search-TT key observable so
 * tests can prove that every packed king/clock state remains distinguishable.
 * Production DLLs are built with this disabled. */
MAKHOS_API int makhos_search_debug_position_key(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    uint64_t *out_key
) {
    uint32_t all = red | black;
    if (
        out_key == NULL || (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 || reversible_plies > 255
    ) {
        return 1;
    }
    Position position;
    position.red = red;
    position.black = black;
    position.kings = kings;
    position.turn = (uint8_t)turn;
    position.reversible_plies = (uint8_t)reversible_plies;
    *out_key = search_position_key(position);
    return 0;
}
#endif

/* Test and profiling hook for the search-only capture-existence fast path.
 * It exposes only whether mandatory capture exists; legal move generation
 * remains internal and authoritative. */
MAKHOS_API int makhos_capture_exists(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int *exists
) {
    uint32_t all = red | black;
    if (
        exists == NULL || (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 || reversible_plies > 255
    ) {
        return 1;
    }
    Position position;
    position.red = red;
    position.black = black;
    position.kings = kings;
    position.turn = (uint8_t)turn;
    position.reversible_plies = (uint8_t)reversible_plies;
    *exists = native_has_capture(position) ? 1 : 0;
    return 0;
}

#if MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY && MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY
/* Test-only export for the scoped qsearch capture-existence geometry.  The
 * normal-search terminality helper remains makhos_capture_exists above. */
MAKHOS_API int makhos_qsearch_fast_capture_exists(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int *exists
) {
    uint32_t all = red | black;
    if (
        exists == NULL || (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 || reversible_plies > 255
    ) {
        return 1;
    }
    Position position;
    position.red = red;
    position.black = black;
    position.kings = kings;
    position.turn = (uint8_t)turn;
    position.reversible_plies = (uint8_t)reversible_plies;
    *exists = qsearch_has_capture_fast_man_geometry(position) ? 1 : 0;
    return 0;
}
#endif

#if MAKHOS_QSEARCH_CAPTURE_ONLY
/* Test-only export for differential checking of the separate qsearch capture
 * generator.  The caller owns the output buffer; production search never
 * calls this entry point. */
MAKHOS_API int makhos_qsearch_capture_moves(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    Move *moves,
    uint32_t capacity,
    uint32_t *count
) {
    uint32_t all = red | black;
    if (
        count == NULL || (moves == NULL && capacity != 0) ||
        (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 || reversible_plies > 255
    ) {
        return 1;
    }
    Position position;
    position.red = red;
    position.black = black;
    position.kings = kings;
    position.turn = (uint8_t)turn;
    position.reversible_plies = (uint8_t)reversible_plies;

    MoveList generated;
    generate_capture_moves(position, &generated);
    *count = generated.count;
    if (capacity < generated.count) {
        return 2;
    }
    if (generated.count != 0) {
        memcpy(moves, generated.moves, (size_t)generated.count * sizeof(*moves));
    }
    return 0;
}
#endif

MAKHOS_API int makhos_search(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    int hash_power,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    Position root;
    if (hash_power < 12 || hash_power > 24) return 1;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;

    NativeSearchContext context;
    if (!initialize_native_search(
        &context,
        hash_power,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history,
        history_count
    )) {
        return 2;
    }
    status = execute_native_search(&context, root, 1, max_depth, 0, result);
    destroy_native_search(&context);
    return status;
}

MAKHOS_API void *makhos_search_create(int hash_power) {
    if (hash_power < 12 || hash_power > 24) return NULL;
    NativeSearchContext *context = malloc(sizeof(*context));
    if (context == NULL) return NULL;
    if (!allocate_native_search(context, hash_power)) {
        free(context);
        return NULL;
    }
    return context;
}

MAKHOS_API int makhos_search_shared_tt_available(void) {
    return MAKHOS_SHARED_TT ? 1 : 0;
}

MAKHOS_API void *makhos_search_create_shared(void *owner_handle) {
#if MAKHOS_SHARED_TT
    if (owner_handle == NULL) return NULL;
    NativeSearchContext *context = malloc(sizeof(*context));
    if (context == NULL) return NULL;
    if (!allocate_native_search_shared(context, owner_handle)) {
        free(context);
        return NULL;
    }
    return context;
#else
    (void)owner_handle;
    return NULL;
#endif
}

MAKHOS_API void makhos_search_destroy(void *handle) {
    if (handle == NULL) return;
    NativeSearchContext *context = handle;
    destroy_native_search(context);
    free(context);
}

static int clear_native_search(void *handle, bool clear_tt) {
    if (handle == NULL) return 1;
    NativeSearchContext *context = handle;
    if (clear_tt) {
        memset(context->tt, 0, context->tt_count * sizeof(*context->tt));
#if MAKHOS_SHARED_TT
        atomic_store_explicit(
            &context->shared_tt->generation,
            1,
            memory_order_relaxed
        );
#endif
    }
    memset(context->killers, 0, sizeof(context->killers));
    memset(context->killer_count, 0, sizeof(context->killer_count));
    memset(context->history, 0, sizeof(context->history));
    context->has_cached_root_best = false;
    context->history_lookup_ready = false;
    context->allocation_failed = false;
    context->stopped = false;
#if MAKHOS_ITERATIVE_SESSION
    context->session_active = false;
    context->session_history_count = 0;
#endif
    context->generation = 1;
#if MAKHOS_SEARCH_TELEMETRY
    memset(&context->telemetry, 0, sizeof(context->telemetry));
#endif
#if MAKHOS_IIR_CENSUS
    memset(
        &context->iir_census_telemetry,
        0,
        sizeof(context->iir_census_telemetry)
    );
#endif
#if MAKHOS_REPETITION_CENSUS
    memset(
        &context->repetition_census_telemetry,
        0,
        sizeof(context->repetition_census_telemetry)
    );
#endif
#if MAKHOS_QSEARCH_TT_CENSUS
    memset(
        context->qtt_census,
        0,
        context->qtt_census_count * sizeof(*context->qtt_census)
    );
    memset(
        &context->qtt_census_telemetry,
        0,
        sizeof(context->qtt_census_telemetry)
    );
#endif
    return 0;
}

MAKHOS_API int makhos_search_clear(void *handle) {
    return clear_native_search(handle, true);
}

MAKHOS_API int makhos_search_clear_local(void *handle) {
    return clear_native_search(handle, false);
}

#if MAKHOS_NATIVE_ROOT_PVS_SMP
MAKHOS_API uint64_t makhos_search_memory_bytes(void *handle);

static int native_root_pvs_power_for_budget(uint64_t bytes) {
    uint64_t entries = bytes / (uint64_t)sizeof(NativeTTEntry);
    int power = 0;
    while (power < 24 && (UINT64_C(1) << (power + 1)) <= entries) {
        ++power;
    }
    if (power < 12) power = 12;
    if (power > 24) power = 24;
    return power;
}

static uint64_t native_root_pvs_tt_bytes(int power) {
    return (UINT64_C(1) << power) * (uint64_t)sizeof(NativeTTEntry);
}

static void destroy_native_root_pvs_handle(NativeRootPvsHandle *handle) {
    if (handle == NULL) return;
    atomic_store_explicit(&handle->shutdown, true, memory_order_release);
    for (uint32_t index = 0; index < handle->created_helpers; ++index) {
        SetEvent(handle->start_events[index]);
    }
    for (uint32_t index = 0; index < handle->created_helpers; ++index) {
        WaitForSingleObject(handle->worker_threads[index], INFINITE);
        CloseHandle(handle->worker_threads[index]);
        handle->worker_threads[index] = NULL;
    }
    for (uint32_t index = 0; index < handle->helper_count; ++index) {
        if (handle->start_events[index] != NULL) {
            CloseHandle(handle->start_events[index]);
            handle->start_events[index] = NULL;
        }
        if (handle->done_events[index] != NULL) {
            CloseHandle(handle->done_events[index]);
            handle->done_events[index] = NULL;
        }
    }
    for (uint32_t index = 0; index < handle->allocated_helpers; ++index) {
        destroy_native_search(&handle->helpers[index]);
    }
    if (handle->main_allocated) destroy_native_search(&handle->main_context);
    free(handle);
}

static void reset_native_root_pvs_stats(NativeRootPvsHandle *handle) {
    memset(&handle->stats, 0, sizeof(handle->stats));
    handle->stats.requested_threads = handle->requested_threads;
    handle->stats.effective_threads = handle->effective_threads;
    handle->stats.main_hash_power = (uint32_t)handle->main_hash_power;
    handle->stats.helper_hash_power = handle->helper_count > 0
        ? (uint32_t)handle->helper_hash_power
        : 0;
    handle->stats.allocated_tt_bytes = native_root_pvs_tt_bytes(
        handle->main_hash_power
    );
    if (handle->helper_count > 0) {
        handle->stats.allocated_tt_bytes +=
            (uint64_t)handle->helper_count *
            native_root_pvs_tt_bytes(handle->helper_hash_power);
    }
    for (uint32_t index = 0; index < handle->helper_count; ++index) {
        NativeRootPvsWorker *worker = &handle->workers[index];
        worker->tasks_started = 0;
        worker->tasks_completed = 0;
        worker->fail_highs = 0;
        worker->tasks_aborted = 0;
        worker->failures = 0;
    }
}

MAKHOS_API int makhos_root_pvs_shadow_available(void) {
    return 1;
}

MAKHOS_API const char *makhos_root_pvs_shadow_backend(void) {
    return "native-authoritative-root-pvs-shadow-candidate";
}

MAKHOS_API void *makhos_root_pvs_shadow_create(int threads, int hash_mb) {
    if (
        threads < 1 || threads > MAKHOS_NATIVE_ROOT_PVS_MAX_THREADS ||
        hash_mb < 1 || hash_mb > 65536
    ) {
        return NULL;
    }
    uint64_t total_bytes = (uint64_t)hash_mb * UINT64_C(1024) * UINT64_C(1024);
    uint32_t helper_count = (uint32_t)(threads - 1);
    int main_power = 12;
    int helper_power = 0;
    uint64_t allocated_tt_bytes = 0;
    for (;;) {
        uint64_t main_budget = helper_count > 0
            ? total_bytes * UINT64_C(5) / UINT64_C(8)
            : total_bytes;
        main_power = native_root_pvs_power_for_budget(main_budget);
        allocated_tt_bytes = native_root_pvs_tt_bytes(main_power);
        if (helper_count > 0) {
            uint64_t helper_budget =
                (total_bytes - main_budget) / (uint64_t)helper_count;
            helper_power = native_root_pvs_power_for_budget(helper_budget);
            allocated_tt_bytes +=
                (uint64_t)helper_count *
                native_root_pvs_tt_bytes(helper_power);
        } else {
            helper_power = 0;
        }
        if (allocated_tt_bytes <= total_bytes) break;
        if (helper_count == 0) return NULL;
        --helper_count;
    }

    NativeRootPvsHandle *handle = calloc(1, sizeof(*handle));
    if (handle == NULL) return NULL;
    atomic_init(&handle->control.stop, false);
    atomic_init(&handle->shutdown, false);
    for (uint32_t index = 0; index < MAX_MOVES; ++index) {
        atomic_init(&handle->task_states[index], 0);
    }
    handle->requested_threads = (uint32_t)threads;
    handle->effective_threads = helper_count + 1;
    handle->helper_count = helper_count;
    handle->main_hash_power = main_power;
    handle->helper_hash_power = helper_power;

    if (!allocate_native_search(&handle->main_context, main_power)) {
        destroy_native_root_pvs_handle(handle);
        return NULL;
    }
    handle->main_allocated = true;
    for (uint32_t index = 0; index < helper_count; ++index) {
        if (!allocate_native_search(&handle->helpers[index], helper_power)) {
            destroy_native_root_pvs_handle(handle);
            return NULL;
        }
        ++handle->allocated_helpers;
    }

    for (uint32_t index = 0; index < helper_count; ++index) {
        handle->workers[index].owner = handle;
        handle->workers[index].index = index;
        handle->start_events[index] = CreateEventA(NULL, FALSE, FALSE, NULL);
        handle->done_events[index] = CreateEventA(NULL, FALSE, FALSE, NULL);
        if (
            handle->start_events[index] == NULL ||
            handle->done_events[index] == NULL
        ) {
            destroy_native_root_pvs_handle(handle);
            return NULL;
        }
        handle->worker_threads[index] = CreateThread(
            NULL,
            0,
            run_native_root_pvs_worker,
            &handle->workers[index],
            0,
            NULL
        );
        if (handle->worker_threads[index] == NULL) {
            destroy_native_root_pvs_handle(handle);
            return NULL;
        }
        ++handle->created_helpers;
    }
    reset_native_root_pvs_stats(handle);
    return handle;
}

MAKHOS_API void makhos_root_pvs_shadow_destroy(void *opaque) {
    if (opaque == NULL) return;
    NativeRootPvsHandle *handle = opaque;
    if (handle->running) return;
    destroy_native_root_pvs_handle(handle);
}

MAKHOS_API int makhos_root_pvs_shadow_clear(void *opaque) {
    if (opaque == NULL) return 1;
    NativeRootPvsHandle *handle = opaque;
    if (handle->running) return 1;
    if (clear_native_search(&handle->main_context, true) != 0) return 2;
    for (uint32_t index = 0; index < handle->helper_count; ++index) {
        if (clear_native_search(&handle->helpers[index], true) != 0) return 2;
    }
    reset_native_root_pvs_stats(handle);
    return 0;
}

MAKHOS_API int makhos_root_pvs_shadow_run(
    void *opaque,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (opaque == NULL) return 1;
    NativeRootPvsHandle *handle = opaque;
    if (handle->running) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;

    handle->running = true;
    reset_native_root_pvs_stats(handle);
    prepare_native_search(
        &handle->main_context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history,
        history_count
    );
    double common_start = handle->main_context.start;
    for (uint32_t index = 0; index < handle->helper_count; ++index) {
        NativeSearchContext *context = &handle->helpers[index];
        prepare_native_search(
            context,
            no_progress_plies,
            repetition_limit,
            0,
            history,
            history_count
        );
        context->start = common_start;
        context->has_deadline = handle->main_context.has_deadline;
        context->deadline = handle->main_context.deadline;
        context->root_pvs_control = &handle->control;
    }
    atomic_store_explicit(&handle->control.stop, false, memory_order_release);

    status = execute_native_search_impl(
        &handle->main_context,
        root,
        1,
        max_depth,
        0,
        handle,
        result
    );
    finish_native_root_pvs_shadow_iteration(handle);
    atomic_store_explicit(&handle->control.stop, true, memory_order_release);

    handle->stats.main_nodes = handle->main_context.nodes;
    for (uint32_t index = 0; index < handle->helper_count; ++index) {
        NativeSearchContext *context = &handle->helpers[index];
        NativeRootPvsWorker *worker = &handle->workers[index];
        context->root_pvs_control = NULL;
        handle->stats.helper_nodes += context->nodes;
        handle->stats.scout_tasks_started += worker->tasks_started;
        handle->stats.scout_tasks_completed += worker->tasks_completed;
        handle->stats.scout_fail_highs += worker->fail_highs;
        handle->stats.scout_tasks_aborted += worker->tasks_aborted;
        handle->stats.worker_failures += worker->failures;
    }
    handle->running = false;
    return status;
}

MAKHOS_API int makhos_root_pvs_shadow_stats(
    void *opaque,
    MakhosRootPvsStats *output
) {
    if (opaque == NULL || output == NULL) return 1;
    NativeRootPvsHandle *handle = opaque;
    if (handle->running) return 1;
    *output = handle->stats;
    return 0;
}

MAKHOS_API uint64_t makhos_root_pvs_shadow_memory_bytes(void *opaque) {
    if (opaque == NULL) return 0;
    NativeRootPvsHandle *handle = opaque;
    uint64_t bytes = (uint64_t)sizeof(*handle) -
        (uint64_t)sizeof(handle->main_context) -
        (uint64_t)sizeof(handle->helpers);
    bytes += makhos_search_memory_bytes(&handle->main_context);
    for (uint32_t index = 0; index < handle->helper_count; ++index) {
        bytes += makhos_search_memory_bytes(&handle->helpers[index]);
    }
    return bytes;
}
#endif

#if MAKHOS_NATIVE_LAZY_SMP
MAKHOS_API int makhos_lazy_smp_available(void) {
    return 1;
}

MAKHOS_API void *makhos_lazy_smp_create(int threads, int hash_power) {
    if (
        threads < 1 || threads > MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS ||
        hash_power < 12 || hash_power > 24
    ) {
        return NULL;
    }
    NativeLazySmpHandle *handle = calloc(1, sizeof(*handle));
    if (handle == NULL) return NULL;
    if (!allocate_native_search(&handle->workers[0], hash_power)) {
        free(handle);
        return NULL;
    }
    uint32_t allocated = 1;
    for (uint32_t index = 1; index < (uint32_t)threads; ++index) {
        if (!allocate_native_search_shared(
            &handle->workers[index],
            &handle->workers[0]
        )) {
            while (allocated > 0) {
                --allocated;
                destroy_native_search(&handle->workers[allocated]);
            }
            free(handle);
            return NULL;
        }
        ++allocated;
    }
    atomic_init(&handle->control.stop, false);
    handle->threads = (uint32_t)threads;
    return handle;
}

MAKHOS_API void makhos_lazy_smp_destroy(void *handle) {
    if (handle == NULL) return;
    NativeLazySmpHandle *lazy = handle;
    for (uint32_t index = lazy->threads; index > 0; --index) {
        destroy_native_search(&lazy->workers[index - 1]);
    }
    free(lazy);
}

MAKHOS_API int makhos_lazy_smp_clear(void *handle) {
    if (handle == NULL) return 1;
    NativeLazySmpHandle *lazy = handle;
    if (lazy->running) return 1;
    if (clear_native_search(&lazy->workers[0], true) != 0) return 1;
    for (uint32_t index = 1; index < lazy->threads; ++index) {
        if (clear_native_search(&lazy->workers[index], false) != 0) return 1;
    }
    atomic_store_explicit(&lazy->control.stop, false, memory_order_release);
    memset(&lazy->stats, 0, sizeof(lazy->stats));
    return 0;
}

MAKHOS_API int makhos_lazy_smp_run(
    void *handle,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    NativeLazySmpHandle *lazy = handle;
    if (lazy->running) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;

    lazy->running = true;
    memset(&lazy->stats, 0, sizeof(lazy->stats));
    lazy->stats.requested_threads = lazy->threads;
    atomic_store_explicit(&lazy->control.stop, false, memory_order_release);
    lazy->control.has_deadline = time_ms > 0;
    double common_start = search_now_seconds();
    lazy->control.deadline = lazy->control.has_deadline
        ? common_start + (double)time_ms / 1000.0
        : 0.0;

    for (uint32_t index = 0; index < lazy->threads; ++index) {
        NativeSearchContext *context = &lazy->workers[index];
        prepare_native_search(
            context,
            no_progress_plies,
            repetition_limit,
            0,
            history,
            history_count
        );
        context->start = common_start;
        context->has_deadline = lazy->control.has_deadline;
        context->deadline = lazy->control.deadline;
        context->lazy_smp_control = &lazy->control;
    }

    NativeLazySmpJob jobs[MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS];
    HANDLE threads[MAKHOS_NATIVE_LAZY_SMP_MAX_THREADS];
    memset(jobs, 0, sizeof(jobs));
    memset(threads, 0, sizeof(threads));
    HANDLE start_event = CreateEventA(NULL, TRUE, FALSE, NULL);
    if (start_event == NULL) {
        status = 2;
        goto lazy_smp_cleanup;
    }

    uint32_t created = 0;
    for (uint32_t index = 0; index < lazy->threads; ++index) {
        jobs[index].context = &lazy->workers[index];
        jobs[index].root = root;
        jobs[index].max_depth = max_depth;
        jobs[index].root_order_rotation =
            MAKHOS_NATIVE_LAZY_SMP_ROOT_ROTATION ? index : 0;
        jobs[index].start_event = start_event;
        threads[index] = CreateThread(
            NULL,
            0,
            run_native_lazy_smp_worker,
            &jobs[index],
            0,
            NULL
        );
        if (threads[index] == NULL) {
            status = 2;
            atomic_store_explicit(&lazy->control.stop, true, memory_order_release);
            break;
        }
        ++created;
    }

    if (SetEvent(start_event) == 0) {
        status = 2;
        atomic_store_explicit(&lazy->control.stop, true, memory_order_release);
    }
    if (created > 0) {
        DWORD waited = WaitForMultipleObjects(created, threads, TRUE, INFINITE);
        if (waited != WAIT_OBJECT_0) {
            status = 2;
            atomic_store_explicit(&lazy->control.stop, true, memory_order_release);
            /* Keep jobs and the shared control alive until every worker exits. */
            for (uint32_t index = 0; index < created; ++index) {
                if (WaitForSingleObject(threads[index], INFINITE) != WAIT_OBJECT_0) {
                    status = 2;
                }
            }
        }
    }
    for (uint32_t index = 0; index < created; ++index) {
        CloseHandle(threads[index]);
    }
    CloseHandle(start_event);

    if (created != lazy->threads) {
        status = 2;
    }
    for (uint32_t index = 0; index < created; ++index) {
        lazy->stats.worker_nodes[index] = lazy->workers[index].nodes;
        lazy->stats.worker_depth[index] = jobs[index].result.depth;
        lazy->stats.aggregate_nodes += lazy->workers[index].nodes;
        if (jobs[index].status == 0) ++lazy->stats.completed_threads;
        if (jobs[index].status == 2) status = 2;
    }
    lazy->stats.leader_nodes = lazy->workers[0].nodes;
    lazy->stats.leader_depth = jobs[0].result.depth;
    if (status == 0) {
        status = jobs[0].status;
        if (status == 0) *result = jobs[0].result;
    }

lazy_smp_cleanup:
    for (uint32_t index = 0; index < lazy->threads; ++index) {
        lazy->workers[index].lazy_smp_control = NULL;
    }
    lazy->running = false;
    return status;
}
#endif

#if MAKHOS_SEARCH_TELEMETRY
MAKHOS_API int makhos_search_telemetry(
    void *handle,
    MakhosSearchTelemetry *telemetry
) {
    if (handle == NULL || telemetry == NULL) return 1;
    const NativeSearchContext *context = handle;
    *telemetry = context->telemetry;
    return 0;
}
#endif

#if MAKHOS_IIR_CENSUS
MAKHOS_API int makhos_search_iir_census(
    void *handle,
    MakhosIirCensusTelemetry *telemetry
) {
    if (handle == NULL || telemetry == NULL) return 1;
    const NativeSearchContext *context = handle;
    *telemetry = context->iir_census_telemetry;
    return 0;
}
#endif

#if MAKHOS_REPETITION_CENSUS
MAKHOS_API int makhos_search_repetition_census(
    void *handle,
    MakhosRepetitionCensusTelemetry *telemetry
) {
    if (handle == NULL || telemetry == NULL) return 1;
    const NativeSearchContext *context = handle;
    *telemetry = context->repetition_census_telemetry;
    return 0;
}
#endif

#if MAKHOS_QSEARCH_TT_CENSUS
MAKHOS_API int makhos_search_qtt_census(
    void *handle,
    MakhosQttCensusTelemetry *telemetry
) {
    if (handle == NULL || telemetry == NULL) return 1;
    const NativeSearchContext *context = handle;
    *telemetry = context->qtt_census_telemetry;
    telemetry->table_entries = (uint64_t)context->qtt_census_count;
    return 0;
}
#endif

MAKHOS_API uint64_t makhos_search_memory_bytes(void *handle) {
    if (handle == NULL) return 0;
    const NativeSearchContext *context = handle;
    uint64_t bytes =
        (uint64_t)sizeof(*context) +
        (uint64_t)context->history_lookup_capacity *
            (uint64_t)sizeof(*context->history_lookup) +
        (uint64_t)context->workspace_count *
            (uint64_t)sizeof(MoveList);
#if MAKHOS_ITERATIVE_SESSION
    bytes += (uint64_t)context->session_history_capacity *
        (uint64_t)sizeof(*context->session_history);
#endif
#if MAKHOS_SHARED_TT
    if (context->owns_shared_tt) {
        bytes +=
            (uint64_t)sizeof(*context->shared_tt) +
            (uint64_t)context->tt_count * (uint64_t)sizeof(*context->tt);
    }
#else
    bytes +=
        (uint64_t)context->tt_count * (uint64_t)sizeof(*context->tt);
#endif
#if MAKHOS_QSEARCH_TT_CENSUS
    bytes +=
        (uint64_t)context->qtt_census_count *
        (uint64_t)sizeof(*context->qtt_census);
#endif
    return bytes;
}

MAKHOS_API uint64_t makhos_search_workspace_lists(void *handle) {
    if (handle == NULL) return 0;
    const NativeSearchContext *context = handle;
    return (uint64_t)context->workspace_count;
}

#if MAKHOS_NATIVE_LAZY_SMP
MAKHOS_API uint64_t makhos_lazy_smp_memory_bytes(void *handle) {
    if (handle == NULL) return 0;
    const NativeLazySmpHandle *lazy = handle;
    uint64_t bytes = (uint64_t)sizeof(*lazy) -
        (uint64_t)lazy->threads * (uint64_t)sizeof(NativeSearchContext);
    for (uint32_t index = 0; index < lazy->threads; ++index) {
        bytes += makhos_search_memory_bytes((void *)&lazy->workers[index]);
    }
    return bytes;
}

MAKHOS_API int makhos_lazy_smp_stats(
    void *handle,
    MakhosLazySmpStats *output
) {
    if (handle == NULL || output == NULL) return 1;
    const NativeLazySmpHandle *lazy = handle;
    *output = lazy->stats;
    return 0;
}

#endif

MAKHOS_API uint64_t makhos_search_tt_entry_bytes(void) {
    return (uint64_t)sizeof(NativeTTEntry);
}

MAKHOS_API int makhos_search_compact_move_selftest(void) {
    Move original;
    memset(&original, 0, sizeof(original));
    original.path_len = MAKHOS_MAX_PATH;
    original.capture_count = MAKHOS_MAX_PATH - 1;
    original.promotes = 1;
    for (uint8_t index = 0; index < original.path_len; ++index) {
        original.path[index] = (uint8_t)((index * 7 + 3) & 31);
    }
    for (uint8_t index = 0; index < original.capture_count; ++index) {
        original.captured[index] = (uint8_t)((index * 11 + 5) & 31);
    }
#if MAKHOS_COMPACT_TT
    NativeCompactMove compact;
    compact_tt_move(&compact, &original);
    if (!same_compact_tt_move(&original, &compact)) return 1;
    Move expanded;
    expand_compact_tt_move(&expanded, &compact);
    if (!same_move(&original, &expanded)) return 7;

    Move changed = original;
    changed.path[MAKHOS_MAX_PATH - 1] ^= 1;
    if (same_compact_tt_move(&changed, &compact)) return 2;
    changed = original;
    changed.captured[MAKHOS_MAX_PATH - 2] ^= 1;
    if (same_compact_tt_move(&changed, &compact)) return 3;
    changed = original;
    changed.path_len -= 1;
    if (same_compact_tt_move(&changed, &compact)) return 4;
    changed = original;
    changed.capture_count -= 1;
    if (same_compact_tt_move(&changed, &compact)) return 5;
    changed = original;
    changed.promotes = 0;
    if (same_compact_tt_move(&changed, &compact)) return 6;
    return 0;
#else
    return 1;
#endif
}

MAKHOS_API int makhos_search_run(
    void *handle,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;
    NativeSearchContext *context = handle;
#if MAKHOS_ITERATIVE_SESSION
    end_native_search_session(context);
#endif
    prepare_native_search(
        context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history,
        history_count
    );
    status = execute_native_search(context, root, 1, max_depth, 0, result);
    return status;
}

#if MAKHOS_ITERATIVE_SESSION
MAKHOS_API int makhos_search_session_available(void) {
    return 1;
}

MAKHOS_API int makhos_search_session_begin(
    void *handle,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;
    return begin_native_search_session(
        handle,
        root,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result
    );
}

MAKHOS_API int makhos_search_session_attach(
    void *handle,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int completed_depth,
    int max_depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;
    return attach_native_search_session(
        handle,
        root,
        completed_depth,
        max_depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result
    );
}

MAKHOS_API int makhos_search_session_advance(
    void *handle,
    int max_depth,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    return advance_native_search_session(handle, max_depth, result);
}

MAKHOS_API int makhos_search_session_end(void *handle) {
    if (handle == NULL) return 1;
    end_native_search_session(handle);
    return 0;
}
#endif

#if MAKHOS_EXPERIMENTAL_SEARCH_APIS
MAKHOS_API int makhos_search_fixed(
    void *handle,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int depth,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;
    NativeSearchContext *context = handle;
    prepare_native_search(
        context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history,
        history_count
    );
    status = execute_native_search(context, root, depth, depth, 0, result);
    if (status != 0) return status;
    return result->depth == (uint32_t)depth ? 0 : 5;
}

MAKHOS_API int makhos_search_window(
    void *handle,
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int depth,
    int alpha,
    int beta,
    int time_ms,
    int no_progress_plies,
    int repetition_limit,
    const MakhosHistoryEntry *history,
    uint32_t history_count,
    MakhosSearchResult *result
) {
    if (handle == NULL) return 1;
    Position root;
    int status = validate_native_search_inputs(
        red,
        black,
        kings,
        turn,
        reversible_plies,
        depth,
        time_ms,
        no_progress_plies,
        repetition_limit,
        history,
        history_count,
        result,
        &root
    );
    if (status != 0) return status;
    if (
        alpha < -MAKHOS_SEARCH_INFINITY ||
        beta > MAKHOS_SEARCH_INFINITY ||
        alpha >= beta
    ) {
        return 1;
    }
    NativeSearchContext *context = handle;
    prepare_native_search(
        context,
        no_progress_plies,
        repetition_limit,
        time_ms,
        history,
        history_count
    );
    return execute_native_window_search(
        context, root, depth, alpha, beta, result
    );
}
#endif

MAKHOS_API int makhos_fnv1a_file_ranges(
    const char *path,
    const uint64_t *offsets,
    const uint64_t *lengths,
    uint32_t range_count,
    uint64_t *output
) {
    if (
        path == NULL || offsets == NULL || lengths == NULL ||
        range_count == 0 || output == NULL
    ) {
        return 1;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) return 2;
    const size_t buffer_size = (size_t)1 << 20;
    uint8_t *buffer = malloc(buffer_size);
    if (buffer == NULL) {
        fclose(file);
        return 3;
    }
    uint64_t checksum = UINT64_C(1469598103934665603);
    bool ok = true;
    for (uint32_t range = 0; ok && range < range_count; ++range) {
#if defined(_WIN32)
        if (_fseeki64(file, (__int64)offsets[range], SEEK_SET) != 0) {
            ok = false;
            break;
        }
#else
        if (fseeko(file, (off_t)offsets[range], SEEK_SET) != 0) {
            ok = false;
            break;
        }
#endif
        uint64_t remaining = lengths[range];
        while (remaining > 0) {
            size_t wanted = remaining < buffer_size
                ? (size_t)remaining
                : buffer_size;
            if (fread(buffer, 1, wanted, file) != wanted) {
                ok = false;
                break;
            }
            for (size_t index = 0; index < wanted; ++index) {
                checksum ^= buffer[index];
                checksum *= UINT64_C(1099511628211);
            }
            remaining -= wanted;
        }
    }
    free(buffer);
    if (fclose(file) != 0) ok = false;
    if (!ok) return 4;
    *output = checksum;
    return 0;
}

static ExactContext global_three_piece_tablebase;
static ExactCounts global_three_piece_counts;

MAKHOS_API void makhos_tb3_shutdown(void) {
    if (global_three_piece_tablebase.entries != NULL) {
        exact_context_destroy(&global_three_piece_tablebase);
    }
    memset(&global_three_piece_counts, 0, sizeof(global_three_piece_counts));
}

MAKHOS_API int makhos_tb3_init(int no_progress_plies, int hash_power) {
    size_t requested_capacity;
    if (
        no_progress_plies < 1 || no_progress_plies > 200 ||
        hash_power < 16 || hash_power > 28
    ) {
        return 1;
    }
    requested_capacity = (size_t)1 << hash_power;
    if (
        global_three_piece_tablebase.entries != NULL &&
        global_three_piece_tablebase.no_progress_plies == no_progress_plies &&
        global_three_piece_tablebase.capacity == requested_capacity
    ) {
        return 0;
    }
    makhos_tb3_shutdown();
    if (!exact_context_init(
        &global_three_piece_tablebase, no_progress_plies, hash_power, 3
    )) {
        return 2;
    }
    if (!solve_three_piece_roots(
        &global_three_piece_tablebase, &global_three_piece_counts
    )) {
        makhos_tb3_shutdown();
        return 3;
    }
#if defined(_WIN32) && defined(MAKHOS_NO_MAIN)
    /*
     * The complete three-piece hash is about 640 MiB at the required power
     * of 25.  Long-running tablebase/DFPN commands can ask Windows to evict
     * those freshly built private pages from the working set before their
     * own large hashes are allocated.  The pages remain valid and are paged
     * back on demand by makhos_tb3_probe.
     */
    const char *trim_working_set = getenv("MAKHOS_TB3_TRIM_WORKING_SET");
    if (
        trim_working_set != NULL &&
        trim_working_set[0] != '\0' &&
        strcmp(trim_working_set, "0") != 0
    ) {
        (void)SetProcessWorkingSetSize(
            GetCurrentProcess(), (SIZE_T)-1, (SIZE_T)-1
        );
    }
#endif
    return 0;
}

MAKHOS_API int makhos_tb3_probe(
    uint32_t red,
    uint32_t black,
    uint32_t kings,
    int turn,
    int reversible_plies,
    int *outcome,
    int *distance
) {
    if (global_three_piece_tablebase.entries == NULL) {
        return 4;
    }
    uint32_t all = red | black;
    if (
        (red & black) != 0 || (kings & ~all) != 0 ||
        (turn != RED && turn != BLACK) ||
        reversible_plies < 0 ||
        reversible_plies > global_three_piece_tablebase.no_progress_plies ||
        count_bits(all) < 1 || count_bits(all) > 3 ||
        outcome == NULL || distance == NULL
    ) {
        return 1;
    }
    Position position;
    memset(&position, 0, sizeof(position));
    position.red = red;
    position.black = black;
    position.kings = kings;
    position.turn = (uint8_t)turn;
    position.reversible_plies = (uint8_t)reversible_plies;
    ExactValue value;
    if (!exact_solve(&global_three_piece_tablebase, position, 0, &value)) {
        return 3;
    }
    *outcome = value.outcome;
    *distance = value.outcome == OUTCOME_DRAW ? -1 : value.distance;
    return 0;
}

MAKHOS_API uint64_t makhos_tb3_state_count(void) {
    return global_three_piece_tablebase.count;
}

MAKHOS_API uint64_t makhos_tb3_root_count(void) {
    return global_three_piece_counts.roots;
}

#ifndef MAKHOS_NO_MAIN
int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "moves") == 0) {
        return command_moves(argv[2]);
    }
    if (argc == 4 && strcmp(argv[1], "moves-state") == 0) {
        int reversible_plies;
        if (!parse_bounded_int(argv[3], 0, 200, &reversible_plies)) {
            fprintf(stderr, "moves-state requires CLOCK in 0..200\n");
            return 1;
        }
        return command_move_states(argv[2], reversible_plies);
    }
    int depth;
    if (argc == 3 && strcmp(argv[1], "perft") == 0) {
        if (!parse_depth(argv[2], &depth)) {
            fprintf(stderr, "DEPTH must be an integer in 1..15\n");
            return 1;
        }
        return command_perft(depth);
    }
    if (argc == 4 && strcmp(argv[1], "perft-position") == 0) {
        if (!parse_depth(argv[3], &depth)) {
            fprintf(stderr, "DEPTH must be an integer in 1..15\n");
            return 1;
        }
        return command_position_perft(argv[2], depth);
    }
    if (argc == 4 && strcmp(argv[1], "verify-1v1") == 0) {
        int no_progress_plies;
        int hash_power;
        if (
            !parse_bounded_int(argv[2], 1, 200, &no_progress_plies) ||
            !parse_bounded_int(argv[3], 16, 28, &hash_power)
        ) {
            fprintf(stderr, "verify-1v1 requires NO_PROGRESS 1..200 and HASH_POWER 16..28\n");
            return 1;
        }
        return command_verify_one_vs_one(no_progress_plies, hash_power);
    }
    if (argc == 4 && strcmp(argv[1], "verify-3piece") == 0) {
        int no_progress_plies;
        int hash_power;
        if (
            !parse_bounded_int(argv[2], 1, 200, &no_progress_plies) ||
            !parse_bounded_int(argv[3], 16, 28, &hash_power)
        ) {
            fprintf(stderr, "verify-3piece requires NO_PROGRESS 1..200 and HASH_POWER 16..28\n");
            return 1;
        }
        return command_verify_three_piece(no_progress_plies, hash_power);
    }
    if (argc == 5 && strcmp(argv[1], "solve") == 0) {
        int no_progress_plies;
        int hash_power;
        if (
            !parse_bounded_int(argv[3], 1, 200, &no_progress_plies) ||
            !parse_bounded_int(argv[4], 16, 28, &hash_power)
        ) {
            fprintf(stderr, "solve requires NO_PROGRESS 1..200 and HASH_POWER 16..28\n");
            return 1;
        }
        return command_exact_position(argv[2], no_progress_plies, hash_power);
    }
    fprintf(
        stderr,
        "usage:\n"
        "  makhos_native perft DEPTH\n"
        "  makhos_native moves POSITION\n"
        "  makhos_native moves-state POSITION CLOCK\n"
        "  makhos_native perft-position POSITION DEPTH\n"
        "  makhos_native verify-1v1 NO_PROGRESS HASH_POWER\n"
        "  makhos_native verify-3piece NO_PROGRESS HASH_POWER\n"
        "  makhos_native solve POSITION NO_PROGRESS HASH_POWER\n"
    );
    return 1;
}
#endif
