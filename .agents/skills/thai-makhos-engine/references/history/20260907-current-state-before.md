# Historical snapshot before 2026-09-07 guide implementation

This content preserves the previous document for provenance. Relative paths
refer to its original location. Current instructions are in current-state.md,
SKILL.md and DEVELOPMENT_PLAN_TH.md; old next-action statements below are not active.

---

# Current ThaiMakhosEngine state

Last reviewed: 2026-09-05.

This file is a stable routing snapshot, not a live progress counter. Inspect the
current worktree and processes before acting.

## Authoritative phase

**Gate B completed PASS; Gate C production confirmation is next.** The final
atomic result `build/nnue_phase9_gate_b_seed20261102.json` has SHA-256
`1D439C7E96E189377D9865FA03AABD08D89611F7C903F3BB5B31C714853EAAB3`.
It contains 550 pairs / 1,100 games, W498 D395 L207, pentanomial
`4/47/230/192/77`, LLR `2.945863242736825`, and reported Elo
`94.1514433519097 +/-13.470467078909259`. On 2026-09-05 the arena PID was
absent, stdout ended with PASS, stderr was empty, `complete=true`, and
recomputation from the pentanomial reproduced all statistics. Original v21
source/test inventories and accepted/frozen candidate/model hashes were
reverified. Do not resume this completed match.

Gate C is not yet implemented/launched: predeclare isolated production-setting
checks at 1s and 2s per move, 12 threads, 512 MiB total Hash per engine, using
the unchanged frozen model/DLL. GUI default remains HCE; no promotion exists.
The historical Gate B preparation/recovery paragraphs below are provenance,
not the active next action.

Gate C harness preparation: `makhos.sprt` and CLI now have an explicit
`fixed_move_time_ms` / `--fixed-move-time-ms` option. Clock-mode behavior and
legacy checkpoint config shape remain unchanged; fixed mode bypasses clock
allocation on both colors, rejects a simultaneous clock cap, and binds the
budget into checkpoint configuration. Focused SPRT/workload tests pass 20/20.
Full-suite v22 passed 393/393, zero skips/failures/errors, at attestation SHA
`1271ECBFE903FC8D672CA250BC4D135F8D5C9C2BB6CBF28533CEE154FD9DE7A8`.
The v21 source/test inventory is historical after
these harness/test edits; accepted and frozen NNUE DLL hashes remain unchanged.
No Gate C strength games have been launched. A separate one-pair fixed-time
tooling smoke started on 2026-09-05: see
`build/nnue_gate_c_fixed_smoke_v1/RUN.md` for PID/start identity, exact command
and scope. Revalidate that process and result before resuming. This uses
1,000 ms, 12 threads, 512 MiB budget and production TB, but cannot establish
Gate C strength or promotion. Per-move timing/allocation diagnostics and the
independent 1s/2s confirmation contracts remain next.

The one-pair smoke subsequently completed normally: complete=true, W1 D0 L1,
INCONCLUSIVE, result SHA-256
`A5C329DE2B3BBCA94E8FF2F18398C3887B28B357C4E8CDF3BB0D2C48B6801E80`.
Runtime diagnostics now use `work/nnue_gate_c_runtime_audit.py`; inspect
`build/nnue_gate_c_runtime_v1/RUN.md` for process/start identity and scope.
It schedules 96 observations through the GUI factory without an HTTP server
or default changes, at 1s/2s and 12T/512 MiB. Output, if completed, is
`build/nnue_gate_c_runtime_v1.json`. Review actual allocation/backend/timing
and quality diagnostics before freezing independent Gate C paired matches.

Runtime audit subsequently completed 96/96: report SHA-256
`57A521D9178677F6568F5107F83E81F9D042EEB9775B2C9C10948B7D5A0EA732`.
Both engines used 12 workers and 480 MiB allocated TT within the 512 MiB
budget, correct backend/model/TBs, no fallback/error, and <=6.11ms maximum
wall overshoot. See `build/nnue_gate_c_runtime_v1/REVIEW.md` for the two
NNUE 1s move instabilities at different completed depths and scope limits.
This completes runtime diagnostics, not strength confirmation. Next action is
freeze independent paired 1s/2s Gate C contracts and run sequentially using
the unchanged DLL/model; no engine promotion has occurred.

