# Current ThaiMakhosEngine state

Updated 2026-09-16. This file owns the current scope and next action. Historical
commands and counters are evidence, not launch instructions.

### G2 diagnostic review and r5 boundary (2026-09-20)

- PR #23 head `f5a2f3fee1b04c0af10f74f802095ee0ce66f807` was reviewed in an
  isolated worktree. Both frozen snapshot verifiers, all 75 evidence hashes
  and all 12 planned observations matched. Accept only its diagnostic scope:
  the frozen r3/r4 harness has an initialization defect; historical failures,
  publication safety and liveness remain unproved.
- G2 remains `NOT_PASSED`; the candidate remains `REJECT_FOR_PERFORMANCE /
  NOT_PROMOTED`. No PR merge, production change or SPRT was performed locally.
- The proposed r5 acceptance contract is under review at
  `handoffs/lazy-smp-g2-r5-design/PLAN_TH.md`. It separates initialization,
  safety and liveness/coverage. It is not authorization to implement or run r5.

### User target clarification (2026-09-20)

Invincible 2 is the external engine by อาจารย์ทศพล ธนะทิพานนท์, not our release name.
The target is ThaiMakhosEngine: improve practical strength, then non-loss against
Invincible 2, then superior conversion/holding on matched complex positions.
For phase definitions and empirical versus universal 100% evidence, read
[the corrected comparison roadmap](../../../../docs/architecture/INVINCIBLE_2_ROADMAP_TH.md).
This does not start a proof builder, resume checkpoints, or close pending gates.

## Current scope: readiness evidence before Lazy SMP gates

- Inspected Local HEAD `ef42064` on `local/strict-key-acceptance-a0f7964`.
  PR #17 (`a0f7964`) contains the isolated strict-key candidate/design review;
  `ef42064` adds the P0 race harness and closes the move-only design requirements.
  A design acceptance or merged candidate interface is not a production promotion.
- The worktree contains pre-existing native/Lazy SMP implementation, build,
  benchmark and game-review changes. Keep them separate from this P0 tooling/docs
  patch; do not stage all, reset, clean, or relocate the nested checkout.
- Use [the canonical Lazy SMP design](../../../../docs/architecture/NATIVE_SHARED_TT_LAZY_SMP_DESIGN_TH.md)
  for G0–G6: **move hints only**, private scores/history/NNUE accumulators,
  main-thread result authority. Shared-score cutoff stays `BLOCKED_SCORE_SHARING`.
  The older `SMP_DESIGN_LAZY_SMP_NATIVE_TH.md` proposal is superseded, not a launch plan.
- Keep C4 routing, terminal/TB proof precedence, root policy, GUI defaults and
  accepted rollback unchanged. No SPRT or production change is part of P0.

### Evidence and next action

- Active user goal (2026-09-15): complete the Lazy SMP acceptance sequence with
  evidence-based KEEP/REJECT/PROMOTE, preserving production and stopped runs.
  New same-source strict/control DLLs were reproducibly built twice in
  `build/lazy_smp_acceptance_20260915_g0/{control,candidate}/`; source/model/compiler
  identities are frozen in `contract.json`, with build results in `build_result.json`.
  Existing six parity/memory/cancellation tests PASS against these fresh DLLs
  (`fresh_candidate_tests.json`), not just the older candidate.
- **Allocation defect reproduced and fixed in r2:** expanded probing found the native handle
  exceeds requested Hash at 16 MiB with multiple workers and at 64 MiB/2T.
  `memory_budget_probe.json` records the actual bytes. The hint table is fixed at
  48 MiB, while private allocation assumes a budget derived from hash power.
  The failing 24-configuration regression is retained in
  `build/lazy_smp_acceptance_20260915_g0/memory_budget_regression_red.txt`.
  Revision `build/lazy_smp_acceptance_20260915_r2/` adds an additive budgeted-create
  API, caps total TT allocation, keeps 512 MiB layouts and 1T parity, and retains
  identical memory allocation when hints are disabled. Both DLLs build reproducibly;
  all seven focused tests PASS (`candidate_tests.json`). Old DLLs remain untouched.
  Legacy oversized allocations fail closed in the Python wrapper.
  Full-suite validation for r2 PASS: 598/598 Python + 16/16 Node, zero skips,
  failures/errors/protected reads, 209.233 s Python time (`full/result.json`).
  Use `MAKHOS_TEST_LAZY_SMP_DLL` and `MAKHOS_TEST_STRICT_CONTROL_DLL` with the r2
  candidate/control paths when testing; default paths still name historical DLLs.
  The old pilot is not acceptance evidence. Future ON/OFF measurements must use
  separate processes with the environment set before DLL load (CRT environment
  caching may make in-process environment toggles unreliable).
- G2 actual-code harness now passes Windows stress and ASan: eight writers/four
  readers, partial/paused publication, key/epoch mismatch, wrap guard, allocation/
  event/thread failures and repeated teardown. See
  `build/lazy_smp_acceptance_20260915_g2/protocol_result.json`; full run passed
  600 Python + 16 Node. ASan is NOT a race detector: the race-detector gate is
  still NOT_RUN (no installed WSL distribution found). Do not call G2 complete.
