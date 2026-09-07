"""Build exact train/validation inventories after the final NNUE data audit.

The builder consumes only the reproduced final-audit artifact, the locked
development manifest, and the coordinator's final hash inventory.  It never
opens an analysis payload, the sealed-test selection manifest, or a test
analysis.  The active partial acquisition cannot satisfy its preconditions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scratch import nnue_scaling_final_audit as final_audit  # noqa: E402
from scratch import nnue_trainer_contract_gate as contract_gate  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    encoded_json,
    sha256,
    write_locked_json,
)


FORMAT = contract_gate.INVENTORY_FORMAT
KIND = "trainer-input-inventory"
EXPECTED_DEVELOPMENT_GAMES = final_audit.EXPECTED_DEVELOPMENT_GAMES
EXPECTED_DEVELOPMENT_MANIFEST_SHA256 = (
    final_audit.EXPECTED_DEVELOPMENT_MANIFEST_SHA256
)
DEFAULT_WORK_DIR = ROOT / "build" / "nnue_scaling_full_v1"


class InventoryBuildError(RuntimeError):
    """Raised when final evidence cannot produce exact trainer inventories."""


def _analysis_name(game_id: str) -> str:
    return f"{game_id}.analysis.json"


def _validate_game_row(game: object) -> dict:
    if not isinstance(game, dict):
        raise InventoryBuildError("development game row must be an object")
    required = {
        "game_id",
        "sha256",
        "selection_sha256",
        "selected_positions",
        "split",
    }
    if not required <= set(game):
        raise InventoryBuildError("development game row is missing bindings")
    game_id = game["game_id"]
    if (
        not isinstance(game_id, str)
        or not contract_gate.GAME_ID.fullmatch(game_id)
    ):
        raise InventoryBuildError("development game id is invalid")
    for key in ("sha256", "selection_sha256"):
        value = game[key]
        if (
            not isinstance(value, str)
            or not contract_gate.HEX_64.fullmatch(value)
        ):
            raise InventoryBuildError(f"development {key} is invalid: {game_id}")
    if (
        isinstance(game["selected_positions"], bool)
        or not isinstance(game["selected_positions"], int)
        or game["selected_positions"] < 0
    ):
        raise InventoryBuildError(f"selected-position count is invalid: {game_id}")
    if game["split"] not in {"train", "validation"}:
        raise InventoryBuildError(f"non-development split found: {game_id}")
    return game


def build_inventory_payloads(
    *,
    development_manifest: dict,
    analysis_hashes: Mapping[str, str],
    final_audit_payload: dict,
) -> dict[str, dict]:
    """Create both exact inventory payloads without reading analysis files."""

    if (
        final_audit_payload.get("verdict") != "PASS"
        or final_audit_payload.get("trainer_authorized_by_this_artifact")
        is not False
        or final_audit_payload.get("sealed_test_manifest_read") is not False
        or final_audit_payload.get("test_analysis_files_read") != 0
    ):
        raise InventoryBuildError("final audit is not an isolated PASS artifact")
    if (
        final_audit_payload.get("development_manifest_sha256")
        != EXPECTED_DEVELOPMENT_MANIFEST_SHA256
    ):
        raise InventoryBuildError("final audit development binding changed")
    analysis_set_sha256 = final_audit_payload.get("analysis_set_sha256")
    if (
        not isinstance(analysis_set_sha256, str)
        or not contract_gate.HEX_64.fullmatch(analysis_set_sha256)
    ):
        raise InventoryBuildError("final audit analysis-set SHA-256 is invalid")
    coverage = final_audit_payload.get("coverage")
    if not isinstance(coverage, dict):
        raise InventoryBuildError("final audit coverage is missing")

    if (
        development_manifest.get("kind") != "development-selection-manifest"
        or development_manifest.get("split_before_sampling") is not True
    ):
        raise InventoryBuildError("development manifest contract changed")
    games = development_manifest.get("games")
    if not isinstance(games, list) or len(games) != EXPECTED_DEVELOPMENT_GAMES:
        raise InventoryBuildError("development manifest game count changed")

    validated = []
    seen_ids = set()
    for raw_game in games:
        game = _validate_game_row(raw_game)
        game_id = game["game_id"]
        if game_id in seen_ids:
            raise InventoryBuildError(f"duplicate development game id: {game_id}")
        seen_ids.add(game_id)
        validated.append(game)

    expected_names = {_analysis_name(game["game_id"]) for game in validated}
    if set(analysis_hashes) != expected_names:
        raise InventoryBuildError("coordinator analysis inventory is not an exact set")
    for name, digest in analysis_hashes.items():
        if not isinstance(digest, str) or not contract_gate.HEX_64.fullmatch(digest):
            raise InventoryBuildError(f"invalid coordinator analysis SHA-256: {name}")
    if contract_gate._analysis_set_sha256(analysis_hashes.items()) != (
        analysis_set_sha256
    ):
        raise InventoryBuildError("coordinator hashes differ from final audit")

    rows = {"train": [], "validation": []}
    for game in sorted(validated, key=lambda item: item["game_id"]):
        name = _analysis_name(game["game_id"])
        rows[game["split"]].append(
            {
                "game_id": game["game_id"],
                "game_sha256": game["sha256"],
                "selection_sha256": game["selection_sha256"],
                "selected_positions": game["selected_positions"],
                "analysis_file": name,
                "analysis_sha256": analysis_hashes[name],
            }
        )

    split_counts = {split: len(split_rows) for split, split_rows in rows.items()}
    selected_counts = {
        split: sum(row["selected_positions"] for row in split_rows)
        for split, split_rows in rows.items()
    }
    if development_manifest.get("games_by_split") != split_counts:
        raise InventoryBuildError("development manifest split counts changed")
    if development_manifest.get("selected_by_split") != selected_counts:
        raise InventoryBuildError("development manifest selected counts changed")
    for split in ("train", "validation"):
        split_coverage = coverage.get(split)
        if (
            not isinstance(split_coverage, dict)
            or split_coverage.get("games") != split_counts[split]
            or split_coverage.get("selected") != selected_counts[split]
            or not isinstance(split_coverage.get("eligible"), int)
            or split_coverage["eligible"] <= 0
        ):
            raise InventoryBuildError(f"final audit {split} coverage differs")

    return {
        split: {
            "format": FORMAT,
            "kind": KIND,
            "split": split,
            "development_manifest_sha256": (
                EXPECTED_DEVELOPMENT_MANIFEST_SHA256
            ),
            "analysis_set_sha256": analysis_set_sha256,
            "games": rows[split],
        }
        for split in ("train", "validation")
    }


def write_inventory_pair(
    *,
    train_path: Path,
    validation_path: Path,
    inventories: Mapping[str, dict],
) -> None:
    """Preflight both locked outputs before creating either missing file."""

    outputs = {
        train_path.resolve(): inventories["train"],
        validation_path.resolve(): inventories["validation"],
    }
    if len(outputs) != 2:
        raise InventoryBuildError("train and validation outputs must differ")
    for path, payload in outputs.items():
        if path.exists() and path.read_text(encoding="utf-8") != encoded_json(payload):
            raise InventoryBuildError(f"locked inventory differs: {path}")
    for path, payload in outputs.items():
        write_locked_json(path, payload)


def build_from_paths(
    *,
    work_dir: Path,
    final_audit_path: Path,
    train_output: Path,
    validation_output: Path,
) -> dict:
    """Validate completed-run evidence and write the exact inventory pair."""

    work_dir = work_dir.resolve()
    output_paths = (train_output.resolve(), validation_output.resolve())
    for output_path in output_paths:
        if output_path.is_relative_to(work_dir):
            raise InventoryBuildError(
                "trainer inventory outputs must stay outside the locked run directory"
            )
    audit_snapshot = contract_gate.load_json_snapshot(final_audit_path)
    contract_gate._validate_final_audit(audit_snapshot)
    _, commitment, _, _, development = final_audit.verify_locked_sources(work_dir)
    summary_path = work_dir / "preflight_summary.json"
    if not summary_path.exists():
        raise InventoryBuildError("coordinator final PASS summary does not exist")
    summary, summary_sha256 = final_audit.load_json_bytes_with_sha256(summary_path)
    analysis_hashes = final_audit.validate_final_summary(summary, commitment)
    if audit_snapshot.payload.get("coordinator_summary_sha256") != summary_sha256:
        raise InventoryBuildError("final audit coordinator-summary binding changed")
    inventories = build_inventory_payloads(
        development_manifest=development,
        analysis_hashes=analysis_hashes,
        final_audit_payload=audit_snapshot.payload,
    )
    write_inventory_pair(
        train_path=train_output,
        validation_path=validation_output,
        inventories=inventories,
    )
    return {
        "format": "thai-makhos-nnue-trainer-input-inventory-build-v1",
        "kind": "development-only-trainer-inventory-build",
        "verdict": "PASS",
        "playing_code_changed": False,
        "model_trained": False,
        "training_authorized_by_this_artifact": False,
        "final_data_audit_sha256": audit_snapshot.sha256,
        "development_manifest_sha256": EXPECTED_DEVELOPMENT_MANIFEST_SHA256,
        "analysis_set_sha256": audit_snapshot.payload["analysis_set_sha256"],
        "train_inventory_sha256": sha256(train_output.resolve()),
        "validation_inventory_sha256": sha256(validation_output.resolve()),
        "train_games": len(inventories["train"]["games"]),
        "validation_games": len(inventories["validation"]["games"]),
        "analysis_payloads_read": 0,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "next_gate": (
            "freeze train-only trainer choices and satisfy the separate "
            "trainer-contract preflight; this artifact does not authorize training"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--final-audit", type=Path, required=True)
    parser.add_argument("--train-output", type=Path, required=True)
    parser.add_argument("--validation-output", type=Path, required=True)
    args = parser.parse_args()
    report = build_from_paths(
        work_dir=args.work_dir,
        final_audit_path=args.final_audit,
        train_output=args.train_output,
        validation_output=args.validation_output,
    )
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
