"""Milestone C4: Multi-Thread Root Split with Shared Tablebases & Differential Verification."""

from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch
import json

from makhos.compact_tb3 import CompactTablebase
from makhos.core import Rules, apply_move, legal_moves, parse_position
from makhos.exact import Outcome
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import (
    EndgameResult,
    NativeEndgameSearch,
    ParallelNativeEndgameSearch,
    NativeRoot,
)
from makhos.search import Engine, Mode, SearchLimits, WDLBound
from tests.test_server import DummyHandler


ROOT = Path(__file__).resolve().parents[1]
C2_LIBRARY = ROOT / "build/native_endgame_c2/makhos_endgame_search.dll"
C4_LIBRARY = ROOT / "build/native_endgame_c4/makhos_endgame_search_nnue.dll"
NNUE_MODEL = ROOT / "build/nnue_quantized_v1/model_a.mknnue"
TB_PATHS = tuple(ROOT / f"build/tb{n}_np80.compact.bin" for n in (4, 5, 6))


@unittest.skipUnless(
    C4_LIBRARY.is_file() and NNUE_MODEL.is_file() and all(p.is_file() for p in TB_PATHS),
    "C4 NNUE candidate and tablebase artifacts must be present",
)
class EndgameC4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.tb3 = cls.stack.enter_context(CompactTablebase())
        cls.tb = cls.stack.enter_context(
            NativeEndgameTablebase(cls.tb3, library=C4_LIBRARY, ranked_paths=TB_PATHS)
        )

    def test_threads_validation(self):
        with self.assertRaises(ValueError):
            ParallelNativeEndgameSearch(self.tb, threads=0, nnue_model=NNUE_MODEL)
        with self.assertRaises(ValueError):
            ParallelNativeEndgameSearch(self.tb, threads=-1, nnue_model=NNUE_MODEL)
        with self.assertRaises(ValueError):
            ParallelNativeEndgameSearch(self.tb, threads=13, nnue_model=NNUE_MODEL)

        # 1 and 12 are valid bounds
        with ParallelNativeEndgameSearch(self.tb, threads=1, nnue_model=NNUE_MODEL) as s1:
            self.assertEqual(s1.threads, 1)
        with ParallelNativeEndgameSearch(self.tb, threads=12, nnue_model=NNUE_MODEL) as s12:
            self.assertEqual(s12.threads, 12)

    def test_differential_equivalence_across_threads_nnue(self):
        positions = (
            "B:BK6,15:RK28",
            "B:BK1,5,6:RK24,28",
            "B:BM5,9:RM1,14",
        )
        threads_to_test = (2, 4, 6, 8, 12)

        with NativeEndgameSearch(self.tb, nnue_model=NNUE_MODEL) as ref_1t:
            for notation in positions:
                state = parse_position(notation)
                for depth in (1, 2, 4):
                    with self.subTest(position=notation, depth=depth):
                        res_1t = ref_1t.search(state, depth=depth)
                        ref_scores = [r.score for r in res_1t.roots]
                        ref_bounds = [r.bound for r in res_1t.roots]
                        ref_pvs = [[m.notation for m in r.pv] for r in res_1t.roots]

                        for t in threads_to_test:
                            with ParallelNativeEndgameSearch(self.tb, threads=t, nnue_model=NNUE_MODEL) as smp:
                                res_smp = smp.search(state, depth=depth)
                                self.assertEqual(res_smp.depth, res_1t.depth)
                                self.assertEqual(res_smp.nodes, res_1t.nodes)
                                self.assertEqual(res_smp.tb_hits, res_1t.tb_hits)
                                smp_scores = [r.score for r in res_smp.roots]
                                smp_bounds = [r.bound for r in res_smp.roots]
                                smp_pvs = [[m.notation for m in r.pv] for r in res_smp.roots]
                                self.assertEqual(smp_scores, ref_scores, f"Mismatch at {t}T depth {depth}")
                                self.assertEqual(smp_bounds, ref_bounds, f"Mismatch at {t}T depth {depth}")
                                self.assertEqual(smp_pvs, ref_pvs, f"Mismatch at {t}T depth {depth}")

    def test_differential_equivalence_across_threads_hce(self):
        positions = (
            "B:BK6,15:RK28",
            "B:BK1,5,6:RK24,28",
        )
        with NativeEndgameTablebase(self.tb3, library=C2_LIBRARY, ranked_paths=TB_PATHS) as tb_hce, \
             NativeEndgameSearch(tb_hce) as ref_1t:
            for notation in positions:
                state = parse_position(notation)
                for depth in (1, 2, 4):
                    res_1t = ref_1t.search(state, depth=depth)
                    ref_scores = [r.score for r in res_1t.roots]
                    ref_bounds = [r.bound for r in res_1t.roots]
                    ref_pvs = [[m.notation for m in r.pv] for r in res_1t.roots]

                    for t in (2, 4, 6):
                        with ParallelNativeEndgameSearch(tb_hce, threads=t) as smp:
                            res_smp = smp.search(state, depth=depth)
                            self.assertEqual(res_smp.depth, res_1t.depth)
                            self.assertEqual(res_smp.nodes, res_1t.nodes)
                            smp_scores = [r.score for r in res_smp.roots]
                            smp_bounds = [r.bound for r in res_smp.roots]
                            smp_pvs = [[m.notation for m in r.pv] for r in res_smp.roots]
                            self.assertEqual(smp_scores, ref_scores)
                            self.assertEqual(smp_bounds, ref_bounds)
                            self.assertEqual(smp_pvs, ref_pvs)

    def test_common_completed_depth_barrier_on_timeout(self):
        state = parse_position("B:BK6,15:RK28")
        with ParallelNativeEndgameSearch(self.tb, threads=4, nnue_model=NNUE_MODEL) as smp:
            # Requesting high depth with a 1 ms timeout:
            # Iterative deepening must stop and publish only complete common layers.
            res = smp.search(state, depth=20, time_ms=1)
            self.assertGreaterEqual(res.depth, 1)
            self.assertLess(res.depth, 20)
            self.assertEqual(len(res.roots), len(legal_moves(state)))
            for root in res.roots:
                self.assertGreater(len(root.pv), 0)

    def test_cancellation_and_lifecycle(self):
        state = parse_position("B:BK6,15:RK28")
        smp = ParallelNativeEndgameSearch(self.tb, threads=4, nnue_model=NNUE_MODEL)
        res1 = smp.search(state, depth=2)
        self.assertEqual(res1.depth, 2)

        smp.cancel()
        smp.clear()
        res2 = smp.search(state, depth=2)
        self.assertEqual(res2.depth, 2)

        smp.close()
        with self.assertRaises(RuntimeError):
            smp.search(state, depth=2)

    def test_server_multi_thread_routing_and_provenance(self):
        state = parse_position("B:BK6,15:RK28")
        fake_parallel_native = type(
            "FakeParallelNative",
            (),
            {
                "path": ROOT / "build/makhos_native_accepted.dll",
                "threads": 6,
                "nnue_enabled": True,
                "nnue_model_path": NNUE_MODEL,
                "allocated_hash_mb": 64.0,
                "_workers": [None] * 6,
            },
        )()

        engine = Engine(
            native_tablebase=self.tb3,
            native_search=fake_parallel_native,
            native_endgame_enabled=True,
            exact_piece_limit=0,
        )

        handler = DummyHandler({})
        with patch("makhos.server.get_default_engine", return_value=engine), \
             patch("makhos.server.ensure_native_tablebase_ready", return_value=True), \
             patch("makhos.server.GUI_NNUE_MODEL_OVERRIDE", None), \
             patch("makhos.server.GLOBAL_ENGINE_PROVENANCE", {}):
            handler.handle_bestmove({
                "position": "B:BK6,15:RK28",
                "depth": 2,
                "time_sec": 1,
                "use_full_time": False,
                "native_endgame": True,
            })

        data = json.loads(handler.wfile.bytes.decode("utf-8"))
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["search_backend"], "native-endgame")
        self.assertTrue(data["native_endgame_ready"])
        self.assertEqual(data["native_endgame_threads"], 6)
        self.assertEqual(data["search_thread_capacity"], 6)
        self.assertEqual(data["native_endgame_evaluator"], "nnue")
        self.assertIsInstance(engine.native_endgame_search, ParallelNativeEndgameSearch)
        self.assertEqual(engine.native_endgame_search.threads, 6)

    def test_parallel_native_endgame_search_deadline_compliance(self):
        import time

        with ParallelNativeEndgameSearch(self.tb, threads=4, nnue_model=NNUE_MODEL) as s:
            state = parse_position("B:BK1,5,6:RK24,28")
            t0 = time.perf_counter()
            res = s.search(state, depth=16, time_ms=50)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            self.assertEqual(res.status, 0)
            self.assertGreaterEqual(res.depth, 1)
            self.assertLess(res.depth, 16)
            self.assertLess(elapsed_ms, 200.0)


if __name__ == "__main__":
    unittest.main()
