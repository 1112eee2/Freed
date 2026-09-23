# Current ThaiMakhosEngine state

Updated 2026-09-23. This file owns the current scope and next action. Historical
commands and counters are evidence, not launch instructions.

### Lazy SMP G2 r5 handoff status (2026-09-23 local recheck)

- The isolated branch `codex/lazy-smp-g2-r5-implementation` is at
  `0ced9eb2759ccd0dbe2541b07b0609301c80e317`; its worktree is clean and tracks
  the same remote commit. The frozen bundle's `verify_snapshot.py` passes.
- Frozen Windows readiness result is `INCOMPLETE_COVERAGE`: directed preflight
  and protocol processes 1–4 passed; process 5 had reader 2 accept zero of
  100,000 attempts. Its SPSC subtest still completed all 256 distinct
  publications. Preserve all six fixed slots; do not retry or replace process 5.
- The result records `tsan_calibration_status: NOT_RUN`; Windows readiness does
  not close G2. G2 remains `NOT_PASSED`, and the candidate remains
  `REJECT_FOR_PERFORMANCE / NOT_PROMOTED`. Production, frozen r3/r4 evidence,
  accepted DLL, and SPRT/checkpoint state were not changed. The detailed frozen
  artifacts are in
  `build/lazy_smp_r5_impl_worktree/handoffs/lazy-smp-g2-r5/`.
- Next for this gate: review the manifest-bound Linux TSan matrix results when
  Astra returns them; do not merge/promote or open SPRT from Windows readiness.
  This pending gate does not block separate safe-baseline strength work.

### Strength-track saved-game audit (2026-09-23)

- Replayed all three current `saved_games/` records through
  `makhos.game_analysis.load_game_record()` / `replay_game()` under project
  rules: 197 legal plies, 200 stored position snapshots, and zero mismatches in
  move history, final position, or reversible-ply clock. Hash-bound record:
  `benchmarks/game_reviews/saved_games_corpus_audit_20260923/`.
- Two records are user adjudications whose rule state is still ongoing. In
  `6ef62f9998d12db4`, Red (engine) was adjudicated lost by Black but the game is
  not a rules loss; its last recorded pre-move search was `LOSS..DRAW`, not an
  outcome proof. Treat it as the highest-priority development review, not a
  solved label. `f65be3eb5558f9af` is a similarly ongoing adjudicated draw and
  can serve as a separate hold/control review. The third record is a natural
  Black engine win and already has its own detailed review.
- Rechecked the game-bound candidate DLL/model hashes against disk; the
  accepted DLL identity remains distinct and unchanged. Arena was present
  (PID 9388) during the audit, so no engine search, profiling, full suite, or
  strength run was started. Recheck GUI/workload state before any such run.
- Fixed an analysis-tool gap found while preparing that review: `analyze-game`
  now accepts `--nnue-model`, passes it to both 1T and root-split searchers, and
  records/compares NNUE enablement, feature ABI, and model SHA. Search identity
  is captured before worker teardown. Focused CLI/game-analysis tests pass
  **15/15**; no native search was run.
- Next strength-track action, when GUI priority permits: fresh-state diagnostic
  review of `6ef62f9998d12db4` at engine plies 8, 10, and 12 using its complete
  history/clock, recorded DLL/model, 12T/512 MiB, and 5 s plus 10 s search
  budgets. The exact command is staged in the audit README. Inspect the earliest
  reproducible value loss before labeling a move. Keep it development-only,
  separate from G2 and any independent acceptance/SPRT corpus.

### Current addendum (2026-09-20)

- The older G2 paragraph below saying that the r4-pthread harness is not
  implemented is superseded by the collected evidence under
  `handoffs/lazy-smp-g2-r4/`: pthread smoke/negative controls run, but the G2
  gate remains `NOT_PASSED`.
- The reviewed r4 evidence and its liveness addendum report two separate abort
  classes: timing-dependent `accepted == 0` and the payload assertion
  `move.captured_low == ~move.path_low`. Neither establishes a production
  publication defect. Keep the frozen probes and raw results unchanged.
- Astra Web is investigating the seed-state hypothesis on GitHub. Local must
  not close G2, change production atomics, promote the candidate, or start an
  SPRT until a new revision supplies complete evidence.
