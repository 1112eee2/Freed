# Historical snapshot before 2026-09-07 guide implementation

This content preserves the previous document for provenance. Relative paths
refer to its original location. Current instructions are in current-state.md,
SKILL.md and DEVELOPMENT_PLAN_TH.md; old next-action statements below are not active.

---

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

## Current directive — authoritative (2026-09-05)

**Gate B is complete PASS; the next experiment is Gate C production
confirmation, not another Gate B run.** Its immutable result is
`build/nnue_phase9_gate_b_seed20261102.json`, SHA-256
`1D439C7E96E189377D9865FA03AABD08D89611F7C903F3BB5B31C714853EAAB3`.
Recomputed pentanomial statistics agree: 550 pairs / 1,100 games, W498 D395
L207, buckets `4/47/230/192/77`, LLR `2.945863242736825`, reported Elo
`94.1514433519097 +/-13.470467078909259` versus accepted HCE at the locked
10s+0.1s, one-thread setting. This is not production promotion or evidence
against external opponents.

Prepare and predeclare Gate C using the same frozen candidate/model versus
accepted control at 1s and 2s per move, 12 threads and 512 MiB total Hash per
engine. Verify actual backend/allocation/time-stop behavior and paired strength
under GUI-priority workload isolation, following DEVELOPMENT_PLAN_TH.md Gate C.
Keep the staged `work/nnue_ancestor_delta_v1` optimization separate: only its
feature-algebra/isolation preflight has passed; no native build, performance,
or strength evidence exists for it. Do not combine it with Gate C.

### Completed phase provenance (historical, not launch instructions)

The frozen opt-in **NNUE search candidate** has completed Phase 7 pre-game gates
and the Phase 8 one-time sealed report. All six shards passed: 1,533 games,
41,698 selected positions, 23,097 eligible rows, zero stderr/tmp artifacts, and
one opening only. The immutable report is
`build/nnue_sealed_test_v1/sealed_test_report.json`, SHA-256
`BF5166F7BF2B5B5311C138321E5CF97AB8ECE8AC3DB3AF7E1F215A3E7AFD1077`.
It records quantized-vs-teacher MAE `0.1240688054049856` versus accepted-HCE
MAE `0.16674293355207395`; this is an offline gate, not Elo or promotion, and
the opened partition may never select or change this model.

Phase 9 Gate A **PASS** is now complete under the frozen contract. At seed
`20261101`, one thread, 256-MiB Hash, persistent search, production tablebases,
and `0.2s+0.01s`, it crossed H0/H1 `-10/+10` after 52 pairs / 104 games:
W49 D36 L19, pentanomial `0/8/18/14/12`, LLR `+2.9921776889755956`, and
`+103.1398415563513 +/-52.33548371749529 Elo` (95%). The result SHA-256 is
`6C6C29C6D430085FF5549741485D5702FE102651B24A0C8738B8061F9AECDEDA`.
This advances the frozen candidate to Gate B but does not promote it.

The completed experiment was **Phase 9 Gate B tooling and
primary acceptance**. Before launching the independent
`10s+0.1s`, H0=0/H1=+2 SPRT, add atomic per-completed-pair checkpoint/resume.
An interactive GUI interruption must leave the last complete pair recoverable,
must never count the in-flight pair, and a resume must reproduce the same RNG
opening stream/config identities. Prove this with focused tests and the complete
suite, then freeze the independent Gate B seed, pair cap, hashes, and output.
Offline loss, Gate A alone, fixed-depth results, external positions, and the
pipeline smoke pair cannot promote the model.

The resume tooling is now complete: focused SPRT/workload tests pass 16/16, a
real-DLL CLI smoke checkpointed one pair and resumed it without replay, and
complete-suite attestation v21 passes 389/389 at SHA-256
`9549E7A8E55A3C57713FEE92ADF32770E99574648652FCCC5E9F35A3192DA0AF`.
Gate B ran from `build/nnue_phase9_gate_b_contract.json`, SHA-256
`DD56A5709348F6CE88B13EC14A33DFC4A8F36AE4156298962427E28D7C3A7FB8`; do
not change any setting after the first pair. A GUI interruption is a pause, not
a new seed.

