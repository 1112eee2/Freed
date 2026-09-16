# Astra Web: Linux ThreadSanitizer handoff

Use **this directory's source snapshot**, not the checkout's top-level native sources.
The top-level checkout is only the transport base. Local r3 implementation changes
were not committed there. The exact inputs are under `source/`, bound by `manifest.json`.
This branch does not promote or replace any engine DLL.

## Procedure

1. Run `python3 verify_snapshot.py` here. Record this branch commit, OS/kernel/architecture,
   compiler and sanitizer runtime versions.
2. Compile and execute a separate deliberately racy negative control. Require a real
   ThreadSanitizer data-race report: a nonzero exit alone could be a runtime failure.
3. Compile `clang -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o probe`.
4. Run `TSAN_OPTIONS=halt_on_error=1 timeout 120s ./probe` five times in separate processes.
   Capture commands, stdout/stderr, exit codes, elapsed times and binary SHA-256.
5. PASS requires a working negative control and five clean protocol PASS results with
   no sanitizer reports/assertion failures/timeouts. Unsupported runtime is NOT_RUN.

Do not change atomics, assertions, workload, implementation, or add suppressions to
obtain PASS. ASan and ordinary stress do not replace TSan. If blocked, return the exact
error and environment evidence. Do not alter rules, production binaries or checkpoints,
launch SPRT, merge, or promote this branch.

## Return through GitHub

Create a results branch from this commit and open a PR targeting
`codex/astra-g2-race-handoff`, not main. Put result.json, environment, commands and raw
logs under `handoffs/lazy-smp-g2-r3/results/<unique-run-id>/`. Do not commit compiled
binaries; record their hashes. Keep inputs unchanged. Report the PR URL and result.
Scope is the publication protocol only, not the Windows worker lifecycle or full
G2/G3 acceptance. Windows Local will validate evidence before closing any gate.
