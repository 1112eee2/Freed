"""Reproducible pre-game audit for the Phase 7 NNUE search candidate."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, legal_moves, parse_position
from makhos.native import NativeSearch
from makhos.native_benchmark import (
    compare_native_libraries,
    generate_native_benchmark_cases,
)


FORMAT = "thai-makhos-nnue-search-candidate-audit-v1"
ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
CANDIDATE = (
    ROOT
    / "build"
    / "nnue_search_v1_r5"
    / "makhos_native_nnue_candidate_v1.dll"
)
MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
TARGETS = (
    {
        "id": "external-sian-thao-ply-21",
        "position": "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17",
        "reversible_plies": 2,
        "historical_move": "27-23",
    },
    {
        "id": "human-loss-ply-13",
        "position": "B:BM20,22,23,25,27,28,29,31:RM2,3,5,7,8,9,11,15",
        "reversible_plies": 12,
        "historical_move": "28-24",
    },
    {
        "id": "human-loss-ply-25",
        "position": "B:BM19,20,22,27,31:RM2,3,5,10,11",
        "reversible_plies": 3,
        "historical_move": "27-23",
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def search_payload(engine: NativeSearch, state, history, budget_ms: int) -> dict:
    engine.clear()
    started = time.perf_counter()
    result = engine.search(
        state,
        depth=64,
        time_ms=budget_ms,
        no_progress_plies=DEFAULT_RULES.no_progress_plies,
        repetition_limit=DEFAULT_RULES.repetition_limit,
        history=history,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if result.move not in legal_moves(state):
        raise RuntimeError("search returned an illegal move")
    nnue = engine.nnue_telemetry()
    return {
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "elapsed_ms": result.elapsed_ms,
        "wall_ms": round(wall_ms, 3),
        "pv": [move.notation for move in result.pv],
        "qnodes": result.telemetry.qnodes if result.telemetry else None,
        "nnue": (
            {
                "root_refreshes": nnue[0],
                "child_updates": nnue[1],
                "evaluations": nnue[2],
            }
            if nnue is not None
            else None
        ),
    }


def summary(rows: list[dict]) -> dict:
    return {
        "trials": len(rows),
        "move_counts": dict(sorted(Counter(row["move"] for row in rows).items())),
        "median_depth": statistics.median(row["depth"] for row in rows),
        "median_nodes": statistics.median(row["nodes"] for row in rows),
        "median_elapsed_ms": statistics.median(row["elapsed_ms"] for row in rows),
        "median_wall_ms": statistics.median(row["wall_ms"] for row in rows),
    }


def run(args: argparse.Namespace) -> dict:
    candidate = args.candidate.resolve()
    accepted = args.accepted.resolve()
    model = args.model.resolve()
    for path in (candidate, accepted, model):
        if not path.is_file():
            raise FileNotFoundError(path)

    fixed_depth = compare_native_libraries(
        candidate,
        accepted,
        count=args.fixed_depth_cases,
        depth=args.fixed_depth,
        repetitions=args.fixed_depth_repetitions,
        hash_power=args.hash_power,
        candidate_nnue_model=model,
    ).as_dict()

    cases = generate_native_benchmark_cases(
        count=args.timed_cases,
        seed=args.seed,
    )
    timed_rows = []
    with NativeSearch(
        candidate,
        hash_power=args.hash_power,
        persistent=True,
        nnue_model=model,
    ) as nnue, NativeSearch(
        accepted,
        hash_power=args.hash_power,
        persistent=True,
    ) as control:
        for case in cases:
            if case.index % 2:
                candidate_row = search_payload(
                    nnue, case.state, case.history, args.timed_budget_ms
                )
                accepted_row = search_payload(
                    control, case.state, case.history, args.timed_budget_ms
                )
            else:
                accepted_row = search_payload(
                    control, case.state, case.history, args.timed_budget_ms
                )
                candidate_row = search_payload(
                    nnue, case.state, case.history, args.timed_budget_ms
                )
            timed_rows.append(
                {
                    "case": case.index,
                    "target_plies": case.target_plies,
                    "candidate": candidate_row,
                    "accepted": accepted_row,
                }
            )

        targets = []
        for target in TARGETS:
            state = parse_position(
                target["position"],
                reversible_plies=target["reversible_plies"],
            )
            candidate_rows = []
            accepted_rows = []
            for trial in range(args.target_trials):
                if trial % 2:
                    accepted_rows.append(
                        search_payload(
                            control, state, None, args.target_budget_ms
                        )
                    )
                    candidate_rows.append(
                        search_payload(nnue, state, None, args.target_budget_ms)
                    )
                else:
                    candidate_rows.append(
                        search_payload(nnue, state, None, args.target_budget_ms)
                    )
                    accepted_rows.append(
                        search_payload(
                            control, state, None, args.target_budget_ms
                        )
                    )
            targets.append(
                {
                    **target,
                    "budget_ms": args.target_budget_ms,
                    "candidate": {
                        "rows": candidate_rows,
                        "summary": summary(candidate_rows),
                    },
                    "accepted": {
                        "rows": accepted_rows,
                        "summary": summary(accepted_rows),
                    },
                }
            )

    candidate_timed = [row["candidate"] for row in timed_rows]
    accepted_timed = [row["accepted"] for row in timed_rows]
    payload = {
        "format": FORMAT,
        "verdict": "MEASUREMENT_ONLY",
        "accepted": {"path": str(accepted), "sha256": sha256(accepted)},
        "candidate": {"path": str(candidate), "sha256": sha256(candidate)},
        "model": {"path": str(model), "sha256": sha256(model)},
        "settings": {
            "hash_power": args.hash_power,
            "fixed_depth_cases": args.fixed_depth_cases,
            "fixed_depth": args.fixed_depth,
            "fixed_depth_repetitions": args.fixed_depth_repetitions,
            "timed_cases": args.timed_cases,
            "timed_budget_ms": args.timed_budget_ms,
            "target_budget_ms": args.target_budget_ms,
            "target_trials": args.target_trials,
            "seed": args.seed,
            "threads": 1,
        },
        "fixed_depth": fixed_depth,
        "fixed_time": {
            "rows": timed_rows,
            "candidate_summary": summary(candidate_timed),
            "accepted_summary": summary(accepted_timed),
            "same_move_cases": sum(
                row["candidate"]["move"] == row["accepted"]["move"]
                for row in timed_rows
            ),
        },
        "external_targets": targets,
        "sealed_test_labels_opened": False,
        "promotion_status": "NOT_EVALUATED",
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--accepted", type=Path, default=ACCEPTED)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "nnue_search_v1_r5" / "pre_game_audit.json",
    )
    parser.add_argument("--hash-power", type=int, default=18)
    parser.add_argument("--fixed-depth-cases", type=int, default=32)
    parser.add_argument("--fixed-depth", type=int, default=13)
    parser.add_argument("--fixed-depth-repetitions", type=int, default=3)
    parser.add_argument("--timed-cases", type=int, default=24)
    parser.add_argument("--timed-budget-ms", type=int, default=250)
    parser.add_argument("--target-budget-ms", type=int, default=1000)
    parser.add_argument("--target-trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0x4E4E554553454152)
    args = parser.parse_args()
    payload = run(args)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
