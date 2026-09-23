# PR #25 review and frozen r5 Linux evidence

Decision: **CHANGES_REQUIRED / DO_NOT_MERGE** for PR #25 head `7cca706377f5e963431fc0f251b91add8673a136`.

The authorized validation loop advanced from source review to one complete Linux r5 matrix. Its result is **INCOMPLETE_COVERAGE**, not PASS and not a TSan environment blocker. G2 stays **NOT_PASSED**. The old candidate stays **REJECT_FOR_PERFORMANCE / NOT_PROMOTED**.

## Inputs and scope

- PR #25 targets main `a0f79645d9803680a6aa42ae910d49dee1d89f52`, with 100 changed files. Reviewed: publication/ordering integration, Python handle lifetime, C ABI, pilot code, gate documentation and source/evidence identities. This is not a full independent audit of every unrelated tooling/game-analysis change.
- PR #24 frozen r5: `0ced9eb2759ccd0dbe2541b07b0609301c80e317`; implementation follows design `8f575a568fd258aa98c9bf918528f75a2bd7753f`.
- PR #25 root `native/makhos_native.c` SHA-256 `4b4362e3e9af2cfc2d2f56bfb0deb124d20cfb3001663f930e18f9c76df9770f` and `native/makhos_types.h` SHA-256 `c088056972a2f73bfbb9c111a777aa32bdc1bc493d5ae41fa7534dbd300077bf` match the frozen r5 source files exactly. Both publication functions and both types also match verbatim.
- No production source, atomics, memory ordering, frozen r3/r4/r5 inputs, existing logs, rules/core, accepted DLL/profile, model or checkpoints were edited. No binaries/tablebases are included.

## Findings requiring action

### F1 — P1: enlarged stats output has no ABI protection for old callers

At PR #25, `MakhosLazySmpStats` gained three uint64 fields; `makhos_lazy_smp_stats` still performs `*output = lazy->stats` with no caller-size argument. The base Python `_LazySmpStats` is 176 bytes under the project's x64 layout; the new structure is 200 bytes. `makhos_search_abi_version` is unchanged (4/5/6 depending on build flags).

An old wrapper loading a newly built candidate can therefore pass its existing ABI check and receive a 200-byte write into a 176-byte output buffer. This is an ABI-level 24-byte overrun scenario, derived from the compared declarations and assignment; no Windows DLL crash is claimed to have been reproduced here.

