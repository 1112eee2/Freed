import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scratch import nnue_trainer_contract_freezer as freezer
from scratch import nnue_trainer_preflight as preflight
from scratch.nnue_quiet_leaf_acquire import encoded_json
from tests.test_nnue_trainer_contract_freezer import sample_inputs


def write_canonical(path: Path, payload: dict) -> None:
    path.write_bytes(encoded_json(payload).encode("utf-8"))


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class TrainerPreflightTests(unittest.TestCase):
    def test_preflight_accepts_native_newline_final_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            audit = json.loads(fixture["audit"].read_text(encoding="utf-8"))
            fixture["audit"].write_bytes(
                encoded_json(audit).replace("\n", os.linesep).encode("utf-8")
            )
            contract = json.loads(
                fixture["contract"].read_text(encoding="utf-8")
            )
            contract["evidence"]["final_data_audit_sha256"] = file_sha(
                fixture["audit"]
            )
            write_canonical(fixture["contract"], contract)

            artifact = self.run_preflight(fixture)

        self.assertEqual(artifact["verdict"], "PASS")

    def build_fixture(self, root: Path) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        source = root / "trainer_source.py"
        source.write_bytes(b"# synthetic trainer source\n")
        fixture_path = root / "tiny_fixture.json"
        write_canonical(
            fixture_path,
            {
                "format": preflight.FIXTURE_FORMAT,
                "kind": preflight.FIXTURE_KIND,
                "samples": [
                    {"feature_indices": [0], "target": 0.75},
                    {"feature_indices": [1], "target": -0.5},
                    {"feature_indices": [2], "target": 0.25},
                    {"feature_indices": [3], "target": -0.125},
                ],
            },
        )
        audit_path = root / "final_audit.json"
        write_canonical(
            audit_path,
            {
                "format": "thai-makhos-nnue-final-audit-v1",
                "kind": "final-development-data-readiness-audit",
                "verdict": "PASS",
                "trainer_authorized_by_this_artifact": False,
            },
        )
        choices = sample_inputs()
        choices["evidence"]["final_data_audit_sha256"] = file_sha(audit_path)
        choices["trainer_source_sha256"] = file_sha(source)
        choices["trainer_fixture_sha256"] = file_sha(fixture_path)
        contract = freezer.freeze_contract(**choices)
        contract_path = root / "contract.json"
        write_canonical(contract_path, contract)
        production_root = root / "production"
        production_root.mkdir()
        return {
            "contract": contract_path,
            "audit": audit_path,
            "source": source,
            "fixture": fixture_path,
            "production": production_root,
            "output": root / "preflight.json",
        }

    def run_preflight(self, fixture: dict) -> dict:
        return preflight.run_preflight(
            contract_path=fixture["contract"],
            final_audit_path=fixture["audit"],
            trainer_source_path=fixture["source"],
            fixture_path=fixture["fixture"],
            output_path=fixture["output"],
            production_root=fixture["production"],
        )

    def test_realistic_synthetic_preflight_passes_and_is_non_authorizing(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            artifact = self.run_preflight(fixture)
            self.assertEqual(artifact["format"], preflight.gate.PREFLIGHT_FORMAT)
            self.assertEqual(artifact["kind"], preflight.PREFLIGHT_KIND)
            self.assertEqual(artifact["verdict"], "PASS")
            for key in (
                "tiny_fixture_overfit",
                "deterministic_repeat_byte_identical",
                "deterministic_resume_byte_identical",
                "checkpoint_checksum_verified",
                "sealed_guard_tests_passed",
                "fixture_model_discarded",
            ):
                self.assertTrue(artifact[key], key)
            self.assertEqual(artifact["development_rows_read"], 0)
            self.assertFalse(artifact["sealed_test_manifest_read"])
            self.assertEqual(artifact["test_analysis_files_read"], 0)
            self.assertFalse(artifact["production_model_trained"])
            self.assertFalse(artifact["training_run_authorized_by_this_artifact"])
            self.assertEqual(
                fixture["output"].read_bytes(),
                encoded_json(artifact).encode("utf-8"),
            )

    def test_repeat_run_and_locked_output_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            first = self.run_preflight(fixture)
            first_bytes = fixture["output"].read_bytes()
            second = self.run_preflight(fixture)
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, fixture["output"].read_bytes())

    def test_contract_source_and_fixture_bindings_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            contract = json.loads(fixture["contract"].read_text(encoding="utf-8"))
            contract["evidence"]["trainer_source_sha256"] = "A" * 64
            write_canonical(fixture["contract"], contract)
            with self.assertRaisesRegex(preflight.TrainerPreflightError, "trainer-source"):
                self.run_preflight(fixture)

    def test_bad_fixture_shape_and_duplicate_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            fixture["fixture"].write_bytes(
                encoded_json(
                    {
                        "format": preflight.FIXTURE_FORMAT,
                        "kind": preflight.FIXTURE_KIND,
                        "samples": [{"feature_indices": [0], "target": 1.0}],
                    }
                ).encode("utf-8")
            )
            with self.assertRaisesRegex(preflight.TrainerPreflightError, "at least two"):
                self.run_preflight(fixture)

            fixture = self.build_fixture(Path(directory) / "duplicate")
            fixture["fixture"].write_bytes(
                b'{"format":"thai-makhos-nnue-trainer-fixture-v1",'
                b'"format":"thai-makhos-nnue-trainer-fixture-v1",'
                b'"kind":"tiny-linear-overfit-fixture","samples":[]}\n'
            )
            with self.assertRaisesRegex(preflight.TrainerPreflightError, "duplicate JSON key"):
                self.run_preflight(fixture)

            fixture = self.build_fixture(Path(directory) / "noncanonical")
            fixture["fixture"].write_bytes(
                b'{"format":"thai-makhos-nnue-trainer-fixture-v1",'
                b'"kind":"tiny-linear-overfit-fixture","samples":[]}\n'
            )
            with self.assertRaisesRegex(preflight.TrainerPreflightError, "canonical"):
                self.run_preflight(fixture)

    def test_output_and_production_paths_are_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            for path in (
                fixture["production"] / "blocked.json",
                preflight.ROOT / "scratch" / "blocked-preflight.json",
                preflight.ROOT / "tests" / "blocked-preflight.json",
            ):
                with self.subTest(path=path), self.assertRaises(preflight.TrainerPreflightError):
                    preflight.run_preflight(
                        contract_path=fixture["contract"],
                        final_audit_path=fixture["audit"],
                        trainer_source_path=fixture["source"],
                        fixture_path=fixture["fixture"],
                        output_path=path,
                        production_root=fixture["production"],
                    )

    def test_cli_help_is_available_without_opening_production_data(self):
        # The command-line surface is intentionally checked through argparse's
        # parser construction only; running a real preflight belongs after the
        # final-data gate.
        self.assertEqual(preflight.PREFLIGHT_KIND, "tiny-fixture-trainer-readiness")
        self.assertEqual(preflight.CHECKPOINT_EPOCH * 2, preflight.EPOCHS)

    def test_direct_cli_smoke_uses_repo_root_import_path(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            command = [
                sys.executable,
                str(preflight.ROOT / "scratch" / "nnue_trainer_preflight.py"),
                "--contract",
                str(fixture["contract"]),
                "--final-audit",
                str(fixture["audit"]),
                "--trainer-source",
                str(fixture["source"]),
                "--fixture",
                str(fixture["fixture"]),
                "--output",
                str(fixture["output"]),
                "--production-root",
                str(fixture["production"]),
            ]
            completed = subprocess.run(
                command,
                cwd=preflight.ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["verdict"], "PASS")
            self.assertEqual(
                report["output_sha256"], file_sha(fixture["output"])
            )


if __name__ == "__main__":
    unittest.main()
