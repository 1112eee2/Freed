import unittest

from scratch.quiet_leaf_hce_gap_audit import (
    pair_metrics,
    percentile,
    summarize_rows,
)


class QuietLeafHceGapAuditTests(unittest.TestCase):
    def test_percentile_interpolates_and_checks_input(self) -> None:
        self.assertEqual(percentile([0, 10], 0.5), 5.0)
        self.assertEqual(percentile([3], 0.9), 3.0)
        with self.assertRaises(ValueError):
            percentile([], 0.5)
        with self.assertRaises(ValueError):
            percentile([1], 1.1)

    def test_pair_metrics_reports_exact_agreement(self) -> None:
        rows = [
            {"hce_score": -10, "teacher_score": -10},
            {"hce_score": 20, "teacher_score": 20},
        ]
        metrics = pair_metrics(rows, "teacher_score")
        self.assertEqual(metrics["positions"], 2)
        self.assertEqual(metrics["mae"], 0.0)
        self.assertEqual(metrics["rmse"], 0.0)
        self.assertEqual(metrics["pearson"], 1.0)
        self.assertEqual(metrics["sign_agreement_percent"], 100.0)

    def test_summary_keeps_phase_king_turn_and_budget_groups(self) -> None:
        rows = [
            {
                "phase_band": "13_to_16",
                "king_count": 0,
                "turn": "black",
                "hce_score": 0,
                "teacher_score": 10,
                "score_100ms": 4,
                "score_500ms": 8,
                "score_2000ms": 10,
            },
            {
                "phase_band": "5_to_8",
                "king_count": 1,
                "turn": "red",
                "hce_score": -10,
                "teacher_score": -20,
                "score_100ms": -12,
                "score_500ms": -18,
                "score_2000ms": -20,
            },
        ]
        summary = summarize_rows(rows, (100, 500, 2000))
        self.assertEqual(summary["all"]["teacher"]["positions"], 2)
        self.assertEqual(summary["with_kings"]["teacher"]["positions"], 1)
        self.assertEqual(summary["without_kings"]["teacher"]["positions"], 1)
        self.assertEqual(summary["13_to_16"]["teacher"]["positions"], 1)
        self.assertEqual(summary["5_to_8"]["teacher"]["positions"], 1)
        self.assertEqual(summary["turn_black"]["teacher"]["positions"], 1)
        self.assertEqual(
            summary["all"]["search_ladder_delta"]["100_to_500ms"][
                "mean_absolute_delta"
            ],
            5.0,
        )


if __name__ == "__main__":
    unittest.main()