This directive and the current phase in `DEVELOPMENT_PLAN_TH.md` supersede every
historical sentence that says “next experiment.” The former 219-KB skill is
preserved at [references/experiment-evidence-ledger.md](references/experiment-evidence-ledger.md)
for mechanism/evidence lookup only; its old routing statements are not active.

Before acting, read [references/current-state.md](references/current-state.md)
and inspect the live worktree/process state. For the forward sequence and exact
phase gates, read [../../../DEVELOPMENT_PLAN_TH.md](../../../DEVELOPMENT_PLAN_TH.md).
For NNUE feature/model/data contracts, read
[../../../NNUE_ROADMAP.md](../../../NNUE_ROADMAP.md) only when the task touches
NNUE or acquisition. For a historical search/HCE candidate, search the evidence
ledger by mechanism name before proposing it.

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

## Crash and reboot runbook

Atomic data and the lease protocol are crash-safe; the supervisor/process-handle
watcher is not OS-reboot-persistent. After reboot or unexplained process loss:

1. verify whether a GUI/server or interactive lease is active;
2. verify no supervisor/coordinator/worker duplicate is alive;
3. count completed atomic artifacts; inspect stderr, `.tmp`, and free disk;
4. rehash the accepted DLL, bound acquisition/coordinator/supervisor/isolation
   scripts, config, manifests, and authorization artifacts;
5. if a non-empty log is fully explained by external process loss, hash it and
   move it to `incident_logs/` with a recovery record; never delete, truncate,
   overwrite, or silently exclude unexplained stderr;
6. if every binding matches and no GUI is active, relaunch only the locked
   supervisor; never launch ad-hoc workers. On Windows launch it as a hidden
   detached process with separate launcher stdout/stderr so a terminal/task
   lifetime cannot own the acquisition;
7. verify one supervisor, one coordinator, six correctly configured workers,
   BelowNormal priority, expected affinity, zero new stderr/tmp, and forward
   progress;
8. record the incident and preserved count without calling it a data failure.

If any binding differs, fail closed and audit. Do not edit generated JSON by
hand to force resume.

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
actually proved.

### Strength-changing

Any evaluation, pruning, ordering, TT policy, parallel schedule, time allocation,
or model that can change a selected move/score is a strength candidate. It needs
paired pentanomial evidence even when fixed-depth work or one external position
improves.

Use color-swapped opening pairs and preserve the five buckets:

`LL, LD+DL, LW+DD+WL, DW+WD, WW`

Use the generalized logistic pentanomial LLR. The primary acceptance control is
`10s + 0.1s`, normally H0=0 Elo/H1=+2 Elo, with a predeclared maximum. A positive
estimate whose confidence interval crosses zero is `INCONCLUSIVE`, not a pass.
Test Threads=1 intrinsic quality separately from the production 12-thread path
because the Python root splitter is a measured confound.

### Threads and Hash

Treat Hash as a total budget. Threads-related work must report actual native
allocation, effective per-worker layout, utilization, timeout behavior, and
1/2/4/8/12-thread scaling. More total nodes are not automatically useful work.

### 2026-08-30 Threads contract repair (source-level KEEP; full suite pending)

The GUI/CLI contract and every measured production matrix stop at 12 Threads,
but `ParallelNativeSearch` and two server validation seams still accepted 13--16.
A red-capable focused loop proved that Threads=13 reached both native-library
loading and the server engine factory. The backend and server now share
`MAX_PARALLEL_NATIVE_THREADS = 12`; selective-candidate and shared-TT group
configuration use the same ceiling. The original two regression tests plus the
adjacent invalid-settings test pass 3/3 in 0.001 seconds. Current hashes are
`parallel_native.py` `56CF41C9DEB943537326844B45195AE50B7114FF70B01F9AB20B5E1D3B5920F0`,
`server.py` `4C92184F1818A588D55190339674DE96034E538572842CA7D2234BF7E3A546C2`,
`test_native_search.py` `328E9EAB75700784224604C90F5AD7B1D42F25727102716A5DAB25B60F2E2C53`,
and `test_server.py` `4BE61E0C2909A39118F2B7F821FD18FDDCFF6C2805B606770A66CC43E27327D3`.
The accepted DLL remains byte-identical. This is a fail-closed configuration
repair, not an Elo claim or playing-path promotion; the complete suite remains
mandatory after acquisition workers are idle.

