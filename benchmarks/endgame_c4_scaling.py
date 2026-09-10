"""Milestone C4 multi-thread scaling benchmark across 1T..12T."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.compact_tb3 import CompactTablebase
from makhos.core import parse_position
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import (
    NativeEndgameSearch,
    ParallelNativeEndgameSearch,
)
from tests.test_endgame_repetition import repetition_fixture

C4_LIBRARY = ROOT / "build/native_endgame_c4/makhos_endgame_search_nnue.dll"
NNUE_MODEL = ROOT / "build/nnue_quantized_v1/model_a.mknnue"
RANKED_PATHS = tuple(ROOT / f"build/tb{pieces}_np80.compact.bin" for pieces in (4, 5, 6))

BENCH_POSITIONS = [
    ("repetition_win", "B:BK6,15:RK28"),
    ("4_pieces_kings", "B:BK1,5,6:RK24,28"),
    ("5_pieces_pawns", "B:BM5,9:RM1,14"),
]
THREADS_TO_TEST = (1, 2, 4, 6, 8, 12)
DEPTHS_TO_TEST = (2, 4, 6)


def run() -> dict[str, object]:
    missing = [str(p) for p in (C4_LIBRARY, NNUE_MODEL, *RANKED_PATHS) if not p.is_file()]
    if missing:
        raise FileNotFoundError("missing C4 benchmark artifact(s): " + ", ".join(missing))

    results: dict[str, object] = {
        "candidate": str(C4_LIBRARY),
        "model": str(NNUE_MODEL),
        "positions": {},
    }

    with CompactTablebase() as tb3, \
         NativeEndgameTablebase(tb3, library=C4_LIBRARY, ranked_paths=RANKED_PATHS) as tb:

        for name, notation in BENCH_POSITIONS:
            state = parse_position(notation)
            pos_results: dict[str, object] = {}

            for depth in DEPTHS_TO_TEST:
                depth_results: dict[str, object] = {}

                # 1T reference
                with NativeEndgameSearch(tb, nnue_model=NNUE_MODEL) as ref_1t:
                    # Warmup
                    ref_1t.search(state, depth=depth)
                    t0 = time.perf_counter()
                    res_1t = ref_1t.search(state, depth=depth)
                    t1 = time.perf_counter()
                    t_1t_ms = (t1 - t0) * 1000.0

                depth_results["1T"] = {
                    "ms": round(t_1t_ms, 3),
                    "nodes": res_1t.nodes,
                    "speedup": 1.0,
                }

                ref_scores = [r.score for r in res_1t.roots]
                ref_bounds = [r.bound for r in res_1t.roots]

                for t in (2, 4, 6, 8, 12):
                    with ParallelNativeEndgameSearch(tb, threads=t, nnue_model=NNUE_MODEL) as smp:
                        # Warmup
                        smp.search(state, depth=depth)
                        t0 = time.perf_counter()
                        res_smp = smp.search(state, depth=depth)
                        t1 = time.perf_counter()
                        t_smp_ms = (t1 - t0) * 1000.0

                    smp_scores = [r.score for r in res_smp.roots]
                    smp_bounds = [r.bound for r in res_smp.roots]
                    if smp_scores != ref_scores or smp_bounds != ref_bounds:
                        raise RuntimeError(f"Differential mismatch at {name} depth {depth} {t}T")

                    speedup = t_1t_ms / max(t_smp_ms, 0.001)
                    depth_results[f"{t}T"] = {
                        "ms": round(t_smp_ms, 3),
                        "nodes": res_smp.nodes,
                        "speedup": round(speedup, 2),
                    }

                pos_results[f"depth_{depth}"] = depth_results

            results["positions"][name] = pos_results

    return results


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
