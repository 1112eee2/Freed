import ctypes
import unittest
from pathlib import Path

from makhos.core import initial_state, legal_moves, parse_position
from makhos.native import NativeRootPvsShadowSearch, NativeSearch


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / "build" / "makhos_native_root_pvs_shadow_candidate.dll"
CONTROL = ROOT / "build" / "makhos_native_root_pvs_shadow_control.dll"
ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"


@unittest.skipUnless(CANDIDATE.is_file(), "root-PVS shadow candidate is not built")
class NativeRootPvsShadowTests(unittest.TestCase):
    def test_candidate_is_isolated_from_accepted_library(self):
        accepted = ctypes.CDLL(str(ACCEPTED.resolve()))
        self.assertFalse(hasattr(accepted, "makhos_root_pvs_shadow_available"))
        candidate = ctypes.CDLL(str(CANDIDATE.resolve()))
        self.assertTrue(hasattr(candidate, "makhos_root_pvs_shadow_available"))

    def test_one_thread_authoritative_main_matches_same_source_control(self):
        positions = (
            initial_state(),
            parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2"),
            parse_position("B:BM14,20,22,23,27,31,32:RM2,3,5,7,11,13,15"),
        )
        with NativeRootPvsShadowSearch(
            CANDIDATE,
            threads=1,
            hash_mb=128,
        ) as shadow:
            main_power = shadow.stats.main_hash_power
            with NativeSearch(
                CONTROL,
                hash_power=main_power,
                persistent=True,
            ) as control:
                for state in positions:
                    shadow.clear()
                    control.clear()
                    expected = control.search(
                        state,
                        depth=10,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                    )
                    actual = shadow.search(
                        state,
                        depth=10,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                    )
                    self.assertEqual(actual.move, expected.move)
                    self.assertEqual(actual.score, expected.score)
                    self.assertEqual(actual.nodes, expected.nodes)
                    self.assertEqual(actual.pv, expected.pv)
                    self.assertEqual(actual.depth, expected.depth)

    def test_shadow_helpers_cannot_change_fixed_depth_main_result(self):
        state = parse_position(
            "B:BM14,20,22,23,27,31,32:RM2,3,5,7,11,13,15"
        )
        with NativeRootPvsShadowSearch(
            CANDIDATE,
            threads=12,
            hash_mb=512,
        ) as shadow:
            initial_stats = shadow.stats
            with NativeSearch(
                CANDIDATE,
                hash_power=initial_stats.main_hash_power,
                persistent=True,
            ) as main:
                shadow.clear()
                main.clear()
                expected = main.search(
                    state,
                    depth=10,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                actual = shadow.search(
                    state,
                    depth=10,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                stats = shadow.stats
        self.assertEqual(actual.move, expected.move)
        self.assertEqual(actual.score, expected.score)
        self.assertEqual(actual.nodes, expected.nodes)
        self.assertEqual(actual.pv, expected.pv)
        self.assertEqual(stats.main_nodes, actual.nodes)
        self.assertGreater(stats.helper_nodes, 0)
        self.assertGreater(stats.scout_tasks_started, 0)
        self.assertGreater(stats.shadow_iterations, 0)
        self.assertEqual(stats.worker_failures, 0)
        self.assertLessEqual(stats.allocated_tt_bytes, 512 * 1024 * 1024)

    def test_hash_is_a_total_budget_across_thread_counts(self):
        for threads in (1, 2, 4, 8, 12):
            with self.subTest(threads=threads):
                with NativeRootPvsShadowSearch(
                    CANDIDATE,
                    threads=threads,
                    hash_mb=64,
                ) as shadow:
                    stats = shadow.stats
                    self.assertEqual(stats.requested_threads, threads)
                    self.assertLessEqual(stats.effective_threads, threads)
                    self.assertLessEqual(stats.allocated_tt_bytes, 64 * 1024 * 1024)
                    self.assertGreaterEqual(shadow.memory_bytes, stats.allocated_tt_bytes)

    def test_short_deadline_returns_legal_authoritative_fallback(self):
        state = initial_state()
        with NativeRootPvsShadowSearch(
            CANDIDATE,
            threads=12,
            hash_mb=64,
        ) as shadow:
            result = shadow.search(
                state,
                depth=64,
                time_ms=10,
                no_progress_plies=80,
                repetition_limit=3,
            )
            stats = shadow.stats
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.nodes, stats.main_nodes)
        self.assertLessEqual(stats.completed_depth, stats.attempted_depth)
        self.assertEqual(stats.worker_failures, 0)


if __name__ == "__main__":
    unittest.main()