## 2026-08-30 Phase 0--3 evidence (KEEP; not a playing promotion)

- Acquisition completed exactly 13,802 development analyses; final audit A/B
  are byte-identical at SHA-256
  `9FF7A425CB40EB3741225554A0AC3886FC08C92F776E4E532F4B04D1FFAB20E6`.
- The audited corpus contains 199,923 eligible train rows and 23,550 eligible
  validation rows. Train has 19,535 exact-WDL labels. The sealed-test manifest
  and test analyses remain unread.
- The final source-bound full-suite attestation is
  `build/nnue_phase1_evidence/full_suite_attestation_v5.json`, SHA-256
  `C19E1FA3F94DD4BD0D86ED1F2AFF6E597A3ADC4C33BE981C91B0B8AE7F693739`;
  all 339 discovered tests passed.
- Frozen contract A/B are byte-identical at SHA-256
  `890B1B6AF0D8DF0E5FEE4F4ABA111E531A33B47837D77CA1D852CA6656F5C12E`.
  The real preflight passed and authorization SHA-256 is
  `7590DB46F45D0D7E674B5B341C1B80D9F8C4A6DCFA783EC0A10BB89042A355FD`.
- `build/nnue_float_v1/training_result.json` is a PASS artifact, SHA-256
  `B3D2A2E0FED326E06179ED0EEEC92EEF3A248300D8F7CB620A06FCA4490B9C41`.
  All 8 predeclared runs completed. Validation improves with data size across
  both seeds. The contract-selected full-data seed `20280002` checkpoint has
  validation loss `0.08270999044179916`, teacher MAE `0.12098223072290963`
  versus accepted-HCE MAE `0.16617580001338003`, teacher Pearson
  `0.8678187832904446`, and model SHA-256
  `5FD87ABD2F9CAAC81045A58AEA420445B90CAC9A70D5FFBDFC5694BA1338CA4E`.

This is a float-model/data result only. It is not native inference, an Elo
claim, or a promotion against the accepted DLL.

## 2026-08-30 Phase 4 quantized export (KEEP; offline artifact only)

- Quantization contract SHA-256 is
  `68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF`;
  exporter SHA-256 is
  `9854F2065605E9F875F836DED656C981A7CC886A71CD1D450F3AB9E185FB18F4`.
- Full suite v7 passed all 344 discovered tests, attestation SHA-256
  `22243703051E8E3632D83BC6D1F8F5E583A06CE515ECD490824F942814633B94`.
- Export A/B and parity report A/B are byte-identical. `MKNNUE1` binary size is
  43,872 bytes, SHA-256
  `07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C`;
  report SHA-256 is
  `969A7C0FFF1F3675DC6BC6D48BB942C16EF57C18D3478E0AC530B26B9800C4D7`.
- On all 23,550 validation rows, float-vs-quantized MAE is
  `0.00230912088115429`, RMSE `0.00302979286685792`, max absolute error
  `0.0148904375679927`, and sign mismatch rate `0.00382165605095541`; all
  pre-frozen limits pass.
- Conservative legal-position overflow proof: int16 feature accumulator bound
  16,935/32,767; int32 dense bound 806,516/2,147,483,647. Corrupt, truncated,
  and incompatible binaries fail closed in the Python loader tests.

This remains default-off offline tooling. It is not native inference, search
behavior, Elo evidence, or accepted-control promotion.

## 2026-08-31 Phase 5 native scalar oracle (KEEP; measurement only)

- The standalone loader/full-refresh source SHA-256 is
  `D95CE674EE9180EDCAAFAD08F2D42C4FAD20212374F94A45A32460251EF93704`;
  its focused test SHA-256 is
  `5411D7A8D44D18A321652C584A44C6BCE54563321940B2282DC43CBA31CCED1B`.
