"""Request timings and optional profiling must not change search semantics."""

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from benchmarks.endgame_latency import cases, percentiles, result_signature
from makhos.core import parse_position
from makhos.ranked_tablebase import RankedTablebase
from makhos.search import Engine, SearchLimits
from makhos.search_profile import RequestProfiler
from tests.test_server import DummyHandler


class EndgameLatencyTests(unittest.TestCase):
    def test_request_counts_queue_and_cold_setup_outside_search_budget(self):
        engine = Engine(exact_piece_limit=0)
        position = "B:BK6,15:RK28"
        result = engine.search(parse_position(position), SearchLimits(depth=1))
        now = [10.0]

        @contextmanager
        def queued_lock():
            now[0] += 0.010
            yield
            now[0] += 0.004

        def setup(**kwargs):
            now[0] += 0.005
            return engine

        def prepare_tb3(target):
            now[0] += 0.200
            target.native_tablebase = object()
            return True

        def search(*args, **kwargs):
            self.assertEqual(kwargs["limits"].time_ms, 10)
            now[0] += 0.025
            return result

        handler = DummyHandler({})
        with patch("makhos.server.time.perf_counter", side_effect=lambda: now[0]), \
                patch("makhos.server.ENGINE_SEARCH_LOCK", queued_lock()), \
                patch("makhos.server.get_default_engine", side_effect=setup), \
                patch("makhos.server.ensure_native_tablebase_ready", side_effect=prepare_tb3), \
                patch("makhos.server.engine_search_provenance", return_value={"search_backend": "python"}), \
                patch("makhos.server.GUI_NNUE_MODEL_OVERRIDE", None), \
                patch.object(engine, "search", side_effect=search):
            handler.handle_bestmove({"position": position, "time_sec": 0.01, "threads": 12})
        data = json.loads(handler.wfile.bytes)
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["timings_ms"], {
            "validation": 0.0, "engine_lock_wait": 10.0, "engine_setup": 5.0,
            "tb3_prepare": 200.0, "search": 25.0, "provenance": 0.0, "response_prepare": 4.0,
        })
        self.assertEqual(data["request_elapsed_ms"], 244.0)
        self.assertEqual(data["request_overshoot_ms"], 234.0)
        self.assertEqual(data["pre_search_setup_ms"], 205.0)
        self.assertEqual(data["search_thread_capacity"], 1)
        self.assertTrue(data["tb3_load_attempted"])
        self.assertFalse(data["tb3_ready_before"])
        self.assertIsNone(data["python_profile"])

    def test_invalid_profile_flag_does_not_load_engine(self):
        handler = DummyHandler({})
        with patch("makhos.server.get_default_engine") as setup:
            handler.handle_bestmove({"position": "B:BK6,15:RK28", "profile_request": "false"})
            setup.assert_not_called()
        self.assertEqual(handler.response_status, 400)

    def test_disabled_profiler_does_not_allocate_or_install_hook(self):
        with patch("makhos.search_profile.cProfile.Profile") as create:
            with RequestProfiler() as profile:
                self.assertIsNone(profile.report())
            create.assert_not_called()

    def test_profiler_releases_hook_when_search_raises(self):
        profile = RequestProfiler(True)
        with self.assertRaisesRegex(RuntimeError, "search failed"):
            with profile:
                raise RuntimeError("search failed")
        self.assertIsNone(sys.getprofile())
        self.assertFalse(profile.report()["strength_evidence"])

    def test_percentiles_use_raw_observations_and_report_sample_count(self):
        self.assertEqual(percentiles([4, 1, 2, 3]), {"n": 4, "p50": 2, "p95": 4, "p99": 4, "max": 4})
        self.assertIsNone(percentiles([])["p95"])

    @unittest.skipUnless(Path("build/tb4_np80.compact.bin").is_file(), "local TB4 required")
    def test_profiled_http_search_preserves_repetition_results_at_fixed_depth(self):
        with RankedTablebase("build/tb4_np80.compact.bin") as tb4:
            engine = Engine(ranked_tablebase=tb4, exact_piece_limit=0)
            # This test profiles search semantics, not the asynchronous startup.
            from makhos.compact_tb3 import CompactTablebase
            from makhos.server import _attach_native_tablebase
            tb3 = CompactTablebase()
            self.addCleanup(tb3.close)
            _attach_native_tablebase(engine, tb3)
            for case in cases()[1:6]:
                for mode in ("best", "win"):
                    observations = []
                    for enabled in (False, True):
                        engine.clear()
                        handler = DummyHandler({})
                        with patch("makhos.server.get_default_engine", return_value=engine), \
                                patch("makhos.server.GUI_NNUE_MODEL_OVERRIDE", None):
                            handler.handle_bestmove({
                                **case, "time_sec": 30, "depth": 2, "use_full_time": False,
                                "mode": mode, "profile_request": enabled,
                            })
                        data = json.loads(handler.wfile.bytes)
                        self.assertEqual(handler.response_status, 200)
                        observations.append(data)
                    with self.subTest(case=case["id"], mode=mode):
                        self.assertEqual(result_signature(observations[0]), result_signature(observations[1]))
                        report = observations[1]["python_profile"]
                        self.assertAlmostEqual(sum(x["self_ms"] for x in report["categories"].values()),
                                               report["total_self_ms"], delta=0.02)
                        self.assertIn("python_tree", report["categories"])
                        self.assertFalse(report["io_wait_separated"])
                        self.assertLess(abs(sum(observations[1]["timings_ms"].values())
                                            - observations[1]["request_elapsed_ms"]), 0.01)
