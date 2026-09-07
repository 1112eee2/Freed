import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scratch import nnue_sealed_test_evaluate as sealed


class SealedTestEvaluatorTests(unittest.TestCase):
    def test_regression_metrics_and_calibration_are_deterministic(self):
        pairs = [(0.5, 0.25), (-0.5, -0.25), (0.0, 0.0)]
        metrics = sealed.regression_metrics(pairs)
        self.assertEqual(metrics["count"], 3)
        self.assertAlmostEqual(metrics["mae"], 1 / 6)
        self.assertAlmostEqual(metrics["rmse"], math.sqrt(0.125 / 3))
        self.assertEqual(metrics["sign_mismatch_rate"], 0.0)
        bins = sealed.calibration(pairs)
        self.assertEqual(sum(row["count"] for row in bins), 3)

    def test_locked_artifact_rejects_different_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locked.json"
            sealed.write_locked(path, {"value": 1})
            sealed.write_locked(path, {"value": 1})
            with self.assertRaisesRegex(RuntimeError, "locked artifact differs"):
                sealed.write_locked(path, {"value": 2})

    def test_preflight_does_not_open_sealed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.json" for name in sealed.default_paths()}
            paths["output_dir"] = root / "output"
            paths["sealed_manifest"].write_text("DO NOT OPEN", encoding="utf-8")
            expected = {
                name: "A" * 64
                for name in sealed.EXPECTED
            }
            expected["sealed_manifest"] = "B" * 64
            for name in expected:
                if name not in {"sealed_manifest", "partition_commitment", "trainer_contract"}:
                    paths[name].write_text(name, encoding="utf-8")
                    expected[name] = sealed.sha256(paths[name])
            commitment = {
                "sealed_test_manifest_sha256": expected["sealed_manifest"],
                "sealed_test_games": sealed.EXPECTED_TEST_GAMES,
                "sealed_test_selected_positions": sealed.EXPECTED_TEST_POSITIONS,
                "test_analysis_files_may_be_read": False,
            }
            paths["partition_commitment"].write_text(
                json.dumps(commitment), encoding="utf-8"
            )
            expected["partition_commitment"] = sealed.sha256(
                paths["partition_commitment"]
            )
            contract = {
                "sealed_test_policy": {
                    "manifest_sha256": expected["sealed_manifest"],
                    "labels_opened": False,
                    "model_selection_forbidden": True,
                    "open_count_limit": 1,
                },
                "network": {"hidden": [128, 32]},
            }
            paths["trainer_contract"].write_text(
                json.dumps(contract), encoding="utf-8"
            )
            expected["trainer_contract"] = sealed.sha256(paths["trainer_contract"])
            from scratch import nnue_full_suite_attestation as full_suite

            suite = {
                "verdict": "PASS",
                "tests_run": 1,
                "discovered_tests": 1,
                "sealed_test_manifest_read": False,
                "accepted_library_sha256": expected["accepted_library"],
                "source_inventory_sha256": full_suite.inventory_sha256(
                    full_suite.source_inventory_paths(sealed.ROOT), root=sealed.ROOT
                ),
                "test_inventory_sha256": full_suite.inventory_sha256(
                    full_suite.test_inventory_paths(sealed.ROOT), root=sealed.ROOT
                ),
            }
            paths["full_suite"].write_text(json.dumps(suite), encoding="utf-8")
            original_read_text = Path.read_text

            def guarded_read_text(path_self, *args, **kwargs):
                if path_self.resolve() == paths["sealed_manifest"].resolve():
                    raise AssertionError("preflight opened sealed manifest")
                return original_read_text(path_self, *args, **kwargs)

            with (
                patch.object(sealed, "EXPECTED", expected),
                patch.object(Path, "read_text", guarded_read_text),
            ):
                payload = sealed.preflight(paths)
            self.assertEqual(payload["verdict"], "AUTHORIZED_TO_OPEN_ONCE")
            written = json.loads(
                (paths["output_dir"] / "opening_authorization.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(written["sealed_manifest_read"])

    def test_outcome_value_is_strict(self):
        self.assertEqual(sealed.outcome_value("win"), 1.0)
        self.assertEqual(sealed.outcome_value("draw"), 0.0)
        self.assertEqual(sealed.outcome_value("loss"), -1.0)
        self.assertIsNone(sealed.outcome_value("black"))


if __name__ == "__main__":
    unittest.main()