- `build_nnue_scalar.ps1` performs two `/Brepro` builds with the same basename,
  refuses accepted/model/contract drift, and produced byte-identical DLLs at
  SHA-256 `2D071F91EC9551FD82EB8793F4E651BD1FA87A9B14C1EA3A6A4B3588B248634C`.
  The model allocation is 43,684 bytes; build-manifest SHA-256 is
  `FB5F66A2983BB8AE8F7111F8B38B806139ED80729AC2B250101CF5083C2BEEC3`.
- Real KEEP-model parity passed 1,152/1,152 cases: 640 structured cases spanning
  2/6/10/16 pieces, both turns, and every reversible clock 0--79, plus 512
  seeded random legal positions. Report SHA-256 is
  `3E206D0C2A6F9A142006BA0ADBD9A83C2DB6FF62A942B34F0C95D36D11106D82`.
  Corrupt, truncated, incompatible, wrong-source, invalid-feature, and
  checksum-valid-but-overflow-unsafe models/inputs fail closed.
- On the Ryzen 5 5600H, the reproducible BelowNormal raw-cost screen measured
  full refresh at 2,355.643/1,978.304/1,981.276/1,431.463 ns for
  16/10/6/2-piece cases. Accepted HCE measured
  21.088/15.286/12.232/8.329 ns, so full-refresh scalar is 111.7x--171.9x
  slower. Raw-cost report SHA-256 is
  `4F301866CBB4FE3FC96CFAF26E39C6A7D230BC84E138D1881306EFC1C88A4E1D`.
- Source-bound full-suite attestation v9 passed all 351 discovered tests in
  67.777 seconds with zero protected/sealed reads; SHA-256 is
  `E8CE7B0E33FB10E05B29D97D499F128E896B7AFA9D93B1A14826E4E52A7F1DDB`.
  Accepted DLL remains byte-identical.

Verdict: **KEEP as the scalar correctness oracle, never as a playing path**.
The measured cost requires incremental accumulation and AVX2 before any search
candidate; no SPRT applies because search behavior did not change.

## 2026-08-31 Phase 6A scalar incremental oracle (KEEP; measurement only)

- The standalone incremental source SHA-256 is
  `CD2575527528B0B96D924A867A64B9EBEFC9BB8363FB7CC127BF6ED08CF0FFC9`;
  `build_nnue_incremental.ps1` SHA-256 is
  `BFACF797F9FB18DDA484260DBD75D606E9A2DE32D8FB47B963DC93B46EF86DB2`.
- Two `/Brepro` builds are byte-identical at DLL SHA-256
  `E455B708423F4B8B8B126263DB7A5F7BD5E7645DDF300114DC07EAB8B01C0CE7`;
  build-manifest SHA-256 is
  `D2AB902408102C2858A5F22ACA64386FFF937974ED485313AA67592F870F50A6`.
  The wrapped model allocation is 43,704 bytes and each accumulator is 584 bytes.
- Final-artifact parity has zero mismatches across 640 structured refresh states,
  4 targeted quiet/capture/promotion/multi-capture forward/undo transitions,
  all 8 clock-bucket boundaries, resets from all 9 buckets, 300 seeded random
  forward/undo/reapply transitions, a requested 64-ply deep stack, invalid state,
  and model reload. Focused-test SHA-256 is
  `1A652D00AE1952C47A9E90044BA0E81B99AF3F7DCBC1467907262F256A515BBB`;
  parity-report SHA-256 is
  `8241D1FC5CA34A6E81AE3CF5FB00444CD7952B7BC5925D732B0D545885B25475`.
- BelowNormal medians for 16/10/6/2 pieces were 769.266/761.443/789.101/
  780.758 ns for dense scalar evaluation and 637.942/629.348/629.898/437.547 ns
  for a forward move update across both perspectives. Dense evaluation is
  1.833x--3.062x faster than Phase 5 full refresh, but still 36.479x--93.740x
  slower than accepted HCE; update plus evaluation is 66.730x--146.273x slower.
  Raw-cost report SHA-256 is
  `FB6E74281A570249ADCB7B6DF4CDBFA9838D9FF121C9FB602B3EAB1D8E6F3456`.