Gate C contracts are now frozen before games in
`build/nnue_gate_c_contract_v1.json`, SHA-256
`5B727707FBED8D5E9D79AE89159D9DF1EAF5C74D8AFE31A654F3CDC191F6A3F7`.
1000ms seed20261105 runs first; 2000ms seed20261106 follows separately.
Both are 12T/512MiB, paired, H0=0/H1=+2, cap10000 pairs, same frozen
DLL/model/TBs. Both must PASS before production review; no pooling controls.
The 1000ms arena started 2026-09-05 at PID12112: inspect
`build/nnue_gate_c_1000ms_run_v1/RUN.md` for exact start identity/command and
logs, and `build/nnue_gate_c_1000ms_seed20261105.json` for completed pairs.
2000ms has not started. No promotion exists. Do not edit frozen source or
restart an arena merely because an observation handle expires.

On 2026-09-06 the original 1000ms PID12112 was absent with empty stderr. Its
atomic checkpoint preserved 73 pairs / 146 games, W61 D50 L35, pentanomial
`0/10/34/22/7`, LLR `0.41835018999427`, INCONCLUSIVE. All contract-bound
hashes and v22 inventories were revalidated; GUI priority was inactive. The
same command resumed under PID17676 at
`2026-09-06T10:53:15.6364641+07:00`, BelowNormal. Recovery evidence/logs are
in `build/nnue_gate_c_1000ms_resume_25690906_101323/RECOVERY.md`. Verify the
PID/start time, checkpoint and logs before claiming this resume remains live.

An optional future optimization is staged under `work/nnue_ancestor_delta_v1`:
nearest-valid-ancestor net feature deltas instead of recursive intermediate
materialization. Its read-only preflight passed 3,832 feature-algebra checks
and source/artifact isolation checks. Native compilation/parity, performance,
and strength remain untested. Gate C takes priority; keep this candidate out
of the frozen NNUE confirmation.

The frozen separate opt-in NNUE search candidate passed Phase 7 pre-game gates
and completed the Phase 8 one-time sealed report.
Its DLL SHA-256 is
`32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79` and
its model SHA-256 is
`07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C`.
Recursive parity, perft depth 10, randomized differential, fixed-depth/time,
external diagnostics, 12-Thread/512-MiB time-stop/forced-move, opt-in GUI
startup/provenance, and full suite v20 (386/386) pass. The accepted DLL and
production GUI default remain classical and byte-preserved. The Phase 8 harness
is frozen at source/test SHA-256
`EAAEF8129A8DAA49F1A482B564B96CEAF3FC1DFC78E72F571135B02AB131CC55` /
`E0C36DF684546A137FE2049762FA035F35E08AA89585B8932F9822B97A144A10`.
The sealed partition was opened once under commitment SHA-256
`8F00BB6341B271D379BA48B406199B3C5AE50C75037CA2AEFB54AAE9AFEFB44E`.
All six shards passed with 1,533 games, 41,698 selected positions, 23,097
eligible positions, zero stderr/tmp artifacts, and no second opening. The
immutable report SHA-256 is
`BF5166F7BF2B5B5311C138321E5CF97AB8ECE8AC3DB3AF7E1F215A3E7AFD1077`;
its verdict is `OFFLINE_REPORT_COMPLETE_NOT_STRENGTH_PROMOTION`.
Acquisition and all development-data gates are complete. The development
partition has 13,802 games; the sealed test partition has 1,533 games and
41,698 selected positions. Those labels may now be read only by the frozen
Phase 8 report path; they may not select or alter a model.

The completed teacher contract used:

- accepted DLL SHA-256
  `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`;
