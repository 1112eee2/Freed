"""Audit a hash-budgeted branch-count route without changing production play.

The observational reference is the already locked two-depth single-thread
reference in ``root_architecture_quality_audit_20260823.json``.  This harness
reruns the accepted DLL at one fixed clock with two actual backends:

* ordinary single-thread search with a 160 MiB allocation; and
* the production 12-thread/512-MiB Python root splitter.

The predeclared route uses the single-thread result only when the root has at
least eight legal moves.  Reference moves are deeper-search stability labels,
not solved best moves.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import parse_position
from makhos.native import (
    NativeSearch,
    hash_megabytes_for_power,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.parallel_native import ParallelNativeSearch
from scratch.adaptive_native_candidate import AdaptiveNativeSearch
from scratch.horizon_attribution_audit import read_corpus, result_payload, sha256


ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
EXPECTED_ACCEPTED_SHA256 = (
    "feedd39cf16e5f5abc236452be897abe1ecf26b8ba7adcda4a25022b868c3ddd"
)
EXPECTED_REFERENCE_SHA256 = (
    "a73ff15e21afdf634ce099428c519d28228f305088dbc93c8c0e7cda7b6f3a52"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v4.jsonl",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=ROOT / "build" / "root_architecture_quality_audit_20260823.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "adaptive_root_hash_routing_audit_20260823.json",
    )
    parser.add_argument("--budget-ms", type=int, default=1000)
    parser.add_argument("--single-hash-mb", type=int, default=160)
    parser.add_argument("--split-hash-mb", type=int, default=512)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--route-min-legal", type=int, default=8)
    parser.add_argument("--per-label", type=int, default=12)
    return parser.parse_args()


def state_for(sample: dict):
    return parse_position(
        sample["position"],
        reversible_plies=int(sample.get("reversible_plies", 0)),
    )


def stable_references(payload: dict) -> dict[str, dict]:
    stable: dict[str, dict] = {}
    for sample_id, searches in payload["reference"].items():
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


def summarize(
    samples: list[dict],
    stable: dict[str, dict],
    single: dict[str, dict],
    split: dict[str, dict],
    *,
    route_min_legal: int,
) -> dict:
    by_id = {sample["id"]: sample for sample in samples}
    counts = {
        "positions": 0,
        "single_matches_reference": 0,
        "root_split_matches_reference": 0,
        "adaptive_matches_reference": 0,
        "adaptive_uses_single": 0,
        "adaptive_uses_root_split": 0,
    }
    depths = {"single": [], "root_split": [], "adaptive": []}
    nodes = {"single": 0, "root_split": 0, "adaptive": 0}
    rows: list[dict] = []
    for sample_id, reference in stable.items():
        sample = by_id[sample_id]
        legal_count = len(sample["legal_moves"])
        one = single[sample_id]
        many = split[sample_id]
        route = "single" if legal_count >= route_min_legal else "root_split"
        chosen = one if route == "single" else many
        counts["positions"] += 1
        counts["single_matches_reference"] += one["move"] == reference["move"]
        counts["root_split_matches_reference"] += many["move"] == reference["move"]
        counts["adaptive_matches_reference"] += chosen["move"] == reference["move"]
        counts[f"adaptive_uses_{route}"] += 1
        depths["single"].append(one["depth"])
        depths["root_split"].append(many["depth"])
        depths["adaptive"].append(chosen["depth"])
        nodes["single"] += one["nodes"]
        nodes["root_split"] += many["nodes"]
        nodes["adaptive"] += chosen["nodes"]
        rows.append({
            "id": sample_id,
            "classification": sample["label"]["classification"],
            "legal_moves": legal_count,
            "reference_move": reference["move"],
            "single": one,
            "root_split": many,
            "route": route,
            "adaptive_move": chosen["move"],
            "adaptive_matches_reference": chosen["move"] == reference["move"],
        })
    counts.update({
        "mean_depth": {
            key: statistics.fmean(values) for key, values in depths.items()
        },
        "total_nodes": nodes,
        "rows": rows,
    })
    return counts


def main() -> None:
    args = parse_args()
    if sha256(ACCEPTED).lower() != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity mismatch")
    if sha256(args.reference).lower() != EXPECTED_REFERENCE_SHA256:
        raise RuntimeError("locked reference artifact identity mismatch")
    if args.route_min_legal != 8:
        raise ValueError("this predeclared audit requires --route-min-legal 8")

    samples, available = read_corpus(args.corpus, args.per_label)
    reference_payload = json.loads(args.reference.read_text(encoding="utf-8"))
    stable = stable_references(reference_payload)
    selected_ids = {sample["id"] for sample in samples}
    if not set(stable).issubset(selected_ids):
        raise RuntimeError("reference IDs do not match the selected corpus")

    entry_bytes = native_tt_entry_bytes(ACCEPTED)
    single_hash_power = hash_power_for_megabytes(
        args.single_hash_mb,
        partitions=1,
        entry_bytes=entry_bytes,
    )
    single_allocated_mb = hash_megabytes_for_power(
        single_hash_power,
        partitions=1,
        entry_bytes=entry_bytes,
    )
    started = time.perf_counter()
    single: dict[str, dict] = {}
    with NativeSearch(
        ACCEPTED,
        hash_power=single_hash_power,
        persistent=True,
    ) as searcher:
        for sample in samples:
            searcher.clear()
            single[sample["id"]] = result_payload(searcher.search(
                state_for(sample),
                depth=64,
                time_ms=args.budget_ms,
                no_progress_plies=80,
                repetition_limit=3,
            ))

    split: dict[str, dict] = {}
    with ParallelNativeSearch(
        ACCEPTED,
        threads=args.threads,
        hash_mb=args.split_hash_mb,
    ) as searcher:
        split_allocated_mb = searcher.allocated_hash_mb
        for sample in samples:
            searcher.clear()
            split[sample["id"]] = result_payload(searcher.search(
                state_for(sample),
                depth=64,
                time_ms=args.budget_ms,
                no_progress_plies=80,
                repetition_limit=3,
            ))

    summary = summarize(
        samples,
        stable,
        single,
        split,
        route_min_legal=args.route_min_legal,
    )
    actual: dict[str, dict] = {}
    actual_backend: dict[str, str] = {}
    with AdaptiveNativeSearch(
        ACCEPTED,
        threads=args.threads,
        hash_mb=args.split_hash_mb,
        route_min_legal=args.route_min_legal,
        single_hash_mb=args.single_hash_mb,
    ) as searcher:
        adaptive_allocated_mb = searcher.allocated_hash_mb
        for sample in samples:
            searcher.clear()
            actual[sample["id"]] = result_payload(searcher.search(
                state_for(sample),
                depth=64,
                time_ms=args.budget_ms,
                no_progress_plies=80,
                repetition_limit=3,
            ))
            actual_backend[sample["id"]] = str(searcher.last_backend)
    actual_rows = []
    actual_matches = 0
    actual_matches_simulated = 0
    actual_depths = []
    actual_nodes = 0
    for row in summary["rows"]:
        result = actual[row["id"]]
        matches_reference = result["move"] == row["reference_move"]
        matches_simulated = result["move"] == row["adaptive_move"]
        actual_matches += matches_reference
        actual_matches_simulated += matches_simulated
        actual_depths.append(result["depth"])
        actual_nodes += result["nodes"]
        actual_rows.append({
            "id": row["id"],
            "backend": actual_backend[row["id"]],
            "result": result,
            "matches_reference": matches_reference,
            "matches_simulated_route": matches_simulated,
        })
    summary["actual_adaptive"] = {
        "matches_reference": actual_matches,
        "matches_simulated_route": actual_matches_simulated,
        "mean_depth": statistics.fmean(actual_depths),
        "total_nodes": actual_nodes,
        "rows": actual_rows,
    }
    payload = {
        "format": "thai-makhos-adaptive-root-hash-routing-audit-v1",
        "reference_semantics": (
            "locked depth-17/depth-19 single-thread move stability; not solved truth"
        ),
        "accepted_library": str(ACCEPTED.resolve()),
        "accepted_sha256": sha256(ACCEPTED),
        "corpus": str(args.corpus.resolve()),
        "corpus_sha256": sha256(args.corpus),
        "available_by_classification": available,
        "selected_positions": len(samples),
        "stable_reference_positions": len(stable),
        "reference": str(args.reference.resolve()),
        "reference_sha256": sha256(args.reference),
        "settings": {
            "budget_ms": args.budget_ms,
            "threads": args.threads,
            "single_hash_requested_mb": args.single_hash_mb,
            "single_hash_allocated_mb": single_allocated_mb,
            "root_split_hash_requested_mb": args.split_hash_mb,
            "root_split_hash_allocated_mb": split_allocated_mb,
            "adaptive_total_hash_allocated_mb": adaptive_allocated_mb,
            "route_min_legal": args.route_min_legal,
            "repetition_limit": 3,
            "no_progress_plies": 80,
        },
        "summary": summary,
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
        "settings": payload["settings"],
        "summary": {
            key: (
                {item_key: item_value for item_key, item_value in value.items()
                 if item_key != "rows"}
                if key == "actual_adaptive"
                else value
            )
            for key, value in summary.items()
            if key != "rows"
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
