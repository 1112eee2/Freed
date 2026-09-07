"""Fail-closed entry point for the first production float NNUE trainer.

The trainer is developed while acquisition is active, but production rows may
not be opened until the separate contract gate emits a real PASS authorization.
This module therefore validates authorization before touching the frozen
contract, train/validation inventories, analysis payloads, or model outputs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import platform
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import EMPTY, is_king, legal_moves, parse_position  # noqa: E402
from makhos.eval_corpus import canonical_position_id  # noqa: E402
from makhos.game_analysis import player_name  # noqa: E402
from makhos.native import NativeSearch  # noqa: E402
from makhos.nnue_features import (  # noqa: E402
    clock_bucket,
    ordered_accumulator_features,
)
from scratch import nnue_trainer_contract_gate as gate  # noqa: E402


ANALYSES_DIRECTORY = gate.ROOT / "build" / "nnue_scaling_full_v1" / "analyses"
ANALYSIS_FORMAT = "thai-makhos-nnue-quiet-leaf-acquisition-v1"
TEACHER_BUDGETS_MS = [100, 500, 2000]
TEACHER_MAX_DEPTH = 90


class FloatTrainerError(RuntimeError):
    """Raised when the first float trainer cannot proceed safely."""


class FloatTrainerPaused(FloatTrainerError):
    """Raised after a safe epoch checkpoint when a run should be resumed."""

    def __init__(self, resume_directory: Path) -> None:
        self.resume_directory = Path(resume_directory).resolve()
        super().__init__(
            f"float trainer paused; resume from {self.resume_directory}"
        )


def _after_epoch_checkpoint(
    staging_directory: Path,
    size: int | str,
    seed: int,
    epoch: int,
) -> None:
    """Patchable interruption boundary after a durable epoch checkpoint."""

    del staging_directory, size, seed, epoch


@dataclass(frozen=True, slots=True)
class TrainingSample:
    game_id: str
    sample_id: str
    split: str
    side_to_move_features: tuple[int, ...]
    opponent_features: tuple[int, ...]
    teacher_target: float
    hce_target: float
    game_outcome_target: float | None
    exact_wdl_target: float | None
    phase_band: str
    king_count: int
    turn: str
    clock_bucket: int


def _load_authorization(path: Path) -> dict:
    try:
        snapshot = gate.load_json_snapshot(Path(path))
    except (OSError, gate.ContractGateError) as error:
        raise FloatTrainerError("trainer authorization is unreadable or invalid") from error
    payload = snapshot.payload
    if (
        payload.get("format") != gate.AUTHORIZATION_FORMAT
        or payload.get("kind") != "first-float-trainer-authorization"
        or payload.get("verdict") != "PASS"
        or payload.get("training_authorized") is not True
    ):
        raise FloatTrainerError("trainer authorization did not PASS")
    gates = payload.get("gates")
    if (
        set(payload) != gate.AUTHORIZATION_KEYS
        or not isinstance(gates, dict)
        or set(gates) != gate.AUTHORIZATION_GATE_KEYS
        or any(value is not True for value in gates.values())
        or payload.get("playing_code_changed") is not False
        or payload.get("model_trained") is not False
        or payload.get("sealed_test_manifest_read") is not False
        or payload.get("test_analysis_files_read") != 0
        or payload.get("sealed_test_labels_opened") is not False
    ):
        raise FloatTrainerError("trainer authorization artifact is incomplete")
    return payload


def _load_bound_snapshot(path: Path, expected_sha256: object, where: str):
    try:
        snapshot = gate.load_json_snapshot(Path(path))
    except (OSError, gate.ContractGateError) as error:
        raise FloatTrainerError(f"{where} is unreadable or invalid") from error
    if snapshot.sha256 != expected_sha256:
        raise FloatTrainerError(f"{where} binding differs from authorization")
    return snapshot


def _validate_contract_source(contract: dict) -> None:
    evidence = contract.get("evidence")
    if (
        contract.get("format") != gate.CONTRACT_FORMAT
        or contract.get("kind") != "first-float-nnue-v1"
        or contract.get("status") != "FROZEN"
        or not isinstance(evidence, dict)
    ):
        raise FloatTrainerError("frozen trainer contract is invalid")
    if evidence.get("trainer_source_sha256") != gate.sha256(Path(__file__)):
        raise FloatTrainerError("trainer source binding differs from frozen contract")


def _validate_engine_identity(authorization: dict, contract: dict) -> None:
    accepted_sha256 = gate.sha256(gate.ACCEPTED_LIBRARY)
    if not (
        authorization.get("accepted_library_sha256")
        == contract.get("accepted_library_sha256")
        == gate.EXPECTED_ACCEPTED_SHA256
        == accepted_sha256
    ):
        raise FloatTrainerError("accepted control binding differs")

    ruleset_sha256 = gate.sha256(gate.RULESET)
    if not (
        authorization.get("ruleset_sha256")
        == contract.get("ruleset_sha256")
        == ruleset_sha256
    ):
        raise FloatTrainerError("ruleset binding differs")


def _validate_contract_authorization_bindings(
    authorization: dict,
    contract: dict,
) -> None:
    evidence = contract["evidence"]
    bindings = {
        "final_data_audit_sha256": "final_data_audit_sha256",
        "development_manifest_sha256": "development_manifest_sha256",
        "analysis_set_sha256": "analysis_set_sha256",
        "full_suite_attestation_sha256": "full_suite_attestation_sha256",
        "train_inventory_sha256": "train_inventory_sha256",
        "validation_inventory_sha256": "validation_inventory_sha256",
    }
    if any(
        evidence.get(contract_key) != authorization.get(authorization_key)
        for contract_key, authorization_key in bindings.items()
    ):
        raise FloatTrainerError("contract evidence differs from authorization")
    dataset = contract.get("dataset")
    if not isinstance(dataset, dict) or (
        dataset.get("train_games") != authorization.get("train_games")
        or dataset.get("validation_games")
        != authorization.get("validation_games")
        or dataset.get("test_rows_included") is not False
        or dataset.get("test_game_ids_included") is not False
    ):
        raise FloatTrainerError(
            "dataset declaration differs from authorization"
        )
    targets = contract.get("targets")
    if (
        not isinstance(targets, dict)
        or targets.get("missing_label_policy")
        != "renormalize_available_components_per_sample"
        or targets.get("teacher_score", {}).get("normalization_kind") != "tanh"
        or targets.get("teacher_score", {}).get("loss") != "huber"
        or targets.get("game_outcome", {}).get("loss") != "mse"
        or targets.get("exact_wdl", {}).get("loss") != "mse"
        or contract.get("weighting", {}).get("position_weighting")
        != "uniform_within_source_game"
        or contract.get("optimizer", {}).get("name") != "AdamW"
        or contract.get("checkpoint", {}).get("metric") != "validation_loss"
        or contract.get("checkpoint", {}).get("mode") != "min"
    ):
        raise FloatTrainerError("frozen choices differ from executable trainer")


def _validate_inventory_content(
    inventory: dict,
    *,
    split: str,
    authorization: dict,
    contract: dict,
) -> set[str]:
    top_keys = {
        "format",
        "kind",
        "split",
        "development_manifest_sha256",
        "analysis_set_sha256",
        "games",
    }
    rows = inventory.get("games")
    dataset = contract["dataset"]
    if (
        set(inventory) != top_keys
        or inventory.get("format") != gate.INVENTORY_FORMAT
        or inventory.get("kind") != "trainer-input-inventory"
        or inventory.get("split") != split
        or inventory.get("development_manifest_sha256")
        != authorization["development_manifest_sha256"]
        or inventory.get("analysis_set_sha256")
        != authorization["analysis_set_sha256"]
        or not isinstance(rows, list)
        or len(rows) != dataset[f"{split}_games"]
    ):
        raise FloatTrainerError(f"{split} inventory content is invalid")

    row_keys = {
        "game_id",
        "game_sha256",
        "selection_sha256",
        "selected_positions",
        "analysis_file",
        "analysis_sha256",
    }
    game_ids: set[str] = set()
    selected_positions = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != row_keys:
            raise FloatTrainerError(f"{split} inventory content is invalid")
        game_id = row.get("game_id")
        selected = row.get("selected_positions")
        if (
            not isinstance(game_id, str)
            or not gate.GAME_ID.fullmatch(game_id)
            or game_id in game_ids
            or row.get("analysis_file") != f"{game_id}.analysis.json"
            or any(
                not isinstance(row.get(key), str)
                or not gate.HEX_64.fullmatch(row[key])
                for key in (
                    "game_sha256",
                    "selection_sha256",
                    "analysis_sha256",
                )
            )
            or isinstance(selected, bool)
            or not isinstance(selected, int)
            or selected < 0
        ):
            raise FloatTrainerError(f"{split} inventory content is invalid")
        game_ids.add(game_id)
        selected_positions += selected

    if (
        selected_positions != dataset[f"{split}_selected_rows"]
        or gate._game_id_set_sha256(game_ids)
        != dataset[f"{split}_game_ids_sha256"]
    ):
        raise FloatTrainerError(f"{split} inventory content is invalid")
    return game_ids


def _validate_new_output_directory(path: Path) -> Path:
    requested = Path(path)
    if requested.exists() or requested.is_symlink():
        raise FloatTrainerError("output directory must be new")
    resolved = requested.resolve()
    protected_roots = (
        gate.ROOT / ".agents",
        gate.ROOT / "makhos",
        gate.ROOT / "scratch",
        gate.ROOT / "tests",
        gate.ROOT / "build" / "nnue_scaling_full_v1",
    )
    if resolved == gate.ROOT or any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in protected_roots
    ):
        raise FloatTrainerError("output directory is inside a protected tree")
    return resolved


def _load_analysis_payloads(inventory: dict, *, split: str) -> list[dict]:
    directory = ANALYSES_DIRECTORY.resolve()
    payloads = []
    for row in inventory["games"]:
        path = (directory / row["analysis_file"]).resolve()
        if path.parent != directory or not path.is_file():
            raise FloatTrainerError(f"{split} analysis file is missing")
        if gate.sha256(path) != row["analysis_sha256"]:
            raise FloatTrainerError(f"{split} analysis hash differs")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise FloatTrainerError(f"{split} analysis is invalid JSON") from error
        positions = payload.get("positions") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("format") != ANALYSIS_FORMAT
            or payload.get("kind") != "game-analysis"
            or payload.get("game_id") != row["game_id"]
            or payload.get("game_sha256") != row["game_sha256"]
            or payload.get("split") != split
            or payload.get("selection_sha256") != row["selection_sha256"]
            or payload.get("accepted_library_sha256")
            != gate.EXPECTED_ACCEPTED_SHA256
            or payload.get("threads") != 1
            or payload.get("persistent_search") is not True
            or payload.get("clear_once_per_position_before_ascending_budgets")
            is not True
            or payload.get("budgets_ms") != TEACHER_BUDGETS_MS
            or payload.get("teacher_max_depth") != TEACHER_MAX_DEPTH
            or payload.get("rules_profile") != "project"
            or not isinstance(positions, list)
            or len(positions) != row["selected_positions"]
        ):
            raise FloatTrainerError(f"{split} analysis content is invalid")
        payloads.append(payload)
    return payloads


def _label_value(value: object) -> float | None:
    if value is None:
        return None
    if value == "loss":
        return -1.0
    if value == "draw":
        return 0.0
    if value == "win":
        return 1.0
    return None


def _valid_teacher_trace(row: dict) -> bool:
    searches = row.get("searches")
    if not isinstance(searches, list) or len(searches) != len(TEACHER_BUDGETS_MS):
        return False
    for expected_budget, search in zip(TEACHER_BUDGETS_MS, searches):
        if (
            not isinstance(search, dict)
            or search.get("budget_ms") != expected_budget
            or search.get("native_library_sha256")
            != gate.EXPECTED_ACCEPTED_SHA256
            or isinstance(search.get("score"), bool)
            or not isinstance(search.get("score"), int)
            or isinstance(search.get("depth"), bool)
            or not isinstance(search.get("depth"), int)
            or search["depth"] < 1
        ):
            return False
    delta = abs(searches[-1]["score"] - searches[-2]["score"])
    return (
        searches[-1]["score"] == row.get("teacher_score")
        and delta <= 50
        and row.get("last_two_score_delta") == delta
    )


def _extract_training_samples(
    analyses: list[dict],
    *,
    split: str,
    contract: dict,
    evaluator: NativeSearch,
) -> list[TrainingSample]:
    samples = []
    seen_ids = set()
    for analysis in analyses:
        for row in analysis["positions"]:
            if not isinstance(row, dict) or not isinstance(row.get("eligible"), bool):
                raise FloatTrainerError(f"{split} position content is invalid")
            if not row["eligible"]:
                continue
            teacher_score = row.get("teacher_score")
            reversible_plies = row.get("reversible_plies")
            ply = row.get("ply")
            if (
                isinstance(teacher_score, bool)
                or not isinstance(teacher_score, int)
                or abs(teacher_score) >= 999_000
                or row.get("gate_reason") != "accepted"
                or isinstance(reversible_plies, bool)
                or not isinstance(reversible_plies, int)
                or not 0 <= reversible_plies < 80
                or not isinstance(row.get("position"), str)
                or isinstance(ply, bool)
                or not isinstance(ply, int)
                or ply < 0
                or not _valid_teacher_trace(row)
            ):
                raise FloatTrainerError(f"{split} position content is invalid")
            try:
                state = parse_position(
                    row["position"],
                    reversible_plies=reversible_plies,
                    ply=ply,
                )
                moves = legal_moves(state)
                features = ordered_accumulator_features(state)
            except (TypeError, ValueError) as error:
                raise FloatTrainerError(
                    f"{split} position content is invalid"
                ) from error
            sample_id = canonical_position_id(state)
            game_outcome = row.get("game_outcome_from_side_to_move")
            exact_wdl = row.get("exact_wdl")
            exact_outcome = (
                exact_wdl.get("outcome") if isinstance(exact_wdl, dict) else None
            )
            piece_count = sum(piece != EMPTY for piece in state.board)
            king_count = sum(
                piece != EMPTY and is_king(piece) for piece in state.board
            )
            expected_phase = (
                "13_to_16"
                if piece_count >= 13
                else "9_to_12"
                if piece_count >= 9
                else "5_to_8"
            )
            history = row.get("history")
            legal_move_notation = [move.notation for move in moves]
            if (
                not moves
                or moves[0].is_capture
                or row.get("legal_moves") != legal_move_notation
                or row.get("split") != split
                or row.get("turn") != player_name(state.turn)
                or row.get("canonical_position_id") != sample_id
                or sample_id in seen_ids
                or row.get("piece_count") != piece_count
                or row.get("king_count") != king_count
                or row.get("phase_band") != expected_phase
                or not 5 <= piece_count <= 16
                or not isinstance(row.get("game_truncated"), bool)
                or (row["game_truncated"] and game_outcome is not None)
                or game_outcome not in (None, "loss", "draw", "win")
                or (exact_wdl is not None and not isinstance(exact_wdl, dict))
                or exact_outcome not in (None, "loss", "draw", "win")
                or (
                    isinstance(exact_wdl, dict)
                    and (
                        exact_outcome is None
                        or exact_wdl.get("perspective") != "side_to_move"
                    )
                )
                or not isinstance(history, dict)
                or isinstance(history.get("entries"), bool)
                or not isinstance(history.get("entries"), int)
                or history["entries"] < 1
                or isinstance(history.get("current_repetition_count"), bool)
                or not isinstance(history.get("current_repetition_count"), int)
                or history["current_repetition_count"] < 1
                or not isinstance(history.get("sha256"), str)
                or not gate.HEX_64.fullmatch(history["sha256"])
            ):
                raise FloatTrainerError(f"{split} position content is invalid")
            game_target = _label_value(game_outcome)
            exact_target = _label_value(exact_outcome)
            seen_ids.add(sample_id)
            teacher_contract = contract["targets"]["teacher_score"]
            clipped_score = max(
                -teacher_contract["clip_cp"],
                min(teacher_contract["clip_cp"], teacher_score),
            )
            hce_score = evaluator.evaluate(state)
            clipped_hce = max(
                -teacher_contract["clip_cp"],
                min(teacher_contract["clip_cp"], hce_score),
            )
            samples.append(
                TrainingSample(
                    game_id=analysis["game_id"],
                    sample_id=sample_id,
                    split=split,
                    side_to_move_features=features.side_to_move,
                    opponent_features=features.opponent,
                    teacher_target=math.tanh(
                        clipped_score
                        / teacher_contract["normalization_scale_cp"]
                    ),
                    hce_target=math.tanh(
                        clipped_hce
                        / teacher_contract["normalization_scale_cp"]
                    ),
                    game_outcome_target=game_target,
                    exact_wdl_target=exact_target,
                    phase_band=expected_phase,
                    king_count=king_count,
                    turn=row["turn"],
                    clock_bucket=clock_bucket(reversible_plies),
                )
            )
    if len(samples) != contract["dataset"][f"{split}_eligible_rows"]:
        raise FloatTrainerError(f"{split} eligible-row count differs")
    return samples


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: object) -> None:
    Path(path).write_bytes(_canonical_json_bytes(payload))


def _write_json_atomic(path: Path, payload: object) -> None:
    path = Path(path)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(_canonical_json_bytes(payload))
    temporary.replace(path)


def _load_canonical_json(path: Path, where: str) -> dict:
    try:
        raw = Path(path).read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FloatTrainerError(f"{where} is unreadable or invalid") from error
    if not isinstance(payload, dict) or raw != _canonical_json_bytes(payload):
        raise FloatTrainerError(f"{where} is not canonical")
    return payload


def _tensor_payload(tensor) -> dict:
    return {
        "dtype": str(tensor.dtype).removeprefix("torch."),
        "shape": list(tensor.shape),
        "values": tensor.detach().cpu().reshape(-1).tolist(),
    }


def _tensor_from_payload(payload: dict, torch):
    if set(payload) != {"dtype", "shape", "values"}:
        raise FloatTrainerError("checkpoint tensor declaration is invalid")
    dtype = getattr(torch, payload["dtype"], None)
    shape = payload["shape"]
    values = payload["values"]
    if dtype is None or not isinstance(shape, list) or not isinstance(values, list):
        raise FloatTrainerError("checkpoint tensor declaration is invalid")
    try:
        return torch.tensor(values, dtype=dtype).reshape(shape)
    except (TypeError, ValueError, RuntimeError) as error:
        raise FloatTrainerError("checkpoint tensor payload is invalid") from error


def _model_state_payload(state: dict) -> dict:
    return {
        name: _tensor_payload(value)
        for name, value in sorted(state.items())
    }


def _model_state_from_payload(payload: dict, torch) -> dict:
    if not isinstance(payload, dict):
        raise FloatTrainerError("checkpoint model state is invalid")
    return {
        name: _tensor_from_payload(value, torch)
        for name, value in payload.items()
    }


def _optimizer_state_payload(optimizer) -> dict:
    state = optimizer.state_dict()
    return {
        "state": [
            {
                "parameter": int(parameter),
                "values": {
                    name: _tensor_payload(value)
                    if hasattr(value, "detach")
                    else value
                    for name, value in sorted(values.items())
                },
            }
            for parameter, values in sorted(state["state"].items())
        ],
        "param_groups": state["param_groups"],
    }


def _optimizer_state_from_payload(payload: dict, torch) -> dict:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"state", "param_groups"}
        or not isinstance(payload["state"], list)
        or not isinstance(payload["param_groups"], list)
    ):
        raise FloatTrainerError("checkpoint optimizer state is invalid")
    state = {}
    for row in payload["state"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"parameter", "values"}
            or isinstance(row["parameter"], bool)
            or not isinstance(row["parameter"], int)
            or not isinstance(row["values"], dict)
        ):
            raise FloatTrainerError("checkpoint optimizer state is invalid")
        state[row["parameter"]] = {
            name: _tensor_from_payload(value, torch)
            if isinstance(value, dict) and set(value) == {"dtype", "shape", "values"}
            else value
            for name, value in row["values"].items()
        }
    return {"state": state, "param_groups": payload["param_groups"]}


def _run_stem(size: int | str, seed: int) -> str:
    size_name = "all" if size == "all" else f"{size:08d}"
    return f"size_{size_name}_seed_{seed}"


def _write_epoch_checkpoint(
    *,
    staging_directory: Path,
    contract_sha256: str,
    size: int | str,
    seed: int,
    epoch: int,
    model,
    optimizer,
    best_state: dict,
    best_epoch: int,
    best_loss: float,
    stale_epochs: int,
    history: list[dict],
) -> tuple[Path, str]:
    stem = _run_stem(size, seed)
    checkpoint_path = staging_directory / f"{stem}.checkpoint.json"
    checksum_path = staging_directory / f"{stem}.checkpoint.sha256.json"
    payload = {
        "format": "thai-makhos-float-nnue-checkpoint-v1",
        "kind": "deterministic-epoch-checkpoint",
        "contract_sha256": contract_sha256,
        "size": size,
        "seed": seed,
        "completed_epoch": epoch,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "stale_epochs": stale_epochs,
        "history": history,
        "model_state": _model_state_payload(model.state_dict()),
        "best_model_state": _model_state_payload(best_state),
        "optimizer_state": _optimizer_state_payload(optimizer),
    }
    _write_json_atomic(checkpoint_path, payload)
    checkpoint_sha256 = gate.sha256(checkpoint_path)
    _write_json_atomic(
        checksum_path,
        {
            "format": "thai-makhos-float-nnue-checkpoint-checksum-v1",
            "kind": "checkpoint-sha256-sidecar",
            "file": checkpoint_path.name,
            "sha256": checkpoint_sha256,
        },
    )
    return checkpoint_path, checkpoint_sha256


def _load_epoch_checkpoint(
    *,
    staging_directory: Path,
    contract_sha256: str,
    size: int | str,
    seed: int,
    torch,
) -> dict | None:
    stem = _run_stem(size, seed)
    checkpoint_path = staging_directory / f"{stem}.checkpoint.json"
    checksum_path = staging_directory / f"{stem}.checkpoint.sha256.json"
    if not checkpoint_path.exists() and not checksum_path.exists():
        return None
    if not checkpoint_path.is_file() or not checksum_path.is_file():
        raise FloatTrainerError("checkpoint pair is incomplete")
    checksum = _load_canonical_json(checksum_path, "checkpoint checksum")
    if checksum != {
        "format": "thai-makhos-float-nnue-checkpoint-checksum-v1",
        "kind": "checkpoint-sha256-sidecar",
        "file": checkpoint_path.name,
        "sha256": gate.sha256(checkpoint_path),
    }:
        raise FloatTrainerError("checkpoint checksum differs")
    payload = _load_canonical_json(checkpoint_path, "epoch checkpoint")
    expected_keys = {
        "format",
        "kind",
        "contract_sha256",
        "size",
        "seed",
        "completed_epoch",
        "best_epoch",
        "best_validation_loss",
        "stale_epochs",
        "history",
        "model_state",
        "best_model_state",
        "optimizer_state",
    }
    if (
        set(payload) != expected_keys
        or payload["format"] != "thai-makhos-float-nnue-checkpoint-v1"
        or payload["kind"] != "deterministic-epoch-checkpoint"
        or payload["contract_sha256"] != contract_sha256
        or payload["size"] != size
        or payload["seed"] != seed
        or isinstance(payload["completed_epoch"], bool)
        or not isinstance(payload["completed_epoch"], int)
        or payload["completed_epoch"] < 1
        or not isinstance(payload["history"], list)
        or len(payload["history"]) != payload["completed_epoch"]
    ):
        raise FloatTrainerError("epoch checkpoint binding is invalid")
    return {
        "completed_epoch": payload["completed_epoch"],
        "best_epoch": payload["best_epoch"],
        "best_validation_loss": payload["best_validation_loss"],
        "stale_epochs": payload["stale_epochs"],
        "history": payload["history"],
        "model_state": _model_state_from_payload(payload["model_state"], torch),
        "best_model_state": _model_state_from_payload(
            payload["best_model_state"], torch
        ),
        "optimizer_state": _optimizer_state_from_payload(
            payload["optimizer_state"], torch
        ),
        "checkpoint_sha256": checksum["sha256"],
        "checkpoint_file": checkpoint_path.name,
    }


def _learning_subset(
    samples: list[TrainingSample],
    size: int | str,
) -> list[TrainingSample]:
    ordered = sorted(
        samples,
        key=lambda sample: hashlib.sha256(
            f"{sample.game_id}:{sample.sample_id}".encode("ascii")
        ).digest(),
    )
    return ordered if size == "all" else ordered[:size]


def _regression_metrics(
    predictions: list[float],
    targets: list[float],
) -> dict:
    count = len(predictions)
    if count != len(targets) or not count:
        raise FloatTrainerError("metric inputs are empty or misaligned")
    errors = [prediction - target for prediction, target in zip(predictions, targets)]
    mean_prediction = math.fsum(predictions) / count
    mean_target = math.fsum(targets) / count
    prediction_variance = math.fsum(
        (prediction - mean_prediction) ** 2 for prediction in predictions
    )
    target_variance = math.fsum(
        (target - mean_target) ** 2 for target in targets
    )
    denominator = math.sqrt(prediction_variance * target_variance)
    pearson = (
        None
        if denominator == 0.0
        else math.fsum(
            (prediction - mean_prediction) * (target - mean_target)
            for prediction, target in zip(predictions, targets)
        )
        / denominator
    )
    return {
        "count": count,
        "mae": math.fsum(abs(error) for error in errors) / count,
        "rmse": math.sqrt(math.fsum(error * error for error in errors) / count),
        "bias": math.fsum(errors) / count,
        "pearson": pearson,
    }


def _prediction_report(
    predictions: list[float],
    samples: list[TrainingSample],
) -> dict:
    if len(predictions) != len(samples):
        raise FloatTrainerError("prediction report inputs are misaligned")

    def grouped(
        attribute: str,
        values: list[float],
        transform=lambda value: str(value),
    ) -> dict:
        groups = {}
        for index, sample in enumerate(samples):
            key = transform(getattr(sample, attribute))
            groups.setdefault(key, []).append(index)
        return {
            key: _regression_metrics(
                [values[index] for index in indices],
                [samples[index].teacher_target for index in indices],
            )
            for key, indices in sorted(groups.items())
        }

    game_indices = [
        index
        for index, sample in enumerate(samples)
        if sample.game_outcome_target is not None
    ]
    exact_indices = [
        index
        for index, sample in enumerate(samples)
        if sample.exact_wdl_target is not None
    ]

    def label_metrics(indices: list[int], attribute: str) -> dict:
        if not indices:
            return {"count": 0, "mse": None}
        return {
            "count": len(indices),
            "mse": math.fsum(
                (
                    predictions[index]
                    - float(getattr(samples[index], attribute))
                )
                ** 2
                for index in indices
            )
            / len(indices),
        }

    teacher_targets = [sample.teacher_target for sample in samples]
    hce_predictions = [sample.hce_target for sample in samples]
    teacher_metrics = _regression_metrics(predictions, teacher_targets)
    hce_metrics = _regression_metrics(hce_predictions, teacher_targets)
    return {
        "teacher": teacher_metrics,
        "hce_teacher": hce_metrics,
        "teacher_mae_improvement_vs_hce": (
            hce_metrics["mae"] - teacher_metrics["mae"]
        ),
        "game_outcome": label_metrics(
            game_indices,
            "game_outcome_target",
        ),
        "exact_wdl": label_metrics(exact_indices, "exact_wdl_target"),
        "by_phase": grouped("phase_band", predictions),
        "hce_by_phase": grouped("phase_band", hce_predictions),
        "by_king_presence": grouped(
            "king_count",
            predictions,
            lambda value: "with_kings" if value else "no_kings",
        ),
        "hce_by_king_presence": grouped(
            "king_count",
            hce_predictions,
            lambda value: "with_kings" if value else "no_kings",
        ),
        "by_turn": grouped("turn", predictions),
        "hce_by_turn": grouped("turn", hce_predictions),
        "by_clock_bucket": grouped("clock_bucket", predictions),
        "hce_by_clock_bucket": grouped("clock_bucket", hce_predictions),
    }


def _train_one_run(
    *,
    train_samples: list[TrainingSample],
    validation_samples: list[TrainingSample],
    contract: dict,
    contract_sha256: str,
    seed: int,
    size: int | str,
    staging_directory: Path,
) -> dict:
    try:
        import numpy
        import torch
        from torch import nn
        from torch.nn import functional as functional
    except ImportError as error:
        raise FloatTrainerError("PyTorch dependency is unavailable") from error

    dependencies = contract["reproducibility"]["dependencies"]
    if (
        dependencies.get("python") != platform.python_version()
        or dependencies.get("numpy") != numpy.__version__
        or dependencies.get("torch") != torch.__version__
    ):
        raise FloatTrainerError(
            "runtime dependencies differ from frozen contract"
        )

    stem = _run_stem(size, seed)
    completed_run_path = staging_directory / f"{stem}.run.json"
    if completed_run_path.is_file():
        completed = _load_canonical_json(completed_run_path, "completed run")
        model_path = staging_directory / str(completed.get("model_file", ""))
        checkpoint_path = staging_directory / str(
            completed.get("checkpoint_file", "")
        )
        if (
            completed.get("size") != size
            or completed.get("seed") != seed
            or not model_path.is_file()
            or gate.sha256(model_path) != completed.get("model_sha256")
            or not checkpoint_path.is_file()
            or gate.sha256(checkpoint_path)
            != completed.get("checkpoint_sha256")
        ):
            raise FloatTrainerError("completed run binding is invalid")
        return completed

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)

    feature_spec = contract["feature_spec"]
    network = contract["network"]

    class FloatNNUE(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.feature_weights = nn.Parameter(
                torch.empty(
                    feature_spec["input_dimensions"],
                    network["feature_width"],
                    dtype=torch.float32,
                )
            )
            self.feature_bias = nn.Parameter(
                torch.zeros(network["feature_width"], dtype=torch.float32)
            )
            self.hidden = nn.Linear(
                network["concatenated_width"],
                network["hidden_width"],
            )
            self.output = nn.Linear(network["hidden_width"], 1)
            nn.init.uniform_(
                self.feature_weights,
                -1.0 / math.sqrt(feature_spec["input_dimensions"]),
                1.0 / math.sqrt(feature_spec["input_dimensions"]),
            )

        def _accumulator(self, flat, offsets):
            summed = functional.embedding_bag(
                flat,
                self.feature_weights,
                offsets,
                mode="sum",
            )
            return torch.clamp(summed + self.feature_bias, 0.0, 1.0)

        def forward(self, stm_flat, stm_offsets, opponent_flat, opponent_offsets):
            combined = torch.cat(
                (
                    self._accumulator(stm_flat, stm_offsets),
                    self._accumulator(opponent_flat, opponent_offsets),
                ),
                dim=1,
            )
            hidden = torch.clamp(self.hidden(combined), 0.0, 1.0)
            return self.output(hidden).squeeze(1)

    def packed_features(batch: list[TrainingSample], attribute: str):
        flat = []
        offsets = []
        for sample in batch:
            offsets.append(len(flat))
            flat.extend(getattr(sample, attribute))
        return (
            torch.tensor(flat, dtype=torch.long),
            torch.tensor(offsets, dtype=torch.long),
        )

    targets = contract["targets"]
    mix = targets["loss_mix"]
    weighting = contract["weighting"]

    def batch_loss(
        model,
        batch: list[TrainingSample],
        game_counts: dict[str, int],
    ):
        stm_flat, stm_offsets = packed_features(
            batch, "side_to_move_features"
        )
        opponent_flat, opponent_offsets = packed_features(
            batch, "opponent_features"
        )
        predictions = model(
            stm_flat,
            stm_offsets,
            opponent_flat,
            opponent_offsets,
        )
        teacher = torch.tensor(
            [sample.teacher_target for sample in batch],
            dtype=torch.float32,
        )
        teacher_loss = functional.huber_loss(
            predictions,
            teacher,
            reduction="none",
            delta=targets["teacher_score"]["loss_parameter"],
        )
        loss_numerator = mix["teacher_score"] * teacher_loss
        active_mix = torch.full_like(predictions, mix["teacher_score"])

        for attribute, mix_key in (
            ("game_outcome_target", "game_outcome"),
            ("exact_wdl_target", "exact_wdl"),
        ):
            available = torch.tensor(
                [getattr(sample, attribute) is not None for sample in batch],
                dtype=torch.bool,
            )
            values = torch.tensor(
                [
                    0.0
                    if getattr(sample, attribute) is None
                    else getattr(sample, attribute)
                    for sample in batch
                ],
                dtype=torch.float32,
            )
            component = (predictions - values).square()
            component_weight = mix[mix_key] * available.to(torch.float32)
            loss_numerator = loss_numerator + component_weight * component
            active_mix = active_mix + component_weight

        per_sample = loss_numerator / active_mix
        sample_weights = torch.tensor(
            [
                weighting["phase_weights"][sample.phase_band]
                / game_counts[sample.game_id]
                * (
                    weighting["exact_wdl_multiplier"]
                    if sample.exact_wdl_target is not None
                    else 1.0
                )
                for sample in batch
            ],
            dtype=torch.float32,
        )
        return (per_sample * sample_weights).sum() / sample_weights.sum()

    def counts_by_game(samples: list[TrainingSample]) -> dict[str, int]:
        counts = {}
        for sample in samples:
            counts[sample.game_id] = counts.get(sample.game_id, 0) + 1
        return counts


    def predict(model, samples: list[TrainingSample]) -> list[float]:
        predictions = []
        model.eval()
        with torch.no_grad():
            for start in range(0, len(samples), batch_size):
                batch = samples[start : start + batch_size]
                stm_flat, stm_offsets = packed_features(
                    batch,
                    "side_to_move_features",
                )
                opponent_flat, opponent_offsets = packed_features(
                    batch,
                    "opponent_features",
                )
                predictions.extend(
                    float(value)
                    for value in model(
                        stm_flat,
                        stm_offsets,
                        opponent_flat,
                        opponent_offsets,
                    )
                )
        return predictions

    model = FloatNNUE()
    optimizer_contract = contract["optimizer"]
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=optimizer_contract["learning_rate"],
        weight_decay=optimizer_contract["weight_decay"],
    )
    batch_size = optimizer_contract["batch_size"]
    train_game_counts = counts_by_game(train_samples)
    validation_game_counts = counts_by_game(validation_samples)
    best_loss = math.inf
    best_epoch = 0
    best_state = None
    stale_epochs = 0
    history = []
    start_epoch = 1

    resumed = _load_epoch_checkpoint(
        staging_directory=staging_directory,
        contract_sha256=contract_sha256,
        size=size,
        seed=seed,
        torch=torch,
    )
    if resumed is not None:
        model.load_state_dict(resumed["model_state"])
        optimizer.load_state_dict(resumed["optimizer_state"])
        best_state = resumed["best_model_state"]
        best_epoch = resumed["best_epoch"]
        best_loss = resumed["best_validation_loss"]
        stale_epochs = resumed["stale_epochs"]
        history = resumed["history"]
        start_epoch = resumed["completed_epoch"] + 1

    schedule = optimizer_contract["schedule"]

    def learning_rate_for_epoch(epoch: int) -> float:
        base = optimizer_contract["learning_rate"]
        warmup = schedule["warmup_epochs"]
        if warmup and epoch <= warmup:
            return base * epoch / warmup
        if schedule["kind"] == "constant":
            return base
        decay_epochs = optimizer_contract["max_epochs"] - warmup
        progress = (epoch - warmup) / decay_epochs
        return base * 0.5 * (1.0 + math.cos(math.pi * progress))

    checkpoint_path = None
    checkpoint_sha256 = None
    for epoch in range(start_epoch, optimizer_contract["max_epochs"] + 1):
        learning_rate = learning_rate_for_epoch(epoch)
        for parameter_group in optimizer.param_groups:
            parameter_group["lr"] = learning_rate
        generator = torch.Generator(device="cpu")
        generator.manual_seed(seed + epoch)
        order = torch.randperm(len(train_samples), generator=generator).tolist()
        model.train()
        train_loss_sum = 0.0
        train_batches = 0
        for start in range(0, len(order), batch_size):
            batch = [train_samples[index] for index in order[start : start + batch_size]]
            optimizer.zero_grad(set_to_none=True)
            loss = batch_loss(model, batch, train_game_counts)
            loss.backward()
            optimizer.step()
            train_loss_sum += float(loss.detach())
            train_batches += 1

        model.eval()
        with torch.no_grad():
            validation_loss = float(
                batch_loss(model, validation_samples, validation_game_counts)
            )
        train_loss = train_loss_sum / train_batches
        history.append(
            {
                "epoch": epoch,
                "learning_rate": learning_rate,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        checkpoint = contract["checkpoint"]
        should_stop = False
        if validation_loss < best_loss - checkpoint["min_delta"]:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= checkpoint["early_stop_patience"]:
                should_stop = True
        if best_state is None:
            raise FloatTrainerError("training produced no validation checkpoint")
        checkpoint_path, checkpoint_sha256 = _write_epoch_checkpoint(
            staging_directory=staging_directory,
            contract_sha256=contract_sha256,
            size=size,
            seed=seed,
            epoch=epoch,
            model=model,
            optimizer=optimizer,
            best_state=best_state,
            best_epoch=best_epoch,
            best_loss=best_loss,
            stale_epochs=stale_epochs,
            history=history,
        )
        _after_epoch_checkpoint(staging_directory, size, seed, epoch)
        if should_stop:
            break

    if best_state is None:
        raise FloatTrainerError("training produced no validation checkpoint")
    if checkpoint_path is None or checkpoint_sha256 is None:
        loaded_checkpoint = _load_epoch_checkpoint(
            staging_directory=staging_directory,
            contract_sha256=contract_sha256,
            size=size,
            seed=seed,
            torch=torch,
        )
        if loaded_checkpoint is None:
            raise FloatTrainerError("completed training checkpoint is missing")
        checkpoint_path = staging_directory / loaded_checkpoint["checkpoint_file"]
        checkpoint_sha256 = loaded_checkpoint["checkpoint_sha256"]
    model.load_state_dict(best_state)
    train_metrics = _prediction_report(
        predict(model, train_samples),
        train_samples,
    )
    validation_metrics = _prediction_report(
        predict(model, validation_samples),
        validation_samples,
    )
    model_name = f"{stem}.model.json"
    model_payload = {
        "format": "thai-makhos-float-nnue-model-v1",
        "kind": "float-nnue-checkpoint",
        "contract_sha256": contract_sha256,
        "feature_spec": feature_spec,
        "network": network,
        "size": size,
        "seed": seed,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "state": {
            name: {
                "shape": list(value.shape),
                "values": value.detach().cpu().reshape(-1).tolist(),
            }
            for name, value in sorted(model.state_dict().items())
        },
    }
    model_path = staging_directory / model_name
    _write_json_atomic(model_path, model_payload)
    completed = {
        "size": size,
        "seed": seed,
        "epochs_completed": len(history),
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "model_file": model_name,
        "model_sha256": gate.sha256(model_path),
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": checkpoint_sha256,
    }
    _write_json_atomic(completed_run_path, completed)
    return completed


def _execute_training(
    *,
    train_samples: list[TrainingSample],
    validation_samples: list[TrainingSample],
    contract: dict,
    contract_sha256: str,
    authorization_sha256: str,
    output_directory: Path,
    resume_directory: Path | None,
) -> dict:
    parent = output_directory.parent
    if not parent.is_dir():
        raise FloatTrainerError("output parent directory does not exist")
    manifest_payload = {
        "format": "thai-makhos-float-nnue-resume-manifest-v1",
        "kind": "transactional-training-staging",
        "status": "IN_PROGRESS",
        "authorization_sha256": authorization_sha256,
        "contract_sha256": contract_sha256,
        "output_directory": str(output_directory),
    }
    created_staging = resume_directory is None
    if resume_directory is None:
        staging_directory = Path(
            tempfile.mkdtemp(
                prefix=f".{output_directory.name}.staging-",
                dir=parent,
            )
        )
        _write_json_atomic(
            staging_directory / "resume_manifest.json",
            manifest_payload,
        )
    else:
        staging_directory = Path(resume_directory).resolve()
        if (
            not staging_directory.is_dir()
            or staging_directory.parent != parent
            or not staging_directory.name.startswith(
                f".{output_directory.name}.staging-"
            )
            or _load_canonical_json(
                staging_directory / "resume_manifest.json",
                "resume manifest",
            )
            != manifest_payload
        ):
            raise FloatTrainerError("resume directory binding is invalid")
    try:
        runs = []
        for size in contract["learning_curve"]["sizes"]:
            subset = _learning_subset(train_samples, size)
            if not subset:
                raise FloatTrainerError("learning-curve subset is empty")
            for seed in contract["reproducibility"]["seeds"]:
                runs.append(
                    _train_one_run(
                        train_samples=subset,
                        validation_samples=validation_samples,
                        contract=contract,
                        contract_sha256=contract_sha256,
                        seed=seed,
                        size=size,
                        staging_directory=staging_directory,
                    )
                )
        result = {
            "format": "thai-makhos-float-nnue-training-result-v1",
            "kind": "first-float-nnue-training",
            "verdict": "PASS",
            "training_authorized": True,
            "model_trained": True,
            "playing_code_changed": False,
            "authorization_sha256": authorization_sha256,
            "contract_sha256": contract_sha256,
            "accepted_library_sha256": gate.EXPECTED_ACCEPTED_SHA256,
            "ruleset_sha256": gate.sha256(gate.RULESET),
            "train_eligible_rows": len(train_samples),
            "validation_eligible_rows": len(validation_samples),
            "sealed_test_manifest_read": False,
            "test_analysis_files_read": 0,
            "sealed_test_labels_opened": False,
            "runs": runs,
        }
        _write_json_atomic(staging_directory / "training_result.json", result)
        if output_directory.exists():
            raise FloatTrainerError("output directory appeared during training")
        completed_manifest = dict(manifest_payload)
        completed_manifest["status"] = "COMPLETE"
        _write_json_atomic(
            staging_directory / "resume_manifest.json",
            completed_manifest,
        )
        staging_directory.replace(output_directory)
        return result
    except FloatTrainerPaused:
        raise
    except BaseException:
        if created_staging and staging_directory.exists():
            shutil.rmtree(staging_directory)
        raise


def run_training(
    *,
    authorization_path: Path,
    contract_path: Path,
    train_inventory_path: Path,
    validation_inventory_path: Path,
    output_directory: Path,
    resume_directory: Path | None = None,
) -> dict:
    """Run the contract-bound float trainer after fail-closed authorization.

    The remaining implementation is intentionally unreachable until subsequent
    vertical slices validate every authorization binding and protected path.
    """

    authorization = _load_authorization(authorization_path)
    authorization_sha256 = gate.sha256(Path(authorization_path))
    contract_snapshot = _load_bound_snapshot(
        contract_path,
        authorization["contract_sha256"],
        "contract",
    )
    train_inventory_snapshot = _load_bound_snapshot(
        train_inventory_path,
        authorization["train_inventory_sha256"],
        "train inventory",
    )
    validation_inventory_snapshot = _load_bound_snapshot(
        validation_inventory_path,
        authorization["validation_inventory_sha256"],
        "validation inventory",
    )
    _validate_contract_source(contract_snapshot.payload)
    _validate_engine_identity(authorization, contract_snapshot.payload)
    _validate_contract_authorization_bindings(
        authorization,
        contract_snapshot.payload,
    )
    train_ids = _validate_inventory_content(
        train_inventory_snapshot.payload,
        split="train",
        authorization=authorization,
        contract=contract_snapshot.payload,
    )
    validation_ids = _validate_inventory_content(
        validation_inventory_snapshot.payload,
        split="validation",
        authorization=authorization,
        contract=contract_snapshot.payload,
    )
    if train_ids & validation_ids:
        raise FloatTrainerError("train and validation inventories overlap")
    resolved_output_directory = _validate_new_output_directory(output_directory)
    train_analyses = _load_analysis_payloads(
        train_inventory_snapshot.payload,
        split="train",
    )
    validation_analyses = _load_analysis_payloads(
        validation_inventory_snapshot.payload,
        split="validation",
    )
    try:
        with NativeSearch(
            gate.ACCEPTED_LIBRARY,
            hash_power=12,
            persistent=False,
        ) as evaluator:
            train_samples = _extract_training_samples(
                train_analyses,
                split="train",
                contract=contract_snapshot.payload,
                evaluator=evaluator,
            )
            validation_samples = _extract_training_samples(
                validation_analyses,
                split="validation",
                contract=contract_snapshot.payload,
                evaluator=evaluator,
            )
    except FloatTrainerError:
        raise
    except (OSError, RuntimeError) as error:
        raise FloatTrainerError("accepted HCE baseline evaluation failed") from error
    if {sample.sample_id for sample in train_samples} & {
        sample.sample_id for sample in validation_samples
    }:
        raise FloatTrainerError("train and validation samples overlap")
    return _execute_training(
        train_samples=train_samples,
        validation_samples=validation_samples,
        contract=contract_snapshot.payload,
        contract_sha256=contract_snapshot.sha256,
        authorization_sha256=authorization_sha256,
        output_directory=resolved_output_directory,
        resume_directory=resume_directory,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--train-inventory", type=Path, required=True)
    parser.add_argument("--validation-inventory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--resume-directory", type=Path)
    args = parser.parse_args()
    result = run_training(
        authorization_path=args.authorization,
        contract_path=args.contract,
        train_inventory_path=args.train_inventory,
        validation_inventory_path=args.validation_inventory,
        output_directory=args.output_directory,
        resume_directory=args.resume_directory,
    )
    result_path = args.output_directory.resolve() / "training_result.json"
    print(
        json.dumps(
            {
                "output_directory": str(args.output_directory.resolve()),
                "result_sha256": gate.sha256(result_path),
                "runs": len(result["runs"]),
                "sealed_test_manifest_read": False,
                "verdict": result["verdict"],
                "test_analysis_files_read": 0,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
