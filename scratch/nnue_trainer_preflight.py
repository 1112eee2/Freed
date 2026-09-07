"""Run a deterministic tiny-fixture preflight for the first NNUE trainer.

This is gate infrastructure, not production training.  It reads only a frozen
contract, a final-audit metadata artifact, a trainer-source file, and an
explicit synthetic fixture.  The tiny linear exercise proves the operational
properties required by the authorizer (overfit, repeat/resume, checksum, and
protected-read guard) while discarding all fixture model state before returning.
It never reads an analysis payload or a sealed-test file and never authorizes a
training run.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.nnue_features import INPUT_DIMENSIONS
from scratch import nnue_trainer_contract_gate as gate
from scratch.nnue_quiet_leaf_acquire import encoded_json


FIXTURE_FORMAT: Final = "thai-makhos-nnue-trainer-fixture-v1"
FIXTURE_KIND: Final = "tiny-linear-overfit-fixture"
PREFLIGHT_KIND: Final = "tiny-fixture-trainer-readiness"
LEARNING_RATE: Final = 0.25
EPOCHS: Final = 128
CHECKPOINT_EPOCH: Final = 64
OVERFIT_TOLERANCE: Final = 1e-6


class TrainerPreflightError(RuntimeError):
    """Raised when a preflight cannot produce trustworthy PASS evidence."""


class ProtectedReadError(TrainerPreflightError):
    """Raised when preflight attempts to open a production/sealed path."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TrainerPreflightError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _exact_keys(value: Mapping, expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        raise TrainerPreflightError(
            f"{where} keys differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _mapping(value: object, where: str) -> dict:
    if not isinstance(value, Mapping):
        raise TrainerPreflightError(f"{where} must be an object")
    return deepcopy(dict(value))


