# Current ThaiMakhosEngine state

Updated 2026-10-13. This file owns the current scope and the next action. It is
kept short on purpose: historical commands and counters are evidence, not launch
instructions, and detail that is no longer current lives in the snapshots below.

- Full text before the 2026-10-13 update:
  [history/20261013-current-state-before-director-loop-update.md](history/20261013-current-state-before-director-loop-update.md)
  (this includes the long 2026-09-25 narrative, the PR #28/#31/#32 notes and the
  per-candidate detail that is condensed here).
- Earlier snapshots: [history/20260925-current-state-before-no-loss-track.md](history/20260925-current-state-before-no-loss-track.md).
- The director-loop section below was first committed in `748ac0c` on branch
  `docs/current-state-director-loop-20261013`.

## Director-loop status (2026-10-13)

Written from the process inventory, the `build/runs/` trees and local git refs
on 2026-10-13. For strength work it supersedes the 2026-09-25 text. The
BASELINE_HORIZON_01 gate named there was not re-checked in this session.

**Scope.** NNUE V2 became a main track beside the no-loss track on 2026-10-08
(owner approval, recorded in the handoff). Search candidates run one concept at
a time through four stages:

1. **Screen:** 1T, 2s+0.02s, no tablebases, H0=0/H1=+5, cap 2,000 pairs,
   control = strict TT key (`8b82fef8…`).
2. **W1:** 1T, 10s+0.1s, TB4–6 plus the C4 endgame library, H0=0/H1=+2,
   cap 4,000 pairs.
3. **W2:** 12T/512 MiB, fixed 1 s, 1,000 pairs. It needs the owner's go-ahead
   and an idle machine; the owner asked for it to run at night.
4. **Integrated candidate and full suite.** Gains from separate candidates are
   not assumed to add.

Nothing below is promoted. Production, the accepted DLL, `RULESET.json` and
`makhos/core.py` are unchanged. Screen intervals are wide and screen results
are not promotion evidence.

