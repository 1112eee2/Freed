import json
import tempfile
from pathlib import Path
import unittest

from makhos.cli import build_parser
from makhos.core import BLACK, parse_position
from makhos.eval_corpus import (
    EVAL_CORPUS_FORMAT,
    canonical_position_id,
    corpus_split,
    load_exact_wdl_corpus,
    rotate_swap_state,
)


class EvaluationCorpusTests(unittest.TestCase):
    def test_color_rotation_has_one_id_and_split(self) -> None:
        state = parse_position("B:BM19,25,27:BK31:RM1,6:RK10")
        rotated = rotate_swap_state(state)
        self.assertEqual(canonical_position_id(state), canonical_position_id(rotated))
        self.assertEqual(
            corpus_split(canonical_position_id(state)),
            corpus_split(canonical_position_id(rotated)),
        )
        self.assertEqual(rotate_swap_state(rotated), state)

    def test_loader_checks_metadata_sample_count(self) -> None:
        metadata = {
            "kind": "metadata",
            "format": EVAL_CORPUS_FORMAT,
            "version": 1,
            "sample_count": 1,
        }
        sample = {"kind": "sample", "id": "a"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text(
                json.dumps(metadata) + "\n" + json.dumps(sample) + "\n",
                encoding="utf-8",
            )
            loaded_metadata, samples = load_exact_wdl_corpus(path)
            self.assertEqual(loaded_metadata["format"], EVAL_CORPUS_FORMAT)
            self.assertEqual(samples, (sample,))

    def test_cli_exposes_reproducible_corpus_controls(self) -> None:
        args = build_parser().parse_args([
            "build-eval-corpus",
            "--samples-per-outcome",
            "50",
            "--seed",
            "123",
            "--validation-percent",
            "25",
            "--skip-checksum",
        ])
        self.assertEqual(args.samples_per_outcome, 50)
        self.assertEqual(args.seed, 123)
        self.assertEqual(args.validation_percent, 25)
        self.assertTrue(args.skip_checksum)


if __name__ == "__main__":
    unittest.main()