- project rules;
- one persistent teacher thread;
- 256 MiB Hash;
- clear once per position, followed by warm 100/500/2000-ms searches;
- six BelowNormal whole-game workers under the GUI-priority workload lease.

Phase 9 Gate A passed. The SPRT harness fails closed on
`sprt_max_plies`, and a batch lease checks GUI priority before every pair and
ply. The arena CLI alone runs BelowNormal; locked acquisition isolation remains
byte-preserved. Focused tests pass 13/13; complete-suite attestation v20 passes
386/386 at SHA-256
`DAB696B9128CB249F61E49DED85C134F2439AB21912A42AD8C16BCE80D959135`.
The frozen Gate A contract is `build/nnue_phase9_gate_a_contract.json`, SHA-256
`47E591BAE0E3A29F7A386851EE0ECD242452594E9C19B8ED835850ED8D47DA8E`: seed
`20261101`, `0.2s+0.01s`, H0/H1 `-10/+10`, 256 pairs, Threads=1, Hash=256
MiB, persistent search, eight opening plies, one game at a time, production
tablebases, and max 300 plies. It crossed PASS after 52 pairs / 104 games at
W49 D36 L19, pentanomial `0/8/18/14/12`, LLR
`+2.9921776889755956`, and `+103.1398415563513 +/-52.33548371749529 Elo`.
The result SHA-256 is
`6C6C29C6D430085FF5549741485D5702FE102651B24A0C8738B8061F9AECDEDA`.

Gate B preflight is complete. Atomic checkpointing writes after each complete
color-swapped pair; resume validates exact config/statistics and replays the
same seeded opening stream. Focused tests pass 16/16, the real-DLL one-pair
resume smoke passes, and full-suite attestation v21 passes 389/389 at SHA-256
`9549E7A8E55A3C57713FEE92ADF32770E99574648652FCCC5E9F35A3192DA0AF`.
The completed Gate B used the frozen independent `10s+0.1s`, H0=0/H1=+2
primary SPRT in `build/nnue_phase9_gate_b_contract.json`, SHA-256
`DD56A5709348F6CE88B13EC14A33DFC4A8F36AE4156298962427E28D7C3A7FB8`.
Accepted and candidate identities stay unchanged; no playing promotion exists
yet.

On 2026-09-05 the old exec session `4944` was missing and no arena/GUI process
was alive. The atomic Gate B checkpoint preserved 221 pairs / 442 games at
W207 D153 L82, pentanomial `0/17/91/84/29`, LLR `1.2684715273797915`,
`complete=false`, and `INCONCLUSIVE`. All contract-bound DLL/model/tablebase/
harness hashes, the 153-source/52-test-file v21 inventories, and Python 3.14.0
were revalidated. The unchanged CLI resumed that checkpoint in a hidden
BelowNormal process and completed pair 222. The recovery evidence and logs are
in `build/nnue_gate_b_resume_25690905_122756/RECOVERY.md`. This is a historical
recovery snapshot: inspect that record's PID/start time, process state, logs,
and the canonical result before claiming the arena is still live or resuming.
The interruption cause is unknown; neither a final Gate B verdict nor a
production promotion has been established.

The user-visible read-only Gate B monitor is
`work/nnue_status_terminal.ps1` (PowerShell 7; `-Once` prints one snapshot).
It refreshes every five seconds, uses read/write/delete sharing for atomic
checkpoint reads, validates the arena PID/start time, and shows signed LLR,
distance to PASS, conditional run-trend ETA, errors, and pending Gate C steps.
Its window title is `ThaiMakhos NNUE - LIVE STATUS (read-only)`. Closing this
monitor does not stop the arena. Its default run/PID bindings refer to the
2026-09-05 recovery; update or pass its parameters after a later arena restart.

