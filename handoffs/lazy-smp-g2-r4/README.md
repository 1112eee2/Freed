# Astra Web: Linux ThreadSanitizer handoff (r4 pthread)

This is a **separate versioned r4 handoff**. The r3 handoff (`handoffs/lazy-smp-g2-r3/`),
PR #18 and its NOT_RUN evidence directory remain byte-for-byte frozen and are **not**
superseded or reinterpreted by this bundle. Never transfer r3 results to r4.

Use **this directory's source snapshot**, not the checkout's top-level native sources.
The exact inputs are under `source/`, bound by `manifest.json`. This branch does not
promote or replace any engine DLL.

## Why r4 exists

The unchanged r3 C11 probe and a publication-free C11 smoke both abort in sanitizer
function-entry handling (`__tsan_func_entry`, null thread state) on the tested
Clang/GCC + glibc combinations, while pthread negative controls are correctly
instrumented on the same runners. r4 replaces **only** the thread launch/join/yield
adapters with pthread. Eight writers, four readers, 100000 iterations each, all payload
assertions, start synchronization, mismatch/paused-writer/wrap checks, all atomic types
and memory orders, and the at-least-one-accepted-read requirement are unchanged.

## Procedure

Preferred: `python3 collect.py <unique-run-id>` runs every step below for both Clang and
GCC, writes raw logs, `commands.json` and `result.json` under `results/<unique-run-id>/`,
and re-verifies the snapshot before and after. Raw status is `REVIEW_REQUIRED`; the
reviewed classification is decided by Windows Local, not by the collector.

Manual equivalent:

1. Run `python3 verify_snapshot.py` here. Record this branch commit,
   OS/kernel/architecture, and compiler and sanitizer runtime versions.
2. Compile and execute the **independent pthread negative control** and require a
   genuine ThreadSanitizer data-race report. A nonzero exit alone could be a runtime
   failure and is not accepted as calibration. `clang -std=c17 -O1 -g -fsanitize=thread -pthread negative_pthread.c -o negative` then
   `TSAN_OPTIONS=halt_on_error=1 timeout 120s ./negative`.
3. Compile and run the **pthread smoke** (`clang -std=c17 -O1 -g -fsanitize=thread -pthread smoke_pthread.c -o smoke` then `timeout 120s ./smoke`) to
   separate a sanitizer thread-entry failure from a publication failure.
4. Compile `clang -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o probe`.
5. Run `TSAN_OPTIONS=halt_on_error=1 timeout 120s ./probe` five times in separate processes. Capture commands, stdout/stderr,
   exit codes, elapsed times and binary SHA-256.
6. PASS requires a working negative control plus five clean protocol PASS results with
   no sanitizer reports, assertion failures or timeouts. An unsupported runtime is
   NOT_RUN.

Do not change atomics, assertions, workload, implementation, or add suppressions to
obtain PASS. ASan and ordinary stress do not replace TSan. If blocked, return the exact
error and environment evidence. Do not alter rules, production binaries or checkpoints,
launch SPRT, merge, or promote this branch.

## Return through GitHub

Put `result.json`, environment, commands and raw logs under
`handoffs/lazy-smp-g2-r4/results/<unique-run-id>/`. Do not commit compiled binaries;
record their hashes. Keep inputs unchanged. Report the PR URL and result.
Scope is the publication protocol only, not the Windows worker lifecycle or full
G2/G3 acceptance. Windows Local validates evidence before closing any gate.

## Frozen identities

- probe SHA-256 `2c1c6fa494941bb8b2411cd4c41d3ca5160a382013d3fa32d78c9dadd6db3be9`
- gate: require a genuine pthread data-race report from the negative control, then five clean protocol PASS runs with zero exit, zero detector reports, no assertion failure and no timeout; an unsupported sanitizer runtime is NOT_RUN