- The local coordination record is
  `handoffs/local-coordination-20260920/STATUS_AND_HANDOFF_TH.md`.

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

- Inspected Local HEAD `34217f3` on `local/strict-key-acceptance-a0f7964`.
  PR #17 (`a0f7964`) contains the isolated strict-key candidate/design review;
  `ef42064` adds the P0 race harness and closes the move-only design requirements;
  `ff771d4` adds non-power-of-two/below-floor Hash budget coverage and `34217f3`
  adds terminal-root reason and stop/clear lifecycle coverage. A design acceptance
  or merged candidate interface is not a production promotion.
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
  change). Three tests added. (F1) The two terminal reasons that had no root
  coverage are now verified rejected at the Lazy SMP root across 1/2/4/6/8/12T
  against the Python `terminal_status`/`legal_moves` oracle: `no_progress`
  (reversible_plies=80) and `no_legal_move`
  (`state_from_pieces({(1,0):BLACK_MAN,(0,1):RED_MAN},BLACK)`); a clock-79 root
  still searches. `repetition` is covered by the separate, older
  `test_terminal_root_repetition_rejected_before_search`, so the F1 test was
  renamed to `test_terminal_root_rejected_for_no_legal_move_and_no_progress` to
  match what it actually asserts. For `no_legal_move`/`no_progress` the pre-fix
  g0 candidate also rejects, so those two are **coverage, not a defect repair**.
  `repetition` is the opposite: the pre-fix g0 candidate FAILED it on all six
  thread counts (`build/lazy_smp_acceptance_20260916_g3/terminal_root_red.txt`,
  "RuntimeError not raised" ×6), so the r3 root-repetition rejection **is a real
  defect repair**. The two evidence sets are consistent, not contradictory — they
  cover different terminal reasons. The `g3_lifecycle/result.json` F1
  `negative_control` wording ("also rejects all three") is imprecise on that
  point; that frozen record is deliberately left unedited and the correction is
  carried here. (F2) An
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
- Gate matrix for G0–G6 now lives in `DEVELOPMENT_PLAN_TH.md` ("Gate matrix
  Native Lazy SMP"), with per-gate evidence, verdict and remaining action. It
  recorded one blocking discovery: `NativeLazySmpSearch` was **not wired into the
  engine path** — `makhos/engine_manager.py::_create_native_search` returned only
  `NativeSearch`/`ParallelNativeSearch`. That blocker is now resolved.
- **Round r4 (`build/lazy_smp_acceptance_20260916_r4/contract.json`) — engine
  opt-in wiring + G3 closure + G4 measurement. No native source changed, so the
  r3 DLLs are reused unchanged (verified: 17/17 native files still match the r3
  contract; `native_source_drift: []`).** Changed Python only:
  `makhos/engine_manager.py`, `makhos/server.py`, `makhos/cli.py`,
  `makhos/cli_handlers/{sprt_handler,play_handler}.py`,
  `tests/test_native_lazy_smp.py`, `tests/test_engine_manager.py`, and the new
  `tools/benchmarks/run_lazy_smp_scaling_matrix.py`.
  - **Opt-in wiring:** `_create_native_search(..., lazy_smp=False)` selects
    `NativeLazySmpSearch` only when asked; the default path still returns
    `NativeSearch` (1T) / `ParallelNativeSearch` (>1T). `GLOBAL_ENGINE_CONFIG`
    grew an 8th field (the flag) and a backend change now forces a rebuild.
    `configure_gui_native_search(..., lazy_smp=None)` plus `GUI_LAZY_SMP_OVERRIDE`
    drive the GUI, `--lazy-smp` drives `gui`/`sprt` (candidate only; the SPRT
    baseline stays root-split and `--lazy-smp` is mutually exclusive with
    `--selective-root/--shared-tt/--root-alpha`). Provenance reports
    `configured_search_backend: native-lazy-smp` and `native_search_threads`, so
    the backend is never inferred from a file name. The Engine still owns root
    selection; no new root policy was introduced.
  - **G3 is CLOSED.** Six tests added (repeated games with determinism after
    `clear()`, 50x create/close leak check on OS threads + RSS, cross-history
    score isolation, legal PV at 2/4/6/8/12T, timed-deadline overshoot, restart
    after allocation failure) plus two wiring tests. Measured before asserting:
    overshoot +2.0 ms/+0.9 ms at 12T, RSS +0.1 MiB over 50 cycles, threads
    returning to baseline. No new defect was found; r2 (allocation) and r3
    (repetition) remain the only two real defect repairs.
  - **G4 is MEASURED. The result is negative but narrower than earlier reported,
    and two of this round's own claims are withdrawn.** The authoritative
    correction record is `build/lazy_smp_g4_corrections_20260916/corrections.json`
    (C1–C8); `g4_003/gate.json` is kept with a `superseded_by` pointer and none of
    the raw evidence was deleted.
  - **Negative control (C1) — the hints claim is WITHDRAWN.** At 1T the code takes
    the bypass branch at `native/makhos_native.c:6033-6047`: `shared_hint_table` is
    NULL and `MAKHOS_LAZY_SMP_DISABLE_HINTS` is never read (that `getenv` is at line
    6052, multi-thread only). Measured: at 1T, hints ON vs OFF are **bit-identical**
    in move/score/nodes/depth/PV at fixed depth 6 and 8, with identical allocation
    (private 335,544,320; shared 0; entries 0). So the earlier "hints are
    net-negative at every thread count, including 1T (−2.4…−9.5%)" was inside the
    protocol's own noise. In the frozen paired run
    (`build/lazy_smp_scaling_20260916_g4_008_hints_control/`, 352 cells, 0 errors,
    freeze pre-declared) the 1T noise floor is median +0.85%, IQR [−2.56, +3.70],
    range [−13.84, +15.57]; at 12T the authoritative worker's ON−OFF difference is
    median **+1.20%** with IQR [−22.01, +39.75], i.e. **no established effect**.
    At 12T fixed depth, hints ON and OFF give **identical score and identical PV in
    12/12 cases** while hints ON uses equal-or-fewer authoritative nodes — hints
    improve move-ordering efficiency without changing the answer. The only
    consistent measured effect is on the *helpers'* aggregate nodes (median −6.26%,
    IQR [−9.53, −2.88]), which is not the returned result.
  - **What survives from G4, and it is robust:** stop latency 0.176–0.270 ms at
    1/2/4/6/8/12T; deadline overshoot median 0.5–0.8 ms with a ~0.5–1% tail over
    10 ms under load; pv_legal 792/792; both backends inside the requested Hash;
    aggregate scaling 5.96x vs the root-split control's ~1.35x; and the
    authoritative worker's own node count falling roughly as 1/T (1T median
    2,894,848 → 12T median 1,067,286, far beyond the ±14% node noise) while only
    worker 0's result is returned by design (`makhos_native.c:6367`).
    **Paired 12T comparison vs the production root-split backend**
    (`..._g4_007_interleaved/`, 5 repeats, 55 pairs): median **−1 ply**, candidate
    shallower in **37**, equal in 11, deeper in 7. **No thread count has the
    candidate's median depth above the production backend's** (1T 23/23, 2T 23/23,
    4T 22/22, 6T 22/22, 8T 21.5/22, 12T 21/22).
  - **Calibrated against a measured noise floor** (`..._g4_010_depth_noise_control/`,
    frozen first: the *same* r3 control DLL in **both** roles, 110 cells, 0 errors).
    Pure noise by construction gives median 0.00, range [−1, +1] and **47 of 55
    pairs tied** with an asymmetry of 5 versus 3. The real comparison has only 11
    ties and an asymmetry of 37 versus 7 with a tail to −4 plies, and its
    authoritative-worker node difference is negative in **55 of 55** pairs (median
    −2.9M nodes). The two distributions differ qualitatively, so the −1 ply deficit
    **is** distinguishable from this protocol's noise floor. Without this control the
    verdict would have had to be INCONCLUSIVE; with it, the negative finding stands
    for this candidate/configuration/corpus/runtime.
  - **Scope is narrowed (C2).** The structural argument holds for this candidate,
    configuration, corpus and runtime. It is **not** a general proof that
    move-hints-only Lazy SMP cannot work, and it is **not** evidence that helper
    work is useless (fixed-depth evidence shows hints do change worker 0's node
    count). **No Elo conclusion exists anywhere.**
  - **Corrections C4–C7:** worker 0's share is essentially its fair share
    (0.93–1.005 x 1/T), so the earlier "7.2% vs fair 8.3%" framing was wrong; that
    metric is **node share, not CPU time share**, and per-thread CPU was never
    measured; correlations (worker-0 nodes vs depth +0.596, aggregate vs depth
    +0.167) are reported as association only, not causation; the Hash-sensitivity
    bracket is supplementary evidence for one comparison, not a general proof.
  - **C5/C6 — status is NOT REPRODUCED, CAUSE UNKNOWN.** The 328.92 ms overshoot
    did not recur in 5 repeats of the exact configuration (max 1.255 ms, 0/30 over
    10 ms), and the depth-4 / worker-0-~50-nodes event did not recur under
    interleaved ordering. Neither is attributed to the environment, to the
    candidate, or to any mechanism, and neither is reported as a product defect.
    No outlier was removed from any dataset. The harness now alternates
    repeat-major → hints → role under `--interleave-roles`.
  - **Engine integration audited behaviourally, not by test count**
    (`build/lazy_smp_r4_integration_audit_20260916/audit.json`, A1–A6): default-off
    returns the production backend; exact endgames still route to the
    tablebase-aware Python path and never to the lazy backend; a terminal root is
    refused before any backend (`ValueError: cannot search a terminal position`);
    the engine's cancellation path is `clear()` and it never calls
    `native_search.stop()` (grep-verified, and `ParallelNativeSearch` has no
    `stop()`); an opt-in DLL without Lazy SMP degrades gracefully with
    `last_native_error` set. **Not covered:** C4 exact-outcome agreement under the
    lazy backend, and GUI HTTP smoke / perft (G6 scope).
  - Full suite: **618/618 Python + 16/16 Node PASS**, zero
    failures/errors/skips/protected reads
    (`build/deepseek_handoff_full_003/result.json`).
