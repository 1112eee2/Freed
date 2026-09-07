"""Deterministic, fail-closed builder for the first NNUE trainer contract.

The freezer assembles only after the final-data/full-suite evidence exists, but
it is safe to unit-test during acquisition because it never opens an analysis
payload or a sealed-test file.  Dynamic evidence and train-only choices must be
provided explicitly; the locked feature, network, split, and sealed-test
policies are supplied by code so they cannot drift through hand-edited JSON.
This module does not train a model or authorize a run.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import sys
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.nnue_features import feature_spec_payload  # noqa: E402
from scratch import nnue_trainer_contract_gate as gate  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import encoded_json  # noqa: E402


SHA256: Final = re.compile(r"^[0-9A-F]{64}$")
CLI_INPUT_KEYS: Final = frozenset(
    {
        "evidence",
        "dataset",
        "targets",
        "weighting",
        "optimizer",
        "reproducibility",
        "learning_curve",
        "checkpoint",
        "trainer_source_sha256",
        "trainer_fixture_sha256",
    }
)

EVIDENCE_INPUT_KEYS: Final = frozenset(
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
    }
)
DATASET_INPUT_KEYS: Final = frozenset(
    {
        "train_games",
        "validation_games",
        "train_selected_rows",
        "validation_selected_rows",
        "train_eligible_rows",
        "validation_eligible_rows",
        "train_game_ids_sha256",
        "validation_game_ids_sha256",
    }
)
TARGET_KEYS: Final = frozenset(
    {
        "teacher_score",
        "game_outcome",
        "exact_wdl",
        "loss_mix",
        "missing_label_policy",
        "calibration_source",
        "test_used",
    }
)
TEACHER_KEYS: Final = frozenset(
    {
        "enabled",
        "clip_cp",
        "normalization_kind",
        "normalization_scale_cp",
        "loss",
        "loss_parameter",
    }
)
LABEL_KEYS: Final = frozenset(
    {"enabled", "encoding", "loss", "history_required"}
)
WEIGHTING_KEYS: Final = frozenset(
    {
        "source_game_equal_weight",
        "position_weighting",
        "phase_weights",
        "exact_wdl_multiplier",
        "selection_source",
    }
)
OPTIMIZER_KEYS: Final = frozenset(
    {"name", "learning_rate", "weight_decay", "batch_size", "max_epochs", "schedule"}
)
REPRODUCIBILITY_KEYS: Final = frozenset(
    {
        "seeds",
        "deterministic_algorithms",
        "deterministic_resume_required",
        "checkpoint_checksum",
        "dataloader_workers",
        "dependencies",
        "target_cpu",
    }
)
LEARNING_CURVE_KEYS: Final = frozenset(
    {"sizes", "same_split", "predeclared", "selection_source"}
)
CHECKPOINT_KEYS: Final = frozenset(
    {
        "selection_split",
        "metric",
        "mode",
        "early_stop_patience",
        "min_delta",
        "restore_best",
        "test_used",
    }
)

LOCKED_NETWORK: Final = {
    "architecture_count": 1,
    "perspective_accumulators": 2,
    "feature_width": 128,
    "concatenated_width": 256,
    "hidden_width": 32,
    "output_width": 1,
    "output_perspective": "side_to_move",
    "policy_head": False,
}
LOCKED_EXTERNAL_REGRESSIONS: Final = {
    "report_only": True,
    "hyperparameter_selection": False,
}
LOCKED_AUTHORIZATION_POLICY: Final = {
    "training_requires_this_gate_pass": True,
    "playing_code_changed": False,
    "model_already_trained": False,
}


class ContractFreezeError(ValueError):
    """Raised when a contract cannot be frozen without guessing or leakage."""


def _mapping(value: object, where: str) -> dict:
    if not isinstance(value, Mapping):
        raise ContractFreezeError(f"{where} must be an object")
    return deepcopy(dict(value))


def _exact_keys(value: Mapping, expected: frozenset[str], where: str) -> dict:
    actual = set(value)
    if actual != set(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractFreezeError(f"{where} keys differ; missing={missing}, extra={extra}")
    return deepcopy(dict(value))


def _sha256(value: object, where: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ContractFreezeError(f"{where} must be an uppercase SHA-256")
    return value


def _bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise ContractFreezeError(f"{where} must be boolean")
    return value


def _positive_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractFreezeError(f"{where} must be a positive integer")
    return value


def _nonnegative_number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractFreezeError(f"{where} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ContractFreezeError(f"{where} must be finite and nonnegative")
    return float(value)


def _validate_targets(targets: dict) -> None:
    _exact_keys(targets, TARGET_KEYS, "targets")
    teacher = _exact_keys(
        _mapping(targets["teacher_score"], "targets.teacher_score"),
        TEACHER_KEYS,
        "teacher_score",
    )
    if teacher["enabled"] is not True:
        raise ContractFreezeError("teacher_score.enabled must be true")
    _positive_int(teacher["clip_cp"], "teacher_score.clip_cp")
    if teacher["clip_cp"] > 30_000:
        raise ContractFreezeError("teacher_score.clip_cp exceeds non-terminal bound")
    if teacher["normalization_kind"] != "tanh":
        raise ContractFreezeError("teacher_score.normalization_kind is not v1 tanh")
    _nonnegative_number(
        teacher["normalization_scale_cp"], "teacher_score.normalization_scale_cp"
    )
    if teacher["normalization_scale_cp"] <= 0:
        raise ContractFreezeError("teacher_score.normalization_scale_cp must be positive")
    if teacher["loss"] != "huber":
        raise ContractFreezeError("teacher_score.loss is not v1 huber")
    if _nonnegative_number(
        teacher["loss_parameter"], "teacher_score.loss_parameter"
    ) <= 0:
        raise ContractFreezeError("teacher_score.loss_parameter must be positive")

    label_encoding = {"loss": -1, "draw": 0, "win": 1}
    for name in ("game_outcome", "exact_wdl"):
        component = _exact_keys(
            _mapping(targets[name], f"targets.{name}"),
            LABEL_KEYS,
            f"targets.{name}",
        )
        _bool(component["enabled"], f"targets.{name}.enabled")
        if component["encoding"] != label_encoding:
            raise ContractFreezeError(f"targets.{name}.encoding is not locked")
        if component["loss"] != "mse":
            raise ContractFreezeError(f"targets.{name}.loss is not v1 mse")
        if component["history_required"] is not True:
            raise ContractFreezeError(f"targets.{name}.history_required must be true")

    loss_mix = _exact_keys(
        _mapping(targets["loss_mix"], "targets.loss_mix"),
        frozenset({"teacher_score", "game_outcome", "exact_wdl"}),
        "targets.loss_mix",
    )
    mix_total = 0.0
    for name, value in loss_mix.items():
        mix_total += _nonnegative_number(value, f"targets.loss_mix.{name}")
    if abs(mix_total - 1.0) > 1e-12:
        raise ContractFreezeError("targets.loss_mix must sum to one")
    if loss_mix["teacher_score"] <= 0:
        raise ContractFreezeError("teacher_score must have nonzero loss weight")
    for name in ("game_outcome", "exact_wdl"):
        if bool(targets[name]["enabled"]) != (loss_mix[name] > 0):
            raise ContractFreezeError(f"targets.{name}.enabled disagrees with loss mix")
    if (
        targets["missing_label_policy"]
        != "renormalize_available_components_per_sample"
    ):
        raise ContractFreezeError("targets.missing_label_policy is not locked")
    if targets["calibration_source"] != "train_only" or targets["test_used"] is not False:
        raise ContractFreezeError("targets must be train-only and test-free")


def _validate_weighting(weighting: dict) -> None:
    _exact_keys(weighting, WEIGHTING_KEYS, "weighting")
    if weighting["source_game_equal_weight"] is not True:
        raise ContractFreezeError("source_game_equal_weight must be true")
    if weighting["position_weighting"] != "uniform_within_source_game":
        raise ContractFreezeError("position_weighting is not v1 uniform")
    phase = _exact_keys(
        _mapping(weighting["phase_weights"], "weighting.phase_weights"),
        frozenset({"13_to_16", "9_to_12", "5_to_8"}),
        "weighting.phase_weights",
    )
    for key, value in phase.items():
        if _nonnegative_number(value, f"weighting.phase_weights.{key}") <= 0:
            raise ContractFreezeError(f"weighting.phase_weights.{key} must be positive")
    if _nonnegative_number(weighting["exact_wdl_multiplier"], "weighting.exact_wdl_multiplier") <= 0:
        raise ContractFreezeError("exact_wdl_multiplier must be positive")
    if weighting["selection_source"] != "train_only":
        raise ContractFreezeError("weighting.selection_source must be train_only")


def _validate_optimizer(optimizer: dict) -> None:
    _exact_keys(optimizer, OPTIMIZER_KEYS, "optimizer")
    if optimizer["name"] != "AdamW":
        raise ContractFreezeError("optimizer.name is not v1 AdamW")
    if _nonnegative_number(optimizer["learning_rate"], "optimizer.learning_rate") <= 0:
        raise ContractFreezeError("optimizer.learning_rate must be positive")
    _nonnegative_number(optimizer["weight_decay"], "optimizer.weight_decay")
    _positive_int(optimizer["batch_size"], "optimizer.batch_size")
    max_epochs = _positive_int(optimizer["max_epochs"], "optimizer.max_epochs")
    schedule = _mapping(optimizer["schedule"], "optimizer.schedule")
    _exact_keys(schedule, frozenset({"kind", "warmup_epochs"}), "optimizer.schedule")
    warmup_epochs = schedule["warmup_epochs"]
    if (
        schedule["kind"] not in {"constant", "cosine"}
        or isinstance(warmup_epochs, bool)
        or not isinstance(warmup_epochs, int)
        or not 0 <= warmup_epochs < max_epochs
    ):
        raise ContractFreezeError("optimizer.schedule is unsupported")


def _validate_reproducibility(reproducibility: dict) -> None:
    _exact_keys(reproducibility, REPRODUCIBILITY_KEYS, "reproducibility")
    seeds = reproducibility["seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) < 2
        or len(set(seeds)) != len(seeds)
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ContractFreezeError("reproducibility.seeds must contain two unique nonnegative integers")
    if reproducibility["deterministic_algorithms"] is not True:
        raise ContractFreezeError("deterministic_algorithms must be true")
    if reproducibility["deterministic_resume_required"] is not True:
        raise ContractFreezeError("deterministic_resume_required must be true")
    if reproducibility["checkpoint_checksum"] != "sha256":
        raise ContractFreezeError("checkpoint_checksum must be sha256")
    if reproducibility["dataloader_workers"] != 0:
        raise ContractFreezeError("dataloader_workers must be zero")
    if reproducibility["target_cpu"] != "AMD Ryzen 5 5600H":
        raise ContractFreezeError("target_cpu differs from the locked host")
    dependencies = _mapping(reproducibility["dependencies"], "reproducibility.dependencies")
    if not dependencies or not all(
        isinstance(name, str)
        and bool(name)
        and isinstance(version, str)
        and bool(version)
        for name, version in dependencies.items()
    ):
        raise ContractFreezeError("reproducibility.dependencies must be fully pinned")


def _validate_learning_curve(learning_curve: dict, train_eligible_rows: int) -> None:
    _exact_keys(learning_curve, LEARNING_CURVE_KEYS, "learning_curve")
    sizes = learning_curve["sizes"]
    numeric = sizes[:-1] if isinstance(sizes, list) else []
    if (
        not isinstance(sizes, list)
        or len(sizes) < 2
        or sizes[-1] != "all"
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in numeric)
        or numeric != sorted(set(numeric))
        or any(value >= train_eligible_rows for value in numeric)
        or learning_curve["same_split"] is not True
        or learning_curve["predeclared"] is not True
        or learning_curve["selection_source"] != "train_only"
    ):
        raise ContractFreezeError("learning_curve is not sorted, predeclared, or train-only")


def _validate_checkpoint(checkpoint: dict) -> None:
    _exact_keys(checkpoint, CHECKPOINT_KEYS, "checkpoint")
    if checkpoint["selection_split"] != "validation":
        raise ContractFreezeError("checkpoint.selection_split must be validation")
    if checkpoint["metric"] != "validation_loss":
        raise ContractFreezeError("checkpoint.metric is not validation_loss")
    if checkpoint["mode"] != "min":
        raise ContractFreezeError("checkpoint.mode is not min")
    if checkpoint["restore_best"] is not True or checkpoint["test_used"] is not False:
        raise ContractFreezeError("checkpoint policy is not validation-only")
    _positive_int(checkpoint["early_stop_patience"], "checkpoint.early_stop_patience")
    _nonnegative_number(checkpoint["min_delta"], "checkpoint.min_delta")


def _validate_dynamic_evidence(evidence: Mapping[str, object]) -> dict:
    result = _exact_keys(_mapping(evidence, "evidence"), EVIDENCE_INPUT_KEYS, "evidence")
    for key, value in result.items():
        _sha256(value, f"evidence.{key}")
    if result["development_manifest_sha256"] != gate.EXPECTED_DEVELOPMENT_MANIFEST_SHA256:
        raise ContractFreezeError("evidence development manifest is not the locked one")
    return result


def _validate_dataset(dataset: Mapping[str, object]) -> dict:
    values = _exact_keys(_mapping(dataset, "dataset"), DATASET_INPUT_KEYS, "dataset")
    for key in (
        "train_games",
        "validation_games",
        "train_selected_rows",
        "validation_selected_rows",
        "train_eligible_rows",
        "validation_eligible_rows",
    ):
        _positive_int(values[key], f"dataset.{key}")
    for key in ("train_game_ids_sha256", "validation_game_ids_sha256"):
        _sha256(values[key], f"dataset.{key}")
    return {
        "split_unit": "source_game",
        "dedup_identity": "canonical_position_plus_reversible_clock",
        **values,
        "test_rows_included": False,
        "test_game_ids_included": False,
    }


def freeze_contract(
    *,
    evidence: Mapping[str, object],
    dataset: Mapping[str, object],
    targets: Mapping[str, object],
    weighting: Mapping[str, object],
    optimizer: Mapping[str, object],
    reproducibility: Mapping[str, object],
    learning_curve: Mapping[str, object],
    checkpoint: Mapping[str, object],
    trainer_source_sha256: str,
    trainer_fixture_sha256: str,
) -> dict:
    """Build one canonical frozen contract from explicit post-gate inputs."""

    evidence_out = _validate_dynamic_evidence(evidence)
    dataset_out = _validate_dataset(dataset)
    targets_out = _mapping(targets, "targets")
    weighting_out = _mapping(weighting, "weighting")
    optimizer_out = _mapping(optimizer, "optimizer")
    reproducibility_out = _mapping(reproducibility, "reproducibility")
    learning_curve_out = _mapping(learning_curve, "learning_curve")
    checkpoint_out = _mapping(checkpoint, "checkpoint")
    _validate_targets(targets_out)
    _validate_weighting(weighting_out)
    _validate_optimizer(optimizer_out)
    _validate_reproducibility(reproducibility_out)
    _validate_learning_curve(learning_curve_out, dataset_out["train_eligible_rows"])
    _validate_checkpoint(checkpoint_out)

    evidence_out.update(
        {
            "trainer_source_sha256": _sha256(
                trainer_source_sha256, "trainer_source_sha256"
            ),
            "trainer_fixture_sha256": _sha256(
                trainer_fixture_sha256, "trainer_fixture_sha256"
            ),
            "final_audit_reproduced_byte_identical": True,
        }
    )
    contract = {
        "format": gate.CONTRACT_FORMAT,
        "kind": "first-float-nnue-v1",
        "status": "FROZEN",
        "accepted_library_sha256": gate.EXPECTED_ACCEPTED_SHA256,
        "ruleset_sha256": gate.sha256(gate.RULESET),
        "evidence": evidence_out,
        "dataset": dataset_out,
        "feature_spec": feature_spec_payload(),
        "network": deepcopy(LOCKED_NETWORK),
        "targets": targets_out,
        "weighting": weighting_out,
        "optimizer": optimizer_out,
        "reproducibility": reproducibility_out,
        "learning_curve": learning_curve_out,
        "checkpoint": checkpoint_out,
        "external_regressions": deepcopy(LOCKED_EXTERNAL_REGRESSIONS),
        "sealed_test_policy": {
            "manifest_sha256": gate.EXPECTED_SEALED_TEST_MANIFEST_SHA256,
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
        "authorization_policy": deepcopy(LOCKED_AUTHORIZATION_POLICY),
    }
    return contract


def canonical_contract_bytes(contract: Mapping[str, object]) -> bytes:
    """Return the exact bytes that a locked contract artifact must contain."""

    if not isinstance(contract, Mapping):
        raise ContractFreezeError("contract must be an object")
    try:
        return encoded_json(dict(contract)).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractFreezeError("contract cannot be encoded canonically") from error


def write_frozen_contract(path: Path, contract: Mapping[str, object]) -> str:
    """Write an immutable contract only to an approved non-source output path."""

    resolved = Path(path).resolve()
    forbidden_roots = (
        ROOT / "build" / "nnue_scaling_full_v1",
        ROOT / "makhos",
        ROOT / "native",
        ROOT / "schemas",
        ROOT / "scratch",
        ROOT / "tests",
        ROOT / "web",
    )
    if any(resolved == root or resolved.is_relative_to(root) for root in forbidden_roots):
        raise ContractFreezeError(f"contract output is inside a protected tree: {resolved}")
    if resolved.name == "RULESET.json" or resolved.suffix.casefold() != ".json":
        raise ContractFreezeError("contract output must be a new .json artifact")
    payload = dict(contract)
    encoded = canonical_contract_bytes(payload)
    if resolved.exists():
        try:
            existing = resolved.read_bytes()
        except OSError as error:
            raise ContractFreezeError("locked contract output cannot be read") from error
        if existing != encoded:
            raise ContractFreezeError("locked contract output already differs")
        return resolved.as_posix()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = resolved.with_suffix(resolved.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(resolved)
    except OSError as error:
        raise ContractFreezeError("locked contract output could not be written") from error
    return resolved.as_posix()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractFreezeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_freeze_inputs(path: Path) -> dict:
    """Load one canonical, exact-key input artifact for the freezer CLI."""

    resolved = Path(path).resolve()
    try:
        encoded = resolved.read_bytes()
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractFreezeError("freezer inputs are not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != set(CLI_INPUT_KEYS):
        raise ContractFreezeError("freezer input keys differ")
    if encoded_json(payload).encode("utf-8") != encoded:
        raise ContractFreezeError("freezer inputs are not canonical JSON")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = freeze_contract(**load_freeze_inputs(args.inputs))
    output = Path(write_frozen_contract(args.output, contract))
    print(
        json.dumps(
            {
                "output": str(output),
                "output_sha256": gate.sha256(output),
                "status": contract["status"],
                "training_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
