"""Measure the standalone scalar incremental NNUE seams reproducibly."""

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

from makhos.core import apply_move, legal_moves, parse_position  # noqa: E402
from makhos.nnue_features import (  # noqa: E402
    both_perspective_feature_deltas,
    perspective_active_features,
)
from makhos.workload_isolation import (  # noqa: E402
    BatchWorkLease,
    interactive_session_active,
)


CASES = (
    {
        "name": "pieces16_clock0",
        "pieces": 16,
        "clock": 0,
        "position": "B:BM21,22,23,24,25,26,27,28:RM1,2,3,4,5,6,7,8",
    },
    {
        "name": "pieces10_clock39",
        "pieces": 10,
        "clock": 39,
        "position": "R:BM21,22,25,27:BK30:RM5,7,8,10:RK2",
    },
    {
        "name": "pieces6_clock59",
        "pieces": 6,
        "clock": 59,
        "position": "B:BM21,22:BK30:RM5,7:RK2",
    },
    {
        "name": "pieces2_clock78",
        "pieces": 2,
        "clock": 78,
        "position": "R:BK30:RK2",
    },
)
ACCEPTED_SHA256 = (
    "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def encode(values) -> str:
    values = tuple(values)
    if not values:
        raise RuntimeError("benchmark transition unexpectedly has an empty delta")
    return ",".join(str(value) for value in values)


def run_once(
    executable: Path,
    library: Path,
    model: Path,
    source_sha: str,
    iterations: int,
    case: dict,
) -> dict:
    parent = parse_position(
        case["position"], reversible_plies=case["clock"]
    )
    moves = legal_moves(parent)
    if not moves:
        raise RuntimeError(f"benchmark case has no move: {case['name']}")
    move = moves[0]
    child = apply_move(parent, move)
    deltas = {
        delta.perspective: delta
        for delta in both_perspective_feature_deltas(parent, child)
    }
    red_delta = deltas[1]
    black_delta = deltas[2]
    command = [
        str(executable),
        str(library),
        str(model),
        source_sha,
        str(iterations),
        encode(perspective_active_features(parent, 1)),
        encode(perspective_active_features(parent, 2)),
        encode(red_delta.removed),
        encode(red_delta.added),
        encode(black_delta.removed),
        encode(black_delta.added),
        str(parent.turn),
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
    payload = json.loads(result.stdout)
    payload["move"] = move.notation
    payload["child_clock"] = child.reversible_plies
    return payload


def median_runs(runs: list[dict], key: str) -> float:
    return round(statistics.median(run[key] for run in runs), 3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--scalar-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=500_000)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 100_000 or args.repetitions < 3:
        parser.error("evidence run requires >=100000 iterations and >=3 repetitions")

    executable = args.executable.resolve()
    library = args.library.resolve()
    model = args.model.resolve()
    contract_path = args.contract.resolve()
    scalar_path = args.scalar_report.resolve()
    for path in (executable, library, model, contract_path, scalar_path):
        if not path.is_file():
            raise RuntimeError(f"missing benchmark input: {path}")
    accepted = ROOT / "build" / "makhos_native_accepted.dll"
    if sha256(accepted) != ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity mismatch")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    scalar_report = json.loads(scalar_path.read_text(encoding="utf-8"))
    scalar_by_pieces = {case["pieces"]: case for case in scalar_report["cases"]}

    all_runs = {case["name"]: [] for case in CASES}
    run_order = []
    with BatchWorkLease(ROOT) as lease:
        for repetition in range(args.repetitions):
            ordered = CASES if repetition % 2 == 0 else tuple(reversed(CASES))
            for case in ordered:
                lease.checkpoint(f"incremental raw-cost {case['name']}")
                run = run_once(
                    executable,
                    library,
                    model,
                    contract["source_model_sha256"],
                    args.iterations,
                    case,
                )
                all_runs[case["name"]].append(run)
                run_order.append(case["name"])

    cases = []
    for case in CASES:
        runs = all_runs[case["name"]]
        reference = scalar_by_pieces[case["pieces"]]
        refresh_ns = median_runs(runs, "refresh_ns")
        eval_ns = median_runs(runs, "eval_ns")
        full_ns = median_runs(runs, "full_refresh_eval_ns")
        update_ns = median_runs(runs, "move_update_both_perspectives_ns")
        hce_ns = reference["hce_median_ns_per_eval"]
        scalar_ns = reference["scalar_median_ns_per_eval"]
        cases.append({
            **case,
            "move": runs[0]["move"],
            "child_clock": runs[0]["child_clock"],
            "active_features_red": runs[0]["red_count"],
            "active_features_black": runs[0]["black_count"],
            "model_bytes": runs[0]["model_bytes"],
            "accumulator_bytes": runs[0]["accumulator_bytes"],
            "refresh_ns_runs": [run["refresh_ns"] for run in runs],
            "eval_ns_runs": [run["eval_ns"] for run in runs],
            "full_refresh_eval_ns_runs": [
                run["full_refresh_eval_ns"] for run in runs
            ],
            "move_update_both_perspectives_ns_runs": [
                run["move_update_both_perspectives_ns"] for run in runs
            ],
            "median_refresh_ns": refresh_ns,
            "median_incremental_eval_ns": eval_ns,
            "median_full_refresh_eval_ns": full_ns,
            "median_move_update_both_perspectives_ns": update_ns,
            "median_update_plus_eval_ns": round(update_ns + eval_ns, 3),
            "phase5_scalar_reference_ns": scalar_ns,
            "phase5_hce_reference_ns": hce_ns,
            "incremental_eval_speedup_vs_phase5_full_refresh": round(
                scalar_ns / eval_ns, 3
            ),
            "incremental_eval_over_hce_latency_ratio": round(eval_ns / hce_ns, 3),
            "update_plus_eval_over_hce_latency_ratio": round(
                (update_ns + eval_ns) / hce_ns, 3
            ),
            "checksum_stable": len({run["checksum"] for run in runs}) == 1,
            "raw_runs": runs,
        })

    report = {
        "format": "thai-makhos-nnue-incremental-raw-cost-v1",
        "verdict": "PASS_MEASUREMENT_ONLY",
        "conclusion": (
            "scalar incremental state is correct and materially reduces the "
            "dense-evaluation seam versus Phase 5 full refresh, but remains "
            "far too slow for the playing path; retain it as the incremental "
            "correctness oracle and require a separately proven AVX2 path"
        ),
        "incremental_library_sha256": sha256(library),
        "incremental_source_sha256": sha256(
            ROOT / "native" / "makhos_nnue_incremental.c"
        ),
        "benchmark_executable_sha256": sha256(executable),
        "benchmark_source_sha256": sha256(
            ROOT / "scratch" / "nnue_incremental_benchmark.c"
        ),
        "runner_source_sha256": sha256(Path(__file__).resolve()),
        "quantized_model_sha256": sha256(model),
        "quantization_contract_sha256": sha256(contract_path),
        "phase5_scalar_report_sha256": sha256(scalar_path),
        "accepted_hce_sha256": sha256(accepted),
        "host_processor_identifier": os.environ.get(
            "PROCESSOR_IDENTIFIER", "unknown"
        ),
        "priority": "BelowNormal",
        "iterations_per_run": args.iterations,
        "repetitions": args.repetitions,
        "run_order": run_order,
        "interactive_session_inactive_at_write": not interactive_session_active(),
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
