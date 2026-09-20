# Proposed diff — not implemented

ไฟล์ในรายการนี้เป็นขอบเขต **หลัง design approval** เท่านั้น ไม่มีไฟล์ r5 acceptance ใดถูกสร้างจากเอกสารนี้

```text
A  tests/native_lazy_smp_portable_pthread_r5.c
   - harness_body source: separate preflight/workload/liveness slots
   - PR #23 seed regression, directed protocol, SPSC handshake, 8W/4R safety counters

A  tools/verification/prepare_lazy_smp_race_probe_r5.py
   - refuse source/hash drift
   - copy frozen r4 production source snapshot and unchanged pthread controls
   - extract exact production types/functions and append the reviewed r5 body

A  handoffs/lazy-smp-g2-r5/README.md
A  handoffs/lazy-smp-g2-r5/manifest.json
A  handoffs/lazy-smp-g2-r5/verify_snapshot.py
A  handoffs/lazy-smp-g2-r5/collect.py
A  handoffs/lazy-smp-g2-r5/probe.c
A  handoffs/lazy-smp-g2-r5/smoke_pthread.c
A  handoffs/lazy-smp-g2-r5/negative_pthread.c
A  handoffs/lazy-smp-g2-r5/source/native/makhos_native.c
A  handoffs/lazy-smp-g2-r5/source/native/makhos_types.h
A  handoffs/lazy-smp-g2-r5/source/tests/native_lazy_smp_portable_pthread_r5.c
A  handoffs/lazy-smp-g2-r5/source/tests/native_lazy_smp_smoke_pthread.c
A  handoffs/lazy-smp-g2-r5/source/tests/native_lazy_smp_negative_pthread.c
   - self-contained frozen bundle; no dependency on mutable root sources at run time

A  .github/workflows/lazy-smp-tsan-r5.yml
   - branch-scoped, read-only token, pinned actions, no persisted credentials
   - Clang/GCC smoke + calibrated negative + five protocol processes/lane
   - upload text evidence only; no binaries

NO CHANGE  native/makhos_native.c
NO CHANGE  native/makhos_types.h
NO CHANGE  RULESET.json
NO CHANGE  makhos/core.py
NO CHANGE  accepted/production DLLs, profiles, models, checkpoints
NO CHANGE  handoffs/lazy-smp-g2-r3/**
NO CHANGE  handoffs/lazy-smp-g2-r4/** and all prior results
```

## Harness outline proposed for review

```c
static SharedMoveHintEntry preflight_slot;
static SharedMoveHintEntry workload_slot; /* invalid key/epoch before workers */
static SharedMoveHintEntry liveness_slot; /* independent SPSC */
static atomic_bool reader_ready;          /* release store / acquire load */
static atomic_uint_fast64_t ack;           /* release store / acquire load */

directed_preflight_tests(&preflight_slot);      /* includes PR #23 regression */
assert_initial_namespace_miss(&workload_slot);  /* before any valid publication */
run_bounded_spsc(&liveness_slot, 256);          /* 256 distinct ids, not raw reads */
run_concurrent_safety(&workload_slot, 8, 4, 100000);
emit_one_json_result_and_exit_by_classification();
```

Failure output must serialize the accepted local move/depth plus reader/writer/iteration encoding
before returning FAIL. It must not reread the slot and call that reread the original observation.
The exact JSON schema and exit mapping are frozen in `manifest.json` before any acceptance run.
Concurrent writer ids are 0..7 and iterations 1..100000; SPSC uses writer id 0 and distinct
publication ids 1..256. Per-participant stress counters are thread-local non-atomic records,
written only by their owner and aggregated after join, so normal-loop counters add no synchronization.
Reader-ready is published before the first SPSC write; acknowledgments order each successive id.

## Explicit non-diff

No production instrumentation is proposed. If accepted locals prove insufficient to diagnose a
future FAIL, a separate diagnostic proposal may mechanically expose internal sequence values;
that build cannot replace the byte-exact production-function gate without another review.
