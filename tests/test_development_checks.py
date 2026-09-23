"""Developer checks must never label skipped or incomplete work as a PASS."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.verification import run_tests as runner


class DevelopmentCheckTests(unittest.TestCase):
    def test_python_gate_rejects_skips_incomplete_and_expected_failures(self):
        result = unittest.TestResult()
        result.testsRun = 2
        self.assertTrue(runner.python_passed(result, 2))
        self.assertFalse(runner.python_passed(result, 0))
        self.assertFalse(runner.python_passed(result, 3))
        result.skipped.append((None, "missing DLL"))
        self.assertFalse(runner.python_passed(result, 2))
        result.skipped.clear()
        result.expectedFailures.append((None, "still broken"))
        self.assertFalse(runner.python_passed(result, 2))

    def test_node_report_requires_explicit_counts(self):
        counts = runner.tap_summary("# tests 16\n# pass 16\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n")
        self.assertEqual(counts["tests"], 16)
        with self.assertRaises(runner.gate.FullSuiteGateError):
            runner.tap_summary("# tests 16\n# pass 16\n")
        with self.assertRaises(runner.gate.FullSuiteGateError):
            runner.tap_summary("# tests 16\n# tests 17\n")

    def test_reference_discovery_fails_if_a_selected_file_disappears(self):
        with patch.object(runner, "REFERENCE_TEST_FILES", ("test_does_not_exist.py",)):
            with self.assertRaisesRegex(runner.gate.FullSuiteGateError, "missing reference"):
                runner.discover("reference")

    def test_reference_hash_check_accepts_line_endings_but_rejects_content_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in runner.EXPECTED_RULE_HASHES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                data = (runner.ROOT / name).read_bytes().replace(b"\r\n", b"\n")
                path.write_bytes(data.replace(b"\n", b"\r\n"))
            runner.verify_invariants(root)
            (root / "RULESET.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(runner.gate.FullSuiteGateError, "immutable reference"):
                runner.verify_invariants(root)

    def test_output_cannot_overwrite_evidence_or_escape_build(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
            root = Path(directory)
            target = root / "build/run"
            self.assertEqual(runner.new_output_directory(target), target)
            with self.assertRaises(FileExistsError):
                runner.new_output_directory(target)
            for target in (root / "makhos", root / "build", root / "build/../tests"):
                with self.assertRaises(runner.gate.FullSuiteGateError):
                    runner.new_output_directory(target)

    def test_output_rejects_protected_runs_before_creating_any_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
            root = Path(directory)
            with patch.object(runner.gate, "DEFAULT_WORK_DIR", root / "build/acquisition"):
                for name in ("nnue_sprt_6t_vs_12t", "nnue_sprt_6t_vs_12t_c4_v1", "acquisition"):
                    for suffix in ("", "/new-report"):
                        with self.subTest(run=name, suffix=suffix):
                            target = root / ("build/" + name + suffix)
                            with self.assertRaisesRegex(runner.gate.FullSuiteGateError, "protected"):
                                runner.new_output_directory(target)
                            self.assertFalse(target.exists())
                self.assertFalse((root / "build").exists())


if __name__ == "__main__":
    unittest.main()
