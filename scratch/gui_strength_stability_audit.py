"""Rebaseline production 1-second search variance under runtime isolation."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import parse_position  # noqa: E402
from makhos.native import (  # noqa: E402
    NativeSearch,
    hash_megabytes_for_power,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.parallel_native import ParallelNativeSearch  # noqa: E402
from makhos.workload_isolation import BatchWorkLease  # noqa: E402


ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
EXPECTED_ACCEPTED_SHA256 = (
    "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def trial_payload(result) -> dict:
    return {
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "common_depth": result.common_depth,
        "nodes": result.nodes,
        "elapsed_ms": result.elapsed_ms,
        "pv": [move.notation for move in result.pv],
    }


def summarize_trials(trials: list[dict], reference_move: str) -> dict:
    moves = Counter(trial["move"] for trial in trials)
    return {
        "move_counts": dict(sorted(moves.items())),
        "distinct_moves": len(moves),
        "reference_move": reference_move,
        "reference_matches": moves[reference_move],
        "reference_match_percent": 100.0 * moves[reference_move] / len(trials),
        "depth_min": min(trial["depth"] for trial in trials),
        "depth_max": max(trial["depth"] for trial in trials),
        "depth_mean": statistics.fmean(trial["depth"] for trial in trials),
        "nodes_min": min(trial["nodes"] for trial in trials),
        "nodes_max": max(trial["nodes"] for trial in trials),
        "elapsed_mean_ms": statistics.fmean(
            trial["elapsed_ms"] for trial in trials
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--regressions",
        type=Path,
        default=ROOT / "corpora" / "positional_regressions.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "gui_strength_stability_1s_20260824.json",
    )
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--time-ms", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--hash-mb", type=int, default=512)
    args = parser.parse_args()
    if args.trials < 2 or args.time_ms < 10 or args.threads < 2:
        parser.error("audit requires at least two trials and a parallel backend")
    if sha256(ACCEPTED) != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity mismatch")

    corpus = json.loads(args.regressions.read_text(encoding="utf-8"))
    cases = corpus["cases"]
    entry_bytes = native_tt_entry_bytes(ACCEPTED)
    single_power = hash_power_for_megabytes(
        args.hash_mb,
        partitions=1,
        entry_bytes=entry_bytes,
    )
    single_allocated = hash_megabytes_for_power(
        single_power,
        partitions=1,
        entry_bytes=entry_bytes,
    )
    results = []
    started = time.perf_counter()
    with BatchWorkLease(ROOT):
        with NativeSearch(
            ACCEPTED,
            hash_power=single_power,
            persistent=True,
        ) as single, ParallelNativeSearch(
            ACCEPTED,
            threads=args.threads,
            hash_mb=args.hash_mb,
        ) as parallel:
            for case in cases:
                state = parse_position(
                    case["position"],
                    reversible_plies=int(case["reversible_plies"]),
                )
                repetition_limit = (
                    None
                    if case["rules_profile"] == "external-no-repetition"
                    else 3
                )
                reference_move = case["evidence"]["long"]["best_move"]
                backend_trials = {"single": [], "root_split": []}
                for _trial in range(args.trials):
                    single.clear()
                    backend_trials["single"].append(trial_payload(single.search(
                        state,
                        depth=64,
                        time_ms=args.time_ms,
                        no_progress_plies=80,
                        repetition_limit=repetition_limit,
                    )))
                    parallel.clear()
                    backend_trials["root_split"].append(trial_payload(parallel.search(
                        state,
                        depth=64,
                        time_ms=args.time_ms,
                        no_progress_plies=80,
                        repetition_limit=repetition_limit,
                    )))
                results.append({
                    "id": case["id"],
                    "position": case["position"],
                    "reversible_plies": case["reversible_plies"],
                    "rules_profile": case["rules_profile"],
                    "reference_semantics": "longer accepted search; not solved truth",
                    "single": {
                        "summary": summarize_trials(
                            backend_trials["single"], reference_move
                        ),
                        "trials": backend_trials["single"],
                    },
                    "root_split": {
                        "summary": summarize_trials(
                            backend_trials["root_split"], reference_move
                        ),
                        "trials": backend_trials["root_split"],
                    },
                })

    payload = {
        "format": "thai-makhos-gui-strength-stability-audit-v1",
        "accepted_library": str(ACCEPTED.resolve()),
        "accepted_library_sha256": sha256(ACCEPTED),
        "regressions": str(args.regressions.resolve()),
        "regressions_sha256": sha256(args.regressions),
        "runtime_isolation": "batch lease held; interactive server excluded",
        "fresh_state_protocol": "clear backend before every timed trial",
        "settings": {
            "trials_per_case_per_backend": args.trials,
            "time_ms": args.time_ms,
            "threads": args.threads,
            "hash_mb_total_per_backend": args.hash_mb,
            "single_allocated_hash_mb": single_allocated,
            "root_split_allocated_hash_mb": parallel.allocated_hash_mb,
        },
        "cases": results,
        "wall_seconds": time.perf_counter() - started,
    }
    atomic_write_json(args.output.resolve(), payload)
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
