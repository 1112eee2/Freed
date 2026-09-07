"""Unit tests for the Handcrafted Evaluation module."""

import unittest
import random

from makhos.core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    State,
    apply_move,
    initial_state,
    legal_moves,
)
from makhos.eval import (
    KING_VALUE,
    MAN_VALUE,
    evaluate_handcrafted,
    evaluate_endgame_king_value,
    evaluation_features,
    trace_evaluation,
)


class EvalTests(unittest.TestCase):

    def test_initial_position_eval_is_balanced(self) -> None:
        # Initial board setup
        board = [EMPTY] * 32
        for sq in range(24, 32):
            board[sq] = BLACK_MAN
        for sq in range(0, 8):
            board[sq] = RED_MAN
        state = State(tuple(board), BLACK)

        score_black = evaluate_handcrafted(state, BLACK)
        score_red = evaluate_handcrafted(state, RED)

        self.assertEqual(score_black, -score_red)
        # Starting board symmetry should be equal
        self.assertEqual(score_black, 0)

    def test_material_advantage(self) -> None:
        # Red has an extra man
        board = [EMPTY] * 32
        board[0] = RED_MAN
        board[1] = RED_MAN
        board[30] = BLACK_MAN
        state = State(tuple(board), RED)

        score_red = evaluate_handcrafted(state, RED)
        score_black = evaluate_handcrafted(state, BLACK)

        self.assertGreaterThan(score_red, 0)
        self.assertLessThan(score_black, 0)
        self.assertEqual(score_red, -score_black)

    def test_king_worth_more_than_man(self) -> None:
        # Red has a king, Black has a man
        board = [EMPTY] * 32
        board[10] = RED_KING
        board[20] = BLACK_MAN
        state = State(tuple(board), RED)

        score_red = evaluate_handcrafted(state, RED)
        self.assertGreaterThan(score_red, KING_VALUE - MAN_VALUE)

    def test_passed_man_bonus(self) -> None:
        # Red man on sq 22 (row 5) with no black pieces ahead
        board = [EMPTY] * 32
        board[22] = RED_MAN
        board[31] = BLACK_MAN  # Black man on back rank far away
        state_passed = State(tuple(board), RED)

        score_red = evaluate_handcrafted(state_passed, RED)
        self.assertGreaterThan(score_red, 40)

    def test_endgame_king_value_tapers_only_through_twelve_pieces(self) -> None:
        board = [EMPTY] * 32
        board[10] = RED_KING
        board[20] = BLACK_MAN
        six_piece = State(tuple(board), RED)
        self.assertEqual(
            evaluate_endgame_king_value(six_piece, RED),
            evaluate_handcrafted(six_piece, RED) - 126,
        )
        self.assertEqual(
            evaluate_endgame_king_value(six_piece, BLACK),
            -evaluate_endgame_king_value(six_piece, RED),
        )

        for square in (0, 1, 2, 3, 4, 5, 6, 24, 25, 26, 27):
            board[square] = RED_MAN if square < 7 else BLACK_MAN
        thirteen_piece = State(tuple(board), RED)
        self.assertEqual(
            evaluate_endgame_king_value(thirteen_piece, RED),
            evaluate_handcrafted(thirteen_piece, RED),
        )

    def test_evaluation_trace_matches_hot_evaluator_on_random_play(self) -> None:
        rng = random.Random(20260813)
        state = initial_state()
        for _ in range(500):
            for perspective in (BLACK, RED):
                trace = trace_evaluation(state, perspective)
                self.assertEqual(trace.score, evaluate_handcrafted(state, perspective))
                if trace.terminal_score is None:
                    self.assertEqual(sum(trace.relative_terms.values()), trace.score)
                    self.assertEqual(
                        int(evaluation_features(state, perspective).score()),
                        trace.score,
                    )
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )

    def assertGreaterThan(self, a, b):
        self.assertGreater(a, b)

    def assertLessThan(self, a, b):
        self.assertLess(a, b)


if __name__ == "__main__":
    unittest.main()
