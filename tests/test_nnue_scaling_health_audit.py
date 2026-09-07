from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scratch.nnue_scaling_health_audit as health


def process(entrypoint: str, pid: int) -> dict:
    return {
        "pid": pid,
        "command": ["python.exe", f"D:\\repo\\scratch\\{entrypoint}"],
    }


def healthy_processes() -> list[dict]:
    rows = [process("nnue_scaling_full_run.py", 1)]
    rows.append(process("nnue_scaling_preflight.py", 2))
    rows.extend(
        process("nnue_quiet_leaf_acquire.py", 10 + index)
        for index in range(6)
    )
    return rows


class NnueScalingHealthAuditTests(unittest.TestCase):
    def make_work_dir(self, root: Path) -> Path:
        for name in ("games", "analyses", "worker_logs", "supervisor_logs"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def test_running_inventory_is_healthy_and_sharded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work_dir = self.make_work_dir(Path(temporary))
            games = [
                {"game_id": "0000000000000001"},
                {"game_id": "0000000000000002"},
                {"game_id": "0000000000000003"},
            ]
            for index in range(3):
                (work_dir / "games" / f"game_{index}.json").touch()
            for game in games[:2]:
                (work_dir / "analyses" / f"{game['game_id']}.analysis.json").touch()

            inventory = health.collect_inventory(
                work_dir,
                games,
                healthy_processes(),
                expected_source_files=3,
                shard_count=2,
            )

            self.assertEqual(inventory["state"], "RUNNING_HEALTHY")
            self.assertEqual(inventory["development_analyses"], 2)
            self.assertEqual(inventory["missing_development_analyses"], 1)
            self.assertEqual(
                sum(row["completed"] for row in inventory["analysis_shards"]),
                2,
            )
            self.assertFalse(inventory["safe_to_resume_locked_supervisor"])

    def test_clean_stopped_inventory_is_safe_to_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work_dir = self.make_work_dir(Path(temporary))
            (work_dir / "games" / "game.json").touch()
            inventory = health.collect_inventory(
                work_dir,
                [{"game_id": "0000000000000001"}],
                [],
                expected_source_files=1,
                shard_count=1,
            )
            self.assertEqual(inventory["state"], "PAUSED_OR_STOPPED_CLEAN")
            self.assertTrue(inventory["safe_to_resume_locked_supervisor"])

    def test_extra_analysis_and_stderr_are_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work_dir = self.make_work_dir(Path(temporary))
            (work_dir / "games" / "game.json").touch()
            (work_dir / "analyses" / "unexpected.analysis.json").touch()
            (work_dir / "worker_logs" / "worker.stderr.log").write_text("x")
            inventory = health.collect_inventory(
                work_dir,
                [{"game_id": "0000000000000001"}],
                healthy_processes(),
                expected_source_files=1,
                shard_count=1,
            )
            self.assertEqual(inventory["state"], "UNHEALTHY")
            self.assertEqual(inventory["stderr_bytes"], 1)
            self.assertEqual(
                inventory["extra_analysis_files"],
                ["unexpected.analysis.json"],
            )

    def test_duplicate_supervisor_is_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work_dir = self.make_work_dir(Path(temporary))
            (work_dir / "games" / "game.json").touch()
            processes = healthy_processes()
            processes.append(process("nnue_scaling_full_run.py", 99))
            inventory = health.collect_inventory(
                work_dir,
                [{"game_id": "0000000000000001"}],
                processes,
                expected_source_files=1,
                shard_count=1,
            )
            self.assertEqual(inventory["state"], "UNHEALTHY")
            self.assertTrue(
                any("duplicate" in error for error in inventory["errors"])
            )

    def test_build_snapshot_never_opens_forbidden_live_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work_dir = self.make_work_dir(Path(temporary))
            game_id = "0000000000000001"
            (work_dir / "games" / "game.json").touch()
            (work_dir / "analyses" / f"{game_id}.analysis.json").touch()
            (work_dir / "sealed_test_selection_manifest.json").touch()
            (work_dir / "full_run_supervisor_status.json").touch()
            returned = (
                {},
                {
                    "sealed_test_manifest_sha256": (
                        health.EXPECTED_SEALED_TEST_MANIFEST_SHA256
                    ),
                    "sealed_test_games": health.EXPECTED_SEALED_TEST_GAMES,
                    "sealed_test_selected_positions": (
                        health.EXPECTED_SEALED_TEST_SELECTED_POSITIONS
                    ),
                },
                {"contract": {"games": 1, "shard_count": 1}},
                {},
                {"games": [{"game_id": game_id}]},
            )
            original_open = Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if (
                    path.name
                    in {
                        "sealed_test_selection_manifest.json",
                        "full_run_supervisor_status.json",
                    }
                    or path.name.endswith(".analysis.json")
                ):
                    raise AssertionError(f"forbidden read: {path}")
                return original_open(path, *args, **kwargs)

            with (
                patch.object(health, "verify_locked_sources", return_value=returned),
                patch.object(Path, "open", guarded_open),
            ):
                snapshot = health.build_health_snapshot(work_dir, processes=[])

            self.assertFalse(
                snapshot["isolation"]["volatile_supervisor_status_read"]
            )
            self.assertFalse(snapshot["isolation"]["sealed_test_manifest_read"])
            self.assertEqual(snapshot["isolation"]["analysis_payloads_read"], 0)
            self.assertFalse(snapshot["training_authorized"])


if __name__ == "__main__":
    unittest.main()
