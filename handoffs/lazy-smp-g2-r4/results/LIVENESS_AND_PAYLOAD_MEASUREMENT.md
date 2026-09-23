# r4 probe liveness and payload-consistency measurement — 2026-09-16

Reviewed by Windows Local. This is a **measurement of frozen artifacts**, not gate
evidence and not a re-run of the gate. It never edited a handoff, never weakened an
assertion, and never added a suppression.

Run: https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/35125560169
Tool: `tools/verification/measure_lazy_smp_r4_liveness.py`
Raw summaries in this directory. Probe SHAs re-checked against each frozen manifest
before measuring: r4 `2c1c6fa4…`, r3 `67f8b7cf…`.

## 1. Headline

The r4 gate run aborted on the frozen liveness assertion `assert(atomic_load(&accepted) > 0)`
in five of six probe runs. Measuring 20 runs per variant found that this is **not the only
abort**: the probe also aborts on its **own payload-consistency assertion**
`assert(move.captured_low == ~move.path_low)` (probe.c:125) — an assertion that is
supposed to hold for **any** snapshot the reader accepts.

That second abort reproduces on the **frozen r3 probe as well**, which is byte-for-byte
untouched since PR #18. It is therefore **not** caused by the r4 pthread revision.

| Probe | Variant | pass | `captured_low == ~path_low` | `accepted > 0` | other |
|---|---|---|---|---|---|
| r4 (pthread) | clang + TSan | 3/20 | **9** | 8 | 0 |
| r4 | gcc + TSan | 5/20 | **8** | 7 | 0 |
| r4 | clang, no sanitizer | 4/20 | **10** | 6 | 0 |
| **r3 (C11, frozen)** | clang + TSan | 0/20 | 0 | 0 | 20 × exit 66 |
| **r3 (C11, frozen)** | gcc + TSan | 0/20 | 0 | 0 | 20 × exit 66 |
| **r3 (C11, frozen)** | clang, no sanitizer | 5/20 | **9** | 6 | 0 |

Runner: ubuntu-24.04.5, kernel 6.17.0-1022-azure, **2 vCPU**, clang 18.1.3, gcc 13.3.0.

Platform contrast, same frozen r4 probe, no sanitizer, 20 runs on a 12-logical-CPU
Windows host (gcc 15.2.0): **19 pass, 1 payload-assertion abort.**

## 2. What this means

- The payload abort is **real, reproducible, and pre-existing**. It is present in the
  frozen workload that r3 has carried since PR #18.
- It has never been reported before because r3's TSan variants **cannot run at all**
  (20/20 exit 66 — the C11 sanitizer blocker, reproduced deterministically here), and
  r3's plain probe was only ever run **once**, where it passed.
- The r4 gate run never surfaced it either, because it aborted earlier on the liveness
  assertion.
- The liveness assertion is also unreliable (~30–40% failure) and its `accepted` values
  span a huge range when it does pass: 2 … 400000 on Linux, 611 … 42645 on Windows
  (400000 = the theoretical maximum of 4 readers × 100000). Both are timing-dependent
  quantities.

## 3. Mechanism: NOT ATTRIBUTED

This is stated plainly because it matters:

A reading of the publication protocol says a torn payload should be **impossible**. The
writer raises the odd sequence bit with a CAS before the payload stores and lowers it
after; the reader brackets its payload loads with two sequence loads and rejects on
`seq1 != seq2`. Under x86-TSO with seq_cst operations, a reader that observes a payload
word from write B must observe B's final sequence store, so `seq1 != seq2` would reject.
The measured ~45% failure rate on Linux (and ~5% on Windows) contradicts that reading.

**No mechanism is claimed.** The observation is recorded with counts; the contradiction
between the intended semantics and the measurement is itself the finding, and it needs a
dedicated diagnostic before any conclusion. Possibilities that remain open, none of them
established:

- a hole in the seqlock as written that the reasoning above misses;
- a compiler/codegen effect at `-O1` on the inlined `static inline` reader;
- something in the harness's own payload construction or assertion;
- a platform/libc difference in how the atomics are implemented.

**This is not a data-race report.** No run produced a ThreadSanitizer report on the probe.
It is an assertion inside the probe's own payload check firing.

## 4. Consequences

- The r4 gate remains **NOT_PASSED**, now for two independent reasons.
- **G2's publication-protocol scope is not closed and should not be treated as close to
  closed.** If a reader can accept an inconsistent move snapshot, the shared hint table
  can hand a wrong move to the search. That is a correctness question, not a performance
  one, and it outranks the Lazy SMP performance verdict.
- The `accepted > 0` assertion should not be used as a liveness gate at all until the
  workload is calibrated; it encodes a timing-dependent expectation, not a guarantee.
- Nothing here authorises a production change, an SPRT, or a promotion. r3, r4, PR #18
  and PR #20 are untouched.

## 5. Proposed next diagnostic (r5, NOT implemented, needs owner authorisation)

Capture the failing read itself. A diagnostic probe that, instead of asserting, records
the accepted `w0`, `w1`, `w2`, `d` **and** re-reads `sequence`, `key`, `move_w0`,
`move_w1`, `move_w2` immediately after the acceptance, plus a monotonically increasing
reader-local counter, would show directly whether the accepted payload words came from
different writes and what the sequence looked like at both ends.

Two further controls that need no harness change:

1. Run the same frozen probe pinned to a single CPU (`taskset -c 0`) to separate
   oversubscription from a protocol hole.
2. Repeat the 20× measurement on a host with more vCPUs; larger GitHub runners are not
   available on this repository's plan, so this needs a different machine.

Any change to the frozen probe, its assertions or its workload needs explicit owner
acceptance and must not be made to manufacture a pass.