- **Candidate verdict recorded: `REJECT_FOR_PERFORMANCE`** —
  `build/lazy_smp_candidate_verdict_20260916/verdict.json`. Gate-by-gate status,
  identities, the frozen corpus/protocol hashes, the corrections summary,
  limitations, and what a future attempt should know. G5/G6 are recorded **NOT_RUN
  with the reason**, not PASS. `INCONCLUSIVE` would also be defensible if the user
  prefers to reserve judgement until a strength gate exists.
- **Round 1 diagnostic complete** (`build/round1_profile_20260916/round1.json`). Scope
  declared first: profile production only, no candidate, no behaviour change, and an
  avenue counts as having headroom **only if the precondition the plan states for it is
  measured and met**.
  - **Source-state finding:** the worktree native source is **not** the source that built
    production (`.text` 155648 vs 158720; `.pdata/.rdata/.reloc` differ) but is
    **behaviourally identical** to it on the default path — 1T fixed-depth parity 33/33
    over 11 positions × depths 6/8/10 (move/score/nodes/depth/PV all equal). The extra
    code is inert unless the opt-in is enabled. The worktree also carries a large
    uncommitted native delta (539+/163−) that is **not** reverted here; a defined
    baseline is a prerequisite for candidate work.
  - **Instrumentation:** `makhos_search_nnue_telemetry` exists on every NNUE DLL;
    **`makhos_search_telemetry` is compiled out of every shipped DLL**. A diagnostic
    build with `-DMAKHOS_SEARCH_TELEMETRY=1` was made
    (`build/round1_profile_20260916/telemetry/`, sha `56753BFD…`), proven
    behaviour-identical to production (33/33), and used only for profiling. Ablation
    defines exist, so time attribution needs no source edit.
  - **Measured (1T, production behaviour):** qsearch is **64.7%** (depth 10) / **51.4%**
    (1 s) of all nodes; ordering efficiency is already **86.9% / 89.1%** first-move
    cutoffs (avg index 0.24–0.27); TT hit rate 48.4% / 66.5%; null cutoff rate
    44.8% / 61.1%; LMR 0.0025–0.0031 and PVS 0.023–0.031 researches per node;
    **NNUE full refreshes are 0.0002–0.022% of evaluations**; overshoot 0.049% (1T) /
    0.151% (12T) of budget; NPS 1.53M at 1T and 2.40M at 12T (**1.57x** for 12 threads).
  - **Avenue ranking:** (1) wasted search work / qsearch — **candidate, largest measured
    block**; (2) NNUE `ancestor delta` — **precondition NOT met, removed**; (3) ordering
    — **precondition NOT met for the ordering sub-item** (history/horizon unmeasured);
    (4) time management — **NOT met, deprioritized**; (5) next NNUE generation —
    separate workstream needing data and a sealed split.
  - **Two measurement errors of my own corrected:** the 12T NNUE counters are
    **withdrawn** (the telemetry resets per search call, and root-split runs one search
    per root move, so only the last subtree is captured); and the qsearch share is
    **51–64.7%, not 34–39%**, because `qnodes` is incremented at the same site as
    `nodes` (`native/makhos_native.c:3962-3963`).
  - **Round 2 proposal:** ablation-based time attribution for the qsearch/movegen block
    (defines only, no source edit), with pre-declared criteria, and with every ablation
    result explicitly diagnostic — never strength evidence, never promotable.
  - Status: **NOT_PROMOTED**, no strength claim, no production change.
