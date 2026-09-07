import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scratch import nnue_scaling_final_audit as final_audit
from scratch import nnue_full_suite_attestation as suite_runner
from scratch import nnue_trainer_contract_gate as gate
from scratch.nnue_quiet_leaf_acquire import encoded_json, sha256


TRAIN_ID = "0000000000000001"
VALIDATION_ID = "0000000000000002"
SEALED_SHA = "D" * 64
TEST_PATHS = suite_runner.test_inventory_paths(gate.ROOT)
SOURCE_PATHS = suite_runner.source_inventory_paths(gate.ROOT)
TEST_INVENTORY_SHA = suite_runner.inventory_sha256(TEST_PATHS, root=gate.ROOT)
SOURCE_INVENTORY_SHA = suite_runner.inventory_sha256(SOURCE_PATHS, root=gate.ROOT)
RESULT_OUTPUT_SHA = "9" * 64
TRAINER_SOURCE_SHA = "A" * 64
TRAINER_FIXTURE_SHA = "B" * 64


def write_json(path: Path, payload: dict) -> None:
    path.write_text(encoded_json(payload), encoding="utf-8")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def inventory_game(game_id: str, marker: str) -> dict:
    return {
        "game_id": game_id,
        "game_sha256": marker * 64,
        "selection_sha256": chr(ord(marker) + 1) * 64,
        "selected_positions": 10,
        "analysis_file": f"{game_id}.analysis.json",
        "analysis_sha256": chr(ord(marker) + 2) * 64,
    }