Sources: [new C output API](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/native/makhos_native.c#L6490), [unchanged version](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/native/makhos_native.c#L5324), [base caller layout](https://github.com/1112eee2/ThaiMakhosEngine/blob/a0f79645d9803680a6aa42ae910d49dee1d89f52/makhos/native.py#L127).

Before adopting this API, preserve the legacy-size writer and add a versioned/sized stats entrypoint, or explicitly reject incompatible clients before the call. Require a mixed-version canary regression; testing only a matched new wrapper/new DLL cannot detect this.

### F2 — P1: the advertised ON/OFF pilot does not establish effective hint state

`run_lazy_smp_hints_ab_pilot.py` changes `os.environ` between calls inside one Python process; native create samples C `getenv`. The same PR's current-state already records this Windows CRT environment problem and requires separate processes with the environment set before DLL load.

The committed pilot has identical shared-table allocation in both modes, but that is intentional even with hints disabled, so allocation telemetry cannot verify the switch. It also lacks DLL/model/source hashes and effective-hint telemetry. Its six single observations cannot replace the newer, separately recorded G4 rejection.

Source: [pilot mode switching](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/tools/benchmarks/run_lazy_smp_hints_ab_pilot.py#L36), [native toggle/allocation](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/native/makhos_native.c#L6052).

Preserve this JSON as historical diagnostic evidence; withdraw the causal ON/OFF claim. If a genuinely new performance experiment is authorized later, use child-process environment before DLL load, effective configuration verification and full provenance. Do not rerun this rejected mechanism or start SPRT merely to refresh this pilot.

### F3 — P2: close/stop can miss a search entering the native call

The two locks protect handle destruction from concurrent `stop()`; this is a useful lifetime improvement. However `close()` sends stop once **before** acquiring `_search_lock`, and marks `_closed` only after destruction. A search that has acquired the search lock but not yet entered C can have that stop overwritten by `makhos_lazy_smp_run` resetting `control.stop=false`. A queued search can similarly enter before close wins the lock. Close can then wait for the full search (potentially an untimed depth-limited search).

This is a source-derived cancellation/admission counterexample, not a claim of a demonstrated use-after-free. The existing `test_stop_concurrent_with_close` creates an idle handle and never calls search; the active cancellation test waits 60 ms and does not cover the entry gap.

Sources: [close admission](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/makhos/native.py#L1754), [native stop reset](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/native/makhos_native.c#L6273), [idle stress](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/tests/test_native_lazy_smp.py#L574).

Define closing/admission semantics and add a deterministic regression for close between Python admission and native activation, plus queued-search/close coverage. Do not hold the lifecycle lock for the entire search, which would prevent external stop. Any cancellation fix is separate from frozen publication atomics and requires its own Windows verification.

### F4 — P2: canonical protocol/gate prose contradicts the implementation and current evidence

The canonical design calls P0-A CLOSED/VERIFIED using `tests/native_protocol_test.c`, yet that test has a separately maintained `SharedTTEntry` implementation (no epoch validation or production exhaustion guard). The design still describes relaxed payload / acquire-release sequence operations while the actual frozen implementation uses seq_cst throughout.

The PR description also calls G4 a paired-SPRT gate; the maintained gate table uses G4 for runtime/scaling and G5 for strength. Its "all six requirements validated" presentation omits the retained performance rejection and open G2 coverage.

Source: [canonical design](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/docs/architecture/NATIVE_SHARED_TT_LAZY_SMP_DESIGN_TH.md#L129), [independent old protocol test](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/tests/native_protocol_test.c#L36).

Correct maintained prose and PR summary, with links to immutable old evidence. Do not rewrite frozen results or interpret a G2 diagnostic as reauthorization of the old candidate.

## Positive findings with limited scope

- Shared publications contain move/depth/epoch only; the shared hint is used in ordering, not a shared score/bound cutoff.
- Thread 0 supplies the returned search result; helpers are drained before aggregation in the reviewed normal path.
- 1T bypass, total TT budgeting and 32-bit request-epoch exhaustion handling are present in source.
- Handle lifetime locks prevent the direct stop/destroy overlap in the reviewed Python wrapper.
- These source observations do not independently reproduce the claimed Windows timings, broad G1/G3 test attestations or G6 behavior.

## Executed Linux r5 matrix

[Actions run 35870928227, attempt 1](https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/35870928227), execution commit `3be0dc96505571f0d7d08c2f20d923dd2721d925`.
Ubuntu 24.04, 2 vCPU, kernel 6.17.0-1022-azure, glibc 2.39, Clang 18.1.3 and GCC 13.3.0. GCC dynamically links installed libtsan2 14.2.0; package versions and runtime SHA-256 are recorded, not inferred from compiler major version.

| Lane | Smoke | Known-racy control | Protocol processes | SPSC |
|---|---|---|---|---|
| Clang 18 | clean | actual data-race report; exit 66 | 5/5 INCOMPLETE_COVERAGE | 256 distinct + ack each |
| GCC 13 | clean | actual data-race report; exit 66 | 5/5 INCOMPLETE_COVERAGE | 256 distinct + ack each |

All 10 protocol processes exited 3 without timeout. Their stderr files are empty. No payload failure or protocol TSan race report was observed. There were 1245 accepted reads across the stress phases; three processes accepted zero stress reads, and every process had zero-progress participants. SPSC observations must not be substituted for concurrent coverage.

The frozen Windows result remains directed PASS, four protocol PASS, one INCOMPLETE_COVERAGE. The Linux collector invokes protocol mode only; this run does not invent a Linux directed-mode PASS or add unplanned gate processes.

Both snapshot verifiers passed. All tracked files remained unchanged during execution. All 82 recovered text files match their transport SHA-256; the collector's 51-entry evidence manifest and wrapper's 29-entry manifest both verify. Original result/commands/logs/manifests are committed unchanged; supplemental review is separate.

- [Frozen result](../lazy-smp-g2-r5/results/linux-35870928227-1/result.json)
- [Frozen commands and all raw logs](../lazy-smp-g2-r5/results/linux-35870928227-1/)
- [Environment/runtime/integrity evidence](results/linux-35870928227-1/)
- [Machine-readable reviewed summary](reviewed_result.json)

## Next loop boundary

The predeclared r5 run is complete. Do not retry it until it passes, lower coverage, or patch its frozen inputs. The working TSan runtime eliminates the earlier environment blocker; the remaining issue is coverage and harness failure handling.

See [NEXT_ACTION.md](NEXT_ACTION.md) for a concrete next-revision proposal to review before changing acceptance workload. PR #25 remains unmerged; no production changes or SPRT were performed. Safe-baseline game diagnosis can continue independently under the existing GUI/workload rules, but this Linux gate is not new playing-strength evidence.
