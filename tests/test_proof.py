import unittest
import tempfile
from pathlib import Path

from makhos.audit_rules import IndependentRulesAuditor
from makhos.core import BLACK, Rules, apply_move, legal_moves, parse_position
from makhos.exact import Outcome
from makhos.native_tablebase import NativeProbe
from makhos.proof import (
    CertificateChecker,
    EndgameOracle,
    MappedProofStrategy,
    NonLossProver,
    ProofStrategy,
    _STRATEGY_ENTRY,
    _STRATEGY_HEADER,
    _dfpn_tablebase_binding,
    _king_flags,
    _state_bitboards,
    _strategy_hash,
)


class ProofTests(unittest.TestCase):
    def test_memory_mapped_native_strategy_checks_closure(self):
        root = parse_position("B:BM29,30,31,32:BK18:RM11,22")
        move = next(
            move for move in legal_moves(root)
            if move.notation == "18x8x25"
        )
        child = apply_move(root, move, validate=False)
        capacity = 1 << 16
        payload = bytearray(capacity * _STRATEGY_ENTRY.size)
        for state in (root, child):
            red, black, kings = _state_bitboards(state)
            flags = _king_flags(red, black, kings)
            meta = 1 + state.reversible_plies + (
                127 if state.turn == BLACK else 0
            )
            slot = _strategy_hash(
                red, black, kings, state.turn, state.reversible_plies
            ) & (capacity - 1)
            while payload[slot * _STRATEGY_ENTRY.size + 10] != 0:
                slot = (slot + 1) & (capacity - 1)
            _STRATEGY_ENTRY.pack_into(
                payload,
                slot * _STRATEGY_ENTRY.size,
                red,
                black,
                flags,
                meta,
                0,
            )
        checksum = 1_469_598_103_934_665_603
        for byte in payload:
            checksum ^= byte
            checksum = (checksum * 1_099_511_628_211) & ((1 << 64) - 1)
        root_red, root_black, root_kings = _state_bitboards(root)
        binding = _dfpn_tablebase_binding({4: 1, 5: 2, 6: 3})
        header = _STRATEGY_HEADER.pack(
            b"MKSTRAT1", 1, _STRATEGY_HEADER.size, 1, BLACK, 16, 0,
            capacity, 2, binding, 1, 2, 3, checksum,
            root_red, root_black, root_kings, root.turn, 0,
        )

        class Tablebase:
            no_progress_plies = 1

            def __init__(self, piece_count, checksum):
                self.piece_count = piece_count
                self.expected_checksum = checksum

            @staticmethod
            def probe(_state):
                raise AssertionError("fixture reaches a terminal child")

        oracle = EndgameOracle(ranked_tablebases=(
            Tablebase(4, 1), Tablebase(5, 2), Tablebase(6, 3),
        ))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "strategy.bin"
            path.write_bytes(header + payload)
            strategy = MappedProofStrategy(
                path,
                oracle,
                rules_auditor=IndependentRulesAuditor(),
            )
            self.assertEqual(strategy.checked_nodes, 2)
            self.assertEqual(strategy.move_for(root), move)
            strategy.close()

            bad_header = _STRATEGY_HEADER.pack(
                b"MKSTRAT1", 1, _STRATEGY_HEADER.size, 1, BLACK, 16, 0,
                capacity, 2, binding ^ 1, 1, 2, 3, checksum,
                root_red, root_black, root_kings, root.turn, 0,
            )
            path.write_bytes(bad_header + payload)
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                MappedProofStrategy(path, oracle)

            path.write_bytes(header + payload)
            with path.open("r+b") as file:
                file.seek(-1, 2)
                file.write(b"\x01")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                MappedProofStrategy(path, oracle)

    def test_mapped_tablebase_leaf_continues_outside_stored_frontier(self):
        root = parse_position("B:BK1:RK32")
        capacity = 1 << 16
        payload = bytearray(capacity * _STRATEGY_ENTRY.size)
        red, black, kings = _state_bitboards(root)
        flags = _king_flags(red, black, kings)
        meta = 1 + root.reversible_plies + (127 if root.turn == BLACK else 0)
        slot = _strategy_hash(red, black, kings, root.turn, root.reversible_plies)
        slot &= capacity - 1
        _STRATEGY_ENTRY.pack_into(
            payload,
            slot * _STRATEGY_ENTRY.size,
            red,
            black,
            flags,
            meta,
            0,
        )
        checksum = 1_469_598_103_934_665_603
        for byte in payload:
            checksum ^= byte
            checksum = (checksum * 1_099_511_628_211) & ((1 << 64) - 1)
        binding = _dfpn_tablebase_binding({4: 1, 5: 2, 6: 3})
        header = _STRATEGY_HEADER.pack(
            b"MKSTRAT1", 1, _STRATEGY_HEADER.size, 80, BLACK, 16, 0,
            capacity, 1, binding, 1, 2, 3, checksum,
            red, black, kings, root.turn, root.reversible_plies,
        )

        class DrawNative:
            max_pieces = 3
            no_progress_plies = 80

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        class Tablebase:
            no_progress_plies = 80

            def __init__(self, piece_count, expected_checksum):
                self.piece_count = piece_count
                self.expected_checksum = expected_checksum

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        oracle = EndgameOracle(
            native=DrawNative(),
            ranked_tablebases=tuple(Tablebase(count, count - 3) for count in (4, 5, 6)),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "strategy.bin"
            path.write_bytes(header + payload)
            strategy = MappedProofStrategy(path, oracle)
            first = strategy.moves_for(root)[0]
            opponent_state = apply_move(root, first, validate=False)
            reply = legal_moves(opponent_state)[0]
            continuation = apply_move(opponent_state, reply, validate=False)
            self.assertTrue(strategy.moves_for(continuation))
            strategy.close()

    def test_json_strategy_rejects_native_draw_horizon_mismatch(self):
        class DrawNative:
            max_pieces = 3

            def __init__(self, no_progress_plies):
                self.no_progress_plies = no_progress_plies

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        root = parse_position("B:BK1:RK32")
        rules = Rules(repetition_limit=None, no_progress_plies=80)
        matching = EndgameOracle(native=DrawNative(80))
        certificate, _ = NonLossProver(rules, matching, node_budget=10).prove(
            root, BLACK
        )
        with self.assertRaisesRegex(ValueError, "no-progress mismatch"):
            ProofStrategy(certificate, EndgameOracle(native=DrawNative(1)))

    def test_certificate_binds_five_piece_tablebase(self):
        class DrawFiveTablebase:
            piece_count = 5
            no_progress_plies = 80
            expected_checksum = 0x123456789ABCDEF0
            checksum_verified = False

            def verify_checksum(self):
                self.checksum_verified = True

            @staticmethod
            def probe(_state):
                return NativeProbe(Outcome.DRAW, None)

        state = parse_position("B:BM25,26,27:RM1,2")
        rules = Rules(repetition_limit=None, no_progress_plies=80)
        oracle = EndgameOracle(ranked_tablebases=(DrawFiveTablebase(),))
        certificate, stats = NonLossProver(
            rules, oracle, node_budget=10
        ).prove(state, BLACK)
        self.assertEqual(
            certificate["ranked_tablebase_checksums"],
            {"5": "123456789abcdef0"},
        )
        self.assertEqual(CertificateChecker(oracle).check(certificate), 1)
        self.assertTrue(oracle.ranked_tablebases[5].checksum_verified)
        self.assertEqual(stats.certificate_nodes, 1)

    def test_terminal_capture_certificate_checks_independently(self):
        state = parse_position("B:BM29,30:BK18:RM11,22")
        rules = Rules(repetition_limit=None, no_progress_plies=80)
        oracle = EndgameOracle()
        certificate, stats = NonLossProver(
            rules, oracle, node_budget=100
        ).prove(state, BLACK)
        self.assertIsNotNone(certificate)
        self.assertGreaterEqual(stats.certificate_nodes, 2)
        checked = CertificateChecker(oracle).check(certificate)
        self.assertEqual(checked, stats.certificate_nodes)

    def test_checker_rejects_missing_opponent_reply(self):
        state = parse_position("R:BM29,30:BK18:RM11,22")
        rules = Rules(repetition_limit=None, no_progress_plies=1)
        oracle = EndgameOracle()
        certificate, _ = NonLossProver(
            rules, oracle, node_budget=10_000
        ).prove(state, BLACK)
        if certificate is None:
            self.skipTest("fixture is not a non-loss for black")
        all_node = next(
            node for node in certificate["nodes"].values()
            if node["kind"] == "all" and len(node["edges"]) > 1
        )
        all_node["edges"].pop()
        with self.assertRaisesRegex(ValueError, "every legal move"):
            CertificateChecker(oracle).check(certificate)


if __name__ == "__main__":
    unittest.main()
