"""One-time, model-selection-forbidden evaluation of the frozen NNUE v1.

Preflight never opens the sealed manifest.  Analysis is resumable by whole
source game and may be split across six processes.  Finalization is allowed
only after every committed test game has a validated accepted-teacher report.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import parse_position  # noqa: E402
from makhos.native import (  # noqa: E402
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.workload_isolation import BatchWorkLease  # noqa: E402
from scratch import nnue_quantized_export as exporter  # noqa: E402
from scratch import nnue_quiet_leaf_acquire as acquisition  # noqa: E402
EXPECTED = {
    "accepted_library": "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD",
    "candidate_library": "32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79",
    "quantized_model": "07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C",
    "float_model": "5FD87ABD2F9CAAC81045A58AEA420445B90CAC9A70D5FFBDFC5694BA1338CA4E",
    "quantization_contract": "68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF",
    "trainer_contract": "890B1B6AF0D8DF0E5FEE4F4ABA111E531A33B47837D77CA1D852CA6656F5C12E",
    "partition_commitment": "6DA3EE1F841AA8A1A1E9E8B3ECA57E39ADB4DEC9F68AB3E83F95EC3B96E45DB3",
    "sealed_manifest": "B1F2350607A95ACF3F04B5667236EE10B7D2ABCF0DE3EB7FA737E72D96338115",
}
EXPECTED_TEST_GAMES = 1_533
EXPECTED_TEST_POSITIONS = 41_698
BUDGETS_MS = (100, 500, 2000)
HASH_MB = 256
SHARD_COUNT = 6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_locked(path: Path, payload: object) -> None:
    encoded = canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise RuntimeError(f"locked artifact differs: {path}")
        return
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_json(path: Path, where: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value


def default_paths() -> dict[str, Path]:
    phase = ROOT / "build" / "nnue_phase1_evidence"
    work = ROOT / "build" / "nnue_scaling_full_v1"
    return {
        "accepted_library": ROOT / "build" / "makhos_native_accepted.dll",
        "candidate_library": (
            ROOT
            / "build"
            / "nnue_search_v1_r5"
            / "makhos_native_nnue_candidate_v1.dll"
        ),
        "quantized_model": ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue",
        "float_model": ROOT / "build" / "nnue_float_v1" / "size_all_seed_20280002.model.json",
        "quantization_contract": phase / "quantization_contract_v2.json",
        "trainer_contract": phase / "trainer_contract_v3_a.json",
        "partition_commitment": work / "selection_partition_commitment.json",
        "sealed_manifest": work / "sealed_test_selection_manifest.json",
        "full_suite": phase / "full_suite_attestation_v17.json",
        "tablebase_provenance": ROOT / "TABLEBASE_PROVENANCE.json",
        "output_dir": ROOT / "build" / "nnue_sealed_test_v1",
    }


def resolved_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        name: Path(getattr(args, name)).resolve()
        for name in default_paths()
    }


def verify_frozen_inputs(paths: dict[str, Path]) -> tuple[dict, dict, dict]:
    for name, expected in EXPECTED.items():
        path = paths[name]
        if not path.is_file():
            raise FileNotFoundError(path)
        if name == "sealed_manifest":
            continue
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"{name} identity changed: expected {expected}, got {actual}"
            )

    commitment = load_json(paths["partition_commitment"], "partition commitment")
    if (
        commitment.get("sealed_test_manifest_sha256") != EXPECTED["sealed_manifest"]
        or commitment.get("sealed_test_games") != EXPECTED_TEST_GAMES
        or commitment.get("sealed_test_selected_positions") != EXPECTED_TEST_POSITIONS
        or commitment.get("test_analysis_files_may_be_read") is not False
    ):
        raise RuntimeError("sealed partition commitment changed")

    contract = load_json(paths["trainer_contract"], "trainer contract")
    policy = contract.get("sealed_test_policy")
    if not isinstance(policy, dict) or (
        policy.get("manifest_sha256") != EXPECTED["sealed_manifest"]
        or policy.get("labels_opened") is not False
        or policy.get("model_selection_forbidden") is not True
        or policy.get("open_count_limit") != 1
    ):
        raise RuntimeError("trainer sealed-test policy changed")

    if not paths["full_suite"].is_file():
        raise FileNotFoundError(paths["full_suite"])
    suite = load_json(paths["full_suite"], "full-suite attestation")
    from scratch import nnue_full_suite_attestation as full_suite

    current_source_sha256 = full_suite.inventory_sha256(
        full_suite.source_inventory_paths(ROOT), root=ROOT
    )
    current_test_sha256 = full_suite.inventory_sha256(
        full_suite.test_inventory_paths(ROOT), root=ROOT
    )
    if (
        suite.get("verdict") != "PASS"
        or suite.get("tests_run") != suite.get("discovered_tests")
        or not isinstance(suite.get("tests_run"), int)
        or suite["tests_run"] <= 0
        or suite.get("sealed_test_manifest_read") is not False
        or suite.get("accepted_library_sha256") != EXPECTED["accepted_library"]
        or suite.get("source_inventory_sha256") != current_source_sha256
        or suite.get("test_inventory_sha256") != current_test_sha256
    ):
        raise RuntimeError("current full-suite gate is not valid")
    return commitment, contract, suite


def authorization_payload(paths: dict[str, Path]) -> dict:
    commitment, contract, suite = verify_frozen_inputs(paths)
    return {
        "format": "thai-makhos-nnue-sealed-test-authorization-v1",
        "verdict": "AUTHORIZED_TO_OPEN_ONCE",
        "model_selection_forbidden": True,
        "sealed_manifest_read": False,
        "sealed_labels_opened": False,
        "expected_test_games": EXPECTED_TEST_GAMES,
        "expected_test_positions": EXPECTED_TEST_POSITIONS,
        "teacher": {
            "library_sha256": EXPECTED["accepted_library"],
            "threads": 1,
            "hash_mb": HASH_MB,
            "persistent_search": True,
            "clear_protocol": "clear once per position, then ascending warm budgets",
            "budgets_ms": list(BUDGETS_MS),
        },
        "frozen": {
            name: {"path": str(paths[name]), "sha256": digest}
            for name, digest in EXPECTED.items()
        },
        "full_suite": {
            "path": str(paths["full_suite"]),
            "sha256": sha256(paths["full_suite"]),
            "source_inventory_sha256": suite["source_inventory_sha256"],
            "test_inventory_sha256": suite["test_inventory_sha256"],
            "tests_run": suite["tests_run"],
        },
        "feature_abi": "thai-makhos-shared-137-v1",
        "network_shape": contract.get("network"),
        "partition": {
            "commitment_path": str(paths["partition_commitment"]),
            "games": commitment["sealed_test_games"],
            "selected_positions": commitment["sealed_test_selected_positions"],
        },
        "completion_criterion": (
            "all 1533 committed test games have validated accepted-teacher "
            "analyses and one immutable offline report; no model is selected"
        ),
    }


def preflight(paths: dict[str, Path]) -> dict:
    output = paths["output_dir"]
    allowed = {"opening_authorization.json"}
    if output.exists():
        extras = {path.name for path in output.iterdir()} - allowed
        if extras:
            raise RuntimeError(
                "sealed output already contains post-opening artifacts: "
                + ", ".join(sorted(extras))
            )
    payload = authorization_payload(paths)
    write_locked(output / "opening_authorization.json", payload)
    return payload


def load_authorization(paths: dict[str, Path]) -> dict:
    expected = authorization_payload(paths)
    path = paths["output_dir"] / "opening_authorization.json"
    if not path.is_file() or path.read_bytes() != canonical_bytes(expected):
        raise RuntimeError("sealed opening authorization is missing or stale")
    return expected


def open_manifest(paths: dict[str, Path]) -> dict:
    if sha256(paths["sealed_manifest"]) != EXPECTED["sealed_manifest"]:
        raise RuntimeError("sealed manifest commitment mismatch")
    manifest = load_json(paths["sealed_manifest"], "sealed-test manifest")
    acquisition.validate_selection_manifest(manifest)
    games = manifest.get("games")
    if not isinstance(games, list) or len(games) != EXPECTED_TEST_GAMES:
        raise RuntimeError("sealed-test game count changed")
    if any(game.get("split") != "test" for game in games):
        raise RuntimeError("sealed manifest contains a non-test game")
    positions = sum(int(game.get("selected_positions", -1)) for game in games)
    if positions != EXPECTED_TEST_POSITIONS:
        raise RuntimeError("sealed-test selected-position count changed")
    return manifest


def opening_payload(paths: dict[str, Path]) -> dict:
    return {
        "format": "thai-makhos-nnue-sealed-test-opening-v1",
        "verdict": "OPENED_FOR_FROZEN_MODEL_REPORT_ONLY",
        "open_count": 1,
        "model_selection_forbidden": True,
        "sealed_manifest_sha256": EXPECTED["sealed_manifest"],
        "test_games": EXPECTED_TEST_GAMES,
        "selected_positions": EXPECTED_TEST_POSITIONS,
        "candidate_library_sha256": EXPECTED["candidate_library"],
        "quantized_model_sha256": EXPECTED["quantized_model"],
        "float_model_sha256": EXPECTED["float_model"],
        "feature_abi": "thai-makhos-shared-137-v1",
        "authorization_sha256": sha256(
            paths["output_dir"] / "opening_authorization.json"
        ),
    }


def analyze_shard(paths: dict[str, Path], shard_index: int) -> dict:
    if not 0 <= shard_index < SHARD_COUNT:
        raise ValueError(f"shard_index must be in 0..{SHARD_COUNT - 1}")
    load_authorization(paths)
    manifest = open_manifest(paths)
    write_locked(
        paths["output_dir"] / "opening_commitment.json",
        opening_payload(paths),
    )
    analyses_dir = paths["output_dir"] / "analyses"
    shard_games = [
        game
        for game in manifest["games"]
        if acquisition.analysis_shard(game["game_id"], SHARD_COUNT) == shard_index
    ]
    selected = {
        game["game_id"]: {int(row["ply"]) for row in game["selected"]}
        for game in shard_games
    }
    tablebase_paths = [
        ROOT / "build" / "tb4_np80.bin",
        ROOT / "build" / "tb5_np80.compact.bin",
        ROOT / "build" / "tb6_np80.compact.bin",
    ]
    completed_new = 0
    with BatchWorkLease(ROOT) as batch_lease, ExitStack() as stack:
        tablebases, _ = acquisition.open_ranked_tablebases(
            [path.resolve() for path in tablebase_paths],
            stack=stack,
            provenance_path=paths["tablebase_provenance"],
        )
        power = hash_power_for_megabytes(
            HASH_MB,
            entry_bytes=native_tt_entry_bytes(paths["accepted_library"]),
        )
        with NativeSearch(
            paths["accepted_library"],
            hash_power=power,
            persistent=True,
        ) as teacher:
            for offset, game in enumerate(shard_games, 1):
                batch_lease.checkpoint(f"sealed analysis game {game['game_id']}")
                analysis_path = analyses_dir / f"{game['game_id']}.analysis.json"
                if analysis_path.exists():
                    acquisition.validate_existing_analysis(
                        load_json(analysis_path, "sealed analysis"),
                        game=game,
                        library_sha256=EXPECTED["accepted_library"],
                        budgets_ms=BUDGETS_MS,
                    )
                    continue
                report = acquisition.analyze_game(
                    Path(game["path"]),
                    selected[game["game_id"]],
                    split="test",
                    selection_sha256=game["selection_sha256"],
                    searcher=teacher,
                    library=paths["accepted_library"],
                    library_sha256=EXPECTED["accepted_library"],
                    budgets_ms=BUDGETS_MS,
                    hash_mb=HASH_MB,
                    tablebases=tablebases,
                )
                acquisition.write_json(analysis_path, report)
                completed_new += 1
                print(json.dumps({
                    "stage": "sealed-analyzed",
                    "shard": shard_index,
                    "completed": offset,
                    "assigned": len(shard_games),
                    "game_id": game["game_id"],
                    "eligible": sum(bool(row["eligible"]) for row in report["positions"]),
                }, sort_keys=True), flush=True)

    rows = []
    for game in shard_games:
        path = analyses_dir / f"{game['game_id']}.analysis.json"
        if not path.is_file():
            raise RuntimeError(f"shard analysis missing: {path}")
        rows.append((game["game_id"], sha256(path)))
    payload = {
        "format": "thai-makhos-nnue-sealed-test-shard-v1",
        "verdict": "PASS",
        "shard_count": SHARD_COUNT,
        "shard_index": shard_index,
        "assigned_games": len(shard_games),
        "completed_new": completed_new,
        "analysis_inventory_sha256": hashlib.sha256(
            canonical_bytes(rows)
        ).hexdigest().upper(),
        "model_selection_forbidden": True,
    }
    write_locked(
        paths["output_dir"] / "shards" / f"shard_{shard_index:02d}.json",
        payload,
    )
    return payload


def regression_metrics(pairs: Iterable[tuple[float, float]]) -> dict:
    values = list(pairs)
    if not values:
        return {"count": 0, "mae": None, "rmse": None, "bias": None, "sign_mismatch_rate": None}
    errors = [prediction - target for prediction, target in values]
    sign_mismatches = sum(
        (prediction > 0) != (target > 0)
        for prediction, target in values
        if prediction != 0 and target != 0
    )
    sign_comparable = sum(
        prediction != 0 and target != 0 for prediction, target in values
    )
    return {
        "count": len(values),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "bias": sum(errors) / len(errors),
        "sign_mismatch_rate": (
            None if sign_comparable == 0 else sign_mismatches / sign_comparable
        ),
    }


def calibration(pairs: Iterable[tuple[float, float]]) -> list[dict]:
    bins: list[list[tuple[float, float]]] = [[] for _ in range(10)]
    for prediction, target in pairs:
        index = min(9, max(0, int((prediction + 1.0) * 5.0)))
        bins[index].append((prediction, target))
    return [
        {
            "lower": -1.0 + index * 0.2,
            "upper": -0.8 + index * 0.2,
            "count": len(rows),
            "mean_prediction": (
                None if not rows else sum(row[0] for row in rows) / len(rows)
            ),
            "mean_target": (
                None if not rows else sum(row[1] for row in rows) / len(rows)
            ),
        }
        for index, rows in enumerate(bins)
    ]


def outcome_value(value: object) -> float | None:
    return {"win": 1.0, "draw": 0.0, "loss": -1.0}.get(value)


def finalize(paths: dict[str, Path]) -> dict:
    load_authorization(paths)
    manifest = open_manifest(paths)
    commitment_path = paths["output_dir"] / "opening_commitment.json"
    if (
        not commitment_path.is_file()
        or commitment_path.read_bytes() != canonical_bytes(opening_payload(paths))
    ):
        raise RuntimeError("sealed opening commitment is missing or stale")
    for index in range(SHARD_COUNT):
        shard_path = paths["output_dir"] / "shards" / f"shard_{index:02d}.json"
        shard = load_json(shard_path, "sealed shard completion")
        if shard.get("verdict") != "PASS" or shard.get("shard_index") != index:
            raise RuntimeError(f"sealed shard {index} is incomplete")

    contract = load_json(paths["quantization_contract"], "quantization contract")
    quantized = exporter.parse_quantized_model(
        paths["quantized_model"].read_bytes(), contract
    )
    analyses_dir = paths["output_dir"] / "analyses"
    teacher_pairs: list[tuple[float, float]] = []
    hce_pairs: list[tuple[float, float]] = []
    outcome_pairs: list[tuple[float, float]] = []
    exact_pairs: list[tuple[float, float]] = []
    strata: dict[str, list[tuple[float, float]]] = {}
    inventory: list[tuple[str, str]] = []
    positions_seen = 0
    eligible_seen = 0
    with NativeSearch(
        paths["accepted_library"], hash_power=12, persistent=True
    ) as hce:
        for game in manifest["games"]:
            analysis_path = analyses_dir / f"{game['game_id']}.analysis.json"
            report = load_json(analysis_path, "sealed analysis")
            acquisition.validate_existing_analysis(
                report,
                game=game,
                library_sha256=EXPECTED["accepted_library"],
                budgets_ms=BUDGETS_MS,
            )
            inventory.append((game["game_id"], sha256(analysis_path)))
            for row in report["positions"]:
                positions_seen += 1
                if not row["eligible"]:
                    continue
                eligible_seen += 1
                state = replace(
                    parse_position(row["position"]),
                    reversible_plies=int(row["reversible_plies"]),
                )
                first, second = exporter.ordered_feature_indices(state)
                prediction = float(exporter.quantized_infer(quantized, first, second))
                teacher_target = math.tanh(float(row["teacher_score"]) / 600.0)
                pair = (prediction, teacher_target)
                teacher_pairs.append(pair)
                hce_pairs.append((math.tanh(hce.evaluate(state) / 600.0), teacher_target))
                strata.setdefault(f"phase:{row['phase_band']}", []).append(pair)
                strata.setdefault(
                    "kings:yes" if int(row["king_count"]) else "kings:no", []
                ).append(pair)
                strata.setdefault(f"turn:{row['turn']}", []).append(pair)
                game_target = outcome_value(row.get("game_outcome_from_side_to_move"))
                if game_target is not None and row.get("game_truncated") is False:
                    outcome_pairs.append((prediction, game_target))
                exact = row.get("exact_wdl")
                if isinstance(exact, dict):
                    exact_target = outcome_value(exact.get("outcome"))
                    if exact_target is not None:
                        exact_pairs.append((prediction, exact_target))

    if positions_seen != EXPECTED_TEST_POSITIONS:
        raise RuntimeError("final sealed position count changed")
    payload = {
        "format": "thai-makhos-nnue-sealed-test-report-v1",
        "verdict": "OFFLINE_REPORT_COMPLETE_NOT_STRENGTH_PROMOTION",
        "model_selection_forbidden": True,
        "open_count": 1,
        "test_games": len(manifest["games"]),
        "positions": positions_seen,
        "eligible_positions": eligible_seen,
        "frozen": {name: digest for name, digest in EXPECTED.items()},
        "full_suite_sha256": sha256(paths["full_suite"]),
        "quantized_vs_teacher": regression_metrics(teacher_pairs),
        "accepted_hce_vs_teacher": regression_metrics(hce_pairs),
        "quantized_vs_game_outcome": regression_metrics(outcome_pairs),
        "quantized_vs_exact_wdl": regression_metrics(exact_pairs),
        "teacher_calibration": calibration(teacher_pairs),
        "teacher_strata": {
            name: regression_metrics(rows) for name, rows in sorted(strata.items())
        },
        "analysis_inventory_sha256": hashlib.sha256(
            canonical_bytes(inventory)
        ).hexdigest().upper(),
        "next_gate": (
            "run the predeclared independent-seed one-thread paired STC; "
            "this report cannot select or alter a model"
        ),
    }
    write_locked(paths["output_dir"] / "sealed_test_report.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "analyze", "finalize"))
    defaults = default_paths()
    for name, path in defaults.items():
        parser.add_argument("--" + name.replace("_", "-"), type=Path, default=path)
    parser.add_argument("--shard-index", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    paths = resolved_paths(args)
    if args.mode == "preflight":
        result = preflight(paths)
    elif args.mode == "analyze":
        if args.shard_index is None:
            raise SystemExit("analyze requires --shard-index")
        result = analyze_shard(paths, args.shard_index)
    else:
        result = finalize(paths)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
