import ast
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.verification import full_suite_attestation as runner
from scratch import nnue_full_suite_attestation as legacy_runner
from scratch import nnue_trainer_contract_gate as contract_gate


class FakeLock:
    def __init__(self, *, locks: bool = True) -> None:
        self.locks = locks
        self.try_calls = []
        self.closed = False

    def try_lock(self, start: int, length: int) -> bool:
        self.try_calls.append((start, length))
        return self.locks

    def close(self) -> None:
        self.closed = True


def passing_suite() -> unittest.TestSuite:
    class PassingCase(unittest.TestCase):
        def test_passes(self):
            self.assertEqual(2 + 2, 4)

    return unittest.TestSuite([PassingCase("test_passes")])


def failing_suite() -> unittest.TestSuite:
    class FailingCase(unittest.TestCase):
        def test_fails(self):
            self.fail("synthetic failure")

    return unittest.TestSuite([FailingCase("test_fails")])


class FullSuiteAttestationTests(unittest.TestCase):
    def test_inventory_binds_relocated_tools_ci_and_runtime_entrypoints(self):
        included = (
            ".github/workflows/reference-ci.yml",
            ".github/dependabot.yaml",
            "tools/verification/run_tests.py",
            "tools/build/build_orchestrator.ps1",
            "tools/nested/helper.mjs",
            "tests/tooling/test_gui_lifecycle.cjs",
            "config/gui_release.json",
            "server.py",
            "run_gui.ps1",
            "run_dfpn_on_d.ps1",
            "follow_dfpn_saturated_line_on_d.ps1",
        )
        excluded = (
            "build/nnue_sprt_6t_vs_12t/checkpoint.json",
            "build/nnue_sprt_6t_vs_12t_c4_v1/checkpoint.json",
            "saved_games/game.json",
            "tools/__pycache__/ghost.py",
            "tools/notes.txt",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in included + excluded:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original\n", encoding="utf-8")
            paths = runner.source_inventory_paths(root)
            self.assertEqual(
                [path.relative_to(root).as_posix() for path in paths],
                sorted(included),
            )
            original = runner.inventory_sha256(paths, root=root)
            for name in included:
                with self.subTest(path=name):
                    path = root / name
                    path.write_text("changed\n", encoding="utf-8")
                    self.assertNotEqual(original, runner.inventory_sha256(paths, root=root))
                    path.write_text("original\n", encoding="utf-8")
            added = root / "tools/new_runner.py"
            added.write_text("pass\n", encoding="utf-8")
            self.assertNotEqual(paths, runner.source_inventory_paths(root))
            added.unlink()
            (root / included[0]).unlink()
            self.assertNotEqual(paths, runner.source_inventory_paths(root))

    def test_real_suite_discovery_supports_non_package_tests_directory(self):
        suite = runner.discover_complete_suite()
        self.assertGreater(suite.countTestCases(), 0)

    def test_source_and_test_inventories_are_deterministic_and_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "makhos").mkdir()
            (root / "tests" / "__pycache__").mkdir(parents=True)
            (root / "makhos" / "engine.py").write_text("x = 1\n", encoding="utf-8")
            (root / "tests" / "test_one.py").write_text("pass\n", encoding="utf-8")
            (root / "tests" / "notes.txt").write_text("ignored\n", encoding="utf-8")
            (root / "tests" / "__pycache__" / "ghost.py").write_text(
                "ignored\n", encoding="utf-8"
            )
            (root / "RULESET.json").write_text("{}\n", encoding="utf-8")

            source_paths = runner.source_inventory_paths(root)
            test_paths = runner.test_inventory_paths(root)
            relative_sources = [path.relative_to(root).as_posix() for path in source_paths]
            self.assertEqual(
                relative_sources,
                ["RULESET.json", "makhos/engine.py", "tests/test_one.py"],
            )
            self.assertEqual(
                [path.relative_to(root).as_posix() for path in test_paths],
                ["tests/test_one.py"],
            )
            first = runner.inventory_sha256(source_paths, root=root)
            second = runner.inventory_sha256(reversed(source_paths), root=root)
            self.assertEqual(first, second)
            (root / "makhos" / "engine.py").write_text("x = 2\n", encoding="utf-8")
            self.assertNotEqual(
                first,
                runner.inventory_sha256(source_paths, root=root),
            )

    def test_exclusive_lease_owns_every_slot_and_releases_it(self):
        fake = FakeLock()
        with runner.ExclusiveSuiteLease(
            runner.ROOT,
            interactive_probe=lambda: False,
            lock_factory=lambda _path: fake,
        ):
            self.assertEqual(fake.try_calls, [(0, runner.LOCK_SLOTS)])
            self.assertFalse(fake.closed)
        self.assertTrue(fake.closed)

    def test_exclusive_lease_fails_closed_for_gui_or_lock_contention(self):
        gui_lock = FakeLock()
        with self.assertRaises(runner.InteractivePriorityChanged):
            with runner.ExclusiveSuiteLease(
                runner.ROOT,
                interactive_probe=lambda: True,
                lock_factory=lambda _path: gui_lock,
            ):
                pass
        self.assertTrue(gui_lock.closed)
        busy_lock = FakeLock(locks=False)
        with self.assertRaisesRegex(runner.FullSuiteGateError, "every batch"):
            with runner.ExclusiveSuiteLease(
                runner.ROOT,
                interactive_probe=lambda: False,
                lock_factory=lambda _path: busy_lock,
            ):
                pass
        self.assertTrue(busy_lock.closed)

    def test_execute_suite_checkpoints_each_test(self):
        events = []
        suite = passing_suite()
        result, output, duration = runner.execute_suite(
            suite,
            checkpoint=events.append,
            verbosity=1,
        )
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0].startswith("before test "))
        self.assertTrue(events[1].startswith("after test "))
        self.assertIn("OK", output)
        self.assertGreaterEqual(duration, 0.0)

    def test_built_attestation_satisfies_hardened_contract_gate(self):
        test_paths = runner.test_inventory_paths(runner.ROOT)
        source_paths = runner.source_inventory_paths(runner.ROOT)
        result, output, duration = runner.execute_suite(
            passing_suite(),
            checkpoint=lambda _stage: None,
            verbosity=1,
        )
        attestation = runner.build_attestation(
            final_audit_sha256="A" * 64,
            started_at_utc="2026-08-28T00:00:00+00:00",
            completed_at_utc="2026-08-28T00:00:01+00:00",
            duration_seconds=duration,
            discovered_tests=1,
            result=result,
            result_output=output,
            test_inventory_sha256=runner.inventory_sha256(
                test_paths, root=runner.ROOT
            ),
            source_inventory_sha256=runner.inventory_sha256(
                source_paths, root=runner.ROOT
            ),
            test_files=len(test_paths),
            source_files=len(source_paths),
            command=[sys.executable, str(Path(runner.__file__).resolve())],
        )
        snapshot = contract_gate.JsonSnapshot(
            path=Path("synthetic-suite.json"),
            payload=attestation,
            encoded=b"",
            sha256="D" * 64,
        )
        validated = contract_gate._validate_suite_attestation(
            snapshot,
            final_audit_sha256="A" * 64,
        )
        self.assertEqual(validated["tests_run"], 1)
        self.assertEqual(
            validated["result_output_sha256"],
            hashlib.sha256(output.encode("utf-8")).hexdigest().upper(),
        )

    def test_builder_rejects_failed_or_incomplete_suite(self):
        result, output, duration = runner.execute_suite(
            failing_suite(),
            checkpoint=lambda _stage: None,
            verbosity=1,
        )
        with self.assertRaisesRegex(runner.FullSuiteGateError, "did not PASS"):
            runner.build_attestation(
                final_audit_sha256="A" * 64,
                started_at_utc="start",
                completed_at_utc="end",
                duration_seconds=duration,
                discovered_tests=1,
                result=result,
                result_output=output,
                test_inventory_sha256="B" * 64,
                source_inventory_sha256="C" * 64,
                test_files=1,
                source_files=1,
                command=["synthetic"],
            )

    def test_preconditions_reject_live_pipeline_before_health_or_audit_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work_dir = root / "work"
            work_dir.mkdir()
            with (
                mock.patch.object(
                    runner,
                    "live_full_run_processes",
                    return_value=[{"pid": 42}],
                ),
                mock.patch.object(runner, "build_health_snapshot") as health,
                mock.patch.object(contract_gate, "load_json_snapshot") as audit,
            ):
                with self.assertRaisesRegex(runner.FullSuiteGateError, "still active"):
                    runner.validate_run_preconditions(
                        work_dir=work_dir,
                        final_audit_path=root / "audit.json",
                        output_path=root / "suite.json",
                    )
            health.assert_not_called()
            audit.assert_not_called()

    def test_preconditions_reject_output_inside_bound_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory) / "work"
            work_dir.mkdir()
            with mock.patch.object(
                runner,
                "live_full_run_processes",
                return_value=[],
            ) as processes:
                with self.assertRaisesRegex(
                    runner.FullSuiteGateError, "source/test inventory"
                ):
                    runner.validate_run_preconditions(
                        work_dir=work_dir,
                        final_audit_path=Path(directory) / "audit.json",
                        output_path=runner.ROOT / "scratch" / "suite.json",
                    )
            processes.assert_not_called()

    def test_production_open_guard_blocks_only_bound_production_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory) / "work"
            protected = work_dir / "analyses" / "0001.analysis.json"
            unrelated = Path(directory) / "fixture" / "0001.analysis.json"
            guard = runner.ProductionOpenGuard(work_dir)
            guard.hook("open", (str(unrelated), "r", 0))
            with self.assertRaisesRegex(runner.FullSuiteGateError, "protected"):
                guard.hook("open", (str(protected), "r", 0))
            self.assertEqual(guard.triggered, [protected.resolve()])

    def test_postchecks_and_attestation_write_remain_inside_exclusive_lease(self):
        tree = ast.parse(Path(runner.__file__).read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "run_complete_suite"
        )
        lease = next(
            node
            for node in ast.walk(function)
            if isinstance(node, ast.With)
            and any(
                isinstance(item.context_expr, ast.Call)
                and getattr(item.context_expr.func, "id", None)
                == "ExclusiveSuiteLease"
                for item in node.items
            )
        )
        required_calls = {
            "build_health_snapshot",
            "inventory_sha256",
            "build_attestation",
            "write_locked_json",
        }
        calls_inside = {
            getattr(node.func, "id", None)
            for statement in lease.body
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
        }
        self.assertTrue(required_calls <= calls_inside)

    def test_cli_imports_from_outside_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(Path(runner.__file__).resolve()), "--help"],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--final-audit", result.stdout)
        self.assertIn("--output", result.stdout)


    def test_legacy_wrapper_reexports_and_runs_cli(self):
        self.assertIs(legacy_runner.ExclusiveSuiteLease, runner.ExclusiveSuiteLease)
        self.assertIs(legacy_runner.execute_suite, runner.execute_suite)
        self.assertIs(legacy_runner.inventory_sha256, runner.inventory_sha256)
        self.assertIs(legacy_runner.source_inventory_paths, runner.source_inventory_paths)
        self.assertIs(legacy_runner.test_inventory_paths, runner.test_inventory_paths)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(Path(legacy_runner.__file__).resolve()), "--help"],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--final-audit", result.stdout)
        self.assertIn("--output", result.stdout)


if __name__ == "__main__":
    unittest.main()
