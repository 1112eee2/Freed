from contextlib import redirect_stdout
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scratch import nnue_float_trainer as trainer
from scratch import nnue_trainer_contract_freezer as freezer
from scratch import nnue_trainer_contract_gate as gate
from scratch.nnue_quiet_leaf_acquire import encoded_json
from tests.test_nnue_scaling_final_audit import (
    TRAIN_POSITION,
    VALIDATION_POSITION,
    game_and_analysis,
    position as analysis_position,
)
from tests.test_nnue_trainer_contract_freezer import sample_inputs


def write_canonical(path: Path, payload: dict) -> None:
    path.write_text(encoded_json(payload), encoding="utf-8")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def pass_authorization(**overrides: object) -> dict:
    payload = {
        "format": gate.AUTHORIZATION_FORMAT,
        "kind": "first-float-trainer-authorization",
        "verdict": "PASS",
        "training_authorized": True,
        "playing_code_changed": False,
        "model_trained": False,
        "accepted_library_sha256": gate.EXPECTED_ACCEPTED_SHA256,
        "ruleset_sha256": "A" * 64,
        "contract_sha256": "A" * 64,
        "trainer_contract_reproduced_byte_identical": True,
        "final_data_audit_sha256": "B" * 64,
        "final_data_audit_reproduced_byte_identical": True,
        "development_manifest_sha256": "C" * 64,
        "analysis_set_sha256": "D" * 64,
        "train_inventory_sha256": "E" * 64,
        "validation_inventory_sha256": "F" * 64,
        "full_suite_attestation_sha256": "1" * 64,
        "trainer_preflight_sha256": "2" * 64,
        "train_games": 1,
        "validation_games": 1,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "sealed_test_labels_opened": False,
        "gates": {key: True for key in gate.AUTHORIZATION_GATE_KEYS},
        "next_action": "run only the frozen first float trainer",
    }
    payload.update(overrides)
    return payload


def bound_authorization(
    contract_payload: dict,
    contract_path: Path,
    train_inventory_path: Path,
    validation_inventory_path: Path,
    **overrides: object,
) -> dict:
    evidence = contract_payload["evidence"]
    dataset = contract_payload["dataset"]
    bindings = {
        "ruleset_sha256": file_sha(gate.RULESET),
        "contract_sha256": file_sha(contract_path),
        "final_data_audit_sha256": evidence["final_data_audit_sha256"],
        "development_manifest_sha256": evidence[
            "development_manifest_sha256"
        ],
        "analysis_set_sha256": evidence["analysis_set_sha256"],
        "full_suite_attestation_sha256": evidence[
            "full_suite_attestation_sha256"
        ],
        "train_inventory_sha256": file_sha(train_inventory_path),
        "validation_inventory_sha256": file_sha(validation_inventory_path),
        "train_games": dataset["train_games"],
        "validation_games": dataset["validation_games"],
    }
    bindings.update(overrides)
    return pass_authorization(**bindings)


def inventory_payload(split: str, game_id: str, selected: int = 10) -> dict:
    return {
        "format": gate.INVENTORY_FORMAT,
        "kind": "trainer-input-inventory",
        "split": split,
        "development_manifest_sha256": gate.EXPECTED_DEVELOPMENT_MANIFEST_SHA256,
        "analysis_set_sha256": "C" * 64,
        "games": [
            {
                "game_id": game_id,
                "game_sha256": "A" * 64,
                "selection_sha256": "B" * 64,
                "selected_positions": selected,
                "analysis_file": f"{game_id}.analysis.json",
                "analysis_sha256": "D" * 64,
            }
        ],
    }


