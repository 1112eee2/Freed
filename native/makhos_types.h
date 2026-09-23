#ifndef MAKHOS_TYPES_H
#define MAKHOS_TYPES_H

#include <inttypes.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#if defined(_MSC_VER)
#include <intrin.h>
#endif

#define RED 1
#define BLACK 2
#define MAX_MOVES 4096
#define MAKHOS_MAX_PATH 17
#define MAKHOS_SEARCH_MAX_PLY 96

enum {
    OUTCOME_LOSS = -1,
    OUTCOME_DRAW = 0,
    OUTCOME_WIN = 1
};

typedef struct {
    uint32_t red;
    uint32_t black;
    uint32_t kings;
    uint8_t turn;
    uint8_t reversible_plies;
} Position;

typedef struct {
    uint8_t path[MAKHOS_MAX_PATH];
    uint8_t captured[MAKHOS_MAX_PATH - 1];
    uint8_t path_len;
    uint8_t capture_count;
    uint8_t promotes;
} MakhosPackedMove;

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
    _Atomic uint64_t sequence; /* bit 0 = writer active; bits 1..63 = version */
    _Atomic uint64_t key;      /* strict XOR position key */
    _Atomic uint64_t data;     /* depth (16b), flags (16b), epoch (32b) */
    _Atomic uint64_t move_w0;  /* compact move word 0 (path_low) */
    _Atomic uint64_t move_w1;  /* compact move word 1 (captured_low) */
    _Atomic uint64_t move_w2;  /* compact move word 2 (meta) */
} SharedMoveHintEntry;

/* Memory layout assertions protecting the C/ctypes ABI */
_Static_assert(sizeof(Position) == 16, "Position layout drifted");
_Static_assert(sizeof(MakhosPackedMove) == 36, "packed move layout drifted");
_Static_assert(
    offsetof(Move, path) + sizeof(MakhosPackedMove) == sizeof(Move),
    "Move path metadata is no longer a contiguous packed move"
);
_Static_assert(sizeof(MakhosHistoryEntry) == 16, "history entry layout drifted");
_Static_assert(sizeof(NativeCompactMove) == 24, "compact move layout drifted");
_Static_assert(sizeof(SharedMoveHintEntry) == 48, "SharedMoveHintEntry layout drifted");
_Static_assert(sizeof(SharedMoveHintEntry) % 8 == 0, "SharedMoveHintEntry must be 64-bit aligned");

/* Core bitboard operations */
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

static inline int pop_lsb(uint32_t *bits) {
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

#endif /* MAKHOS_TYPES_H */
