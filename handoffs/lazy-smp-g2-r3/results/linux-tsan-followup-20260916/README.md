# r3 Linux ThreadSanitizer follow-up: NOT_RUN

PR #18 and its NOT_RUN evidence remain unchanged. This is a new result directory.
The frozen handoff is commit `ed89600cdc92944efc158050b71ce5c0f9c881f1`.

## Execution and evidence

- Hosted execution: https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/35089088905
- Tested head: `36b215cc0aaa21c413db8e98d462b6b46f440fb6`; GitHub tested merge ref `ca01fdec49ec29504cb77d794f0639f51c00fc35`. This ephemeral CI merge ref is not a merge of the PR into the handoff branch.
- Ubuntu 24.04.5 / kernel 6.17.0-1022-azure, Clang 18.1.3, GCC 13.3.0, glibc 2.39, GDB 15.1. Exact package revisions and linker information are in hosted logs.
- Original hosted artifact: ID 10443681624; ZIP SHA-256 `4d12f42e2457bca75cf762255f66a3062582c741c4add4101cbf5e9017974357`.
- The artifact download's temporary URL returned HTTP 403 in this container. A separate read-only Actions job retrieved and SHA-verified the SAME original artifact and emitted its UTF-8 files through job logs: run 35089383678, job 104771802562. Tests were not rerun during retrieval. All per-command stdout/stderr hashes were checked after extraction.
- `executed-workflow.yml` archives the workflow actually used. The temporary active workflow is removed from the final branch tree so this PR's final diff contains only this result directory.
- Local installation attempt failed because apt could not change process groups/uids in the container (apt-update.log). No sandbox bypass was attempted. The hosted runner successfully provisioned Clang/TSan and GDB.

## Results

| Case | Local GCC | Hosted GCC | Hosted Clang |
|---|---|---|---|
| pthread negative / TSan | genuine data-race report | genuine data-race report | genuine data-race report |
| C11 smoke / no sanitizer | PASS | PASS | not requested |
| C11 smoke / TSan | runtime SEGV | runtime SEGV | runtime SEGV |
| C11 negative / TSan | runtime SEGV; no calibration | runtime SEGV; no calibration | runtime SEGV; no calibration |
| Frozen probe / no sanitizer | protocol PASS | protocol PASS | not requested |
| Frozen probe / TSan | 5/5 runtime abort | 5/5 runtime abort | 5/5 runtime abort |

Clang compiled the frozen probe using the exact README command, then executed
`TSAN_OPTIONS=halt_on_error=1 timeout 120s ./probe` five times in independent
processes. All exited 66 with SEGV/DEADLYSIGNAL/nested runtime aborts, not data-race
reports or protocol PASS. See hosted/commands.json and hosted/result.json for
commands, UTC times, elapsed times and binary SHA-256. All assertions and atomic
operations remain enabled and unchanged; no suppressions or ASLR changes were used.

The GitHub job succeeded as an evidence-collection job; that is NOT a TSan PASS.
Raw collector result.json files retain their original REVIEW_REQUIRED marker;
the reviewed classification is this directory's top-level result.json: NOT_RUN
because the sanitizer cannot execute this C11-thread path successfully.

## Crash localization

The hosted GCC smoke stack stops in `__tsan_func_entry`, called at entry to the
minimal worker, above glibc `start_thread` and `clone3`. This smoke contains no
Makhos publication functions or structures. The frozen probe's debugger trace
also resolves `__tsan::TraceAcquire(thr=0x0)` / `TryTraceFunc` / `FuncEntry`, with
an atomic load at address 0x18, before executing the body of `collide`.

Clang's separately linked runtime likewise stops in `__tsan_func_entry` at entry
to both the smoke worker and the frozen probe worker. The C11 negative control
does not produce a usable race report, whereas pthread negative controls do.
Unsanitized C11 smoke and the exact frozen probe pass in both environments.

These observations localize the reproduced crash to sanitizer thread-entry
handling on the C11 thrd_create path for these tested toolchain/libc combinations.
They support a missing/uninitialized sanitizer thread-state integration diagnosis;
they do not establish the exact upstream interceptor defect or prove that every
TSan version lacks C11 support. They do not prove publication race-freedom. Exit 66
alone was not used for diagnosis.

Relevant stack files: hosted/gcc_c11_smoke_tsan_gdb.stdout.log,
hosted/gcc_probe_tsan_gdb.stdout.log, hosted/clang_c11_smoke_tsan_gdb.stdout.log,
hosted/clang_probe_tsan_gdb.stdout.log. Debugger exit 0 means a trace was captured,
not that the inferior passed. Local GDB was absent; that exact error is retained.

## Next action

See HARNESS_REVISION_PROPOSAL.md for an unimplemented r4 pthread harness proposal.
Do not overwrite r3 or reinterpret its results. No binaries are committed, no
production files changed, no merge/promotion/SPRT occurred. Scope is publication
protocol only, not Windows lifecycle or overall G2-G6 acceptance.
