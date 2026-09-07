"""Deterministic gate for the evidence-scoped quiet non-PV IIR candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, format_position, legal_moves, parse_position
from makhos.native import NativeSearch
from makhos.native_benchmark import generate_native_benchmark_cases


CONTROL = ROOT / "build" / "makhos_native_iir_quiet_control.dll"
CANDIDATE = ROOT / "build" / "makhos_native_iir_quiet_candidate.dll"
ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
TARGETS = (
    {
        "id": "external-sian-thao-ply-21",
        "position": "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17",
        "reversible_plies": 2,
        "played_move": "27-23",
        "depths": (22, 24, 25),
    },
    {
        "id": "human-loss-ply-13",
        "position": "B:BM20,22,23,25,27,28,29,31:RM2,3,5,7,8,9,11,15",
        "reversible_plies": 12,
        "played_move": "28-24",
        "depths": (18, 20, 22),
    },
    {
        "id": "human-loss-ply-25",
        "position": "B:BM19,20,22,27,31:RM2,3,5,10,11",
        "reversible_plies": 3,
        "played_move": "27-23",
        "depths": (18, 20, 22),
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def search_payload(
    engine: NativeSearch,
    state,
    depth: int,
    *,
    deadline_ms: int,
    history=None,
) -> dict:
    engine.clear()
    started = time.perf_counter()
    result = engine.search(
        state,
        depth=depth,
        time_ms=deadline_ms,
        no_progress_plies=DEFAULT_RULES.no_progress_plies,
        repetition_limit=DEFAULT_RULES.repetition_limit,
        history=history,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if result.move not in legal_moves(state):
        raise RuntimeError("native search returned an illegal move")
    return {
        "requested_depth": depth,
        "completed": result.depth == depth,
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "elapsed_ms": result.elapsed_ms,
        "wall_ms": round(wall_ms, 3),
        "pv": [move.notation for move in result.pv],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "iir_quiet_candidate_audit_20260823.json",
    )
    parser.add_argument("--cases", type=int, default=96)
    parser.add_argument("--depth", type=int, default=15)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--hash-power", type=int, default=17)
    parser.add_argument("--case-deadline-ms", type=int, default=5000)
    parser.add_argument("--target-deadline-ms", type=int, default=5000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (CONTROL, CANDIDATE, ACCEPTED):
        if not path.is_file():
            raise FileNotFoundError(path)

    if args.repetitions < 2:
        raise ValueError("at least two repetitions are required")
    started = time.perf_counter()
    cases = generate_native_benchmark_cases(count=args.cases, seed=args.seed)
    benchmark_rows = []
    timed_out_case = None
    control_total_ms = 0.0
    candidate_total_ms = 0.0
    node_ratios = []
    same_moves = 0
    same_scores = 0
    repeatable_control = 0
    repeatable_candidate = 0
    target_rows = []
    with NativeSearch(
        CONTROL, hash_power=args.hash_power, persistent=True
    ) as control, NativeSearch(
        CANDIDATE, hash_power=args.hash_power, persistent=True
    ) as candidate:
        for case in cases:
            control_runs = [
                search_payload(
                    control,
                    case.state,
                    args.depth,
                    deadline_ms=args.case_deadline_ms,
                    history=case.history,
                )
                for _ in range(args.repetitions)
            ]
            candidate_runs = [
                search_payload(
                    candidate,
                    case.state,
                    args.depth,
                    deadline_ms=args.case_deadline_ms,
                    history=case.history,
                )
                for _ in range(args.repetitions)
            ]
            control_keys = {
                (row["move"], row["score"], row["depth"], row["nodes"], tuple(row["pv"]))
                for row in control_runs
            }
            candidate_keys = {
                (row["move"], row["score"], row["depth"], row["nodes"], tuple(row["pv"]))
                for row in candidate_runs
            }
            control_repeat = len(control_keys) == 1
            candidate_repeat = len(candidate_keys) == 1
            repeatable_control += control_repeat
            repeatable_candidate += candidate_repeat
            control_completed = all(row["completed"] for row in control_runs)
            candidate_completed = all(row["completed"] for row in candidate_runs)
            control_row = control_runs[0]
            candidate_row = candidate_runs[0]
            control_ms = statistics.median(row["wall_ms"] for row in control_runs)
            candidate_ms = statistics.median(row["wall_ms"] for row in candidate_runs)
            benchmark_rows.append(
                {
                    "case": case.index,
                    "target_plies": case.target_plies,
                    "position": format_position(case.state),
                    "legal_moves": len(legal_moves(case.state)),
                    "control_repeatable": control_repeat,
                    "candidate_repeatable": candidate_repeat,
                    "control": {**control_row, "median_wall_ms": control_ms},
                    "candidate": {**candidate_row, "median_wall_ms": candidate_ms},
                }
            )
            if not control_completed or not candidate_completed:
                timed_out_case = {
                    "case": case.index,
                    "control_completed": control_completed,
                    "candidate_completed": candidate_completed,
                    "deadline_ms": args.case_deadline_ms,
                }
                break
            control_total_ms += control_ms
            candidate_total_ms += candidate_ms
            node_ratios.append(candidate_row["nodes"] / control_row["nodes"])
            same_moves += candidate_row["move"] == control_row["move"]
            same_scores += candidate_row["score"] == control_row["score"]

        for target in TARGETS:
            state = parse_position(
                target["position"],
                reversible_plies=target["reversible_plies"],
            )
            searches = []
            for depth in target["depths"]:
                searches.append(
                    {
                        "depth": depth,
                        "control": search_payload(
                            control,
                            state,
                            depth,
                            deadline_ms=args.target_deadline_ms,
                        ),
                        "candidate": search_payload(
                            candidate,
                            state,
                            depth,
                            deadline_ms=args.target_deadline_ms,
                        ),
                    }
                )
            target_rows.append({**target, "searches": searches})

    completed_cases = len(node_ratios)
    node_ratio = (
        math.exp(sum(math.log(value) for value in node_ratios) / completed_cases)
        if completed_cases
        else None
    )
    time_ratio = (
        candidate_total_ms / control_total_ms if control_total_ms else None
    )
    summary = {
        "requested_cases": args.cases,
        "processed_cases": len(benchmark_rows),
        "completed_fixed_depth_cases": completed_cases,
        "timed_out_case": timed_out_case,
        "control_repeatable_cases": repeatable_control,
        "candidate_repeatable_cases": repeatable_candidate,
        "same_move_cases": same_moves,
        "same_score_cases": same_scores,
        "candidate_node_ratio": node_ratio,
        "candidate_time_ratio": time_ratio,
        "control_total_median_ms": control_total_ms,
        "candidate_total_median_ms": candidate_total_ms,
    }
    report = {
        "format": "thai-makhos-iir-quiet-candidate-v1",
        "experiment": (
            "one-ply IIR at non-root quiet null-window nodes without TT move, "
            "depth >= 6, after null probe"
        ),
        "accepted_control_sha256": sha256(ACCEPTED),
        "config": {
            "cases": args.cases,
            "depth": args.depth,
            "repetitions": args.repetitions,
            "seed": args.seed,
            "hash_power": args.hash_power,
            "case_deadline_ms": args.case_deadline_ms,
            "target_deadline_ms": args.target_deadline_ms,
        },
        "libraries": {
            "control": {"path": str(CONTROL), "sha256": sha256(CONTROL)},
            "candidate": {"path": str(CANDIDATE), "sha256": sha256(CANDIDATE)},
        },
        "benchmark": {"summary": summary, "rows": benchmark_rows},
        "legal_move_cases": len(benchmark_rows),
        "target_ladders": target_rows,
        "decision_inputs": {
            "candidate_node_ratio": node_ratio,
            "candidate_time_ratio": time_ratio,
            "same_move_cases": same_moves,
            "same_score_cases": same_scores,
            "timed_out_case": timed_out_case,
        },
        "wall_seconds": round(time.perf_counter() - started, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "IIR_QUIET_AUDIT "
        + json.dumps(
            {
                "output": str(args.output.resolve()),
                "sha256": sha256(args.output),
                "accepted_control_sha256": report["accepted_control_sha256"],
                "decision_inputs": report["decision_inputs"],
                "target_ladders": target_rows,
                "wall_seconds": report["wall_seconds"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