| Candidate (branch) | Result so far | Now |
|---|---|---|
| STRICT_KEY_02 | Linux screen PASS, +15.9 ± 9.3 Elo. The W1 checkpoint stopped at 1,909 pairs (+9.5 ± 7.3, LLR +1.21); the cause of the stop was not recorded | **W1 resumed** 2026-10-13T07:05Z, pid 25052, seed 20261004. Pre-resume checkpoint SHA-256 `F0D3DCD8…7FFE`, kept as `build/strict02/sprt-w1-1t-10s.pre-resume-20261013.json`. Output `build/strict02/sprt-w1-1t-10s.json`, logs `build/strict02/resume-20261013/` |
| LMR_LOG_01 (`lmr-log-01`, PR #35 per the handoff) | Screen PASS, 967 pairs, +21.4 ± 11.1 Elo (screen seed 20261006) | **W1 running** since 2026-10-13T06:58Z, pid 19692, seed 20261007, tree `build/runs/lmr_w1` |
| NULL_EVAL_01 (`null-eval-01`, local only, 7 ahead of `origin/main`) | Screen PASS, 486 pairs, +42.0 ± 15.8 Elo, LLR +2.95 (seed 20261009) | **W1 running** since 2026-10-13T06:58Z, pid 5408, seed 20261010, tree `build/runs/nullev_w1` |
| HISTORY_MALUS_01 (`history-malus-01`) | Screen PASS, 1,021 pairs, +20.1 ± 10.6 Elo, LLR +2.95 (seed 20261013); QA tests 5/5 and reproducible build per the handoff | W1 not started |
| ITER_PARTIAL_01 (`iter-partial-01`) | **INCONCLUSIVE** at the 2,000-pair cap: +5.5 ± 7.1 Elo, LLR +1.14 (seed 20261012). Raw result in `build/runs/iterpartial_l1w`; only the declaration is committed on its branch | Do not rerun with a new seed; a changed rule is a new hypothesis |
| NNUE2_LABEL_PILOT_01 (`nnue2-label-pilot-01`) | Part 1: NNUE depth-10 labels cost about 12 ms against about 2.6 s per position; 223,473 rows relabelled, no sealed test. Part 2: the NNUE-label model beat the HCE-label model, PASS at 1,563 pairs, +14.2 ± 8.7 Elo, LLR +2.96 (seed 20261017; arms `B956045E…` vs `EE2B86F8…`). One seed per arm, screen settings | Next: freeze the stage-2 data contract. No compute while W1 runs |

**Decision rules.** W1 PASS → W2. FAIL → REJECT as declared. Cap → INCONCLUSIVE,
with no rerun on a new seed. LMR_LOG_01 and NULL_EVAL_01 are both measured on
top of the strict key, so if STRICT_KEY_02 fails W1 or W2 their results are
conditional on it.

**Identities bound to the W1 runs.** Control `8b82fef8…`; LMR candidate
`7cef50eb…`; NULL candidate `e4d7b0d3…`; NNUE v1 model `07b9ab0f…`; C4 endgame
library `eb8af045…`; TB4/5/6 header FNV `89459baa…`, `c9e825ce…`, `7102f551…`.
The two new run trees are copies of the screen trees. They lack `build/tb*` and
`build/native_endgame_c4`, so their commands pass `--ranked-tablebase` with
absolute paths and `--native-endgame-library`. Without those options `sprt`
silently skips absent default tablebase files and fails later on the missing
endgame library. The first launch attempt failed at startup for that reason, with
no game played. Its logs are kept as `sprt-w1-20261013-attempt1-failed-no-endgame-lib`.

**Monitoring.** `build/runs/_status/w1_live_status.ps1` is read-only. It reads
only `stdout.log` and process identity (PID plus creation time), never a running
match's `sprt.json`. `sprt` prints only when a pair finishes, so the "now playing"
line is inferred.

**Open items.**

- The BASELINE_HORIZON_01 gate, which an older owner review set before any W1/W2
  start, is not verified. The owner told this session on 2026-10-13 to start W1
  and to resume STRICT_KEY_02 W1.
- Untracked on `main`: `.claude/`, `scratch/profile_smp_scaling.py`, and a nested
  checkout `ThaiMakhosEngine/` with its own `.git` that no session created. It was
  not touched.
- No relay or automated play against Invincible 2 (2026-09-25 decision), so the
  external baseline can only be gathered by hand.
- The review of game `6ef62f9998d12db4` was only read from the existing log: at
  ply 10 the played move scored -119 against -59 for the best move at 5 s, and at
  ply 12 -291 against -172 at 10 s. It is not concluded and no cause is assigned.

## Next action

1. Wait for the three W1 results (LMR_LOG_01, NULL_EVAL_01, STRICT_KEY_02) and
   apply the decision rules above. Do not start other heavy work meanwhile.
2. For each W1 PASS, run W2 only on an idle machine and with the owner's go-ahead.
3. Light work that does not touch the running trees is allowed: documentation,
   and drafting the NNUE stage-2 data contract. The tech-debt order agreed on
   2026-10-13 starts with trimming this file and the branch/PR clean-up.
4. Not queued: STRICT_KEY_01's gates are withdrawn; TBDRAW_01 needs a
   scope-specific instruction; RFP_01 ended INCONCLUSIVE (see below).

## Standing scope: practical no-loss track against Invincible 2

On 2026-09-25 the user approved the
[practical no-loss track](../../../../docs/architecture/PRACTICAL_NO_LOSS_TRACK.md)
as the active strength scope. The goal is zero losses against Invincible 2 in a
large, frozen, colour-balanced match, reported with a 95% upper bound on the loss
rate and never as "proven perfect". It excludes proof/DFPN work, tablebases of 7
or more pieces, and any Lazy SMP redesign. The track is in Phase 0; no production
default, rules file, model or accepted artifact has changed under it.

Decisions of 2026-09-25 (still in force unless the owner changes them):

- The owner confirmed the F1 form: extract only what the track needs from PR #25
  and keep the Lazy SMP PRs open.
- A game that reaches a `project` draw that Invincible 2 does not declare is
  reported non-comparable. There is no external rules profile and `RULESET.json`
  is unchanged.
- No relay or automated play against Invincible 2, and no permission request for
  now.
- If PR #29 merges, the frozen NNUE-v1 tools stay blocked rather than re-bound.
  Promotion gates then compare plain `unittest discover` failure IDs with `main`'s.

Findings of the 2026-09-25 review, checked against source on that date and not
re-verified since:

- The root safety policy in `search.py` (`_choose`/`_safety_rank`) runs only on the
  native-endgame route and on the Python paths. The production 12T middlegame uses
  `ParallelNativeSearch._choose`: the highest score wins, with no WDL bound or mode.
  PR #31 (F2) centralized the root choice without a policy change, so a safety-first
  policy (Phase 2) is still to be designed.
- The F3 schema work is partly done: PR #30 aligned `thai-makhos-game-v1` with the
  GUI's records. `sprt --games-dir` records still fail that schema (the top-level
  `match` key, the per-move engine `role`, missing engine fields). They are
  replay-validated only and not gate evidence until the recorder is aligned.