def write_bound_fixture(root: Path) -> dict[str, Path]:
    paths = {
        "authorization": root / "authorization.json",
        "contract": root / "contract.json",
        "train": root / "train.json",
        "validation": root / "validation.json",
    }
    train_id = "0000000000000001"
    validation_id = "0000000000000002"
    write_canonical(paths["train"], inventory_payload("train", train_id))
    write_canonical(
        paths["validation"],
        inventory_payload("validation", validation_id),
    )
    choices = sample_inputs()
    choices["trainer_source_sha256"] = file_sha(Path(trainer.__file__))
    choices["evidence"]["train_inventory_sha256"] = file_sha(paths["train"])
    choices["evidence"]["validation_inventory_sha256"] = file_sha(
        paths["validation"]
    )
    choices["dataset"].update(
        {
            "train_games": 1,
            "validation_games": 1,
            "train_selected_rows": 10,
            "validation_selected_rows": 10,
            "train_game_ids_sha256": gate._game_id_set_sha256({train_id}),
            "validation_game_ids_sha256": gate._game_id_set_sha256(
                {validation_id}
            ),
        }
    )
    contract_payload = freezer.freeze_contract(**choices)
    write_canonical(paths["contract"], contract_payload)
    write_canonical(
        paths["authorization"],
        bound_authorization(
            contract_payload,
            paths["contract"],
            paths["train"],
            paths["validation"],
        ),
    )
    return paths


def write_bound_analysis_fixture(
    root: Path,
    *,
    wrong_train_game_id: bool = False,
    missing_train_teacher: bool = False,
    mismatched_train_teacher_search: bool = False,
    dependency_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Path], Path]:
    paths = {
        "authorization": root / "authorization.json",
        "contract": root / "contract.json",
        "train": root / "train.json",
        "validation": root / "validation.json",
    }
    analyses = root / "analyses"
    analyses.mkdir()
    rows = {}
    for split, game_id in (
        ("train", "0000000000000001"),
        ("validation", "0000000000000002"),
    ):
        game, analysis = game_and_analysis(
            game_id,
            accepted_library=gate.ACCEPTED_LIBRARY,
            split=split,
            position_text=(
                TRAIN_POSITION if split == "train" else VALIDATION_POSITION
            ),
        )
        if split == "train":
            analysis["positions"].append(
                analysis_position(
                    "B:BM21,22,25,27:BK30:RM5,7,8,11:RK2",
                    split="train",
                    ply=6,
                )
            )
        if split == "train" and wrong_train_game_id:
            analysis["game_id"] = "0000000000000003"
        if split == "train" and missing_train_teacher:
            analysis["positions"][0]["teacher_score"] = None
        if split == "train" and mismatched_train_teacher_search:
            analysis["positions"][0]["teacher_score"] += 1
        analysis_path = analyses / f"{game_id}.analysis.json"
        write_canonical(analysis_path, analysis)
        inventory = inventory_payload(
            split,
            game_id,
            selected=len(analysis["positions"]),
        )
        inventory["games"][0].update(
            {
                "game_sha256": game["sha256"],
                "selection_sha256": game["selection_sha256"],
                "analysis_sha256": file_sha(analysis_path),
            }
        )
        write_canonical(paths[split], inventory)
        rows[split] = game_id

    choices = sample_inputs()
    choices["trainer_source_sha256"] = file_sha(Path(trainer.__file__))
    choices["evidence"]["train_inventory_sha256"] = file_sha(paths["train"])
    choices["evidence"]["validation_inventory_sha256"] = file_sha(
        paths["validation"]
    )
    choices["dataset"].update(
        {
            "train_games": 1,
            "validation_games": 1,
            "train_selected_rows": 2,
            "validation_selected_rows": 1,
            "train_eligible_rows": 2,
            "validation_eligible_rows": 1,
            "train_game_ids_sha256": gate._game_id_set_sha256(
                {rows["train"]}
            ),
            "validation_game_ids_sha256": gate._game_id_set_sha256(
                {rows["validation"]}
            ),
        }
    )
    choices["learning_curve"]["sizes"] = [1, "all"]
    choices["optimizer"]["batch_size"] = 2
    choices["optimizer"]["max_epochs"] = 2
    if dependency_overrides:
        choices["reproducibility"]["dependencies"].update(
            dependency_overrides
        )
    contract_payload = freezer.freeze_contract(**choices)
    write_canonical(paths["contract"], contract_payload)
    write_canonical(
        paths["authorization"],
        bound_authorization(
            contract_payload,
            paths["contract"],
            paths["train"],
            paths["validation"],
        ),
    )
    return paths, analyses


