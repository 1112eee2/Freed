"""Tests for the UCI-style text protocol."""

import io
import threading
import unittest
from unittest.mock import patch

from makhos import engine_manager
from makhos.cli import main
from makhos.core import apply_move, initial_state, legal_moves
from makhos.parallel_native import MAX_PARALLEL_NATIVE_THREADS
from makhos.search import Engine, Mode, SearchLimits, TimeManager
from makhos.uci import UciSession

RELEASE = {
    "release_id": "test-release",
    "settings": {"threads": 3, "hash_mb_total": 32, "mode": "best", "rules_profile": "project"},
}


class UciTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = Engine()
        self.engine_calls = []

        def get_engine(**kwargs):
            self.engine_calls.append(kwargs)
            return self.engine

        # The real release, TB3 and native files are never touched.
        for name, value in (("get_default_engine", get_engine),
                            ("start_native_tablebase_warmup", lambda: None),
                            ("ensure_native_tablebase_ready", lambda engine: True),
                            ("close_global_engine", lambda: None),
                            ("GUI_NNUE_MODEL_OVERRIDE", None),
                            ("GLOBAL_ENGINE_PROVENANCE", {})):
            patcher = patch.object(engine_manager, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_session(self, text: str) -> list[str]:
        output = io.StringIO()
        self.assertEqual(UciSession(output, RELEASE).run(io.StringIO(text)), 0)
        return output.getvalue().splitlines()

    def canned_result(self):
        return self.engine.search(initial_state(), SearchLimits(depth=1))

    def test_handshake_reports_release_options(self) -> None:
        lines = self.run_session("uci\nisready\nquit\n")
        self.assertEqual(lines, [
            "id name Freed test-release",
            "id author 1112eee2",
            f"option name Threads type spin default 3 min 1 max {MAX_PARALLEL_NATIVE_THREADS}",
            "option name Hash type spin default 32 min 4 max 1024",
            "uciok",
            "readyok",
        ])
        self.assertEqual(self.engine_calls, [{"threads": 3, "hash_mb": 32, "rules_profile": "project"}])

    def test_setoption_applies_valid_values_only(self) -> None:
        lines = self.run_session(
            "setoption name Threads value 2\nsetoption name Hash value 3\n"
            "setoption name Hash value 64\nsetoption name Ponder value true\nisready\n")
        self.assertEqual(lines[:2], ["info string error: Hash must be an integer in 4..1024",
                                     "info string error: unknown option Ponder"])
        self.assertEqual(self.engine_calls[-1], {"threads": 2, "hash_mb": 64, "rules_profile": "project"})

    def test_position_moves_and_go_depth(self) -> None:
        start = initial_state()
        first = legal_moves(start)[0]
        second = legal_moves(apply_move(start, first))[0]
        root = apply_move(apply_move(start, first), second)
        with patch.object(self.engine, "search", wraps=self.engine.search) as search:
            lines = self.run_session(
                f"position startpos moves {first.notation} {second.notation}\ngo depth 1\nquit\n")
        args, kwargs = search.call_args
        self.assertEqual(args, (root,))
        self.assertEqual(kwargs["limits"], SearchLimits(depth=1))
        self.assertIs(kwargs["mode"], Mode.BEST)
        self.assertEqual(sum(kwargs["history"].values()), 3)
        self.assertTrue(lines[0].startswith("info depth 1 score cp "), lines)
        self.assertTrue(lines[1].startswith("info string wdl "), lines)
        self.assertIn(lines[2].removeprefix("bestmove "), {m.notation for m in legal_moves(root)})

    def test_time_control_uses_the_side_to_move_clock(self) -> None:
        start = initial_state()
        first = legal_moves(start)[0]
        with patch.object(self.engine, "search", return_value=self.canned_result()) as search:
            self.run_session(
                "position startpos\ngo btime 60000 wtime 1000 binc 500 winc 0\n"
                f"position startpos moves {first.notation}\ngo btime 60000 wtime 1000 binc 500 winc 0\n")
        first_limits, second_limits = (call.kwargs["limits"] for call in search.call_args_list)
        self.assertEqual(first_limits, SearchLimits(depth=engine_manager.GUI_SEARCH_DEPTH,
                                                    time_ms=TimeManager.allocate_time(60000, 1000, 500, 0)))
        self.assertEqual(second_limits, SearchLimits(depth=engine_manager.GUI_SEARCH_DEPTH,
                                                     time_ms=TimeManager.allocate_time(1000, 60000, 0, 500)))

    def test_refusals_end_with_bestmove_none(self) -> None:
        with patch.object(self.engine, "search") as search:
            lines = self.run_session(
                "position startpos moves 1-2\ngo depth 1\n"
                "position fen B:RM1\ngo depth 1\n"
                "position startpos\ngo infinite\ngo\ngo depth 0\n")
        search.assert_not_called()
        self.assertEqual(lines, [
            "info string error: illegal move 1-2",
            "info string error: no valid position", "bestmove (none)",
            "info string error: game over: no_legal_move", "bestmove (none)",
            "info string error: unsupported go parameter: infinite", "bestmove (none)",
            "info string error: go needs depth, movetime or btime", "bestmove (none)",
            f"info string error: depth must be in 1..{engine_manager.MAX_SEARCH_DEPTH}", "bestmove (none)",
        ])

    def test_endgame_root_is_refused_without_tb3(self) -> None:
        with patch.object(engine_manager, "ensure_native_tablebase_ready", lambda engine: False), \
             patch.object(self.engine, "search") as search:
            lines = self.run_session("position fen B:BM25,26:RM1\ngo depth 1\n")
        search.assert_not_called()
        self.assertTrue(lines[0].startswith("info string error: TB3 "), lines)
        self.assertEqual(lines[1], "bestmove (none)")

    def test_isready_is_answered_while_searching(self) -> None:
        canned = self.canned_result()
        started, release = threading.Event(), threading.Event()

        def slow_search(*args, **kwargs):
            started.set()
            release.wait(10)
            return canned

        output = io.StringIO()
        session = UciSession(output, RELEASE)
        with patch.object(self.engine, "search", side_effect=slow_search):
            session.handle("go depth 5")
            self.assertTrue(started.wait(10))
            session.handle("isready")
            self.assertEqual(output.getvalue(), "readyok\n")
            release.set()
            session.handle("stop")
        self.assertEqual(output.getvalue().splitlines()[-1], f"bestmove {canned.move.notation}")

    def test_cli_selects_the_release_like_the_gui(self) -> None:
        output = io.StringIO()
        with patch.object(engine_manager, "configure_engine_release", return_value=RELEASE) as configure, \
             patch("sys.stdin", io.StringIO("uci\nquit\n")), patch("sys.stdout", output):
            self.assertEqual(main(["uci", "--release-profile", "hce"]), 0)
        configure.assert_called_once_with(None, None, release_pointer=None, release_profile="hce")
        self.assertIn("id name Freed test-release", output.getvalue())


if __name__ == "__main__":
    unittest.main()
