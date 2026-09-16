import ctypes
import os
import random
from collections import Counter
import threading
import time
import unittest
from pathlib import Path

from makhos.core import apply_move, initial_state, legal_moves, parse_position, terminal_status
from makhos.native import NativeLazySmpSearch, NativeSearch


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = Path(os.environ.get("MAKHOS_TEST_LAZY_SMP_DLL", str(ROOT / "build/lazy_smp_candidate_v1/makhos_native_lazy_smp_candidate_v1.dll")))
STRICT_CONTROL = Path(os.environ.get("MAKHOS_TEST_STRICT_CONTROL_DLL", str(ROOT / "build/strict_key_candidate_a0f7964_v1/makhos_native_nnue_candidate_v1.dll")))
NNUE_MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"


@unittest.skipUnless(CANDIDATE.is_file(), "Lazy SMP candidate is not built")
class NativeLazySmpTests(unittest.TestCase):
    def test_terminal_children_match_independent_rules_oracle(self):
        cases = ("B:BM14:RM10", "B:BK15:RM19,27", "B:BK1:RK32")
        for threads in (1, 2, 4, 6, 8, 12):
            with NativeLazySmpSearch(CANDIDATE, threads=threads, hash_mb=16,
                                     nnue_model=NNUE_MODEL) as engine:
                for fen in cases:
                    state = parse_position(fen, reversible_plies=79)
                    outcomes = {move: terminal_status(apply_move(state, move))
                                for move in legal_moves(state)}
                    self.assertTrue(all(item.terminal for item in outcomes.values()))
                    for depth in (1, 2, 4, 6):
                        with self.subTest(threads=threads, fen=fen, depth=depth):
                            engine.clear()
                            result = engine.search(state, depth=depth, time_ms=None,
                                                   no_progress_plies=80, repetition_limit=3)
                            self.assertIn(result.move, outcomes)
                            expected = outcomes[result.move]
                            if expected.winner is None:
                                self.assertEqual(result.score, 0)
                            else:
                                self.assertEqual(expected.winner, state.turn)
                                self.assertGreaterEqual(result.score, 90000)

    def test_long_history_lookup_and_replayed_cycle(self):
        # More than 32 unique keys exercises native hashed history, not linear lookup.
        rng = random.Random(736)
        position = initial_state()
        history = Counter({position.position_key: 1})
        for _ in range(60):
            if terminal_status(position, repetition_count=history[position.position_key]).terminal:
                break
            position = apply_move(position, rng.choice(legal_moves(position)))
            history[position.position_key] += 1
        self.assertGreaterEqual(len(history), 32)
        root = initial_state()
        history[root.position_key] = 1
        for move in legal_moves(root):
            history[apply_move(root, move).position_key] = 2
        cycle_root = parse_position("B:BK1:RK32")
        cycle = cycle_root
        cycle_history = Counter({cycle.position_key: 1})
        for _ in range(2):
            for path in ((0, 4), (31, 27), (4, 0), (27, 31)):
                move = next(move for move in legal_moves(cycle) if move.path == path)
                cycle = apply_move(cycle, move)
                cycle_history[cycle.position_key] += 1
        self.assertEqual(cycle.position_key, cycle_root.position_key)
        self.assertEqual(terminal_status(cycle, repetition_count=cycle_history[cycle.position_key]).reason,
                         "repetition")
        for threads in (1, 2, 4, 6, 8, 12):
            with self.subTest(threads=threads):
                with NativeLazySmpSearch(CANDIDATE, threads=threads, hash_mb=16,
                                         nnue_model=NNUE_MODEL) as engine:
                    result = engine.search(root, depth=4, time_ms=None, no_progress_plies=80,
                                           repetition_limit=3, history=history)
                    self.assertEqual(result.score, 0)
                    with self.assertRaisesRegex(RuntimeError, "terminal"):
                        engine.search(cycle, depth=4, time_ms=None, no_progress_plies=80,
                                      repetition_limit=3, history=cycle_history)
                    # Disabling repetition must not leave stale terminal state on the handle.
                    result = engine.search(cycle, depth=2, time_ms=None, no_progress_plies=80,
                                           repetition_limit=None, history=cycle_history)
                    self.assertIn(result.move, legal_moves(cycle))

    def test_terminal_root_repetition_rejected_before_search(self):
        state = initial_state()
        for threads in (1, 2, 4, 6, 8, 12):
            with self.subTest(threads=threads):
                with NativeLazySmpSearch(CANDIDATE, threads=threads, hash_mb=16,
                                         nnue_model=NNUE_MODEL) as engine:
                    with self.assertRaisesRegex(RuntimeError, "terminal"):
                        engine.search(state, depth=1, time_ms=None, no_progress_plies=80,
                                      repetition_limit=3, history={state.position_key: 3})

    def test_history_switch_forced_draw_and_legal_pv(self):
        state = initial_state()
        history = {apply_move(state, move).position_key: 2 for move in legal_moves(state)}
        history[state.position_key] = 1
        for threads in (1, 2, 4, 6, 8, 12):
            with NativeLazySmpSearch(CANDIDATE, threads=threads, hash_mb=64,
                                     nnue_model=NNUE_MODEL) as engine:
                for depth in (1, 2, 4, 6):
                    engine.clear()
                    for label, counts in (("H1", None), ("H2", history), ("H1_again", None)):
                        with self.subTest(threads=threads, depth=depth, history=label):
                            result = engine.search(state, depth=depth, time_ms=None,
                                                   no_progress_plies=80, repetition_limit=3,
                                                   history=counts)
                            if counts is not None:
                                # Every legal child reaches its third occurrence.
                                self.assertEqual(result.score, 0)
                            position = state
                            for move in result.pv:
                                self.assertIn(move, legal_moves(position))
                                position = apply_move(position, move)

    def test_candidate_exports_lazy_smp_api(self):
        candidate = ctypes.CDLL(str(CANDIDATE.resolve()))
        self.assertTrue(hasattr(candidate, "makhos_lazy_smp_available"))
        self.assertTrue(hasattr(candidate, "makhos_lazy_smp_create"))
        self.assertTrue(hasattr(candidate, "makhos_lazy_smp_destroy"))
        self.assertTrue(hasattr(candidate, "makhos_lazy_smp_stop"))
        self.assertTrue(hasattr(candidate, "makhos_lazy_smp_run"))
        self.assertTrue(hasattr(candidate, "makhos_lazy_smp_stats"))

    def test_gate_g1_comprehensive_parity_against_strict_control_binary(self):
        # 1. Multi-capture fixture: B:BM23,26:BK15:RM13,14,19,21,27 (15x24x31 captures 2 pieces)
        s_multi = parse_position("B:BM23,26:BK15:RM13,14,19,21,27")
        self.assertTrue(any(len(m.captures) >= 2 for m in legal_moves(s_multi)), "Fixture must have multi-capture")

        # 2. Promotion fixture: B:BM5:RM28 (5-1 promotes)
        s_promo = parse_position("B:BM5:RM28")
        self.assertTrue(any(m.promotes for m in legal_moves(s_promo)), "Fixture must have promotion")

        cases = [
            ("initial", initial_state(), 80, None),
            ("tactical", parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2"), 80, None),
            ("middlegame", parse_position("B:BM14,20,22,23,27,31,32:RM2,3,5,7,11,13,15"), 80, None),
            ("multi_capture", s_multi, 80, None),
            ("promotion", s_promo, 80, None),
            ("clock_79", parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2", reversible_plies=79), 80, None),
            ("repetition_history", initial_state(), 80, {initial_state().position_key: 2}),
        ]

        self.assertTrue(STRICT_CONTROL.is_file(), f"Strict control binary not found: {STRICT_CONTROL}")
        with NativeLazySmpSearch(
            CANDIDATE,
            threads=1,
            hash_mb=512,
            nnue_model=NNUE_MODEL,
        ) as smp:
            with NativeSearch(
                STRICT_CONTROL,
                hash_power=23,
                nnue_model=NNUE_MODEL,
                persistent=True,
            ) as std:
                for name, state, no_prog, hist in cases:
                    with self.subTest(case=name):
                        smp.clear()
                        std.clear()
                        expected = std.search(
                            state,
                            depth=6,
                            time_ms=None,
                            no_progress_plies=no_prog,
                            repetition_limit=3,
                            history=hist,
                        )
                        actual = smp.search(
                            state,
                            depth=6,
                            time_ms=None,
                            no_progress_plies=no_prog,
                            repetition_limit=3,
                            history=hist,
                        )
                        self.assertEqual(actual.move, expected.move)
                        self.assertEqual(actual.score, expected.score)
                        self.assertEqual(actual.nodes, expected.nodes)
                        self.assertEqual(actual.pv, expected.pv)
                        self.assertEqual(actual.depth, expected.depth)

                # Warm TT parity: verify move, score, nodes, depth, and pv
                state_warm = initial_state()
                smp.clear()
                std.clear()
                std.search(state_warm, depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)
                smp.search(state_warm, depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)
                expected_warm = std.search(state_warm, depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)
                actual_warm = smp.search(state_warm, depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)
                self.assertEqual(actual_warm.move, expected_warm.move)
                self.assertEqual(actual_warm.score, expected_warm.score)
                self.assertEqual(actual_warm.nodes, expected_warm.nodes)
                self.assertEqual(actual_warm.depth, expected_warm.depth)
                self.assertEqual(actual_warm.pv, expected_warm.pv)

                # Reversible clock 80 terminal rejection parity
                pos_clock80 = parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2", reversible_plies=80)
                with self.assertRaises(RuntimeError) as cm_std:
                    std.search(pos_clock80, depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)
                with self.assertRaises(RuntimeError) as cm_smp:
                    smp.search(pos_clock80, depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)
                self.assertIn("terminal", str(cm_std.exception))
                self.assertIn("terminal", str(cm_smp.exception))

    def test_memory_budget_and_allocation_formula(self):
        # Entry is 40 bytes. Hash power 23 = 8,388,608 entries = 320 MiB allocated TT for 1T.
        # Shared hints table is pinned to 2^20 entries * 48 bytes = 48.0 MiB.
        expected_allocations = {
            1: (0, 320 * 1024 * 1024),                 # 1T: 0 shared, 320 MiB private
            2: (48 * 1024 * 1024, 320 * 1024 * 1024), # 2T: 48 MiB shared, 2x160 MiB private
            4: (48 * 1024 * 1024, 320 * 1024 * 1024), # 4T: 48 MiB shared, 4x80 MiB private
            6: (48 * 1024 * 1024, 240 * 1024 * 1024), # 6T: 48 MiB shared, 6x40 MiB private = 288 MiB total
            12: (48 * 1024 * 1024, 240 * 1024 * 1024), # 12T: 48 MiB shared, 12x20 MiB private = 288 MiB total
        }
        for threads, (exp_shared, exp_priv) in expected_allocations.items():
            with self.subTest(threads=threads):
                with NativeLazySmpSearch(
                    CANDIDATE,
                    threads=threads,
                    hash_mb=512,
                    nnue_model=NNUE_MODEL,
                ) as smp:
                    stats = smp.stats
                    self.assertEqual(stats.shared_hint_allocated_bytes, exp_shared)
                    self.assertEqual(stats.private_tt_allocated_bytes, exp_priv)
                    total_tt = stats.shared_hint_allocated_bytes + stats.private_tt_allocated_bytes
                    self.assertLessEqual(total_tt, 512 * 1024 * 1024)

    def test_total_tt_respects_small_and_production_hash_budgets(self):
        for hash_mb in (16, 64, 128, 512):
            for threads in (1, 2, 4, 6, 8, 12):
                with self.subTest(hash_mb=hash_mb, threads=threads):
                    with NativeLazySmpSearch(
                        CANDIDATE, threads=threads, hash_mb=hash_mb, nnue_model=NNUE_MODEL,
                    ) as smp:
                        stats = smp.stats
                        total = stats.private_tt_allocated_bytes + stats.shared_hint_allocated_bytes
                        self.assertLessEqual(total, hash_mb * 1024 * 1024)

    def test_total_tt_respects_non_power_of_two_hash_budgets(self):
        # The power-of-two grid in the previous test happens to miss non-aligned
        # budgets, where the shared hint table floor can push the total over the
        # requested Hash. These values are the measured boundary where the shared
        # table grows (6 MiB -> 12 MiB of shared) while the private share stays
        # pinned to a power-of-two entry count. Asserting the budget here covers
        # the class of request the aligned grid cannot falsify.
        for hash_mb in (24, 48, 56, 80, 96, 100, 112, 200, 300, 500, 1000, 1300):
            for threads in (1, 2, 4, 6, 8, 12):
                with self.subTest(hash_mb=hash_mb, threads=threads):
                    with NativeLazySmpSearch(
                        CANDIDATE, threads=threads, hash_mb=hash_mb, nnue_model=NNUE_MODEL,
                    ) as smp:
                        stats = smp.stats
                        total = stats.private_tt_allocated_bytes + stats.shared_hint_allocated_bytes
                        self.assertLessEqual(
                            total,
                            hash_mb * 1024 * 1024,
                            f"Hash={hash_mb} MiB Threads={threads}: allocated "
                            f"{total} bytes exceeds the requested budget",
                        )

    def test_impossible_hash_budget_fails_closed_without_partial_allocation(self):
        # A budget too small to satisfy the shared table plus per-worker minimum
        # must fail closed rather than silently over-allocating or half-building a
        # handle. 1 MiB at 6/8/12T is below the measured floor, so this pins the
        # fail-closed contract instead of letting it drift into a silent success.
        for threads in (6, 8, 12):
            with self.subTest(threads=threads):
                with self.assertRaisesRegex(RuntimeError, "allocation failed"):
                    NativeLazySmpSearch(
                        CANDIDATE, threads=threads, hash_mb=1, nnue_model=NNUE_MODEL,
                    )

    def test_external_cancellation_from_separate_thread(self):
        state1 = initial_state()
        state2 = parse_position("B:BM23,26:BK15:RM13,14,19,21,27")

        with NativeLazySmpSearch(CANDIDATE, threads=12, hash_mb=512, nnue_model=NNUE_MODEL) as smp:
            search_result = [None]
            search_error = [None]
            t_cancel_sent = [0.0]
            t_search_returned = [0.0]

            def worker():
                try:
                    search_result[0] = smp.search(state1, depth=30, time_ms=10000, no_progress_plies=80, repetition_limit=3)
                except Exception as exc:
                    search_error[0] = exc
                t_search_returned[0] = time.perf_counter()

            thread = threading.Thread(target=worker)
            thread.start()

            # Wait while all 12 workers are actively searching
            time.sleep(0.060)

            # Signal cancellation externally
            t_cancel_sent[0] = time.perf_counter()
            smp.stop()

            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive(), "Search thread did not terminate within timeout")
            self.assertIsNone(search_error[0], f"Search thread error: {search_error[0]}")

            drain_latency_ms = (t_search_returned[0] - t_cancel_sent[0]) * 1000.0
            self.assertLess(drain_latency_ms, 50.0, f"Drain latency exceeded limit: {drain_latency_ms:.2f} ms")

            res1 = search_result[0]
            self.assertIn(res1.move, legal_moves(state1))
            self.assertGreater(smp.stats.aggregate_nodes, 10000)

            # Subsequent request: verify fresh search immediately succeeds without stale leakage
            res2 = smp.search(state2, depth=6, time_ms=500, no_progress_plies=80, repetition_limit=3)
            self.assertIn(res2.move, legal_moves(state2))
            self.assertGreaterEqual(len(res2.move.captures), 2)

    def test_stop_after_close_is_noop_and_safe(self):
        smp = NativeLazySmpSearch(CANDIDATE, threads=2, hash_mb=64, nnue_model=NNUE_MODEL)
        smp.close()
        # Calling stop after close must be a safe no-op without exception or crash
        smp.stop()
        smp.close()  # Double close is also safe
        self.assertTrue(smp._closed)
        self.assertIsNone(smp._handle)
        with self.assertRaises(RuntimeError):
            smp.search(initial_state(), depth=1, time_ms=100, no_progress_plies=80, repetition_limit=3)

    def test_stop_concurrent_with_close(self):
        # Stress is evidence of these interleavings, not a race-detector proof.
        for _ in range(25):
            smp = NativeLazySmpSearch(CANDIDATE, threads=4, hash_mb=64, nnue_model=NNUE_MODEL)
            errors = []

            def stop_worker():
                try:
                    for _ in range(50):
                        smp.stop()
                        time.sleep(0.0001)
                except BaseException as exc:
                    errors.append(exc)

            def close_worker():
                try:
                    time.sleep(0.001)
                    smp.close()
                except BaseException as exc:
                    errors.append(exc)

            t1 = threading.Thread(target=stop_worker)
            t2 = threading.Thread(target=close_worker)
            t1.start()
            t2.start()
            t1.join(timeout=2.0)
            t2.join(timeout=2.0)
            self.assertFalse(t1.is_alive())
            self.assertFalse(t2.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(smp._closed)
            self.assertIsNone(smp._handle)


if __name__ == "__main__":
    unittest.main()