A float model is trained but is not in the playing path. The final learning
curve has 8/8 runs. Under the frozen validation-loss rule, the KEEP artifact is
`build/nnue_float_v1/size_all_seed_20280002.model.json`, SHA-256
`5FD87ABD2F9CAAC81045A58AEA420445B90CAC9A70D5FFBDFC5694BA1338CA4E`.
Its validation teacher MAE is `0.12098223072290963` versus accepted-HCE
`0.16617580001338003`. Quantized export A/B is now byte-identical at binary
SHA-256 `07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C`;
  all frozen parity/overflow limits pass. The native scalar oracle DLL is
  byte-reproducible at SHA-256
  `2D071F91EC9551FD82EB8793F4E651BD1FA87A9B14C1EA3A6A4B3588B248634C`;
  real-model parity passed 1,152/1,152. The scalar incremental DLL is
  byte-reproducible at SHA-256
  `E455B708423F4B8B8B126263DB7A5F7BD5E7645DDF300114DC07EAB8B01C0CE7`;
  all structured/targeted/clock/random/deep/reload parity gates pass. The
  baseline-x86-64/AVX2-target dense DLL is byte-reproducible at SHA-256
  `EA6B6A1C47671CC1050E9FC861D3BF403E2AD6FCB6D07A7B24BE62E41B8C250A`;
  full parity/capability gates pass, dense evaluation is 4.793x--4.993x faster
  than native scalar, and full suite v12 passed 363/363. The AVX2-update DLL is
  byte-reproducible at SHA-256
  `64C862F3FC2AB99ACFE2AEE04966401E05B48849FF61EAE14A5F5208C5873095`;
  exact update parity passes and it is 4.987x--5.926x faster than scalar by
  delta shape. Full suite v13 passed 373/373. All pre-search inference gates are
  complete, but no search promotion exists yet.

## Runtime history that changes decisions

Windows rebooted three times during acquisition. Atomic source/analysis artifacts
survived, but the process-handle watcher and supervisor did not survive reboot.
After the second reboot, 697 completed analyses, zero stderr bytes, and zero
temporary artifacts were preserved; all bound hashes matched and the locked
supervisor was relaunched. Therefore do not describe orchestration as reboot
persistent. Use the reboot runbook in the skill.

Later the six workers were externally terminated together at 1,734 completed
analyses with exit code `0x40010004`; every worker stderr remained empty. The
705-byte coordinator traceback was hashed and preserved under
`build/nnue_scaling_full_v1/incident_logs/` with an incident record. Locked
source/config/manifest/authorization/DLL hashes still matched, there were no
extra analyses or `.tmp` files, and the run returned to a clean stopped state.
Only the locked supervisor was relaunched, this time as a hidden detached
Windows process with separate launcher logs so task/terminal lifetime does not
own it.

The third reboot occurred at 2026-08-28T09:08:56.5000000Z. A clean stopped
snapshot preserved 2,173/13,802 development analyses, all 15,360 source games,
zero stderr/tmp/extra artifacts, and every locked hash; the health verifier
reported `safe_to_resume_locked_supervisor=true` and no GUI/server was active.
Only the hidden detached locked supervisor was relaunched. Its coordinator
replayed six completed source-generation shards, then restored six BelowNormal
analysis workers on logical CPUs 0/2/4/6/8/10. The first post-recovery health
snapshot with forward progress was `RUNNING_HEALTHY` at 2,177 analyses, with
zero protected reads and training still unauthorized. The recovery record is
`build/nnue_scaling_full_v1/incident_logs/20260828_reboot_090856Z_resume.md`.

The volatile `full_run_supervisor_status.json` previously triggered a Windows
replace race when a monitor held it open. Never poll that file while its writer
is active. Derive live progress from process inventory, analysis filenames,
stderr sizes, temporary artifacts, disk space, and coordinator-owned final
artifacts.

## Prepared final-data verifier

