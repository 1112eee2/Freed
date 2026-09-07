import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from makhos.core import BLACK, RED, TerminalStatus
from scratch.nnue_quiet_leaf_acquire import (
    analysis_shard,
    build_selection_manifest,
    coverage_select_samples,
    deduplicate_source_game_rows,
    game_result_payload,
    game_split,
    generation_shard,
    label_gate,
    outcome_from_turn,
    phase_band,
    resolve_position_owners,
    selection_binding_sha256,
    validate_existing_game_payload,
    validate_selection_manifest,
)


class QuietLeafAcquisitionTests(unittest.TestCase):
    def test_game_split_is_stable_and_close_to_80_10_10(self):
        first = [game_split(f"game-{index:04d}") for index in range(1000)]
        second = [game_split(f"game-{index:04d}") for index in range(1000)]
        self.assertEqual(first, second)
        self.assertGreaterEqual(first.count("train"), 750)
        self.assertLessEqual(first.count("train"), 850)
        self.assertGreaterEqual(first.count("validation"), 70)
        self.assertLessEqual(first.count("validation"), 130)
        self.assertGreaterEqual(first.count("test"), 70)
        self.assertLessEqual(first.count("test"), 130)

    def test_analysis_shards_are_stable_disjoint_and_reasonably_even(self):
        first = [analysis_shard(f"game-{index:04d}", 4) for index in range(1000)]
        second = [analysis_shard(f"game-{index:04d}", 4) for index in range(1000)]
        self.assertEqual(first, second)
        self.assertTrue(all(0 <= shard < 4 for shard in first))
        for shard in range(4):
            self.assertGreaterEqual(first.count(shard), 200)
            self.assertLessEqual(first.count(shard), 300)

    def test_generation_shards_cover_each_schedule_exactly_once(self):
        assignments = [generation_shard(index, 6) for index in range(1, 97)]
        self.assertEqual(assignments, [generation_shard(index, 6) for index in range(1, 97)])
        self.assertTrue(all(assignments.count(shard) == 16 for shard in range(6)))
        with self.assertRaises(ValueError):
            generation_shard(0, 6)

    def test_selection_builder_honors_coordinator_checkpoints(self):
        calls = []
        replayed = SimpleNamespace(
            record=SimpleNamespace(game_id="checkpoint-game"),
            plies=[],
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "game.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch(
                    "scratch.nnue_quiet_leaf_acquire.load_game_record",
                    return_value=object(),
                ),
                patch(
                    "scratch.nnue_quiet_leaf_acquire.replay_game",
                    return_value=replayed,
                ),
            ):
                manifest, _selected = build_selection_manifest(
                    [path],
                    max_positions_per_game=3,
                    checkpoint=calls.append,
                )
        self.assertEqual(manifest["generated_source_game_files"], 1)
        self.assertEqual(len(manifest["games"]), 1)
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0].startswith("selection source replay"))

    def test_phase_bands_cover_only_the_locked_5_to_16_range(self):
        self.assertIsNone(phase_band(4))
        self.assertEqual(phase_band(5), "5_to_8")
        self.assertEqual(phase_band(8), "5_to_8")
        self.assertEqual(phase_band(9), "9_to_12")
        self.assertEqual(phase_band(12), "9_to_12")
        self.assertEqual(phase_band(13), "13_to_16")
        self.assertEqual(phase_band(16), "13_to_16")
        self.assertIsNone(phase_band(17))

    def test_truncation_never_becomes_a_draw_label(self):
        ongoing = TerminalStatus(False)
        payload = game_result_payload(ongoing, truncated=True)
        self.assertTrue(payload["truncated"])
        self.assertIsNone(payload["outcome"])
        draw = game_result_payload(
            TerminalStatus(True, None, "no_progress"),
            truncated=False,
        )
        self.assertFalse(draw["truncated"])
        self.assertEqual(draw["outcome"], "draw")

    def test_existing_source_game_provenance_rejects_stale_seed(self):
        schedule = {
            "seed": 123,
            "opening_plies": 4,
            "exploration_rate": 0.1,
        }
        tablebases = [{"piece_count": 4, "path": "tb4.bin"}]
        payload = {
            "format": "thai-makhos-game-v1",
            "moves": [
                {
                    "actor": "engine",
                    "engine": {"native_library_sha256": "ABC"},
                }
            ],
            "engine": {
                "game_mode": "accepted-selfplay-nnue-label-source",
                "corpus_role": "quiet-leaf-scalar-label-acquisition",
                "library_sha256": "ABC",
                "rules_profile": "project",
                "generation_depth": 7,
                "random_opening_plies": 4,
                "exploration_rate": 0.1,
                "seed": 123,
                "tablebases": tablebases,
            },
        }
        validate_existing_game_payload(
            payload,
            schedule=schedule,
            library_sha256="ABC",
            generation_depth=7,
            tablebase_bindings=tablebases,
        )
        stale = {**payload, "engine": {**payload["engine"], "seed": 124}}
        with self.assertRaises(RuntimeError):
            validate_existing_game_payload(
                stale,
                schedule=schedule,
                library_sha256="ABC",
                generation_depth=7,
                tablebase_bindings=tablebases,
            )

    def test_game_outcome_is_converted_to_side_to_move(self):
        self.assertEqual(outcome_from_turn("black", BLACK), "win")
        self.assertEqual(outcome_from_turn("black", RED), "loss")
        self.assertEqual(outcome_from_turn("draw", BLACK), "draw")
        self.assertIsNone(outcome_from_turn(None, RED))

    def test_label_gate_requires_complete_stable_non_mate_scores(self):
        stable = [
            {"depth": 10, "score": 30},
            {"depth": 12, "score": 75},
        ]
        self.assertEqual(label_gate(stable), (True, "accepted"))
        unstable = [
            {"depth": 10, "score": 30},
            {"depth": 12, "score": 81},
        ]
        self.assertEqual(
            label_gate(unstable),
            (False, "last_two_score_delta"),
        )
        incomplete = [{"depth": 0, "score": 1}, {"depth": 2, "score": 1}]
        self.assertEqual(label_gate(incomplete), (False, "incomplete_search"))
        mate = [{"depth": 4, "score": 0}, {"depth": 5, "score": 999999}]
        self.assertEqual(label_gate(mate), (False, "mate_like_score"))

    def test_cross_split_symmetry_identity_is_dropped(self):
        occurrences = {
            "same-position": [
                ("train", "game-a", {"item": SimpleNamespace(ply=7)}),
                ("test", "game-b", {"item": SimpleNamespace(ply=3)}),
            ],
            "inside-train": [
                ("train", "game-z", {"item": SimpleNamespace(ply=9)}),
                ("train", "game-a", {"item": SimpleNamespace(ply=11)}),
            ],
        }
        cross_split, owners, duplicate_count = resolve_position_owners(occurrences)
        self.assertEqual(cross_split, {"same-position"})
        self.assertEqual(owners["inside-train"], ("game-a", 11))
        self.assertEqual(duplicate_count, 1)

    def test_duplicate_source_trajectories_keep_one_deterministic_file(self):
        rows = [
            {"game_id": "same", "path": "z.json", "sha256": "Z"},
            {"game_id": "other", "path": "b.json", "sha256": "B"},
            {"game_id": "same", "path": "a.json", "sha256": "A"},
        ]
        unique, duplicates = deduplicate_source_game_rows(rows)
        self.assertEqual([row["game_id"] for row in unique], ["other", "same"])
        self.assertEqual(unique[1]["path"], "a.json")
        self.assertEqual(duplicates[0]["kept_path"], "a.json")
        self.assertEqual(duplicates[0]["dropped"], [{"path": "z.json", "sha256": "Z"}])

    def test_selection_binding_rejects_stale_or_duplicate_manifest(self):
        game = {
            "game_id": "game-a",
            "sha256": "ABC",
            "selected": [{"ply": 3, "canonical_position_id": "position-a"}],
        }
        game["selection_sha256"] = selection_binding_sha256(game)
        validate_selection_manifest({"games": [game]})
        stale = {**game, "selected": [{"ply": 4, "canonical_position_id": "position-b"}]}
        with self.assertRaises(RuntimeError):
            validate_selection_manifest({"games": [stale]})
        with self.assertRaises(RuntimeError):
            validate_selection_manifest({"games": [game, dict(game)]})

    def test_coverage_sampler_is_deterministic_and_meets_all_minima(self):
        phases = ("13_to_16", "9_to_12", "5_to_8")
        samples = []
        for index in range(60):
            samples.append(
                {
                    "sample_id": f"sample-{index:03d}",
                    "turn": "black" if index % 2 == 0 else "red",
                    "phase_band": phases[index % len(phases)],
                    "king_count": int(index < 30),
                    "split": "train",
                    "source": {"game_id": f"game-{index // 6}", "ply": index},
                }
            )
        first, details = coverage_select_samples(samples, 30)
        second, _details = coverage_select_samples(list(reversed(samples)), 30)
        self.assertEqual(
            [row["sample_id"] for row in first],
            [row["sample_id"] for row in second],
        )
        self.assertEqual(len(first), 30)
        self.assertGreaterEqual(sum(row["king_count"] > 0 for row in first), 9)
        for phase in phases:
            self.assertGreaterEqual(sum(row["phase_band"] == phase for row in first), 6)
        self.assertGreaterEqual(sum(row["turn"] == "black" for row in first), 14)
        self.assertGreaterEqual(sum(row["turn"] == "red" for row in first), 14)
        self.assertEqual(details["algorithm"], "deterministic-minimum-coverage-v1")


if __name__ == "__main__":
    unittest.main()
