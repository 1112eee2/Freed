#ifndef MAKHOS_ENDGAME_SEARCH_H
#define MAKHOS_ENDGAME_SEARCH_H
#include "makhos_endgame_tb.h"
/* Additive, opt-in C2 reference search ABI. Legacy search ABI is untouched. */
#define MK_EG_SEARCH_VERSION 1u
#define MK_EG_MAX_PLY 96u
#define MK_EG_PLY_LIMIT 8
typedef struct MakhosEndgameSession MakhosEndgameSession;
typedef struct { uint32_t red, black, kings, turn, count; } MakhosEndgameHistory;
typedef struct { uint8_t path[17], captured[16], path_len, capture_count, promotes; } MakhosEndgameMove;
typedef struct {
    uint32_t struct_size, version;
    int32_t score, lower, upper;
    uint32_t depth, pv_count;
    MakhosEndgameMove pv[MK_EG_MAX_PLY];
} MakhosEndgameRoot;
typedef struct {
    uint32_t struct_size, version, completed_depth, root_count;
    uint32_t terminal_reason; /* 0 ongoing, 1 repetition, 2 clock, 3 no moves */
    int32_t score, lower, upper;
    uint64_t nodes, tb_hits[7], repetition_draws;
} MakhosEndgameSummary;
MK_TB_API uint32_t makhos_endgame_search_version(void);
/* One owner per session. run/get/destroy are idle-only except cancel, which is
 * thread-safe. Run copies history, owns private line/workspace and retains TB.
 * No TT scores are read/written; no selective pruning; 1T only.  The
 * translation unit may select the isolated NNUE candidate evaluator, while
 * terminal/TB WDL proofs remain authoritative over scalar evaluation.
 */
MK_TB_API int32_t makhos_endgame_session_create(MakhosTBSet *, MakhosEndgameSession **);
MK_TB_API void makhos_endgame_session_destroy(MakhosEndgameSession *);
MK_TB_API void makhos_endgame_cancel(MakhosEndgameSession *);
MK_TB_API int32_t makhos_endgame_run(MakhosEndgameSession *,
    const MakhosEndgamePosition *, const MakhosEndgameHistory *, uint32_t history_count,
    uint32_t depth, uint32_t no_progress_plies, uint32_t repetition_limit,
    uint32_t time_ms, uint64_t node_limit);
/* CANCELLED returns only the last completed all-root layer (possibly empty).
 * Errors invalidate the snapshot; never publish partial/provisional proofs.
 * BUFFER_TOO_SMALL fills summary with required root_count, copies no roots. */
MK_TB_API int32_t makhos_endgame_results(MakhosEndgameSession *,
    MakhosEndgameSummary *, MakhosEndgameRoot *, uint32_t capacity);
#endif