- **G3 root-terminal defect fixed in r3:** an already threefold root returned a
  move/NNUE score in all 1/2/4/6/8/12T configurations. Failing regression retained
  at `build/lazy_smp_acceptance_20260916_g3/terminal_root_red.txt`. The common
  native search now rejects that root before NNUE refresh. Production DLLs were
  not replaced. Fresh same-source strict control/candidate, each reproducibly
  built twice, are frozen under `build/lazy_smp_acceptance_20260916_r3/`.
  Bind test DLL environment variables to that directory, replacing r2 paths.
  Eleven focused tests PASS, including 72 H1/H2/H1 history/depth/thread cases
  with forced-child repetition draws and Python legal-PV checks.
  Full r3 run: **602/602 Python + 16/16 Node PASS**, 263.644 s Python time,
  zero failures/errors/skips/protected reads (`full/result.json`).
  This does not establish general history isolation or close all G3 cases.
- G3 expanded regressions (same r3 DLLs) PASS: independent Python terminal-child
  oracle for forced capture/multi-capture wins and clock-79 draws at depths
  1/2/4/6 across 1/2/4/6/8/12T; hashed history with >32 distinct keys; legally
  replayed king cycle; repetition-disabled restart; concurrent stop/close now
  captures thread exceptions rather than silently losing them.
  `build/lazy_smp_acceptance_20260916_g3_expanded/result.json` binds the changes.
  Full suite **604/604 Python + 16/16 Node PASS**, 353.491 s Python time,
  zero errors/failures/skips/protected reads. Candidate remains r3 and unpromoted.
- G3 allocation-budget coverage extended (same r3 DLLs, no engine change).
  The existing Hash-budget grid was all powers of two, so it could not falsify an
  overrun that only appears for non-aligned requests where the shared hint table
  floor steps (3/6/12/25/50 MiB shared) while the private entry count stays
  pinned. Two tests added: non-power-of-two Hash across 1/2/4/6/8/12T, and
  fail-closed for a budget below the shared+per-worker floor (1 MiB at 6/8/12T).
  The non-aligned test FAILs (15 errors) against the pre-fix g0 candidate and
  PASSes against r3, so it has measured falsifying power. Full suite
  **606/606 Python + 16/16 Node PASS**, 232.959 s, zero
  failures/errors/skips/protected reads
  (`build/lazy_smp_acceptance_20260916_g3_budget/full/result.json`); retained red
  `non_power_of_two_red_on_prefix.txt`, record `result.json` in the same dir.
  This is a KEEP-only coverage gain, not a strength or promotion result.
- G3 terminal-proof and lifecycle coverage extended (same r3 DLLs, no engine
  change). Three tests added. (F1) All three terminal reasons are now verified
  rejected at the Lazy SMP root across 1/2/4/6/8/12T against the Python
  `terminal_status`/`legal_moves` oracle: `repetition`, `no_progress`
  (reversible_plies=80) and `no_legal_move`
  (`state_from_pieces({(1,0):BLACK_MAN,(0,1):RED_MAN},BLACK)`); a clock-79 root
  still searches. The pre-fix g0 candidate also rejects all three, so this is
  **coverage, not a defect repair** — do not report it as a fix. (F2) An
  externally stopped search clears the native running flag; `clear()` and a
  fresh search keep working afterwards at 1/2/4/12T. (F3) contract
  clarification: native `makhos_lazy_smp_clear` returns 1 (refused) while a run
  is active, but that refusal is **unreachable through
  `NativeLazySmpSearch.clear()`**, because the wrapper holds `_search_lock` for
  the whole native run. Measured: `clear()` blocked 2902 ms for a 2900 ms
  search. The native refusal is defence-in-depth only; the observable contract
  is that `clear()` serializes behind an active search. A first draft asserting
  `clear()` raises during an active search was wrong about the contract and was
  replaced, not loosened. Full suite **609/609 Python + 16/16 Node PASS**,
  218.202 s, zero failures/errors/skips/protected reads
  (`build/lazy_smp_acceptance_20260916_g3_lifecycle/full/result.json`); record
  `result.json` in the same dir. KEEP-only coverage gain.
- Next: finish actual race-detector coverage (still blocked on a Linux/TSan
  runtime) and the remaining G3 cases, then G4 scaling, fresh G5 paired
  strength and G6 production/rollback. Status remains NOT_PROMOTED; no SPRT
  launch or checkpoint mutation has occurred in these correctness gates.
- G2 Linux handoff: user assigned race-detector execution to Astra Web; Local
  has prepared (not sent) `build/lazy_smp_race_portable_20260916/astra_g2_handoff.zip`
  and `ASTRA_WEB_PROMPT_TH.md` in that directory. The bundle includes verbatim
  production function/type extraction, source hashes and a portable C11 harness.
  Windows normal compile/stress PASS (1,200,000 operations), but TSan is still
  NOT_RUN. Astra must verify a known-racy negative control and return raw evidence
  for five sanitized runs. Do not infer completion from handoff preparation.
  New exporter/template have a Windows smoke, not a rerun full-suite attestation.

