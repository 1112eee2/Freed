# r4 pthread ThreadSanitizer result: sanitizer path fixed, protocol run NOT_COMPLETED

Reviewed 2026-09-16. Run: https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/35114293886
Handoff commit: `117c22aa3cf47d1175e1758c70f9af1ab8daa709`.
Raw evidence: `35114293886-1/` (collector status `REVIEW_REQUIRED`; this file and
`reviewed_result.json` are the reviewed classification).

r3 is byte-for-byte untouched. No r3 result was read, reused or transferred.

## 1. The r4 hypothesis is confirmed

| Case | r3 (C11 threads) | r4 (pthread) |
|---|---|---|
| smoke under TSan | runtime SEGV in `__tsan_func_entry`, null thread state | **exit 0, zero reports** (clang and gcc) |
| negative control under TSan | runtime SEGV; no usable race report | **exit 66 with `WARNING: ThreadSanitizer: data race`** (clang and gcc) |
| probe under TSan | 5/5 runtime abort | runs the publication code; see below |

Replacing only the thread launch/join/yield adapters moved the failure from
"the sanitizer cannot execute this path at all" to "the sanitizer executes it".
That is the outcome the harness revision proposal predicted, and it is the first
calibrated TSan negative control this project has had: the report text was checked,
not just the exit code.

## 2. The protocol run does not complete

`probe.c:158: Assertion 'atomic_load(&accepted) > 0' failed` — SIGABRT.

| Configuration | Exit codes |
|---|---|
| clang probe, no sanitizer | −6 |
| gcc probe, no sanitizer | −6 |
| clang probe + TSan (5 runs) | −6, −6, −6, −6, −6 |
| gcc probe + TSan (5 runs) | −6, −6, −6, −6, **0** (`accepted=961`) |

**No probe run reported a data race.** No assertion inside the publication
functions fired. The only failure is the frozen liveness assertion at the end of
`main`.

Classification: **harness liveness calibration, not a publication defect.**

`shared_move_hint_read` returns true only when the seqlock sequence is even and
unchanged across its six loads and the key matches. `shared_move_hint_write` is a
documented bounded store-skip that returns false on contention, and the reader has
no retry loop by design. Zero accepted reads is therefore a legitimate outcome of
the documented contract under an 8-writer : 4-reader ratio — it is a liveness
expectation the contract does not guarantee. The single passing run
(`accepted=961`) confirms the assertion is timing-dependent, not impossible.

Runner: ubuntu-24.04.5, kernel 6.17.0-1022-azure, **2 vCPU**, clang 18.1.3,
gcc 13.3.0, glibc 2.39. Twelve threads on two vCPUs is a heavy-contention regime.

Note for the record: the r3 follow-up reported one plain frozen-probe PASS on a
hosted runner. A single observation is consistent with a low-probability event at
the rate measured here (1 of 6). It is not treated as a contradiction, and it is
not treated as proof that the pthread adapters changed scheduling.

No assertion, atomic, memory order, workload or sanitizer option was changed and
no suppression was added to obtain a pass.

## 3. Gate status

**NOT_PASSED.** The r4 gate needs a calibrated negative control plus five clean
protocol PASS runs. The negative control is now calibrated; zero probe runs passed.

Not established by this run: publication race-freedom, Windows worker lifecycle
behaviour, any G2–G6 closure, any Elo claim, any production change.

## 4. Proposed next action (r5 — not implemented, needs owner authorisation)

Hypothesis: the frozen `accepted > 0` assertion is not guaranteed by the
documented bounded-skip/miss contract at 8:4 on a 2-vCPU runner. Options, in
increasing order of change:

1. **Run r4 unchanged on a runner with more vCPUs** and record whether the
   assertion then holds reproducibly. No code change; cheapest falsification.
2. **Separate the race test from the liveness expectation.** Keep the concurrent
   protocol run and report its accepted count as an observation, but assert
   liveness on a dedicated single-writer/single-reader handshake that the contract
   does guarantee.
3. **Change the workload** — lower the writer:reader ratio, or add a bounded drain
   phase where writers stop before readers finish.

Any change to the frozen assertion or workload needs explicit owner acceptance and
must not be made to manufacture a PASS.
