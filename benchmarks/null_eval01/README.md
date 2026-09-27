# NULL_EVAL_01: null move only where a fail high is expected

Status 2026-09-27: **candidate, default-off, not promoted.** Production, the
GUI release, the accepted DLL, the model and the default build are unchanged.

## Hypothesis

Trying null move only at null-window nodes whose static evaluation already
reaches beta makes the engine stronger at a fixed time control. The default
search tries null move at every eligible node, including PV nodes and nodes
where the side to move is statically behind. The 2026-08-23 telemetry refresh
in the ledger reports a 48.9% null-cutoff success rate, so about half of those
reduced searches are spent without a cutoff.

It is falsified by a paired loss: a FAIL of the screening match below, or
later of either Windows gate. Fixed-depth node counts are not a falsifier,
because this candidate changes the tree by design.

The ledger rejected disabling null move and a shallower deep reduction. No
admission guard of this kind has been tried.

The candidate is measured **on top of the strict TT key**: both players use
`MAKHOS_STRICT_SEARCH_POSITION_KEY=1`, which passed its Linux screen as
STRICT_KEY_02. It does not include LMR_LOG_01, which is screened separately
against the same control.

## The rule (`MAKHOS_NULL_EVAL_GUARD=1`)

The existing null-move conditions stay: depth at least 3, not the root, no
capture available, more than 6 pieces, and no repeated position. The candidate
adds, in this order:

- a null window (`beta - alpha == 1`);
- beta away from mate bounds (`beta < MAKHOS_SEARCH_MATE - 1000`, the band the
  TT uses for mate scores);
- the static evaluation of the side to move is at least beta.

The evaluation is the last term, so the cheap guards short-circuit it. The
guard only removes null attempts; it never prunes anything the control does
not. The build switch is `-NullEvalGuard`.

## Correctness

- The default build is unchanged: all new code is under
  `#if MAKHOS_NULL_EVAL_GUARD`. The strict-key control built from this branch
  is byte-identical to LMR_LOG_01-L1W's control (`8b82fef8…`).
- Both Windows builds are reproducible (2 byte-identical builds each).
- [`tests/test_native_null_eval.py`](../../tests/test_native_null_eval.py)
  (4 tests):
  - depth-2 searches match the control node for node;
  - a six-piece search matches the control node for node at depth 12, because
    null move needs more than six pieces;
  - depth-12 searches complete with legal moves;
  - the candidate changes deeper searches.
- The `-NullEvalGuard` build switch has two orchestrator tests.
- Move generation is untouched.

## Speed check (context, not a falsifier)

The 64 census positions from RFP_01 (the first 32 of each group of the
128-position census, from the train split), strict + guard against strict,
each searched once at depth 16 and once for 500 ms, in fresh contexts with
alternating order, on Windows:

| Group | Nodes at depth 16 (geometric) | Time to depth 16 | Depth reached in 500 ms | Same move at depth 16 |
|---|---:|---:|---:|---:|
| 11–14 pieces | 0.857× | 0.877× | +0.22 plies | 25/32 |
| 15+ pieces | 0.970× | 0.996× | +0.06 plies | 25/32 |
| All 64 | 0.912× | 0.934× | +0.14 plies | 50/64 |

A second, independent draw of 32 positions per group gave 0.890× nodes,
0.941× time and +0.30 plies. The saving is concentrated in the 11–14-piece
middlegame.

## Windows screening match (NULL_EVAL_01-L1W)

The contract is [`contract_l1w.json`](contract_l1w.json), declared before the
first game:

- players: strict + guard `e4d7b0d3…` against strict `8b82fef8…`;
- 1 thread each, persistent search, hash power 20, **no tablebases**, project
  rules;
- 2s+0.02s, 6 random opening plies, seed 20261009, two parallel games;
- pentanomial SPRT with H0 = 0 and H1 = +5 Elo, capped at 2,000 pairs.

Decision rule:

- **PASS** → the Windows gates below;
- **FAIL** → REJECT NULL_EVAL_01 as declared;
- **cap** → INCONCLUSIVE, with Elo and interval only.

There is no rerun with another seed.

## Windows gates for Local (only after an L1W PASS)

These follow the same order as STRICT_KEY_02's and LMR_LOG_01's gates, once
`BASELINE_HORIZON_01`'s records exist and the owner agrees. Both builds carry
the strict key, so the only difference is the null-move guard.

```powershell
.\build_nnue_search_candidate.ps1 -OutputDirectory build\nullev01\control -StrictSearchKey
.\build_nnue_search_candidate.ps1 -OutputDirectory build\nullev01\candidate -StrictSearchKey -NullEvalGuard
$c = 'build\nullev01\control\makhos_native_nnue_candidate_v1.dll'
$n = 'build\nullev01\candidate\makhos_native_nnue_candidate_v1.dll'
$m = 'build\nnue_quantized_v1\model_a.mknnue'
python -m unittest tests.test_native_null_eval tests.tooling.test_build_orchestrator -v
# W1: 1T intrinsic with production TB4-6, the standard strength bounds.
python -B -m makhos sprt --dev-library $n --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 1 --persistent-search --time 10 --inc 0.1 --elo0 0 --elo1 2 --pairs 4000 --seed 20261010 --parallel-games 2 --output build\nullev01\sprt-w1-1t-10s.json --resume
# W2: production path, 12T and 512 MiB at a fixed 1 s per move, one game at a time.
python -B -m makhos sprt --dev-library $n --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 12 --hash-mb 512 --fixed-move-time-ms 1000 --elo0 0 --elo1 2 --pairs 1000 --seed 20261011 --output build\nullev01\sprt-w2-12t-1s.json --resume
```

**PROMOTE** only if the full suite passes and W1 and W2 both PASS. **REJECT**
on any FAIL. A capped run is **INCONCLUSIVE**.