- Invincible 2 reportedly has a database of 10 or fewer pieces and a 300M-position
  book. The page confirms none of this. Its script declares threefold repetition a
  draw only at 10 or fewer pieces, has no no-progress limit and declares one king
  each a draw, so our TB4–TB6 draws, which assume the 80-ply limit, are not
  guaranteed draws against that service (track §3.5).
- The staged review of game `6ef62f9998d12db4` needs Windows, an idle GUI, the game
  DLL `32c32302…`, NNUE v1 `07b9ab0f…` and the gitignored saved game. The frozen
  matrix is `BASELINE_HORIZON_01` in
  [PR #27](https://github.com/1112eee2/ThaiMakhosEngine/pull/27).

## Default-off candidates (before the director loop)

| Candidate | State |
|---|---|
| STRICT_KEY_01 | **REJECT_AS_DECLARED / NOT_PROMOTED.** The depth-20 screen met its declared falsifier, a repeatable fixed-depth slowdown (1.147× and 1.037× total time). It remains correctness evidence: the legacy key made 20.3% and 4.3% of TT cutoffs false, strict none. Linux match stopped at 344 pairs, +19.7 ± 17.8 Elo, INCONCLUSIVE; do not resume. Windows gates withdrawn. ([README](../../../../benchmarks/strict_tt_key/README.md)) |
| STRICT_KEY_02 | The same flag under a paired-play hypothesis. Linux screen PASS 2026-09-26: strict `73aef947` against control `4178a8f7`, 1T, no tablebases, 2s+0.02s, seed 20261003, H0=0/H1=+5, stopped at 1,281 pairs (945/789/828), pentanomial 83/199/623/270/106, LLR +2.96, +15.9 ± 9.3 Elo. W1 status is in the director-loop table. ([README](../../../../benchmarks/strict_tt_key/README.md)) |
| TBDRAW_01 | Main search returns 0 at non-root nodes on an exact tablebase DRAW. INCONCLUSIVE / NOT_PROMOTED; on `main` since PR #28, default-off, 8 tests, default build byte-identical, no paired result. ([README](../../../../benchmarks/tb_frontier/README.md)) |
| RFP_01 | Reverse futility at guarded shallow null-window nodes with 11 or more pieces, margin 48. **RFP_01-L1: INCONCLUSIVE / NOT_PROMOTED** at the 2,000-pair cap: 1,414/1,219/1,367, pentanomial 163/393/849/424/171, LLR +0.49, +4.1 ± 7.9 Elo. No rerun with a new seed. ([README](../../../../benchmarks/rfp01/README.md)) |

Tooling on `main` since PR #28, each default-off: `sprt --games-dir`
(replay-validated only), `bench-native --candidate/--baseline-nnue-model` and
`analyze-game --nnue-model`.

## Repository and PR state

- `main` is at `664e981` (2026-10-13). Since `a0f7964` (PR #17) these merged:
  #28 (no-loss track docs, match tooling, STRICT_KEY_01 evidence, TBDRAW_01),
  #30 (game schema), #31 (root-choice refactor, no policy change), #32 (RFP_01),
  #33 and #34 (the STRICT_KEY_02 declaration and its Linux screen evidence).
  Production 12T/C4 defaults, the model and the accepted DLL are unchanged.
- Open and unmerged as of 2026-09-25 (not re-listed since; this machine has no
  `gh`): #18–#20, #22, #24 and #26 (the Lazy SMP G2 evidence stack), #25 (the Lazy
  SMP candidate, marked `REJECT_FOR_PERFORMANCE / NOT_PROMOTED` by #26), #21 (the
  self-drive loop), #27 (the strength-loop handoff) and #29 (a draft Linux lease
  fix). None of them changes production. The Lazy SMP design document is a
  reviewed proposal, not a backend.
