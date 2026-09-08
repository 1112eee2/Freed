# Current ThaiMakhosEngine state

Reviewed: 2026-09-08. This is the single current-state routing record, not a
live counter. Check atomic result files, run manifest and process identity.

## Current gate and next action

**Gate C and Production Promotion are both complete and verified.**
- Gate C 1000ms: 546 pairs / 1,092 games | W 472 D 396 L 224 | LLR +2.945906 | Elo vs HCE +80.3 +/- 13.5
- Gate C 2000ms: 554 pairs / 1,108 games | W 477 D 404 L 227 | LLR +2.946336 | Elo vs HCE +79.8 +/- 12.9
- NNUE v1 Promotion: **PROMOTED AS DEFAULT GUI ENGINE**
  - Release ID: `nnue-v1-20260908`
  - Active pointer: `config/gui_release.json` (Profile: `nnue`)
  - Manifest: `releases/nnue-v1-20260908/manifest.json`
  - Attestation: `releases/nnue-v1-20260908/promotion_attestation.json` (Revision 2 errata: corrected promoted_git_head to full SHA `2cec9f480c3e91aedbee18ba043dc81bff9dca33`).
  - Verification: 403 Python tests (100% OK), 3 Node.js lifecycle tests (100% OK), HTTP production smoke passed.
  - Reversible rollback preserved: `--release-profile hce`.

**Phase 4 (NNUE Thread-Scaling Audit) is COMPLETE.**
- 5,760 observations collected and verified: `build/nnue_thread_scaling_measured_v1/observations.jsonl` (SHA-256: `254FB1C685E458F7C43DCCE4C4DBB1518874FA79BC319E85BC9554689EF4384F`).
- Authoritative analytical report: `build/nnue_thread_scaling_measured_v1/report.json` (SHA-256: `5F19083ADE11DD9E76C9B1AC90102376328B988D1D1DF5722B20856BF477757E`).
- Limitations noted: Offline diagnostic benchmark, not complete production profile (`profile_coverage_complete=false`, `strength_evidence=false`). Forced move latency (1.0ms, score=0) was hardcoded in collector; tablebase checked size/checksum without Engine oracle; unmeasured telemetry is null.
- Key findings:
  1. Node speedup vs 1T: 2T=1.46x, 4T=2.13x, 6T=2.45x, 8T=2.79x, 12T=2.97x (at 2000ms).
  2. Diminishing returns from 6T to 12T: +21.3% nodes for 2x threads due to SMT hardware resource sharing on 6 physical cores.
  3. Root-split branch starvation: 31/96 positions have <= 6 moves; idle threads explain low CPU utilization (3.93x out of 12T).
  4. Synchronization barrier: All root moves must complete depth D-1 before depth D is accepted, causing lower reported completed depth (18-20 vs 22-23 on 1T) despite 3x higher total nodes.

**Next action:** Phase 5 — Experiment A (Direct 6T vs 12T Superiority SPRT).
- Manifest: `build/nnue_sprt_6t_vs_12t/manifest.json`.
- Arena pilot passed: verified dual NNUE models, tablebase routing, and result checkpointing.
- Launch 1000ms control (`seed 20261108`, `parallel-games=1`), followed by 2000ms control (`seed 20261109`).

The monitor reads append-only stdout while the arena is alive and recomputes
exact paired statistics; it never opens the active checkpoint. It reads the
canonical result only after the writer stops. An injected replacement test
showed that FileShare.Delete alone did not protect an open destination on this
host; JSON handles now close before parsing, and pointer publication retries
bounded permission denial. The regression suite guards zero live-checkpoint reads.

The process manifest records PID plus Windows creation ticks, command, cwd,
logs and contract identity. The display follows the pointer, not a hardcoded
PID. It shows both gates, last pair time, LLR and failures without an ETA or
completion percentage. Unknown failures require incident review; no blind
automatic restart. A user GUI session retains absolute resource priority.

During the arena, only isolated docs/fixtures/low-resource tooling may run.
Preserve the frozen playing-source/test inventory. Do not build native code,
train, run a full suite, profile, or start another match concurrently.

After complete 2000ms PASS, enter production smoke/reversible promotion review.
A FAIL or cap-INCONCLUSIVE does not promote or authorize new seeds. Do not
resume completed Gate A/B/1000ms, pool time controls, or alter the frozen model.

## Immutable result and artifact identities

### GitHub checkout verification (2026-09-07)

The original Windows host's current 2000ms state cannot be established from
the repository alone. Use `python -B work/nnue_gate_c_control.py preflight`
for local prerequisites before host verification. It does not read result
payloads, inspect remote processes, run search, or authorize promotion; exit 2
means prerequisites are blocked. Missing local results never mean NOT_STARTED.

