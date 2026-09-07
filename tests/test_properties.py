import random
import unittest

from makhos.core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    Move,
    RED,
    RED_KING,
    RED_MAN,
    State,
    apply_move,
    index_to_coord,
    legal_moves,
    opponent,
    piece_player,
    coord_to_index,
)


SWAP_PIECE = {
    EMPTY: EMPTY,
    RED_MAN: BLACK_MAN,
    BLACK_MAN: RED_MAN,
    RED_KING: BLACK_KING,
    BLACK_KING: RED_KING,
}


def rotate_square(square: int) -> int:
    row, col = index_to_coord(square)
    rotated = coord_to_index(7 - row, 7 - col)
    assert rotated is not None
    return rotated


def rotate_state(state: State) -> State:
    board = [EMPTY] * 32
    for square, piece in enumerate(state.board):
        board[rotate_square(square)] = SWAP_PIECE[piece]
    return State(tuple(board), opponent(state.turn), state.reversible_plies, state.ply)


def rotate_move(move: Move) -> Move:
    return Move(
        tuple(rotate_square(square) for square in move.path),
        tuple(rotate_square(square) for square in move.captures),
        move.promotes,
    )


class PropertyTests(unittest.TestCase):
    def test_random_positions_preserve_color_rotation_symmetry_and_counts(self):
        rng = random.Random(0x4D414B484F53)
        pieces = (RED_MAN, BLACK_MAN, RED_KING, BLACK_KING)
        checked_moves = 0
        for _ in range(500):
            board = [EMPTY] * 32
            for square in rng.sample(range(32), rng.randint(2, 12)):
                piece = rng.choice(pieces)
                row, _ = index_to_coord(square)
                if piece == RED_MAN and row == 7:
                    piece = RED_KING
                elif piece == BLACK_MAN and row == 0:
                    piece = BLACK_KING
                board[square] = piece
            turn = rng.choice((RED, BLACK))
            # Ensure both players exist; otherwise terminal positions still obey
            # symmetry but provide little move-application coverage.
            if not any(piece_player(piece) == RED for piece in board):
                board[0] = RED_MAN
            if not any(piece_player(piece) == BLACK for piece in board):
                board[31] = BLACK_MAN
            state = State(tuple(board), turn)
            rotated = rotate_state(state)

            expected = {rotate_move(move) for move in legal_moves(state)}
            self.assertEqual(expected, set(legal_moves(rotated)))

            own_before = sum(piece_player(piece) == turn for piece in state.board)
            enemy_before = sum(piece_player(piece) == opponent(turn) for piece in state.board)
            moves = legal_moves(state)
            if moves and any(move.is_capture for move in moves):
                self.assertTrue(all(move.is_capture for move in moves))
            for move in moves:
                after = apply_move(state, move, validate=False)
                own_after = sum(piece_player(piece) == turn for piece in after.board)
                enemy_after = sum(piece_player(piece) == opponent(turn) for piece in after.board)
                self.assertEqual(own_after, own_before)
                self.assertEqual(enemy_after, enemy_before - len(move.captures))
                checked_moves += 1
        self.assertGreater(checked_moves, 1_000)


if __name__ == "__main__":
    unittest.main()

