---
name: thai-makhos-engine
description: >-
  Develop, diagnose, benchmark, and strengthen ThaiMakhosEngine in
  D:\ThaiMakhosEngine using correctness, reproducible performance, data,
  NNUE, and paired-SPRT evidence. Use for engine/search/evaluation, GUI
  Threads/Hash/runtime, game-loss analysis, corpus acquisition, NNUE, or
  promotion decisions; do not use it to resume large proof/tablebase work
  unless that work is explicitly requested.
---

# Thai Makhos Engine

## Mission

Build a Thai Makhos engine that can credibly compete for strongest in the
world. Optimize general playing strength at short and long controls without
sacrificing rules correctness, reproducibility, rollback, or user-facing
stability. “World strongest” requires independent external evidence; self-play
against an older internal build is not enough.

## Current directive — approved implementation (2026-09-07)

Read [references/current-state.md](references/current-state.md) first for the
current gate, immutable result identities, run-manifest pointer and next action.
It is the single current-state record; live counters come from validated
append-only pair logs and process creation identity, not prose or a cached PID.
Read the canonical atomic result only after its writer has stopped.

Execute the approved sequence in
[../../../DEVELOPMENT_PLAN_TH.md](../../../DEVELOPMENT_PLAN_TH.md):
finish the frozen Gate C controls -> reversible NNUE v1 production review ->
NNUE thread-scaling/profile audit -> one evidence-selected Elo experiment.
Gate C 1000ms is complete PASS. The sole active strength experiment is the
unchanged 2000ms match; inspect its manifest before launching or resuming.
Both controls must PASS independently before production review. During the
arena, prepare only isolated documentation/fixtures/low-resource tooling.
The staged ancestor-delta optimization is not part of the frozen candidate.

Optimize measured playing strength on this 6-core/12-logical-thread host.
Include 6 threads in 1/2/4/6/8/12 comparisons. Recommend the strongest supported
configuration; using fewer threads alone does not establish that SMP is solved.
Keep manual settings and report requested versus effective resources.

For NNUE features/model/data work read
[../../../NNUE_ROADMAP.md](../../../NNUE_ROADMAP.md). For a historical mechanism,
search [references/experiment-evidence-ledger.md](references/experiment-evidence-ledger.md)
before proposing it. Previous directive/evidence text is preserved in
[references/history/20260907-skill-before.md](references/history/20260907-skill-before.md);
read it only for historical evidence, never as a launch instruction.

## Authority and scope

Use this order when documents conflict:

1. the user's latest request and active goal;
2. this skill's current directive and invariants;
3. `DEVELOPMENT_PLAN_TH.md`;
4. `NNUE_ROADMAP.md` for NNUE details;
5. the historical evidence ledger;
6. deferred proof/architecture roadmaps.

Do not treat old test counts, live progress counts, “next” prose, filenames, or
point estimates as current authority. Re-measure cheap, drift-prone facts.

## Immutable identities

