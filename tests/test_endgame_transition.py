"""Multi-capture admission: route the whole root, preserve per-move proofs.

Contract doubles are explicitly not TB evidence. Real C4 tests below need an
isolated library; the human-game DRAW assertion additionally needs real TB4-6.
"""
from collections import Counter
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from makhos.compact_tb3 import CompactTablebase
from makhos.core import State, apply_move, initial_state, legal_moves, parse_position
from makhos.endgame_routing import is_native_endgame_position
from makhos.exact import Outcome
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import (
    EndgameResult, NativeEndgameSearch, NativeRoot, ParallelNativeEndgameSearch,
)
from makhos.search import Engine, Mode, SearchLimits, UNKNOWN_WDL, WDLBound
import makhos.server as server
from tests.test_server import DummyHandler

ROOT = Path(__file__).resolve().parents[1]
MAGNUM = "B:BM23,26:BK15:RM13,14,19,21,27"
NINE = "B:BK6,13,14:RK4,16,17,18,19,21"
LIBRARY = ROOT / ("build/native_endgame_c4/makhos_endgame_search_nnue"
                  + (".dll" if os.name == "nt" else ".so"))
MODEL = ROOT / "build/nnue_quantized_v1/model_a.mknnue"
TB_PATHS = tuple(ROOT / f"build/tb{n}_np80.compact.bin" for n in (4, 5, 6))


class RecordingEndgame:
    """Synthetic root-policy contract, never a solved tablebase fixture."""
    evaluator = "hce"
    supports_position = NativeEndgameSearch.supports_position

    def __init__(self):
        self.calls = []

    def search(self, state, **kwargs):
        self.calls.append((state, kwargs))
        roots = tuple(NativeRoot(
            0 if m.notation == "15x24x31" else 214,
            WDLBound.exact(Outcome.DRAW) if m.notation == "15x24x31" else UNKNOWN_WDL,
            (m,),
        ) for m in legal_moves(state))
        return EndgameResult(0, 1, roots, 0, None, None, 2, (0,) * 7, 0)