`scratch/nnue_scaling_final_audit.py` and
`tests/test_nnue_scaling_final_audit.py` are prepared but must not be used as a
final PASS before all 13,802 development analyses and the coordinator PASS
summary exist. Their reviewed SHA-256 values are
`7D67882150B6E271292CBAACCE1AFE41827EBEAD5409A0C141B680FF18BADD22`
and `5F3D8066CDB72C2BA46D90686C79F8A5F3BC2F5DDB39EEC3E256763BB186A9D4`.
The focused verifier tests passed 6/6 during development and again after the
plan/skill audit.

The verifier binds all locked inputs, validates the exact development manifest
and coordinator inventories, streams and hashes each analysis from the same
bytes it parses, recomputes position/canonical/phase/king/turn/legal-move
metadata, verifies teacher settings/search rows, checks coverage, and avoids
opening the sealed-test manifest or any test analysis.

After workers are idle: run the verifier twice for byte-identical reproduction,
then run the complete discovered test suite. Its PASS artifact does not itself
authorize a trainer; the trainer contract is a separate gate.

## Safe live health audit (PROMOTED TOOLING)

The read-only monitor `scratch/nnue_scaling_health_audit.py` has SHA-256
`A3B76458174DB59A9226E38A36EB990F32384614C729B2EF194DA6241A7DDEBE`;
its focused test file has SHA-256
`6D349E73E84D367DF7DAF97A4986BC3FE461465C40E2A56346418D8FFC343739`.
Focused tests pass 5/5, including exact process-token classification, clean
stopped/resume state, duplicate-supervisor and extra-analysis/stderr rejection,
and a guard that fails if the monitor opens an analysis payload, sealed-test
manifest, or volatile supervisor status.

The recovery baseline snapshot reported `RUNNING_HEALTHY` at 1,768/13,802
development analyses. Later live snapshots reached 1,901/13,802, followed by
a final validation snapshot at 1,917/13,802 with completed shard counts
315/325/323/300/318/320, one supervisor, one
coordinator, six analysis workers, zero unknown processes, zero new stderr
bytes, zero temporary artifacts, no extra analyses, and about 407 GiB free.
The coordinator and all workers were BelowNormal; worker affinities were
exactly 0/2/4/6/8/10. Both snapshots verified the accepted/full-run/development/
sealed-commitment hashes and reported zero analysis-payload, test-analysis,
sealed-manifest, and volatile-status reads.

This snapshot is dynamic, non-gating evidence. It proves one healthy instant,
not full acquisition completion by itself. The observed sequence
725 -> 729 -> 734 and the later 1,734 -> 1,768 increase with six analysis
workers after external process-loss recovery prove the resume path is operating.
Continue the locked supervisor and use the final-data verifier only after all
development analyses exist.

## Prepared full-suite attestation runner (PROMOTED TOOLING)

`scratch/nnue_full_suite_attestation.py` has SHA-256
`4109D973F7200A3EC61ABC262F93CC3820D1B3F59B1EA2F34F8CDE21690AADB9`;
its focused test file has SHA-256
`B1C255946AE68822BDE10ECCF5F7C1782C478435A996884F42CCE0E9033DC653`.
Focused tests pass 11/11. Before the feature-oracle addition the complete
focused gate stack passed 41/41 in 4.232 seconds; the preflight-freezer
checkpoint stack was 63/63 after adding the executable feature oracle and
contract-freezer tests. The latest 70/70 stack is recorded below.

The v2 runner refuses active/incomplete acquisition, active GUI priority, lock
contention, output inside acquisition/source/test trees, incomplete discovery,
failed tests, source/test drift, accepted/final-audit drift, and protected
production-data opens. It owns all 32 workload slots, probes GUI priority around
every test, binds the exact source/test inventories measured at its run (the
118-source/43-test checkpoint before the preflight addition) plus its own/result
hashes, and writes no artifact unless every condition passes. The
trainer gate independently recomputes those inventories and rejects stale or
forged evidence.

This is tooling promotion only. The real complete suite was deliberately not
run while acquisition is active, and no attestation exists yet.

## Prepared trainer-contract authorization gate (PROMOTED TOOLING)