- Accepted control:
  `build/makhos_native_accepted.dll`, SHA-256
  `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.
  Never overwrite it during an experiment.
- Current source may contain infrastructure or source-level promotions but is
  not accepted merely because it builds.
- Every candidate DLL/model has a separate path and SHA-256.
- The GUI's active identity comes from runtime provenance/API state. Never infer
  it from a filename or a source tree.

Keep the accepted control recoverable until a reproduced candidate passes all
applicable gates and the production smoke/rollback procedure.

## Non-negotiable correctness and safety

- Never edit `RULESET.json`.
- Never edit `makhos/core.py`; it is the verified Python rules reference.
- Preserve mandatory capture, Thai king-halt landing, immediate captured-piece
  removal, end-of-turn promotion, threefold repetition, and 80 reversible plies.
- Native move/state changes require official initial-position perft through
  depth 10 and randomized Python/native differential tests.
- Proof/tablebase/terminal results remain authoritative over HCE or NNUE.
- Keep proof/DFPN/tablebase artifacts intact. Do not resume a large builder or
  delete/move its data unless explicitly requested.
- Inspect running engine/batch/tablebase processes before resource-heavy work.
  Do not stop a user workload without explicit approval.
- Never label a truncated game as a draw. A stable teacher search is an
  observational scalar/move label, not solved ground truth.
- The sealed NNUE test partition may not select architecture, features, loss,
  scale, epoch, weighting, checkpoint, or candidate.

## GUI and resource priority

The GUI has absolute priority. Acquisition, profiling, arena, SPRT, and
tablebase work must not run concurrently with a user-facing strength test.

- Interactive GUI/server work owns the complete workload lease.
- Batch workers must run BelowNormal, checkpoint at safe boundaries, drain, and
  release their slots when interactive priority is asserted.
- A byte-identical DLL does not make a loaded run comparable if background load,
  backend, time management, Threads/Hash, or isolation differs.
- Rebaseline after server/root-split/scheduling/time-management changes.

Do not open volatile `full_run_supervisor_status.json` while its writer is
active. Monitor process inventory, completed analysis filenames, shard logs,
stderr sizes, `.tmp` count, disk space, and final coordinator artifacts instead.
Use `python -B scratch/nnue_scaling_health_audit.py` for the bound read-only
snapshot; it must continue to report zero reads of analysis payloads, sealed
test files, and the volatile status file.

## Gate C recovery and monitoring

1. Read the immutable contract, current run manifest and last atomic result.
2. Verify process PID plus creation identity, GUI priority and workload isolation.
3. Validate full configuration, source/test/artifact hashes and recomputed paired
   statistics. Preserve old logs and incomplete-pair evidence.
4. Use only the contract's exact command with completed-pair resume. A completed
   PASS/FAIL or cap-INCONCLUSIVE result is a stop condition, not a restart target.
5. Unexplained stderr or identity drift requires incident review; no automatic
   retry or new seed. Closing the status display never stops the arena.

The read-only monitor is `work/nnue_gate_c_status_terminal.ps1`; it discovers
the arena through `build/runtime/nnue_gate_c_active_run.json`. Show both gates,
last completed pair, signed LLR/bounds and run/error/GUI state. LLR is not a
completion percentage. Verify Thai/English locale timestamps using Unix time.
For acquisition-specific reboot recovery only, consult the archived skill;
completed acquisition does not authorize restarting its old workers.

## Evidence-first work loop

For any engine/data change:

1. Inspect the active source, tests, processes, identities, and relevant ledger
   entries.
2. State one falsifiable hypothesis supported by the latest measurement.
3. Preserve a byte-for-byte control and record compiler/config/model hashes.
4. Change one concept only; keep experimental behavior opt-in/default-off.
5. Run the smallest correctness tests that can falsify it.
6. Run deterministic fixed-depth/fixed-time/profile gates appropriate to the
   hypothesis.
7. If search/evaluation/time behavior changes, run paired color-swapped
   pentanomial testing; do not promote from tactics, NPS, or a point estimate.
8. End with `PROMOTE`, `KEEP`, `REJECT`, or `INCONCLUSIVE`, cleanly revert when
   rejected, update the plan/ledger with reproducible evidence, and choose one
   next experiment.

Do not retry a rejected mechanism unchanged merely because another engine uses
it. A retry needs a new measured mechanism that directly addresses the recorded
failure.

## Testing policy without resource contradiction

During an active teacher/acquisition batch:

- run only focused, low-resource tests needed for documentation or isolated
  tooling changes;
- do not run the complete suite, benchmarks, or arena concurrently;
- do not modify scripts/hashes bound by the active acquisition manifest.

When workers are idle:

- run the complete currently discovered suite after code changes and before
  data finalization, trainer authorization, candidate promotion, or production
  replacement;
- for native move/state changes also run perft and differential gates;
- report the exact discovered test count and elapsed result; historical counts
  in the ledger are evidence snapshots, not current requirements.

Documentation-only edits require link/frontmatter/skill validation, not a
resource-heavy engine suite. Full tests remain mandatory before the next gated
code/data transition.

## Experiment classification

### Behavior-preserving

Representation/allocation/telemetry/refactor candidates must match the control
node-for-node, move-for-move, score-for-score, and PV where promised on the
deterministic suite. Require reproducible timing and memory results. Reject a
repeatable slowdown. SPRT is unnecessary only when behavior preservation is
actually proved. If faster inference/search changes depth reachable at fixed
wall time, confirm the fixed-time strength effect separately before promotion.

### Strength-changing

Any evaluation, pruning, ordering, TT policy, parallel schedule, time allocation,
or model that can change a selected move/score is a strength candidate. It needs
paired pentanomial evidence even when fixed-depth work or one external position
improves.

Use color-swapped opening pairs and preserve the five buckets:

`LL, LD+DL, LW+DD+WL, DW+WD, WW`

Use the generalized logistic pentanomial LLR. The primary intrinsic acceptance control is
`10s + 0.1s`, normally H0=0 Elo/H1=+2 Elo, with a predeclared maximum.
Production confirmation uses independent fixed 1s and 2s controls; keep the
current frozen Gate C contract unchanged. A positive
estimate whose confidence interval crosses zero is `INCONCLUSIVE`, not a pass.
Test Threads=1 intrinsic quality separately from the production 12-thread path
because the Python root splitter is a measured confound.

### Threads and Hash

Treat Hash as a total budget. Threads-related work must report actual native
allocation, effective per-worker layout, utilization, timeout behavior, and
1/2/4/6/8/12-thread scaling. More total nodes are not automatically useful work.

## Completed NNUE v1 pipeline evidence

Acquisition, trainer authorization, float training, quantization, scalar and
AVX2 parity, search integration, one-time sealed reporting, and Gates A/B are
completed milestones. Their source-bound evidence is retained in the historical
ledger and archived skill. Historical test counts are snapshots, not permission
to omit current tests. Use `scratch/nnue_full_suite_attestation.py` for the
complete suite while all workers are idle; it guards protected/sealed data,
owns the workload lease and binds exact source/test inventories.

A new model generation needs its own development manifest, game-level split,
train-only choices, fresh sealed test and frozen trainer/model contract. Reuse
validated tooling, not the authorization or opened test set of the old run.

## NNUE boundaries

The executable v1 feature ABI is now defined by
`makhos/nnue_features.py` (`thai-makhos-shared-137-v1`). It is a pure oracle,
not a playing-path dependency: the future trainer, scalar native evaluator,
refresh/incremental accumulator, and AVX2 implementation must reproduce its
indices, perspective order, clock buckets, and parent/child remove/add deltas
exactly. The contract gate is single-sourced from this module. A legal
position activates `piece_count + 1` features per perspective; a clock-bucket
change is the only clock delta for a quiet move, while captures and promotion
are derived from the authoritative parent/child states. Do not import the
oracle into playing code until an explicitly authorized candidate phase.

The v1 representation and shape are locked in `NNUE_ROADMAP.md`: shared
137-input Thai-specific sparse features, two 128-wide perspective accumulators,
32 hidden units, and one scalar output. Do not add a policy head or copy chess
HalfKP.

Before training, freeze target normalization, teacher/outcome/exact-WDL loss
mix, game/position/phase weighting, optimizer, seeds, deterministic settings,
learning-curve sizes, checkpoint/early-stop rule, and one-time sealed-test
policy. Architecture/loss/checkpoint/model/export must be frozen before opening
test labels. Reusing an opened test set to tune the next model is leakage; make
a fresh sealed split.

Quantized/native promotion requires Python/scalar-C/AVX2 and
refresh/incremental bit-exact parity, overflow proof, corrupt-model fail-closed
behavior, measured inference/search cost, diverse fixed-time evidence, paired
SPRT, and production GUI confirmation.

## Game-loss diagnosis

Replay and validate legality first. Bind engine moves to DLL/model SHA, backend,
rules, mode, Threads, Hash, requested/actual time, depth, nodes, score, and PV.
Find the earliest non-forced reproducible loss of value with fresh-state ladders.
Classify it as search horizon, root architecture, time management, evaluation,
or environment evidence. One game may add a regression; it cannot identify a
general HCE/NNUE weight or promote a candidate.

For detailed positional diagnosis only, read
[references/positional-diagnosis.md](references/positional-diagnosis.md).

## Deferred work

Large DFPN, larger tablebases, and proof-guided policy/value are not on the
current critical path. Read `PROOF_ROADMAP.md` or `POLICY_VALUE.md` only when
the user explicitly reactivates that scope. The rejected native root-PVS/SMP
record is diagnostic infrastructure, not an active playing candidate.

## Reporting and completion

At the end of each experiment report:

- hypothesis and changed files;
- control/candidate/model hashes and settings;
- correctness and deterministic benchmark evidence;
- RAM/Threads/Hash when relevant;
- SPRT settings, pentanomial, LLR, Elo interval, and status when behavior changed;
- accepted/rejected/inconclusive state and rollback condition;
- the single highest-value next experiment.

Do not call the overall mission complete because the GUI works, data acquisition
finishes, a model trains, one opponent loses, or one SPRT passes. Completion
requires sustained reproducible external competitive evidence under the
definition in `DEVELOPMENT_PLAN_TH.md`.
