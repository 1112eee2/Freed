import random
import unittest

from makhos.audit_rules import IndependentRulesAuditor
from makhos.core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    Rules,
    State,
    apply_move,
    index_to_coord,
    legal_moves,
    parse_position,
)
from makhos.proof import CertificateChecker, EndgameOracle, NonLossProver


def _reference_edges(state: State):
    return tuple(sorted(
        (
            move.notation,
            move.path,
            move.captures,
            move.promotes,
            apply_move(state, move, validate=False),
        )
        for move in legal_moves(state)
    ))


def _audited_edges(state: State, auditor: IndependentRulesAuditor):
    return tuple(sorted(
        (
            move.notation,
            move.path,
            move.captures,
            move.promotes,
            move.child,
        )
        for move in auditor.legal_moves(state)
    ))


class IndependentRulesAuditTests(unittest.TestCase):
    def test_random_positions_match_reference_edges_and_child_states(self):
        auditor = IndependentRulesAuditor()
        rng = random.Random(0x41554449544D4F56)
        pieces = (RED_MAN, BLACK_MAN, RED_KING, BLACK_KING)
        compared_moves = 0
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
            if not any(piece in (RED_MAN, RED_KING) for piece in board):
                board[0] = RED_MAN
            if not any(piece in (BLACK_MAN, BLACK_KING) for piece in board):
                board[31] = BLACK_MAN
            state = State(
                tuple(board),
                rng.choice((RED, BLACK)),
                reversible_plies=rng.randrange(80),
                ply=rng.randrange(200),
            )
            expected = _reference_edges(state)
            self.assertEqual(_audited_edges(state, auditor), expected)
            compared_moves += len(expected)
        self.assertGreater(compared_moves, 1_000)

    def test_terminal_precedence_matches_proof_rules(self):
        auditor = IndependentRulesAuditor()
        blocked = parse_position(
            "B:BM5:RM1",
            reversible_plies=80,
        )
        status = auditor.terminal_status(blocked, no_progress_plies=80)
        self.assertTrue(status.is_draw)
        self.assertEqual(status.reason, "no_progress")

    def test_certificate_checker_can_require_independent_edges(self):
        state = parse_position("B:BM29,30:BK18:RM11,22")
        rules = Rules(repetition_limit=None, no_progress_plies=80)
        oracle = EndgameOracle()
        certificate, stats = NonLossProver(
            rules,
            oracle,
            node_budget=100,
        ).prove(state, BLACK)
        self.assertIsNotNone(certificate)
        self.assertEqual(
            CertificateChecker(
                oracle,
                rules_auditor=IndependentRulesAuditor(),
            ).check(certificate),
            stats.certificate_nodes,
        )

        class BrokenAuditor:
            @staticmethod
            def legal_moves(_state):
                return ()

        with self.assertRaisesRegex(ValueError, "independent rules audit mismatch"):
            CertificateChecker(
                oracle,
                rules_auditor=BrokenAuditor(),
            ).check(certificate)


if __name__ == "__main__":
    unittest.main()
