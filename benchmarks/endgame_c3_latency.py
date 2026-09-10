"""C3 candidate cold/warm latency smoke for the GUI budget.

This benchmark maps immutable TB artifacts and searches one representative
repetition-safe endgame.  It never starts a match, changes a release pointer,
or touches the accepted DLL/checkpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.compact_tb3 import CompactTablebase
from makhos.core import Rules
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import NativeEndgameSearch
from makhos.search import Engine, Mode, SearchLimits
from tests.test_endgame_repetition import repetition_fixture


C3_LIBRARY = ROOT / "build/native_endgame_c3/makhos_endgame_search_nnue.dll"
NNUE_MODEL = ROOT / "build/nnue_quantized_v1/model_a.mknnue"
RANKED_PATHS = tuple(ROOT / f"build/tb{pieces}_np80.compact.bin" for pieces in (4, 5, 6))


def run() -> dict[str, object]:
    missing = [str(path) for path in (C3_LIBRARY, NNUE_MODEL, *RANKED_PATHS) if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing C3 benchmark artifact(s): " + ", ".join(missing))
    state, history = repetition_fixture()
    start = time.perf_counter()
    with CompactTablebase() as tb3:
        with NativeEndgameTablebase(tb3, library=C3_LIBRARY, ranked_paths=RANKED_PATHS) as tb:
            with NativeEndgameSearch(tb, nnue_model=NNUE_MODEL) as native:
                setup_ms = (time.perf_counter() - start) * 1000.0
                engine = Engine(
                    Rules(repetition_limit=3),
                    native_tablebase=tb3,
                    native_endgame_search=native,
                    native_endgame_enabled=True,
                    exact_piece_limit=0,
                )
                limits = SearchLimits(depth=2, time_ms=1000)
                cold_start = time.perf_counter()
                cold = engine.search(state, limits, mode=Mode.WIN, history=history)
                cold_ms = (time.perf_counter() - cold_start) * 1000.0
                warm_start = time.perf_counter()
                warm = engine.search(state, limits, mode=Mode.WIN, history=history)
                warm_ms = (time.perf_counter() - warm_start) * 1000.0
                result = {
                    "backend": engine.last_search_backend,
                    "evaluator": native.evaluator,
                    "cold_setup_ms": round(setup_ms, 3),
                    "cold_search_ms": round(cold_ms, 3),
                    "warm_search_ms": round(warm_ms, 3),
                    "cold_move": cold.move.notation,
                    "warm_move": warm.move.notation,
                    "cold_depth": cold.depth,
                    "warm_depth": warm.depth,
                    "cold_tablebase_hits": cold.tablebase_hits,
                    "warm_tablebase_hits": warm.tablebase_hits,
                    "budgets_ms": {"cold": 2000, "warm": 1000},
                }
    if result["cold_search_ms"] > 2000 or result["warm_search_ms"] > 1000:
        raise RuntimeError("C3 GUI latency budget exceeded: " + json.dumps(result))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