- Source-bound full-suite attestation v11 passed 356/356 in 68.252 seconds with
  zero protected/sealed reads; SHA-256 is
  `760FE2EB829EA7C269A9B220EF4B96DCF74E5DC0144E3FE06875A2FE43D84C1C`.
  Accepted DLL and the playing path remain byte-identical/unchanged.

Verdict: **KEEP as the incremental scalar correctness oracle, never as a
playing path**. No SPRT applies because search behavior did not change. The
next experiment is the isolated AVX2 dense-evaluation kernel specified by the
current directive; scalar delta-update vectorization remains a later decision.

## 2026-08-31 Phase 6B AVX2 dense oracle (KEEP; measurement only)

- AVX2 source SHA-256 is
  `2137BC4BB4DBB8E85CE2F38F93B3C529C20A497E7C7E3A078F04EBB765D84568`;
  reproducible build-script SHA-256 is
  `D1610418400145193215B6985B20015D5B220F0754E90898AC3A5361436FF157`.
- The DLL is baseline x86-64 with an AVX2 function target and explicit runtime
  gate, not a globally AVX2 binary. Two `/Brepro` builds are byte-identical at
  SHA-256 `EA6B6A1C47671CC1050E9FC861D3BF403E2AD6FCB6D07A7B24BE62E41B8C250A`;
  build-manifest SHA-256 is
  `0C657B4A6408F0EF2C5720BB2D41CE8F125577043FAA60415263CB13D3463DCD`.
- Final-artifact AVX2/scalar parity has zero mismatches on the complete Phase 6A
  corpus, the target host reports AVX2, and a forced-unsupported build fails
  closed without modifying output. Focused-test SHA-256 is
  `AFDBB15B27958577D769FF4D8B020351D7B6A96792493F4EF6D526B0E5468198`;
  parity-report SHA-256 is
  `E3529A12455BE179EAF557FD086216CC3E18A0CD1F9921D6E15C38B67F6C2F92`.
- BelowNormal alternating-order medians for 16/10/6/2 pieces were
  154.062/158.872/159.664/157.358 ns per AVX2 dense evaluation. This is
  4.793x--4.993x faster than the Phase 6A `-march=native` scalar control.
  Dense AVX2 alone is still 7.306x--18.893x slower than HCE; combining it with
  unchanged scalar updates projects 594.905--792.004 ns per update+eval and
  37.557x--71.426x HCE latency. Raw-cost report SHA-256 is
  `80DCD2FA5F889CB54C2163FDB8EF1E6B199F806B8E4A4068769A3B073C07B6C9`.
- Source-bound full-suite attestation v12 passed 363/363 in 71.191 seconds with
  zero protected/sealed reads; SHA-256 is
  `4D9FCA24A27015D32E0B1D1827A673E6937A084823405664CE98711E0F329687`.
  Accepted DLL and playing path remain unchanged.

Verdict: **KEEP as the standalone AVX2 dense correctness/performance oracle,
not as a playing path**. No SPRT applies. Scalar delta updates now dominate the
measured cost, so the next experiment is the isolated AVX2 update kernel in the
current directive.

## 2026-08-31 Phase 6C AVX2 delta updates (KEEP; measurement only)

- AVX2-update source SHA-256 is
  `6A236861A185D6C6DAD8DA785F10C92D680D26823C4A534F5733E56651FD182C`;
  reproducible build-script SHA-256 is
  `F4E4C74855BA45B0BE5A82FE2CB77F3D9F30FB515A2EF5076D3E80EBF2DFF21C`.
- Two `/Brepro` builds are byte-identical at DLL SHA-256
  `64C862F3FC2AB99ACFE2AEE04966401E05B48849FF61EAE14A5F5208C5873095`;
  build-manifest SHA-256 is
  `57A31A0841BF50DEFEFFE9FA74722868AF9296056F6FBE900C7D8310C27841B1`.