- Next: **record the verdict and stop extending the r3 candidate.** The single
  highest-value next action is to close **G2's race-detector clause** once a working
  Linux sanitizer runtime exists (Astra PR #18/#19) — it is the only gate blocked on
  something outside this repository. Do **not** re-run the existing C11 probe without
  a new hypothesis, do **not** install WSL, and do **not** treat ASan as TSan. No
  other work on this candidate adds value. A negative G4 result gives **no**
  authority to open shared-score cutoff (still `BLOCKED_SCORE_SHARING`) or to
  redesign the mechanism. Status remains NOT_PROMOTED; no SPRT launch or checkpoint
  mutation has occurred.
- G2 Linux handoff: user assigned race-detector execution to Astra Web and has
  **handed off** `build/lazy_smp_race_portable_20260916/astra_g2_handoff.zip`
  plus `ASTRA_WEB_PROMPT_TH.md` in that directory. No Linux result has returned
  yet. The bundle includes verbatim production function/type extraction, source
  hashes and a portable C11 harness. Re-verified 2026-09-16: the zip is still
  byte-current (`5b090c64…e3d3f`), the probe matches its manifest (`67f8b7cf…a19b`)
  and all three bundled sources (`native/makhos_native.c` `4b4362e3…`,
  `native/makhos_types.h` `c0880569…`, `tests/native_lazy_smp_portable.c`
  `6ae8fe0c…`) match both the worktree and the r3 freeze, so the handoff did not
  go stale. Windows normal compile/stress PASS (1,200,000 operations), but TSan is
  still NOT_RUN. Astra must verify a known-racy negative control and return raw
  evidence for five sanitized runs. Do not infer completion from handoff
  preparation. Note the bundle ships no pinned negative-control source, so that
  part of the TSan evidence is not independently reproducible from the zip.
  New exporter/template have a Windows smoke, not a rerun full-suite attestation.
- G2 Linux status per the user (2026-09-16): Astra PR #18 and #19 are **NOT_RUN**.
  The sanitizer / C11-thread runtime is not working there, and the r4-pthread
  harness has **not been implemented**. Consequences for planning:
  - Do **not** re-run the existing C11 probe without a new hypothesis; it has
    already been shown not to establish anything.
  - Do **not** install WSL locally and do **not** treat ASan as a substitute for
    TSan. No sanitizer evidence exists, so G2's race-detector clause stays open.
  - Keep three things named separately, because they are different deliverables:
    (1) the **r4 integration freeze** = `build/lazy_smp_acceptance_20260916_r4/contract.json`;
    (2) the **r4 integration audit** = `build/lazy_smp_r4_integration_audit_20260916/audit.json`;
    (3) the **r4-pthread harness** = not implemented.
  - Work that does not depend on a Linux runtime may continue, but no gate that
    depends on the sanitizer result may be closed in the meantime.
- Additional artifact found on inspection 2026-09-16:
  `build/astra_g2_github_worktree/` is a full source worktree snapshot for the
  Astra handoff. Its origin and status are unverified; it is not referenced by
  `manifest.json`. Leave it in place; do not treat it as evidence or delete it.

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
