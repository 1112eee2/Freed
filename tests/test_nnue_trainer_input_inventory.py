import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scratch import nnue_scaling_final_audit as final_audit
from scratch import nnue_trainer_contract_gate as contract_gate
from scratch import nnue_trainer_input_inventory as inventory
from scratch.nnue_quiet_leaf_acquire import encoded_json


TRAIN_ID = "0000000000000001"
VALIDATION_ID = "0000000000000002"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded_json(payload), encoding="utf-8")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def game(game_id: str, split: str, marker: str) -> dict:
    return {
        "game_id": game_id,
        "sha256": marker * 64,
        "selection_sha256": chr(ord(marker) + 1) * 64,
        "selected_positions": 10,
        "split": split,
    }


def fixture_payloads() -> tuple[dict, dict, dict]:
    train = game(TRAIN_ID, "train", "1")
    validation = game(VALIDATION_ID, "validation", "4")
    analysis_hashes = {
        f"{TRAIN_ID}.analysis.json": "7" * 64,
        f"{VALIDATION_ID}.analysis.json": "8" * 64,
    }
    analysis_set_sha = contract_gate._analysis_set_sha256(
        analysis_hashes.items()
    )
    development = {
        "kind": "development-selection-manifest",
        "split_before_sampling": True,
        "games": [validation, train],
        "games_by_split": {"train": 1, "validation": 1},
        "selected_by_split": {"train": 10, "validation": 10},
    }
    audit = {
        "verdict": "PASS",
        "trainer_authorized_by_this_artifact": False,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "development_manifest_sha256": (
            inventory.EXPECTED_DEVELOPMENT_MANIFEST_SHA256
        ),
        "analysis_set_sha256": analysis_set_sha,
        "coverage": {
            "train": {"games": 1, "selected": 10, "eligible": 8},
            "validation": {"games": 1, "selected": 10, "eligible": 7},
        },
    }
    return development, analysis_hashes, audit