class TrainerContractGateTests(unittest.TestCase):
    def test_snapshot_loader_accepts_project_lf_canonical_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.json"
            payload = {"kind": "project-writer", "value": 1}
            path.write_bytes(encoded_json(payload).encode("utf-8"))
            snapshot = gate.load_json_snapshot(path)
        self.assertEqual(snapshot.payload, payload)

    def test_manifest_and_inventory_allow_zero_selected_games(self):
        zero_id = "0000000000000003"
        train_game = inventory_game(TRAIN_ID, "1")
        zero_game = inventory_game(zero_id, "7")
        zero_game["selected_positions"] = 0
        validation_game = inventory_game(VALIDATION_ID, "4")
        manifest_games = []
        for row, split in (
            (train_game, "train"),
            (zero_game, "train"),
            (validation_game, "validation"),
        ):
            manifest_games.append(
                {
                    "game_id": row["game_id"],
                    "sha256": row["game_sha256"],
                    "selection_sha256": row["selection_sha256"],
                    "selected_positions": row["selected_positions"],
                    "split": split,
                }
            )
        manifest = {
            "format": "thai-makhos-nnue-quiet-leaf-acquisition-v1",
            "kind": "development-selection-manifest",
            "split_before_sampling": True,
            "games_by_split": {"train": 2, "validation": 1},
            "sealed_test_commitment": {
                "manifest_sha256": SEALED_SHA,
                "model_selection_may_read": False,
            },
            "games": manifest_games,
        }
        snapshot = gate.JsonSnapshot(Path("development.json"), manifest, b"", "A" * 64)
        with (
            mock.patch.object(gate, "EXPECTED_DEVELOPMENT_GAMES", 3),
            mock.patch.object(gate, "EXPECTED_DEVELOPMENT_MANIFEST_SHA256", "A" * 64),
            mock.patch.object(gate, "EXPECTED_SEALED_TEST_MANIFEST_SHA256", SEALED_SHA),
        ):
            development_games = gate._validate_development_manifest(snapshot)
            inventory_payload = {
                "format": gate.INVENTORY_FORMAT,
                "kind": "trainer-input-inventory",
                "split": "train",
                "development_manifest_sha256": "A" * 64,
                "analysis_set_sha256": "B" * 64,
                "games": [train_game, zero_game],
            }
            ids, _rows = gate._validate_inventory(
                gate.JsonSnapshot(Path("train.json"), inventory_payload, b"", "C" * 64),
                expected_split="train",
                development_games=development_games,
                analysis_set_sha256="B" * 64,
            )
        self.assertEqual(ids, {TRAIN_ID, zero_id})

    def build_fixture(self, root: Path) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        train_game = inventory_game(TRAIN_ID, "1")
        validation_game = inventory_game(VALIDATION_ID, "4")
        analysis_set_sha = gate._analysis_set_sha256(
            [
                (train_game["analysis_file"], train_game["analysis_sha256"]),
                (
                    validation_game["analysis_file"],
                    validation_game["analysis_sha256"],
                ),
            ]
        )
        development = {
            "format": "thai-makhos-nnue-quiet-leaf-acquisition-v1",
            "kind": "development-selection-manifest",
            "split_before_sampling": True,
            "games_by_split": {"train": 1, "validation": 1},
            "sealed_test_commitment": {
                "manifest_sha256": SEALED_SHA,
                "model_selection_may_read": False,
            },
            "games": [
                {
                    "game_id": TRAIN_ID,
                    "path": "D:/synthetic/train.json",
                    "provisional_positions": 10,
                    "selected": [],
                    "selected_positions": train_game["selected_positions"],
                    "selection_sha256": train_game["selection_sha256"],
                    "sha256": train_game["game_sha256"],
                    "split": "train",
                },
                {
                    "game_id": VALIDATION_ID,
                    "path": "D:/synthetic/validation.json",
                    "provisional_positions": 10,
                    "selected": [],
                    "selected_positions": validation_game["selected_positions"],
                    "selection_sha256": validation_game["selection_sha256"],
                    "sha256": validation_game["game_sha256"],
                    "split": "validation",
                },
            ],
        }
        development_path = root / "development.json"
        write_json(development_path, development)
        development_sha = file_sha(development_path)

        train_inventory = {
            "format": gate.INVENTORY_FORMAT,
            "kind": "trainer-input-inventory",
            "split": "train",
            "development_manifest_sha256": development_sha,
            "analysis_set_sha256": analysis_set_sha,
            "games": [train_game],
        }
        validation_inventory = {
            "format": gate.INVENTORY_FORMAT,
            "kind": "trainer-input-inventory",
            "split": "validation",
            "development_manifest_sha256": development_sha,
            "analysis_set_sha256": analysis_set_sha,
            "games": [validation_game],
        }
        train_path = root / "train_inventory.json"
        validation_path = root / "validation_inventory.json"
        write_json(train_path, train_inventory)
        write_json(validation_path, validation_inventory)

        coverage = {
            "train": {"games": 1, "selected": 10, "eligible": 900},
            "validation": {"games": 1, "selected": 10, "eligible": 100},
        }
        audit = {
            "format": final_audit.FORMAT,
            "kind": "final-development-data-readiness-audit",
            "verdict": "PASS",
            "playing_code_changed": False,
            "model_trained": False,
            "trainer_authorized_by_this_artifact": False,
            "accepted_library_sha256": gate.EXPECTED_ACCEPTED_SHA256,
            "audit_script_sha256": sha256(Path(final_audit.__file__).resolve()),
            "development_manifest_sha256": development_sha,
            "sealed_test_manifest_sha256": SEALED_SHA,
            "sealed_test_manifest_read": False,
            "test_analysis_files_read": 0,
            "analysis_set_sha256": analysis_set_sha,
            "analysis_files": 2,
            "coverage": coverage,
            "gates": {"synthetic_gate": True},
        }
        audit_a = root / "audit_a.json"
        audit_b = root / "audit_b.json"
        write_json(audit_a, audit)
        write_json(audit_b, audit)
        audit_sha = file_sha(audit_a)

        suite = {
            "format": gate.SUITE_FORMAT,
            "kind": "post-acquisition-complete-suite",
            "verdict": "PASS",
            "workers_idle": True,
            "interactive_session_inactive_before_and_after": True,
            "health_state_before_and_after": [
                "COMPLETE_PENDING_FINAL_GATES",
                "COMPLETE_PENDING_FINAL_GATES",
            ],
            "exit_code": 0,
            "discovered_tests": 250,
            "tests_run": 250,
            "failures": 0,
            "errors": 0,
            "expected_failures": 0,
            "unexpected_successes": 0,
            "skipped": 0,
            "duration_seconds": 90.0,
            "started_at_utc": "2026-08-28T00:00:00+00:00",
            "completed_at_utc": "2026-08-28T00:01:30+00:00",
            "command": [sys.executable, "-B", "-m", "unittest", "discover"],
            "python_version": sys.version.split()[0],
            "test_files": len(TEST_PATHS),
            "source_files": len(SOURCE_PATHS),
            "test_inventory_sha256": TEST_INVENTORY_SHA,
            "source_inventory_sha256": SOURCE_INVENTORY_SHA,
            "runner_sha256": sha256(gate.FULL_SUITE_RUNNER),
            "result_output_sha256": RESULT_OUTPUT_SHA,
            "accepted_library_sha256": gate.EXPECTED_ACCEPTED_SHA256,
            "final_data_audit_sha256": audit_sha,
            "analysis_payloads_read": 0,
            "sealed_test_manifest_read": False,
            "test_analysis_files_read": 0,
            "production_open_guard_triggered": False,
        }
        suite_path = root / "suite.json"
        write_json(suite_path, suite)

        contract = {
            "format": gate.CONTRACT_FORMAT,
            "kind": "first-float-nnue-v1",
            "status": "FROZEN",
            "accepted_library_sha256": gate.EXPECTED_ACCEPTED_SHA256,
            "ruleset_sha256": sha256(gate.RULESET),
            "evidence": {
                "final_data_audit_sha256": audit_sha,
                "final_data_audit_script_sha256": audit["audit_script_sha256"],
                "development_manifest_sha256": development_sha,
                "analysis_set_sha256": analysis_set_sha,
                "full_suite_attestation_sha256": file_sha(suite_path),
                "full_suite_test_inventory_sha256": TEST_INVENTORY_SHA,
                "full_suite_source_inventory_sha256": SOURCE_INVENTORY_SHA,
                "full_suite_runner_sha256": suite["runner_sha256"],
                "train_inventory_sha256": file_sha(train_path),
                "validation_inventory_sha256": file_sha(validation_path),
                "trainer_source_sha256": TRAINER_SOURCE_SHA,
                "trainer_fixture_sha256": TRAINER_FIXTURE_SHA,
                "final_audit_reproduced_byte_identical": True,
            },
            "dataset": {
                "split_unit": "source_game",
                "dedup_identity": "canonical_position_plus_reversible_clock",
                "train_games": 1,
                "validation_games": 1,
                "train_selected_rows": 10,
                "validation_selected_rows": 10,
                "train_eligible_rows": 900,
                "validation_eligible_rows": 100,
                "train_game_ids_sha256": gate._game_id_set_sha256({TRAIN_ID}),
                "validation_game_ids_sha256": gate._game_id_set_sha256(
                    {VALIDATION_ID}
                ),
                "test_rows_included": False,
                "test_game_ids_included": False,
            },
            "feature_spec": {
                "name": "thai-makhos-shared-137-v1",
                "input_dimensions": 137,
                "piece_square_features": 128,
                "clock_buckets": [
                    "0",
                    "1_to_9",
                    "10_to_19",
                    "20_to_29",
                    "30_to_39",
                    "40_to_49",
                    "50_to_59",
                    "60_to_69",
                    "70_to_79",
                ],
                "black_canonical_square": "identity",
                "red_canonical_square": "31_minus_square",
                "perspective_categories": [
                    "own_man",
                    "own_king",
                    "opponent_man",
                    "opponent_king",
                ],
                "active_features": "piece_count_plus_one",
                "concatenation_order": ["side_to_move", "opponent"],
            },
            "network": {
                "architecture_count": 1,
                "perspective_accumulators": 2,
                "feature_width": 128,
                "concatenated_width": 256,
                "hidden_width": 32,
                "output_width": 1,
                "output_perspective": "side_to_move",
                "policy_head": False,
            },
            "targets": {
                "teacher_score": {
                    "enabled": True,
                    "clip_cp": 2000,
                    "normalization_kind": "tanh",
                    "normalization_scale_cp": 600.0,
                    "loss": "huber",
                    "loss_parameter": 0.1,
                },
                "game_outcome": {
                    "enabled": True,
                    "encoding": {"loss": -1, "draw": 0, "win": 1},
                    "loss": "mse",
                    "history_required": True,
                },
                "exact_wdl": {
                    "enabled": True,
                    "encoding": {"loss": -1, "draw": 0, "win": 1},
                    "loss": "mse",
                    "history_required": True,
                },
                "loss_mix": {
                    "teacher_score": 0.8,
                    "game_outcome": 0.1,
                    "exact_wdl": 0.1,
                },
                "missing_label_policy": (
                    "renormalize_available_components_per_sample"
                ),
                "calibration_source": "train_only",
                "test_used": False,
            },
            "weighting": {
                "source_game_equal_weight": True,
                "position_weighting": "uniform_within_source_game",
                "phase_weights": {
                    "13_to_16": 1.0,
                    "9_to_12": 1.0,
                    "5_to_8": 1.0,
                },
                "exact_wdl_multiplier": 1.0,
                "selection_source": "train_only",
            },
            "optimizer": {
                "name": "AdamW",
                "learning_rate": 0.001,
                "weight_decay": 0.0001,
                "batch_size": 256,
                "max_epochs": 50,
                "schedule": {"kind": "cosine", "warmup_epochs": 2},
            },
            "reproducibility": {
                "seeds": [20280001, 20280002],
                "deterministic_algorithms": True,
                "deterministic_resume_required": True,
                "checkpoint_checksum": "sha256",
                "dataloader_workers": 0,
                "dependencies": {"python": sys.version.split()[0], "trainer": "v1"},
                "target_cpu": "AMD Ryzen 5 5600H",
            },
            "learning_curve": {
                "sizes": [250, 500, "all"],
                "same_split": True,
                "predeclared": True,
                "selection_source": "train_only",
            },
            "checkpoint": {
                "selection_split": "validation",
                "metric": "validation_loss",
                "mode": "min",
                "early_stop_patience": 5,
                "min_delta": 0.0001,
                "restore_best": True,
                "test_used": False,
            },
            "external_regressions": {
                "report_only": True,
                "hyperparameter_selection": False,
            },
            "sealed_test_policy": {
                "manifest_sha256": SEALED_SHA,
                "labels_opened": False,
                "model_selection_forbidden": True,
                "open_count_limit": 1,
                "open_only_after": [
                    "architecture_frozen",
                    "loss_frozen",
                    "checkpoint_frozen",
                    "quantization_frozen",
                    "model_binary_frozen",
                ],
                "fresh_split_required_after_model_change": True,
            },
            "authorization_policy": {
                "training_requires_this_gate_pass": True,
                "playing_code_changed": False,
                "model_already_trained": False,
            },
        }
        contract_a_path = root / "contract_a.json"
        contract_b_path = root / "contract_b.json"
        write_json(contract_a_path, contract)
        write_json(contract_b_path, contract)
        preflight = {
            "format": gate.PREFLIGHT_FORMAT,
            "kind": "tiny-fixture-trainer-readiness",
            "verdict": "PASS",
            "contract_sha256": file_sha(contract_a_path),
            "final_data_audit_sha256": audit_sha,
            "trainer_source_sha256": TRAINER_SOURCE_SHA,
            "fixture_sha256": TRAINER_FIXTURE_SHA,
            "seeds_tested": [20280001, 20280002],
            "tiny_fixture_overfit": True,
            "deterministic_repeat_byte_identical": True,
            "deterministic_resume_byte_identical": True,
            "checkpoint_checksum_verified": True,
            "sealed_guard_tests_passed": True,
            "development_rows_read": 0,
            "sealed_test_manifest_read": False,
            "test_analysis_files_read": 0,
            "production_model_trained": False,
            "fixture_model_discarded": True,
            "training_run_authorized_by_this_artifact": False,
        }
        preflight_path = root / "trainer_preflight.json"
        write_json(preflight_path, preflight)
        sealed_decoy = root / "sealed_test_selection_manifest.json"
        sealed_decoy.write_text("must not be opened", encoding="utf-8")
        return {
            "contract_a": contract_a_path,
            "contract_b": contract_b_path,
            "audit_a": audit_a,
            "audit_b": audit_b,
            "development": development_path,
            "train": train_path,
            "validation": validation_path,
            "suite": suite_path,
            "preflight": preflight_path,
            "sealed_decoy": sealed_decoy,
            "development_sha": development_sha,
        }

    def authorize(self, fixture: dict) -> dict:
        with (
            mock.patch.object(gate, "EXPECTED_DEVELOPMENT_GAMES", 2),
            mock.patch.object(
                gate,
                "EXPECTED_DEVELOPMENT_MANIFEST_SHA256",
                fixture["development_sha"],
            ),
            mock.patch.object(
                gate,
                "EXPECTED_SEALED_TEST_MANIFEST_SHA256",
                SEALED_SHA,
            ),
        ):
            return gate.authorize_from_paths(
                contract_a_path=fixture["contract_a"],
                contract_b_path=fixture["contract_b"],
                final_audit_a_path=fixture["audit_a"],
                final_audit_b_path=fixture["audit_b"],
                development_manifest_path=fixture["development"],
                train_inventory_path=fixture["train"],
                validation_inventory_path=fixture["validation"],
                full_suite_attestation_path=fixture["suite"],
                trainer_preflight_path=fixture["preflight"],
            )

    def test_valid_contract_authorizes_without_reading_sealed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            original = Path.read_bytes
            reads = []

            def tracked(path_self):
                reads.append(path_self.resolve())
                if path_self.resolve() == fixture["sealed_decoy"].resolve():
                    raise AssertionError("sealed-test file was opened")
                return original(path_self)

            with mock.patch.object(Path, "read_bytes", tracked):
                report = self.authorize(fixture)
            self.assertTrue(report["training_authorized"])
            self.assertEqual(report["verdict"], "PASS")
            self.assertFalse(report["sealed_test_manifest_read"])
            self.assertEqual(report["test_analysis_files_read"], 0)
            self.assertNotIn(fixture["sealed_decoy"].resolve(), reads)

    def test_report_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            first = self.authorize(fixture)
            second = self.authorize(fixture)
            self.assertEqual(encoded_json(first), encoded_json(second))

    def test_rejects_nonidentical_final_audit_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            payload = json.loads(fixture["audit_b"].read_text(encoding="utf-8"))
            payload["gates"]["second_run_drift"] = True
            write_json(fixture["audit_b"], payload)
            with self.assertRaisesRegex(gate.ContractGateError, "byte-identical"):
                self.authorize(fixture)

    def test_rejects_cross_split_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            payload = json.loads(fixture["train"].read_text(encoding="utf-8"))
            payload["games"][0]["game_id"] = VALIDATION_ID
            payload["games"][0]["analysis_file"] = (
                f"{VALIDATION_ID}.analysis.json"
            )
            write_json(fixture["train"], payload)
            with self.assertRaisesRegex(gate.ContractGateError, "absent from its split"):
                self.authorize(fixture)

    def test_rejects_checkpoint_selected_from_test(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            payload = json.loads(fixture["contract_a"].read_text(encoding="utf-8"))
            payload["checkpoint"]["metric"] = "test_loss"
            write_json(fixture["contract_a"], payload)
            write_json(fixture["contract_b"], payload)
            with self.assertRaisesRegex(gate.ContractGateError, "checkpoint"):
                self.authorize(fixture)

    def test_rejects_nonidentical_contract_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            payload = json.loads(fixture["contract_b"].read_text(encoding="utf-8"))
            payload["optimizer"]["max_epochs"] += 1
            write_json(fixture["contract_b"], payload)
            with self.assertRaisesRegex(gate.ContractGateError, "contract reproduction"):
                self.authorize(fixture)

    def test_rejects_failed_deterministic_resume_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.build_fixture(Path(directory))
            payload = json.loads(fixture["preflight"].read_text(encoding="utf-8"))
            payload["deterministic_resume_byte_identical"] = False
            write_json(fixture["preflight"], payload)
            with self.assertRaisesRegex(gate.ContractGateError, "deterministic_resume"):
                self.authorize(fixture)

    def test_rejects_forged_or_stale_full_suite_evidence(self):
        cases = [
            ("source_inventory_sha256", "0" * 64, "source inventory"),
            ("runner_sha256", "1" * 64, "runner binding"),
            ("analysis_payloads_read", 1, "protected data boundary"),
            ("tests_run", 249, "every discovered test"),
            ("started_at_utc", "not-a-time", "ISO timestamp"),
        ]
        for key, value, message in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                fixture = self.build_fixture(Path(directory))
                payload = json.loads(
                    fixture["suite"].read_text(encoding="utf-8")
                )
                payload[key] = value
                write_json(fixture["suite"], payload)
                with self.assertRaisesRegex(gate.ContractGateError, message):
                    self.authorize(fixture)

    def test_rejects_noncanonical_or_duplicate_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            noncanonical = root / "noncanonical.json"
            noncanonical.write_text('{"b": 1, "a": 2}', encoding="utf-8")
            with self.assertRaisesRegex(gate.ContractGateError, "canonical"):
                gate.load_json_snapshot(noncanonical)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a": 1, "a": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(gate.ContractGateError, "duplicate"):
                gate.load_json_snapshot(duplicate)

    def test_cli_imports_from_repo_root(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(gate.ROOT / "scratch" / "nnue_trainer_contract_gate.py"),
                "--help",
            ],
            cwd=Path(tempfile.gettempdir()),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--full-suite-attestation", result.stdout)
        self.assertIn("--trainer-preflight", result.stdout)


if __name__ == "__main__":
    unittest.main()