class TransitionRoutingTests(unittest.TestCase):
    def test_real_multi_capture_material_edges(self):
        for position, expected in (
            (MAGNUM, {"15x24x31": 6, "23x16": 7}),
            (NINE, {"6x24": 8, "13x22x15x24": 6, "14x23": 8}),
            ("B:BM23,26:BK15:RM13,14,19,21", {"15x24": 6, "23x16": 6}),
        ):
            with self.subTest(position=position):
                state = parse_position(position)
                actual = {m.notation: sum(bool(p) for p in apply_move(state, m).board)
                          for m in legal_moves(state)}
                self.assertEqual(actual, expected)
                self.assertTrue(is_native_endgame_position(state))
                self.assertTrue(server.is_native_endgame_position(state))
                self.assertTrue(NativeEndgameSearch.supports_position(None, state))

    def test_quiet_midgame_and_non_crossing_captures_stay_out(self):
        for state in (initial_state(), parse_position("B:BK1,5,6,9:RK24,28,31,32"),
                      parse_position("B:BK6,13,14,32:RK4,16,17,18,19,21")):
            with self.subTest(state=state):
                self.assertFalse(is_native_endgame_position(state))

    def test_admission_matches_verified_child_material(self):
        rng = random.Random(20260911)
        for _ in range(300):
            board = [0] * 32
            for i, square in enumerate(rng.sample(range(32), rng.randrange(2, 17))):
                board[square] = 3 if i % 2 else 4
            state = State(tuple(board), rng.choice((1, 2)))
            expected = sum(bool(p) for p in board) <= 6 or any(
                sum(bool(p) for p in apply_move(state, m).board) <= 6
                for m in legal_moves(state))
            self.assertEqual(is_native_endgame_position(state), expected)

    def test_route_preserves_every_root_bound_policy_and_history(self):
        state = replace(parse_position(MAGNUM), reversible_plies=79)
        backend = RecordingEndgame()
        engine = Engine(native_endgame_search=backend, native_endgame_enabled=True,
                        exact_piece_limit=0)
        histories = [Counter({state.position_key: n}) for n in (1, 2, 1)]
        original = [h.copy() for h in histories]
        sentinel = object()
        engine._tt[state.position_key] = sentinel
        for history in histories:
            for mode in Mode:
                with patch.object(engine, "_choose", wraps=engine._choose) as choose:
                    result = engine.search(state, SearchLimits(depth=2, time_ms=1000),
                                           mode=mode, history=history)
                self.assertEqual(engine.last_search_backend, "native-endgame")
                choose.assert_called_once()
                candidates = {c.move.notation: c for c in result.candidates}
                self.assertEqual(set(candidates), {"15x24x31", "23x16"})
                self.assertEqual(candidates["15x24x31"].bound, WDLBound.exact(Outcome.DRAW))
                self.assertEqual(candidates["15x24x31"].score, 0)
                self.assertEqual(candidates["23x16"].bound, UNKNOWN_WDL)
                self.assertEqual(candidates["23x16"].score, 214)
                received, kwargs = backend.calls[-1]
                self.assertEqual(received.reversible_plies, 79)
                self.assertEqual(kwargs["history"], history)
                self.assertEqual(kwargs["rules"], engine.rules)
                self.assertEqual(kwargs["time_ms"], 1000)
        self.assertEqual(histories, original)
        self.assertIs(engine._tt[state.position_key], sentinel)

    def test_flag_off_and_reference_search_do_not_offload(self):
        for kwargs in ({"native_endgame_enabled": False},
                       {"native_endgame_enabled": True, "reference_search": True}):
            backend = RecordingEndgame()
            engine = Engine(native_endgame_search=backend, exact_piece_limit=0, **kwargs)
            result = engine.search(parse_position(MAGNUM), SearchLimits(depth=1))
            self.assertEqual(backend.calls, [])
            self.assertNotEqual(engine.last_search_backend, "native-endgame")
            self.assertIn(result.move, legal_moves(parse_position(MAGNUM)))

    def test_terminal_root_precedes_admission(self):
        backend = RecordingEndgame()
        engine = Engine(native_endgame_search=backend, native_endgame_enabled=True)
        state = parse_position(MAGNUM)
        for root, history in ((replace(state, reversible_plies=80), None),
                              (state, Counter({state.position_key: 3}))):
            with self.assertRaisesRegex(ValueError, "terminal"):
                engine.search(root, SearchLimits(depth=1), history=history)
        self.assertEqual(backend.calls, [])

    def test_native_failure_keeps_legal_fallback(self):
        engine = Engine(native_endgame_search=RecordingEndgame(),
                        native_endgame_enabled=True, exact_piece_limit=0)
        with patch.object(engine.native_endgame_search, "search", side_effect=ValueError("probe failed")):
            result = engine.search(parse_position(MAGNUM), SearchLimits(depth=1, time_ms=10))
        self.assertEqual(engine.last_search_backend, "python-fallback")
        self.assertIn("probe failed", engine.last_native_error)
        self.assertIn(result.move, legal_moves(parse_position(MAGNUM)))

    def test_server_prepares_transition_but_skips_forced_and_flag_off(self):
        for position, enabled, prepare in ((MAGNUM, True, True), (MAGNUM, False, False),
                                          ("B:BM18,25:RM14,1", True, False)):
            with self.subTest(position=position, enabled=enabled):
                engine = Engine(native_endgame_search=RecordingEndgame(),
                                native_endgame_enabled=enabled, exact_piece_limit=0)
                handler = DummyHandler({})
                with patch.object(server, "get_default_engine", return_value=engine), \
                     patch.object(server, "ensure_native_tablebase_ready", return_value=True) as tb, \
                     patch.object(server, "ensure_native_endgame_ready", return_value=True) as ready, \
                     patch.object(server, "GUI_NNUE_MODEL_OVERRIDE", None), \
                     patch.object(server, "GLOBAL_ENGINE_PROVENANCE", {}):
                    handler.handle_bestmove({"position": position, "depth": 1, "time_sec": 1,
                                             "use_full_time": False, "native_endgame": enabled})
                self.assertEqual(handler.response_status, 200, handler.wfile.bytes)
                self.assertEqual(ready.called, prepare)
                self.assertEqual(tb.called, prepare)
                if prepare:
                    self.assertEqual(json.loads(handler.wfile.bytes)["search_backend"], "native-endgame")