class TrainerInputInventoryTests(unittest.TestCase):
    def build(self, development: dict, hashes: dict, audit: dict) -> dict:
        with mock.patch.object(inventory, "EXPECTED_DEVELOPMENT_GAMES", 2):
            return inventory.build_inventory_payloads(
                development_manifest=development,
                analysis_hashes=hashes,
                final_audit_payload=audit,
            )

    def test_builds_exact_sorted_inventories_and_reconstructs_analysis_set(self):
        development, hashes, audit = fixture_payloads()
        result = self.build(development, hashes, audit)
        self.assertEqual(set(result), {"train", "validation"})
        self.assertEqual(result["train"]["games"][0]["game_id"], TRAIN_ID)
        self.assertEqual(
            result["validation"]["games"][0]["game_id"], VALIDATION_ID
        )
        self.assertEqual(result["train"]["format"], inventory.FORMAT)
        combined = [
            (row["analysis_file"], row["analysis_sha256"])
            for split in ("train", "validation")
            for row in result[split]["games"]
        ]
        self.assertEqual(
            contract_gate._analysis_set_sha256(combined),
            audit["analysis_set_sha256"],
        )

    def test_preserves_games_with_zero_positions_after_global_dedup(self):
        development, hashes, audit = fixture_payloads()
        zero_id = "0000000000000003"
        zero_game = game(zero_id, "train", "7")
        zero_game["selected_positions"] = 0
        development["games"].append(zero_game)
        development["games_by_split"]["train"] = 2
        hashes[f"{zero_id}.analysis.json"] = "B" * 64
        audit["analysis_set_sha256"] = contract_gate._analysis_set_sha256(
            hashes.items()
        )
        audit["coverage"]["train"]["games"] = 2

        with mock.patch.object(inventory, "EXPECTED_DEVELOPMENT_GAMES", 3):
            result = inventory.build_inventory_payloads(
                development_manifest=development,
                analysis_hashes=hashes,
                final_audit_payload=audit,
            )

        rows = {row["game_id"]: row for row in result["train"]["games"]}
        self.assertEqual(rows[zero_id]["selected_positions"], 0)

    def test_generated_payloads_match_contract_gate_schema(self):
        development, hashes, audit = fixture_payloads()
        result = self.build(development, hashes, audit)
        development_games = {
            row["game_id"]: row for row in development["games"]
        }
        for split in ("train", "validation"):
            payload = result[split]
            snapshot = contract_gate.JsonSnapshot(
                Path(f"{split}.json"),
                payload,
                encoded_json(payload).encode("utf-8"),
                "0" * 64,
            )
            ids, _ = contract_gate._validate_inventory(
                snapshot,
                expected_split=split,
                development_games=development_games,
                analysis_set_sha256=audit["analysis_set_sha256"],
            )
            self.assertEqual(len(ids), 1)

    def test_rejects_missing_or_extra_coordinator_analysis(self):
        development, hashes, audit = fixture_payloads()
        hashes.pop(f"{VALIDATION_ID}.analysis.json")
        with self.assertRaisesRegex(inventory.InventoryBuildError, "exact set"):
            self.build(development, hashes, audit)

    def test_rejects_non_development_split(self):
        development, hashes, audit = fixture_payloads()
        development["games"][0]["split"] = "test"
        with self.assertRaisesRegex(inventory.InventoryBuildError, "non-development"):
            self.build(development, hashes, audit)

    def test_rejects_final_audit_coverage_drift(self):
        development, hashes, audit = fixture_payloads()
        audit["coverage"]["train"]["selected"] = 9
        with self.assertRaisesRegex(inventory.InventoryBuildError, "coverage differs"):
            self.build(development, hashes, audit)

    def test_pair_write_reproduces_and_preflights_both_outputs(self):
        development, hashes, audit = fixture_payloads()
        payloads = self.build(development, hashes, audit)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = root / "train.json"
            validation = root / "validation.json"
            inventory.write_inventory_pair(
                train_path=train,
                validation_path=validation,
                inventories=payloads,
            )
            first = (file_sha(train), file_sha(validation))
            inventory.write_inventory_pair(
                train_path=train,
                validation_path=validation,
                inventories=payloads,
            )
            self.assertEqual(first, (file_sha(train), file_sha(validation)))

            guarded = root / "guarded"
            guarded.mkdir()
            missing_train = guarded / "train.json"
            bad_validation = guarded / "validation.json"
            bad_validation.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(inventory.InventoryBuildError, "differs"):
                inventory.write_inventory_pair(
                    train_path=missing_train,
                    validation_path=bad_validation,
                    inventories=payloads,
                )
            self.assertFalse(missing_train.exists())

    def test_build_from_paths_never_opens_analysis_or_sealed_files(self):
        development, hashes, audit = fixture_payloads()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            work.mkdir()
            summary_path = work / "preflight_summary.json"
            write_json(summary_path, {"synthetic": True})
            audit["coordinator_summary_sha256"] = file_sha(summary_path)
            audit_path = root / "final_audit.json"
            write_json(audit_path, audit)
            sealed = work / "sealed_test_selection_manifest.json"
            sealed.write_text("must not be opened", encoding="utf-8")
            analysis = work / "analyses" / f"{TRAIN_ID}.analysis.json"
            analysis.parent.mkdir()
            analysis.write_text("must not be opened", encoding="utf-8")
            train_output = root / "train_inventory.json"
            validation_output = root / "validation_inventory.json"
            original_read_bytes = Path.read_bytes
            reads = []

            def tracked(path_self):
                resolved = path_self.resolve()
                reads.append(resolved)
                if resolved in {sealed.resolve(), analysis.resolve()}:
                    raise AssertionError("forbidden file was opened")
                return original_read_bytes(path_self)

            with (
                mock.patch.object(Path, "read_bytes", tracked),
                mock.patch.object(inventory, "EXPECTED_DEVELOPMENT_GAMES", 2),
                mock.patch.object(
                    contract_gate,
                    "_validate_final_audit",
                    return_value=audit["coverage"],
                ),
                mock.patch.object(
                    final_audit,
                    "verify_locked_sources",
                    return_value=({}, {}, {}, {}, development),
                ),
                mock.patch.object(
                    final_audit,
                    "validate_final_summary",
                    return_value=hashes,
                ),
            ):
                report = inventory.build_from_paths(
                    work_dir=work,
                    final_audit_path=audit_path,
                    train_output=train_output,
                    validation_output=validation_output,
                )
            self.assertEqual(report["verdict"], "PASS")
            self.assertFalse(report["training_authorized_by_this_artifact"])
            self.assertEqual(report["analysis_payloads_read"], 0)
            self.assertFalse(report["sealed_test_manifest_read"])
            self.assertNotIn(sealed.resolve(), reads)
            self.assertNotIn(analysis.resolve(), reads)

    def test_rejects_output_inside_locked_run_before_reading_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            work.mkdir()
            missing_audit = root / "missing_audit.json"
            with self.assertRaisesRegex(
                inventory.InventoryBuildError,
                "outside the locked run directory",
            ):
                inventory.build_from_paths(
                    work_dir=work,
                    final_audit_path=missing_audit,
                    train_output=work / "train_inventory.json",
                    validation_output=root / "validation_inventory.json",
                )
            self.assertFalse((work / "train_inventory.json").exists())

    def test_cli_imports_from_outside_repo(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(
                    inventory.ROOT
                    / "scratch"
                    / "nnue_trainer_input_inventory.py"
                ),
                "--help",
            ],
            cwd=Path(tempfile.gettempdir()),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--validation-output", result.stdout)


if __name__ == "__main__":
    unittest.main()