The fail-closed tool `scratch/nnue_trainer_contract_gate.py` has SHA-256
`FB99AE3DC546D4B3FC1B4E1CFDD6025439FA4C2A72787E43460FD968D4FBBA31`;
its focused test file has SHA-256
`B3B4977926F7CC8B2E6B5E66182179646E474033D47DC08F960C057E611F386D`.
Focused tests pass 10/10; at the freezer checkpoint the complete focused gate
stack passed 63/63 in 4.139 seconds on the final rerun (the freezer experiment
run was 4.355 seconds). The latest stack including the preflight is recorded
below.

At this historical preparation checkpoint, the tool was not yet executable as
a real authorization. It required
two byte-identical final-data audits, two byte-identical frozen contracts, the
exact development manifest, train/validation inventories that reconstruct the
audited analysis-set hash, a v2 full-suite PASS bound to current source/test
inventories while workers were idle, and a
tiny-fixture preflight proving overfit, deterministic repeat/resume, checkpoint
checksum, and sealed-test guards. It never opens analysis payloads or the sealed
test. At that checkpoint no production contract, real trainer preflight,
authorization artifact, or model existed. Those statements are superseded by
the completed evidence in the authoritative phase at the top of this file.

## Prepared trainer-input inventory builder (PROMOTED TOOLING)

`scratch/nnue_trainer_input_inventory.py` has SHA-256
`B33B7ACACB0F5C0F5374B27D7289A6061CF40C77F969F93552CB34E0B8330C5E`;
its focused test file has SHA-256
`1932F769B6AB7406E2E7CFA5E97FECA296424305F60072A06FBC51C673AFF211`.
Focused tests pass 9/9; at the preflight-freezer checkpoint the complete
focused gate stack passed 63/63 in 4.139 seconds on the final rerun.

The builder can run only after a real final-audit PASS and coordinator PASS. It
maps every locked development game to the coordinator-verified analysis hash,
creates exact disjoint train/validation inventories in deterministic game-id
order, reconstructs the final audit's analysis-set SHA-256, preflights both
locked outputs, and rejects outputs inside the acquisition directory. It reads
no analysis payload or sealed-test file and does not authorize training. No real
inventory was generated from the active partial acquisition.

## Deterministic trainer-contract freezer (PROMOTED TOOLING)

The freezer `scratch/nnue_trainer_contract_freezer.py` has SHA-256
`B0E26673291AB92882CE48051F9C487E244E33EB64FE5A9B744A2ECEEB721273`;
its focused tests have SHA-256
`3F8F0D841E19E9E4420195A243E4215B0690FD25DBC822F19FD8EAD286FDD17F`.
Focused freezer tests pass 10/10; at the freezer checkpoint the complete
low-resource stack passed 63/63 in 4.139 seconds on the final rerun (4.355
seconds in the experiment run). The latest stack including preflight is
recorded below.

It assembles a frozen v1 contract from explicit post-gate evidence and
train-only choices, injects the executable feature/network/sealed-test and
authorization policies, deep-copies inputs, rejects incomplete/extra/leaky
fields, and writes canonical LF byte-locked JSON only outside source and
acquisition trees. It does not read analysis payloads or sealed-test data and
does not authorize training; the existing fail-closed trainer gate remains the
authority. No production contract, trainer, model, or playing code exists.

At the freezer checkpoint (before the preflight tooling), the discovered
inventory was 118 source files and 43 test files. Its historical inventory
hashes were
`B0F9A0EE4A174160E03958EC9E511DCE2D782C8159A3BBBAD59BECB9A0AA34DC` and
`1170853627E8DE3ADE9FE390E79C3B6E46293B9F8DA7BDA7EA2EF795EF442EC0`.

## Deterministic tiny-fixture trainer preflight (PROMOTED TOOLING)

