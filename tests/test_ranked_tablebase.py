import random
import tempfile
import unittest
from pathlib import Path

from makhos.core import (
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED_KING,
    RED_MAN,
    parse_position,
)
from makhos.ranked_tablebase import (
    RankedTablebase,
    _COMPACT_HEADER,
    _COMPACT_MAGIC,
    _HEADER,
    _MAGIC,
    _SIGNATURE_COUNTS,
    _SIGNATURE_HEADER,
    _VERSION,
    _canonical_signature_counts,
    _completion_count,
    _rank_board,
    _unrank_board,
)


class RankedTablebaseTests(unittest.TestCase):
    @staticmethod
    def _write_compact_draw_tablebase(
        path: Path,
        *,
        piece_count: int = 4,
        no_progress_plies: int = 1,
    ) -> dict[tuple[int, int, int, int], int]:
        counts_in_order = _canonical_signature_counts(piece_count)
        boards_by_signature = {
            counts: _completion_count(0, *counts)
            for counts in counts_in_order
        }
        total_positions = 2 * sum(boards_by_signature.values())
        total_states = total_positions * (no_progress_plies + 1)
        header_offsets = {}
        with path.open("wb") as file:
            file.write(_COMPACT_HEADER.pack(
                _COMPACT_MAGIC,
                _VERSION,
                piece_count,
                no_progress_plies,
                len(counts_in_order),
                total_positions,
                total_states,
                0,
            ))
            for counts in counts_in_order:
                boards = boards_by_signature[counts]
                byte_count = boards * 2
                header_offsets[counts] = file.tell()
                file.write(_SIGNATURE_HEADER.pack(*counts, boards, byte_count))
                file.seek(byte_count, 1)
            file.truncate()
        return header_offsets

    @staticmethod
    def _board(placements):
        board = [EMPTY] * 32
        for square, piece in placements.items():
            board[square] = piece
        return tuple(board)

    def test_two_black_kings_two_red_kings_board_count(self):
        self.assertEqual(_completion_count(0, 0, 2, 0, 2), 215_760)

    def test_five_piece_board_count(self):
        self.assertEqual(_completion_count(0, 0, 3, 0, 2), 2_013_760)

    def test_six_piece_metadata_and_board_count(self):
        self.assertEqual(_SIGNATURE_COUNTS[6], 70)
        self.assertEqual(_completion_count(0, 0, 3, 0, 3), 18_123_840)

    def test_canonical_signature_schema_matches_native_counts(self):
        for piece_count, expected in _SIGNATURE_COUNTS.items():
            with self.subTest(piece_count=piece_count):
                signatures = _canonical_signature_counts(piece_count)
                self.assertEqual(len(signatures), expected)
                self.assertEqual(
                    signatures,
                    tuple(sorted(
                        signatures,
                        key=lambda counts: (counts[0] + counts[2], *counts),
                    )),
                )

    def test_equal_sized_signature_header_swap_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "swapped.compact.bin"
            offsets = self._write_compact_draw_tablebase(path)
            by_size = {}
            for counts in offsets:
                boards = _completion_count(0, *counts)
                by_size.setdefault(boards, []).append(counts)
            first, second = next(
                group[:2] for group in by_size.values() if len(group) >= 2
            )
            self.assertEqual(
                _completion_count(0, *first),
                _completion_count(0, *second),
            )
            with path.open("r+b") as file:
                file.seek(offsets[first])
                first_header = file.read(4)
                file.seek(offsets[second])
                second_header = file.read(4)
                file.seek(offsets[first])
                file.write(second_header)
                file.seek(offsets[second])
                file.write(first_header)
            with self.assertRaisesRegex(ValueError, "canonical order"):
                RankedTablebase(path)

    def test_no_progress_horizon_domain_matches_native_readers(self):
        cases = (
            (
                _COMPACT_HEADER.pack(
                    _COMPACT_MAGIC, _VERSION, 4, 0, 25, 0, 0, 0
                ),
                "compact-zero",
            ),
            (
                _COMPACT_HEADER.pack(
                    _COMPACT_MAGIC, _VERSION, 4, 127, 25, 0, 0, 0
                ),
                "compact-too-large",
            ),
            (_HEADER.pack(_MAGIC, _VERSION, 0, 25, 0, 0), "full-zero"),
            (_HEADER.pack(_MAGIC, _VERSION, 201, 25, 0, 0), "full-too-large"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for header, name in cases:
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.bin"
                    path.write_bytes(header)
                    with self.assertRaisesRegex(ValueError, "horizon"):
                        RankedTablebase(path)

    def test_reserved_compact_threshold_code_is_rejected_on_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reserved-threshold.compact.bin"
            self._write_compact_draw_tablebase(path)
            state = parse_position("B:BK1,5:RK2,6")
            tablebase = RankedTablebase(path)
            signature = tablebase._signatures[(0, 2, 0, 2)]
            payload_offset = (
                signature.data_offset +
                _rank_board(state.board, signature.counts) * 2 +
                1
            )
            tablebase.close()
            with path.open("r+b") as file:
                file.seek(payload_offset)
                file.write(b"\x80")
            tablebase = RankedTablebase(path)
            try:
                with self.assertRaisesRegex(ValueError, "threshold"):
                    tablebase.probe(state)
            finally:
                tablebase.close()

    def test_python_rank_matches_native_known_position(self):
        state = parse_position("B:BK1,5:RK2,6")
        self.assertEqual(_rank_board(state.board, (0, 2, 0, 2)), 202_133)

    def test_first_and_last_rank_for_four_five_and_six_king_signatures(self):
        cases = (
            ((0, 2, 0, 2), 2, 2),
            ((0, 3, 0, 2), 3, 2),
            ((0, 3, 0, 3), 3, 3),
        )
        for counts, black_kings, red_kings in cases:
            with self.subTest(counts=counts):
                piece_count = black_kings + red_kings
                first = {
                    32 - piece_count + index: BLACK_KING
                    for index in range(black_kings)
                }
                first.update({
                    32 - red_kings + index: RED_KING
                    for index in range(red_kings)
                })
                last = {
                    index: RED_KING
                    for index in range(red_kings)
                }
                last.update({
                    red_kings + index: BLACK_KING
                    for index in range(black_kings)
                })
                boards = _completion_count(0, *counts)
                self.assertEqual(_rank_board(self._board(first), counts), 0)
                self.assertEqual(
                    _rank_board(self._board(last), counts),
                    boards - 1,
                )
                self.assertEqual(
                    _rank_board(_unrank_board(0, counts), counts),
                    0,
                )
                self.assertEqual(
                    _rank_board(_unrank_board(boards - 1, counts), counts),
                    boards - 1,
                )

    def test_random_unrank_round_trips_for_all_piece_counts(self):
        rng = random.Random(20260910)
        cases = (
            (1, 1, 1, 1),
            (2, 1, 1, 1),
            (2, 1, 2, 1),
        )
        for counts in cases:
            boards = _completion_count(0, *counts)
            for rank in rng.sample(range(boards), 50):
                with self.subTest(counts=counts, rank=rank):
                    board = _unrank_board(rank, counts)
                    self.assertEqual(_rank_board(board, counts), rank)

    def test_rank_rejects_every_unpromoted_man_on_a_promotion_row(self):
        for square in range(4):
            with self.subTest(player="black", square=square + 1):
                board = self._board({square: BLACK_MAN, 31: RED_KING})
                with self.assertRaisesRegex(ValueError, "material signature"):
                    _rank_board(board, (1, 0, 0, 1))
        for square in range(28, 32):
            with self.subTest(player="red", square=square + 1):
                board = self._board({0: BLACK_KING, square: RED_MAN})
                with self.assertRaisesRegex(ValueError, "material signature"):
                    _rank_board(board, (0, 1, 1, 0))

        black_boundary = self._board({4: BLACK_MAN, 31: RED_KING})
        red_boundary = self._board({0: BLACK_KING, 27: RED_MAN})
        self.assertLess(
            _rank_board(black_boundary, (1, 0, 0, 1)),
            _completion_count(0, 1, 0, 0, 1),
        )
        self.assertLess(
            _rank_board(red_boundary, (0, 1, 1, 0)),
            _completion_count(0, 0, 1, 1, 0),
        )


if __name__ == "__main__":
    unittest.main()
