"""Fail-closed authorization gate for the first float NNUE trainer.

This module validates a frozen trainer contract against two byte-identical
final development-data audits, the development-only split manifest, exact
train/validation analysis inventories, and a post-acquisition full-suite
attestation.  It never opens the sealed-test selection manifest, a sealed-test
analysis, or an analysis payload.

The current acquisition is intentionally unable to satisfy this gate.  The
tool exists so the first trainer cannot start from prose, a partial corpus, or
an unrecorded hyperparameter choice after acquisition completes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scratch import nnue_scaling_final_audit as final_audit  # noqa: E402
from makhos.nnue_features import feature_spec_payload  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    encoded_json,
    sha256,
    write_locked_json,
)


CONTRACT_FORMAT = "thai-makhos-nnue-trainer-contract-v1"
INVENTORY_FORMAT = "thai-makhos-nnue-trainer-input-inventory-v1"
SUITE_FORMAT = "thai-makhos-full-suite-attestation-v2"
PREFLIGHT_FORMAT = "thai-makhos-nnue-trainer-preflight-v1"
AUTHORIZATION_FORMAT = "thai-makhos-nnue-trainer-authorization-v1"
AUTHORIZATION_KEYS = frozenset(
    {
        "format",
        "kind",
        "verdict",
        "training_authorized",
        "playing_code_changed",
        "model_trained",
        "accepted_library_sha256",
        "ruleset_sha256",
        "contract_sha256",
        "trainer_contract_reproduced_byte_identical",
        "final_data_audit_sha256",
        "final_data_audit_reproduced_byte_identical",
        "development_manifest_sha256",
        "analysis_set_sha256",
        "train_inventory_sha256",
        "validation_inventory_sha256",
        "full_suite_attestation_sha256",
        "trainer_preflight_sha256",
        "train_games",
        "validation_games",
        "sealed_test_manifest_read",
        "test_analysis_files_read",
        "sealed_test_labels_opened",
        "gates",
        "next_action",
    }
)
AUTHORIZATION_GATE_KEYS = frozenset(
    {
        "accepted_control_preserved",
        "final_data_audit_passed_and_reproduced",
        "development_manifest_exact",
        "train_validation_inventories_exact_and_disjoint",
        "analysis_set_exact",
        "complete_suite_passed_while_workers_idle",
        "trainer_contract_frozen_and_complete",
        "trainer_contract_reproduced_byte_identical",
        "tiny_fixture_repeat_resume_and_checksum_passed",
        "sealed_test_unopened",
    }
)
EXPECTED_ACCEPTED_SHA256 = final_audit.EXPECTED_ACCEPTED_SHA256
EXPECTED_DEVELOPMENT_MANIFEST_SHA256 = (
    final_audit.EXPECTED_DEVELOPMENT_MANIFEST_SHA256
)
EXPECTED_SEALED_TEST_MANIFEST_SHA256 = (
    final_audit.EXPECTED_SEALED_TEST_MANIFEST_SHA256
)
EXPECTED_DEVELOPMENT_GAMES = final_audit.EXPECTED_DEVELOPMENT_GAMES
ACCEPTED_LIBRARY = ROOT / "build" / "makhos_native_accepted.dll"
RULESET = ROOT / "RULESET.json"
FULL_SUITE_RUNNER = ROOT / "tools" / "verification" / "full_suite_attestation.py"
LEGACY_FULL_SUITE_RUNNER = ROOT / "scratch" / "nnue_full_suite_attestation.py"
HEX_64 = re.compile(r"^[0-9A-F]{64}$")
GAME_ID = re.compile(r"^[0-9a-f]{16}$")


class ContractGateError(RuntimeError):
    """Raised when a trainer authorization input fails closed."""


@dataclass(frozen=True)
class JsonSnapshot:
    path: Path
    payload: dict
    encoded: bytes
    sha256: str


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractGateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_snapshot(path: Path) -> JsonSnapshot:
    """Read, hash, decode, and canonical-format-check one immutable file."""

    resolved = path.resolve()
    encoded = resolved.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest().upper()
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractGateError(f"invalid UTF-8 JSON: {resolved}") from error
    if not isinstance(payload, dict):
        raise ContractGateError(f"JSON root must be an object: {resolved}")
    # Project artifacts are emitted by both write_bytes (LF) and write_text
    # (native newlines). Accept only those two exact canonical byte forms.
    canonical_lf = encoded_json(payload).encode("utf-8")
    canonical_native = encoded_json(payload).replace("\n", os.linesep).encode("utf-8")
    if encoded not in {canonical_lf, canonical_native}:
        raise ContractGateError(f"JSON is not canonical/reproducible: {resolved}")
    return JsonSnapshot(resolved, payload, encoded, digest)


def _mapping(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise ContractGateError(f"{where} must be an object")
    return value


def _exact_keys(value: Mapping, expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractGateError(
            f"{where} keys differ; missing={missing}, extra={extra}"
        )


def _upper_sha256(value: object, where: str) -> str:
    if not isinstance(value, str) or not HEX_64.fullmatch(value):
        raise ContractGateError(f"{where} must be an uppercase SHA-256")
    return value


def _positive_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractGateError(f"{where} must be a positive integer")
    return value


def _nonnegative_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractGateError(f"{where} must be a nonnegative integer")
    return value


def _finite_number(value: object, where: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractGateError(f"{where} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ContractGateError(f"{where} must be finite and >= {minimum}")
    return result


def _aware_timestamp(value: object, where: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContractGateError(f"{where} must be a non-empty ISO timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise ContractGateError(f"{where} must be an ISO timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContractGateError(f"{where} must include a UTC offset")
    return result


def _game_id_set_sha256(game_ids: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for game_id in sorted(game_ids):
        digest.update(game_id.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def _analysis_set_sha256(rows: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, file_sha in sorted(rows):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def _validate_final_audit(snapshot: JsonSnapshot) -> dict:
    audit = snapshot.payload
    required = {
        "format",
        "kind",
        "verdict",
        "playing_code_changed",
        "model_trained",
        "trainer_authorized_by_this_artifact",
        "accepted_library_sha256",
        "audit_script_sha256",
        "development_manifest_sha256",
        "sealed_test_manifest_sha256",
        "sealed_test_manifest_read",
        "test_analysis_files_read",
        "analysis_set_sha256",
        "analysis_files",
        "coverage",
        "gates",
    }
    if not required <= set(audit):
        raise ContractGateError("final data audit is missing required evidence")
    if (
        audit["format"] != final_audit.FORMAT
        or audit["kind"] != "final-development-data-readiness-audit"
        or audit["verdict"] != "PASS"
    ):
        raise ContractGateError("final development-data audit is not PASS")
    if (
        audit["playing_code_changed"] is not False
        or audit["model_trained"] is not False
        or audit["trainer_authorized_by_this_artifact"] is not False
    ):
        raise ContractGateError("final audit phase-boundary flags changed")
    if audit["accepted_library_sha256"] != EXPECTED_ACCEPTED_SHA256:
        raise ContractGateError("final audit accepted DLL binding changed")
    if (
        audit["development_manifest_sha256"]
        != EXPECTED_DEVELOPMENT_MANIFEST_SHA256
    ):
        raise ContractGateError("final audit development binding changed")
    if (
        audit["sealed_test_manifest_sha256"]
        != EXPECTED_SEALED_TEST_MANIFEST_SHA256
        or audit["sealed_test_manifest_read"] is not False
        or audit["test_analysis_files_read"] != 0
    ):
        raise ContractGateError("sealed-test isolation was not preserved")
    if audit["analysis_files"] != EXPECTED_DEVELOPMENT_GAMES:
        raise ContractGateError("final audit analysis count changed")
    _upper_sha256(audit["analysis_set_sha256"], "final audit analysis set")
    expected_script_sha = sha256(Path(final_audit.__file__).resolve())
    if audit["audit_script_sha256"] != expected_script_sha:
        raise ContractGateError("final audit source identity changed")
    gates = _mapping(audit["gates"], "final audit gates")
    if not gates or not all(value is True for value in gates.values()):
        raise ContractGateError("final audit contains a failed gate")
    coverage = _mapping(audit["coverage"], "final audit coverage")
    for split in ("train", "validation"):
        row = _mapping(coverage.get(split), f"coverage.{split}")
        for key in ("games", "selected", "eligible"):
            _positive_int(row.get(key), f"coverage.{split}.{key}")
    if coverage["train"]["games"] + coverage["validation"]["games"] != (
        EXPECTED_DEVELOPMENT_GAMES
    ):
        raise ContractGateError("final audit split game counts do not add up")
    return coverage


def _validate_development_manifest(snapshot: JsonSnapshot) -> dict[str, dict]:
    manifest = snapshot.payload
    if snapshot.sha256 != EXPECTED_DEVELOPMENT_MANIFEST_SHA256:
        raise ContractGateError("development manifest SHA-256 changed")
    if (
        manifest.get("format") != "thai-makhos-nnue-quiet-leaf-acquisition-v1"
        or manifest.get("kind") != "development-selection-manifest"
        or manifest.get("split_before_sampling") is not True
    ):
        raise ContractGateError("development manifest contract changed")
    commitment = _mapping(
        manifest.get("sealed_test_commitment"),
        "development sealed-test commitment",
    )
    if (
        commitment.get("manifest_sha256")
        != EXPECTED_SEALED_TEST_MANIFEST_SHA256
        or commitment.get("model_selection_may_read") is not False
    ):
        raise ContractGateError("development manifest sealed-test policy changed")
    games = manifest.get("games")
    if not isinstance(games, list) or len(games) != EXPECTED_DEVELOPMENT_GAMES:
        raise ContractGateError("development manifest game count changed")
    by_id = {}
    split_counts = {"train": 0, "validation": 0}
    for row in games:
        row = _mapping(row, "development game")
        game_id = row.get("game_id")
        if not isinstance(game_id, str) or not GAME_ID.fullmatch(game_id):
            raise ContractGateError("development game id is invalid")
        if game_id in by_id:
            raise ContractGateError(f"duplicate development game id: {game_id}")
        split = row.get("split")
        if split not in split_counts:
            raise ContractGateError(f"non-development split in manifest: {split}")
        _upper_sha256(row.get("sha256"), f"game {game_id} SHA-256")
        _upper_sha256(
            row.get("selection_sha256"),
            f"game {game_id} selection SHA-256",
        )
        _nonnegative_int(
            row.get("selected_positions"),
            f"game {game_id} selected positions",
        )
        split_counts[split] += 1
        by_id[game_id] = row
    if manifest.get("games_by_split") != split_counts:
        raise ContractGateError("development split counts changed")
    return by_id


def _validate_inventory(
    snapshot: JsonSnapshot,
    *,
    expected_split: str,
    development_games: Mapping[str, dict],
    analysis_set_sha256: str,
) -> tuple[set[str], list[tuple[str, str]]]:
    inventory = snapshot.payload
    _exact_keys(
        inventory,
        {
            "format",
            "kind",
            "split",
            "development_manifest_sha256",
            "analysis_set_sha256",
            "games",
        },
        f"{expected_split} inventory",
    )
    if (
        inventory["format"] != INVENTORY_FORMAT
        or inventory["kind"] != "trainer-input-inventory"
        or inventory["split"] != expected_split
        or inventory["development_manifest_sha256"]
        != EXPECTED_DEVELOPMENT_MANIFEST_SHA256
        or inventory["analysis_set_sha256"] != analysis_set_sha256
    ):
        raise ContractGateError(f"{expected_split} inventory binding changed")
    rows = inventory["games"]
    if not isinstance(rows, list) or not rows:
        raise ContractGateError(f"{expected_split} inventory is empty")
    ids = set()
    analysis_rows = []
    expected_keys = {
        "game_id",
        "game_sha256",
        "selection_sha256",
        "selected_positions",
        "analysis_file",
        "analysis_sha256",
    }
    for row in rows:
        row = _mapping(row, f"{expected_split} inventory game")
        _exact_keys(row, expected_keys, f"{expected_split} inventory game")
        game_id = row["game_id"]
        if not isinstance(game_id, str) or not GAME_ID.fullmatch(game_id):
            raise ContractGateError(f"invalid {expected_split} game id")
        if game_id in ids:
            raise ContractGateError(f"duplicate {expected_split} game id: {game_id}")
        expected = development_games.get(game_id)
        if expected is None or expected.get("split") != expected_split:
            raise ContractGateError(
                f"{expected_split} inventory game is absent from its split: {game_id}"
            )
        if (
            row["game_sha256"] != expected["sha256"]
            or row["selection_sha256"] != expected["selection_sha256"]
            or row["selected_positions"] != expected["selected_positions"]
        ):
            raise ContractGateError(f"{expected_split} game binding changed: {game_id}")
        analysis_name = row["analysis_file"]
        if analysis_name != f"{game_id}.analysis.json":
            raise ContractGateError(f"analysis filename does not bind game: {game_id}")
        _upper_sha256(row["analysis_sha256"], f"analysis {game_id} SHA-256")
        ids.add(game_id)
        analysis_rows.append((analysis_name, row["analysis_sha256"]))
    expected_ids = {
        game_id
        for game_id, row in development_games.items()
        if row["split"] == expected_split
    }
    if ids != expected_ids:
        raise ContractGateError(f"{expected_split} inventory is not an exact set")
    return ids, analysis_rows


def _validate_suite_attestation(
    snapshot: JsonSnapshot,
    *,
    final_audit_sha256: str,
) -> dict:
    suite = snapshot.payload
    _exact_keys(
        suite,
        {
            "format",
            "kind",
            "verdict",
            "workers_idle",
            "interactive_session_inactive_before_and_after",
            "health_state_before_and_after",
            "exit_code",
            "discovered_tests",
            "tests_run",
            "failures",
            "errors",
            "expected_failures",
            "unexpected_successes",
            "skipped",
            "duration_seconds",
            "started_at_utc",
            "completed_at_utc",
            "command",
            "python_version",
            "test_files",
            "source_files",
            "test_inventory_sha256",
            "source_inventory_sha256",
            "runner_sha256",
            "result_output_sha256",
            "accepted_library_sha256",
            "final_data_audit_sha256",
            "analysis_payloads_read",
            "sealed_test_manifest_read",
            "test_analysis_files_read",
            "production_open_guard_triggered",
        },
        "full-suite attestation",
    )
    if (
        suite["format"] != SUITE_FORMAT
        or suite["kind"] != "post-acquisition-complete-suite"
        or suite["verdict"] != "PASS"
        or suite["workers_idle"] is not True
        or suite["interactive_session_inactive_before_and_after"] is not True
        or suite["health_state_before_and_after"]
        != ["COMPLETE_PENDING_FINAL_GATES", "COMPLETE_PENDING_FINAL_GATES"]
        or suite["exit_code"] != 0
    ):
        raise ContractGateError(
            "full suite did not PASS under completed, idle, GUI-inactive health"
        )
    discovered_tests = _positive_int(
        suite["discovered_tests"], "full-suite discovered_tests"
    )
    tests_run = _positive_int(suite["tests_run"], "full-suite tests_run")
    if tests_run != discovered_tests:
        raise ContractGateError("full suite did not run every discovered test")
    for key in ("failures", "errors", "unexpected_successes"):
        if suite[key] != 0:
            raise ContractGateError(f"full-suite {key} is nonzero")
    for key in ("expected_failures", "skipped"):
        _nonnegative_int(suite[key], f"full-suite {key}")
    _finite_number(suite["duration_seconds"], "full-suite duration")
    if (
        not isinstance(suite["command"], list)
        or not suite["command"]
        or not all(isinstance(item, str) and item for item in suite["command"])
        or not isinstance(suite["python_version"], str)
        or not suite["python_version"]
    ):
        raise ContractGateError("full-suite runtime provenance is incomplete")
    started_at = _aware_timestamp(
        suite["started_at_utc"], "full-suite started_at_utc"
    )
    completed_at = _aware_timestamp(
        suite["completed_at_utc"], "full-suite completed_at_utc"
    )
    if completed_at < started_at:
        raise ContractGateError("full-suite timestamps run backwards")
    _positive_int(suite["test_files"], "full-suite test_files")
    _positive_int(suite["source_files"], "full-suite source_files")
    _upper_sha256(suite["test_inventory_sha256"], "test inventory SHA-256")
    _upper_sha256(suite["source_inventory_sha256"], "source inventory SHA-256")
    _upper_sha256(suite["runner_sha256"], "full-suite runner SHA-256")
    _upper_sha256(suite["result_output_sha256"], "full-suite output SHA-256")
    if suite["runner_sha256"] not in (sha256(FULL_SUITE_RUNNER), sha256(LEGACY_FULL_SUITE_RUNNER)):
        raise ContractGateError("full-suite runner binding changed")
    # Import lazily: the runner imports this gate for its schema and validators.
    # At authorization time both modules are initialized, so this independently
    # recomputes the current tree rather than trusting hashes self-reported by
    # the attestation.
    from scratch import nnue_full_suite_attestation as suite_runner

    current_test_paths = suite_runner.test_inventory_paths(ROOT)
    current_source_paths = suite_runner.source_inventory_paths(ROOT)
    if (
        suite["test_files"] != len(current_test_paths)
        or suite["test_inventory_sha256"]
        != suite_runner.inventory_sha256(current_test_paths, root=ROOT)
    ):
        raise ContractGateError("full-suite test inventory is stale or incomplete")
    if (
        suite["source_files"] != len(current_source_paths)
        or suite["source_inventory_sha256"]
        != suite_runner.inventory_sha256(current_source_paths, root=ROOT)
    ):
        raise ContractGateError("full-suite source inventory is stale or incomplete")
    if suite["accepted_library_sha256"] != EXPECTED_ACCEPTED_SHA256:
        raise ContractGateError("full-suite accepted DLL binding changed")
    if suite["final_data_audit_sha256"] != final_audit_sha256:
        raise ContractGateError("full-suite final-audit binding changed")
    if (
        suite["analysis_payloads_read"] != 0
        or suite["sealed_test_manifest_read"] is not False
        or suite["test_analysis_files_read"] != 0
        or suite["production_open_guard_triggered"] is not False
    ):
        raise ContractGateError("full suite crossed a protected data boundary")
    return suite


def _validate_trainer_preflight(
    snapshot: JsonSnapshot,
    *,
    contract_sha256: str,
    final_audit_sha256: str,
    expected_seeds: list[int],
    trainer_source_sha256: str,
    trainer_fixture_sha256: str,
) -> dict:
    preflight = snapshot.payload
    _exact_keys(
        preflight,
        {
            "format",
            "kind",
            "verdict",
            "contract_sha256",
            "final_data_audit_sha256",
            "trainer_source_sha256",
            "fixture_sha256",
            "seeds_tested",
            "tiny_fixture_overfit",
            "deterministic_repeat_byte_identical",
            "deterministic_resume_byte_identical",
            "checkpoint_checksum_verified",
            "sealed_guard_tests_passed",
            "development_rows_read",
            "sealed_test_manifest_read",
            "test_analysis_files_read",
            "production_model_trained",
            "fixture_model_discarded",
            "training_run_authorized_by_this_artifact",
        },
        "trainer preflight",
    )
    if (
        preflight["format"] != PREFLIGHT_FORMAT
        or preflight["kind"] != "tiny-fixture-trainer-readiness"
        or preflight["verdict"] != "PASS"
        or preflight["contract_sha256"] != contract_sha256
        or preflight["final_data_audit_sha256"] != final_audit_sha256
        or preflight["trainer_source_sha256"] != trainer_source_sha256
        or preflight["fixture_sha256"] != trainer_fixture_sha256
        or preflight["seeds_tested"] != expected_seeds
    ):
        raise ContractGateError("trainer preflight identity or seed binding changed")
    for key in (
        "tiny_fixture_overfit",
        "deterministic_repeat_byte_identical",
        "deterministic_resume_byte_identical",
        "checkpoint_checksum_verified",
        "sealed_guard_tests_passed",
        "fixture_model_discarded",
    ):
        if preflight[key] is not True:
            raise ContractGateError(f"trainer preflight gate failed: {key}")
    if (
        preflight["development_rows_read"] != 0
        or preflight["sealed_test_manifest_read"] is not False
        or preflight["test_analysis_files_read"] != 0
        or preflight["production_model_trained"] is not False
        or preflight["training_run_authorized_by_this_artifact"] is not False
    ):
        raise ContractGateError("trainer preflight crossed its phase boundary")
    return preflight


def _validate_contract(
    snapshot: JsonSnapshot,
    *,
    final_audit_snapshot: JsonSnapshot,
    suite_snapshot: JsonSnapshot,
    train_inventory_snapshot: JsonSnapshot,
    validation_inventory_snapshot: JsonSnapshot,
    coverage: dict,
    train_ids: set[str],
    validation_ids: set[str],
) -> dict:
    contract = snapshot.payload
    _exact_keys(
        contract,
        {
            "format",
            "kind",
            "status",
            "accepted_library_sha256",
            "ruleset_sha256",
            "evidence",
            "dataset",
            "feature_spec",
            "network",
            "targets",
            "weighting",
            "optimizer",
            "reproducibility",
            "learning_curve",
            "checkpoint",
            "external_regressions",
            "sealed_test_policy",
            "authorization_policy",
        },
        "trainer contract",
    )
    if (
        contract["format"] != CONTRACT_FORMAT
        or contract["kind"] != "first-float-nnue-v1"
        or contract["status"] != "FROZEN"
    ):
        raise ContractGateError("trainer contract is not a frozen v1 contract")
    if contract["accepted_library_sha256"] != EXPECTED_ACCEPTED_SHA256:
        raise ContractGateError("trainer contract accepted DLL binding changed")
    if contract["ruleset_sha256"] != sha256(RULESET):
        raise ContractGateError("trainer contract ruleset binding changed")

    evidence = _mapping(contract["evidence"], "contract evidence")
    _exact_keys(
        evidence,
        {
            "final_data_audit_sha256",
            "final_data_audit_script_sha256",
            "development_manifest_sha256",
            "analysis_set_sha256",
            "full_suite_attestation_sha256",
            "full_suite_test_inventory_sha256",
            "full_suite_source_inventory_sha256",
            "full_suite_runner_sha256",
            "train_inventory_sha256",
            "validation_inventory_sha256",
            "trainer_source_sha256",
            "trainer_fixture_sha256",
            "final_audit_reproduced_byte_identical",
        },
        "contract evidence",
    )
    expected_evidence = {
        "final_data_audit_sha256": final_audit_snapshot.sha256,
        "final_data_audit_script_sha256": final_audit_snapshot.payload[
            "audit_script_sha256"
        ],
        "development_manifest_sha256": EXPECTED_DEVELOPMENT_MANIFEST_SHA256,
        "analysis_set_sha256": final_audit_snapshot.payload["analysis_set_sha256"],
        "full_suite_attestation_sha256": suite_snapshot.sha256,
        "full_suite_test_inventory_sha256": suite_snapshot.payload[
            "test_inventory_sha256"
        ],
        "full_suite_source_inventory_sha256": suite_snapshot.payload[
            "source_inventory_sha256"
        ],
        "full_suite_runner_sha256": suite_snapshot.payload["runner_sha256"],
        "train_inventory_sha256": train_inventory_snapshot.sha256,
        "validation_inventory_sha256": validation_inventory_snapshot.sha256,
        "trainer_source_sha256": evidence["trainer_source_sha256"],
        "trainer_fixture_sha256": evidence["trainer_fixture_sha256"],
        "final_audit_reproduced_byte_identical": True,
    }
    _upper_sha256(evidence["trainer_source_sha256"], "trainer source SHA-256")
    _upper_sha256(evidence["trainer_fixture_sha256"], "trainer fixture SHA-256")
    if evidence != expected_evidence:
        raise ContractGateError("trainer contract evidence bindings differ")

    dataset = _mapping(contract["dataset"], "contract dataset")
    _exact_keys(
        dataset,
        {
            "split_unit",
            "dedup_identity",
            "train_games",
            "validation_games",
            "train_selected_rows",
            "validation_selected_rows",
            "train_eligible_rows",
            "validation_eligible_rows",
            "train_game_ids_sha256",
            "validation_game_ids_sha256",
            "test_rows_included",
            "test_game_ids_included",
        },
        "contract dataset",
    )
    expected_dataset = {
        "split_unit": "source_game",
        "dedup_identity": "canonical_position_plus_reversible_clock",
        "train_games": len(train_ids),
        "validation_games": len(validation_ids),
        "train_selected_rows": coverage["train"]["selected"],
        "validation_selected_rows": coverage["validation"]["selected"],
        "train_eligible_rows": coverage["train"]["eligible"],
        "validation_eligible_rows": coverage["validation"]["eligible"],
        "train_game_ids_sha256": _game_id_set_sha256(train_ids),
        "validation_game_ids_sha256": _game_id_set_sha256(validation_ids),
        "test_rows_included": False,
        "test_game_ids_included": False,
    }
    if dataset != expected_dataset:
        raise ContractGateError("trainer dataset declaration differs from evidence")

    feature = _mapping(contract["feature_spec"], "feature spec")
    expected_feature = feature_spec_payload()
    if feature != expected_feature:
        raise ContractGateError("locked v1 feature specification changed")

    network = _mapping(contract["network"], "network")
    expected_network = {
        "architecture_count": 1,
        "perspective_accumulators": 2,
        "feature_width": 128,
        "concatenated_width": 256,
        "hidden_width": 32,
        "output_width": 1,
        "output_perspective": "side_to_move",
        "policy_head": False,
    }
    if network != expected_network:
        raise ContractGateError("locked v1 network architecture changed")

    targets = _mapping(contract["targets"], "targets")
    _exact_keys(
        targets,
        {
            "teacher_score",
            "game_outcome",
            "exact_wdl",
            "loss_mix",
            "missing_label_policy",
            "calibration_source",
            "test_used",
        },
        "targets",
    )
    teacher = _mapping(targets["teacher_score"], "teacher target")
    _exact_keys(
        teacher,
        {
            "enabled",
            "clip_cp",
            "normalization_kind",
            "normalization_scale_cp",
            "loss",
            "loss_parameter",
        },
        "teacher target",
    )
    if teacher["enabled"] is not True:
        raise ContractGateError("teacher score must remain enabled in v1")
    clip_cp = _positive_int(teacher["clip_cp"], "teacher clip_cp")
    if clip_cp > 30_000:
        raise ContractGateError("teacher clip collides with the non-terminal bound")
    if teacher["normalization_kind"] != "tanh":
        raise ContractGateError("teacher normalization is not v1 tanh")
    _finite_number(
        teacher["normalization_scale_cp"],
        "teacher normalization scale",
        minimum=1e-12,
    )
    if teacher["loss"] != "huber":
        raise ContractGateError("teacher loss is not v1 huber")
    _finite_number(
        teacher["loss_parameter"],
        "teacher loss parameter",
        minimum=1e-12,
    )

    label_encoding = {"loss": -1, "draw": 0, "win": 1}
    for name in ("game_outcome", "exact_wdl"):
        component = _mapping(targets[name], f"{name} target")
        _exact_keys(
            component,
            {"enabled", "encoding", "loss", "history_required"},
            f"{name} target",
        )
        if not isinstance(component["enabled"], bool):
            raise ContractGateError(f"{name}.enabled must be boolean")
        if component["encoding"] != label_encoding:
            raise ContractGateError(f"{name} encoding changed")
        if component["loss"] != "mse":
            raise ContractGateError(f"{name} loss is not v1 mse")
        if component["history_required"] is not True:
            raise ContractGateError(f"{name} discarded history semantics")
    mix = _mapping(targets["loss_mix"], "loss mix")
    _exact_keys(mix, {"teacher_score", "game_outcome", "exact_wdl"}, "loss mix")
    weights = {
        key: _finite_number(value, f"loss mix {key}")
        for key, value in mix.items()
    }
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-12):
        raise ContractGateError("loss mix must sum to exactly one")
    if weights["teacher_score"] <= 0.0:
        raise ContractGateError("teacher score must have nonzero v1 loss weight")
    for name in ("game_outcome", "exact_wdl"):
        if bool(targets[name]["enabled"]) != (weights[name] > 0.0):
            raise ContractGateError(f"{name} enabled flag and loss weight differ")
    if (
        targets["missing_label_policy"]
        != "renormalize_available_components_per_sample"
    ):
        raise ContractGateError("missing-label policy changed")
    if targets["calibration_source"] != "train_only" or targets["test_used"] is not False:
        raise ContractGateError("target choices were not isolated to train data")

    weighting = _mapping(contract["weighting"], "weighting")
    _exact_keys(
        weighting,
        {
            "source_game_equal_weight",
            "position_weighting",
            "phase_weights",
            "exact_wdl_multiplier",
            "selection_source",
        },
        "weighting",
    )
    if (
        weighting["source_game_equal_weight"] is not True
        or weighting["position_weighting"] != "uniform_within_source_game"
        or weighting["selection_source"] != "train_only"
    ):
        raise ContractGateError("weighting contract is incomplete or leaked")
    phase_weights = _mapping(weighting["phase_weights"], "phase weights")
    _exact_keys(phase_weights, {"13_to_16", "9_to_12", "5_to_8"}, "phase weights")
    for key, value in phase_weights.items():
        _finite_number(value, f"phase weight {key}", minimum=1e-12)
    _finite_number(
        weighting["exact_wdl_multiplier"],
        "exact WDL multiplier",
        minimum=1e-12,
    )

    optimizer = _mapping(contract["optimizer"], "optimizer")
    _exact_keys(
        optimizer,
        {
            "name",
            "learning_rate",
            "weight_decay",
            "batch_size",
            "max_epochs",
            "schedule",
        },
        "optimizer",
    )
    if optimizer["name"] != "AdamW":
        raise ContractGateError("optimizer is not v1 AdamW")
    _finite_number(optimizer["learning_rate"], "learning rate", minimum=1e-12)
    _finite_number(optimizer["weight_decay"], "weight decay")
    _positive_int(optimizer["batch_size"], "batch size")
    max_epochs = _positive_int(optimizer["max_epochs"], "max epochs")
    schedule = _mapping(optimizer["schedule"], "optimizer schedule")
    _exact_keys(schedule, {"kind", "warmup_epochs"}, "optimizer schedule")
    warmup_epochs = _nonnegative_int(
        schedule["warmup_epochs"],
        "optimizer warmup epochs",
    )
    if (
        schedule["kind"] not in {"constant", "cosine"}
        or warmup_epochs >= max_epochs
    ):
        raise ContractGateError("optimizer schedule is unsupported")

    reproducibility = _mapping(contract["reproducibility"], "reproducibility")
    _exact_keys(
        reproducibility,
        {
            "seeds",
            "deterministic_algorithms",
            "deterministic_resume_required",
            "checkpoint_checksum",
            "dataloader_workers",
            "dependencies",
            "target_cpu",
        },
        "reproducibility",
    )
    seeds = reproducibility["seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) < 2
        or len(set(seeds)) != len(seeds)
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ContractGateError("at least two unique deterministic seeds are required")
    if (
        reproducibility["deterministic_algorithms"] is not True
        or reproducibility["deterministic_resume_required"] is not True
        or reproducibility["checkpoint_checksum"] != "sha256"
        or reproducibility["dataloader_workers"] != 0
        or reproducibility["target_cpu"] != "AMD Ryzen 5 5600H"
    ):
        raise ContractGateError("first-trainer reproducibility contract changed")
    dependencies = _mapping(reproducibility["dependencies"], "dependencies")
    if not dependencies or not all(
        isinstance(name, str)
        and name
        and isinstance(version, str)
        and version
        for name, version in dependencies.items()
    ):
        raise ContractGateError("trainer dependencies are not fully pinned")

    learning_curve = _mapping(contract["learning_curve"], "learning curve")
    _exact_keys(
        learning_curve,
        {"sizes", "same_split", "predeclared", "selection_source"},
        "learning curve",
    )
    sizes = learning_curve["sizes"]
    numeric_sizes = sizes[:-1] if isinstance(sizes, list) and sizes else []
    if (
        not isinstance(sizes, list)
        or len(sizes) < 2
        or sizes[-1] != "all"
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in numeric_sizes)
        or numeric_sizes != sorted(set(numeric_sizes))
        or any(value >= dataset["train_eligible_rows"] for value in numeric_sizes)
        or learning_curve["same_split"] is not True
        or learning_curve["predeclared"] is not True
        or learning_curve["selection_source"] != "train_only"
    ):
        raise ContractGateError("learning curve is not valid and predeclared")

    checkpoint = _mapping(contract["checkpoint"], "checkpoint")
    _exact_keys(
        checkpoint,
        {
            "selection_split",
            "metric",
            "mode",
            "early_stop_patience",
            "min_delta",
            "restore_best",
            "test_used",
        },
        "checkpoint",
    )
    if (
        checkpoint["selection_split"] != "validation"
        or checkpoint["metric"] != "validation_loss"
        or checkpoint["mode"] != "min"
        or checkpoint["restore_best"] is not True
        or checkpoint["test_used"] is not False
    ):
        raise ContractGateError("checkpoint selection policy leaked or is incomplete")
    _positive_int(checkpoint["early_stop_patience"], "early-stop patience")
    _finite_number(checkpoint["min_delta"], "checkpoint min_delta")

    external = _mapping(contract["external_regressions"], "external regressions")
    if external != {"report_only": True, "hyperparameter_selection": False}:
        raise ContractGateError("external regressions became model-selection data")

    sealed = _mapping(contract["sealed_test_policy"], "sealed-test policy")
    expected_sealed = {
        "manifest_sha256": EXPECTED_SEALED_TEST_MANIFEST_SHA256,
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
    }
    if sealed != expected_sealed:
        raise ContractGateError("sealed-test one-time policy changed")

    authorization = _mapping(contract["authorization_policy"], "authorization policy")
    if authorization != {
        "training_requires_this_gate_pass": True,
        "playing_code_changed": False,
        "model_already_trained": False,
    }:
        raise ContractGateError("trainer authorization phase boundary changed")
    return contract


def authorize_from_paths(
    *,
    contract_a_path: Path,
    contract_b_path: Path,
    final_audit_a_path: Path,
    final_audit_b_path: Path,
    development_manifest_path: Path,
    train_inventory_path: Path,
    validation_inventory_path: Path,
    full_suite_attestation_path: Path,
    trainer_preflight_path: Path,
) -> dict:
    paths = [
        contract_a_path,
        contract_b_path,
        final_audit_a_path,
        final_audit_b_path,
        development_manifest_path,
        train_inventory_path,
        validation_inventory_path,
        full_suite_attestation_path,
        trainer_preflight_path,
    ]
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ContractGateError("authorization inputs must be distinct files")
    (
        contract_a,
        contract_b,
        audit_a,
        audit_b,
        development_snapshot,
        train_snapshot,
        validation_snapshot,
        suite_snapshot,
        preflight_snapshot,
    ) = [load_json_snapshot(path) for path in resolved]
    if contract_a.encoded != contract_b.encoded:
        raise ContractGateError("trainer contract reproduction is not byte-identical")
    if audit_a.encoded != audit_b.encoded:
        raise ContractGateError("final audit reproduction is not byte-identical")
    coverage = _validate_final_audit(audit_a)
    _validate_final_audit(audit_b)
    development_games = _validate_development_manifest(development_snapshot)
    train_ids, train_rows = _validate_inventory(
        train_snapshot,
        expected_split="train",
        development_games=development_games,
        analysis_set_sha256=audit_a.payload["analysis_set_sha256"],
    )
    validation_ids, validation_rows = _validate_inventory(
        validation_snapshot,
        expected_split="validation",
        development_games=development_games,
        analysis_set_sha256=audit_a.payload["analysis_set_sha256"],
    )
    if train_ids & validation_ids:
        raise ContractGateError("train/validation game inventories overlap")
    if len(train_ids) + len(validation_ids) != EXPECTED_DEVELOPMENT_GAMES:
        raise ContractGateError("trainer inventories do not cover development games")
    if _analysis_set_sha256(train_rows + validation_rows) != audit_a.payload[
        "analysis_set_sha256"
    ]:
        raise ContractGateError("trainer inventories do not match validated analyses")
    _validate_suite_attestation(
        suite_snapshot,
        final_audit_sha256=audit_a.sha256,
    )
    contract = _validate_contract(
        contract_a,
        final_audit_snapshot=audit_a,
        suite_snapshot=suite_snapshot,
        train_inventory_snapshot=train_snapshot,
        validation_inventory_snapshot=validation_snapshot,
        coverage=coverage,
        train_ids=train_ids,
        validation_ids=validation_ids,
    )
    _validate_trainer_preflight(
        preflight_snapshot,
        contract_sha256=contract_a.sha256,
        final_audit_sha256=audit_a.sha256,
        expected_seeds=contract["reproducibility"]["seeds"],
        trainer_source_sha256=contract["evidence"]["trainer_source_sha256"],
        trainer_fixture_sha256=contract["evidence"]["trainer_fixture_sha256"],
    )
    if sha256(ACCEPTED_LIBRARY) != EXPECTED_ACCEPTED_SHA256:
        raise ContractGateError("accepted DLL changed before trainer authorization")
    return {
        "format": AUTHORIZATION_FORMAT,
        "kind": "first-float-trainer-authorization",
        "verdict": "PASS",
        "training_authorized": True,
        "playing_code_changed": False,
        "model_trained": False,
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "ruleset_sha256": sha256(RULESET),
        "contract_sha256": contract_a.sha256,
        "trainer_contract_reproduced_byte_identical": True,
        "final_data_audit_sha256": audit_a.sha256,
        "final_data_audit_reproduced_byte_identical": True,
        "development_manifest_sha256": development_snapshot.sha256,
        "analysis_set_sha256": audit_a.payload["analysis_set_sha256"],
        "train_inventory_sha256": train_snapshot.sha256,
        "validation_inventory_sha256": validation_snapshot.sha256,
        "full_suite_attestation_sha256": suite_snapshot.sha256,
        "trainer_preflight_sha256": preflight_snapshot.sha256,
        "train_games": len(train_ids),
        "validation_games": len(validation_ids),
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "sealed_test_labels_opened": False,
        "gates": {
            "accepted_control_preserved": True,
            "final_data_audit_passed_and_reproduced": True,
            "development_manifest_exact": True,
            "train_validation_inventories_exact_and_disjoint": True,
            "analysis_set_exact": True,
            "complete_suite_passed_while_workers_idle": True,
            "trainer_contract_frozen_and_complete": True,
            "trainer_contract_reproduced_byte_identical": True,
            "tiny_fixture_repeat_resume_and_checksum_passed": True,
            "sealed_test_unopened": True,
        },
        "next_action": (
            "run only the first float trainer declared by the frozen contract; "
            "the sealed test remains unopened"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-a", type=Path, required=True)
    parser.add_argument("--contract-b", type=Path, required=True)
    parser.add_argument("--final-audit-a", type=Path, required=True)
    parser.add_argument("--final-audit-b", type=Path, required=True)
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument("--train-inventory", type=Path, required=True)
    parser.add_argument("--validation-inventory", type=Path, required=True)
    parser.add_argument("--full-suite-attestation", type=Path, required=True)
    parser.add_argument("--trainer-preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = authorize_from_paths(
        contract_a_path=args.contract_a,
        contract_b_path=args.contract_b,
        final_audit_a_path=args.final_audit_a,
        final_audit_b_path=args.final_audit_b,
        development_manifest_path=args.development_manifest,
        train_inventory_path=args.train_inventory,
        validation_inventory_path=args.validation_inventory,
        full_suite_attestation_path=args.full_suite_attestation,
        trainer_preflight_path=args.trainer_preflight,
    )
    write_locked_json(args.output.resolve(), report)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": sha256(args.output.resolve()),
                "training_authorized": report["training_authorized"],
                "sealed_test_manifest_read": False,
                "test_analysis_files_read": 0,
                "verdict": report["verdict"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
