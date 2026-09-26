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

No Windows strength gate is queued behind it. The 2026-09-25 owner review on
PR #28 says no W1/W2 starts while `BASELINE_HORIZON_01`'s records are absent.
STRICT_KEY_01's gates are withdrawn. TBDRAW_01's also need a scope-specific
instruction. RFP_01's needed a PASS of its Linux screening match RFP_01-L1,
which instead ended INCONCLUSIVE at its 2,000-pair cap on 2026-09-26
(+4.1 ± 7.9 Elo, LLR +0.49), so they are not triggered.

Decided on 2026-09-25 under the user's delegation ("You are the head. Just
pick one."):

1. Engine direction: RFP_01 is the single concept pursued now. It was split
   out of PR #28 as PR #32, which is merged.
2. Invincible 2 draw rules: a game that reaches a `project` draw the service
   does not declare is reported non-comparable (the §2 default). There is no
   external rules profile, and `RULESET.json` is unchanged.
3. No relay or automated play against Invincible 2, and no permission request
   for now.
4. If PR #29 merges, the frozen NNUE-v1 tools stay blocked rather than
   re-bound. Promotion gates then compare plain `unittest discover` failure
   IDs with `main`'s.
5. PR #28 merged whole on 2026-09-25, so its planned split is moot.

The F3 schema part is done: PR #30 aligned `thai-makhos-game-v1` with the
GUI's records. `sprt --games-dir` records still fail that schema, because of
the top-level `match` key, the per-move engine `role` and the missing engine
fields. They are replay-validated only and not gate evidence until the
recorder is aligned. PR #31 (F2) centralized the root choice without a
policy change. The rest of F1 (two evidence directories and the roadmap) is a
separate small extraction.

## Default-off candidates

| Candidate | What | State |
|---|---|---|
| STRICT_KEY_01 | Strict TT key: XOR instead of OR when salting the key state, so kings and the clock are not erased | **REJECT_AS_DECLARED / NOT_PROMOTED.** The depth-20 screen met its declared falsifier, a repeatable fixed-depth slowdown: 1.147× and 1.037× total time. It remains correctness evidence: the legacy key made 20.3% and 4.3% of TT cutoffs false, strict none. The Linux match was stopped at 344 pairs: +19.7 ± 17.8 Elo, LLR +0.98, INCONCLUSIVE; do not resume it. Windows gates withdrawn. ([README](../../../../benchmarks/strict_tt_key/README.md)) |
| TBDRAW_01 | Main search returns 0 at non-root nodes on an exact tablebase DRAW | INCONCLUSIVE / NOT_PROMOTED. On `main` since PR #28, default-off, with 8 tests; default build byte-identical. No paired result. ([README](../../../../benchmarks/tb_frontier/README.md)) |
| RFP_01 | Reverse futility at guarded shallow null-window nodes with 11 or more pieces | On `main` via PR #32 with margin 48, chosen by the rule declared before the census was read. Census at depth 20 on 128 positions: 0.30%, 0.70% and 0.26% of pruned nodes at depths 1–3 failed low in the real search. Speed check: 0.843× nodes, 0.929× time, +0.19 plies in 500 ms. **RFP_01-L1: INCONCLUSIVE / NOT_PROMOTED.** Contract declared at 17:29:32Z (1T, no tablebases, 2s+0.02s, H0=0/H1=+5, cap 2,000 pairs). At the cap: 1,414/1,219/1,367, pentanomial 163/393/849/424/171, LLR +0.49, +4.1 ± 7.9 Elo. No rerun with a new seed; a changed rule would be a new hypothesis. ([README](../../../../benchmarks/rfp01/README.md)) |

Tooling added by PR #28, now on `main`, each default-off: `sprt --games-dir` (replay-validated
only), `bench-native --candidate/--baseline-nnue-model`, and
`analyze-game --nnue-model`.

## Repository and PR state

- `main` is at `80f85be`. On 2026-09-25, four PRs merged on top of `a0f7964`
  (PR #17, 2026-09-12): #32 (RFP_01, default-off), #30 (game schema aligned
  with the GUI), #31 (F2 root-choice refactor, no policy change) and #28 (the
  no-loss track docs, F1 extraction, match tooling, STRICT_KEY_01 evidence
  and TBDRAW_01, default-off). The strict TT key candidate stays opt-in, and
  production 12T/C4 defaults, the model and the accepted DLL are unchanged.
  The Lazy SMP design document is a reviewed proposal, not a backend.
- PR #32 converted `tests/tooling/test_build_orchestrator.py` from CRLF to LF
  line endings by accident. It is harmless, and the repository has no
  `.gitattributes` convention, so it was left as is.
- The tech-debt roadmap (Phases 0–3, PRs #7–#16) is complete; see
  [the roadmap](../../../../docs/architecture/TECH_DEBT_ROADMAP_TH.md).
- These PRs are open and unmerged:
  - #18–#20, #22, #24 and #26: the Lazy SMP G2 evidence stack.
  - #25: the Lazy SMP candidate plus unrelated tooling, marked
    `REJECT_FOR_PERFORMANCE / NOT_PROMOTED` by #26.
  - #21: the self-drive loop.
  - #27: the strength-loop handoff.
  - #29 (draft): the Linux lease fix from another session.
    Open-file-description locks replace the whole-file `flock` that made the
    32 slots act as one. The Windows lease is unchanged.

  None of them changes production.

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
