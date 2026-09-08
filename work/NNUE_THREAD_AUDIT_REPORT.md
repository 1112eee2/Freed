# Offline NNUE thread-audit reporting

This is preparation for the audit after both Gate C controls PASS and the
production smoke/reversible promotion review. It reads explicitly supplied
audit observations; it never loads a DLL, searches, monitors Gate C, changes
defaults, or authorizes a workload. The native measurement collector is still
pending those gates and its own correctness/isolation checks.

The existing preparation remains unchanged: 96 cases, Threads 1/2/4/6/8/12,
fixed 1000/2000 ms, total Hash 512 MiB, five balanced repetitions: **5,760
observations**. The reader regenerates that exact preparation and verifies
the complete fixture/schedule hash, including repetition histories.

## Use now with synthetic data

From the repository root, choose a new directory:

```powershell
python -B work/nnue_thread_audit_report.py demo --output-dir build/thread_report_synthetic_demo_v1
python -B work/test_nnue_thread_audit_report.py
```

`demo` creates `synthetic_observations.jsonl` and `synthetic_report.json`.
Every value is fabricated. The header/report say `synthetic_fixture`, the host
is `FABRICATED_HOST`, and the report carries a conspicuous fabricated-data
marker. These files exercise the reporting contract; their numbers are not
engine performance measurements. Existing directories/files are not overwritten.

To reproduce a report from a stopped/copied **thread-audit** stream:

```powershell
python -B work/nnue_thread_audit_report.py summarize --input build/thread_report_synthetic_demo_v1/synthetic_observations.jsonl --output build/thread_report_synthetic_demo_v1/reproduced_report.json
```

Do not pass a Gate C checkpoint or a sealed training partition. The reader
requires the specific header/observation schema below. It does not repair or
resume an input file. Newlines may be LF or CRLF; file hashes bind the actual
bytes while decoded observation statistics remain identical.

## Recording contract for the future collector

The first JSONL line is one header with exactly these fields:

| Field | Meaning |
|---|---|
| `format` | `thai-makhos-thread-observations-v1` |
| `run_id` | Unique nonempty run label |
| `data_kind` | `measured` or `synthetic_fixture`; never relabel a demo |
| `fixtures_sha256` | `digest(prepare())` from the existing preparation module |
| `release_manifest_sha256` | SHA-256 of the reviewed release manifest; the reporter records the binding but does not verify the manifest |
| `host` | `id`, positive `physical_cores`, positive `logical_threads`; the target is 6/12 |
| `identity` | `native_library_sha256`, `nnue_model_sha256`, `native_search_abi`, `nnue_feature_abi`, and `tablebase_sha256` with keys `4`, `5`, `6` |
| `settings` | `mode: win`, `hash_mb_total: 512`, `fresh_state_per_observation: true`, `restore_fixture_history: true`, `tt_layout: private-per-worker` |

The feature ABI must be `thai-makhos-shared-137-v1`. Each subsequent line is
one observation with exactly these fields:

| Field | Meaning |
|---|---|
| `run_sha256` | Canonical `digest(header)`; prevents combining runs/hosts/configurations |
| `schedule_index` | Zero-based index into the reproduced schedule; contiguous in recording order |
| `identity` | Actual runtime identity for this observation; must equal the header identity |
| `result` | `move`, integer `score`, completed `depth`, `nodes`, legal `pv`, `wall_ms`, engine `elapsed_ms`, `tablebase_hits`, `backend`, `native_error` |
| `tt_bytes_by_worker` | Actual allocated TT bytes for each private worker; exactly the requested worker count, summed within the 512 MiB total budget |
| `telemetry` | All fields below, each a measurement or explicit `null` |

`backend` must be `native-single` at 1T or `native-root-split` at larger thread
counts. `forced` is allowed only with one legal root move. Fallback or native
errors invalidate the stream for comparisons. A PV must start with the chosen
move and replay legally with the recorded repetition history, captures,
promotion and no-progress clock. Scores/depths are diagnostic observations,
not solved truth. The reader checks consistency of recorded claims; it cannot
prove that a collector actually reset state, restored history, or had an idle host.

Telemetry fields are:

| Fields | Units/semantics |
|---|---|
| `active_workers` | Observed workers doing search work; distinct from allocated workers, 0 for a forced return |
| `qnodes`, `duplicate_nodes` | Per-observation instrumented counts; duplication cannot be inferred from total nodes |
| `coordinator_ms`, `cpu_time_ms` | Observed coordination wall time and CPU time respectively |
| `process_peak_rss_bytes` | Process high-water RSS as sampled/defined by the collector; not TT allocation |
| `nnue_ms`, `movegen_ms`, `tablebase_ms` | Instrumented component time; define overlap and worker aggregation before recording, do not sum them as disjoint time |
| `cpu_frequency_mhz`, `temperature_c` | Available host readings |

Unavailable measurements must be **null**, never fabricated zeros. In
particular, the current iterative-session root splitter exposes no per-layer
telemetry delta. Do not copy a cumulative counter into a per-observation field.
The report includes availability counts and leaves `profile_coverage_complete`
false while any required observation lacks telemetry.

## Interpretation

- Summaries keep budgets and thread counts separate and report actual TT,
  depth/nodes, wall/engine time, nonnegative overshoot and available telemetry.
  p95 is the nearest-rank percentile. Forced cases and synthetic two-king clock
  edges have separate strata from the main playout positions.
- With all 5,760 rows present, matched comparisons use the same case,
  repetition and budget against 1T. They report move agreement, deeper/shallower
  counts, and depth/time deltas. Repetition summaries count stable moves across
  all five runs. No NPS-based configuration recommendation is made.
- Missing rows or an unterminated final line yield `INCOMPLETE_DIAGNOSTIC` and
  suppress matched comparisons/repeatability statistics. A partial tail is
  counted in bytes and preserved; even a tail after 5,760 valid rows withholds
  completion. Duplicates, gaps, reordered rows, malformed completed lines,
  identity drift, illegal moves, nonfinite values and excess TT are errors.
- `COMPLETE_DIAGNOSTIC` means complete, structurally valid recorded observations.
  It is not a strength gate or a full profile attestation. Header identities,
  runtime isolation and release evidence still need independent host checks.
  `recommended_threads` is always null; strength and promotion flags are false.

After Gate C and production review, implement the collector against this
contract and validate its real measurements. Then use the approved matrix to
identify a single bottleneck. Paired strength testing remains necessary before
recommending a different thread configuration or promoting an optimization.