def _canonical_json(path: Path, where: str) -> tuple[dict, bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise TrainerPreflightError(f"unable to read {where}: {path}") from error
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainerPreflightError(f"{where} is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise TrainerPreflightError(f"{where} must contain a JSON object")
    try:
        canonical_lf = encoded_json(payload).encode("utf-8")
        canonical_native = encoded_json(payload).replace("\n", os.linesep).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise TrainerPreflightError(f"{where} contains non-canonical values") from error
    if raw not in {canonical_lf, canonical_native}:
        raise TrainerPreflightError(f"{where} is not canonical JSON")
    return payload, raw, _sha256_bytes(raw)


def _safe_path(path: Path, where: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.exists() or not resolved.is_file():
        raise TrainerPreflightError(f"{where} is not an existing file: {resolved}")
    return resolved


class ProtectedReadGuard:
    """Audit-hook guard for production analyses, sealed data, and status."""

    def __init__(self, production_root: Path) -> None:
        root = production_root.resolve()
        self.production_root = root
        self.forbidden_exact = {
            root / "sealed_test_selection_manifest.json",
            root / "full_run_supervisor_status.json",
        }
        self.forbidden_roots = {
            root / "analyses",
            root / "test_analyses",
            root / "sealed_test_analyses",
        }
        self.blocked_paths: list[Path] = []
        self.active = True

    def check(self, raw_path: object) -> None:
        if isinstance(raw_path, int):
            return
        try:
            path = Path(os.fsdecode(raw_path)).resolve()
        except (OSError, TypeError, ValueError):
            return
        forbidden = path in self.forbidden_exact or any(
            path == root or path.is_relative_to(root)
            for root in self.forbidden_roots
        )
        if forbidden:
            self.blocked_paths.append(path)
            raise ProtectedReadError(f"protected production path opened: {path}")

    def hook(self, event: str, args: tuple) -> None:
        if event == "open" and args:
            self.check(args[0])

    def probe(self) -> None:
        """Exercise the guard against a synthetic forbidden path."""

        probe = self.production_root / "sealed_test_analyses" / "guard-probe.json"
        try:
            with probe.open("rb"):
                pass
        except ProtectedReadError:
            return
        except OSError as error:
            raise TrainerPreflightError("protected-read probe was not intercepted") from error
        raise TrainerPreflightError("protected-read probe unexpectedly succeeded")


_AUDIT_GUARDS: list[ProtectedReadGuard] = []
_AUDIT_HOOK_INSTALLED = False


def _install_guard(guard_instance: ProtectedReadGuard) -> None:
    global _AUDIT_HOOK_INSTALLED
    for active in _AUDIT_GUARDS:
        active.active = False
    _AUDIT_GUARDS.append(guard_instance)
    if not _AUDIT_HOOK_INSTALLED:
        def audit_hook(event: str, args: tuple) -> None:
            for active in tuple(_AUDIT_GUARDS):
                if active.active:
                    active.hook(event, args)

        sys.addaudithook(audit_hook)
        _AUDIT_HOOK_INSTALLED = True


def _validate_fixture(payload: Mapping) -> list[tuple[tuple[int, ...], float]]:
    _exact_keys(payload, {"format", "kind", "samples"}, "fixture")
    if payload["format"] != FIXTURE_FORMAT or payload["kind"] != FIXTURE_KIND:
        raise TrainerPreflightError("fixture format or kind changed")
    samples = payload["samples"]
    if not isinstance(samples, list) or len(samples) < 2:
        raise TrainerPreflightError("fixture needs at least two samples")
    result: list[tuple[tuple[int, ...], float]] = []
    for number, sample in enumerate(samples):
        sample_map = _mapping(sample, f"fixture sample {number}")
        _exact_keys(sample_map, {"feature_indices", "target"}, f"fixture sample {number}")
        indices = sample_map["feature_indices"]
        if (
            not isinstance(indices, list)
            or not indices
            or len(set(indices)) != len(indices)
            or any(
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < INPUT_DIMENSIONS
                for index in indices
            )
        ):
            raise TrainerPreflightError(f"fixture sample {number} has invalid features")
        target = sample_map["target"]
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            raise TrainerPreflightError(f"fixture sample {number} target is not numeric")
        target_float = float(target)
        if not math.isfinite(target_float):
            raise TrainerPreflightError(f"fixture sample {number} target is not finite")
        result.append((tuple(indices), target_float))
    return result


def _sample_order(seed: int, epoch: int, count: int) -> list[int]:
    order = list(range(count))
    random.Random((seed << 32) ^ epoch).shuffle(order)
    return order


def _initial_weights(seed: int) -> list[float]:
    rng = random.Random(seed ^ 0x5EED5EED)
    return [(rng.random() - 0.5) * 0.02 for _ in range(INPUT_DIMENSIONS)]


def _train_epochs(
    samples: list[tuple[tuple[int, ...], float]],
    seed: int,
    weights: list[float],
    start_epoch: int,
    end_epoch: int,
) -> list[float]:
    for epoch in range(start_epoch, end_epoch):
        for sample_index in _sample_order(seed, epoch, len(samples)):
            feature_indices, target = samples[sample_index]
            prediction = sum(weights[index] for index in feature_indices)
            error = prediction - target
            step = LEARNING_RATE * error / len(feature_indices)
            for index in feature_indices:
                weights[index] -= step
    return weights


def _state_bytes(weights: list[float], epoch: int) -> bytes:
    return encoded_json({"epoch": epoch, "weights": weights}).encode("utf-8")


def _max_abs_error(samples: list[tuple[tuple[int, ...], float]], weights: list[float]) -> float:
    return max(
        abs(sum(weights[index] for index in feature_indices) - target)
        for feature_indices, target in samples
    )


def _resume_from_checkpoint(checkpoint_bytes: bytes) -> tuple[int, list[float]]:
    try:
        payload = json.loads(checkpoint_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainerPreflightError("checkpoint is not valid JSON") from error
    _exact_keys(payload, {"epoch", "weights"}, "checkpoint")
    if (
        isinstance(payload["epoch"], bool)
        or not isinstance(payload["epoch"], int)
        or payload["epoch"] != CHECKPOINT_EPOCH
        or not isinstance(payload["weights"], list)
        or len(payload["weights"]) != INPUT_DIMENSIONS
    ):
        raise TrainerPreflightError("checkpoint shape or epoch changed")
    weights = []
    for value in payload["weights"]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TrainerPreflightError("checkpoint weight is not numeric")
        value = float(value)
        if not math.isfinite(value):
            raise TrainerPreflightError("checkpoint weight is not finite")
        weights.append(value)
    return payload["epoch"], weights


def _validate_contract_and_bindings(
    contract: Mapping,
    contract_sha256: str,
    final_audit: Mapping,
    final_audit_sha256: str,
    trainer_source_sha256: str,
    fixture_sha256: str,
) -> list[int]:
    if (
        contract.get("format") != gate.CONTRACT_FORMAT
        or contract.get("kind") != "first-float-nnue-v1"
        or contract.get("status") != "FROZEN"
    ):
        raise TrainerPreflightError("contract is not a frozen v1 contract")
    evidence = _mapping(contract.get("evidence"), "contract.evidence")
    if evidence.get("final_data_audit_sha256") != final_audit_sha256:
        raise TrainerPreflightError("contract/final-audit binding differs")
    if evidence.get("trainer_source_sha256") != trainer_source_sha256:
        raise TrainerPreflightError("contract/trainer-source binding differs")
    if evidence.get("trainer_fixture_sha256") != fixture_sha256:
        raise TrainerPreflightError("contract/fixture binding differs")
    if final_audit.get("verdict") != "PASS" or final_audit.get("trainer_authorized_by_this_artifact") is not False:
        raise TrainerPreflightError("final audit is not a non-authorizing PASS")
    reproducibility = _mapping(contract.get("reproducibility"), "contract.reproducibility")
    seeds = reproducibility.get("seeds")
    if (
        not isinstance(seeds, list)
        or len(seeds) < 2
        or len(set(seeds)) != len(seeds)
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise TrainerPreflightError("contract seeds are invalid")
    if contract_sha256 != _sha256_bytes(encoded_json(dict(contract)).encode("utf-8")):
        raise TrainerPreflightError("contract hash is not canonical")
    return list(seeds)


def _write_locked(path: Path, payload: Mapping) -> None:
    encoded = encoded_json(dict(payload)).encode("utf-8")
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise TrainerPreflightError("existing preflight artifact cannot be read") from error
        if existing != encoded:
            raise TrainerPreflightError("existing preflight artifact differs")
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(path)
    except OSError as error:
        raise TrainerPreflightError("preflight artifact could not be written") from error


def run_preflight(
    *,
    contract_path: Path,
    final_audit_path: Path,
    trainer_source_path: Path,
    fixture_path: Path,
    output_path: Path | None = None,
    production_root: Path | None = None,
) -> dict:
    """Run the synthetic preflight and optionally write its locked artifact."""

    production_root = (
        production_root or ROOT / "build" / "nnue_scaling_full_v1"
    ).resolve()
    output = Path(output_path).resolve() if output_path is not None else None
    forbidden_outputs = (
        production_root,
        ROOT / "makhos",
        ROOT / "native",
        ROOT / "schemas",
        ROOT / "scratch",
        ROOT / "tests",
        ROOT / "web",
    )
    if output is not None and any(
        output == root or output.is_relative_to(root) for root in forbidden_outputs
    ):
        raise TrainerPreflightError(f"preflight output is inside a protected tree: {output}")
    if output is not None and output.suffix.casefold() != ".json":
        raise TrainerPreflightError("preflight output must be a .json artifact")

    guard = ProtectedReadGuard(production_root)
    _install_guard(guard)
    contract_path = _safe_path(Path(contract_path), "contract")
    final_audit_path = _safe_path(Path(final_audit_path), "final audit")
    trainer_source_path = _safe_path(Path(trainer_source_path), "trainer source")
    fixture_path = _safe_path(Path(fixture_path), "fixture")
    contract, _, contract_sha256 = _canonical_json(contract_path, "contract")
    final_audit, _, final_audit_sha256 = _canonical_json(final_audit_path, "final audit")
    fixture, _, fixture_sha256 = _canonical_json(fixture_path, "fixture")
    trainer_source_sha256 = _sha256_bytes(trainer_source_path.read_bytes())
    samples = _validate_fixture(fixture)
    seeds = _validate_contract_and_bindings(
        contract,
        contract_sha256,
        final_audit,
        final_audit_sha256,
        trainer_source_sha256,
        fixture_sha256,
    )

    overfit = True
    repeat = True
    resume = True
    checksum = True
    for seed in seeds:
        full_weights = _train_epochs(
            samples, seed, _initial_weights(seed), 0, EPOCHS
        )
        full_bytes = _state_bytes(full_weights, EPOCHS)
        if _max_abs_error(samples, full_weights) > OVERFIT_TOLERANCE:
            overfit = False

        repeat_weights = _train_epochs(
            samples, seed, _initial_weights(seed), 0, EPOCHS
        )
        repeat = repeat and full_bytes == _state_bytes(repeat_weights, EPOCHS)

        checkpoint_weights = _train_epochs(
            samples, seed, _initial_weights(seed), 0, CHECKPOINT_EPOCH
        )
        checkpoint_bytes = _state_bytes(checkpoint_weights, CHECKPOINT_EPOCH)
        checkpoint_checksum = _sha256_bytes(checkpoint_bytes)
        try:
            checkpoint_payload = json.loads(checkpoint_bytes.decode("utf-8"))
            checkpoint_roundtrip = encoded_json(checkpoint_payload).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            checkpoint_roundtrip = b""
        checksum = checksum and (
            checkpoint_bytes == checkpoint_roundtrip
            and checkpoint_checksum == _sha256_bytes(checkpoint_roundtrip)
        )
        resumed_epoch, resumed_weights = _resume_from_checkpoint(checkpoint_bytes)
        resumed_weights = _train_epochs(
            samples, seed, resumed_weights, resumed_epoch, EPOCHS
        )
        resume = resume and full_bytes == _state_bytes(resumed_weights, EPOCHS)

    guard.probe()
    artifact = {
        "format": gate.PREFLIGHT_FORMAT,
        "kind": PREFLIGHT_KIND,
        "verdict": "PASS" if all((overfit, repeat, resume, checksum)) else "FAIL",
        "contract_sha256": contract_sha256,
        "final_data_audit_sha256": final_audit_sha256,
        "trainer_source_sha256": trainer_source_sha256,
        "fixture_sha256": fixture_sha256,
        "seeds_tested": seeds,
        "tiny_fixture_overfit": overfit,
        "deterministic_repeat_byte_identical": repeat,
        "deterministic_resume_byte_identical": resume,
        "checkpoint_checksum_verified": checksum,
        "sealed_guard_tests_passed": bool(guard.blocked_paths),
        "development_rows_read": 0,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "production_model_trained": False,
        "fixture_model_discarded": True,
        "training_run_authorized_by_this_artifact": False,
    }
    if artifact["verdict"] != "PASS" or not artifact["sealed_guard_tests_passed"]:
        raise TrainerPreflightError("tiny-fixture preflight did not PASS")
    if output is not None:
        _write_locked(output, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--final-audit", type=Path, required=True)
    parser.add_argument("--trainer-source", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--production-root", type=Path)
    args = parser.parse_args()
    artifact = run_preflight(
        contract_path=args.contract,
        final_audit_path=args.final_audit,
        trainer_source_path=args.trainer_source,
        fixture_path=args.fixture,
        output_path=args.output,
        production_root=args.production_root,
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": _sha256_bytes(args.output.resolve().read_bytes()),
                "seeds_tested": artifact["seeds_tested"],
                "verdict": artifact["verdict"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
