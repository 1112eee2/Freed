/* DESIGN ONLY: additive Phase 1C extension; not part of any production build.
 * Storage/layout assertions, exported calling convention and ctypes mirror
 * must be finalized/tested in C1/C2. Legacy search ABI remains untouched.
 */
#ifndef MAKHOS_PHASE1C_API_SKETCH_H
#define MAKHOS_PHASE1C_API_SKETCH_H
#include <stddef.h>
#include <stdint.h>

#define MAKHOS_ENDGAME_API_V1 1u
typedef struct MakhosTBSet MakhosTBSet;
typedef struct MakhosEndgameSession MakhosEndgameSession;

enum {
    MK_EG_OK = 0, MK_EG_MISS = 1, MK_EG_CANCELLED = 2,
    MK_EG_INVALID = 3, MK_EG_CORRUPT = 4, MK_EG_BUFFER_TOO_SMALL = 5
};

typedef struct {
    int8_t lower; /* -1 LOSS, 0 DRAW, +1 WIN; independent of scalar score. */
    int8_t upper;
    uint8_t reserved[2];
} MakhosWDLInterval;

typedef struct {
    uint32_t red, black, kings;
    uint32_t turn, reversible_plies;
} MakhosEndgamePosition;

typedef struct {
    uint32_t red, black, kings, turn, count; /* repetition key excludes clock */
} MakhosEndgameHistory;

typedef struct {
    uint32_t struct_size, version;
    int32_t outcome; /* Raw history-free outcome; valid only on HIT/OK. */
    int32_t distance; /* -1 = unavailable; never treat raw DTM as history proof. */
    uint32_t material_count, reserved;
} MakhosTBProbe;

typedef struct {
    uint8_t path[17], captured[16]; /* Existing packed-move layout. */
    uint8_t path_len, capture_count, promotes;
} MakhosEndgameMove;

typedef struct {
    uint32_t struct_size, version;
    MakhosEndgameMove move;
    int32_t score;
    MakhosWDLInterval wdl;
    uint32_t completed_depth;
    uint32_t pv_offset, pv_count; /* Into caller-owned packed PV buffer. */
} MakhosEndgameRootResult;

/* Proposed preparation contract:
 * create validates/copies a verified decoded TB3 image; add_ranked pins and
 * validates the actual opened file identity before read-only mapping.
 * seal disallows mutation. Sessions retain sealed sets; close waits for idle.
 * Full create/add_ranked descriptors (identities, uint64 sizes, platform file
 * handles) are deliberately deferred to C1, not represented as unsafe void*.
 */
uint32_t makhos_endgame_api_version(void);
void makhos_tb_set_retain(MakhosTBSet *set);
void makhos_tb_set_release(MakhosTBSet *set);
int32_t makhos_tb_set_probe(const MakhosTBSet *set,
                           const MakhosEndgamePosition *position,
                           MakhosTBProbe *output);

/* Session creation copies history, rules, root-relative ply offset, limits and
 * retains the set. Production uses native evaluation, never a Python callback.
 * A cancelled/partial iteration cannot overwrite the completed root snapshot.
 * get_roots is legal only while idle; all counts are in elements, not bytes.
 */
int32_t makhos_endgame_get_roots(MakhosEndgameSession *session,
                               MakhosEndgameRootResult *roots,
                               uint32_t root_capacity, uint32_t *root_count,
                               MakhosEndgameMove *pv,
                               uint32_t pv_capacity, uint32_t *pv_count);
/* On BUFFER_TOO_SMALL, required counts are returned; no partial result copy. */
/* Thread-safe stop request only. The owner must wait for search completion
 * before collecting the last completed snapshot or destroying the session. */
void makhos_endgame_cancel(MakhosEndgameSession *session);
#endif
