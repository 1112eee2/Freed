/*
 * Isolated C3 candidate: the history-safe endgame kernel linked against the
 * already verified NNUE v1 runtime.  This translation unit is intentionally
 * separate from both the accepted HCE DLL and the C2 HCE candidate.
 */
#define _CRT_SECURE_NO_WARNINGS
#define MAKHOS_NO_MAIN 1
#define MAKHOS_NNUE_RUNTIME_INCLUDED 1
#define MAKHOS_NNUE_SEARCH_CANDIDATE 1

#include "makhos_nnue_avx2_update.c"
#include "makhos_native.c"

/* makhos_endgame_search.c normally includes makhos_native.c itself.  The
 * guard tells it that this NNUE-enabled copy is already in the translation
 * unit and keeps the C2 search ABI additive. */
#define MAKHOS_ENDGAME_SEARCH_NATIVE_INCLUDED 1
#include "makhos_endgame_search.c"
