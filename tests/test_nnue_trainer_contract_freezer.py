import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scratch import nnue_trainer_contract_freezer as freezer
from scratch import nnue_trainer_contract_gate as gate


def sha(marker: str) -> str:
    return marker * 64


def sample_inputs() -> dict:
    evidence = {
        "final_data_audit_sha256": sha("A"),
        "final_data_audit_script_sha256": sha("B"),
        "development_manifest_sha256": gate.EXPECTED_DEVELOPMENT_MANIFEST_SHA256,
        "analysis_set_sha256": sha("C"),
        "full_suite_attestation_sha256": sha("D"),
        "full_suite_test_inventory_sha256": sha("E"),
        "full_suite_source_inventory_sha256": sha("F"),
        "full_suite_runner_sha256": sha("0"),
        "train_inventory_sha256": sha("1"),
        "validation_inventory_sha256": sha("2"),
    }
    dataset = {
        "train_games": 100,
        "validation_games": 20,
        "train_selected_rows": 80_000,
        "validation_selected_rows": 10_000,
        "train_eligible_rows": 90_000,
        "validation_eligible_rows": 11_000,
        "train_game_ids_sha256": sha("3"),
        "validation_game_ids_sha256": sha("4"),
    }
    labels = {
        "enabled": True,
        "encoding": {"loss": -1, "draw": 0, "win": 1},
        "loss": "mse",
        "history_required": True,
    }
    targets = {
        "teacher_score": {
            "enabled": True,
            "clip_cp": 2_000,
            "normalization_kind": "tanh",
            "normalization_scale_cp": 600.0,
            "loss": "huber",
            "loss_parameter": 0.1,
        },
        "game_outcome": copy.deepcopy(labels),
        "exact_wdl": copy.deepcopy(labels),
        "loss_mix": {"teacher_score": 0.8, "game_outcome": 0.1, "exact_wdl": 0.1},
        "missing_label_policy": "renormalize_available_components_per_sample",
        "calibration_source": "train_only",
        "test_used": False,
    }
    weighting = {
        "source_game_equal_weight": True,
        "position_weighting": "uniform_within_source_game",
        "phase_weights": {"13_to_16": 1.0, "9_to_12": 1.0, "5_to_8": 1.0},
        "exact_wdl_multiplier": 1.0,
        "selection_source": "train_only",
    }
    optimizer = {
        "name": "AdamW",
        "learning_rate": 0.001,
        "weight_decay": 0.0001,
        "batch_size": 64,
        "max_epochs": 20,
        "schedule": {"kind": "constant", "warmup_epochs": 1},
    }
    reproducibility = {
        "seeds": [20260828, 20260829],
        "deterministic_algorithms": True,
        "deterministic_resume_required": True,
        "checkpoint_checksum": "sha256",
        "dataloader_workers": 0,
        "dependencies": {
            "python": "3.14.0",
            "numpy": "2.3.5",
            "torch": "2.9.1+cu130",
        },
        "target_cpu": "AMD Ryzen 5 5600H",
    }
    learning_curve = {
        "sizes": [25_000, 50_000, 75_000, "all"],
        "same_split": True,
        "predeclared": True,
        "selection_source": "train_only",
    }
    checkpoint = {
        "selection_split": "validation",
        "metric": "validation_loss",
        "mode": "min",
        "early_stop_patience": 5,
        "min_delta": 0.0,
        "restore_best": True,
        "test_used": False,
    }
    return {
        "evidence": evidence,
        "dataset": dataset,
        "targets": targets,
        "weighting": weighting,
        "optimizer": optimizer,
        "reproducibility": reproducibility,
        "learning_curve": learning_curve,
        "checkpoint": checkpoint,
        "trainer_source_sha256": sha("5"),
        "trainer_fixture_sha256": sha("6"),
    }


def build_contract() -> dict:
    return freezer.freeze_contract(**sample_inputs())