- Scalar/AVX2 forward/undo/reapply parity has zero mismatches for quiet 1/1,
  clock-boundary 2/2, capture 3/2, multi-capture 4/2, promotion 2/2, every clock
  transition/reset, 300 seeded random transitions, the deep stack, invalid
  deltas, reload, and forced-unsupported fail-closed behavior. Focused tests pass
  10/10; parity-report SHA-256 is
  `E95821C2027F6E2EC7AD04366C0DFDFA3D3B90FA09B377ADD44ECF582962D680`.
- BelowNormal alternating-order AVX2 medians are 87.427/121.573/134.418/
  138.179/121.884 ns for quiet/boundary/capture/multi-capture/promotion,
  4.987x--5.926x faster than the scalar update control. Combining these with
  the Phase 6B dense reference estimates 245.542--296.294 ns per update+eval;
  this is a planning estimate, not measured search NPS.
- Source-bound full-suite attestation v13 passed 373/373 in 82.544 seconds with
  zero protected/sealed reads; SHA-256 is
  `7E7F1BBB1D1AB73BC76B0C02C8228C4C6540322766BD659E28D540D5549F2964`.
  Accepted DLL and playing path remain unchanged.

Verdict: **KEEP as the standalone AVX2 update oracle, not as a playing path**.
No SPRT applies. All pre-search model/inference gates are now complete; the
current one-concept experiment is the separate opt-in NNUE search candidate in
the authoritative directive.

## 2026-08-31 Phase 7 NNUE search candidate (PRE-GAME PASS; not promoted)