@unittest.skipUnless(LIBRARY.is_file() and MODEL.is_file(), "isolated C4 library and model required")
class NativeTransitionTests(unittest.TestCase):
    def test_real_c4_all_root_parity_and_reuse_without_ranked_files(self):
        # Real TB3 only: verify TB misses above three preserve all alternatives.
        # No claim about the human game's TB6 outcome is made in this test.
        with CompactTablebase() as tb3, NativeEndgameTablebase(tb3, library=LIBRARY) as tb, \
             NativeEndgameSearch(tb, nnue_model=MODEL) as one, \
             ParallelNativeEndgameSearch(tb, threads=4, nnue_model=MODEL) as many:
            for notation in (MAGNUM, NINE):
                state = parse_position(notation)
                first = one.search(state, depth=2)
                self.assertEqual({r.pv[0] for r in first.roots}, set(legal_moves(state)))
                self.assertEqual(first.roots, many.search(state, depth=2).roots)
                # H1 -> terminal H2 -> H1 on the same native session.
                self.assertEqual(one.search(state, depth=2,
                    history={state.position_key: 3}).terminal_reason, 1)
                self.assertEqual(first.roots, one.search(state, depth=2).roots)
                engine = Engine(native_endgame_search=many, native_endgame_enabled=True,
                                native_tablebase=tb3, exact_piece_limit=0)
                for mode in Mode:
                    routed = engine.search(state, SearchLimits(depth=2), mode=mode)
                    self.assertEqual(engine.last_search_backend, "native-endgame")
                    expected = first.choose(engine, state, mode)
                    self.assertEqual((routed.move, routed.score, routed.bound, routed.pv),
                                     (expected.move, expected.score, expected.bound, expected.pv))
                    self.assertEqual({c.move for c in routed.candidates}, set(legal_moves(state)))

    @unittest.skipUnless(all(p.is_file() for p in TB_PATHS), "real TB4-TB6 artifacts required")
    def test_human_game_draw_child_with_real_ranked_tablebases(self):
        with ExitStack() as stack:
            tb3 = stack.enter_context(CompactTablebase())
            tb = stack.enter_context(NativeEndgameTablebase(tb3, library=LIBRARY, ranked_paths=TB_PATHS))
            state = parse_position(MAGNUM)
            draw_move = next(m for m in legal_moves(state) if m.notation == "15x24x31")
            self.assertEqual(tb.probe(apply_move(state, draw_move)).outcome, Outcome.DRAW)
            reference_roots = None
            for threads in (1, 2, 4, 6, 8, 12):
                native = stack.enter_context(ParallelNativeEndgameSearch(tb, threads=threads, nnue_model=MODEL))
                engine = Engine(native_endgame_search=native, native_endgame_enabled=True,
                                native_tablebase=tb3, exact_piece_limit=0)
                for mode in Mode:
                    result = engine.search(state, SearchLimits(depth=2, time_ms=1000), mode=mode)
                    self.assertEqual(engine.last_search_backend, "native-endgame")
                    roots = {c.move.notation: (c.score, c.bound, c.pv) for c in result.candidates}
                    self.assertEqual(set(roots), {"15x24x31", "23x16"})
                    self.assertEqual(roots["15x24x31"][:2], (0, WDLBound.exact(Outcome.DRAW)))
                    self.assertGreater(result.tablebase_hits, 0)
                    if reference_roots is None:
                        reference_roots = roots
                    self.assertEqual(roots, reference_roots)


if __name__ == "__main__":
    unittest.main()
