"""Compare native scalar and AVX2 accumulator delta updates by delta shape."""

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

from makhos.core import (  # noqa: E402
    BLACK,
    BLACK_MAN,
    RED_MAN,
    apply_move,
    legal_moves,
    parse_position,
    state_from_pieces,
)
from makhos.nnue_features import (  # noqa: E402
    both_perspective_feature_deltas,
    perspective_active_features,
)
from makhos.workload_isolation import (  # noqa: E402
    BatchWorkLease,
    interactive_session_active,
)


ACCEPTED_SHA256 = (
    "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def encode(values) -> str:
    values = tuple(values)
    if not values:
        raise RuntimeError("benchmark delta unexpectedly empty")
    return ",".join(str(value) for value in values)


def cases():
    return (
        ("quiet_no_boundary", parse_position("B:BM25:RK1", reversible_plies=1), False),
        ("quiet_clock_boundary", parse_position("B:BM25:RK1", reversible_plies=9), False),
        (
            "capture_reset",
            state_from_pieces(
                {(4, 3): BLACK_MAN, (3, 2): RED_MAN, (5, 2): RED_MAN},
                BLACK,
                reversible_plies=37,
            ),
            False,
        ),
        (
            "multi_capture",
            state_from_pieces(
                {(6, 1): BLACK_MAN, (5, 2): RED_MAN, (3, 4): RED_MAN},
                BLACK,
                reversible_plies=12,
            ),
            False,
        ),
        ("promotion", parse_position("R:RM25:BK5", reversible_plies=7), True),
    )


def transition(name, parent, require_promotion):
    moves = legal_moves(parent)
    move = next(item for item in moves if item.promotes) if require_promotion else moves[0]
    child = apply_move(parent, move)
    deltas = {delta.perspective: delta for delta in both_perspective_feature_deltas(parent, child)}
    return {
        "name": name,
        "parent": parent,
        "child": child,
        "move": move,
        "red": deltas[1],
        "black": deltas[2],
    }


def run_once(executable, scalar_library, avx2_library, model, source_sha, iterations, case, order):
    parent = case["parent"]
    command = [
        str(executable), str(scalar_library), str(avx2_library), str(model),
        source_sha, str(iterations),
        encode(perspective_active_features(parent, 1)),
        encode(perspective_active_features(parent, 2)),
        encode(case["red"].removed), encode(case["red"].added),
        encode(case["black"].removed), encode(case["black"].added),
        str(parent.turn), order,
    ]
    creationflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        raise RuntimeError(f"benchmark failed for {case['name']}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--scalar-library", type=Path, required=True)
    parser.add_argument("--avx2-library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--dense-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=500_000)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 100_000 or args.repetitions < 3:
        parser.error("evidence run requires >=100000 iterations and >=3 repetitions")
    paths = [
        args.executable.resolve(), args.scalar_library.resolve(),
        args.avx2_library.resolve(), args.model.resolve(), args.contract.resolve(),
        args.dense_report.resolve(),
    ]
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"missing benchmark input: {path}")
    executable, scalar_library, avx2_library, model, contract_path, dense_path = paths
    accepted = ROOT / "build" / "makhos_native_accepted.dll"
    if sha256(accepted) != ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity mismatch")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    dense_report = json.loads(dense_path.read_text(encoding="utf-8"))
    dense_reference_ns = round(statistics.median(
        case["median_avx2_eval_ns"] for case in dense_report["cases"]
    ), 3)
    transitions = [transition(*item) for item in cases()]
    all_runs = {case["name"]: [] for case in transitions}
    run_order = []
    with BatchWorkLease(ROOT) as lease:
        for repetition in range(args.repetitions):
            ordered = transitions if repetition % 2 == 0 else list(reversed(transitions))
            order = "scalar-first" if repetition % 2 == 0 else "avx2-first"
            for case in ordered:
                lease.checkpoint(f"AVX2-update raw-cost {case['name']}")
                run = run_once(
                    executable, scalar_library, avx2_library, model,
                    contract["source_model_sha256"], args.iterations, case, order,
                )
                all_runs[case["name"]].append(run)
                run_order.append({"case": case["name"], "order": order})

    results = []
    for case in transitions:
        runs = all_runs[case["name"]]
        scalar_ns = round(statistics.median(run["scalar_move_update_ns"] for run in runs), 3)
        avx2_ns = round(statistics.median(run["avx2_move_update_ns"] for run in runs), 3)
        results.append({
            "name": case["name"],
            "move": case["move"].notation,
            "parent_clock": case["parent"].reversible_plies,
            "child_clock": case["child"].reversible_plies,
            "red_removed": len(case["red"].removed),
            "red_added": len(case["red"].added),
            "black_removed": len(case["black"].removed),
            "black_added": len(case["black"].added),
            "scalar_move_update_ns_runs": [run["scalar_move_update_ns"] for run in runs],
            "avx2_move_update_ns_runs": [run["avx2_move_update_ns"] for run in runs],
            "median_native_scalar_move_update_ns": scalar_ns,
            "median_avx2_move_update_ns": avx2_ns,
            "avx2_speedup_vs_native_scalar": round(scalar_ns / avx2_ns, 3),
            "phase6b_dense_reference_ns": dense_reference_ns,
            "update_plus_dense_reference_ns": round(avx2_ns + dense_reference_ns, 3),
            "checksum_stable": len({run["checksum"] for run in runs}) == 1,
            "raw_runs": runs,
        })
    minimum_speedup = min(case["avx2_speedup_vs_native_scalar"] for case in results)
    verdict = "KEEP_MEASUREMENT_ONLY" if minimum_speedup > 1.0 else "REJECT"
    report = {
        "format": "thai-makhos-nnue-avx2-update-raw-cost-v1",
        "verdict": verdict,
        "conclusion": (
            "AVX2 accumulator updates are bit-exact and reproducibly faster for every predeclared delta shape; retain the standalone kernel for integration gating"
            if verdict == "KEEP_MEASUREMENT_ONLY"
            else "AVX2 accumulator updates did not beat native scalar for every delta shape"
        ),
        "minimum_median_speedup_vs_native_scalar": minimum_speedup,
        "dense_reference_semantics": "median Phase 6B AVX2 dense cost across four piece bands; combined cost is an estimate, not search NPS",
        "scalar_library_sha256": sha256(scalar_library),
        "avx2_update_library_sha256": sha256(avx2_library),
        "avx2_update_source_sha256": sha256(ROOT / "native" / "makhos_nnue_avx2_update.c"),
        "benchmark_executable_sha256": sha256(executable),
        "benchmark_source_sha256": sha256(ROOT / "scratch" / "nnue_avx2_update_benchmark.c"),
        "runner_source_sha256": sha256(Path(__file__).resolve()),
        "quantized_model_sha256": sha256(model),
        "quantization_contract_sha256": sha256(contract_path),
        "phase6b_dense_report_sha256": sha256(dense_path),
        "accepted_hce_sha256": sha256(accepted),
        "priority": "BelowNormal",
        "iterations_per_run": args.iterations,
        "repetitions": args.repetitions,
        "run_order": run_order,
        "interactive_session_inactive_at_write": not interactive_session_active(),
        "playing_path_changed": False,
        "sealed_test_labels_opened": False,
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
