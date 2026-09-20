# Reviewed seed diagnostic: confirmed initialization defect

Status: **CONFIRMED_HARNESS_INITIALIZATION_DEFECT**, limited to the deterministic counterexample below.
G2 remains **NOT_PASSED**. The old Lazy SMP candidate remains **REJECT_FOR_PERFORMANCE / NOT_PROMOTED** per the user's instruction.

## Provenance and execution

- PR base: `codex/astra-g2-r4-pthread-handoff`, commit `117c22aa3cf47d1175e1758c70f9af1ab8daa709`.
- Frozen r4: [117c22a](https://github.com/1112eee2/ThaiMakhosEngine/tree/117c22aa3cf47d1175e1758c70f9af1ab8daa709/handoffs/lazy-smp-g2-r4).
- Prior TSan evidence reviewed at `4c566c9cac6117061285eed8d42765e4da8da7cb`.
- Prior measurement/addendum reviewed at `757847a9583824c32265efd4ce0b19dc3c78fc08`.
- Executed diagnostic source: `d499a2d9a6cfe7e2b6ebb6de15fb9fb01a2bbd69`.
- [GitHub Actions run 35458339798, attempt 1](https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/35458339798), job `105937525409`.
- Ubuntu 24.04.5 x86-64; Clang 18.1.3; GCC 13.3.0; glibc 2.39-0ubuntu8.8.
- Plain C17 `-O1 -g -pthread`; **no sanitizer**, no worker creation, no timing-dependent interleaving.
- Exactly 12 planned fresh processes: r3/r4 × Clang/GCC × three modes. Each limit 10 seconds; compile limit 60 seconds; job limit 8 minutes. No retry and no timeout occurred.
- [result.json](results/35458339798-1/result.json), [commands with exits/timing](results/35458339798-1/commands.json), [all raw logs](results/35458339798-1/).
- All 75 files listed in [evidence_sha256.json](results/35458339798-1/evidence_sha256.json) were rehashed after GitHub log retrieval and matched. The manifest itself is SHA-256 `c831baf92b1119a2fb2b951497e3ceea76680a596e65e1c71f3ef69fc3367c3b`.
- Before/after snapshot verifiers passed for both r3 and r4. All 209 tracked protected inputs inventoried by the collector retained identical hashes; tracked-file diff was empty.
- This run is not a new negative-control or TSan gate run; existing pthread TSan calibration is historical evidence only.

## Confirmed mechanism

The pre-thread setup is extracted verbatim from the frozen main functions and is identical in r3/r4. The diagnostic includes each unchanged frozen probe, including its production-extracted types/functions and original reader/assertions. It does not compile the repository-root native engine.

Main publishes `{1,2,3,4}` under key 123 / epoch 7 / depth 0 during preflight. Later it resets only sequence to zero. The read protocol accepts an even stable sequence of zero; it does not treat that value as an invalid slot. Consequently the workload's same-key/same-epoch reader can legally accept the old coherent seed before any writer publishes a workload tuple.

| Observed field before any workers | Value |
|---|---|
| Read hit | true |
| Sequence before / after | 0 / 0 |
| Key / epoch / depth / flags | 123 / 7 / 0 / 0 |
| Data | `0000000700000000` |
| w0 | `0000000000000001` |
| w1 | `0000000000000002` |
| w2 | `0000000400000003` |
| Decoded move | `{1,2,3,4}` |
| Payload/depth workload predicates | all four false |

These words exactly match the seed, not a mixed publication. The no-writer condition makes the surrounding sequence/raw-slot observations unambiguous for this experiment. It would not make a later resnapshot sufficient evidence under concurrent writes.

## Complete matrix

| Frozen source / compiler | Seed snapshot | Unchanged reader on seed | Valid-publication control |
|---|---|---|---|
| r3 / Clang | exit 0; exact tuple | SIGABRT (-6), payload assertion | exit 0; 100000 accepted |
| r3 / GCC | exit 0; exact tuple | SIGABRT (-6), payload assertion | exit 0; 100000 accepted |
| r4 / Clang | exit 0; exact tuple | SIGABRT (-6), payload assertion | exit 0; 100000 accepted |
| r4 / GCC | exit 0; exact tuple | SIGABRT (-6), payload assertion | exit 0; 100000 accepted |

All four abort logs identify the original `move.captured_low == ~move.path_low` assertion (r3 line 114; r4 line 125). Classification uses both the seed observation and assertion text, not exit code alone.

The separate valid control writes a workload-valid tuple using the unchanged publication function. Sequence becomes 2, depth becomes 42, all four predicates hold, and the unchanged reader completes its 100000 iterations. Wrong-key and wrong-epoch controls miss in every case. No assertion was removed, bypassed with NDEBUG, or weakened.

## Confirmed / not established

**Confirmed**

- Frozen r3/r4 preflight leaves a seed incompatible with concurrent workload assertions.
- The same payload assertion can fail deterministically without concurrency or a sanitizer.
- An assertion failure alone therefore does not establish a production publication defect or torn read.
- The old GCC TSan run 01 already contains the payload assertion; the later addendum's statement that the original gate could not surface it is contradicted by its raw log.
- The prior result list contains 10 sanitized plus 2 plain attempts; one GCC sanitized attempt passed. This is neither zero individual passes nor a 1-of-6 denominator, and still does not meet the five-clean-process gate.

**Still unknown**

- Which historical concurrent failures observed the seed versus another cause: the original logs did not capture each failing read's tuple/sequence.
- Whether any independent publication defect exists. This counterexample neither proves nor disproves general publication safety.
- The detailed scheduling/progress cause of every `accepted==0` result; this experiment is not a concurrent liveness measurement.
- Windows lifecycle safety and G2-G6 acceptance. No gate is closed here.

The old logs, reviewed_result and addendum are not edited or retroactively reclassified. The corrections above are a separate review of their claims.

## Next action: review a new harness revision before implementation

The [revision proposal](README.md#proposed-next-revision-design-only-not-implemented) separates:

1. **Initialization:** separate preflight and workload slots; the workload starts in an explicitly nonmatching namespace, initialized only while quiescent. Retain this counterexample as a regression.
2. **Safety:** keep every payload/depth assertion; validate accepted tuples against the declared writer encoding; retain directed protocol tests. Log accepted locals and contemporaneous read sequence through a reviewed mechanism, then still fail on invalid data. Do not infer original coherence from a later slot reread.
3. **Liveness/coverage:** use a bounded single-writer/single-reader handshake as a separate progress test. The concurrent stress case records accepted/rejected reads and successful/skipped writes; zero accepted is INCOMPLETE_COVERAGE, never PASS. Predeclare participant and coverage requirements, without retry-until-pass.
4. **New frozen gate:** only after approval, freeze the new harness and run a calibrated pthread negative control plus all five predeclared TSan processes, preserving every result and raw log.

This PR implements only diagnosis, not the proposed acceptance revision. No production atomics/memory ordering, rules, core, DLL, profile, checkpoints, binaries or tablebases are changed/uploaded. No merge, promotion or SPRT.

## Changed paths and complexity

All changes relative to the explicit base are additive:

- `.github/workflows/lazy-smp-seed-diagnostic.yml`: one branch-scoped, bounded diagnostic workflow.
- `handoffs/lazy-smp-seed-diagnostic-v1/reproduce.c`: isolated deterministic reproduction.
- `handoffs/lazy-smp-seed-diagnostic-v1/collect.py`: command/evidence collector.
- `handoffs/lazy-smp-seed-diagnostic-v1/README.md`: design, scope and proposed revision.
- `handoffs/lazy-smp-seed-diagnostic-v1/REPORT.md`: this reviewed conclusion.
- `handoffs/lazy-smp-seed-diagnostic-v1/results/35458339798-1/*`: all 76 runner-produced text evidence files plus separate GitHub retrieval provenance.

No production entrypoint, feature flag, backend, state owner, ABI or engine dependency was added. The project skill's complexity/evidence rules kept this work outside the engine and prevented using diagnostic success as an acceptance gate.