The preflight harness `scratch/nnue_trainer_preflight.py` has SHA-256
`157BF19A3E77D760F3B9B94D747F9CC314C55481A714A245ABE04A2C43019CF2`;
its focused tests have SHA-256
`7432CACD5FC9C6DBE1BCB7E458DF6873CA5550C4BB990E78C9C1007AB156A411`.
The seven preflight tests pass 7/7, including a direct-file CLI smoke that
verifies repo-root imports; the complete low-resource NNUE gate stack passes
70/70 in 4.766 seconds on the latest rerun.

The harness uses only an explicit synthetic linear fixture and the frozen
contract/audit/source identities. It proves a tiny model can overfit, that two
identical runs and checkpoint resumes are byte-identical, that checkpoint
serialization has a non-tautological checksum round-trip, and that protected
production/sealed/status paths are rejected. It reads zero production analysis
payloads, test analyses, sealed-test manifest, or volatile supervisor status;
fixture weights are discarded and the emitted result cannot authorize training.
The real preflight remains gated on acquisition completion, two reproducing
final audits, an idle full-suite attestation, exact train/validation inventories,
and a real frozen trainer contract.

The current discovered inventory is now 120 source files and 44 test files,
with inventory hashes
`A069013B5ABAD25F2D4935E394BE804573A3E0C24E1BB4A06C27AA54A3259B65` and
`007A14891C6592AA0DA49F1E6BE16980248BD80E7970969738E5C6346B655437`.
The latest reviewed read-only health snapshot (2026-08-28T12:59:55Z) reports
`RUNNING_HEALTHY`, 2,177/13,802 development analyses (11,625 remaining), shard
counts 358/369/370/347/365/368,
roles coordinator=1, supervisor=1, worker=6, unknown=0, zero stderr bytes,
zero temporary/extra analysis artifacts, and zero protected reads; 51 stderr
files are present but empty. Training remains unauthorized.

## Executable NNUE v1 feature oracle (PROMOTED TOOLING)

The pure ABI oracle `makhos/nnue_features.py` defines the locked
`thai-makhos-shared-137-v1` sparse feature mapping and is deliberately not
imported by the playing path. Its SHA-256 is
`EAEB36EDBF09476F36958AAD7C78ED28B02A2B5EE178622D44BC331ABE30A30E`;
`tests/test_nnue_features.py` is
`F57B620F6B5407F2EA6BD0E388B521673BFF2DB61E2273235078A8A08B498A2B`.
The trainer-contract gate now single-sources its feature payload from the
oracle and has SHA-256
`DF502CFADDC6B220E141AD1350D838FB62D3A26DFE1D039A93EB2E7D4D1D35C8`.

The focused oracle suite covers exact contract indices, both-perspective
rotation/color-swap symmetry, all 80 legal clock values and terminal rejection,
quiet/capture/promotion/multi-capture deltas, clock-boundary behavior, and 300
random legal parent/child transitions. Before the preflight addition, the
combined low-resource stack passed 63/63 in 4.139 seconds on the final rerun.
The historical source/test inventory at that checkpoint was 118/43 with
inventory hashes
`B0F9A0EE4A174160E03958EC9E511DCE2D782C8159A3BBBAD59BECB9A0AA34DC` and
`1170853627E8DE3ADE9FE390E79C3B6E46293B9F8DA7BDA7EA2EF795EF442EC0`.

At this historical feature-oracle checkpoint no model had been trained and no
native inference or playing code had changed. The current scalar and future
incremental/AVX2 implementations must still reproduce this oracle exactly
before any candidate is allowed to touch the playing path.

## Documents

- `DEVELOPMENT_PLAN_TH.md`: canonical forward plan and phase gates.
- `NNUE_ROADMAP.md`: locked v1 model/data/inference design and acquisition record.
- `experiment-evidence-ledger.md`: full historical experiment ledger;
  its old “next experiment” statements are non-authoritative.
- `NATIVE_ROOT_PVS_SMP_ROADMAP_TH.md`: rejected playing-path architecture record.
- `PROOF_ROADMAP.md`: deferred proof/tablebase path.
