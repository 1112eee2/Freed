# Next action after the reviewed r5 run

Status: PROPOSAL_FOR_REVIEW; not implemented and not authorization to alter frozen r5.

## Preserve the result

Keep r3/r4/r5 and every old log unchanged. r5 Linux is INCOMPLETE_COVERAGE (10/10); Windows remains INCOMPLETE_COVERAGE (1/5 protocol processes). G2 remains NOT_PASSED. The candidate remains REJECT_FOR_PERFORMANCE / NOT_PROMOTED.

## One falsifiable hypothesis for a future harness revision

The fixed 100000-iteration stress loops can exhaust a participant's entire attempt budget while another writer holds an odd sequence and is descheduled. The measured 2-vCPU results (zero-progress participants despite successful bounded SPSC) are consistent with this scheduling explanation; they do not uniquely prove it or establish a production publication bug.

Prepare a reviewed r6 design, without changing publication functions/types, to test whether bounded scheduling opportunities improve **coverage** while preserving unsynchronized overlap during each batch:

- Retain 8 writers, 4 readers, 100000 attempts per participant, all payload/range/depth predicates and per-participant minimum of one successful write/accepted read.
- Candidate scheduling rule for review: 1000 rounds of 100 attempts each, all participants ready before the first round, a barrier between rounds and a fixed yield outside publication calls. No per-attempt counter synchronization, no yield inside production functions, no repeated process until success.
- This rule does not guarantee acceptance; INCOMPLETE_COVERAGE must remain a possible outcome. Explicitly document the changed schedules and synchronization; do not assert it covers every r5 interleaving or turns the old r5 result into PASS.
- Keep SPSC independent and do not count SPSC or post-writer drain reads toward concurrent coverage.
- Keep Clang/GCC, smoke/negative controls and five protocol processes per lane; retain fixed slots, deadlines and every raw result.
- Define how directed cases are exercised on Linux before freezing: r5 collector invokes only protocol mode, whose entrypoint does not call run_directed. Do not silently add runs to frozen r5.
- Review actual admission/ready semantics: the current start flag waits for thread creation, not an acknowledgment that all participants reached the start point.

## Harness error-path defect to fix in the new revision

Frozen r5 run_spsc creates the reader first. If writer pthread_create fails, it sets spsc_failure and joins the reader. The reader loop does not check spsc_failure and can spin indefinitely on the invalid slot. A publication-skip error in the writer has the same cleanup problem. Preserve r5; add explicit error-path termination and a bounded fault-injection regression in the **new** harness revision. This is a source-derived harness finding, not a failure observed in the 10 Linux runs.

Keep failure logging tied to the accepted local tuple. Unexpected tuple/depth errors remain FAIL; missing runtime/launch prerequisites remain separately classified. Capture phase transitions so a timeout is attributable to initialization, SPSC, stress or join.

## PR #25 disposition

Do not merge/promote the candidate or run SPRT. Before any later integration:
1. Make the expanded stats ABI safe for old callers (versioned/sized API or explicit incompatibility rejection).
2. Resolve search-admission versus close/stop semantics with deterministic tests.
3. Withdraw unsupported pilot attribution and synchronize maintained protocol/gate prose.
4. Keep the existing candidate rejection; any future strength mechanism needs a new measured hypothesis.

These are review actions, not permission to edit frozen production atomics. Local can prepare the concrete new-harness design/diff and Windows-only candidate regressions while Web retains the Linux evidence.
