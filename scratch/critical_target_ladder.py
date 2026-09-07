"""Cold timed ladder for the external ply-21 27-23 horizon target."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import legal_moves, parse_position
from makhos.native import NativeSearch
from makhos.parallel_native import ParallelNativeSearch


POSITION = "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17"
REVERSIBLE_PLIES = 2
ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
CANDIDATE = ROOT / "build" / "makhos_native_iir_quiet_production_candidate.dll"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(engine, state, budget_ms: int) -> dict:
    engine.clear()
    result = engine.search(
        state,
        depth=64,
        time_ms=budget_ms,
        no_progress_plies=80,
        repetition_limit=None,
    )
    if result.move not in legal_moves(state):
        raise RuntimeError("native search returned an illegal move")
    return {
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "elapsed_ms": result.elapsed_ms,
        "pv": [move.notation for move in result.pv],
    }


def summarize(rows: list[dict]) -> dict:
    return {
        "trials": len(rows),
        "move_counts": dict(sorted(Counter(row["move"] for row in rows).items())),
        "depth_counts": {
            str(depth): count
            for depth, count in sorted(Counter(row["depth"] for row in rows).items())
        },
        "mean_depth": statistics.fmean(row["depth"] for row in rows),
        "mean_nodes": statistics.fmean(row["nodes"] for row in rows),
        "mean_elapsed_ms": statistics.fmean(row["elapsed_ms"] for row in rows),
        "target_27_23_trials": sum(row["move"] == "27-23" for row in rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-ms", type=int, action="append", default=None)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=512)
    parser.add_argument("--hash-power", type=int, default=20)
    parser.add_argument("--accepted", type=Path, default=ACCEPTED)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "iir_quiet_critical_ladder_20260823.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    budgets = tuple(args.budget_ms or (1000, 1200, 1300))
    if args.trials < 1 or any(budget < 1 for budget in budgets):
        raise ValueError("trials and budgets must be positive")
    if not 1 <= args.threads <= 12:
        raise ValueError("threads must be in 1..12")
    accepted_path = args.accepted.resolve()
    candidate_path = args.candidate.resolve()
    if not accepted_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError("accepted or candidate DLL is absent")
    state = parse_position(POSITION, reversible_plies=REVERSIBLE_PLIES)
    rows = {"accepted": {}, "candidate": {}}
    if args.threads == 1:
        accepted_search = NativeSearch(
            accepted_path, hash_power=args.hash_power, persistent=True
        )
        candidate_search = NativeSearch(
            candidate_path, hash_power=args.hash_power, persistent=True
        )
    else:
        accepted_search = ParallelNativeSearch(
            accepted_path, threads=args.threads, hash_mb=args.hash_mb
        )
        candidate_search = ParallelNativeSearch(
            candidate_path, threads=args.threads, hash_mb=args.hash_mb
        )
    with accepted_search as accepted, candidate_search as candidate:
        engines = {"accepted": accepted, "candidate": candidate}
        for budget in budgets:
            rows["accepted"][str(budget)] = []
            rows["candidate"][str(budget)] = []
            for trial in range(args.trials):
                order = (
                    ("accepted", "candidate")
                    if trial % 2 == 0
                    else ("candidate", "accepted")
                )
                for label in order:
                    rows[label][str(budget)].append(
                        run(engines[label], state, budget)
                    )

    summary = {
        label: {
            budget: summarize(results)
            for budget, results in by_budget.items()
        }
        for label, by_budget in rows.items()
    }
    report = {
        "format": "thai-makhos-critical-target-ladder-v1",
        "position": POSITION,
        "reversible_plies": REVERSIBLE_PLIES,
        "target_move": "27-23",
        "settings": {
            "budgets_ms": budgets,
            "trials": args.trials,
            "max_depth": 64,
            "hash_power": args.hash_power,
            "threads": args.threads,
            "hash_mb": args.hash_mb,
            "no_progress_plies": 80,
            "repetition_limit": 0,
            "fresh_tt_each_trial": True,
        },
        "libraries": {
            "accepted": {
                "path": str(accepted_path),
                "sha256": sha256(accepted_path),
            },
            "candidate": {
                "path": str(candidate_path),
                "sha256": sha256(candidate_path),
            },
        },
        "summary": summary,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "CRITICAL_TARGET_LADDER "
        + json.dumps(
            {
                "output": str(args.output.resolve()),
                "sha256": sha256(args.output),
                "summary": summary,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
