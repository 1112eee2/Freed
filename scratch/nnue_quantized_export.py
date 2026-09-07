"""Deterministic Phase-4 exporter and parity audit for the KEEP float NNUE.

This module is offline tooling.  It never changes the playing path and may read
only the contract-bound validation inventory plus its development analyses.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
from typing import Final

import numpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import parse_position  # noqa: E402
from makhos.nnue_features import (  # noqa: E402
    feature_spec_payload,
    ordered_accumulator_features,
)
from scratch import nnue_trainer_contract_gate as gate  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    canonical_json_sha256,
    encoded_json,
)


CONTRACT_FORMAT: Final = "thai-makhos-nnue-quantization-contract-v1"
REPORT_FORMAT: Final = "thai-makhos-nnue-quantized-export-report-v1"
MAGIC: Final = b"MKNNUE1\0"
VERSION: Final = 1
HEADER_STRUCT: Final = struct.Struct("<8s11I32s32s32sQ32s")
HEX_64: Final = re.compile(r"^[0-9A-F]{64}$")
MAX_ACTIVE_FEATURES: Final = 17
ANALYSES_DIRECTORY: Final = ROOT / "build" / "nnue_scaling_full_v1" / "analyses"

EXPECTED_FEATURE_SPEC: Final = feature_spec_payload()
EXPECTED_FEATURE_SPEC_SHA256: Final = canonical_json_sha256(EXPECTED_FEATURE_SPEC)
EXPECTED_RULESET_SHA256: Final = gate.sha256(gate.RULESET)
EXPECTED_NETWORK: Final = {
    "architecture_count": 1,
    "perspective_accumulators": 2,
    "feature_width": 128,
    "concatenated_width": 256,
    "hidden_width": 32,
    "output_width": 1,
    "output_perspective": "side_to_move",
    "policy_head": False,
}
EXPECTED_DIMENSIONS: Final = {
    "input_dimensions": 137,
    "feature_width": 128,
    "hidden_width": 32,
    "output_width": 1,
}
EXPECTED_SCALES: Final = {
    "feature": 2048,
    "activation": 127,
    "hidden_weight": 256,
    "output_weight": 192,
}
EXPECTED_INTEGER_TYPES: Final = {
    "feature_weights": "int16",
    "feature_bias": "int16",
    "feature_accumulator": "int16",
    "dense_weights": "int8",
    "dense_activations": "int8",
    "dense_biases": "int32",
    "dense_sums": "int32",
}
EXPECTED_PAYLOAD_ORDER: Final = (
    "feature_weights",
    "feature_bias",
    "hidden.weight",
    "hidden.bias",
    "output.weight",
    "output.bias",
)
CONTRACT_KEYS: Final = {
    "format",
    "kind",
    "status",
    "source_model_sha256",
    "float_contract_sha256",
    "exporter_source_sha256",
    "validation_inventory_sha256",
    "feature_spec_sha256",
    "ruleset_sha256",
    "dimensions",
    "scales",
    "integer_types",
    "payload_order",
    "nonterminal_cp_bound",
    "parity_limits",
    "sealed_test_labels_opened",
    "playing_code_changed",
}
PARITY_LIMIT_KEYS: Final = {"mae", "rmse", "max_abs", "sign_mismatch_rate"}


class QuantizedExportError(RuntimeError):
    """Raised when export/parity evidence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class QuantizedModel:
    feature_weights: numpy.ndarray
    feature_bias: numpy.ndarray
    hidden_weight: numpy.ndarray
    hidden_bias: numpy.ndarray
    output_weight: numpy.ndarray
    output_bias: numpy.ndarray


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _require_sha256(value: object, where: str) -> str:
    if not isinstance(value, str) or HEX_64.fullmatch(value) is None:
        raise QuantizedExportError(f"{where} is not an uppercase SHA-256")
    return value


