import random
import unittest

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
    opponent,
    parse_position,
    state_from_pieces,
)
from makhos.nnue_features import (
    ALL_PIECES,
    CLOCK_BUCKETS,
    CLOCK_FEATURE_OFFSET,
    INPUT_DIMENSIONS,
    PIECE_SQUARE_FEATURES,
    both_perspective_feature_deltas,
    canonical_square,
    clock_bucket,
    clock_feature_index,
    feature_spec_payload,
    ordered_accumulator_features,
    perspective_active_features,
    perspective_feature_delta,
    piece_feature_index,
    relative_piece_category,
)


SWAPPED_PIECE = {
    RED_MAN: BLACK_MAN,
    BLACK_MAN: RED_MAN,
    RED_KING: BLACK_KING,
    BLACK_KING: RED_KING,
}


def rotate_and_swap(state: State) -> State:
    board = [EMPTY] * 32
    for square, piece in enumerate(state.board):
        if piece != EMPTY:
            board[31 - square] = SWAPPED_PIECE[piece]
    return State(
        tuple(board),
        opponent(state.turn),
        state.reversible_plies,
        state.ply,
    )


class NnueFeatureOracleTests(unittest.TestCase):
    def assert_delta_reconstructs(
        self,
        parent: State,
        child: State,
        perspective: int,
    ) -> None:
        delta = perspective_feature_delta(parent, child, perspective)
        before = set(perspective_active_features(parent, perspective))
        after = set(perspective_active_features(child, perspective))
        self.assertFalse(set(delta.removed) & set(delta.added))
        self.assertTrue(set(delta.removed) <= before)
        self.assertFalse(set(delta.added) & before)
        reconstructed = (before - set(delta.removed)) | set(delta.added)
        self.assertEqual(reconstructed, after)
        self.assertTrue(all(0 <= index < INPUT_DIMENSIONS for index in after))

    def test_machine_readable_feature_contract_is_exact(self):
        self.assertEqual(
            feature_spec_payload(),
            {
                "name": "thai-makhos-shared-137-v1",
                "input_dimensions": 137,
                "piece_square_features": 128,
                "clock_buckets": [
                    "0",
                    "1_to_9",
                    "10_to_19",
                    "20_to_29",
                    "30_to_39",
                    "40_to_49",
                    "50_to_59",
                    "60_to_69",
                    "70_to_79",
                ],
                "black_canonical_square": "identity",
                "red_canonical_square": "31_minus_square",
                "perspective_categories": [
                    "own_man",
                    "own_king",
                    "opponent_man",
                    "opponent_king",
                ],
                "active_features": "piece_count_plus_one",
                "concatenation_order": ["side_to_move", "opponent"],
            },
        )
        self.assertEqual(INPUT_DIMENSIONS, 137)
        self.assertEqual(PIECE_SQUARE_FEATURES, 128)
        self.assertEqual(len(CLOCK_BUCKETS), 9)

    def test_piece_feature_mapping_is_a_bijection_for_each_perspective(self):
        for perspective in (BLACK, RED):
            mapped = {
                piece_feature_index(piece, square, perspective)
                for piece in ALL_PIECES
                for square in range(32)
            }
            self.assertEqual(mapped, set(range(PIECE_SQUARE_FEATURES)))

    def test_exact_sparse_indices_for_both_perspectives(self):
        state = parse_position(
            "B:BM25:BK20:RM6:RK10",
            reversible_plies=10,
        )
        self.assertEqual(
            perspective_active_features(state, BLACK),
            (24, 51, 69, 105, 130),
        )
        self.assertEqual(
            perspective_active_features(state, RED),
            (26, 54, 71, 108, 130),
        )

    def test_clock_buckets_cover_exactly_zero_through_79(self):
        boundaries = {
            0: 0,
            1: 1,
            9: 1,
            10: 2,
            19: 2,
            20: 3,
            69: 7,
            70: 8,
            79: 8,
        }
        for value, expected in boundaries.items():
            self.assertEqual(clock_bucket(value), expected)
        self.assertEqual(
            {clock_feature_index(value) for value in range(80)},
            set(range(CLOCK_FEATURE_OFFSET, INPUT_DIMENSIONS)),
        )
        for value in (-1, 80, 81):
            with self.assertRaises(ValueError):
                clock_bucket(value)
        with self.assertRaises(TypeError):
            clock_bucket(True)

    def test_active_count_is_piece_count_plus_one(self):
        state = initial_state()
        for perspective in (BLACK, RED):
            active = perspective_active_features(state, perspective)
            self.assertEqual(len(active), 17)
            self.assertEqual(len(active), len(set(active)))

    def test_side_to_move_concatenation_order_is_explicit(self):
        state = parse_position("R:BM25:BK20:RM6:RK10", reversible_plies=39)
        ordered = ordered_accumulator_features(state)
        self.assertEqual(ordered.side_to_move_player, RED)
        self.assertEqual(
            ordered.side_to_move,
            perspective_active_features(state, RED),
        )
        self.assertEqual(
            ordered.opponent,
            perspective_active_features(state, BLACK),
        )

    def test_rotation_and_color_swap_preserve_relative_features(self):
        state = parse_position(
            "B:BM19,25,27:BK31:RM1,6:RK10",
            reversible_plies=47,
        )
        transformed = rotate_and_swap(state)
        self.assertEqual(
            perspective_active_features(state, BLACK),
            perspective_active_features(transformed, RED),
        )
        self.assertEqual(
            perspective_active_features(state, RED),
            perspective_active_features(transformed, BLACK),
        )
        original_order = ordered_accumulator_features(state)
        transformed_order = ordered_accumulator_features(transformed)
        self.assertEqual(original_order.side_to_move, transformed_order.side_to_move)
        self.assertEqual(original_order.opponent, transformed_order.opponent)

    def test_quiet_capture_and_promotion_deltas_include_clock_semantics(self):
        quiet_parent = parse_position(
            "B:BM25:RK1",
            reversible_plies=9,
        )
        quiet_move = legal_moves(quiet_parent)[0]
        self.assertFalse(quiet_move.is_capture)
        self.assertFalse(quiet_move.promotes)
        quiet_child = apply_move(quiet_parent, quiet_move)
        for perspective in (BLACK, RED):
            delta = perspective_feature_delta(
                quiet_parent, quiet_child, perspective
            )
            self.assertIn(clock_feature_index(9), delta.removed)
            self.assertIn(clock_feature_index(10), delta.added)
            self.assert_delta_reconstructs(quiet_parent, quiet_child, perspective)

        capture_parent = state_from_pieces(
            {(4, 3): BLACK_MAN, (3, 2): RED_MAN, (5, 2): RED_MAN},
            BLACK,
            reversible_plies=37,
        )
        capture_move = legal_moves(capture_parent)[0]
        self.assertTrue(capture_move.is_capture)
        capture_child = apply_move(capture_parent, capture_move)
        for perspective in (BLACK, RED):
            delta = perspective_feature_delta(
                capture_parent, capture_child, perspective
            )
            self.assertIn(clock_feature_index(37), delta.removed)
            self.assertIn(clock_feature_index(0), delta.added)
            self.assertEqual(len(delta.removed), 3)
            self.assertEqual(len(delta.added), 2)
            self.assert_delta_reconstructs(capture_parent, capture_child, perspective)

        promotion_parent = parse_position(
            "R:RM25:BK5",
            reversible_plies=7,
        )
        promotion_move = next(
            move for move in legal_moves(promotion_parent) if move.promotes
        )
        promotion_child = apply_move(promotion_parent, promotion_move)
        for perspective in (BLACK, RED):
            delta = perspective_feature_delta(
                promotion_parent, promotion_child, perspective
            )
            self.assertIn(clock_feature_index(7), delta.removed)
            self.assertIn(clock_feature_index(0), delta.added)
            self.assertEqual(len(delta.removed), 2)
            self.assertEqual(len(delta.added), 2)
            self.assert_delta_reconstructs(
                promotion_parent, promotion_child, perspective
            )

    def test_clock_delta_changes_only_when_the_bucket_changes(self):
        parent = parse_position("B:BM25:RK1", reversible_plies=1)
        child = apply_move(parent, legal_moves(parent)[0])
        for perspective in (BLACK, RED):
            delta = perspective_feature_delta(parent, child, perspective)
            self.assertNotIn(clock_feature_index(1), delta.removed)
            self.assertNotIn(clock_feature_index(2), delta.added)
            self.assertEqual(len(delta.removed), 1)
            self.assertEqual(len(delta.added), 1)
            self.assert_delta_reconstructs(parent, child, perspective)

    def test_multi_capture_delta_removes_every_captured_piece(self):
        parent = state_from_pieces(
            {(6, 1): BLACK_MAN, (5, 2): RED_MAN, (3, 4): RED_MAN},
            BLACK,
            reversible_plies=12,
        )
        move = legal_moves(parent)[0]
        self.assertEqual(len(move.captures), 2)
        child = apply_move(parent, move)
        for perspective in (BLACK, RED):
            delta = perspective_feature_delta(parent, child, perspective)
            self.assertEqual(len(delta.removed), 4)
            self.assertEqual(len(delta.added), 2)
            self.assert_delta_reconstructs(parent, child, perspective)

    def test_random_legal_play_preserves_symmetry_and_delta_reconstruction(self):
        rng = random.Random(20280828)
        state = initial_state()
        transitions = 0
        while transitions < 300:
            moves = legal_moves(state)
            if not moves or state.reversible_plies >= 79:
                state = initial_state(rng.choice((BLACK, RED)))
                continue
            child = apply_move(state, rng.choice(moves))
            transformed = rotate_and_swap(state)
            self.assertEqual(
                perspective_active_features(state, BLACK),
                perspective_active_features(transformed, RED),
            )
            self.assertEqual(
                perspective_active_features(state, RED),
                perspective_active_features(transformed, BLACK),
            )
            deltas = both_perspective_feature_deltas(state, child)
            self.assertEqual(tuple(delta.perspective for delta in deltas), (BLACK, RED))
            for perspective in (BLACK, RED):
                self.assert_delta_reconstructs(state, child, perspective)
            state = child
            transitions += 1

    def test_invalid_indices_pieces_and_perspectives_fail_closed(self):
        with self.assertRaises(ValueError):
            relative_piece_category(EMPTY, BLACK)
        for perspective in (0, 3, True):
            with self.assertRaises(ValueError):
                canonical_square(0, perspective)
        for square in (-1, 32):
            with self.assertRaises(ValueError):
                canonical_square(square, BLACK)
        with self.assertRaises(TypeError):
            canonical_square(False, BLACK)


if __name__ == "__main__":
    unittest.main()
