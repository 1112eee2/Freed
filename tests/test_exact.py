import unittest

from makhos.core import BLACK, BLACK_KING, BLACK_MAN, RED_KING, RED_MAN, Rules, state_from_pieces
from makhos.exact import ExactSolver, Outcome


class ExactSolverTests(unittest.TestCase):
    def setUp(self):
        self.rules = Rules(repetition_limit=None, no_progress_plies=8)

    def test_rejects_history_dependent_repetition_rules(self):
        with self.assertRaises(ValueError):
            ExactSolver(Rules(repetition_limit=3))

    def test_forced_capture_is_exact_win(self):
        state = state_from_pieces({(4, 3): BLACK_MAN, (3, 2): RED_MAN}, BLACK)
        result = ExactSolver(self.rules).solve(state)
        self.assertEqual(result.outcome, Outcome.WIN)
        self.assertEqual(result.distance, 1)
        self.assertEqual(len(result.best_moves), 1)

    def test_promotion_that_blocks_opponent_is_exact_win(self):
        state = state_from_pieces(
            {
                (1, 2): BLACK_MAN,
                (5, 2): BLACK_MAN,
                (6, 1): BLACK_MAN,
                (7, 0): RED_KING,
            },
            BLACK,
        )
        result = ExactSolver(self.rules).solve(state)
        self.assertEqual(result.outcome, Outcome.WIN)
        self.assertEqual(result.distance, 1)

    def test_separated_kings_draw_at_small_no_progress_limit(self):
        state = state_from_pieces({(0, 1): BLACK_KING, (0, 3): RED_KING}, BLACK)
        result = ExactSolver(self.rules, max_states=100_000).solve(state)
        self.assertEqual(result.outcome, Outcome.DRAW)


if __name__ == "__main__":
    unittest.main()
