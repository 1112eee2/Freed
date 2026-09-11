# Current ThaiMakhosEngine state

Updated 2026-09-11. This file owns the current scope and next action. Historical
commands and counters are evidence, not launch instructions.

## Current scope: tech-debt Phase 1 complete (1A, 1B, 1C complete)

PR #7 merged as `738cb7cfc350ed1fd606a45ebe05b22589ad3d5b` (roadmap/complexity controls).
Phase 1A completed and merged as `e8f7e90e3ca05b80b11506be95d3e22d9af023cd` (113 files mapped).
Phase 1B (Clusters 1, 2, 3) merged as `36cc8af` (PR #9), `c80b0c6` (PR #10), `3308d4a` (PR #11).
Phase 1C (Evidence routing & documentation consolidation) complete:
- Canonical experiment & evidence index created at `docs/architecture/EXPERIMENT_EVIDENCE_INDEX_TH.md`.
- `README.md` and `DEVELOPMENT_PLAN_TH.md` updated with canonical links.
- Verified on Windows Local: documentation links valid, invariants intact.

Phase 1 complete. Next implementation slice: Phase 2A (Build consolidation).


## Latest accepted correctness change

[PR #6](https://github.com/1112eee2/ThaiMakhosEngine/pull/6) merged as
`e975d6843ee23e9fe42a3662f5d802516293796e`. Its tree matches tested head
`8a9f650ef08890a1e7134bb864b4de1a299fa900` exactly. Native C4 admission now covers
legal multi-captures from >6 into <=6, while retaining all root alternatives.

Windows Local operator reported: 513/513 Python tests, 16/16 Node tests,
real-TB4–TB6 transition assertions in 48 observations, and NNUE/HCE HTTP smoke
all PASS. Full-suite elapsed 177.122 s; reported overshoot mean 2.12 ms/max 3.70 ms.
Raw Windows files remain Local; Web has not retrieved/hashed them independently.

The user explicitly authorized merging PR #6 as a correctness fix without its
paired strength gate. This exception is limited to that PR; no Elo improvement
is established and future strength gates remain applicable. See the PR body,
merge message and [transition record](../../../../docs/architecture/ENDGAME_TRANSITION_COVERAGE_TH.md).

## Production and stopped experiments

- NNUE v1 remains the GUI profile, with C4 native endgame enabled and 12T/512 MiB
  defaults. Runtime provenance remains authoritative for the process actually
  serving the GUI; a merge does not restart a running Local server.
- Pointer: `config/gui_release.json`; release manifest:
  `releases/nnue-v1-20260908/manifest.json`. Rollback is `--no-native-endgame`
  or `--release-profile hce`. Preserve manual resource controls.
- Gate C controls and Phase 4 thread audit are completed historical evidence.
- Experiment A C4 1000ms: user stopped at 539 pairs; statistical status remains
  INCONCLUSIVE, LLR -0.3364. Keep 12T. 2000ms is deferred.
- The older 27-pair checkpoint is historical and bound to pre-fix source.
  Neither run may resume from old launch prose. Counts/identities below are
  Local-reported, not a new Web inspection of the checkpoint payloads.

| Immutable artifact | SHA-256 |
|---|---|
| `RULESET.json` | `77528addc0e08b17217346c511c7c4084bad4af48789955c3ec85ef76a64871f` |
| `makhos/core.py` | `03152e513bd360e6c2c97ecdf08dc58a290dca0ae6e28889ae70585a381292ab` |
| `build/makhos_native_accepted.dll` | `feedd39cf16e5f5abc236452be897abe1ecf26b8ba7adcda4a25022b868c3ddd` |
| NNUE v1 `model_a.mknnue` | `07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c` |
| Historical 27-pair checkpoint | `09cffee749b485c1a742f921d89a173c86defbd5f15bc1a7f1f2a1b84b3de06f` |
| C4 539-pair checkpoint | `66d67efc5ec10ab60f19ff1ef24789ec212c69de8e6d2d7f8400846471cb0c9c` |

## Evidence routing

- [Development plan](../../../../DEVELOPMENT_PLAN_TH.md): current priorities.
- [NNUE roadmap](../../../../NNUE_ROADMAP.md): data/model contracts.
- [Evidence ledger](experiment-evidence-ledger.md): search a mechanism before retrying it.
- [Previous current-state snapshot](history/20260911-current-state-before-tech-debt.md):
  exact preserved historical text; do not execute its old next-action instructions.
- Rejected Root-PVS/SMP, large DFPN and tablebase expansion remain deferred.
