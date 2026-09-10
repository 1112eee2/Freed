"""C3 routing, policy, provenance and candidate NNUE regression coverage."""

from collections import Counter
from dataclasses import replace
from pathlib import Path
import json
import unittest
from unittest.mock import patch

import makhos.server as server
from makhos.compact_tb3 import CompactTablebase
from makhos.core import Rules, apply_move, legal_moves, parse_position
from makhos.exact import Outcome
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import (
    EndgameResult,
    NativeEndgameSearch,
    NativeRoot,
)
from makhos.search import Engine, MATE_SCORE, Mode, SearchLimits, WDLBound
from tests.test_endgame_repetition import WINNING_MOVES, repetition_fixture
from tests.test_server import DummyHandler


ROOT = Path(__file__).resolve().parents[1]
C3_LIBRARY = ROOT / "build/native_endgame_c3/makhos_endgame_search_nnue.dll"
NNUE_MODEL = ROOT / "build/nnue_quantized_v1/model_a.mknnue"


class FakeEndgame:
    evaluator = "hce"

    def __init__(self, *, supports=True):
        self.supports = supports
        self.search_calls = 0
        self.clear_calls = 0

    def supports_position(self, _state):
        return self.supports

    def search(self, state, *, depth, **_kwargs):
        self.search_calls += 1
        roots = tuple(
            NativeRoot(
                MATE_SCORE - 500 if index == 0 else 0,
                WDLBound.exact(Outcome.WIN) if index == 0
                else WDLBound.exact(Outcome.DRAW),
                (move,),
            )
            for index, move in enumerate(legal_moves(state))
        )
        return EndgameResult(0, depth, roots, 0, None, None, 3, (0,) * 7, 0)

    def clear(self):
        self.clear_calls += 1


class NativeEndgameRoutingTests(unittest.TestCase):
    def setUp(self):
        self.state = parse_position("B:BK6,15:RK28")

    def test_default_off_keeps_python_route(self):
        backend = FakeEndgame()
        engine = Engine(native_endgame_search=backend, exact_piece_limit=0)
        result = engine.search(self.state, SearchLimits(depth=1))
        self.assertNotEqual(engine.last_search_backend, "native-endgame")
        self.assertEqual(backend.search_calls, 0)
        self.assertIn(result.move, legal_moves(self.state))

    def test_enabled_route_reuses_proved_root_policy(self):
        backend = FakeEndgame()
        engine = Engine(
            native_endgame_search=backend,
            native_endgame_enabled=True,
            exact_piece_limit=0,
        )
        result = engine.search(self.state, SearchLimits(depth=2), mode=Mode.WIN)
        self.assertEqual(engine.last_search_backend, "native-endgame")
        self.assertEqual(backend.search_calls, 1)
        self.assertEqual(result.bound, WDLBound.exact(Outcome.WIN))
        self.assertEqual(result.move, result.candidates[0].move)
        self.assertTrue(result.score >= MATE_SCORE - 10_000)

    def test_capability_flag_alias_is_accepted(self):
        backend = FakeEndgame()
        engine = Engine(
            native_endgame_search=backend,
            native_endgame=True,
            exact_piece_limit=0,
        )
        engine.search(self.state, SearchLimits(depth=1))
        self.assertEqual(backend.search_calls, 1)

    def test_terminal_check_precedes_native_backend(self):
        backend = FakeEndgame()
        engine = Engine(
            Rules(repetition_limit=3),
            native_endgame_search=backend,
            native_endgame_enabled=True,
            exact_piece_limit=0,
        )
        with self.assertRaisesRegex(ValueError, "terminal"):
            engine.search(
                self.state,
                SearchLimits(depth=1),
                history=Counter({self.state.position_key: 3}),
            )
        self.assertEqual(backend.search_calls, 0)

    def test_clear_resets_configured_backend(self):
        backend = FakeEndgame()
        Engine(native_endgame_search=backend, native_endgame_enabled=True).clear()
        self.assertEqual(backend.clear_calls, 1)

    def test_nnue_profile_does_not_downgrade_to_hce_candidate(self):
        backend = FakeEndgame()
        legacy = type("NnueProfile", (), {"nnue_enabled": True})()
        engine = Engine(
            native_search=legacy,
            native_endgame_search=backend,
            native_endgame_enabled=True,
            exact_piece_limit=3,
        )
        self.assertFalse(engine._can_use_native_endgame(self.state, proof_strategy_used=False))
        self.assertEqual(backend.search_calls, 0)
        self.assertIn("requires an NNUE", engine.last_native_error)

    def test_server_reports_opt_in_route_and_capability(self):
        backend = FakeEndgame()
        engine = Engine(
            native_endgame_search=backend,
            native_endgame_enabled=True,
            exact_piece_limit=0,
        )
        handler = DummyHandler({})
        with patch("makhos.server.get_default_engine", return_value=engine), \
             patch("makhos.server.ensure_native_tablebase_ready", return_value=True), \
             patch("makhos.server.ensure_native_endgame_ready", return_value=True), \
             patch("makhos.server.GUI_NNUE_MODEL_OVERRIDE", None), \
             patch("makhos.server.GLOBAL_ENGINE_PROVENANCE", {}):
            handler.handle_bestmove({
                "position": "B:BK6,15:RK28",
                "depth": 1,
                "time_sec": 1,
                "use_full_time": False,
                "native_endgame": True,
            })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["search_backend"], "native-endgame")
        self.assertTrue(data["native_endgame_enabled"])
        self.assertTrue(data["native_endgame_ready"])
        self.assertEqual(data["native_endgame_evaluator"], "hce")
        self.assertEqual(data["search_thread_capacity"], 1)


