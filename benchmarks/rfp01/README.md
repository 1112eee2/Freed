# RFP_01: guarded reverse futility pruning

Status 2026-09-26: **INCONCLUSIVE / NOT_PROMOTED.** The Linux screening match
reached its 2,000-pair cap at +4.1 ± 7.9 Elo, LLR +0.49
([result](#rfp_01-l1-result)), with neither a PASS nor a FAIL. Its contract
reports only the Elo and its interval, and the Windows gates, which need a
PASS, are not triggered. The candidate stays in source, default-off.
Production, the GUI release, the accepted DLL, the model and the default build
are unchanged.

## Hypothesis

At guarded shallow null-window nodes, the static NNUE evaluation can stand in
for the search when it clears beta by 48 per ply of remaining depth. The time
saved makes the engine stronger at a fixed time control.

It is falsified by a paired loss: a FAIL of the Linux screening match below,
or later of either Windows gate. Fixed-depth node counts are not a falsifier,
because this candidate changes the tree by design. On seven positions they
moved both ways, from 0.88× to 1.10× of the control's nodes.

## The rule (`MAKHOS_REVERSE_FUTILITY=1`)

At a main-search node with `ply > 0`, a null window (`beta - alpha == 1`) and
depth 1 to 3, the node returns `beta` when all of the following hold:

- beta is outside the mate-score range;
- neither side has a capture, so no mandatory exchange is pending;
- the side not to move has no man that can promote with a quiet step;
- at least 11 pieces remain;
- the position has not occurred before in the game or the search line;
- the no-progress clock is at least 16 plies short of the draw limit;
- `static evaluation - 48 * depth >= beta`.

The node stores nothing in the TT and clears its PV. Endgames with 10 or
fewer pieces, the band the practical no-loss plan treats as exact-risk, are
never pruned. The parameters are compile-time defaults (`MAKHOS_RFP_MARGIN`,
`MAKHOS_RFP_MAX_DEPTH`, `MAKHOS_RFP_MIN_PIECES`,
`MAKHOS_RFP_NO_PROGRESS_MARGIN`).

## Census: how often would the rule be wrong?

`MAKHOS_RFP_CENSUS=1` builds a measurement library that searches exactly like
the control. At every null-window node of depth 1..4 it records which guard
rejected the node. For guarded nodes it also records `static evaluation -
beta` against the node's real outcome. For any margin `M`, the rule prunes at
depth `d` exactly when that difference is at least `M * d`. The census
therefore gives, for every margin at once, how many guarded nodes would be
pruned and how many of those the real search failed low on.

[`census.py`](census.py) builds the control and the census library from
current source, with the production NNUE search flags. It searches 128
positions from the *train* split of `corpora/nnue_quiet_leaf_pilot_v4.jsonl`,
seed 20260926: 64 with 11–14 pieces and 64 with 15 or more. Every search is
depth 20, hash power 20, NNUE v1, a fresh context and project rules. The
census and control results matched in move, score, nodes and PV on all 128.

The margin was chosen by a rule written down before the table was read: the
smallest margin in the grid whose false-prune rate is at most 1% at every
depth from 1 to 3.

| Depth | Guarded nodes | Margin | Pruned (share of guarded) | Failed low in the real search |
|---:|---:|---:|---:|---:|
| 1 | 16,212,553 | 48 | 8,672,967 (53.5%) | 25,972 (0.30%) |
| 2 | 6,340,384 | 48 | 2,872,649 (45.3%) | 20,065 (0.70%) |
| 3 | 4,244,321 | 48 | 1,937,872 (45.7%) | 4,988 (0.26%) |
| 4 (not used) | 2,711,133 | 48 | 1,090,728 (40.2%) | 3,571 (0.33%) |

With no margin at all, 1.08%, 5.10% and 2.15% of the would-be prunes at
depths 1–3 were wrong, so the margin removes most of the error. The rule
selects **48**.

The output, including the full histograms for every other margin, is
[`census_20260925T172000Z.json`](census_20260925T172000Z.json) (SHA-256
`ebb544b3…`). It was built with Linux clang 18.1.3: census library
`042f9d84…`, control `4178a8f7…`. An earlier run of the same script on the
PR #28 branch source gave identical histograms. That source differed only in
code compiled out of both libraries.

## Speed check (context, not a falsifier)

On the first 32 census positions of each group, the match libraries below
searched once at depth 16 and once for 500 ms, each in a fresh context,
alternating order:

| Group | Nodes at depth 16 (geometric / total) | Time to depth 16 | Positions with fewer nodes | Depth reached in 500 ms |
|---|---:|---:|---:|---:|
| 11–14 pieces | 0.904× / 0.923× | 1.022× | 27/32 | +0.06 plies |
| 15+ pieces | 0.787× / 0.781× | 0.870× | 24/32 | +0.31 plies |
| All 64 | 0.843× / 0.836× | 0.929× | 51/64 | +0.19 plies |

With 11–14 pieces, the extra static evaluations at guarded nodes cost about as
much time as the pruning saves. The expected gain is therefore modest, and the
parameters stay as declared.

## Correctness

- Default builds are byte-identical to the Linux baselines: HCE `c390d641…`
  (built with `-DMAKHOS_NO_MAIN`) and NNUE `4178a8f7…`.
- The candidate and the census build with clang and gcc under
  `-Wall -Wextra -Werror`. The flags cannot be combined.
- [`tests/test_native_rfp.py`](../../tests/test_native_rfp.py) (7 tests):
  - only the census build exports the census;
  - the census build searches like the control;
  - every guarded node gets exactly one outcome;
  - the clock guard works;
  - the candidate is inert below the piece guard and active in the
    middlegame.
- Move generation is untouched, so perft is unaffected.

## Linux screening match (RFP_01-L1)

The contract is [`contract_l1.json`](contract_l1.json), declared before the
first game. It is a screen, not an acceptance gate: 1T, no tablebases,
2s+0.02s, pentanomial SPRT with H0 = 0 and H1 = +5 Elo, capped at 2,000
pairs.

### RFP_01-L1 result

The match ran in the Linux cloud container from a worktree pinned to
`9d22c01`, the commit that holds the contract. Before launch, its libraries,
model and native sources matched the contract's SHA-256 values, and the
harness logged candidate `ce450b06…` against control `4178a8f7…` with seed
20260930. It started at 2026-09-25T17:45:15Z and reached the cap at about
00:40Z on 2026-09-26. The final checkpoint is
[`sprt_l1_20260925_final.json`](sprt_l1_20260925_final.json), SHA-256
`b636d95b…`.

| Pairs | W / D / L | Pentanomial (0–2) | LLR (bounds ±2.94) | Elo, 95% |
|---:|---|---|---:|---|
| 2,000 (cap) | 1,414 / 1,219 / 1,367 | 163 / 393 / 849 / 424 / 171 | +0.49 | +4.1 ± 7.9 |

**Verdict: INCONCLUSIVE.** The 95% interval, about −3.8 to +12.0 Elo,
excludes a large loss but cannot tell +5 from 0. That fits the speed check: a
modest net speedup that the extra static evaluations partly cancel. The
contract forbids a rerun with a new seed, so RFP_01 as declared stops here.
A changed rule would be a new hypothesis with its own contract.

## Windows gates for Local

These run only after an L1 PASS, after `BASELINE_HORIZON_01`'s records exist,
and with the owner's go-ahead. RFP_01-L1 ended INCONCLUSIVE, so they are
**not triggered**. The commands stay here as the record of what was declared.
When run, the GUI must be idle, and they run under the workload lease at
BelowNormal.

```powershell
.\build_nnue_search_candidate.ps1 -OutputDirectory build\rfp01\control
.\build_nnue_search_candidate.ps1 -OutputDirectory build\rfp01\candidate -ReverseFutility
$c = 'build\rfp01\control\makhos_native_nnue_candidate_v1.dll'
$r = 'build\rfp01\candidate\makhos_native_nnue_candidate_v1.dll'
$m = 'build\nnue_quantized_v1\model_a.mknnue'
python -m unittest tests.test_native_rfp tests.tooling.test_build_orchestrator -v
# W1: 1T intrinsic with production TB4-6, the standard strength bounds.
python -B -m makhos sprt --dev-library $r --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 1 --persistent-search --time 10 --inc 0.1 --elo0 0 --elo1 2 --pairs 4000 --seed 20261001 --parallel-games 2 --output build\rfp01\sprt-w1-1t-10s.json --resume
# W2: production path, 12T and 512 MiB at a fixed 1 s per move, one game at a time.
python -B -m makhos sprt --dev-library $r --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 12 --hash-mb 512 --fixed-move-time-ms 1000 --elo0 0 --elo1 2 --pairs 1000 --seed 20261002 --output build\rfp01\sprt-w2-12t-1s.json --resume
```

Decision rule:

- **PROMOTE** only if the full suite passes and W1 and W2 both PASS.
- **REJECT** on any FAIL.
- A capped run is **INCONCLUSIVE**.
