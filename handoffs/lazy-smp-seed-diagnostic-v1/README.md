# Deterministic Lazy SMP seed diagnosis v1

Diagnostic only; not a revised acceptance workload and not an SMP candidate.
Base: `117c22aa3cf47d1175e1758c70f9af1ab8daa709` on
`codex/astra-g2-r4-pthread-handoff`. PR target is that branch, never main.
No merge, promotion, SPRT, or G2-G6 closure is authorized.

## Source-bound question

Can a reader accept the coherent pre-worker seed and then fail the workload's
payload/depth assertions without any concurrent publication?

Frozen main writes `NativeCompactMove move = {1,2,3,4}` under key 123, epoch 7,
depth 0. After wrong-key/epoch, paused-writer and sequence-exhaustion checks, it
resets **only sequence** to 0. Key/data/payload remain in the slot. The workload
reader asks for the same key and epoch, but expects complementary low words,
matching high metadata, and depth 42. A zero even sequence is accepted by the
actual read function; it is not an invalid-entry sentinel.

The snapshot hypothesis predicts:
- sequence before/after = 0, key = 123, epoch = 7, flags = 0, depth = 0;
- w0 = 0x1, w1 = 0x2, w2 = 0x0000000400000003;
- decoded move = {1,2,3,4}, accepted = true;
- all four workload predicates false, despite one coherent published seed.

This is an initialization/fixture inconsistency, not inherently a torn snapshot.
The scheduled run must establish the observation before a result is claimed.

## Reproduction (GitHub-hosted only for this task)

The collector runs each snapshot verifier before/after, pins the r3/r4 probe
SHA-256, and extracts the pre-thread setup **verbatim** into seed_setup.inc.
It refuses differing r3/r4 setup text. reproduce.c includes the untouched
probe using a preprocessor rename of its main; production functions/types and
the reader/assertions are not copied/reimplemented or modified. No top-level
native engine source is compiled.

Two compilers (Clang/GCC), two snapshots (r3/r4), three fresh-process cases:
1. snapshot: read the seed before any worker, dump full words, decoded move,
   key, epoch, data, depth and surrounding sequence; verify mismatched
   key/epoch miss.
2. assert-reader: set the original start flag and call the original reader
   synchronously. Expect SIGABRT **and the exact payload assertion text**.
   A different abort, timeout, or exit code alone does not confirm this case.
3. valid-control: in a separate process, repeat seed setup, write one valid
   workload tuple through the unchanged write function, verify all payload
   predicates, then run the original reader synchronously through all 100000
   iterations. No assertion is removed or weakened.

Exactly 12 planned diagnostic processes; each timeout 10 s, compile timeout 60 s,
overall Actions job limit 8 min. No timing retries or cherry-picking. Failed
compiles/missing tools/raw errors remain recorded. These are plain C17 -O1 -g
-pthread builds, **not TSan/ASan runs or replacement gate evidence**.
No concurrent workers, DLL loading, engine suite, tablebase or gameplay occurs.

The branch-scoped workflow triggers only when reproduction/collector/workflow
inputs change. A results/documentation commit does not launch another run.
Its token is read-only and checkout does not persist credentials.
All stdout/stderr, argv, exit codes, timing, compiler/OS/libc versions,
generated setup, source/binary hashes and before/after protected-file hashes
go under results/<GitHub-run-id>-<attempt>/; binaries stay outside uploaded
artifacts. Tracked-file diff and frozen subtree hashes must remain unchanged.
Full evidence is also emitted as text-only JSON records in the GitHub job log.

## Evidence reconciliation, without rewriting history

Pinned sources inspected:
- r4 snapshot: 117c22aa3cf47d1175e1758c70f9af1ab8daa709.
- raw TSan results: 4c566c9cac6117061285eed8d42765e4da8da7cb.
- liveness/addendum: 757847a9583824c32265efd4ce0b19dc3c78fc08.

At the second SHA, gcc_probe_tsan_run_01.stderr.log already contains
`move.captured_low == ~move.path_low`. Thus the later addendum's claim that
the original gate could not surface a payload assertion is incorrect. The
accepted-count assertion occurs after workers join, not before reader checks.
The result list contains 10 sanitized plus 2 plain attempts, with one GCC
sanitized process PASS; it is not 1 of 6 or zero individual passes. This does
not satisfy the five-clean-runs requirement. Original files remain immutable.

Current-state on the base predates the r4 results. The actual pthread probe,
smoke and negative-control evidence take precedence over outdated readiness
prose. Prior r3 NOT_RUN evidence is preserved, never relabelled.
Per the user's current directive, the old candidate stays
REJECT_FOR_PERFORMANCE / NOT_PROMOTED. Shared-score sharing stays blocked.

## What this can and cannot establish

A matching deterministic run confirms that the frozen setup admits an invalid
workload seed and that the exact reader can abort without a race. It does not
attribute every historical concurrent abort to that seed: those logs lack the
accepted tuple and publication sequence for each failure. Nor does it establish
a production publication defect, race-freedom, concurrent liveness, Windows
lifecycle safety, or G2-G6 acceptance. G2 stays NOT_PASSED.

The logged surrounding sequence and raw slot words are meaningful here because
**there are no other writers**. A later resnapshot under concurrency would not
prove what the original read observed.

## Proposed next revision (design only; not implemented)

Request review/authorization of a new versioned acceptance harness, retaining
all r3/r4 inputs and results byte-for-byte.

Initialization:
- Use a separate slot for preflight rejection/wrap tests and a fresh,
  explicitly invalid key/epoch slot for the concurrent workload; initialize
  only while quiescent, never reset/free during readers.
- A deterministic regression must show no matching-key seed is accepted before
  the first valid workload publication; retain this seed counterexample.

Safety:
- Keep every payload/depth assertion and key/epoch check.
- Validate each accepted tuple against one declared writer encoding.
- Retain directed paused/partial publication, same-entry multi-writer,
  mismatch and exhaustion cases using actual production types/functions.
- On failure, record the read's accepted locals and contemporaneous bracketing
  sequence via a reviewed diagnostic mechanism, then still fail; do not replace
  failure with logging. Post-read snapshots cannot prove original coherence.
- Run a calibrated pthread negative control and TSan on the new frozen workload.
  Preserve all five predeclared process results; no suppressions/atomic changes.

Liveness/coverage:
- Separately require a bounded single-writer/single-reader publication/ack
  handshake to observe known valid data after the writer completes.
  This synchronized case proves its stated progress condition, not race safety.
- Record successful/skipped writes, accepted/rejected reads and participant
  coverage in the concurrent safety workload. Zero accepted reads is
  INCOMPLETE_COVERAGE, never a safety PASS. Predeclare the coverage requirement
  and any bounded phase coordination before running; do not remove the old
  assertion retroactively or retry until a favorable schedule appears.
- Keep stop/deadlock/time bounds distinct from tuple-coherence results.

## Complexity budget

No production profiles, feature flags, ABI, state owners or engine dependencies
are added. One isolated diagnostic entrypoint (collect.py), one included C
diagnostic, and one branch-scoped CI workflow are added. Generated setup reuses
the frozen workload rather than maintaining a second implementation. This is
a diagnostic maintenance surface, not a permanent playing backend.
