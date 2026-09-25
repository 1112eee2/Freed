# Current ThaiMakhosEngine state

Updated 2026-09-25. This file owns the current scope and the next action.
Historical commands and counters are evidence, not launch instructions.

## Current scope: practical no-loss track against Invincible 2

On 2026-09-25 the user approved the
[practical no-loss track](../../../../docs/architecture/PRACTICAL_NO_LOSS_TRACK.md)
as the active strength scope. The goal is zero losses against Invincible 2 in
a large, frozen, colour-balanced match, reported with a 95% upper bound on the
loss rate and never as "proven perfect". The track excludes proof/DFPN work,
tablebases of 7 or more pieces, and any Lazy SMP redesign.

The track is in **Phase 0**. No production default, rules file, model or
accepted artifact has changed under it. Default-off candidates are listed
below.

On 2026-09-25 the user confirmed the §8 plan changes and the F1 decision,
replying "Confirmed. Now you may open a PR and make the engine stronger." to
this stated form of F1: extract only what the track needs from PR #25, and
keep the Lazy SMP PRs open until the extracted pieces are on `main`.

The plan listed three first actions:

| First action | State |
|---|---|
| 1. Update current-state with this scope | DONE (this file) |
| 2. Run the staged `6ef62f9998d12db4` review | BLOCKED on Local. It needs Windows, an idle GUI, the game DLL `32c32302…`, NNUE v1 `07b9ab0f…` and the gitignored saved game. The frozen matrix is `BASELINE_HORIZON_01` in [PR #27](https://github.com/1112eee2/ThaiMakhosEngine/pull/27). |
| 3. Check Invincible 2 access and rules parity | INCONCLUSIVE. The live page and its script were inspected on 2026-09-25 (§3.5 and §3.6 of the track). Moves and captures match `project`; draw adjudication does not. Server-side rules, determinism and permission for automated play are unknown. |

Findings from the 2026-09-25 Web review, all checked against source:

- The root safety policy the plan targets (`search.py:_choose`/`_safety_rank`)
  runs only on the native-endgame route (at most 6 pieces, or a capture into 6
  or fewer) and on the Python paths. The production 12T middlegame uses
  `ParallelNativeSearch._choose` instead: the highest score wins, with no WDL
  bound or mode. Phase 2 therefore first needs a single, behavior-preserving
  root policy (track F2).
- `analyze-game --nnue-model`, `INVINCIBLE_2_ROADMAP_TH.md` and the game-review
  evidence exist only on the PR #25 branch, not on `main`. PR #28 extracts
  `analyze-game --nnue-model` and the `2139e329d3c5def3/` evidence; the rest
  remains on PR #25.
- The GUI writes game records that its own `schemas/thai-makhos-game-v1.schema.json`
  rejects. Nothing validates against that schema (track F3).
- Invincible 2 reportedly has a database of 10 or fewer pieces and a
  300M-position book, and claims to have solved the game. If true, 7–10
  pieces is our risk band. The page itself confirms none of this.
- The Invincible 2 page script declares threefold repetition a draw only when
  10 or fewer pieces remain, has no no-progress limit, and declares one king
  each a draw. Our TB4–TB6 draws assume the 80-ply limit, so they
  are not guaranteed draws against that service (track §3.5).

## Next action

The single active action is on **Local**: when the GUI is idle, run
`BASELINE_HORIZON_01` exactly as frozen in PR #27, and return the 8 slot
records, raw logs and manifest through a PR. Do not upload the DLL, model or
tablebases. Do not stop the Arena or a user game to run it.

After it, Local's queue is the strength gates in PR #28, in this order. Each
has pre-declared commands and a decision rule in its README:

1. STRICT_KEY_01 W1 and W2 ([README](../../../../benchmarks/strict_tt_key/README.md)).
2. TBDRAW_01 W1 and W2 ([README](../../../../benchmarks/tb_frontier/README.md)).
   If STRICT_KEY_01 was promoted, both TBDRAW_01 builds add `-StrictSearchKey`.

The following are open until the user decides:

1. How to treat the draw-rule difference against Invincible 2: report those
   games as non-comparable under `project` (the §2 default), or approve a
   separate external rules profile for that match. `RULESET.json` stays
   unchanged either way.
2. Whether to ask the developer for permission for automated play. The page
   lists no terms. Until permission exists, no relay or automated play is
   built.

The next Web steps are the F3 schema alignment with a record-validation test,
then the F2 root-policy parity refactor. Both are behavior-preserving. The
rest of F1 (two evidence directories and the roadmap) is a separate small
extraction.

## Default-off candidates (PR #28)

| Candidate | What | State |
|---|---|---|
| STRICT_KEY_01 | Strict TT key: XOR instead of OR when salting the key state, so kings and the clock are not erased | Screen done at depth 20: legacy keys made 20.3% of TT cutoffs false in 7–12 piece king positions and 4.3% in king-free 13+ piece positions; strict made none, at 1.10× and 1.03× nodes (geometric mean). Linux diagnostic SPRT L1 running; Windows W1/W2 pending. |
| TBDRAW_01 | Main search returns 0 at non-root nodes on an exact tablebase DRAW | Implemented with 8 tests; default build byte-identical. Windows W1/W2 pending. |

Tooling added in PR #28, each default-off: `sprt --games-dir` (replay-validated
game records), `bench-native --candidate/--baseline-nnue-model`, and
`analyze-game --nnue-model`.

