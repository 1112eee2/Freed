# Linux TSan publication gate: NOT_RUN

Base commit: `ed89600cdc92944efc158050b71ce5c0f9c881f1`.
Target: `codex/astra-g2-race-handoff`.

The required Clang compile could not execute: `/bin/bash: line 1: clang: command not found` (exit 127). Five canonical Clang runs are therefore explicitly NOT_RUN, with null execution times/codes.

To provide additional environment evidence, GCC 13.3.0 with libtsan2 14.2.0 was used separately, with the same sanitizer/compiler flags and unchanged probe. This is an explicitly disclosed compiler deviation, not a substitute PASS for the README command. The pthread negative control produced `WARNING: ThreadSanitizer: data race` (exit 66). All five separately launched probe processes also exited 66, but with `ThreadSanitizer: SEGV on unknown address 0x000000000018`, DEADLYSIGNAL and nested runtime aborts, not protocol PASS or a diagnosed protocol data race. No root cause is claimed; calibration of pthread interception does not establish working C11-thread instrumentation for this probe.

`verify_snapshot.py` passed before and after. Every original handoff file was fetched at the pinned commit and verified against its Git blob SHA; result.json binds its SHA-256. No input, atomic, assertion or workload was modified. No suppressions, ASan, unsanitized substitute, production change or SPRT was used. Compiled binaries remain outside this results folder and are not committed.

Evidence: result.json, commands.json, exact stdout/stderr logs, negative_control.c, run_gate.py, and evidence_sha256.json. The runner records raw attempts; this README and result classification were added after reviewing stderr. Environment command logs include OS/kernel, GCC, libc, libtsan package and linkage.

Scope: publication protocol only. This does not close full G2-G6 or Windows lifecycle gates. Re-run the unchanged handoff with its specified Clang/TSan toolchain in a supported Linux environment.
