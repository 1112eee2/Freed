import unittest

from makhos.core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    RED,
    RED_KING,
    RED_MAN,
    Rules,
    apply_move,
    coord_to_index,
    initial_state,
    legal_moves,
    format_position,
    parse_position,
    perft,
    state_from_pieces,
    terminal_status,
)


class RuleTests(unittest.TestCase):
    def test_initial_setup_and_first_perft_levels(self):
        state = initial_state()
        self.assertEqual(sum(piece != 0 for piece in state.board), 16)
        # Independent Thai-draughts reference values published by Rein Halbersma.
        expected = {1: 7, 2: 49, 3: 392, 4: 3_136, 5: 26_592}
        self.assertEqual({depth: perft(state, depth) for depth in expected}, expected)

    def test_man_capture_is_mandatory_and_forward_only(self):
        state = state_from_pieces(
            {(4, 3): BLACK_MAN, (3, 2): RED_MAN, (5, 2): RED_MAN}, BLACK
        )
        moves = legal_moves(state)
        self.assertEqual(len(moves), 1)
        self.assertTrue(moves[0].is_capture)
        self.assertEqual(moves[0].end, coord_to_index(2, 1))

    def test_man_must_complete_multi_jump(self):
        state = state_from_pieces(
            {(6, 1): BLACK_MAN, (5, 2): RED_MAN, (3, 4): RED_MAN}, BLACK
        )
        moves = legal_moves(state)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len(moves[0].captures), 2)
        self.assertEqual(
            moves[0].path,
            (coord_to_index(6, 1), coord_to_index(4, 3), coord_to_index(2, 5)),
        )

    def test_promotion_ends_capture_chain(self):
        state = state_from_pieces(
            {(2, 1): BLACK_MAN, (1, 2): RED_MAN, (1, 4): RED_MAN}, BLACK
        )
        move = legal_moves(state)[0]
        self.assertTrue(move.promotes)
        self.assertEqual(len(move.captures), 1)
        self.assertEqual(move.end, coord_to_index(0, 3))
        after = apply_move(state, move)
        self.assertEqual(after.board[move.end], BLACK_KING)

    def test_king_must_land_immediately_behind_captured_piece(self):
        state = state_from_pieces({(6, 1): BLACK_KING, (3, 4): RED_MAN}, BLACK)
        moves = legal_moves(state)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].end, coord_to_index(2, 5))

    def test_immediate_removal_allows_king_to_reverse_direction(self):
        state = state_from_pieces(
            {(4, 3): BLACK_KING, (2, 5): RED_MAN, (5, 2): RED_MAN}, BLACK
        )
        moves = legal_moves(state)
        expected = (
            coord_to_index(4, 3),
            coord_to_index(1, 6),
            coord_to_index(6, 1),
        )
        self.assertIn(expected, [move.path for move in moves])
        move = next(move for move in moves if move.path == expected)
        after = apply_move(state, move)
        self.assertEqual(sum(piece in (RED_MAN, RED_KING) for piece in after.board), 0)

    def test_any_complete_capture_sequence_may_be_chosen(self):
        state = state_from_pieces(
            {
                (6, 1): BLACK_MAN,
                (5, 2): RED_MAN,
                (3, 4): RED_MAN,
                (6, 5): BLACK_MAN,
                (5, 6): RED_MAN,
            },
            BLACK,
        )
        capture_lengths = sorted(len(move.captures) for move in legal_moves(state))
        self.assertEqual(capture_lengths, [1, 2])

    def test_blocked_side_loses(self):
        state = state_from_pieces({(1, 0): BLACK_MAN, (0, 1): RED_MAN}, BLACK)
        status = terminal_status(state)
        self.assertTrue(status.terminal)
        self.assertEqual(status.winner, RED)

    def test_draw_counters_are_explicit(self):
        rules = Rules(repetition_limit=3, no_progress_plies=4)
        state = state_from_pieces({(4, 3): BLACK_KING, (3, 4): RED_KING}, BLACK)
        self.assertEqual(terminal_status(state, repetition_count=3, rules=rules).reason, "repetition")
        old = state_from_pieces(
            {(4, 3): BLACK_KING, (3, 4): RED_KING}, BLACK, reversible_plies=4
        )
        self.assertEqual(terminal_status(old, rules=rules).reason, "no_progress")

    def test_no_progress_draw_precedes_no_legal_move_loss(self):
        rules = Rules(repetition_limit=None, no_progress_plies=4)
        state = state_from_pieces(
            {(1, 0): BLACK_MAN, (0, 1): RED_MAN},
            BLACK,
            reversible_plies=4,
        )
        self.assertEqual(legal_moves(state), ())
        status = terminal_status(state, rules=rules)
        self.assertTrue(status.is_draw)
        self.assertEqual(status.reason, "no_progress")

    def test_position_text_round_trip(self):
        state = parse_position("B:BM25,26:BK29:RM5,6:RK1", reversible_plies=7)
        self.assertEqual(format_position(state), "B:BM25,26:BK29:RM5,6:RK1")
        self.assertEqual(state.reversible_plies, 7)

    def test_position_rejects_unpromoted_man_on_king_row(self):
        with self.assertRaisesRegex(ValueError, "black man.*promotion row"):
            parse_position("B:BM1:RK32")
        with self.assertRaisesRegex(ValueError, "red man.*promotion row"):
            parse_position("R:BK1:RM29")


if __name__ == "__main__":
    unittest.main()
