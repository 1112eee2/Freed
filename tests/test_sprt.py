"""Unit tests for the SPRT testing harness."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from makhos.cli import (
    _load_sprt_checkpoint,
    _set_batch_process_priority,
    _write_sprt_checkpoint,
    build_parser,
)
from makhos.core import DEFAULT_RULES, initial_state, legal_moves
from makhos.search import Engine, TimeManager
from makhos.sprt import (
    calculate_pentanomial_sprt,
    calculate_sprt,
    pentanomial_index,
    play_timed_game,
    run_sprt_match,
    SPRTResult,
)
from makhos.workload_isolation import InteractiveSessionActive


class SPRTTests(unittest.TestCase):
    def test_fixed_move_budget_is_exact_for_both_colors_every_ply(self):
        class RecordingEngine:
            def __init__(self):
                self.budgets = []

            def search(self, state, limits, **kwargs):
                self.budgets.append(limits.time_ms)
                return SimpleNamespace(move=legal_moves(state)[0])

        for budget in (1000, 2000):
            black, red = RecordingEngine(), RecordingEngine()
            state = initial_state()
            with patch("makhos.sprt.TimeManager.allocate_time",
                       side_effect=AssertionError("fixed mode used clock allocator")):
                play_timed_game(state, Counter({state.position_key: 1}),
                    black_engine=black, red_engine=red,
                    black_mode="best", red_mode="best", initial_time_ms=1,
                    inc_ms=0, fixed_move_time_ms=budget, max_game_plies=4)
            self.assertEqual(black.budgets, [budget, budget])
            self.assertEqual(red.budgets, [budget, budget])

    def test_fixed_move_budget_rejects_invalid_and_ambiguous_settings(self):
        for budget, cap in ((0, None), (-1, None), (True, None),
                            (1.5, None), (1000, 500)):
            with self.assertRaises(ValueError):
                run_sprt_match(lambda: self.fail("created engine"),
                    lambda: self.fail("created engine"),
                    fixed_move_time_ms=budget, move_time_cap_ms=cap,
                    verbose=False)

    def test_fixed_move_budget_reaches_both_paired_games(self):
        def factory():
            return SimpleNamespace(native_search=None)
        with patch("makhos.sprt.play_timed_game", return_value=(None, "repetition")) as play:
            result = run_sprt_match(factory, factory, fixed_move_time_ms=2000,
                max_pairs=1, opening_plies=0, verbose=False)
        self.assertEqual(result.games, 2)
        self.assertEqual([c.kwargs["fixed_move_time_ms"] for c in play.call_args_list],
                         [2000, 2000])


    def test_batch_priority_uses_windows_below_normal_class(self) -> None:
        with (
            patch("makhos.cli.sys.platform", "win32"),
            patch("makhos.cli._set_windows_process_priority") as set_priority,
        ):
            self.assertEqual(_set_batch_process_priority(), "BelowNormal")
        set_priority.assert_called_once_with(0x00004000)

    def test_persistent_search_is_explicit_and_off_by_default(self) -> None:
        parser = build_parser()
        legacy = parser.parse_args(["sprt"])
        persistent = parser.parse_args(["sprt", "--persistent-search"])

        self.assertFalse(legacy.persistent_search)
        self.assertTrue(persistent.persistent_search)
        self.assertEqual(legacy.max_game_plies, 300)
        self.assertEqual(legacy.threads, 1)
        self.assertIsNone(legacy.dev_threads)
        self.assertIsNone(legacy.master_threads)
        self.assertIsNone(legacy.hash_mb)
        self.assertFalse(legacy.selective_root)
        self.assertFalse(legacy.shared_tt)
        self.assertEqual(legacy.parallel_games, 1)
        self.assertFalse(legacy.no_tablebase)
        self.assertIsNone(legacy.ranked_tablebase)
        self.assertIsNone(legacy.output)
        self.assertFalse(legacy.resume)
        self.assertIsNone(legacy.fixed_move_time_ms)
        fixed = parser.parse_args(["sprt", "--fixed-move-time-ms", "1000"])
        self.assertEqual(fixed.fixed_move_time_ms, 1000)

        machine_readable = parser.parse_args(
            ["sprt", "--output", "build/sprt-result.json"]
        )
        self.assertEqual(machine_readable.output, "build/sprt-result.json")

        resumable = parser.parse_args(
            ["sprt", "--output", "build/sprt-result.json", "--resume"]
        )
        self.assertTrue(resumable.resume)

        selective = parser.parse_args(
            [
                "sprt",
                "--threads",
                "12",
                "--hash-mb",
                "128",
                "--selective-root",
                "--selective-reserve",
                "0.6",
                "--selective-candidates",
                "4",
                "--selective-margin",
                "160",
                "--move-time-cap-ms",
                "50",
            ]
        )
        self.assertEqual(selective.threads, 12)
        self.assertIsNone(selective.dev_threads)
        self.assertIsNone(selective.master_threads)
        self.assertEqual(selective.hash_mb, 128)
        self.assertTrue(selective.selective_root)
        self.assertEqual(selective.move_time_cap_ms, 50)

        shared = parser.parse_args(
            ["sprt", "--threads", "12", "--hash-mb", "128", "--shared-tt"]
        )
        self.assertTrue(shared.shared_tt)
        self.assertEqual(shared.shared_tt_group_size, 4)

        architecture = parser.parse_args(
            [
                "sprt",
                "--threads",
                "4",
                "--dev-threads",
                "1",
                "--master-threads",
                "12",
            ]
        )
        self.assertEqual(architecture.threads, 4)
        self.assertEqual(architecture.dev_threads, 1)
        self.assertEqual(architecture.master_threads, 12)



    def test_calculate_sprt_pass_and_fail(self) -> None:
        # High wins -> PASS
        status_pass, llr_pass, elo_pass, _ = calculate_sprt(wins=2500, draws=500, losses=100)
        self.assertEqual(status_pass, "PASS")
        self.assertGreater(llr_pass, 2.94)
        self.assertGreater(elo_pass, 0.0)

        # High losses -> FAIL
        status_fail, llr_fail, elo_fail, _ = calculate_sprt(wins=100, draws=500, losses=2500)
        self.assertEqual(status_fail, "FAIL")
        self.assertLess(llr_fail, -2.94)
        self.assertLess(elo_fail, 0.0)

    def test_pentanomial_sprt_uses_pair_score_buckets(self) -> None:
        self.assertEqual(pentanomial_index(0.0, 0.0), 0)
        self.assertEqual(pentanomial_index(0.0, 0.5), 1)
        self.assertEqual(pentanomial_index(1.0, 0.0), 2)
        self.assertEqual(pentanomial_index(1.0, 0.5), 3)
        self.assertEqual(pentanomial_index(1.0, 1.0), 4)

        passed = calculate_pentanomial_sprt((20, 50, 200, 800, 1200))
        failed = calculate_pentanomial_sprt((1200, 800, 200, 50, 20))
        self.assertEqual(passed[0], "PASS")
        self.assertEqual(failed[0], "FAIL")
        self.assertGreater(passed[1], 2.94)
        self.assertLess(failed[1], -2.94)

    def test_official_fishtest_logistic_reference_vector(self) -> None:
        # Same pentanomial vector used by official Fishtest's stat_util tests.
        result = calculate_pentanomial_sprt(
            (39, 2226, 31451, 2412, 40),
            elo0=0.2,
            elo1=0.9,
        )
        self.assertAlmostEqual(result[1], 2.162543, places=5)
        self.assertAlmostEqual(result[2], 0.902981, places=5)

    def test_run_sprt_match_fails_closed_on_max_ply_truncation(self) -> None:
        def engine_factory():
            return Engine(DEFAULT_RULES)

        with self.assertRaisesRegex(
            RuntimeError,
            r"pair 1 truncated.*no result was recorded",
        ):
            run_sprt_match(
                engine_factory,
                engine_factory,
                max_pairs=1,
                initial_time_ms=50,
                inc_ms=10,
                move_time_cap_ms=1,
                parallel_games=2,
                max_game_plies=20,
                verbose=False,
            )

    def test_timed_game_uses_clock_allocation_without_hidden_30ms_cap(self) -> None:
        class RecordingEngine:
            def __init__(self):
                self.time_ms = None

            def search(self, state, limits, **_kwargs):
                self.time_ms = limits.time_ms
                return SimpleNamespace(move=legal_moves(state)[0])

        black = RecordingEngine()
        state = initial_state()
        play_timed_game(
            state,
            Counter({state.position_key: 1}),
            black_engine=black,
            black_mode="best",
            red_engine=RecordingEngine(),
            red_mode="best",
            initial_time_ms=10_000,
            inc_ms=100,
            max_game_plies=1,
        )
        expected = TimeManager.allocate_time(10_000, 10_000, 100, 100)
        self.assertGreater(expected, 30)
        self.assertEqual(black.time_ms, expected)

    def test_timed_game_yields_before_search_when_gui_requests_priority(self) -> None:
        class NeverSearchedEngine:
            def search(self, *_args, **_kwargs):
                self.fail("search must not start after the GUI priority event")

            def fail(self, message):
                raise AssertionError(message)

        checkpoints = []

        def checkpoint(stage: str) -> None:
            checkpoints.append(stage)
            raise InteractiveSessionActive("PAUSED_FOR_INTERACTIVE_PLAY")

        state = initial_state()
        with self.assertRaisesRegex(
            InteractiveSessionActive,
            "PAUSED_FOR_INTERACTIVE_PLAY",
        ):
            play_timed_game(
                state,
                Counter({state.position_key: 1}),
                black_engine=NeverSearchedEngine(),
                black_mode="best",
                red_engine=NeverSearchedEngine(),
                red_mode="best",
                initial_time_ms=100,
                inc_ms=10,
                max_game_plies=1,
                workload_checkpoint=checkpoint,
            )
        self.assertEqual(checkpoints, ["SPRT game ply 1"])

    def test_sprt_yields_before_engine_creation_when_gui_is_active(self) -> None:
        factory_calls = 0

        def engine_factory():
            nonlocal factory_calls
            factory_calls += 1
            return Engine(DEFAULT_RULES)

        def checkpoint(_stage: str) -> None:
            raise InteractiveSessionActive("PAUSED_FOR_INTERACTIVE_PLAY")

        with self.assertRaisesRegex(
            InteractiveSessionActive,
            "PAUSED_FOR_INTERACTIVE_PLAY",
        ):
            run_sprt_match(
                engine_factory,
                engine_factory,
                max_pairs=1,
                verbose=False,
                workload_checkpoint=checkpoint,
            )
        self.assertEqual(factory_calls, 0)

    def test_resumed_sprt_replays_the_same_opening_stream(self) -> None:
        class FirstMoveEngine:
            native_search = None

            def search(self, state, _limits, **_kwargs):
                return SimpleNamespace(move=legal_moves(state)[0])

        def engine_factory():
            return FirstMoveEngine()

        full = run_sprt_match(
            engine_factory,
            engine_factory,
            max_pairs=2,
            seed=8675309,
            verbose=False,
        )
        checkpoints = []
        first = run_sprt_match(
            engine_factory,
            engine_factory,
            max_pairs=1,
            seed=8675309,
            verbose=False,
            on_pair_completed=checkpoints.append,
        )
        resumed = run_sprt_match(
            engine_factory,
            engine_factory,
            max_pairs=2,
            seed=8675309,
            verbose=False,
            resume_result=first,
        )

        self.assertEqual(checkpoints, [first])
        self.assertEqual(resumed, full)

    def test_gui_interruption_preserves_only_complete_pairs_for_resume(self) -> None:
        class FirstMoveEngine:
            native_search = None

            def search(self, state, _limits, **_kwargs):
                return SimpleNamespace(move=legal_moves(state)[0])

        def engine_factory():
            return FirstMoveEngine()

        full = run_sprt_match(
            engine_factory,
            engine_factory,
            max_pairs=2,
            seed=314159,
            verbose=False,
        )
        completed = []

        def checkpoint(stage: str) -> None:
            if stage == "SPRT pair 2":
                raise InteractiveSessionActive("PAUSED_FOR_INTERACTIVE_PLAY")

        with self.assertRaises(InteractiveSessionActive):
            run_sprt_match(
                engine_factory,
                engine_factory,
                max_pairs=2,
                seed=314159,
                verbose=False,
                workload_checkpoint=checkpoint,
                on_pair_completed=completed.append,
            )
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].games, 2)

        resumed = run_sprt_match(
            engine_factory,
            engine_factory,
            max_pairs=2,
            seed=314159,
            verbose=False,
            resume_result=completed[0],
        )
        self.assertEqual(resumed, full)

    def test_atomic_sprt_checkpoint_rejects_config_drift(self) -> None:
        result = SPRTResult(
            status="INCONCLUSIVE",
            llr=0.25,
            elo=3.0,
            elo_error=12.0,
            wins=1,
            draws=0,
            losses=1,
            games=2,
            pentanomial=(0, 0, 1, 0, 0),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "checkpoint.json"
            _write_sprt_checkpoint(
                output,
                config={"seed": 123, "max_pairs": 10},
                result=result,
                complete=False,
            )
            loaded, complete = _load_sprt_checkpoint(
                output,
                expected_config={"seed": 123, "max_pairs": 10},
            )
            self.assertEqual(loaded, result)
            self.assertFalse(complete)
            self.assertFalse(output.with_suffix(".json.tmp").exists())

            with self.assertRaisesRegex(ValueError, "configuration mismatch"):
                _load_sprt_checkpoint(
                    output,
                    expected_config={"seed": 124, "max_pairs": 10},
                )

    def test_fixed_time_checkpoint_cannot_resume_with_other_budget_or_clock_mode(self):
        result = SPRTResult("INCONCLUSIVE", 0, 0, 0, 0, 0, 0, 0)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixed.json"
            config = {"seed": 20261103, "fixed_move_time_ms": 1000}
            _write_sprt_checkpoint(output, config=config, result=result, complete=False)
            self.assertEqual(_load_sprt_checkpoint(output, expected_config=config)[0], result)
            for different in ({"seed": 20261103, "fixed_move_time_ms": 2000},
                              {"seed": 20261103}):
                with self.assertRaisesRegex(ValueError, "configuration mismatch"):
                    _load_sprt_checkpoint(output, expected_config=different)

    def test_sprt_parser_has_native_endgame_flags(self):
        parser = build_parser()
        args = parser.parse_args(["sprt"])
        self.assertTrue(args.native_endgame)
        self.assertIsNone(args.native_endgame_library)

        args = parser.parse_args(["sprt", "--no-native-endgame"])
        self.assertFalse(args.native_endgame)

        args = parser.parse_args(["sprt", "--native-endgame", "--native-endgame-library", "test.dll"])
        self.assertTrue(args.native_endgame)
        self.assertEqual(args.native_endgame_library, "test.dll")

    def test_sprt_match_closes_native_endgame_search(self):
        from unittest.mock import MagicMock

        class MockEngine:
            def __init__(self):
                self.native_search = MagicMock()
                self.native_endgame_search = MagicMock()

            def search(self, state, limits, **kwargs):
                return SimpleNamespace(move=legal_moves(state)[0])

        dev_eg = MockEngine()
        master_eg = MockEngine()
        with self.assertRaises(RuntimeError):
            run_sprt_match(
                lambda: dev_eg,
                lambda: master_eg,
                max_pairs=1,
                max_game_plies=2,
                seed=42,
            )
        self.assertGreaterEqual(dev_eg.native_endgame_search.close.call_count, 1)
        self.assertGreaterEqual(master_eg.native_endgame_search.close.call_count, 1)

    def test_command_sprt_attaches_c4_endgame_to_factories(self):
        from makhos.cli import command_sprt, build_parser
        from contextlib import ExitStack, redirect_stdout
        import io

        captured_dev = None
        captured_master = None

        def fake_run_sprt_match(dev_factory, master_factory, **kwargs):
            nonlocal captured_dev, captured_master
            captured_dev = dev_factory()
            captured_master = master_factory()
            return SPRTResult("INCONCLUSIVE", 0.0, 0.0, 0.0, 0, 0, 0, 0, (0, 0, 0, 0, 0))

        # This is a factory-wiring contract, not a real arena or DLL parity gate.
        # Keep it usable on a clean checkout and independent of stopped experiments.
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            for name in ("dev.dll", "master.dll", "endgame.dll", "model.mknnue", "ranked.bin"):
                (root / name).write_bytes(name.encode("ascii"))
            args = build_parser().parse_args([
                "sprt", "--dev-library", str(root / "dev.dll"),
                "--master-library", str(root / "master.dll"),
                "--dev-nnue-model", str(root / "model.mknnue"),
                "--master-nnue-model", str(root / "model.mknnue"),
                "--dev-threads", "6", "--master-threads", "12",
                "--native-endgame", "--native-endgame-library", str(root / "endgame.dll"),
                "--ranked-tablebase", str(root / "ranked.bin"), "--pairs", "1",
            ])
            module = "makhos.cli_handlers.sprt_handler."
            preflight = stack.enter_context(patch(module + "NativeSearch"))
            preflight.return_value.__enter__.return_value = SimpleNamespace(
                abi_version=5, supports_fixed_search=True, supports_window_search=True,
                supports_shared_tt=True, nnue_enabled=True, nnue_model_sha256="a" * 64,
                nnue_feature_abi="thai-makhos-shared-137-v1",
            )
            stack.enter_context(patch(module + "ParallelNativeSearch"))
            legacy_tb = stack.enter_context(patch(module + "NativeTablebase"))
            legacy_tb.return_value.no_progress_plies = 80
            ranked = stack.enter_context(patch(module + "RankedTablebase"))
            ranked.return_value = SimpleNamespace(path=root / "ranked.bin", piece_count=6,
                no_progress_plies=80, expected_checksum=0, close=Mock())
            stack.enter_context(patch("makhos.compact_tb3.CompactTablebase"))
            tablebase = stack.enter_context(patch("makhos.native_endgame.NativeEndgameTablebase"))
            def endgame_factory(tb, *, threads, nnue_model):
                self.assertEqual(nnue_model, root / "model.mknnue")
                return SimpleNamespace(tablebase=tb, threads=threads, evaluator="nnue", close=Mock())
            stack.enter_context(patch("makhos.native_endgame_search.ParallelNativeEndgameSearch",
                                      side_effect=endgame_factory))
            stack.enter_context(patch(module + "BatchWorkLease"))
            stack.enter_context(patch(module + "_set_batch_process_priority", return_value="test"))
            stack.enter_context(patch("makhos.sprt.run_sprt_match", side_effect=fake_run_sprt_match))
            with redirect_stdout(io.StringIO()):
                command_sprt(args)
            tablebase.return_value.close.assert_called_once()

        self.assertIsNotNone(captured_dev)
        self.assertIsNotNone(captured_master)
        try:
            self.assertTrue(captured_dev.native_endgame_enabled)
            self.assertEqual(captured_dev.native_endgame_search.threads, 6)
            self.assertEqual(captured_dev.native_endgame_search.evaluator, "nnue")

            self.assertTrue(captured_master.native_endgame_enabled)
            self.assertEqual(captured_master.native_endgame_search.threads, 12)
            self.assertEqual(captured_master.native_endgame_search.evaluator, "nnue")

            self.assertIs(
                captured_dev.native_endgame_search.tablebase,
                captured_master.native_endgame_search.tablebase,
            )
        finally:
            captured_dev.native_endgame_search.close()
            captured_master.native_endgame_search.close()


if __name__ == "__main__":
    unittest.main()
