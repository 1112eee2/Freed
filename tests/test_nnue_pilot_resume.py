import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scratch.nnue_pilot_resume import (
    finalizer_command,
    replace_with_retry,
    worker_command,
)


class NnuePilotResumeTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "accepted_library": "D:/engine/accepted.dll",
            "games": 768,
            "seed_start": 20265001,
            "generation_depth": 7,
            "max_game_plies": 200,
            "max_positions_per_game": 64,
            "hash_mb": 256,
            "budgets_ms": [100, 500, 2000],
            "tablebase_provenance": "D:/engine/TABLEBASE_PROVENANCE.json",
            "coverage_target": 8000,
            "tablebases": [
                {"path": "D:/engine/tb4.bin"},
                {"path": "D:/engine/tb5.bin"},
            ],
        }
        self.work_dir = Path("D:/engine/build/pilot")
        self.corpus = Path("D:/engine/corpora/pilot.jsonl")

    def test_worker_command_binds_every_locked_search_setting(self):
        command = worker_command(
            config=self.config,
            work_dir=self.work_dir,
            corpus=self.corpus,
            shard_count=4,
            shard_index=2,
        )
        self.assertEqual(command[0], sys.executable)
        joined = " ".join(command)
        for binding in (
            "--games 768",
            "--seed-start 20265001",
            "--generation-depth 7",
            "--max-game-plies 200",
            "--max-positions-per-game 64",
            "--hash-mb 256",
            "--budgets-ms 100,500,2000",
            "--coverage-target 8000",
            "--analysis-shard-count 4",
            "--analysis-shard-index 2",
        ):
            self.assertIn(binding, joined)
        self.assertEqual(command.count("--tablebase"), 2)

    def test_finalizer_command_binds_exact_worker_set(self):
        command = finalizer_command(
            config=self.config,
            work_dir=self.work_dir,
            corpus=self.corpus,
            worker_pids=[101, 202, 303, 404],
            poll_seconds=30,
            stall_minutes=30,
        )
        joined = " ".join(command)
        self.assertIn("--worker-pids 101,202,303,404", joined)
        self.assertIn("--games 768", joined)
        self.assertIn("--coverage-target 8000", joined)
        self.assertIn("--poll-seconds 30", joined)
        self.assertIn("--stall-minutes 30", joined)

    def test_status_replace_retries_transient_windows_reader_race(self):
        temporary = Path("status.json.tmp")
        destination = Path("status.json")
        with (
            patch.object(
                Path,
                "replace",
                side_effect=[PermissionError("reader holds destination"), None],
            ) as replace,
            patch("scratch.nnue_pilot_resume.time.sleep") as sleep,
        ):
            replace_with_retry(
                temporary,
                destination,
                attempts=3,
                delay_seconds=0.01,
            )
        self.assertEqual(replace.call_count, 2)
        sleep.assert_called_once_with(0.01)

    def test_status_replace_fails_closed_after_retry_budget(self):
        with (
            patch.object(Path, "replace", side_effect=PermissionError("busy")),
            patch("scratch.nnue_pilot_resume.time.sleep") as sleep,
        ):
            with self.assertRaises(PermissionError):
                replace_with_retry(
                    Path("status.json.tmp"),
                    Path("status.json"),
                    attempts=2,
                    delay_seconds=0.01,
                )
        sleep.assert_called_once_with(0.01)


if __name__ == "__main__":
    unittest.main()
