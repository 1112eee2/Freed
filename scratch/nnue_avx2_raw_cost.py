"""Compare scalar and AVX2 dense inference in the same standalone DLL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import parse_position  # noqa: E402
from makhos.nnue_features import perspective_active_features  # noqa: E402
from makhos.workload_isolation import (  # noqa: E402
    BatchWorkLease,
    interactive_session_active,
)
from scratch.nnue_incremental_raw_cost import CASES  # noqa: E402


ACCEPTED_SHA256 = (
    "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def encode(values) -> str:
    return ",".join(str(value) for value in values)


def run_once(executable, library, model, source_sha, iterations, case, order):
    state = parse_position(case["position"], reversible_plies=case["clock"])
    command = [
        str(executable),
        str(library),
        str(model),
        source_sha,
        str(iterations),
        encode(perspective_active_features(state, 1)),
        encode(perspective_active_features(state, 2)),
        str(state.turn),
        order,
    ]
    creationflags = (
        subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    )
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"benchmark failed for {case['name']}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--incremental-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1_000_000)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 100_000 or args.repetitions < 3:
        parser.error("evidence run requires >=100000 iterations and >=3 repetitions")

    paths = [
        args.executable.resolve(),
        args.library.resolve(),
        args.model.resolve(),
        args.contract.resolve(),
        args.incremental_report.resolve(),
    ]
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"missing benchmark input: {path}")
    executable, library, model, contract_path, incremental_path = paths
    accepted = ROOT / "build" / "makhos_native_accepted.dll"
    if sha256(accepted) != ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity mismatch")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    incremental_report = json.loads(incremental_path.read_text(encoding="utf-8"))
    references = {case["pieces"]: case for case in incremental_report["cases"]}

    all_runs = {case["name"]: [] for case in CASES}
    run_order = []
    with BatchWorkLease(ROOT) as lease:
        for repetition in range(args.repetitions):
            ordered_cases = CASES if repetition % 2 == 0 else tuple(reversed(CASES))
            order = "scalar-first" if repetition % 2 == 0 else "avx2-first"
            for case in ordered_cases:
                lease.checkpoint(f"AVX2 raw-cost {case['name']}")
                run = run_once(
                    executable,
                    library,
                    model,
                    contract["source_model_sha256"],
                    args.iterations,
                    case,
                    order,
                )
                all_runs[case["name"]].append(run)
                run_order.append({"case": case["name"], "order": order})

    cases = []
    for case in CASES:
        runs = all_runs[case["name"]]
        scalar_ns = round(statistics.median(run["scalar_eval_ns"] for run in runs), 3)
        avx2_ns = round(statistics.median(run["avx2_eval_ns"] for run in runs), 3)
        reference = references[case["pieces"]]
        update_ns = reference["median_move_update_both_perspectives_ns"]
        hce_ns = reference["phase5_hce_reference_ns"]
        native_scalar_ns = reference["median_incremental_eval_ns"]
        cases.append({
            **case,
            "model_bytes": runs[0]["model_bytes"],
            "accumulator_bytes": runs[0]["accumulator_bytes"],
            "scalar_eval_ns_runs": [run["scalar_eval_ns"] for run in runs],
            "avx2_eval_ns_runs": [run["avx2_eval_ns"] for run in runs],
            "median_scalar_same_dll_ns": scalar_ns,
            "median_avx2_eval_ns": avx2_ns,
            "avx2_speedup_vs_scalar_same_dll": round(scalar_ns / avx2_ns, 3),
            "phase6a_native_scalar_reference_ns": native_scalar_ns,
            "avx2_speedup_vs_phase6a_native_scalar": round(
                native_scalar_ns / avx2_ns, 3
            ),
            "unchanged_move_update_both_perspectives_ns": update_ns,
            "projected_update_plus_avx2_eval_ns": round(update_ns + avx2_ns, 3),
            "avx2_eval_over_hce_latency_ratio": round(avx2_ns / hce_ns, 3),
            "projected_update_plus_avx2_over_hce_latency_ratio": round(
                (update_ns + avx2_ns) / hce_ns, 3
            ),
            "checksum_stable": len({run["checksum"] for run in runs}) == 1,
            "raw_runs": runs,
        })

    minimum_same_dll_speedup = min(
        case["avx2_speedup_vs_scalar_same_dll"] for case in cases
    )
    minimum_native_speedup = min(
        case["avx2_speedup_vs_phase6a_native_scalar"] for case in cases
    )
    verdict = (
        "KEEP_MEASUREMENT_ONLY"
        if minimum_same_dll_speedup > 1.0 and minimum_native_speedup > 1.0
        else "REJECT"
    )
    report = {
        "format": "thai-makhos-nnue-avx2-raw-cost-v1",
        "verdict": verdict,
        "conclusion": (
            "AVX2 dense evaluation is bit-exact and reproducibly faster than "
            "both the same-DLL scalar diagnostic and the Phase 6A native scalar "
            "control; retain the standalone kernel for the next measured gate, "
            "not playing search"
            if verdict == "KEEP_MEASUREMENT_ONLY"
            else "AVX2 dense evaluation did not beat the scalar seam in every case"
        ),
        "minimum_median_speedup_vs_scalar_same_dll": minimum_same_dll_speedup,
        "minimum_median_speedup_vs_phase6a_native_scalar": minimum_native_speedup,
        "avx2_library_sha256": sha256(library),
        "avx2_source_sha256": sha256(ROOT / "native" / "makhos_nnue_avx2.c"),
        "benchmark_executable_sha256": sha256(executable),
        "benchmark_source_sha256": sha256(ROOT / "scratch" / "nnue_avx2_benchmark.c"),
        "runner_source_sha256": sha256(Path(__file__).resolve()),
        "quantized_model_sha256": sha256(model),
        "quantization_contract_sha256": sha256(contract_path),
        "phase6a_incremental_report_sha256": sha256(incremental_path),
        "accepted_hce_sha256": sha256(accepted),
        "host_processor_identifier": os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "priority": "BelowNormal",
        "iterations_per_run": args.iterations,
        "repetitions": args.repetitions,
        "run_order": run_order,
        "interactive_session_inactive_at_write": not interactive_session_active(),
        "accumulator_updates_changed": False,
        "playing_path_changed": False,
        "sealed_test_labels_opened": False,
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
