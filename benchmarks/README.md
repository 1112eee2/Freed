# Endgame latency benchmark

Run from the repository root, with interactive play and other engine workloads idle:

```powershell
python -B benchmarks/endgame_latency.py --output build/latency-new-run --time-ms 1000 --repeats 20 --threads 12 --hash-mb 512
```

The output directory must be new. The runner holds the exclusive workload lease,
launches its own BelowNormal Windows worker without a visible window, and stops
only that child before releasing the lease. Interactive priority is checked
between requests. No SPRT checkpoint is read or resumed. It does not connect to
an existing GUI server. On startup/error it retains the log and partial report.

The worker uses the production release's DLL/model and the production HTTP
handler on loopback. It deliberately disables background engine warm-up: the
first request measures engine setup. `worker_ready_ms` includes release loading,
but is not the production launcher's browser-readiness measurement. Its runtime
isolation is reported as `exclusive-batch-v1`.

Since Phase 1B, TB3 loads independently at worker startup and the coordinator
waits on `GET /api/readiness` before starting observations. `tb3_startup` binds
the artifact SHA and actual load time. The first request still measures cold
search-engine setup; it no longer includes TB3 construction. Historical Phase 1A
reports retain their original meaning and must be compared using their recorded
source commit. They are not rewritten by this change.

The default suite contains TB3, TB4 with/without repetition, clocks 78/79, a draw
defence, TB5, TB6 and a seven-piece native position. Both BEST and WIN are run.
Use repeated `--case` arguments to select case IDs from `cases()`. This first
suite does not yet cover seven-to-six capture transitions, simultaneous requests,
or native cancellation latency. Existing terminal regressions cover clock 80.

Each run contains:

- One unprofiled fresh-process request. OS page-cache state is uncontrolled.
- Twenty unprofiled timed observations per position/mode by default. Engine.clear()
  is invoked through the new-game state endpoint before each warm observation;
  mapped tablebases remain loaded.
- One plain and one profiled fixed-depth request per position/mode. The move,
  score, PV, depth, nodes, WDL and TB-hit count must match. These requests have a
  30-second safety cap; hitting it invalidates the comparison.
- Source hashes, runtime DLL/model/release provenance, raw HTTP responses,
  client wall time, process CPU/IO/page-fault/RSS changes and nearest-rank
  P50/P95/P99 with the actual sample count. With N=20, P99 is the maximum;
  this does not establish a reliable tail estimate.

`PASS` means the runner completed, required tablebases were available, and the
fixed-depth profile comparisons matched. It is not a playing-strength or latency
acceptance decision. Profiled timings must never be pooled into timed results.

## HTTP diagnostics

Successful `/api/bestmove` responses add `timings_ms`:

| Field | Interval |
| --- | --- |
| validation | Handler entry through settings/history validation and profiler setup |
| engine_lock_wait | Waiting for the engine lock |
| engine_setup | Engine/resource creation or reconfiguration after acquiring the lock |
| tb3_prepare | TB3 eligibility check and attachment of ready bytes (no IO/solve since Phase 1B) |
| search | Engine.search call |
| provenance | Runtime identity/resource snapshot |
| response_prepare | Remaining result formatting, including optional profiler report |

The intervals partition `request_elapsed_ms` up to rounding. This clock ends
before JSON serialization and the socket write. Client wall time includes those
costs plus connection/HTTP overhead. Existing `elapsed_ms` remains the engine's
search clock, and `pre_search_setup_ms` remains engine setup plus TB3 preparation.
`request_overshoot_ms` compares the handler's complete measured interval to the
requested search budget; this instrumentation does not change time allocation.

`tb3_ready_before` and `tb3_load_attempted` retain the engine attachment semantics:
the latter means an attempt to attach, not disk IO on the request thread.
`tb3.ready` reports whether the independent artifact loader has finished.
`worker_count` counts configured native workers. `search_thread_capacity`
is the backend's capacity: zero for a forced move, one for Python, and the
configured native pool for root split. It is not measured simultaneous worker
utilization. Process CPU time / client wall time supplies a separate utilization
observation.

Send `"profile_request": true` to collect the optional `python_profile` report.
Profiling is off by default and wraps only setup/TB3/search on the request thread.
Category self times are non-overlapping; cumulative function times overlap.
Native internals/helper threads are opaque. Python movement/state work includes
calls from evaluation and policy as well as tree traversal. Page faults include
soft faults, and process read bytes do not measure mmap disk traffic accurately.
Use an independent Windows ETW trace to separate hard page faults and IO wait;
the report explicitly marks that distinction unmeasured.
