from collections import Counter
import unittest
from unittest.mock import patch
from tools.verification import prepare_nnue_thread_audit as prep
from makhos.core import parse_position, terminal_status, BLACK_KING, RED_KING


class ThreadAuditPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("makhos.native.NativeSearch.__init__", side_effect=AssertionError("Native work forbidden")):
            cls.payload = prep.prepare()

    def test_no_execution_or_strength_authority(self):
        self.assertFalse(self.payload["native_search_authorized"])
        self.assertFalse(self.payload["strength_evidence"])
        self.assertIn("both Gate C controls PASS", self.payload["requires"])

    def test_cases_legal_diverse_and_unlabelled(self):
        cases = self.payload["cases"]
        self.assertEqual(len(cases), 96)
        self.assertEqual(len({(c["position"], c["reversible_plies"]) for c in cases}), 96)
        self.assertEqual(len({c["turn"] for c in cases}), 2)
        self.assertGreater(sum(c["multi_capture"] for c in cases), 0)
        for case in cases:
            state = parse_position(case["position"], reversible_plies=case["reversible_plies"])
            history = {parse_position(h["position"]).position_key: h["count"] for h in case["history"]}
            self.assertFalse(terminal_status(state, repetition_count=history[state.position_key]).terminal)
            self.assertEqual(case["kings"], sum(p in (BLACK_KING, RED_KING) for p in state.board))
            self.assertIsNone(case["expected_best_move"])

    def test_exact_complete_schedule_with_fixed_total_hash(self):
        rows = self.payload["schedule"]
        self.assertEqual(len(rows), 96 * 6 * 2 * 5)
        self.assertEqual(len({(r["case"], r["repetition"], r["budget_ms"], r["threads"]) for r in rows}), len(rows))
        self.assertEqual({r["threads"] for r in rows}, {1, 2, 4, 6, 8, 12})
        self.assertEqual({r["hash_mb_total"] for r in rows}, {512})
        counts = Counter((r["threads"], r["budget_ms"]) for r in rows)
        self.assertEqual(set(counts.values()), {96 * 5})

    def test_balanced_first_thread_order(self):
        first = self.payload["schedule"][::6]
        counts = Counter((r["threads"], r["budget_ms"]) for r in first)
        self.assertEqual(set(counts.values()), {80})

    def test_repeated_preparation_is_identical(self):
        with patch("makhos.native.NativeSearch.__init__", side_effect=AssertionError("Native work forbidden")):
            other = prep.prepare()
        self.assertEqual(prep.digest(self.payload), prep.digest(other))


if __name__ == "__main__":
    unittest.main(verbosity=2)