def _finite_nonnegative(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuantizedExportError(f"{where} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise QuantizedExportError(f"{where} must be finite and nonnegative")
    return result


def validate_contract(
    contract: dict,
    *,
    source_model_sha256: str,
    exporter_source_sha256: str | None = None,
) -> None:
    if not isinstance(contract, dict) or set(contract) != CONTRACT_KEYS:
        raise QuantizedExportError("quantization contract keys differ")
    if (
        contract["format"] != CONTRACT_FORMAT
        or contract["kind"] != "first-quantized-nnue-v1"
        or contract["status"] != "FROZEN"
        or contract["sealed_test_labels_opened"] is not False
        or contract["playing_code_changed"] is not False
        or contract["dimensions"] != EXPECTED_DIMENSIONS
        or contract["scales"] != EXPECTED_SCALES
        or contract["integer_types"] != EXPECTED_INTEGER_TYPES
        or contract["payload_order"] != list(EXPECTED_PAYLOAD_ORDER)
        or contract["feature_spec_sha256"] != EXPECTED_FEATURE_SPEC_SHA256
        or contract["ruleset_sha256"] != EXPECTED_RULESET_SHA256
        or contract["nonterminal_cp_bound"] != 30_000
    ):
        raise QuantizedExportError("quantization contract differs from v1")
    for key in (
        "source_model_sha256",
        "float_contract_sha256",
        "exporter_source_sha256",
        "validation_inventory_sha256",
    ):
        _require_sha256(contract[key], f"contract.{key}")
    if contract["source_model_sha256"] != source_model_sha256:
        raise QuantizedExportError("source model binding differs")
    if (
        exporter_source_sha256 is not None
        and contract["exporter_source_sha256"] != exporter_source_sha256
    ):
        raise QuantizedExportError("exporter source binding differs")
    limits = contract["parity_limits"]
    if not isinstance(limits, dict) or set(limits) != PARITY_LIMIT_KEYS:
        raise QuantizedExportError("parity limit keys differ")
    for key, value in limits.items():
        _finite_nonnegative(value, f"parity_limits.{key}")
    if any(limits[key] <= 0 for key in PARITY_LIMIT_KEYS):
        raise QuantizedExportError("parity limits must be positive")


def _state_array(model: dict, name: str, shape: tuple[int, ...]) -> numpy.ndarray:
    state = model.get("state") if isinstance(model, dict) else None
    row = state.get(name) if isinstance(state, dict) else None
    if not isinstance(row, dict) or row.get("shape") != list(shape):
        raise QuantizedExportError(f"float model tensor shape differs: {name}")
    values = row.get("values")
    expected = int(numpy.prod(shape))
    if not isinstance(values, list) or len(values) != expected:
        raise QuantizedExportError(f"float model tensor length differs: {name}")
    try:
        result = numpy.asarray(values, dtype=numpy.float64).reshape(shape)
    except (TypeError, ValueError, OverflowError) as error:
        raise QuantizedExportError(f"float model tensor is invalid: {name}") from error
    if not numpy.isfinite(result).all():
        raise QuantizedExportError(f"float model tensor is non-finite: {name}")
    return result


def _validate_float_model(model: dict) -> None:
    if (
        not isinstance(model, dict)
        or model.get("format") != "thai-makhos-float-nnue-model-v1"
        or model.get("kind") != "float-nnue-checkpoint"
        or model.get("feature_spec") != EXPECTED_FEATURE_SPEC
        or model.get("network") != EXPECTED_NETWORK
    ):
        raise QuantizedExportError("float model identity or architecture differs")


def _round_half_away(values: numpy.ndarray, scale: int) -> numpy.ndarray:
    scaled = values * float(scale)
    return numpy.where(
        scaled >= 0.0,
        numpy.floor(scaled + 0.5),
        numpy.ceil(scaled - 0.5),
    ).astype(numpy.int64)


def _quantize_checked(
    values: numpy.ndarray,
    scale: int,
    dtype,
    where: str,
) -> numpy.ndarray:
    quantized = _round_half_away(values, scale)
    bounds = numpy.iinfo(dtype)
    if quantized.min(initial=0) < bounds.min or quantized.max(initial=0) > bounds.max:
        raise QuantizedExportError(f"{where} exceeds {numpy.dtype(dtype).name}")
    return quantized.astype(dtype)


def quantize_model(model: dict, contract: dict) -> QuantizedModel:
    _validate_float_model(model)
    scales = contract.get("scales")
    if scales != EXPECTED_SCALES:
        raise QuantizedExportError("quantization scales differ")
    feature_weights = _state_array(model, "feature_weights", (137, 128))
    feature_bias = _state_array(model, "feature_bias", (128,))
    hidden_weight = _state_array(model, "hidden.weight", (32, 256))
    hidden_bias = _state_array(model, "hidden.bias", (32,))
    output_weight = _state_array(model, "output.weight", (1, 32))
    output_bias = _state_array(model, "output.bias", (1,))
    feature_scale = scales["feature"]
    activation_scale = scales["activation"]
    hidden_scale = scales["hidden_weight"]
    output_scale = scales["output_weight"]
    quantized = QuantizedModel(
        feature_weights=_quantize_checked(
            feature_weights, feature_scale, numpy.int16, "feature weights"
        ),
        feature_bias=_quantize_checked(
            feature_bias, feature_scale, numpy.int16, "feature bias"
        ),
        hidden_weight=_quantize_checked(
            hidden_weight, hidden_scale, numpy.int8, "hidden weights"
        ),
        hidden_bias=_quantize_checked(
            hidden_bias,
            activation_scale * hidden_scale,
            numpy.int32,
            "hidden bias",
        ),
        output_weight=_quantize_checked(
            output_weight, output_scale, numpy.int8, "output weights"
        ),
        output_bias=_quantize_checked(
            output_bias,
            activation_scale * output_scale,
            numpy.int32,
            "output bias",
        ),
    )
    if not prove_overflow_bounds(quantized, contract)["all_safe"]:
        raise QuantizedExportError("quantized model overflow proof failed")
    return quantized


def _indices(value: tuple[int, ...] | list[int]) -> numpy.ndarray:
    result = numpy.asarray(value, dtype=numpy.int64)
    if (
        result.ndim != 1
        or len(result) < 1
        or len(result) > MAX_ACTIVE_FEATURES
        or (result < 0).any()
        or (result >= 137).any()
        or len(set(result.tolist())) != len(result)
    ):
        raise QuantizedExportError("active feature indices are invalid")
    return result


def float_infer(
    model: dict,
    side_to_move_indices: tuple[int, ...] | list[int],
    opponent_indices: tuple[int, ...] | list[int],
) -> float:
    _validate_float_model(model)
    feature_weights = _state_array(model, "feature_weights", (137, 128))
    feature_bias = _state_array(model, "feature_bias", (128,))
    hidden_weight = _state_array(model, "hidden.weight", (32, 256))
    hidden_bias = _state_array(model, "hidden.bias", (32,))
    output_weight = _state_array(model, "output.weight", (1, 32))
    output_bias = _state_array(model, "output.bias", (1,))
    first = numpy.clip(
        feature_weights[_indices(side_to_move_indices)].sum(axis=0) + feature_bias,
        0.0,
        1.0,
    )
    second = numpy.clip(
        feature_weights[_indices(opponent_indices)].sum(axis=0) + feature_bias,
        0.0,
        1.0,
    )
    hidden = numpy.clip(
        hidden_weight @ numpy.concatenate((first, second)) + hidden_bias,
        0.0,
        1.0,
    )
    return float((output_weight @ hidden + output_bias)[0])


def _activation_from_accumulator(values: numpy.ndarray, input_scale: int) -> numpy.ndarray:
    activation_scale = EXPECTED_SCALES["activation"]
    clipped = numpy.clip(values.astype(numpy.int64), 0, input_scale)
    return ((clipped * activation_scale + input_scale // 2) // input_scale).astype(
        numpy.int8
    )


def quantized_infer(
    model: QuantizedModel,
    side_to_move_indices: tuple[int, ...] | list[int],
    opponent_indices: tuple[int, ...] | list[int],
) -> float:
    feature_scale = EXPECTED_SCALES["feature"]
    activation_scale = EXPECTED_SCALES["activation"]
    hidden_scale = EXPECTED_SCALES["hidden_weight"]
    output_scale = EXPECTED_SCALES["output_weight"]
    first_sum = (
        model.feature_weights[_indices(side_to_move_indices)]
        .astype(numpy.int32)
        .sum(axis=0)
        + model.feature_bias.astype(numpy.int32)
    )
    second_sum = (
        model.feature_weights[_indices(opponent_indices)]
        .astype(numpy.int32)
        .sum(axis=0)
        + model.feature_bias.astype(numpy.int32)
    )
    if (
        numpy.abs(first_sum).max(initial=0) > 32767
        or numpy.abs(second_sum).max(initial=0) > 32767
    ):
        raise QuantizedExportError("feature accumulator overflow")
    first = _activation_from_accumulator(first_sum, feature_scale)
    second = _activation_from_accumulator(second_sum, feature_scale)
    hidden_sum = (
        model.hidden_weight.astype(numpy.int32)
        @ numpy.concatenate((first, second)).astype(numpy.int32)
        + model.hidden_bias.astype(numpy.int32)
    )
    hidden_activation = _activation_from_accumulator(
        hidden_sum,
        activation_scale * hidden_scale,
    )
    output_sum = int(
        (
            model.output_weight.astype(numpy.int32)
            @ hidden_activation.astype(numpy.int32)
            + model.output_bias.astype(numpy.int32)
        ).item()
    )
    return output_sum / float(activation_scale * output_scale)


def prove_overflow_bounds(model: QuantizedModel, contract: dict) -> dict:
    del contract
    feature_column_max = numpy.abs(model.feature_weights.astype(numpy.int64)).max(
        axis=0
    )
    feature_bounds = (
        numpy.abs(model.feature_bias.astype(numpy.int64))
        + MAX_ACTIVE_FEATURES * feature_column_max
    )
    feature_max = int(feature_bounds.max(initial=0))
    activation_scale = EXPECTED_SCALES["activation"]
    hidden_row_bounds = (
        numpy.abs(model.hidden_bias.astype(numpy.int64))
        + activation_scale
        * numpy.abs(model.hidden_weight.astype(numpy.int64)).sum(axis=1)
    )
    hidden_max = int(hidden_row_bounds.max(initial=0))
    output_max = int(
        numpy.abs(model.output_bias.astype(numpy.int64)).max(initial=0)
        + activation_scale
        * numpy.abs(model.output_weight.astype(numpy.int64)).sum()
    )
    dense_max = max(hidden_max, output_max)
    return {
        "max_active_features": MAX_ACTIVE_FEATURES,
        "feature_accumulator_abs_max": feature_max,
        "hidden_sum_abs_max": hidden_max,
        "output_sum_abs_max": output_max,
        "dense_sum_abs_max": dense_max,
        "int16_limit": 32767,
        "int32_limit": 2147483647,
        "all_safe": feature_max <= 32767 and dense_max <= 2147483647,
    }


def _payload_bytes(model: QuantizedModel) -> bytes:
    return b"".join(
        (
            model.feature_weights.astype("<i2", copy=False).tobytes(order="C"),
            model.feature_bias.astype("<i2", copy=False).tobytes(order="C"),
            model.hidden_weight.astype("i1", copy=False).tobytes(order="C"),
            model.hidden_bias.astype("<i4", copy=False).tobytes(order="C"),
            model.output_weight.astype("i1", copy=False).tobytes(order="C"),
            model.output_bias.astype("<i4", copy=False).tobytes(order="C"),
        )
    )


def serialize_quantized_model(model: QuantizedModel, contract: dict) -> bytes:
    payload = _payload_bytes(model)
    header = HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        HEADER_STRUCT.size,
        EXPECTED_DIMENSIONS["input_dimensions"],
        EXPECTED_DIMENSIONS["feature_width"],
        EXPECTED_DIMENSIONS["hidden_width"],
        EXPECTED_DIMENSIONS["output_width"],
        EXPECTED_SCALES["feature"],
        EXPECTED_SCALES["activation"],
        EXPECTED_SCALES["hidden_weight"],
        EXPECTED_SCALES["output_weight"],
        contract["nonterminal_cp_bound"],
        bytes.fromhex(contract["feature_spec_sha256"]),
        bytes.fromhex(contract["ruleset_sha256"]),
        bytes.fromhex(contract["source_model_sha256"]),
        len(payload),
        hashlib.sha256(payload).digest(),
    )
    return header + payload


def parse_quantized_model(encoded: bytes, contract: dict) -> QuantizedModel:
    if len(encoded) < HEADER_STRUCT.size:
        raise QuantizedExportError("quantized model is truncated")
    unpacked = HEADER_STRUCT.unpack_from(encoded)
    (
        magic,
        version,
        header_size,
        input_dimensions,
        feature_width,
        hidden_width,
        output_width,
        feature_scale,
        activation_scale,
        hidden_scale,
        output_scale,
        cp_bound,
        feature_sha,
        ruleset_sha,
        source_model_sha,
        payload_length,
        payload_sha,
    ) = unpacked
    if (
        magic != MAGIC
        or version != VERSION
        or header_size != HEADER_STRUCT.size
        or [input_dimensions, feature_width, hidden_width, output_width]
        != [137, 128, 32, 1]
        or [feature_scale, activation_scale, hidden_scale, output_scale]
        != [2048, 127, 256, 192]
        or cp_bound != contract["nonterminal_cp_bound"]
        or feature_sha.hex().upper() != contract["feature_spec_sha256"]
        or ruleset_sha.hex().upper() != contract["ruleset_sha256"]
        or source_model_sha.hex().upper() != contract["source_model_sha256"]
    ):
        raise QuantizedExportError("quantized model header is incompatible")
    payload = encoded[HEADER_STRUCT.size :]
    if len(payload) != payload_length or hashlib.sha256(payload).digest() != payload_sha:
        raise QuantizedExportError("quantized model payload is corrupt or truncated")
    expected_length = 137 * 128 * 2 + 128 * 2 + 32 * 256 + 32 * 4 + 32 + 4
    if len(payload) != expected_length:
        raise QuantizedExportError("quantized model payload length differs")
    offset = 0

    def take(dtype, shape):
        nonlocal offset
        count = int(numpy.prod(shape))
        size = numpy.dtype(dtype).itemsize * count
        result = numpy.frombuffer(payload, dtype=dtype, count=count, offset=offset).copy()
        offset += size
        return result.reshape(shape)

    model = QuantizedModel(
        feature_weights=take("<i2", (137, 128)),
        feature_bias=take("<i2", (128,)),
        hidden_weight=take("i1", (32, 256)),
        hidden_bias=take("<i4", (32,)),
        output_weight=take("i1", (1, 32)),
        output_bias=take("<i4", (1,)),
    )
    if offset != len(payload) or not prove_overflow_bounds(model, contract)["all_safe"]:
        raise QuantizedExportError("quantized model failed overflow validation")
    return model


def ordered_feature_indices(state) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Adapt the named feature-oracle result to the exporter inference seam."""

    ordered = ordered_accumulator_features(state)
    return ordered.side_to_move, ordered.opponent


def _validation_feature_rows(inventory: dict) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    if (
        not isinstance(inventory, dict)
        or inventory.get("format") != gate.INVENTORY_FORMAT
        or inventory.get("kind") != "trainer-input-inventory"
        or inventory.get("split") != "validation"
        or not isinstance(inventory.get("games"), list)
    ):
        raise QuantizedExportError("validation inventory is invalid")
    rows = []
    for game in inventory["games"]:
        if not isinstance(game, dict):
            raise QuantizedExportError("validation inventory game is invalid")
        game_id = game.get("game_id")
        name = game.get("analysis_file")
        if name != f"{game_id}.analysis.json":
            raise QuantizedExportError("validation analysis name differs")
        path = (ANALYSES_DIRECTORY / name).resolve()
        if path.parent != ANALYSES_DIRECTORY.resolve() or gate.sha256(path) != game.get(
            "analysis_sha256"
        ):
            raise QuantizedExportError("validation analysis hash differs")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise QuantizedExportError("validation analysis is invalid JSON") from error
        positions = payload.get("positions") if isinstance(payload, dict) else None
        if (
            payload.get("game_id") != game_id
            or payload.get("split") != "validation"
            or payload.get("game_sha256") != game.get("game_sha256")
            or payload.get("selection_sha256") != game.get("selection_sha256")
            or not isinstance(positions, list)
            or len(positions) != game.get("selected_positions")
        ):
            raise QuantizedExportError("validation analysis binding differs")
        for position in positions:
            if not isinstance(position, dict) or position.get("eligible") is not True:
                continue
            state = parse_position(
                position.get("position"),
                reversible_plies=position.get("reversible_plies"),
                ply=position.get("ply"),
            )
            first, second = ordered_feature_indices(state)
            rows.append((tuple(first), tuple(second)))
    return rows


def _parity_report(model: dict, quantized: QuantizedModel, rows) -> dict:
    errors = []
    sign_mismatches = 0
    for first, second in rows:
        floating = float_infer(model, first, second)
        integer = quantized_infer(quantized, first, second)
        errors.append(abs(floating - integer))
        sign_mismatches += int((floating < 0.0) != (integer < 0.0))
    if not errors:
        raise QuantizedExportError("validation parity set is empty")
    values = numpy.asarray(errors, dtype=numpy.float64)
    return {
        "count": len(errors),
        "mae": float(values.mean()),
        "rmse": float(numpy.sqrt(numpy.mean(values * values))),
        "max_abs": float(values.max()),
        "p50_abs": float(numpy.quantile(values, 0.50)),
        "p90_abs": float(numpy.quantile(values, 0.90)),
        "p99_abs": float(numpy.quantile(values, 0.99)),
        "sign_mismatches": sign_mismatches,
        "sign_mismatch_rate": sign_mismatches / len(errors),
    }


def _safe_new_output(path: Path, where: str) -> Path:
    requested = Path(path)
    if requested.exists() or requested.is_symlink():
        raise QuantizedExportError(f"{where} must be new")
    resolved = requested.resolve()
    protected = (
        ROOT / ".agents",
        ROOT / "makhos",
        ROOT / "native",
        ROOT / "scratch",
        ROOT / "tests",
        ROOT / "build" / "nnue_scaling_full_v1",
    )
    if resolved == ROOT or any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in protected
    ):
        raise QuantizedExportError(f"{where} is inside a protected tree")
    if not resolved.parent.is_dir():
        raise QuantizedExportError(f"{where} parent does not exist")
    return resolved


def run_export(
    *,
    quantization_contract_path: Path,
    float_model_path: Path,
    validation_inventory_path: Path,
    binary_output: Path,
    report_output: Path,
) -> dict:
    binary_output = _safe_new_output(binary_output, "binary output")
    report_output = _safe_new_output(report_output, "report output")
    if binary_output == report_output:
        raise QuantizedExportError("binary and report outputs must differ")
    contract_snapshot = gate.load_json_snapshot(quantization_contract_path)
    model_snapshot = gate.load_json_snapshot(float_model_path)
    validation_snapshot = gate.load_json_snapshot(validation_inventory_path)
    exporter_sha = gate.sha256(Path(__file__))
    validate_contract(
        contract_snapshot.payload,
        source_model_sha256=model_snapshot.sha256,
        exporter_source_sha256=exporter_sha,
    )
    contract = contract_snapshot.payload
    model = model_snapshot.payload
    if (
        model.get("contract_sha256") != contract["float_contract_sha256"]
        or validation_snapshot.sha256 != contract["validation_inventory_sha256"]
    ):
        raise QuantizedExportError("float contract or validation binding differs")
    quantized = quantize_model(model, contract)
    encoded_a = serialize_quantized_model(quantized, contract)
    encoded_b = serialize_quantized_model(quantized, contract)
    if encoded_a != encoded_b:
        raise QuantizedExportError("quantized serialization is not deterministic")
    loaded = parse_quantized_model(encoded_a, contract)
    rows = _validation_feature_rows(validation_snapshot.payload)
    parity = _parity_report(model, loaded, rows)
    limits = contract["parity_limits"]
    parity_pass = all(parity[key] <= limits[key] for key in PARITY_LIMIT_KEYS)
    bounds = prove_overflow_bounds(loaded, contract)
    if not parity_pass or not bounds["all_safe"]:
        raise QuantizedExportError("quantized parity or overflow gate failed")
    report = {
        "format": REPORT_FORMAT,
        "kind": "quantized-export-and-validation-parity",
        "verdict": "PASS",
        "playing_code_changed": False,
        "source_model_sha256": model_snapshot.sha256,
        "float_contract_sha256": contract["float_contract_sha256"],
        "quantization_contract_sha256": contract_snapshot.sha256,
        "exporter_source_sha256": exporter_sha,
        "validation_inventory_sha256": validation_snapshot.sha256,
        "binary_sha256": _sha256_bytes(encoded_a),
        "binary_bytes": len(encoded_a),
        "header": {
            "magic": "MKNNUE1",
            "version": VERSION,
            "header_bytes": HEADER_STRUCT.size,
            "payload_bytes": len(encoded_a) - HEADER_STRUCT.size,
            "feature_spec_sha256": contract["feature_spec_sha256"],
            "ruleset_sha256": contract["ruleset_sha256"],
        },
        "scales": contract["scales"],
        "integer_types": contract["integer_types"],
        "overflow_bounds": bounds,
        "parity_limits": limits,
        "validation_parity": parity,
        "deterministic_serialization_byte_identical": True,
        "corrupt_or_truncated_parse_fails_closed": True,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "sealed_test_labels_opened": False,
        "next_gate": "native scalar loader and bit-exact inference parity",
    }
    report_bytes = encoded_json(report).replace("\n", os.linesep).encode("utf-8")
    binary_tmp = binary_output.with_suffix(binary_output.suffix + ".tmp")
    report_tmp = report_output.with_suffix(report_output.suffix + ".tmp")
    if binary_tmp.exists() or report_tmp.exists():
        raise QuantizedExportError("temporary output already exists")
    try:
        binary_tmp.write_bytes(encoded_a)
        report_tmp.write_bytes(report_bytes)
        binary_tmp.replace(binary_output)
        report_tmp.replace(report_output)
    except OSError as error:
        for temporary in (binary_tmp, report_tmp):
            if temporary.exists():
                temporary.unlink()
        raise QuantizedExportError("quantized outputs could not be committed") from error
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quantization-contract", type=Path, required=True)
    parser.add_argument("--float-model", type=Path, required=True)
    parser.add_argument("--validation-inventory", type=Path, required=True)
    parser.add_argument("--binary-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    report = run_export(
        quantization_contract_path=args.quantization_contract,
        float_model_path=args.float_model,
        validation_inventory_path=args.validation_inventory,
        binary_output=args.binary_output,
        report_output=args.report_output,
    )
    print(
        json.dumps(
            {
                "binary_output": str(args.binary_output.resolve()),
                "binary_sha256": report["binary_sha256"],
                "report_output": str(args.report_output.resolve()),
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
