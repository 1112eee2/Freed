import unittest
from pathlib import Path
import tempfile

from scratch.nnue_quiet_leaf_acquire import selection_binding_sha256
from scratch.nnue_scaling_preflight import (
    DEFAULT_WORK_DIR,
    path_hashes,
    partition_and_seal_manifest,
    subset_manifest,
)


def game(game_id, split, selected_count=1):
    row = {
        "game_id": game_id,
        "split": split,
        "path": f"{game_id}.json",
        "sha256": game_id.upper(),
        "provisional_positions": selected_count,
        "selected_positions": selected_count,
        "selected": [
            {
                "ply": index + 1,
                "canonical_position_id": f"{game_id}-position-{index}",
                "phase_band": "13_to_16",
                "piece_count": 16,
                "king_count": 0,
                "legal_move_count": 7,
            }
            for index in range(selected_count)
        ],
    }
    row["selection_sha256"] = selection_binding_sha256(row)
    return row


class NnueScalingPreflightTests(unittest.TestCase):
    def test_default_work_directory_is_a_dedicated_build_subdirectory(self):
        self.assertEqual(DEFAULT_WORK_DIR.name, "nnue_scaling_preflight_v1")
        self.assertEqual(DEFAULT_WORK_DIR.parent.name, "build")

    def test_path_hashes_checkpoint_each_artifact(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "b.json"
            second = root / "a.json"
            first.write_text("b", encoding="utf-8")
            second.write_text("a", encoding="utf-8")
            hashes = path_hashes(
                [first, second],
                checkpoint=calls.append,
            )
        self.assertEqual(list(hashes), ["a.json", "b.json"])
        self.assertEqual(
            calls,
            ["hash artifact a.json", "hash artifact b.json"],
        )

    def setUp(self):
        self.full = {
            "format": "thai-makhos-nnue-quiet-leaf-acquisition-v1",
            "kind": "selection-manifest",
            "split_rule": "locked",
            "split_before_sampling": True,
            "position_identity": "canonical",
            "generated_source_game_files": 3,
            "unique_source_game_trajectories": 3,
            "duplicate_source_game_files_dropped": 0,
            "duplicate_source_game_groups": [],
            "cross_split_symmetry_duplicates_dropped": 0,
            "within_split_duplicates_dropped": 0,
            "games": [
                game("train-game", "train", 2),
                game("validation-game", "validation", 1),
                game("test-game", "test", 3),
            ],
        }

    def test_subset_manifest_keeps_only_requested_games(self):
        development = subset_manifest(
            self.full,
            self.full["games"][:2],
            kind="development-selection-manifest",
        )
        self.assertEqual(
            [row["game_id"] for row in development["games"]],
            ["train-game", "validation-game"],
        )
        self.assertEqual(development["selected_by_split"], {"train": 2, "validation": 1})

    def test_partition_writes_hash_commitment_without_test_games_in_development(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commitment = partition_and_seal_manifest(
                self.full,
                development_path=root / "development.json",
                sealed_test_path=root / "sealed.json",
                commitment_path=root / "commitment.json",
            )
            development = __import__("json").loads(
                (root / "development.json").read_text(encoding="utf-8")
            )
            self.assertEqual(commitment["sealed_test_games"], 1)
            self.assertEqual(commitment["sealed_test_selected_positions"], 3)
            self.assertNotIn("test-game", {row["game_id"] for row in development["games"]})
            self.assertEqual(
                development["sealed_test_commitment"]["manifest_sha256"],
                commitment["sealed_test_manifest_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
