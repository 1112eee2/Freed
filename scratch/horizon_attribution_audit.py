"""Measure root-split and selectivity effects without promoting a candidate.

This audit intentionally reuses previously rejected null-move and LMR ablations
only as measurement controls.  It never overwrites the accepted engine DLL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import parse_position
from makhos.native import NativeSearch
from makhos.parallel_native import ParallelNativeSearch


LIBRARIES = {
    "control": ROOT / "build" / "makhos_native_horizon_audit_control.dll",
    "no_null_measurement": ROOT / "build" / "makhos_native_horizon_audit_nonull.dll",
    "lmr_one_ply_measurement": ROOT / "build" / "makhos_native_horizon_audit_lmr1.dll",
}
HUMAN_POSITIONS = (
    {
        "id": "human-loss-ply-13",
        "ply": 13,
        "position": "B:BM20,22,23,25,27,28,29,31:RM2,3,5,7,8,9,11,15",
        "reversible_plies": 12,
        "played_move": "28-24",
    },
    {
        "id": "human-loss-ply-25",
        "ply": 25,
        "position": "B:BM19,20,22,27,31:RM2,3,5,10,11",
        "reversible_plies": 3,
        "played_move": "27-23",
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_payload(result) -> dict:
    telemetry = asdict(result.telemetry) if result.telemetry is not None else None
    return {
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "common_depth": result.common_depth,
        "nodes": result.nodes,
        "elapsed_ms": result.elapsed_ms,
        "pv": [move.notation for move in result.pv],
        "root_moves": [
            {
                "move": item.move.notation,
                "score": item.score,
                "depth": item.depth,
                "nodes": item.nodes,
                "pv": [move.notation for move in item.pv],
            }
            for item in result.root_moves
        ],
        "telemetry": telemetry,
    }


def read_corpus(path: Path, per_label: int) -> tuple[list[dict], dict[str, int]]:
    samples: list[dict] = []
    available: dict[str, int] = defaultdict(int)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("kind") != "sample":
                continue
            samples.append(row)
            available[row["label"]["classification"]] += 1

    selected: list[dict] = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        grouped[sample["label"]["classification"]].append(sample)
    for label in sorted(grouped):
        selected.extend(sorted(grouped[label], key=lambda row: row["id"])[:per_label])
    return selected, dict(sorted(available.items()))


def search_rows_single(library: Path, samples: Iterable[dict], depth: int) -> list[dict]:
    rows: list[dict] = []
    with NativeSearch(library, hash_power=20, persistent=True) as searcher:
        for sample in samples:
            state = parse_position(
                sample["position"],
                reversible_plies=int(sample.get("reversible_plies", 0)),
            )
            searcher.clear()
            result = searcher.search(
                state,
                depth=depth,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            rows.append({
                "id": sample["id"],
                "classification": sample["label"]["classification"],
                "piece_count": sample["piece_count"],
                "position": sample["position"],
                "reversible_plies": sample.get("reversible_plies", 0),
                "result": result_payload(result),
            })
    return rows


def search_rows_parallel(
    library: Path,
    samples: Iterable[dict],
    depth: int,
    *,
    threads: int,
    hash_mb: int,
) -> list[dict]:
    rows: list[dict] = []
    with ParallelNativeSearch(
        library,
        threads=threads,
        hash_mb=hash_mb,
    ) as searcher:
        for sample in samples:
            state = parse_position(
                sample["position"],
                reversible_plies=int(sample.get("reversible_plies", 0)),
            )
            searcher.clear()
            result = searcher.search(
                state,
                depth=depth,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            rows.append({
                "id": sample["id"],
                "classification": sample["label"]["classification"],
                "piece_count": sample["piece_count"],
                "position": sample["position"],
                "reversible_plies": sample.get("reversible_plies", 0),
                "result": result_payload(result),
            })
    return rows


def search_human_single(library: Path, depths: Iterable[int]) -> list[dict]:
    rows: list[dict] = []
    with NativeSearch(library, hash_power=20, persistent=True) as searcher:
        for sample in HUMAN_POSITIONS:
            state = parse_position(
                sample["position"],
                reversible_plies=sample["reversible_plies"],
            )
            for depth in depths:
                searcher.clear()
                result = searcher.search(
                    state,
                    depth=depth,
                    time_ms=30_000,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                rows.append({
                    **sample,
                    "requested_depth": depth,
                    "deadline_ms": 30_000,
                    "result": result_payload(result),
                })
    return rows


def search_human_parallel(
    library: Path,
    depth: int,
    *,
    threads: int,
    hash_mb: int,
) -> list[dict]:
    rows: list[dict] = []
    with ParallelNativeSearch(
        library,
        threads=threads,
        hash_mb=hash_mb,
    ) as searcher:
        for sample in HUMAN_POSITIONS:
            state = parse_position(
                sample["position"],
                reversible_plies=sample["reversible_plies"],
            )
            searcher.clear()
            result = searcher.search(
                state,
                depth=depth,
                time_ms=30_000,
                no_progress_plies=80,
                repetition_limit=3,
            )
            rows.append({
                **sample,
                "requested_depth": depth,
                "deadline_ms": 30_000,
                "result": result_payload(result),
            })
    return rows


def geometric_mean(values: Iterable[float]) -> float | None:
    positive = [value for value in values if value > 0]
    if not positive:
        return None
    return math.exp(sum(math.log(value) for value in positive) / len(positive))


def compare_rows(control: list[dict], candidate: list[dict]) -> dict:
    control_by_id = {row["id"]: row for row in control}
    candidate_by_id = {row["id"]: row for row in candidate}
    ids = sorted(control_by_id.keys() & candidate_by_id.keys())
    move_matches = 0
    score_matches = 0
    node_ratios: list[float] = []
    time_ratios: list[float] = []
    qnode_ratios: list[float] = []
    differences: list[dict] = []
    for item_id in ids:
        first = control_by_id[item_id]["result"]
        second = candidate_by_id[item_id]["result"]
        move_matches += first["move"] == second["move"]
        score_matches += first["score"] == second["score"]
        if first["nodes"]:
            node_ratios.append(second["nodes"] / first["nodes"])
        if first["elapsed_ms"]:
            time_ratios.append(second["elapsed_ms"] / first["elapsed_ms"])
        first_qnodes = (first["telemetry"] or {}).get("qnodes", 0)
        second_qnodes = (second["telemetry"] or {}).get("qnodes", 0)
        if first_qnodes:
            qnode_ratios.append(second_qnodes / first_qnodes)
        if first["move"] != second["move"] or first["score"] != second["score"]:
            differences.append({
                "id": item_id,
                "control_move": first["move"],
                "candidate_move": second["move"],
                "control_score": first["score"],
                "candidate_score": second["score"],
            })
    return {
        "positions": len(ids),
        "same_move": move_matches,
        "same_score": score_matches,
        "node_geomean_ratio": geometric_mean(node_ratios),
        "elapsed_geomean_ratio": geometric_mean(time_ratios),
        "qnode_geomean_ratio": geometric_mean(qnode_ratios),
        "differences": differences,
    }


def telemetry_totals(rows: Iterable[dict]) -> dict:
    totals: dict[str, int] = defaultdict(int)
    nodes = 0
    for row in rows:
        result = row["result"]
        nodes += result["nodes"]
        for key, value in (result["telemetry"] or {}).items():
            totals[key] += value
    payload = dict(sorted(totals.items()))
    payload["nodes"] = nodes
    payload["qnode_share"] = totals["qnodes"] / nodes if nodes else None
    payload["null_cutoff_rate"] = (
        totals["null_cutoffs"] / totals["null_attempts"]
        if totals["null_attempts"]
        else None
    )
    payload["lmr_research_share"] = (
        totals["lmr_researches"] / totals["pvs_researches"]
        if totals["pvs_researches"]
        else None
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v4.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "horizon_attribution_audit_20260823.json",
    )
    parser.add_argument("--per-label", type=int, default=12)
    parser.add_argument("--corpus-depth", type=int, default=15)
    parser.add_argument("--human-depth", type=int, action="append", default=None)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--hash-mb", type=int, default=512)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    depths = tuple(args.human_depth or (18, 20, 22))
    for path in LIBRARIES.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    samples, available = read_corpus(args.corpus, args.per_label)
    started = time.perf_counter()
    single: dict[str, list[dict]] = {}
    for name, library in LIBRARIES.items():
        single[name] = search_rows_single(library, samples, args.corpus_depth)

    parallel_control = search_rows_parallel(
        LIBRARIES["control"],
        samples,
        args.corpus_depth,
        threads=args.threads,
        hash_mb=args.hash_mb,
    )
    human_single = {
        name: search_human_single(library, depths)
        for name, library in LIBRARIES.items()
    }
    human_parallel = {
        name: search_human_parallel(
            library,
            max(depths),
            threads=args.threads,
            hash_mb=args.hash_mb,
        )
        for name, library in LIBRARIES.items()
    }

    payload = {
        "format": "thai-makhos-horizon-attribution-v1",
        "purpose": "measurement-only; rejected ablations are not promotion candidates",
        "corpus": str(args.corpus.resolve()),
        "corpus_sha256": sha256(args.corpus),
        "corpus_available_by_classification": available,
        "selected_positions": len(samples),
        "selected_by_classification": dict(sorted(
            (label, sum(sample["label"]["classification"] == label for sample in samples))
            for label in available
        )),
        "corpus_depth": args.corpus_depth,
        "human_depths": depths,
        "threads": args.threads,
        "hash_mb": args.hash_mb,
        "rules": {"no_progress_plies": 80, "repetition_limit": 3},
        "history_note": "position clocks retained; prior repetition history unavailable",
        "libraries": {
            name: {"path": str(path.resolve()), "sha256": sha256(path)}
            for name, path in LIBRARIES.items()
        },
        "summary": {
            "no_null_vs_control_single": compare_rows(
                single["control"], single["no_null_measurement"]
            ),
            "lmr_one_ply_vs_control_single": compare_rows(
                single["control"], single["lmr_one_ply_measurement"]
            ),
            "root_split_vs_control_single": compare_rows(
                single["control"], parallel_control
            ),
            "telemetry_single": {
                name: telemetry_totals(rows) for name, rows in single.items()
            },
            "telemetry_root_split_control": telemetry_totals(parallel_control),
        },
        "corpus_results_single": single,
        "corpus_results_root_split_control": parallel_control,
        "human_results_single": human_single,
        "human_results_root_split": human_parallel,
        "wall_seconds": time.perf_counter() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    human_brief = {
        architecture: {
            name: [
                {
                    "id": row["id"],
                    "requested_depth": row["requested_depth"],
                    "move": row["result"]["move"],
                    "score": row["result"]["score"],
                    "depth": row["result"]["depth"],
                    "nodes": row["result"]["nodes"],
                    "elapsed_ms": row["result"]["elapsed_ms"],
                }
                for row in rows
            ]
            for name, rows in results.items()
        }
        for architecture, results in (
            ("single", human_single),
            ("root_split", human_parallel),
        )
    }
    print(json.dumps({
        "output": str(args.output.resolve()),
        "selected_positions": len(samples),
        "wall_seconds": payload["wall_seconds"],
        "summary": payload["summary"],
        "human": human_brief,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
