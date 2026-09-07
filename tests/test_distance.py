import unittest

from makhos.core import Rules, apply_move, legal_moves, parse_position
from makhos.distance import DistanceOracle
from makhos.exact import ExactSolver, Outcome
from makhos.native_tablebase import NativeProbe
from makhos.search import Engine, SearchLimits


class _SolverBackedTablebase:
    max_pieces = 3

    def __init__(self, solver, no_progress_plies):
        self.solver = solver
        self.no_progress_plies = no_progress_plies

    def probe(self, state):
        result = self.solver.solve(state)
        return NativeProbe(result.outcome, result.distance)


class DistanceTests(unittest.TestCase):
    def test_incomplete_preserving_child_never_produces_exact_dtm(self):
        rules = Rules(repetition_limit=None, no_progress_plies=80)
        parent = parse_position("R:BM10,25,27:RM6,22,24")
        move = next(move for move in legal_moves(parent) if move.notation == "6x15")
        child = apply_move(parent, move, validate=False)
        child_key = child.board, child.turn, child.reversible_plies

        class PartialOracle(DistanceOracle):
            def __init__(self):
                super().__init__(rules, max_nodes=100)

            def probe(self, state):
                if (state.board, state.turn, state.reversible_plies) == child_key:
                    return NativeProbe(Outcome.LOSS, None)
                # The child has two legal captures: one reaches three pieces and
                # one reaches four. Knowing only the first is not a complete DTM
                # minimax subgraph, even though it supplies a finite distance.
                if sum(piece != 0 for piece in state.board) == 3:
                    return NativeProbe(Outcome.WIN, 5)
                return None

        distance = PartialOracle().for_move(parent, move)
        self.assertEqual(distance.outcome, Outcome.WIN)
        self.assertFalse(distance.exact)
        self.assertIsNone(distance.dtm)

    def test_engine_reports_and_uses_shortest_exact_dtm(self):
        rules = Rules(repetition_limit=None, no_progress_plies=6)
        state = parse_position("B:BK1:RM2")
        result = Engine(rules, exact_piece_limit=2, exact_max_states=500_000).search(
            state, SearchLimits(depth=1)
        )
        self.assertEqual(result.bound.exact_outcome, Outcome.WIN)
        self.assertEqual(result.move.notation, "1-10")
        self.assertTrue(result.distance.exact)
        self.assertEqual(result.distance.dtm, 3)

    def test_dtr_is_exact_only_after_full_bounded_minimax(self):
        rules = Rules(repetition_limit=None, no_progress_plies=4)
        solver = ExactSolver(rules, max_states=500_000)
        oracle = DistanceOracle(
            rules,
            native=_SolverBackedTablebase(solver, rules.no_progress_plies),
            max_nodes=50_000,
        )
        state = parse_position("B:BK1:RK2")
        distance = oracle.for_move(state, legal_moves(state)[0])
        self.assertEqual(distance.outcome, Outcome.DRAW)
        self.assertTrue(distance.exact)
        self.assertEqual(distance.dtr, 4)


if __name__ == "__main__":
    unittest.main()