- The tech-debt roadmap (Phases 0–3, PRs #7–#16) is complete; see
  [the roadmap](../../../../docs/architecture/TECH_DEBT_ROADMAP_TH.md).

## Latest accepted correctness change

[PR #6](https://github.com/1112eee2/ThaiMakhosEngine/pull/6) merged as
`e975d6843ee23e9fe42a3662f5d802516293796e`: native C4 admission now covers legal
multi-captures from more than 6 pieces into 6 or fewer. It was merged under a
correctness-only exception limited to that PR, so no Elo improvement is
established. See its [transition record](../../../../docs/architecture/ENDGAME_TRANSITION_COVERAGE_TH.md).

## Production and stopped experiments

- The GUI profile is NNUE v1 with the C4 native endgame enabled and 12T/512 MiB
  defaults. Runtime provenance, not a merge, is authoritative for the process
  actually serving the GUI.
- The pointer is `config/gui_release.json`, with release manifest
  `releases/nnue-v1-20260908/manifest.json`. Roll back with
  `--no-native-endgame` or `--release-profile hce`. Keep the manual resource
  controls.
- Experiment A (C4, 1000 ms): the user stopped it at 539 pairs; it remains
  INCONCLUSIVE with LLR -0.3364. Keep 12T. The 2000 ms run is deferred, and
  neither checkpoint may be resumed from old launch prose.

| Immutable artifact | SHA-256 |
|---|---|
| `RULESET.json` | `77528addc0e08b17217346c511c7c4084bad4af48789955c3ec85ef76a64871f` |
| `makhos/core.py` | `03152e513bd360e6c2c97ecdf08dc58a290dca0ae6e28889ae70585a381292ab` |
| `build/makhos_native_accepted.dll` | `feedd39cf16e5f5abc236452be897abe1ecf26b8ba7adcda4a25022b868c3ddd` |
| NNUE v1 `model_a.mknnue` | `07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c` |
| Historical 27-pair checkpoint | `09cffee749b485c1a742f921d89a173c86defbd5f15bc1a7f1f2a1b84b3de06f` |
| C4 539-pair checkpoint | `66d67efc5ec10ab60f19ff1ef24789ec212c69de8e6d2d7f8400846471cb0c9c` |

## Evidence routing

- [Practical no-loss track](../../../../docs/architecture/PRACTICAL_NO_LOSS_TRACK.md):
  the active plan.
- [Development plan](../../../../DEVELOPMENT_PLAN_TH.md): history and sequencing.
- [NNUE roadmap](../../../../NNUE_ROADMAP.md): data and model contracts.
- [Evidence ledger](experiment-evidence-ledger.md): search a mechanism here
  before retrying it.
- Previous current-state snapshots are listed at the top of this file. Do not
  execute their old next-action instructions.
- Rejected Root-PVS/SMP, large DFPN and tablebase expansion remain deferred.
