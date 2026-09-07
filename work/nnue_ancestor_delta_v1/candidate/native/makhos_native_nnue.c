/*
 * Phase 7 opt-in NNUE search candidate.
 *
 * Keep this as a separate translation unit so the ordinary native source and
 * accepted DLL remain classical.  The included Phase 6C implementation owns
 * the validated MKNNUE1 loader, incremental accumulator, AVX2 dense evaluator,
 * and AVX2 delta-update kernel.  makhos_native.c adds search integration only
 * when MAKHOS_NNUE_SEARCH_CANDIDATE is enabled here.
 */
#define _CRT_SECURE_NO_WARNINGS
#define MAKHOS_NO_MAIN 1
#define MAKHOS_NNUE_RUNTIME_INCLUDED 1
#define MAKHOS_NNUE_SEARCH_CANDIDATE 1

#include "makhos_nnue_avx2_update.c"
#include "makhos_native.c"