- Historical developer run `build/development_checks/20260913T113626229890Z/result.json`
  reports 594 Python + 16 Node PASS, no skips. On inspection its 203-file digest
  matched the listed current sources, but omitted relocated tools/CI/Node tests
  and root runtime entrypoints. Preserve that report; do not relabel its scope.
- **P0 tooling verification complete (KEEP; not a strength promotion).** The
  maintained-code inventory now includes tools/CI/Node tests/config/root launchers,
  with mutation/addition/removal regressions. Test outputs are rejected before
  directory creation inside stopped experiments or the acquisition run.
- The first full run failed six build-verification assertions because a child
  Windows PowerShell inherited another edition's Utility module search path.
  The orchestrator now imports Utility from its own `$PSHOME`; a regression
  disables module autoload. Existing SMP/build changes were otherwise preserved.
  Keep the failed report at `build/readiness_p0_20260914/full/result.json`.
- Final Local run (2026-09-14): **597/597 Python + 16/16 Node PASS**, zero
  failures/errors/skips/protected reads, Python suite 205.661 s. Evidence:
  `build/readiness_p0_20260914/full_after_autoload_fix/result.json`.
  Its maintained-source digest covers 234 files; recheck it after source edits.
- P0-only checkout (`ef42064` plus tooling/docs, no DLLs or SMP WIP):
  **134/134 reference + 16/16 Node PASS** on Windows/Python 3.14. Evidence:
  `build/readiness_p0_20260914/source_only/build/ci-final-v2/result.json`.
  GitHub Actions identities/inputs were checked and pinned; hosted Windows/Linux
  and Python 3.11 CI runs have not been executed in this task.
- **G0 provenance gap:** the existing Lazy SMP DLL's build manifest binds a
  different `native/makhos_native.c` hash from the current worktree. Other listed
  native source hashes matched on inspection. The DLL/model/source identities
  and pre-existing changes are frozen in `build/readiness_p0_20260914/before.json`.
  Ten pre-existing SMP files are also preserved byte-for-byte under
  `build/readiness_p0_20260914/preserved_smp_wip/` with a hash manifest.
  Passing tests against that DLL do not validate a build of the current C source.
- Next: complete G2/G3 against actual native code (including direct publication
  testing, allocation failure paths, repeated lifecycle/history/clock cases).
  Preserve the old
  candidate/evidence; do not overwrite its manifest to make hashes appear current.
  Only then proceed to G4 scaling, fresh G5 paired strength, and G6 smoke/rollback.
  The six-position hints pilot is diagnostic, not an Elo or promotion gate.

## Completed structural baseline: Tech-Debt Phases 0 through 3

- PR #7 merged as `738cb7cfc350ed1fd606a45ebe05b22589ad3d5b` (Phase 0: roadmap/complexity controls).
- Phase 1 (1A, 1B, 1C) completed and merged via PR #8, #9, #10, #11, #12 (tooling, evidence routing, canonical index).
- Phase 2A (Build consolidation) merged via PR #13 (`b9bebb8`).
- Phase 2B (Engine manager & server separation) merged via PR #14 (`9caa1ba`): authoritative Engine state in `makhos/engine_manager.py`, `makhos/server.py` as HTTP adapter with 100% facade compatibility.
- Phase 2C (CLI modularization) merged via PR #15 (`5e6bd3b`): CLI command handlers decomposed into `makhos/cli_handlers/` with thin router in `makhos/cli.py`.
- Phase 3 (Native leaf modularization & NNUE surface):
  - Dependency & ABI map documented at `docs/architecture/NATIVE_ABI_AND_DEPENDENCY_MAP_TH.md`.
  - Extracted leaf types and ABI memory layout assertions to `native/makhos_types.h`.
  - Extracted board coordinate conversions, move notation, and FEN parsing to `native/makhos_format.h`.
  - Streamlined `native/makhos_native.c`, eliminating duplicated definitions while keeping bit-exact ABI and inlining.
  - Hardened build orchestrator and `makhos_tb5.c` checkpoint call.
  - Verified: all 10 native variants compile cleanly; native perft depth 1..10 bit-exact match (depth 10 = 861,842,812 nodes); Python/native differential verification (204 positions, 1,149 moves PASS); full unittest suite 581/581 tests PASS; tooling suite 58/58 tests PASS; immutable invariant SHA-256 hashes 100% preserved.

All roadmap phases in `docs/architecture/TECH_DEBT_ROADMAP_TH.md` are completed.


## Accepted endgame correctness baseline (PR #6)

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
- Rejected Root-PVS/SMP mechanisms remain historical; the new move-only Lazy SMP
  candidate follows G0–G6 above. Large DFPN and tablebase expansion remain deferred.