class FloatTrainerAuthorizationTests(unittest.TestCase):
    def test_cli_reports_completed_training_verdict(self) -> None:
        stdout = io.StringIO()
        argv = [
            str(Path(trainer.__file__)),
            "--authorization",
            "authorization.json",
            "--contract",
            "contract.json",
            "--train-inventory",
            "train.json",
            "--validation-inventory",
            "validation.json",
            "--output-directory",
            "model-output",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                trainer,
                "run_training",
                return_value={"verdict": "PASS", "runs": [{}, {}]},
            ),
            patch.object(gate, "sha256", return_value="A" * 64),
            redirect_stdout(stdout),
        ):
            trainer.main()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["runs"], 2)

    def test_cli_imports_from_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(trainer.__file__).resolve()),
                    "--help",
                ],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--authorization", result.stdout)
        self.assertIn("--output-directory", result.stdout)

    def test_inventory_allows_zero_selected_game_bound_to_empty_analysis(self) -> None:
        first_id = "0000000000000001"
        zero_id = "0000000000000003"
        payload = inventory_payload("train", first_id)
        zero_row = inventory_payload("train", zero_id, selected=0)["games"][0]
        payload["games"].append(zero_row)
        authorization = pass_authorization(
            development_manifest_sha256=payload["development_manifest_sha256"],
            analysis_set_sha256=payload["analysis_set_sha256"],
        )
        contract = {
            "dataset": {
                "train_games": 2,
                "train_selected_rows": 10,
                "train_game_ids_sha256": gate._game_id_set_sha256(
                    {first_id, zero_id}
                ),
            }
        }

        ids = trainer._validate_inventory_content(
            payload,
            split="train",
            authorization=authorization,
            contract=contract,
        )

        self.assertEqual(ids, {first_id, zero_id})

    def test_unauthorized_run_fails_before_dataset_inputs_are_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            write_canonical(
                authorization,
                {
                    "format": gate.AUTHORIZATION_FORMAT,
                    "kind": "first-float-trainer-authorization",
                    "verdict": "FAIL",
                    "training_authorized": False,
                },
            )
            output = root / "model-output"

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "authorization",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=root / "must-not-open-contract.json",
                    train_inventory_path=root / "must-not-open-train.json",
                    validation_inventory_path=root / "must-not-open-validation.json",
                    output_directory=output,
                )

            self.assertFalse(output.exists())

    def test_pass_claim_without_gate_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            write_canonical(
                authorization,
                {
                    "format": gate.AUTHORIZATION_FORMAT,
                    "kind": "first-float-trainer-authorization",
                    "verdict": "PASS",
                    "training_authorized": True,
                },
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "authorization artifact is incomplete",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=root / "must-not-open-contract.json",
                    train_inventory_path=root / "must-not-open-train.json",
                    validation_inventory_path=root / "must-not-open-validation.json",
                    output_directory=root / "model-output",
                )

    def test_contract_hash_mismatch_fails_before_inventories_are_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            write_canonical(authorization, pass_authorization())
            write_canonical(contract, {"not": "the authorized contract"})

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "contract binding differs",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=root / "must-not-open-train.json",
                    validation_inventory_path=root / "must-not-open-validation.json",
                    output_directory=root / "model-output",
                )

    def test_train_inventory_hash_mismatch_fails_before_validation_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            train_inventory = root / "train.json"
            write_canonical(contract, {"frozen": True})
            write_canonical(train_inventory, {"split": "train"})
            write_canonical(
                authorization,
                pass_authorization(contract_sha256=file_sha(contract)),
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "train inventory binding differs",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=train_inventory,
                    validation_inventory_path=root / "must-not-open-validation.json",
                    output_directory=root / "model-output",
                )

    def test_contract_bound_to_different_trainer_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            train_inventory = root / "train.json"
            validation_inventory = root / "validation.json"
            choices = sample_inputs()
            choices["trainer_source_sha256"] = "A" * 64
            write_canonical(contract, freezer.freeze_contract(**choices))
            write_canonical(train_inventory, {"split": "train"})
            write_canonical(validation_inventory, {"split": "validation"})
            write_canonical(
                authorization,
                pass_authorization(
                    contract_sha256=file_sha(contract),
                    train_inventory_sha256=file_sha(train_inventory),
                    validation_inventory_sha256=file_sha(validation_inventory),
                ),
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "trainer source binding differs",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=train_inventory,
                    validation_inventory_path=validation_inventory,
                    output_directory=root / "model-output",
                )

    def test_current_accepted_control_is_revalidated_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            train_inventory = root / "train.json"
            validation_inventory = root / "validation.json"
            choices = sample_inputs()
            choices["trainer_source_sha256"] = file_sha(Path(trainer.__file__))
            write_canonical(contract, freezer.freeze_contract(**choices))
            write_canonical(train_inventory, {"split": "train"})
            write_canonical(validation_inventory, {"split": "validation"})
            write_canonical(
                authorization,
                pass_authorization(
                    accepted_library_sha256="A" * 64,
                    contract_sha256=file_sha(contract),
                    train_inventory_sha256=file_sha(train_inventory),
                    validation_inventory_sha256=file_sha(validation_inventory),
                ),
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "accepted control binding differs",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=train_inventory,
                    validation_inventory_path=validation_inventory,
                    output_directory=root / "model-output",
                )

    def test_contract_evidence_must_match_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            train_inventory = root / "train.json"
            validation_inventory = root / "validation.json"
            choices = sample_inputs()
            choices["trainer_source_sha256"] = file_sha(Path(trainer.__file__))
            write_canonical(contract, freezer.freeze_contract(**choices))
            write_canonical(train_inventory, {"split": "train"})
            write_canonical(validation_inventory, {"split": "validation"})
            write_canonical(
                authorization,
                pass_authorization(
                    ruleset_sha256=file_sha(gate.RULESET),
                    contract_sha256=file_sha(contract),
                    train_inventory_sha256=file_sha(train_inventory),
                    validation_inventory_sha256=file_sha(validation_inventory),
                ),
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "contract evidence differs from authorization",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=train_inventory,
                    validation_inventory_path=validation_inventory,
                    output_directory=root / "model-output",
                )

    def test_contract_dataset_counts_must_match_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            train_inventory = root / "train.json"
            validation_inventory = root / "validation.json"
            write_canonical(train_inventory, {"split": "train"})
            write_canonical(validation_inventory, {"split": "validation"})
            choices = sample_inputs()
            choices["trainer_source_sha256"] = file_sha(Path(trainer.__file__))
            choices["evidence"]["train_inventory_sha256"] = file_sha(
                train_inventory
            )
            choices["evidence"]["validation_inventory_sha256"] = file_sha(
                validation_inventory
            )
            contract_payload = freezer.freeze_contract(**choices)
            write_canonical(contract, contract_payload)
            write_canonical(
                authorization,
                bound_authorization(
                    contract_payload,
                    contract,
                    train_inventory,
                    validation_inventory,
                    train_games=contract_payload["dataset"]["train_games"] + 1,
                ),
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "dataset declaration differs from authorization",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=train_inventory,
                    validation_inventory_path=validation_inventory,
                    output_directory=root / "model-output",
                )

    def test_mislabeled_train_inventory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization = root / "authorization.json"
            contract = root / "contract.json"
            train_inventory = root / "train.json"
            validation_inventory = root / "validation.json"
            train_id = "0000000000000001"
            validation_id = "0000000000000002"
            write_canonical(
                train_inventory,
                inventory_payload("validation", train_id),
            )
            write_canonical(
                validation_inventory,
                inventory_payload("validation", validation_id),
            )
            choices = sample_inputs()
            choices["trainer_source_sha256"] = file_sha(Path(trainer.__file__))
            choices["evidence"]["train_inventory_sha256"] = file_sha(
                train_inventory
            )
            choices["evidence"]["validation_inventory_sha256"] = file_sha(
                validation_inventory
            )
            choices["dataset"].update(
                {
                    "train_games": 1,
                    "validation_games": 1,
                    "train_selected_rows": 10,
                    "validation_selected_rows": 10,
                    "train_game_ids_sha256": gate._game_id_set_sha256(
                        {train_id}
                    ),
                    "validation_game_ids_sha256": gate._game_id_set_sha256(
                        {validation_id}
                    ),
                }
            )
            contract_payload = freezer.freeze_contract(**choices)
            write_canonical(contract, contract_payload)
            write_canonical(
                authorization,
                bound_authorization(
                    contract_payload,
                    contract,
                    train_inventory,
                    validation_inventory,
                ),
            )

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "train inventory content is invalid",
            ):
                trainer.run_training(
                    authorization_path=authorization,
                    contract_path=contract,
                    train_inventory_path=train_inventory,
                    validation_inventory_path=validation_inventory,
                    output_directory=root / "model-output",
                )

    def test_existing_output_directory_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_bound_fixture(root)
            output = root / "model-output"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("untouched", encoding="utf-8")

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "output directory must be new",
            ):
                trainer.run_training(
                    authorization_path=paths["authorization"],
                    contract_path=paths["contract"],
                    train_inventory_path=paths["train"],
                    validation_inventory_path=paths["validation"],
                    output_directory=output,
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")

    def test_protected_output_tree_is_rejected_before_analysis_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_bound_fixture(Path(directory))
            protected_output = gate.ROOT / "scratch" / "must-not-create-model"

            with self.assertRaisesRegex(
                trainer.FloatTrainerError,
                "protected tree",
            ):
                trainer.run_training(
                    authorization_path=paths["authorization"],
                    contract_path=paths["contract"],
                    train_inventory_path=paths["train"],
                    validation_inventory_path=paths["validation"],
                    output_directory=protected_output,
                )

            self.assertFalse(protected_output.exists())

    def test_missing_bound_analysis_fails_before_output_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_bound_fixture(root)
            output = root / "model-output"

            with patch.object(
                trainer,
                "ANALYSES_DIRECTORY",
                root / "analyses",
            ):
                with self.assertRaisesRegex(
                    trainer.FloatTrainerError,
                    "train analysis file is missing",
                ):
                    trainer.run_training(
                        authorization_path=paths["authorization"],
                        contract_path=paths["contract"],
                        train_inventory_path=paths["train"],
                        validation_inventory_path=paths["validation"],
                        output_directory=output,
                    )

            self.assertFalse(output.exists())

    def test_analysis_game_id_must_match_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(
                root,
                wrong_train_game_id=True,
            )

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                with self.assertRaisesRegex(
                    trainer.FloatTrainerError,
                    "train analysis content is invalid",
                ):
                    trainer.run_training(
                        authorization_path=paths["authorization"],
                        contract_path=paths["contract"],
                        train_inventory_path=paths["train"],
                        validation_inventory_path=paths["validation"],
                        output_directory=root / "model-output",
                    )

    def test_eligible_position_requires_teacher_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(
                root,
                missing_train_teacher=True,
            )

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                with self.assertRaisesRegex(
                    trainer.FloatTrainerError,
                    "train position content is invalid",
                ):
                    trainer.run_training(
                        authorization_path=paths["authorization"],
                        contract_path=paths["contract"],
                        train_inventory_path=paths["train"],
                        validation_inventory_path=paths["validation"],
                        output_directory=root / "model-output",
                    )

    def test_teacher_target_must_match_final_bound_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(
                root,
                mismatched_train_teacher_search=True,
            )

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                with self.assertRaisesRegex(
                    trainer.FloatTrainerError,
                    "train position content is invalid",
                ):
                    trainer.run_training(
                        authorization_path=paths["authorization"],
                        contract_path=paths["contract"],
                        train_inventory_path=paths["train"],
                        validation_inventory_path=paths["validation"],
                        output_directory=root / "model-output",
                    )

    def test_authorized_synthetic_training_emits_bound_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(root)
            output = root / "model-output"

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                result = trainer.run_training(
                    authorization_path=paths["authorization"],
                    contract_path=paths["contract"],
                    train_inventory_path=paths["train"],
                    validation_inventory_path=paths["validation"],
                    output_directory=output,
                )

            self.assertEqual(result["verdict"], "PASS")
            self.assertTrue(result["model_trained"])
            self.assertEqual(result["train_eligible_rows"], 2)
            self.assertEqual(result["validation_eligible_rows"], 1)
            self.assertEqual(len(result["runs"]), 4)
            for run in result["runs"]:
                self.assertIn("train_metrics", run)
                self.assertIn("validation_metrics", run)
                self.assertIn("hce_teacher", run["validation_metrics"])
                self.assertIn(
                    "teacher_mae_improvement_vs_hce",
                    run["validation_metrics"],
                )
                self.assertIn("by_phase", run["validation_metrics"])
                self.assertIn("by_clock_bucket", run["validation_metrics"])
                self.assertTrue(
                    all("learning_rate" in row for row in run["history"])
                )
            self.assertTrue((output / "training_result.json").is_file())
            self.assertEqual(len(list(output.glob("*.model.json"))), 4)

    def test_runtime_dependency_drift_fails_before_model_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(
                root,
                dependency_overrides={"torch": "0.0.0-drift"},
            )
            output = root / "model-output"

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                with self.assertRaisesRegex(
                    trainer.FloatTrainerError,
                    "runtime dependencies differ from frozen contract",
                ):
                    trainer.run_training(
                        authorization_path=paths["authorization"],
                        contract_path=paths["contract"],
                        train_inventory_path=paths["train"],
                        validation_inventory_path=paths["validation"],
                        output_directory=output,
                    )

            self.assertFalse(output.exists())

    def test_authorized_synthetic_training_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(root)
            outputs = [root / "model-output-a", root / "model-output-b"]

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                results = [
                    trainer.run_training(
                        authorization_path=paths["authorization"],
                        contract_path=paths["contract"],
                        train_inventory_path=paths["train"],
                        validation_inventory_path=paths["validation"],
                        output_directory=output,
                    )
                    for output in outputs
                ]

            self.assertEqual(
                [run["model_sha256"] for run in results[0]["runs"]],
                [run["model_sha256"] for run in results[1]["runs"]],
            )
            self.assertEqual(
                file_sha(outputs[0] / "training_result.json"),
                file_sha(outputs[1] / "training_result.json"),
            )

    def test_checkpoint_resume_matches_uninterrupted_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, analyses = write_bound_analysis_fixture(root)
            resumed_output = root / "model-output-resumed"
            control_output = root / "model-output-control"
            checkpoints = 0

            def interrupt_once(staging_directory: Path, *_args) -> None:
                nonlocal checkpoints
                checkpoints += 1
                if checkpoints == 1:
                    raise trainer.FloatTrainerPaused(staging_directory)

            with patch.object(trainer, "ANALYSES_DIRECTORY", analyses):
                with patch.object(
                    trainer,
                    "_after_epoch_checkpoint",
                    side_effect=interrupt_once,
                ):
                    with self.assertRaises(trainer.FloatTrainerPaused) as raised:
                        trainer.run_training(
                            authorization_path=paths["authorization"],
                            contract_path=paths["contract"],
                            train_inventory_path=paths["train"],
                            validation_inventory_path=paths["validation"],
                            output_directory=resumed_output,
                        )
                staging = raised.exception.resume_directory
                self.assertTrue(staging.is_dir())
                self.assertFalse(resumed_output.exists())
                resumed = trainer.run_training(
                    authorization_path=paths["authorization"],
                    contract_path=paths["contract"],
                    train_inventory_path=paths["train"],
                    validation_inventory_path=paths["validation"],
                    output_directory=resumed_output,
                    resume_directory=staging,
                )
                control = trainer.run_training(
                    authorization_path=paths["authorization"],
                    contract_path=paths["contract"],
                    train_inventory_path=paths["train"],
                    validation_inventory_path=paths["validation"],
                    output_directory=control_output,
                )

            self.assertEqual(
                [run["model_sha256"] for run in resumed["runs"]],
                [run["model_sha256"] for run in control["runs"]],
            )
            self.assertEqual(
                file_sha(resumed_output / "training_result.json"),
                file_sha(control_output / "training_result.json"),
            )


if __name__ == "__main__":
    unittest.main()
