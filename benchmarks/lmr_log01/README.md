# LMR_LOG_01: late-move reductions by ln(depth) · ln(move number)

Status 2026-09-26: **candidate, default-off, not promoted.** Production, the
GUI release, the accepted DLL, the model and the default build are unchanged.

## Hypothesis

Stronger late-move reductions for quiet moves make the engine stronger at a
fixed time control. Move ordering is already very effective: the ledger
records about 90% of beta cutoffs on the first move, with an average cutoff
index of 0.2. Late quiet moves therefore rarely matter, and reducing them
buys depth.

It is falsified by a paired loss: a FAIL of the Linux screening match below,
or later of either Windows gate. Fixed-depth node counts are not a falsifier,
because this candidate changes the tree by design.

The candidate is measured **on top of the strict TT key**: both players use
`MAKHOS_STRICT_SEARCH_POSITION_KEY=1`, which passed its own Linux screen as
STRICT_KEY_02. The match therefore isolates the reduction change in the likely
next baseline. If the strict key later fails its Windows gates, this result is
conditional on it.

## The rule (`MAKHOS_LMR_LOG=1`)

For the 3rd and later moves of a node (`index >= 2`), when the move is quiet
(no capture, no promotion) and the node's depth is at least 3:

- the reduction is `floor(0.75 + ln(depth) * ln(move number) / 2.25)`;
- depth is capped at 63 and the move number at 31;
- PV nodes (`beta - alpha > 1`) reduce one ply less;
- at least one ply of depth always remains.

The values come from a hardcoded integer table, so every platform reduces
identically. Re-search logic is unchanged: a reduced move that beats alpha is
searched again at full depth. The default build keeps the original rule:
one ply from the 4th move, two from the 7th.

Typical reductions (depth, then move numbers 3 to 12):

| Depth | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| 10 | 1 | 2 | 2 | 2 | 2 | 2 | 2 | 3 | 3 | 3 |
| 20 | 2 | 2 | 2 | 3 | 3 | 3 | 3 | 3 | 3 | 4 |

## Correctness

- Default HCE and NNUE builds are byte-identical to the Linux baselines
  (`c390d641…`, `4178a8f7…`).
- The strict-key build is byte-identical to STRICT_KEY_02's candidate
  (`73aef947…`).
- The candidate builds with clang and gcc under `-Wall -Wextra -Werror`.
- [`tests/test_native_lmr.py`](../../tests/test_native_lmr.py) (3 tests):
  - depth-2 searches match the control node for node;
  - depth-12 searches complete with legal moves;
  - the candidate changes deeper searches.
- The `-LogLmr` build switch has two orchestrator tests.
- Move generation is untouched.

## Speed check (context, not a falsifier)

This uses the 64 census positions from RFP_01: the first 32 of each group,
from the train split. Strict + LMR ran against strict, each position searched
once at depth 16 and once for 500 ms, in fresh contexts with alternating
order:

| Group | Nodes at depth 16 (geometric) | Time to depth 16 | Depth reached in 500 ms | Same move at depth 16 |
|---|---:|---:|---:|---:|
| 11–14 pieces | 0.787× | 0.815× | +1.03 plies | 26/32 |
| 15+ pieces | 0.848× | 0.885× | +1.00 plies | 24/32 |
| All 64 | 0.817× | 0.855× | +1.02 plies | 50/64 |

## Linux screening match (LMR_LOG_01-L1)

The contract is [`contract_l1.json`](contract_l1.json), declared before the
first game:

- players: strict + LMR `125068f2…` against strict `73aef947…`;
- 1 thread each, persistent search, hash power 20, **no tablebases**, project
  rules;
- 2s+0.02s, 6 random opening plies, seed 20261006, two parallel games;
- pentanomial SPRT with H0 = 0 and H1 = +5 Elo, capped at 2,000 pairs.

Decision rule:

- **PASS** → the Windows gates below, after STRICT_KEY_02's;
- **FAIL** → REJECT LMR_LOG_01 as declared;
- **cap** → INCONCLUSIVE, with Elo and interval only.

There is no rerun with another seed.

## Windows gates for Local (only after an L1 PASS)

These run after STRICT_KEY_02's W1/W2, once `BASELINE_HORIZON_01`'s records
exist and the owner agrees. Both builds carry the strict key, so the only
difference is the reduction rule.

```powershell
.\build_nnue_search_candidate.ps1 -OutputDirectory build\lmr01\control -StrictSearchKey
.\build_nnue_search_candidate.ps1 -OutputDirectory build\lmr01\candidate -StrictSearchKey -LogLmr
$c = 'build\lmr01\control\makhos_native_nnue_candidate_v1.dll'
$l = 'build\lmr01\candidate\makhos_native_nnue_candidate_v1.dll'
$m = 'build\nnue_quantized_v1\model_a.mknnue'
python -m unittest tests.test_native_lmr tests.tooling.test_build_orchestrator -v
# W1: 1T intrinsic with production TB4-6, the standard strength bounds.
python -B -m makhos sprt --dev-library $l --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 1 --persistent-search --time 10 --inc 0.1 --elo0 0 --elo1 2 --pairs 4000 --seed 20261007 --parallel-games 2 --output build\lmr01\sprt-w1-1t-10s.json --resume
# W2: production path, 12T and 512 MiB at a fixed 1 s per move, one game at a time.
python -B -m makhos sprt --dev-library $l --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 12 --hash-mb 512 --fixed-move-time-ms 1000 --elo0 0 --elo1 2 --pairs 1000 --seed 20261008 --output build\lmr01\sprt-w2-12t-1s.json --resume
```

**PROMOTE** only if the full suite passes and W1 and W2 both PASS. **REJECT**
on any FAIL. A capped run is **INCONCLUSIVE**.
