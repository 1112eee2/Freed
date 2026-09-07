import unittest

from makhos.core import BLACK, BLACK_KING, BLACK_MAN, Move, RED_KING, RED_MAN, Rules, apply_move, legal_moves, parse_position, state_from_pieces
from makhos.exact import Outcome
from makhos.native_tablebase import NativeProbe
from makhos.proof import EndgameOracle, NonLossProver, ProofStrategy, _exact_state_id
from makhos.search import Engine, Mode, RootCandidate, SearchLimits, UNKNOWN_WDL, WDLBound


class SearchTests(unittest.TestCase):
    def test_proof_tablebase_leaf_derives_safe_fallback_moves(self):
        class DrawNative:
            no_progress_plies = 1

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        state = parse_position("B:BK1:RK32")
        rules = Rules(repetition_limit=None, no_progress_plies=1)
        oracle = EndgameOracle(native=DrawNative())
        certificate, _ = NonLossProver(
            rules, oracle, node_budget=10
        ).prove(state, BLACK)
        self.assertEqual(
            certificate["nodes"][certificate["root"]]["kind"],
            "tablebase",
        )
        strategy = ProofStrategy(certificate, oracle)
        safe_moves = strategy.moves_for(state)
        self.assertEqual(len(safe_moves), 7)
        result = Engine(
            Rules(repetition_limit=3, no_progress_plies=1),
            exact_piece_limit=0,
            proof_strategy=strategy,
        ).search(state, SearchLimits(depth=1), mode=Mode.WIN)
        self.assertEqual(result.proof_safe_moves, safe_moves)
        self.assertIn(result.move, safe_moves)
        self.assertGreaterEqual(result.bound.lower, Outcome.DRAW)

    def test_json_tablebase_leaf_continues_outside_certificate_frontier(self):
        class DrawNative:
            max_pieces = 3
            no_progress_plies = 80

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        root = parse_position("B:BK1:RK32")
        rules = Rules(repetition_limit=None, no_progress_plies=80)
        oracle = EndgameOracle(native=DrawNative())
        certificate, _ = NonLossProver(
            rules, oracle, node_budget=10
        ).prove(root, BLACK)
        strategy = ProofStrategy(certificate, oracle)
        first = strategy.moves_for(root)[0]
        opponent_state = apply_move(root, first, validate=False)
        reply = legal_moves(opponent_state)[0]
        continuation = apply_move(opponent_state, reply, validate=False)
        self.assertTrue(strategy.moves_for(continuation))

    def test_engine_fails_closed_if_strategy_returns_no_move(self):
        class EmptyStrategy:
            root_player = BLACK
            no_progress_plies = 80

            @staticmethod
            def moves_for(_state):
                return ()

        state = parse_position("B:BK1:RK32")
        engine = Engine(
            Rules(repetition_limit=3, no_progress_plies=80),
            exact_piece_limit=0,
            proof_strategy=EmptyStrategy(),
        )
        with self.assertRaisesRegex(ValueError, "no safe moves"):
            engine.search(state, SearchLimits(depth=1), mode=Mode.WIN)

    def test_native_v2_certificate_ids_drive_runtime_strategy(self):
        state = parse_position("B:BK1:RK32")
        rules = Rules(repetition_limit=None, no_progress_plies=1)
        oracle = EndgameOracle()
        certificate, _ = NonLossProver(
            rules, oracle, node_budget=100
        ).prove(state, BLACK)
        id_map = {
            old_id: _exact_state_id(parse_position(
                node["position"], reversible_plies=node["clock"]
            ))
            for old_id, node in certificate["nodes"].items()
        }
        for node in certificate["nodes"].values():
            for edge in node.get("edges", ()):
                edge["child"] = id_map[edge["child"]]
        certificate["nodes"] = {
            id_map[old_id]: node
            for old_id, node in certificate["nodes"].items()
        }
        certificate["root"] = id_map[certificate["root"]]
        certificate["format"] = "makhos-nonloss-proof-v2"

        strategy = ProofStrategy(certificate, oracle)
        self.assertEqual(strategy.move_for(state).notation, "1-6")

    def test_all_certified_safe_moves_remain_available_to_policy(self):
        state = parse_position("B:BK1:RK32")
        rules = Rules(repetition_limit=None, no_progress_plies=1)
        oracle = EndgameOracle()
        certificate, _ = NonLossProver(
            rules,
            oracle,
            node_budget=100,
            collect_all_choices=True,
        ).prove(state, BLACK)
        self.assertIsNotNone(certificate)
        strategy = ProofStrategy(certificate, oracle)
        safe_moves = strategy.moves_for(state)
        self.assertEqual(len(safe_moves), 7)

        engine = Engine(
            Rules(repetition_limit=3, no_progress_plies=1),
            exact_piece_limit=0,
            proof_strategy=strategy,
        )
        for mode in (Mode.BEST, Mode.WIN):
            result = engine.search(state, SearchLimits(depth=1), mode=mode)
            self.assertTrue(result.proof_strategy_used)
            self.assertEqual(result.proof_safe_moves, safe_moves)
            self.assertEqual(
                {candidate.move for candidate in result.candidates},
                set(safe_moves),
            )
            self.assertIn(result.move, safe_moves)
            self.assertGreaterEqual(result.bound.lower, Outcome.DRAW)

    def test_verified_proof_strategy_forces_certificate_move(self):
        state = parse_position("B:BK1:RK32")
        rules = Rules(repetition_limit=None, no_progress_plies=1)
        oracle = EndgameOracle()
        certificate, _ = NonLossProver(
            rules, oracle, node_budget=100
        ).prove(state, BLACK)
        self.assertIsNotNone(certificate)
        strategy = ProofStrategy(certificate, oracle)
        expected = strategy.move_for(state)
        result = Engine(
            Rules(repetition_limit=3, no_progress_plies=1),
            exact_piece_limit=0,
            proof_strategy=strategy,
        ).search(state, SearchLimits(depth=1), mode=Mode.WIN)
        self.assertEqual(result.move, expected)
        self.assertTrue(result.proof_strategy_used)
        self.assertGreaterEqual(result.bound.lower, Outcome.DRAW)
        with self.assertRaisesRegex(ValueError, "outside the verified"):
            strategy.move_for(parse_position("B:BK2:RK32"))

    def test_engine_finds_forced_capture(self):
        state = state_from_pieces(
            {(4, 3): BLACK_MAN, (3, 2): RED_MAN},
            BLACK,
        )
        engine = Engine()
        result = engine.search(state, SearchLimits(depth=3))
        self.assertTrue(result.move.is_capture)
        self.assertGreater(result.score, 900_000)
        self.assertEqual(result.bound.exact_outcome, Outcome.WIN)
        self.assertEqual(engine.last_search_backend, "forced")

    def test_native_failure_records_python_fallback_backend(self):
        class FailingNativeSearch:
            @staticmethod
            def search(*_args, **_kwargs):
                raise RuntimeError("synthetic native failure")

        state = parse_position(
            "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"
        )
        engine = Engine(exact_piece_limit=0, native_search=FailingNativeSearch())
        result = engine.search(state, SearchLimits(depth=2))
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(engine.last_search_backend, "python-fallback")
        self.assertEqual(engine.last_native_error, "synthetic native failure")

    def test_search_rejects_root_at_no_progress_terminal(self):
        rules = Rules(repetition_limit=None, no_progress_plies=1)
        state = parse_position("B:BK1:RK32", reversible_plies=1)
        with self.assertRaisesRegex(ValueError, "terminal position"):
            Engine(rules, exact_piece_limit=0).search(
                state, SearchLimits(depth=1)
            )

    def test_search_rejects_root_at_repetition_terminal(self):
        rules = Rules(repetition_limit=3, no_progress_plies=80)
        state = parse_position("B:BK1:RK32")
        history = {state.position_key: 3}
        with self.assertRaisesRegex(ValueError, "terminal position"):
            Engine(rules, exact_piece_limit=0).search(
                state, SearchLimits(depth=1), history=history
            )

    def test_modes_return_legal_moves_without_crossing_safety_score(self):
        state = state_from_pieces(
            {(6, 1): BLACK_KING, (3, 4): RED_MAN, (1, 6): RED_MAN},
            BLACK,
        )
        engine = Engine()
        best = engine.search(state, SearchLimits(depth=3), mode=Mode.BEST)
        win = engine.search(state, SearchLimits(depth=3, win_margin=0), mode=Mode.WIN)
        self.assertEqual(win.score, best.score)

    def test_search_uses_exact_solver_in_two_piece_endgame(self):
        state = state_from_pieces({(0, 1): BLACK_KING, (0, 3): RED_KING}, BLACK)
        result = Engine(exact_piece_limit=2).search(state, SearchLimits(depth=2))
        self.assertGreater(result.tablebase_hits, 0)
        self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)

    def test_proven_draw_outranks_higher_unknown_heuristic(self):
        engine = Engine(exact_piece_limit=0)
        unknown = RootCandidate(Move((0, 4)), 500, (), 999.0, UNKNOWN_WDL)
        proven_draw = RootCandidate(
            Move((1, 5)), 0, (), 0.0, WDLBound.exact(Outcome.DRAW)
        )
        for mode in (Mode.BEST, Mode.WIN):
            chosen = engine._choose((unknown, proven_draw), mode, win_margin=1000)
            self.assertEqual(chosen.move, proven_draw.move)

    def test_exact_two_king_draw_is_reported_as_proven(self):
        state = state_from_pieces({(0, 1): BLACK_KING, (0, 3): RED_KING}, BLACK)
        result = Engine(exact_piece_limit=2, exact_max_states=200_000).search(
            state, SearchLimits(depth=1)
        )
        self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)

    def test_tablebase_outcomes_are_bounded_when_repetition_rule_differs(self):
        engine = Engine(Rules(repetition_limit=3), exact_piece_limit=0)
        self.assertEqual(
            engine._tablebase_bound(Outcome.WIN),
            WDLBound(Outcome.DRAW, Outcome.WIN),
        )
        self.assertEqual(
            engine._tablebase_bound(Outcome.LOSS),
            WDLBound(Outcome.LOSS, Outcome.DRAW),
        )
        self.assertEqual(
            engine._tablebase_bound(Outcome.DRAW),
            WDLBound.exact(Outcome.DRAW),
        )

    def test_search_probes_ranked_four_piece_tablebase(self):
        class DrawTablebase:
            no_progress_plies = 80
            piece_count = 4

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        state = parse_position("B:BK24,30:RM9,18")
        result = Engine(
            exact_piece_limit=0,
            ranked_tablebase=DrawTablebase(),
        ).search(state, SearchLimits(depth=1))
        self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)
        self.assertEqual(result.tablebase_hits, len(result.candidates))

    def test_engine_selects_ranked_tablebase_by_piece_count(self):
        class CountingTablebase:
            no_progress_plies = 80

            def __init__(self, piece_count):
                self.piece_count = piece_count
                self.calls = 0

            def probe(self, _state):
                self.calls += 1
                return NativeProbe(Outcome.DRAW, None)

        four = CountingTablebase(4)
        five = CountingTablebase(5)
        engine = Engine(
            exact_piece_limit=0,
            ranked_tablebases=(four, five),
        )
        state = parse_position("B:BM25,26,27:RM1,2")
        score, bound = engine._probe_exact(state)
        self.assertEqual(score, 0)
        self.assertEqual(bound.exact_outcome, Outcome.DRAW)
        self.assertEqual(four.calls, 0)
        self.assertEqual(five.calls, 1)


if __name__ == "__main__":
    unittest.main()
