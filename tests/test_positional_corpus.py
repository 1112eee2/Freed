import json
from pathlib import Path
import unittest

from makhos.core import legal_moves, parse_position


CORPUS = (
    Path(__file__).resolve().parent.parent
    / "corpora"
    / "positional_regressions.json"
)


class PositionalRegressionCorpusTests(unittest.TestCase):
    def test_positions_and_recorded_moves_are_legal(self) -> None:
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["format"],
            "thai-makhos-positional-regressions-v1",
        )
        self.assertTrue(payload["cases"])
        for case in payload["cases"]:
            state = parse_position(
                case["position"],
                reversible_plies=case["reversible_plies"],
            )
            legal = {move.notation for move in legal_moves(state)}
            self.assertIn(case["played_move"], legal)
            for horizon in ("short", "long"):
                evidence = case["evidence"][horizon]
                self.assertIn(evidence["best_move"], legal)
                self.assertEqual(set(evidence["root_scores"]), legal)
            evidence = case["evidence"]
            self.assertTrue(
                "fixed_depth_ladder" in evidence or "timed_ladder" in evidence
            )
            if "fixed_depth_ladder" in evidence:
                ladder = evidence["fixed_depth_ladder"]
                self.assertEqual(
                    [item["depth"] for item in ladder],
                    sorted(item["depth"] for item in ladder),
                )
            else:
                ladder = evidence["timed_ladder"]
                self.assertEqual(
                    [item["budget_ms"] for item in ladder],
                    sorted(item["budget_ms"] for item in ladder),
                )
            self.assertTrue(all(item["best_move"] in legal for item in ladder))


if __name__ == "__main__":
    unittest.main()