- Reproducible candidate DLL SHA-256 is
  `32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79`;
  it binds quantized model
  `07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C`
  and feature ABI `thai-makhos-shared-137-v1`. Accepted remains
  `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.
- Lazy per-ply accumulators replace only non-terminal static evaluation. The
  parity guard passed 40 recursive depth-6 searches; focused NNUE/parallel tests
  pass 5/5, including exact 256-state Python/native evaluation parity.
- Native perft depth 10 is `861842812`; randomized differential PASS covered
  504 positions, 2,660 legal child states, and 20 exact three-piece positions.
- The diverse pre-game audit SHA-256 is
  `E8AE7AF5E91AF29CB393591E21BA3C26108FEB71DCDD547F39EAD4D75A9D3C7D`.
  At fixed depth 13 the candidate used 2,115,317 total nodes versus 2,308,721
  for accepted but 1.812515x total time; at 250 ms it reached median depth 18.5
  versus 19 and about half the nodes. This is a real NNUE cost, not an Elo result.
- Direct and HTTP GUI smokes passed at 12 Threads / requested Hash 512 MiB
  (480 MiB allocated). The 1-second direct search used 1001 ms; the 100-ms HTTP
  search used 103 ms and exposed the exact DLL/model SHA, feature ABI, and
  `native-root-split` backend. A one-legal-move case returned the forced `14x5`
  at the exact 100-ms native budget.
- The model-aware paired pipeline smoke completed one color-swapped pair and
  recorded both identities; its two truncated screening games were draws and
  the result is deliberately `INCONCLUSIVE`, not strength evidence.
- Source-bound full-suite attestation v16 passed 379/379 in 78.638 seconds with
  zero protected/sealed reads; SHA-256 is
  `BB991A79B4A9459BE1A28A05CE65B0A322A3C09D7F64063E283F4E1EB713F61E`.

Verdict: **freeze the Phase 7 candidate for the offline/arena gates, but do not
promote it**. The current one-concept experiment is the Phase 8 sealed-test
harness and one-time report in the authoritative directive.

## 2026-08-31 Phase 8 one-time sealed test (COMPLETE; not promoted)

- Six whole-game shards passed with 1,533/1,533 analyses, 41,698 selected
  positions, 23,097 eligible positions, zero stderr bytes, and zero temporary
  artifacts. Every shard records `model_selection_forbidden=true`.
- The one-time report is SHA-256
  `BF5166F7BF2B5B5311C138321E5CF97AB8ECE8AC3DB3AF7E1F215A3E7AFD1077`;
  its analysis inventory SHA-256 is
  `95C91738735D56B3B437E2B5AABC6CF2557B2FFB8827E7FB2148022CC41F61C7`.
- Quantized-vs-teacher MAE/RMSE/sign-mismatch are
  `0.1240688054049856` / `0.18659824112575277` / `0.19028017527552782`.
  Accepted-HCE-vs-teacher values on the same rows are
  `0.16674293355207395` / `0.23435484433668882` / `0.27046868704955457`.
- Exact-WDL coverage is 2,648 rows; quantized MAE is `0.3768029441821094`
  with sign mismatch `0.03556187766714083`. These diagnostics may not tune the
  opened model or make the partition unseen again.

Verdict: **OFFLINE_REPORT_COMPLETE_NOT_STRENGTH_PROMOTION**. Keep the frozen
candidate and accepted control unchanged. Phase 9 Gate A is now frozen and
ready to run.

## 2026-08-31 Phase 9 arena-integrity preflight (KEEP tooling)

- `sprt_max_plies` now raises before either game in a pair can be counted; the
  old behavior that silently converted truncations to draws is removed.
- SPRT owns a `BatchWorkLease` and checks GUI priority before every pair and
  every ply. A GUI request aborts the unscored in-flight pair and closes native
  engines/tablebases before releasing the lease.
- Focused SPRT/workload tests pass 13/13. Full suite v20 passes 386/386; its
  artifact SHA-256 is
  `DAB696B9128CB249F61E49DED85C134F2439AB21912A42AD8C16BCE80D959135`.
- The CLI lowers only its arena process to Windows BelowNormal; the acquisition-
  locked `workload_isolation.py` remains byte-preserved. The full-suite guard
  explicitly rejected the first locked-source attempt before this correction.
- Gate A is predeclared in `build/nnue_phase9_gate_a_contract.json` (SHA-256
  `47E591BAE0E3A29F7A386851EE0ECD242452594E9C19B8ED835850ED8D47DA8E`): seed
  `20261101`, `0.2s+0.01s`, H0/H1 `-10/+10`, 256 pairs, Threads=1,
  Hash=256 MiB, persistent search, eight opening plies, sequential
  color-swapped games, production tablebases, and max 300 plies. Only PASS
  advances; cap exhaustion is INCONCLUSIVE and does not advance.

## 2026-08-31 Phase 9 Gate A strength screen (PASS; not promoted)

- Result: 52 pairs / 104 games, W49 D36 L19, pentanomial
  `0/8/18/14/12`, LLR `+2.9921776889755956`, Elo
  `+103.1398415563513 +/-52.33548371749529` (95%).
- Result/config log SHA-256:
  `6C6C29C6D430085FF5549741485D5702FE102651B24A0C8738B8061F9AECDEDA` /
  `C6E1E0738923EE23978298B4FEB669012FAF4FBB6DEDD54CD2E6CF31E753906A`.
- Accepted DLL, candidate DLL, and model remained byte-identical at their
  frozen hashes. No truncation or GUI-priority interruption occurred.

Verdict: **PASS_GATE_A_NOT_PROMOTED**. Proceed only to resumable, independently
seeded Gate B; do not install the NNUE model into production yet.

## 2026-08-31 Gate B atomic resume preflight (KEEP tooling)

- Every completed color-swapped pair atomically replaces a v2 result file.
  An interrupted in-flight pair is never counted.
- Resume requires byte-equal JSON configuration, validates W/D/L, game count,
  pentanomial and recomputed statistics, then replays the seeded opening RNG for
  completed pairs before continuing.
- Focused tests pass 16/16. The real-DLL resume smoke SHA-256 is
  `1241367F48F1F45038D1809C42D953FDCE231C8C43889ABEF432648464A622F2`.
  Complete-suite v21 passes 389/389 at SHA-256
  `9549E7A8E55A3C57713FEE92ADF32770E99574648652FCCC5E9F35A3192DA0AF`.

Verdict: **KEEP_TOOLING_NOT_STRENGTH_EVIDENCE**. Gate B is the only active
strength experiment.

## Completed acquisition exit gate

Do not authorize a trainer until all of the following are proven:

- exactly 13,802 development analyses match the development manifest, with no
  missing or extra files;
- coordinator PASS summary, source/shard/analysis inventories, and hashes agree;
- every analysis binds accepted SHA, project rules, Threads=1, Hash=256 MiB,
  persistent search, clear-once protocol, and 100/500/2000-ms warm ladder;
- position, canonical id, pieces, kings, phase, turn, legal moves, selected ply,
  and label eligibility are recomputed rather than trusted from row metadata;
- train/validation coverage, uniqueness, outcome semantics, stderr, `.tmp`, and
  reproduction gates pass;
- test analysis reads and sealed-test-manifest reads remain zero;
- the final readiness artifact reproduces byte-for-byte;
- the complete suite passes after all workers are idle.

`scratch/nnue_scaling_final_audit.py` is prepared for this gate but intentionally
cannot PASS an incomplete acquisition. Its artifact must not itself authorize
training. Freeze the separate trainer contract in `DEVELOPMENT_PLAN_TH.md`
first.

The separate fail-closed authorizer is
`scratch/nnue_trainer_contract_gate.py`. It may run only after acquisition is
complete and must receive two byte-identical final audits, two byte-identical
frozen trainer contracts, the exact development manifest, disjoint train and
validation analysis inventories that reconstruct the audited analysis-set hash,
a complete-suite PASS attestation produced while workers were idle, and a real
tiny-fixture trainer preflight proving overfit, deterministic repeat/resume,
checkpoint checksum, and sealed-test guards. Until those inputs exist, training
remains unauthorized; never fabricate placeholder evidence from the active
partial corpus.

Produce the complete-suite evidence only with
`scratch/nnue_full_suite_attestation.py`. It must fail closed unless acquisition
health is `COMPLETE_PENDING_FINAL_GATES`, every pipeline process is gone, the
GUI is inactive, and one exclusive lease owns all workload slots. It checks GUI
priority around every test, guards production analysis/sealed/status paths,
requires every discovered test to PASS, binds the accepted DLL, final audit,
runner, result output, and exact source/test inventories before and after, and
writes only outside the acquisition and source/test trees. The trainer gate
must recompute the current inventories instead of trusting attestation fields.

After both final audits reproduce, create the contract's exact train/validation
inventories only with `scratch/nnue_trainer_input_inventory.py`. It must bind the
coordinator's final analysis hashes to the locked development manifest, rebuild
the final audit's analysis-set hash, keep outputs outside the locked acquisition
directory, and report zero payload/sealed/test reads. The inventory artifact is
not a trainer authorization and must not be generated from a partial run.

The deterministic contract freezer is
`scratch/nnue_trainer_contract_freezer.py`. It is safe to focused-test during
acquisition because it reads no production analysis or sealed-test file, but it
may build/write a real contract only after the final audits, idle full-suite
attestation, exact train/validation inventories, and trainer source/fixture
choices are real. It requires every dynamic evidence hash and train-only choice
explicitly, injects the executable feature oracle and locked policies, rejects
test-dependent fields and protected output trees, and writes canonical
byte-locked JSON. It never authorizes training; the separate contract gate must
still validate the completed evidence.

The deterministic tiny-fixture preflight is now available as
`scratch/nnue_trainer_preflight.py`. It is tooling-only and may be focused-tested
while acquisition is active, but the active run may use only the synthetic
`thai-makhos-nnue-trainer-fixture-v1` fixture. The harness reads the frozen
contract, final-audit metadata, trainer-source identity, and explicit fixture;
guards production analyses, test analyses, sealed-test manifest, and volatile
supervisor status; proves overfit, deterministic repeat/resume, checkpoint
round-trip checksum, and fail-closed path guards; and discards fixture weights.
Its artifact is non-authorizing and must be written outside source/acquisition
trees. A real preflight is valid only after the final-data audit, idle full-suite
attestation, exact train/validation inventory, and real frozen contract exist.
The direct-file CLI bootstraps the repository root before importing tooling and
has a focused smoke test; this launch repair does not alter the playing path.

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
