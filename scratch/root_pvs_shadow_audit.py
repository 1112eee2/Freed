"""Deterministic readiness audit for native authoritative root-PVS shadow scouts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, format_position, legal_moves
from makhos.native import NativeRootPvsShadowSearch, NativeSearch
from makhos.native_benchmark import generate_native_benchmark_cases


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        type=Path,
        default=ROOT / "build" / "makhos_native_root_pvs_shadow_candidate.dll",
    )
    parser.add_argument("--count", type=int, default=96)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--hash-mb", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20261061)
    parser.add_argument("--allow-result-mismatches", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "root_pvs_shadow_audit_20260824.json",
    )
    args = parser.parse_args()
    if args.count < 1 or args.depth < 1 or args.repetitions < 1:
        parser.error("count, depth, and repetitions must be positive")

    candidate = args.candidate.resolve()
    cases = generate_native_benchmark_cases(count=args.count, seed=args.seed)
    rows: list[dict] = []
    with NativeRootPvsShadowSearch(
        candidate,
        threads=args.threads,
        hash_mb=args.hash_mb,
    ) as shadow:
        initial_stats = shadow.stats
        behavior_preserving = shadow.backend.endswith("shadow-candidate")
        with NativeSearch(
            candidate,
            hash_power=initial_stats.main_hash_power,
            persistent=True,
        ) as main_search:
            for case in cases:
                repetitions: list[dict] = []
                for repetition in range(args.repetitions):
                    engines = ("shadow", "main")
                    if (case.index + repetition) % 2 == 0:
                        engines = tuple(reversed(engines))
                    results: dict[str, tuple] = {}
                    for label in engines:
                        engine = shadow if label == "shadow" else main_search
                        engine.clear()
                        started = time.perf_counter()
                        result = engine.search(
                            case.state,
                            depth=args.depth,
                            time_ms=None,
                            no_progress_plies=DEFAULT_RULES.no_progress_plies,
                            repetition_limit=DEFAULT_RULES.repetition_limit,
                            history=case.history,
                        )
                        wall_ms = (time.perf_counter() - started) * 1000.0
                        stats = asdict(shadow.stats) if label == "shadow" else None
                        results[label] = (result, wall_ms, stats)
                    actual, shadow_ms, stats = results["shadow"]
                    expected, main_ms, _ = results["main"]
                    parity_match = not (
                        actual.move != expected.move
                        or actual.score != expected.score
                        or actual.pv != expected.pv
                        or actual.depth != expected.depth
                        or (behavior_preserving and actual.nodes != expected.nodes)
                    )
                    if not parity_match and not args.allow_result_mismatches:
                        raise RuntimeError(
                            f"authoritative parity failed on case {case.index} "
                            f"repetition {repetition + 1}: "
                            f"candidate={actual.move.notation}/{actual.score}/"
                            f"d{actual.depth}/n{actual.nodes}/"
                            f"pv={[move.notation for move in actual.pv]}; "
                            f"main={expected.move.notation}/{expected.score}/"
                            f"d{expected.depth}/n{expected.nodes}/"
                            f"pv={[move.notation for move in expected.pv]}"
                        )
                    repetitions.append(
                        {
                            "shadow_wall_ms": shadow_ms,
                            "main_wall_ms": main_ms,
                            "shadow_nodes": actual.nodes,
                            "main_nodes": expected.nodes,
                            "parity_match": parity_match,
                            "shadow_result": {
                                "move": actual.move.notation,
                                "score": actual.score,
                                "depth": actual.depth,
                                "nodes": actual.nodes,
                                "pv": [move.notation for move in actual.pv],
                            },
                            "main_result": {
                                "move": expected.move.notation,
                                "score": expected.score,
                                "depth": expected.depth,
                                "nodes": expected.nodes,
                                "pv": [move.notation for move in expected.pv],
                            },
                            "stats": stats,
                        }
                    )
                first_result = results["shadow"][0]
                rows.append(
                    {
                        "case": case.index,
                        "target_plies": case.target_plies,
                        "position": format_position(case.state),
                        "legal_moves": len(legal_moves(case.state)),
                        "move": first_result.move.notation,
                        "score": first_result.score,
                        "depth": first_result.depth,
                        "nodes": first_result.nodes,
                        "repetitions": repetitions,
                    }
                )

        final_memory = shadow.memory_bytes

    stats_rows = [
        repetition["stats"]
        for row in rows
        for repetition in row["repetitions"]
    ]
    shadow_times = [
        repetition["shadow_wall_ms"]
        for row in rows
        for repetition in row["repetitions"]
    ]
    main_times = [
        repetition["main_wall_ms"]
        for row in rows
        for repetition in row["repetitions"]
    ]
    started = sum(item["scout_tasks_started"] for item in stats_rows)
    completed = sum(item["scout_tasks_completed"] for item in stats_rows)
    ready = sum(item["scout_ready_before_main"] for item in stats_rows)
    helper_nodes = sum(item["helper_nodes"] for item in stats_rows)
    main_nodes = sum(item["main_nodes"] for item in stats_rows)
    total_wait_us = sum(item["main_wait_us"] for item in stats_rows)
    summary = {
        "parity_cases": len(rows) * args.repetitions,
        "parity_failures": sum(
            not repetition["parity_match"]
            for row in rows
            for repetition in row["repetitions"]
        ),
        "shadow_total_ms": sum(shadow_times),
        "main_total_ms": sum(main_times),
        "shadow_time_ratio": sum(shadow_times) / sum(main_times),
        "node_equal_cases": sum(
            repetition["shadow_nodes"] == repetition["main_nodes"]
            for row in rows
            for repetition in row["repetitions"]
        ),
        "authoritative_node_ratio": (
            sum(
                repetition["shadow_nodes"]
                for row in rows
                for repetition in row["repetitions"]
            )
            / sum(
                repetition["main_nodes"]
                for row in rows
                for repetition in row["repetitions"]
            )
        ),
        "median_shadow_ms": statistics.median(shadow_times),
        "median_main_ms": statistics.median(main_times),
        "scout_tasks_started": started,
        "scout_tasks_completed": completed,
        "scout_completion_rate": completed / started if started else 0.0,
        "scout_ready_before_main": ready,
        "ready_per_completed": ready / completed if completed else 0.0,
        "scout_fail_highs": sum(item["scout_fail_highs"] for item in stats_rows),
        "scout_ready_fail_highs": sum(
            item["scout_ready_fail_highs"] for item in stats_rows
        ),
        "scout_ready_above_current_alpha": sum(
            item["scout_ready_above_current_alpha"] for item in stats_rows
        ),
        "scout_tasks_aborted": sum(
            item["scout_tasks_aborted"] for item in stats_rows
        ),
        "worker_failures": sum(item["worker_failures"] for item in stats_rows),
        "main_nodes": main_nodes,
        "helper_nodes": helper_nodes,
        "helper_to_main_node_ratio": helper_nodes / main_nodes if main_nodes else 0.0,
        "main_wait_ms": total_wait_us / 1000.0,
        "main_wait_share": (total_wait_us / 1000.0) / sum(shadow_times),
        "final_memory_bytes": final_memory,
    }
    payload = {
        "format": "thai-makhos-root-pvs-shadow-audit-v1",
        "status": "measurement-only",
        "backend": shadow.backend,
        "behavior_preserving_node_gate": behavior_preserving,
        "candidate": str(candidate),
        "candidate_sha256": sha256(candidate),
        "accepted_control": str((ROOT / "build" / "makhos_native_accepted.dll").resolve()),
        "accepted_control_sha256": sha256(
            ROOT / "build" / "makhos_native_accepted.dll"
        ),
        "source_sha256": sha256(ROOT / "native" / "makhos_native.c"),
        "python_bridge_sha256": sha256(ROOT / "makhos" / "native.py"),
        "settings": {
            "count": args.count,
            "depth": args.depth,
            "repetitions": args.repetitions,
            "threads": args.threads,
            "hash_mb": args.hash_mb,
            "seed": args.seed,
            "main_hash_power": initial_stats.main_hash_power,
            "helper_hash_power": initial_stats.helper_hash_power,
            "allocated_tt_bytes": initial_stats.allocated_tt_bytes,
        },
        "summary": summary,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, payload)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