## Repository and PR state

- `main` is at `a0f7964`: PR #17 merged on 2026-09-12. The strict TT key
  candidate stays opt-in, and production 12T/C4 defaults, the model and the
  accepted DLL are unchanged. Windows and paired-strength acceptance for
  strict-key were pending at merge time; their later status has not been
  re-checked from Web. The Lazy SMP design document is a reviewed proposal,
  not a backend.
- The tech-debt roadmap (Phases 0–3, PRs #7–#16) is complete; see
  [the roadmap](../../../../docs/architecture/TECH_DEBT_ROADMAP_TH.md).
- These PRs are open and unmerged:
  - #18–#20, #22, #24 and #26: the Lazy SMP G2 evidence stack.
  - #25: the Lazy SMP candidate plus unrelated tooling, marked
    `REJECT_FOR_PERFORMANCE / NOT_PROMOTED` by #26.
  - #21: the self-drive loop.
  - #27: the strength-loop handoff.
  - #28: the no-loss track docs, the F1 extraction, match tooling, and the
    STRICT_KEY_01 and TBDRAW_01 candidates.

  None of them changes production.
- On Linux, `BatchWorkLease` uses a whole-file `flock`, so its 32 slots act as
  one. This is tracked separately; the Windows lease is unaffected.

## Latest accepted correctness change

[PR #6](https://github.com/1112eee2/ThaiMakhosEngine/pull/6) merged as
`e975d6843ee23e9fe42a3662f5d802516293796e`. Native C4 admission now covers
legal multi-captures from more than 6 pieces into 6 or fewer, while keeping
all root alternatives. It was merged under a correctness-only exception
limited to that PR, so no Elo improvement is established. See its
[transition record](../../../../docs/architecture/ENDGAME_TRANSITION_COVERAGE_TH.md).

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
- [Development plan](../../../../DEVELOPMENT_PLAN_TH.md): history and
  sequencing.
- [NNUE roadmap](../../../../NNUE_ROADMAP.md): data and model contracts.
- [Evidence ledger](experiment-evidence-ledger.md): search a mechanism here
  before retrying it.
- [Previous current-state snapshot](history/20260925-current-state-before-no-loss-track.md):
  exact preserved text. Do not execute its old next-action instructions.
- Rejected Root-PVS/SMP, large DFPN and tablebase expansion remain deferred.
