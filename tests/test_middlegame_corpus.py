import json
from pathlib import Path
import tempfile
import unittest

from makhos.cli import build_parser
from makhos.middlegame_corpus import (
    MIDDLEGAME_CORPUS_FORMAT,
    MiddlegameCorpusError,
    build_middlegame_corpus,
)


def analysis_payload(*, second_move: str = "25-21") -> dict:
    return {
        "format": "thai-makhos-analysis-v1",
        "game_id": "game-1",
        "source_game": "game.json",
        "library": "engine.dll",
        "library_sha256": "a" * 64,
        "threads": 12,
        "hash_mb": 128,
        "depth_limit": 64,
        "rules_profile": "external-no-repetition",
        "budgets_ms": [100, 200],
        "positions": [
            {
                "ply": 1,
                "player": "black",
                "position": "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8",
                "reversible_plies": 0,
                "legal_moves": 7,
                "played_move": "25-21",
                "classification": "stable",
                "root_static": {"relative_terms": {"material": 0}},
                "candidate_child_static": {
                    "25-21": {"relative_terms": {"material": 0}},
                    "26-22": {"relative_terms": {"material": 1}},
                },
                "searches": [
                    {
                        "budget_ms": 100,
                        "move": "25-21",
                        "score": 4,
                        "depth": 8,
                        "nodes": 1000,
                        "elapsed_ms": 100,
                    },
                    {
                        "budget_ms": 200,
                        "move": second_move,
                        "score": 5,
                        "depth": 9,
                        "nodes": 2000,
                        "elapsed_ms": 200,
                    },
                ],
            }
        ],
    }


class MiddlegameCorpusTests(unittest.TestCase):
    def test_builds_metadata_and_search_stability_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = root / "analysis.json"
            output = root / "corpus.jsonl"
            analysis.write_text(json.dumps(analysis_payload()), encoding="utf-8")
            metadata = build_middlegame_corpus([analysis], output)

            self.assertEqual(metadata["format"], MIDDLEGAME_CORPUS_FORMAT)
            self.assertEqual(metadata["sample_count"], 1)
            lines = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(lines[0]["kind"], "metadata")
            sample = lines[1]
            self.assertEqual(sample["label"]["stable_move"], "25-21")
            self.assertTrue(sample["label"]["usable_for_supervised_training"])
            self.assertEqual(sample["piece_count"], 16)

    def test_rejects_illegal_search_move(self) -> None:
        payload = analysis_payload(second_move="25-20")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = root / "analysis.json"
            analysis.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(MiddlegameCorpusError):
                build_middlegame_corpus([analysis], root / "corpus.jsonl")

    def test_duplicate_position_with_conflicting_labels_is_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left.json"
            right = root / "right.json"
            left.write_text(json.dumps(analysis_payload()), encoding="utf-8")
            right.write_text(
                json.dumps(analysis_payload(second_move="26-22")),
                encoding="utf-8",
            )
            metadata = build_middlegame_corpus(
                [left, right], root / "corpus.jsonl"
            )
            self.assertEqual(metadata["sample_count"], 1)
            self.assertEqual(metadata["conflict_sample_count"], 1)
            sample = json.loads((root / "corpus.jsonl").read_text().splitlines()[1])
            self.assertEqual(
                sample["label"]["classification"],
                "conflicting-search-labels",
            )
            self.assertIsNone(sample["label"]["stable_move"])

    def test_cli_exposes_corpus_builder(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "build-middlegame-corpus",
                "--analysis",
                "analysis.json",
                "--stable-only",
            ]
        )
        self.assertEqual(args.analysis, ["analysis.json"])
        self.assertTrue(args.stable_only)


if __name__ == "__main__":
    unittest.main()
