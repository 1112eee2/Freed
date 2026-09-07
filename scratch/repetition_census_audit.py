"""Measure repetition-scan work without changing native search behavior."""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, format_position, legal_moves, parse_position
from makhos.native import NativeRepetitionCensusTelemetry, NativeSearch
from makhos.native_benchmark import generate_native_benchmark_cases


CONTROL = ROOT / "build" / "makhos_native_repetition_census_control.dll"
CANDIDATE = ROOT / "build" / "makhos_native_repetition_census_candidate.dll"
ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
HUMAN_POSITIONS = (
    {
        "id": "human-loss-ply-13",
        "position": "B:BM20,22,23,25,27,28,29,31:RM2,3,5,7,8,9,11,15",
        "reversible_plies": 12,
        "depth": 22,
        "played_move": "28-24",
    },
    {
        "id": "human-loss-ply-25",
        "position": "B:BM19,20,22,27,31:RM2,3,5,10,11",
        "reversible_plies": 3,
        "depth": 22,
        "played_move": "27-23",
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_payload(result, wall_ms: float) -> dict:
    return {
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "elapsed_ms": result.elapsed_ms,
        "wall_ms": round(wall_ms, 3),
        "pv": [move.notation for move in result.pv],
    }


def run_search(engine: NativeSearch, state, history, depth: int):
    engine.clear()
    started = time.perf_counter()
    result = engine.search(
        state,
        depth=depth,
        time_ms=None,
        no_progress_plies=DEFAULT_RULES.no_progress_plies,
        repetition_limit=DEFAULT_RULES.repetition_limit,
        history=history,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if result.depth != depth:
        raise RuntimeError(
            f"fixed-depth search completed {result.depth}, expected {depth}"
        )
    return result, wall_ms


def zero_totals() -> dict[str, int]:
    return {field.name: 0 for field in fields(NativeRepetitionCensusTelemetry)}


def add_census(
    totals: dict[str, int], census: NativeRepetitionCensusTelemetry
) -> None:
    for name in totals:
        totals[name] += getattr(census, name)


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 4) if denominator else 0.0


def summarize_census(totals: dict[str, int]) -> dict:
    summary = dict(totals)
    summary.update(
        {
            "qsearch_pct_of_calls": percent(
                totals["qsearch_calls"], totals["calls"]
            ),
            "initial_linear_entries_per_call": ratio(
                totals["initial_linear_entries"], totals["initial_linear_calls"]
            ),
            "initial_hash_probes_per_call": ratio(
                totals["initial_hash_probes"], totals["initial_hash_calls"]
            ),
            "initial_hit_pct": percent(
                totals["initial_hits"],
                totals["initial_linear_calls"] + totals["initial_hash_calls"],
            ),
            "line_entries_per_call": ratio(
                totals["line_entries"], totals["calls"]
            ),
            "line_match_pct_of_entries": percent(
                totals["line_matches"], totals["line_entries"]
            ),
            "draw_hit_pct_of_calls": percent(
                totals["draw_hits"], totals["calls"]
            ),
            "span_zero_pct": percent(totals["span_zero"], totals["calls"]),
            "span_1_4_pct": percent(totals["span_1_4"], totals["calls"]),
            "span_5_16_pct": percent(totals["span_5_16"], totals["calls"]),
            "span_17_plus_pct": percent(
                totals["span_17_plus"], totals["calls"]
            ),
        }
    )
    return summary


def parity_key(result) -> tuple:
    return (
        result.move.notation,
        result.score,
        result.depth,
        result.nodes,
        tuple(move.notation for move in result.pv),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "repetition_census_audit_20260823.json",
    )
    parser.add_argument("--cases", type=int, default=96)
    parser.add_argument("--depth", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--hash-power", type=int, default=17)
    parser.add_argument("--repetitions", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for library in (CONTROL, CANDIDATE, ACCEPTED):
        if not library.is_file():
            raise FileNotFoundError(library)
    if args.repetitions < 2:
        raise ValueError("at least two repetitions are required")

    cases = generate_native_benchmark_cases(count=args.cases, seed=args.seed)
    totals = zero_totals()
    rows: list[dict] = []
    control_total_ms = 0.0
    candidate_total_ms = 0.0
    started = time.perf_counter()
    with NativeSearch(
        CONTROL, hash_power=args.hash_power, persistent=True
    ) as control, NativeSearch(
        CANDIDATE, hash_power=args.hash_power, persistent=True
    ) as candidate:
        if control.supports_repetition_census:
            raise RuntimeError("control unexpectedly exposes repetition census")
        if not candidate.supports_repetition_census:
            raise RuntimeError("candidate does not expose repetition census")

        for case in cases:
            control_runs = [
                run_search(control, case.state, case.history, args.depth)
                for _ in range(args.repetitions)
            ]
            candidate_runs = []
            candidate_census = []
            for _ in range(args.repetitions):
                candidate_runs.append(
                    run_search(candidate, case.state, case.history, args.depth)
                )
                census = candidate.repetition_census
                if census is None:
                    raise RuntimeError("candidate returned no repetition census")
                candidate_census.append(census)

            control_keys = {parity_key(result) for result, _ in control_runs}
            candidate_keys = {parity_key(result) for result, _ in candidate_runs}
            census_keys = {tuple(asdict(item).values()) for item in candidate_census}
            if (
                len(control_keys) != 1
                or len(candidate_keys) != 1
                or len(census_keys) != 1
                or control_keys != candidate_keys
            ):
                raise RuntimeError(
                    f"behavior-preserving gate failed on case {case.index}"
                )

            control_result = control_runs[0][0]
            candidate_result = candidate_runs[0][0]
            control_ms = statistics.median(wall for _, wall in control_runs)
            candidate_ms = statistics.median(wall for _, wall in candidate_runs)
            control_total_ms += control_ms
            candidate_total_ms += candidate_ms
            add_census(totals, candidate_census[0])
            moves = legal_moves(case.state)
            rows.append(
                {
                    "case": case.index,
                    "target_plies": case.target_plies,
                    "position": format_position(case.state),
                    "legal_moves": len(moves),
                    "forced_capture": bool(moves[0].captures),
                    "control": result_payload(control_result, control_ms),
                    "candidate": result_payload(candidate_result, candidate_ms),
                    "census": asdict(candidate_census[0]),
                }
            )

        human_rows: list[dict] = []
        for sample in HUMAN_POSITIONS:
            state = parse_position(
                sample["position"], reversible_plies=sample["reversible_plies"]
            )
            control_result, control_ms = run_search(
                control, state, None, sample["depth"]
            )
            candidate_result, candidate_ms = run_search(
                candidate, state, None, sample["depth"]
            )
            census = candidate.repetition_census
            if census is None or parity_key(control_result) != parity_key(
                candidate_result
            ):
                raise RuntimeError(f"human-position parity failed: {sample['id']}")
            human_rows.append(
                {
                    **sample,
                    "control": result_payload(control_result, control_ms),
                    "candidate": result_payload(candidate_result, candidate_ms),
                    "census": summarize_census(asdict(census)),
                }
            )

    report = {
        "format": "thai-makhos-repetition-census-v1",
        "experiment": "behavior-preserving repetition scan census",
        "config": {
            "cases": args.cases,
            "depth": args.depth,
            "seed": args.seed,
            "hash_power": args.hash_power,
            "repetitions": args.repetitions,
            "ply_schedule": [4, 8, 12, 16, 20, 24, 28, 32],
            "no_progress_plies": DEFAULT_RULES.no_progress_plies,
            "repetition_limit": DEFAULT_RULES.repetition_limit,
        },
        "libraries": {
            "accepted_control": {
                "path": str(ACCEPTED.resolve()),
                "sha256": sha256(ACCEPTED),
            },
            "same_source_control": {
                "path": str(CONTROL.resolve()),
                "sha256": sha256(CONTROL),
            },
            "census_candidate": {
                "path": str(CANDIDATE.resolve()),
                "sha256": sha256(CANDIDATE),
            },
        },
        "correctness": {
            "control_repeat_cases": args.cases,
            "candidate_repeat_cases": args.cases,
            "move_score_node_pv_parity_cases": args.cases,
            "human_parity_cases": len(human_rows),
        },
        "timing": {
            "control_median_sum_ms": round(control_total_ms, 3),
            "candidate_median_sum_ms": round(candidate_total_ms, 3),
            "candidate_ratio": round(candidate_total_ms / control_total_ms, 6),
            "audit_wall_seconds": round(time.perf_counter() - started, 3),
        },
        "aggregate_census": summarize_census(totals),
        "human_positions": human_rows,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "REPETITION_CENSUS_RESULT "
        + json.dumps(
            {
                "output": str(args.output.resolve()),
                "sha256": sha256(args.output),
                "correctness": report["correctness"],
                "timing": report["timing"],
                "aggregate_census": report["aggregate_census"],
                "human_positions": human_rows,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
