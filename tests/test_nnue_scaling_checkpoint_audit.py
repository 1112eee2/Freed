import unittest

from scratch.nnue_scaling_checkpoint_audit import (
    summarize_payloads,
    validate_analysis_payload,
)
from scratch.nnue_quiet_leaf_acquire import (
    EXPECTED_ACCEPTED_SHA256,
    FORMAT,
    TEACHER_MAX_DEPTH,
)


def analysis(*, split="train", eligible=True, gate_reason="accepted"):
    searches = [
        {
            "budget_ms": budget,
            "elapsed_ms": float(budget),
            "native_library_sha256": EXPECTED_ACCEPTED_SHA256,
        }
        for budget in (100, 500, 2000)
    ]
    return {
        "format": FORMAT,
        "kind": "game-analysis",
        "game_id": "game-a",
        "split": split,
        "selection_sha256": "BOUND",
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "threads": 1,
        "persistent_search": True,
        "budgets_ms": [100, 500, 2000],
        "teacher_max_depth": TEACHER_MAX_DEPTH,
        "positions": [
            {
                "split": split,
                "eligible": eligible,
                "gate_reason": gate_reason,
                "searches": searches,
                "phase_band": "9_to_12",
                "turn": "black",
                "king_count": 2,
                "exact_wdl": {"outcome": "draw"},
            }
        ],
    }


class NnueScalingCheckpointAuditTests(unittest.TestCase):
    def test_payload_validation_rejects_test_split(self):
        validate_analysis_payload(
            analysis(), expected_name="game-a.analysis.json"
        )
        with self.assertRaises(RuntimeError):
            validate_analysis_payload(
                analysis(split="test"), expected_name="game-a.analysis.json"
            )

    def test_summary_keeps_coverage_and_rejection_counts(self):
        accepted = analysis()
        rejected = analysis(eligible=False, gate_reason="last_two_score_delta")
        rejected["game_id"] = "game-b"
        summary = summarize_payloads([accepted, rejected])
        self.assertEqual(summary["games"], 2)
        self.assertEqual(summary["positions"], 2)
        self.assertEqual(summary["eligible"], 1)
        self.assertEqual(summary["with_kings"], 1)
        self.assertEqual(summary["phases"]["9_to_12"], 1)
        self.assertEqual(summary["turns"]["black"], 1)
        self.assertEqual(summary["rejections"]["last_two_score_delta"], 1)
        self.assertEqual(summary["teacher_elapsed_ms"], 5200.0)


if __name__ == "__main__":
    unittest.main()
