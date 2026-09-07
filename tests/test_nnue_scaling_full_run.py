import argparse
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scratch.nnue_scaling_full_run import (
    ANALYSIS_TIMEOUT_MINUTES,
    BUDGETS_MS,
    FULL_AFFINITIES,
    FULL_GAMES,
    FULL_SEED_END,
    FULL_SEED_START,
    FULL_SHARDS,
    GENERATION_DEPTH,
    GENERATION_TIMEOUT_MINUTES,
    HASH_MB,
    MAX_GAME_PLIES,
    MAX_POSITIONS_PER_GAME,
    classify_coordinator_exit,
    coordinator_command,
    live_full_run_processes,
    progress_counts,
    validate_locked_contract,
)


def args(root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        work_dir=root / "work",
        corpus=root / "unused.jsonl",
        accepted_library=root / "accepted.dll",
        games=FULL_GAMES,
        seed_start=FULL_SEED_START,
        generation_depth=GENERATION_DEPTH,
        max_game_plies=MAX_GAME_PLIES,
        max_positions_per_game=MAX_POSITIONS_PER_GAME,
        hash_mb=HASH_MB,
        budgets_ms=BUDGETS_MS,
        shard_count=FULL_SHARDS,
        affinities=",".join(str(value) for value in FULL_AFFINITIES),
        generation_timeout_minutes=GENERATION_TIMEOUT_MINUTES,
        analysis_timeout_minutes=ANALYSIS_TIMEOUT_MINUTES,
    )


class NnueScalingFullRunTests(unittest.TestCase):
    def test_contract_is_exact_and_seed_range_is_fresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            contract = validate_locked_contract(args(Path(temporary)))
        self.assertEqual(contract["games"], 15_360)
        self.assertEqual(contract["seed_start"], FULL_SEED_START)
        self.assertEqual(contract["seed_end"], FULL_SEED_END)

    def test_contract_rejects_even_one_game_of_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            changed = args(Path(temporary))
            changed.games -= 1
            with self.assertRaises(RuntimeError):
                validate_locked_contract(changed)

    def test_coordinator_command_carries_the_locked_scale_and_timeouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            command = coordinator_command(args(Path(temporary)))
        joined = " ".join(command)
        self.assertIn("--games 15360", joined)
        self.assertIn("--seed-start 20280001", joined)
        self.assertIn("--analysis-timeout-minutes 5760", joined)
        self.assertNotIn("--skip-resume-reproduction", joined)

    def test_progress_counts_only_source_and_analysis_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "games").mkdir()
            (root / "analyses").mkdir()
            (root / "games" / "one.json").write_text("{}", encoding="utf-8")
            (root / "games" / "ignore.tmp").write_text("", encoding="utf-8")
            (root / "analyses" / "one.analysis.json").write_text(
                "{}", encoding="utf-8"
            )
            self.assertEqual(
                progress_counts(root),
                {"source_files": 1, "development_analyses": 1},
            )

    def test_live_process_scan_ignores_parent_shell_command_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            work_dir = Path(temporary) / "work"
            parent = SimpleNamespace(
                pid=2,
                info={
                    "cmdline": [
                        "pwsh.exe",
                        "-Command",
                        "try { setup } catch {}\n"
                        "python -B scratch/nnue_scaling_full_run.py",
                    ],
                    "create_time": 1.0,
                },
            )
            real = SimpleNamespace(
                pid=3,
                info={
                    "cmdline": [
                        "python.exe",
                        "D:/ThaiMakhosEngine/scratch/nnue_scaling_full_run.py",
                    ],
                    "create_time": 2.0,
                },
            )
            with (
                patch("scratch.nnue_scaling_full_run.os.getpid", return_value=1),
                patch(
                    "scratch.nnue_scaling_full_run.psutil.process_iter",
                    return_value=[parent, real],
                ),
            ):
                rows = live_full_run_processes(work_dir)
        self.assertEqual([row["pid"] for row in rows], [3])

    def test_exit_classification_fails_closed(self):
        self.assertEqual(classify_coordinator_exit(0, {"state": "PASS"}, 0), "PASS")
        self.assertEqual(
            classify_coordinator_exit(
                0, {"state": "PAUSED_FOR_INTERACTIVE_PLAY"}, 0
            ),
            "PAUSED_FOR_INTERACTIVE_PLAY",
        )
        self.assertEqual(
            classify_coordinator_exit(0, {"state": "starting"}, 0), "FAILED"
        )
        self.assertEqual(
            classify_coordinator_exit(1, {"state": "PASS"}, 0), "FAILED"
        )
        self.assertEqual(
            classify_coordinator_exit(0, {"state": "PASS"}, 1), "FAILED"
        )


if __name__ == "__main__":
    unittest.main()