This checkout lacks the candidate DLL, tablebases, bound smoke/suite evidence,
Gate C results and active manifest. Accepted DLL/model hashes match. The Git
contract has LF bytes, while its frozen SHA binds CRLF; preflight diagnoses the
exact CRLF reconstruction without rewriting or accepting the checkout. Restore
the original immutable artifacts on the original host and verify their exact
identities before considering any resume. Do not change frozen hashes to fit
a checkout or replace missing evidence with a new run.

Lifecycle validation now rejects unrealizable W/D/L versus pentanomial totals,
invalid consecutive pair deltas in the observed log tail, and resume at the
declared cap even before final checkpoint publication. Focused tooling tests
are separate from the frozen suite. The Linux full-suite attempt is not a PASS
attestation; see the latest evidence-ledger entry for its measured limitations.

| Artifact | SHA-256 |
|---|---|
| Accepted HCE `build/makhos_native_accepted.dll` | `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD` |
| Frozen NNUE `build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll` | `32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79` |
| Model `build/nnue_quantized_v1/model_a.mknnue` | `07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C` |
| Gate B `build/nnue_phase9_gate_b_seed20261102.json` | `1D439C7E96E189377D9865FA03AABD08D89611F7C903F3BB5B31C714853EAAB3` |
| Gate C contract `build/nnue_gate_c_contract_v1.json` | `5B727707FBED8D5E9D79AE89159D9DF1EAF5C74D8AFE31A654F3CDC191F6A3F7` |
| Gate C 1000ms `build/nnue_gate_c_1000ms_seed20261105.json` | `41E78EF359BB9BA6E1CDF189FCD15B56D1D9ED36E2CCD684D4F96D0C8AFE94D8` |
| Full suite v23 `build/nnue_phase1_evidence/full_suite_attestation_v23.json` | `D8C9F06E528D9A710D3C08360B00A63DC8D6C634AE4E2BA09202F53367A0F19D` |

Gate B PASS: 550 pairs/1100 games, W498 D395 L207, buckets 4/47/230/192/77,
LLR 2.945863242736825, reported +94.1514 +/-13.4705 Elo, at 1T/256 MiB,
10s+0.1s. Gate C 1000ms PASS: 546 pairs/1092 games, W472 D396 L224,
buckets 2/65/233/175/71, LLR 2.945906196582963, reported
+80.3049 +/-13.4723 Elo, at 12T/512 MiB, fixed 1000ms. Both are versus
accepted HCE under their own conditions, not external or SMP-scaling proof.
Statistics were recomputed; final 1000ms stderr was zero.

The frozen v22 source/test inventory hashes remain unchanged:
`E8F223128CA34BAFD7AF5E3E93F58D56777D0647A1D279B7C13A3BF20DC383A0` /
`FE123C50E916829F8AA735E4862E726595F89BB8AE03BEF47403B2FFF1E8281B`.
Fresh v23 full suite passed 393/393, zero failures/errors/skips while idle.
New lifecycle tools live in `work/`, outside that frozen inventory; their
focused tests are separate evidence, not an increased discovered-suite count.

## Boundaries and next development milestone

GUI default is now NNUE v1 (Release ID `nnue-v1-20260908`), actively bound via
`config/gui_release.json`. Verified runtime provenance shows `NNUE v1 ·
native-root-split · 12T · TT 480/512 MiB`. Reversible rollback to baseline HCE is
preserved via `--release-profile hce`. Full Python test suite (403 tests) and
Node.js lifecycle suite (3 tests) pass 100%.

Acquisition, training, quantization, native scalar/incremental/AVX2 parity,
search pre-game gates, Gate C SPRT verification, and production promotion review
are complete.

The active experiment is the Phase 4 NNUE 1/2/4/6/8/12-thread scaling/profile audit
at 1s/2s and total Hash 512 MiB, 96 diverse positions, 5 balanced repetitions
(5,760 observations total) collected natively via `work/nnue_thread_audit_collect.py`
and summarized via `work/nnue_thread_audit_report.py`. Optimize the strongest
measured configuration on the 6-physical-core/12-logical-thread host; do not force 12 threads.

`work/nnue_ancestor_delta_v1` is staged only, uncompiled/unprofiled/unproven.
Select it only if post-NNUE thread-audit profiling identifies NNUE accumulator as the primary bottleneck.

## Reference routing

- [Forward plan](../../../../DEVELOPMENT_PLAN_TH.md): full approved sequence,
  production/rollback, scaling, Elo queue and future NNUE acceptance.
- [NNUE contracts](../../../../NNUE_ROADMAP.md): feature/model/data semantics.
- [Evidence ledger](experiment-evidence-ledger.md): mechanism and verdict lookup.
- [Prior current-state snapshot](history/20260907-current-state-before.md):
  historical acquisition/oracle/arena recovery evidence only.
- `NATIVE_ROOT_PVS_SMP_ROADMAP_TH.md`: rejected playing-bound architecture.
- DFPN and tablebase >6 remain deferred; no builders are authorized here.
