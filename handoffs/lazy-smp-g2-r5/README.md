# Lazy SMP G2 r5 frozen publication-protocol bundle

This bundle implements the reviewed r5 contract. It keeps the r3/r4 bundles and
evidence unchanged and reuses their frozen production `SharedMoveHintEntry`,
`NativeCompactMove`, `shared_move_hint_write`, and `shared_move_hint_read` verbatim.
It does not use top-level Local WIP native sources.

The harness separates three slots: deterministic preflight, bounded 256-publication
SPSC liveness, and 8-writer/4-reader concurrent safety/coverage. Production atomics
are not instrumented or altered. Per-participant counters are owner-only non-atomic
records aggregated after join.

## Verify and run

Always run `python3 verify_snapshot.py` before and after collection.

Windows readiness (GCC C17 pthread; not a TSan substitute):

```
python collect.py <unique-result-id> --lane windows --compiler <gcc-path>
```

Linux TSan acceptance matrix (Clang 18 and GCC 13, five fresh protocol processes
per compiler):

```
python3 collect.py <unique-result-id> --lane linux-tsan
```

The collector records every predeclared process slot. A failed or incomplete process
does not cause replacement/retry and does not remove later slots. A shared input or
runtime blocker produces explicit NOT_RUN entries for every remaining slot. Compile
errors on an otherwise supported toolchain are FAIL; missing compiler/sanitizer
runtime is NOT_RUN. A protocol timeout after launch is FAIL.

Do not commit binaries. Return raw logs, commands, environment, hashes, exit codes,
elapsed times, and result JSON under `results/<unique-result-id>/`. Windows evidence
is readiness only. G2 remains NOT_PASSED until the complete Linux matrix is reviewed.
No result from this bundle authorizes production changes, merge/promotion, or SPRT.