class TrainerContractFreezerTests(unittest.TestCase):
    def test_cli_freezes_canonical_contract_from_outside_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs.json"
            inputs.write_bytes(
                (
                    json.dumps(
                    sample_inputs(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            output = root / "contract.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(freezer.__file__).resolve()),
                    "--inputs",
                    str(inputs),
                    "--output",
                    str(output),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                output.read_bytes(),
                freezer.canonical_contract_bytes(build_contract()),
            )

    def test_freezer_supplies_locked_sections_and_never_test_data(self):
        contract = build_contract()
        self.assertEqual(contract["format"], gate.CONTRACT_FORMAT)
        self.assertEqual(contract["kind"], "first-float-nnue-v1")
        self.assertEqual(contract["status"], "FROZEN")
        self.assertEqual(contract["feature_spec"], freezer.feature_spec_payload())
        self.assertEqual(contract["network"], freezer.LOCKED_NETWORK)
        self.assertFalse(contract["dataset"]["test_rows_included"])
        self.assertFalse(contract["dataset"]["test_game_ids_included"])
        self.assertFalse(contract["targets"]["test_used"])
        self.assertEqual(
            contract["targets"]["missing_label_policy"],
            "renormalize_available_components_per_sample",
        )
        self.assertEqual(contract["sealed_test_policy"]["labels_opened"], False)
        self.assertTrue(contract["authorization_policy"]["training_requires_this_gate_pass"])

    def test_repeated_freeze_is_byte_identical(self):
        first = freezer.canonical_contract_bytes(build_contract())
        second = freezer.canonical_contract_bytes(build_contract())
        self.assertEqual(first, second)
        self.assertEqual(
            hashlib.sha256(first).hexdigest().upper(),
            hashlib.sha256(second).hexdigest().upper(),
        )

    def test_freezer_deep_copies_train_only_choices(self):
        choices = sample_inputs()
        contract = freezer.freeze_contract(**choices)
        choices["targets"]["teacher_score"]["clip_cp"] = 99
        choices["optimizer"]["schedule"]["kind"] = "changed"
        self.assertEqual(contract["targets"]["teacher_score"]["clip_cp"], 2_000)
        self.assertEqual(contract["optimizer"]["schedule"]["kind"], "constant")

    def test_evidence_keys_and_hashes_fail_closed(self):
        choices = sample_inputs()
        choices["evidence"]["unexpected"] = sha("7")
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["evidence"]["analysis_set_sha256"] = sha("a")
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["evidence"]["development_manifest_sha256"] = sha("8")
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

    def test_dataset_rejects_extra_fields_and_bool_counts(self):
        choices = sample_inputs()
        choices["dataset"]["sealed_test_games"] = 1
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["dataset"]["train_games"] = True
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

    def test_target_and_weighting_leakage_fail_closed(self):
        choices = sample_inputs()
        choices["targets"]["test_used"] = True
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["targets"]["missing_label_policy"] = "silently_zero_missing"
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["weighting"]["selection_source"] = "test_only"
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

    def test_optimizer_and_learning_curve_are_explicit_and_train_only(self):
        choices = sample_inputs()
        choices["optimizer"]["schedule"] = {"test_metric": "forbidden"}
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["optimizer"]["schedule"] = {
            "kind": "validation_plateau",
            "warmup_epochs": 1,
        }
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["learning_curve"]["sizes"] = [50_000, 25_000, "all"]
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

    def test_reproducibility_requires_multiple_pinned_seeds_and_locked_host(self):
        choices = sample_inputs()
        choices["reproducibility"]["seeds"] = [1]
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

    def test_executable_first_trainer_choices_are_locked(self):
        mutations = (
            ("optimizer", "name", "SGD"),
            ("teacher_score", "normalization_kind", "linear_clip"),
            ("teacher_score", "loss", "mse"),
            ("game_outcome", "loss", "cross_entropy"),
            ("weighting", "position_weighting", "custom"),
            ("checkpoint", "mode", "max"),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                choices = sample_inputs()
                if section in {"teacher_score", "game_outcome"}:
                    choices["targets"][section][key] = value
                else:
                    choices[section][key] = value
                with self.assertRaises(freezer.ContractFreezeError):
                    freezer.freeze_contract(**choices)

        choices = sample_inputs()
        choices["reproducibility"]["target_cpu"] = "other host"
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.freeze_contract(**choices)

    def test_output_path_guard_and_locked_write(self):
        contract = build_contract()
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.write_frozen_contract(
                freezer.ROOT / "scratch" / "contract.json", contract
            )
        with self.assertRaises(freezer.ContractFreezeError):
            freezer.write_frozen_contract(
                freezer.ROOT / "build" / "nnue_scaling_full_v1" / "contract.json",
                contract,
            )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            written = freezer.write_frozen_contract(path, contract)
            self.assertEqual(Path(written), path.resolve())
            self.assertEqual(path.read_bytes(), freezer.canonical_contract_bytes(contract))
            freezer.write_frozen_contract(path, contract)
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(freezer.ContractFreezeError):
                freezer.write_frozen_contract(path, contract)

    def test_static_policy_cannot_become_strength_or_training_evidence(self):
        contract = build_contract()
        self.assertEqual(
            contract["external_regressions"],
            {"report_only": True, "hyperparameter_selection": False},
        )
        self.assertFalse(contract["authorization_policy"]["playing_code_changed"])
        self.assertFalse(contract["authorization_policy"]["model_already_trained"])
        self.assertTrue(contract["sealed_test_policy"]["model_selection_forbidden"])


if __name__ == "__main__":
    unittest.main()