@unittest.skipUnless(C3_LIBRARY.is_file() and NNUE_MODEL.is_file(), "C3 NNUE candidate artifacts are absent")
class NativeEndgameCandidateTests(unittest.TestCase):
    def test_nnue_candidate_keeps_tb_proof_authoritative(self):
        state, history = repetition_fixture()
        with CompactTablebase() as tb3, \
             NativeEndgameTablebase(tb3, library=C3_LIBRARY) as tb, \
             NativeEndgameSearch(tb, nnue_model=NNUE_MODEL) as native:
            engine = Engine(
                Rules(repetition_limit=3),
                native_tablebase=tb3,
                native_endgame_search=native,
                native_endgame_enabled=True,
                exact_piece_limit=0,
            )
            self.assertEqual(native.evaluator, "nnue")
            for depth in (1, 2, 4, 6):
                for mode in Mode:
                    with self.subTest(depth=depth, mode=mode):
                        result = engine.search(
                            state,
                            SearchLimits(depth=depth),
                            mode=mode,
                            history=history,
                        )
                        self.assertEqual(engine.last_search_backend, "native-endgame")
                        self.assertIn(result.move.notation, WINNING_MOVES)
                        self.assertEqual(result.bound.exact_outcome, Outcome.WIN)

            # At the 79-ply boundary the same raw TB win is only a
            # repetition-safe draw; NNUE must not override that proof interval.
            near_clock = replace(state, reversible_plies=79)
            near_history = history.copy()
            near_history[near_clock.position_key] = 1
            result = engine.search(
                near_clock,
                SearchLimits(depth=2),
                mode=Mode.WIN,
                history=near_history,
            )
            self.assertEqual(result.score, 0)
            self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)

            losing_move = next(move for move in legal_moves(state) if move.notation == "6-9")
            losing_state = apply_move(state, losing_move)
            losing_history = history.copy()
            losing_history[losing_state.position_key] += 1
            for mode in Mode:
                result = engine.search(
                    losing_state,
                    SearchLimits(depth=2),
                    mode=mode,
                    history=losing_history,
                )
                self.assertEqual(result.move.notation, "28-32")
                self.assertEqual(result.score, 0)
                self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)


if __name__ == "__main__":
    unittest.main()
