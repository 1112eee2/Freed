"""Compare production root split with ordinary search against deeper stability.

The deeper single-thread result is an observational search reference, not a
solved best-move label.  This script changes no production search setting.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import parse_position
from makhos.native import (
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.parallel_native import ParallelNativeSearch
from scratch.horizon_attribution_audit import (
    HUMAN_POSITIONS,
    LIBRARIES,
    read_corpus,
    result_payload,
    sha256,
)


CONTROL = LIBRARIES["control"]


def state_for(sample: dict):
    return parse_position(
        sample["position"],
        reversible_plies=int(sample.get("reversible_plies", 0)),
    )


def run_reference(
    samples: list[dict],
    depths: tuple[int, int],
    *,
    hash_power: int,
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {sample["id"]: [] for sample in samples}
    with NativeSearch(CONTROL, hash_power=hash_power, persistent=True) as searcher:
        for sample in samples:
            state = state_for(sample)
            for depth in depths:
                searcher.clear()
                result = searcher.search(
                    state,
                    depth=depth,
                    time_ms=30_000,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                results[sample["id"]].append({
                    "requested_depth": depth,
                    "result": result_payload(result),
                })
    return results


def run_single_timed(
    samples: list[dict],
    budgets: tuple[int, ...],
    *,
    hash_power: int,
) -> dict[str, dict[str, dict]]:
    results: dict[str, dict[str, dict]] = defaultdict(dict)
    with NativeSearch(CONTROL, hash_power=hash_power, persistent=True) as searcher:
        for budget in budgets:
            for sample in samples:
                searcher.clear()
                result = searcher.search(
                    state_for(sample),
                    depth=64,
                    time_ms=budget,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                results[str(budget)][sample["id"]] = result_payload(result)
    return dict(results)


def run_root_split_timed(
    samples: list[dict],
    budgets: tuple[int, ...],
    *,
    threads: int,
    hash_mb: int,
) -> dict[str, dict[str, dict]]:
    results: dict[str, dict[str, dict]] = defaultdict(dict)
    with ParallelNativeSearch(
        CONTROL,
        threads=threads,
        hash_mb=hash_mb,
    ) as searcher:
        for budget in budgets:
            for sample in samples:
                searcher.clear()
                result = searcher.search(
                    state_for(sample),
                    depth=64,
                    time_ms=budget,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                results[str(budget)][sample["id"]] = result_payload(result)
    return dict(results)


def stable_references(reference: dict[str, list[dict]]) -> dict[str, dict]:
    stable: dict[str, dict] = {}
    for sample_id, searches in reference.items():
        if len(searches) != 2:
            continue
        first, second = searches
        if (
            first["result"]["depth"] == first["requested_depth"]
            and second["result"]["depth"] == second["requested_depth"]
            and first["result"]["move"] == second["result"]["move"]
        ):
            stable[sample_id] = second["result"]
    return stable


def summarize_budget(
    samples: list[dict],
    stable: dict[str, dict],
    single: dict[str, dict],
    root_split: dict[str, dict],
) -> dict:
    sample_by_id = {sample["id"]: sample for sample in samples}
    counts = {
        "stable_positions": len(stable),
        "single_matches_reference": 0,
        "root_split_matches_reference": 0,
        "both_match": 0,
        "single_only_matches": 0,
        "root_split_only_matches": 0,
        "neither_matches": 0,
        "architectures_same_move": 0,
    }
    single_depths: list[int] = []
    split_depths: list[int] = []
    single_nodes: list[int] = []
    split_nodes: list[int] = []
    disagreements: list[dict] = []
    by_classification: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for sample_id, deep in stable.items():
        one = single[sample_id]
        many = root_split[sample_id]
        one_match = one["move"] == deep["move"]
        many_match = many["move"] == deep["move"]
        same = one["move"] == many["move"]
        counts["single_matches_reference"] += one_match
        counts["root_split_matches_reference"] += many_match
        counts["both_match"] += one_match and many_match
        counts["single_only_matches"] += one_match and not many_match
        counts["root_split_only_matches"] += many_match and not one_match
        counts["neither_matches"] += not one_match and not many_match
        counts["architectures_same_move"] += same
        single_depths.append(one["depth"])
        split_depths.append(many["depth"])
        single_nodes.append(one["nodes"])
        split_nodes.append(many["nodes"])
        label = sample_by_id[sample_id]["label"]["classification"]
        class_counts = by_classification[label]
        class_counts["positions"] += 1
        class_counts["single_matches"] += one_match
        class_counts["root_split_matches"] += many_match
        if not same:
            disagreements.append({
                "id": sample_id,
                "classification": label,
                "reference_move": deep["move"],
                "single_move": one["move"],
                "single_depth": one["depth"],
                "root_split_move": many["move"],
                "root_split_depth": many["depth"],
            })
    counts.update({
        "single_mean_depth": statistics.fmean(single_depths) if single_depths else None,
        "root_split_mean_depth": statistics.fmean(split_depths) if split_depths else None,
        "single_total_nodes": sum(single_nodes),
        "root_split_total_nodes": sum(split_nodes),
        "by_classification": {
            label: dict(values) for label, values in sorted(by_classification.items())
        },
        "disagreements": disagreements,
    })
    return counts


def brief_human(results: dict[str, dict[str, dict]]) -> dict[str, list[dict]]:
    brief: dict[str, list[dict]] = {}
    for budget, rows in results.items():
        brief[budget] = [
            {
                "id": sample["id"],
                "move": rows[sample["id"]]["move"],
                "score": rows[sample["id"]]["score"],
                "depth": rows[sample["id"]]["depth"],
                "nodes": rows[sample["id"]]["nodes"],
                "elapsed_ms": rows[sample["id"]]["elapsed_ms"],
            }
            for sample in HUMAN_POSITIONS
        ]
    return brief


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
        default=ROOT / "build" / "root_architecture_quality_audit_20260823.json",
    )
    parser.add_argument("--per-label", type=int, default=12)
    parser.add_argument("--reference-depth", type=int, action="append", default=None)
    parser.add_argument("--budget-ms", type=int, action="append", default=None)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--hash-mb", type=int, default=512)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reference_depths = tuple(args.reference_depth or (17, 19))
    if len(reference_depths) != 2:
        raise ValueError("exactly two --reference-depth values are required")
    budgets = tuple(args.budget_ms or (300, 1000))
    samples, available = read_corpus(args.corpus, args.per_label)
    entry_bytes = native_tt_entry_bytes(CONTROL)
    single_hash_power = hash_power_for_megabytes(
        args.hash_mb,
        entry_bytes=entry_bytes,
    )
    started = time.perf_counter()

    reference = run_reference(
        samples,
        reference_depths,
        hash_power=single_hash_power,
    )
    stable = stable_references(reference)
    single = run_single_timed(samples, budgets, hash_power=single_hash_power)
    root_split = run_root_split_timed(
        samples,
        budgets,
        threads=args.threads,
        hash_mb=args.hash_mb,
    )
    human_samples = [
        {
            **sample,
            "label": {"classification": "human-diagnostic"},
            "piece_count": len(sample["position"].split(",")),
        }
        for sample in HUMAN_POSITIONS
    ]
    human_single = run_single_timed(
        human_samples,
        budgets,
        hash_power=single_hash_power,
    )
    human_root_split = run_root_split_timed(
        human_samples,
        budgets,
        threads=args.threads,
        hash_mb=args.hash_mb,
    )

    summary = {
        str(budget): summarize_budget(
            samples,
            stable,
            single[str(budget)],
            root_split[str(budget)],
        )
        for budget in budgets
    }
    payload = {
        "format": "thai-makhos-root-architecture-quality-v1",
        "reference_semantics": (
            "two-depth single-thread move stability; observational, not solved truth"
        ),
        "corpus": str(args.corpus.resolve()),
        "corpus_sha256": sha256(args.corpus),
        "corpus_available_by_classification": available,
        "selected_positions": len(samples),
        "reference_depths": reference_depths,
        "stable_reference_positions": len(stable),
        "budgets_ms": budgets,
        "threads": args.threads,
        "hash_mb": args.hash_mb,
        "single_hash_power": single_hash_power,
        "native_library": str(CONTROL.resolve()),
        "native_library_sha256": sha256(CONTROL),
        "rules": {"no_progress_plies": 80, "repetition_limit": 3},
        "history_note": "position clocks retained; prior repetition history unavailable",
        "summary": summary,
        "reference": reference,
        "timed_single": single,
        "timed_root_split": root_split,
        "human_timed_single": human_single,
        "human_timed_root_split": human_root_split,
        "wall_seconds": time.perf_counter() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output.resolve()),
        "wall_seconds": payload["wall_seconds"],
        "selected_positions": len(samples),
        "stable_reference_positions": len(stable),
        "summary": {
            budget: {key: value for key, value in values.items() if key != "disagreements"}
            for budget, values in summary.items()
        },
        "human_single": brief_human(human_single),
        "human_root_split": brief_human(human_root_split),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
