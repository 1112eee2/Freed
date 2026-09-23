#!/usr/bin/env python3
"""Balanced A/B pilot benchmark for Native Lazy SMP: Move-Hints ON vs OFF."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import initial_state, parse_position
from makhos.native import NativeLazySmpSearch

CANDIDATE = ROOT / "build" / "lazy_smp_candidate_v1" / "makhos_native_lazy_smp_candidate_v1.dll"
NNUE_MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
OUTPUT_PATH = ROOT / "benchmarks" / "results" / "lazy_smp_hints_ab_pilot.json"

POSITIONS = [
    ("initial", initial_state()),
    ("tactical", parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2")),
    ("middlegame", parse_position("B:BM14,20,22,23,27,31,32:RM2,3,5,7,11,13,15")),
    ("multi_capture", parse_position("B:BM23,26:BK15:RM13,14,19,21,27")),
    ("endgame_promo", parse_position("B:BM5:RM28")),
    ("dense_tactical", parse_position("B:BM17,19,26,28,29,30,31,32:RM2,3,4,6,7,9,10,11")),
]


def run_single(hints_enabled: bool, state, time_ms: int):
    env_val = "0" if hints_enabled else "1"
    os.environ["MAKHOS_LAZY_SMP_DISABLE_HINTS"] = env_val
    with NativeLazySmpSearch(
        CANDIDATE,
        threads=12,
        hash_mb=512,
        nnue_model=NNUE_MODEL,
    ) as smp:
        smp.clear()
        t0 = time.perf_counter()
        res = smp.search(
            state,
            depth=64,
            time_ms=time_ms,
            no_progress_plies=80,
            repetition_limit=3,
        )
        elapsed_s = time.perf_counter() - t0
        stats = smp.stats
        return {
            "move_str": str(res.move),
            "score": res.score,
            "depth": res.depth,
            "main_nodes": res.nodes,
            "aggregate_nodes": stats.aggregate_nodes,
            "worker_nodes": list(stats.worker_nodes),
            "nps": int(stats.aggregate_nodes / max(elapsed_s, 0.001)),
            "elapsed_ms": round(elapsed_s * 1000, 2),
            "shared_hint_entries": stats.shared_hint_entries,
            "shared_hint_allocated_bytes": stats.shared_hint_allocated_bytes,
        }


def main():
    print("Starting Balanced A/B Pilot Benchmark: Hints ON vs OFF (12T, 1000ms)...")
    results = {
        "format": "makhos-lazy-smp-ab-pilot-v1",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "threads": 12,
        "time_limit_ms": 1000,
        "candidate_dll": str(CANDIDATE),
        "nnue_model": str(NNUE_MODEL),
        "trials": [],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    for index, (pos_name, state) in enumerate(POSITIONS):
        # Alternating schedule
        order = ["ON", "OFF"] if index % 2 == 0 else ["OFF", "ON"]
        trial_entry = {
            "position": pos_name,
            "order": order,
            "measurements": {},
        }
        print(f"\n--- Position {index + 1}/{len(POSITIONS)}: {pos_name} (Order: {' -> '.join(order)}) ---")
        for mode in order:
            hints = (mode == "ON")
            print(f"  Running Mode: Hints {mode}...")
            # Warm up cache briefly
            run_single(hints, state, time_ms=100)
            measurement = run_single(hints, state, time_ms=1000)
            trial_entry["measurements"][mode] = measurement
            print(
                f"    depth={measurement['depth']}, "
                f"move={measurement['move_str']}, "
                f"main_nodes={measurement['main_nodes']:,}, "
                f"agg_nodes={measurement['aggregate_nodes']:,}, "
                f"nps={measurement['nps']:,}"
            )
        results["trials"].append(trial_entry)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved A/B pilot results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
