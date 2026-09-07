"""Fail-closed final development-data audit for the locked NNUE scaling run.

This verifier may run only after the unchanged acquisition coordinator has
published its deterministic PASS summary.  It reads development analyses and
the partition commitment, but deliberately never opens the sealed-test
selection manifest or any test analysis.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import format_position, legal_moves, parse_position  # noqa: E402
from makhos.eval_corpus import canonical_position_id  # noqa: E402
from makhos.game_analysis import player_name  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    EXPECTED_ACCEPTED_SHA256,
    count_kings,
    count_pieces,
    label_gate,
    phase_band,
    sha256,
    validate_existing_analysis,
    validate_selection_manifest,
    write_locked_json,
)
from scratch.nnue_scaling_checkpoint_audit import (  # noqa: E402
    validate_analysis_payload,
)


FORMAT = "thai-makhos-nnue-scaling-final-audit-v1"
EXPECTED_CONFIG_SHA256 = (
    "B42B9369ED6CD40C7D19843674F191CCEE4E22BC137FD28F94C99B57177FA8A4"
)
EXPECTED_CAPACITY_AUDIT_SHA256 = (
    "9F27BCEAADA11695E1049D4F68A34D26ACAF509E25DFDF1D914E9AA74E360C59"
)
EXPECTED_PREFLIGHT_SUMMARY_SHA256 = (
    "58C4A1AFBF1FDF90590AACF0B02109A085FC3A1D3271E586CA5036E3702D94FC"
)
EXPECTED_FULL_RUN_MANIFEST_SHA256 = (
    "8EBB797FF547162791E4CEF4A1C8D4CF5FBD8335D1A0586DE061D99ABC70C787"
)
EXPECTED_ACQUISITION_SHA256 = (
    "C5E5DD007B3566741466229099120C3BD0FD11783576251A9964B08C853D49D5"
)
EXPECTED_COORDINATOR_SHA256 = (
    "A84497F1418D1E19B4871A361D29939951AE95092A3BBD02918FEB298AA9C7A1"
)
EXPECTED_SUPERVISOR_SHA256 = (
    "F3E7E7457B521253E0A893F5F89D89048D662324CAA3FE24B81109159B048AA9"
)
EXPECTED_WORKLOAD_ISOLATION_SHA256 = (
    "FC80019852ADAC635909740399F3826AFA7173FD32D1E50F28FEAAE78658E402"
)
EXPECTED_COMMITMENT_SHA256 = (
    "6DA3EE1F841AA8A1A1E9E8B3ECA57E39ADB4DEC9F68AB3E83F95EC3B96E45DB3"
)
EXPECTED_DEVELOPMENT_MANIFEST_SHA256 = (
    "C359269C7858D042BFE0B41EEA5D98CC6F03DBDBBADE7ACAC9B13D1E90FACDD2"
)
EXPECTED_SEALED_TEST_MANIFEST_SHA256 = (
    "B1F2350607A95ACF3F04B5667236EE10B7D2ABCF0DE3EB7FA737E72D96338115"
)
EXPECTED_DEVELOPMENT_GAMES = 13_802
EXPECTED_SEALED_TEST_GAMES = 1_533
EXPECTED_SEALED_TEST_SELECTED_POSITIONS = 41_698
EXPECTED_COORDINATOR_FORMAT = "thai-makhos-nnue-scaling-preflight-v1"
EXPECTED_COORDINATOR_KIND = "scalable-acquisition-harness-preflight-summary"
EXPECTED_COORDINATOR_CONTRACT = {
    "games": 15_360,
    "seed_start": 20_280_001,
    "generation_depth": 7,
    "max_game_plies": 200,
    "max_positions_per_game": 64,
    "hash_mb": 256,
    "budgets_ms": "100,500,2000",
    "shard_count": 6,
    "analysis_splits": ["train", "validation"],
}
EXPECTED_COORDINATOR_GATES = {
    "all_source_files_generated",
    "all_development_games_analyzed",
    "development_workers_read_zero_test_analyses",
    "empty_worker_stderr",
    "no_temporary_artifacts",
    "generation_resume_byte_identical",
    "analysis_resume_byte_identical",
    "development_manifest_resume_byte_identical",
    "sealed_test_manifest_resume_byte_identical",
}
EXPECTED_FULL_RUN_CONTRACT = {
    "affinities": [0, 2, 4, 6, 8, 10],
    "analysis_timeout_minutes": 5760,
    "budgets_ms": "100,500,2000",
    "games": 15_360,
    "generation_depth": 7,
    "generation_timeout_minutes": 360,
    "hash_mb": 256,
    "max_game_plies": 200,
    "max_positions_per_game": 64,
    "seed_end": 20_295_360,
    "seed_start": 20_280_001,
    "shard_count": 6,
}

DEFAULT_WORK_DIR = ROOT / "build" / "nnue_scaling_full_v1"
DEFAULT_OUTPUT = DEFAULT_WORK_DIR / "development_readiness_audit.json"
CAPACITY_AUDIT_PATH = ROOT / "build" / "nnue_scaling_capacity_audit_v1.json"
HEX_DIGITS = frozenset("0123456789ABCDEF")


def load_json_bytes_with_sha256(path: Path) -> tuple[dict, str]:
    """Hash and decode one immutable byte snapshot to avoid TOCTOU drift."""

    encoded = path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest().upper()
    return json.loads(encoded.decode("utf-8")), digest


def is_upper_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= HEX_DIGITS
    )


def analysis_set_sha256(rows: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, file_sha in sorted(rows):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def validate_final_summary(summary: dict, commitment: dict) -> dict[str, str]:
    if summary.get("format") != EXPECTED_COORDINATOR_FORMAT:
        raise RuntimeError("coordinator summary format changed")
    if summary.get("kind") != EXPECTED_COORDINATOR_KIND:
        raise RuntimeError("coordinator summary kind changed")
    if summary.get("verdict") != "PASS":
        raise RuntimeError("coordinator has not published a PASS summary")
    gates = summary.get("gates")
    if (
        not isinstance(gates, dict)
        or set(gates) != EXPECTED_COORDINATOR_GATES
        or not all(value is True for value in gates.values())
    ):
        raise RuntimeError("coordinator summary contains a failed gate")
    if summary.get("contract") != EXPECTED_COORDINATOR_CONTRACT:
        raise RuntimeError("coordinator summary contract changed")
    if summary.get("accepted_library_sha256") != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError("coordinator accepted DLL binding changed")
    if summary.get("config_sha256") != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("coordinator config binding changed")
    if summary.get("acquisition_script_sha256") != EXPECTED_ACQUISITION_SHA256:
        raise RuntimeError("coordinator acquisition source binding changed")
    if summary.get("coordinator_script_sha256") != EXPECTED_COORDINATOR_SHA256:
        raise RuntimeError("coordinator source binding changed")
    if summary.get("selection_partition") != commitment:
        raise RuntimeError("coordinator partition payload changed")

    outputs = summary.get("outputs", {})
    if outputs.get("generated_source_files") != 15_360:
        raise RuntimeError("generated source-file count changed")
    if outputs.get("analysis_files") != EXPECTED_DEVELOPMENT_GAMES:
        raise RuntimeError("not every development game has an analysis")
    if outputs.get("development_games") != EXPECTED_DEVELOPMENT_GAMES:
        raise RuntimeError("development game count changed")
    if outputs.get("development_manifest_sha256") != (
        EXPECTED_DEVELOPMENT_MANIFEST_SHA256
    ):
        raise RuntimeError("development manifest binding changed")
    if outputs.get("sealed_test_games") != EXPECTED_SEALED_TEST_GAMES:
        raise RuntimeError("sealed-test game count changed")
    if outputs.get("sealed_test_selected_positions") != (
        EXPECTED_SEALED_TEST_SELECTED_POSITIONS
    ):
        raise RuntimeError("sealed-test selected-position count changed")
    if outputs.get("sealed_test_manifest_sha256") != (
        EXPECTED_SEALED_TEST_MANIFEST_SHA256
    ):
        raise RuntimeError("sealed-test manifest commitment changed")
    if outputs.get("test_analysis_files_read") != 0:
        raise RuntimeError("coordinator opened test analyses")
    if outputs.get("stderr_bytes") != 0 or outputs.get("temporary_files") != 0:
        raise RuntimeError("coordinator output is not clean")
    source_hashes = outputs.get("source_game_hashes")
    generation_shards = outputs.get("generation_shard_manifest_hashes")
    analysis_shards = outputs.get("analysis_shard_manifest_hashes")
    if (
        not isinstance(source_hashes, dict)
        or len(source_hashes) != 15_360
        or not isinstance(generation_shards, dict)
        or len(generation_shards) != 6
        or not isinstance(analysis_shards, dict)
        or len(analysis_shards) != 6
    ):
        raise RuntimeError("coordinator source/shard hash inventory is incomplete")
    for inventory in (source_hashes, generation_shards, analysis_shards):
        if any(
            not isinstance(name, str)
            or not is_upper_sha256(file_sha)
            for name, file_sha in inventory.items()
        ):
            raise RuntimeError("coordinator source/shard hash inventory is malformed")

    reproduction = summary.get("resume_reproduction", {})
    required_reproduction = {
        "source_games_byte_identical",
        "development_analyses_byte_identical",
        "development_manifest_byte_identical",
        "sealed_test_manifest_byte_identical",
    }
    if set(reproduction) != required_reproduction or not all(
        value is True for value in reproduction.values()
    ):
        raise RuntimeError("coordinator reproduction proof is incomplete")

    if commitment.get("test_analysis_files_may_be_read") is not False:
        raise RuntimeError("sealed-test read policy changed")
    if commitment.get("development_games") != EXPECTED_DEVELOPMENT_GAMES:
        raise RuntimeError("partition development count changed")
    if commitment.get("sealed_test_games") != EXPECTED_SEALED_TEST_GAMES:
        raise RuntimeError("partition test count changed")
    if commitment.get("sealed_test_selected_positions") != (
        EXPECTED_SEALED_TEST_SELECTED_POSITIONS
    ):
        raise RuntimeError("partition test capacity changed")
    if commitment.get("development_manifest_sha256") != (
        EXPECTED_DEVELOPMENT_MANIFEST_SHA256
    ):
        raise RuntimeError("partition development hash changed")
    if commitment.get("sealed_test_manifest_sha256") != (
        EXPECTED_SEALED_TEST_MANIFEST_SHA256
    ):
        raise RuntimeError("partition sealed-test hash changed")

    hashes = outputs.get("development_analysis_hashes")
    if not isinstance(hashes, dict) or len(hashes) != EXPECTED_DEVELOPMENT_GAMES:
        raise RuntimeError("coordinator analysis-hash inventory is incomplete")
    if any(
        not isinstance(name, str)
        or not name.endswith(".analysis.json")
        or not is_upper_sha256(file_sha)
        for name, file_sha in hashes.items()
    ):
        raise RuntimeError("coordinator analysis-hash inventory is malformed")
    return hashes


def validate_position(
    row: dict,
    *,
    analysis_name: str,
    expected_selection: dict,
) -> None:
    for key in (
        "position",
        "reversible_plies",
        "ply",
        "canonical_position_id",
        "piece_count",
        "phase_band",
        "king_count",
        "turn",
        "legal_moves",
        "history",
        "searches",
        "eligible",
        "gate_reason",
        "game_truncated",
    ):
        if key not in row:
            raise RuntimeError(f"position row lacks {key}: {analysis_name}")
    try:
        if (
            type(row["reversible_plies"]) is not int
            or type(row["ply"]) is not int
        ):
            raise TypeError("clock and ply must be integers")
        reversible_plies = row["reversible_plies"]
        ply = row["ply"]
        state = parse_position(
            row["position"],
            reversible_plies=reversible_plies,
            ply=ply,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"position cannot be parsed: {analysis_name}") from exc
    if not 0 <= reversible_plies < 80 or ply < 0:
        raise RuntimeError(f"position clock/ply is invalid: {analysis_name}")
    if format_position(state) != row["position"]:
        raise RuntimeError(f"position text is not canonical: {analysis_name}")

    moves = [move.notation for move in legal_moves(state)]
    if not moves or any("x" in move.lower() for move in moves):
        raise RuntimeError(f"non-quiet position entered labels: {analysis_name}")
    if row["legal_moves"] != moves:
        raise RuntimeError(f"legal-move metadata differs: {analysis_name}")
    pieces = count_pieces(state)
    kings = count_kings(state)
    band = phase_band(pieces)
    recomputed = {
        "ply": ply,
        "canonical_position_id": canonical_position_id(state),
        "piece_count": pieces,
        "phase_band": band,
        "king_count": kings,
        "legal_move_count": len(moves),
    }
    if any(row.get(key) != value for key, value in recomputed.items() if key != "legal_move_count"):
        raise RuntimeError(f"recomputed position metadata differs: {analysis_name}")
    if any(expected_selection.get(key) != value for key, value in recomputed.items()):
        raise RuntimeError(f"analysis row differs from selection manifest: {analysis_name}")
    if row.get("turn") != player_name(state.turn):
        raise RuntimeError(f"side-to-move metadata differs: {analysis_name}")

    history = row["history"]
    if not isinstance(history, dict) or set(history) != {
        "entries",
        "current_repetition_count",
        "sha256",
    }:
        raise RuntimeError(f"history provenance is malformed: {analysis_name}")
    if (
        type(history["entries"]) is not int
        or history["entries"] < 1
        or type(history["current_repetition_count"]) is not int
        or history["current_repetition_count"] < 1
        or not isinstance(history["sha256"], str)
        or len(history["sha256"]) != 64
        or history["sha256"].upper() != history["sha256"]
    ):
        raise RuntimeError(f"history provenance is invalid: {analysis_name}")

    searches = row.get("searches", [])
    if len(searches) != 3:
        raise RuntimeError(f"teacher budget ladder is incomplete: {analysis_name}")
    for search, budget in zip(searches, (100, 500, 2000), strict=True):
        if search.get("budget_ms") != budget:
            raise RuntimeError(f"teacher budget differs: {analysis_name}")
        if search.get("native_library_sha256") != EXPECTED_ACCEPTED_SHA256:
            raise RuntimeError(f"teacher DLL differs: {analysis_name}")
        if (
            type(search.get("depth")) is not int
            or search["depth"] < 0
            or type(search.get("nodes")) is not int
            or search["nodes"] < 0
            or type(search.get("score")) is not int
        ):
            raise RuntimeError(f"teacher search counters are invalid: {analysis_name}")
        elapsed = search.get("elapsed_ms")
        if (
            type(elapsed) not in {int, float}
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise RuntimeError(f"teacher elapsed time is invalid: {analysis_name}")
        if search.get("move") not in moves:
            raise RuntimeError(f"teacher move is not legal: {analysis_name}")
        pv = search.get("pv")
        if not isinstance(pv, list) or not pv or pv[0] != search["move"]:
            raise RuntimeError(f"teacher PV is malformed: {analysis_name}")

    expected_eligible, expected_reason = label_gate(searches)
    if type(row.get("eligible")) is not bool or row["eligible"] is not expected_eligible:
        raise RuntimeError(f"eligible flag differs from label gate: {analysis_name}")
    if row.get("gate_reason") != expected_reason:
        raise RuntimeError(f"gate reason differs from searches: {analysis_name}")
    expected_score = int(searches[-1]["score"]) if expected_eligible else None
    if row.get("teacher_score") != expected_score:
        raise RuntimeError(f"teacher score differs from longest search: {analysis_name}")
    expected_delta = abs(int(searches[-1]["score"]) - int(searches[-2]["score"]))
    if row.get("last_two_score_delta") != expected_delta:
        raise RuntimeError(f"teacher score delta differs: {analysis_name}")

    outcome = row.get("game_outcome")
    if outcome not in {None, "black", "red", "draw"}:
        raise RuntimeError(f"game outcome is invalid: {analysis_name}")
    if type(row.get("game_truncated")) is not bool:
        raise RuntimeError(f"truncation flag is invalid: {analysis_name}")
    if row["game_truncated"] and row.get("game_outcome") is not None:
        raise RuntimeError(f"truncated game has an outcome label: {analysis_name}")
    if outcome is None:
        expected_perspective = None
    elif outcome == "draw":
        expected_perspective = "draw"
    elif outcome == row["turn"]:
        expected_perspective = "win"
    else:
        expected_perspective = "loss"
    if row.get("game_outcome_from_side_to_move") != expected_perspective:
        raise RuntimeError(f"game outcome perspective differs: {analysis_name}")

    exact_wdl = row.get("exact_wdl")
    if exact_wdl is not None:
        if (
            not isinstance(exact_wdl, dict)
            or exact_wdl.get("outcome") not in {"win", "draw", "loss"}
            or exact_wdl.get("perspective") != "side_to_move"
            or exact_wdl.get("piece_count") != pieces
            or not exact_wdl.get("tablebase_path")
            or not isinstance(exact_wdl.get("tablebase_expected_fnv1a64"), str)
            or len(exact_wdl["tablebase_expected_fnv1a64"]) != 16
        ):
            raise RuntimeError(f"exact-WDL provenance is malformed: {analysis_name}")


def validate_analysis_contract(
    payload: dict,
    *,
    analysis_name: str,
    game: dict,
    accepted_library: Path,
) -> None:
    validate_analysis_payload(payload, expected_name=analysis_name)
    validate_existing_analysis(
        payload,
        game=game,
        library_sha256=EXPECTED_ACCEPTED_SHA256,
        budgets_ms=(100, 500, 2000),
    )
    expected_top = {
        "hash_mb": 256,
        "rules_profile": "project",
    }
    for key, value in expected_top.items():
        if payload.get(key) != value:
            raise RuntimeError(f"teacher contract has stale {key}: {analysis_name}")
    if (
        type(payload.get("threads")) is not int
        or payload["threads"] != 1
        or payload.get("persistent_search") is not True
        or payload.get("clear_once_per_position_before_ascending_budgets")
        is not True
    ):
        raise RuntimeError(f"teacher execution semantics differ: {analysis_name}")
    if Path(payload.get("accepted_library", "")).resolve() != accepted_library.resolve():
        raise RuntimeError(f"accepted library path differs: {analysis_name}")
    if Path(payload.get("game_path", "")).resolve() != Path(game["path"]).resolve():
        raise RuntimeError(f"source game path differs: {analysis_name}")
    positions = payload.get("positions")
    selected = game.get("selected")
    if (
        not isinstance(positions, list)
        or not isinstance(selected, list)
        or len(positions) != game.get("selected_positions")
        or len(positions) != len(selected)
        or [row.get("ply") for row in positions]
        != [row.get("ply") for row in selected]
    ):
        raise RuntimeError(f"analysis/selection row set differs: {analysis_name}")
    for row, expected_selection in zip(positions, selected, strict=True):
        if row.get("split") != game["split"]:
            raise RuntimeError(f"position split differs: {analysis_name}")
        validate_position(
            row,
            analysis_name=analysis_name,
            expected_selection=expected_selection,
        )


def audit_payloads(
    payloads: Iterable[tuple[str, dict, dict]],
    *,
    accepted_library: Path,
    requirements: dict,
    sealed_test_selected_positions: int,
) -> tuple[dict, dict]:
    counts = Counter()
    seen_positions: dict[str, tuple[str, str]] = {}
    for analysis_name, payload, game in payloads:
        validate_analysis_contract(
            payload,
            analysis_name=analysis_name,
            game=game,
            accepted_library=accepted_library,
        )
        split = payload["split"]
        counts[f"games_{split}"] += 1
        for row in payload.get("positions", []):
            counts[f"selected_{split}"] += 1
            position_id = row["canonical_position_id"]
            previous = seen_positions.get(position_id)
            if previous is not None:
                raise RuntimeError(
                    "duplicate canonical position in development pool: "
                    f"{position_id} ({previous[0]}, {analysis_name})"
                )
            seen_positions[position_id] = (analysis_name, split)
            if not row["eligible"]:
                counts[f"rejected_{split}_{row['gate_reason']}"] += 1
                continue
            counts[f"eligible_{split}_total"] += 1
            counts[f"eligible_{split}_phase_{row['phase_band']}"] += 1
            counts[f"eligible_{split}_turn_{row['turn']}"] += 1
            counts[f"eligible_{split}_with_kings"] += int(row["king_count"] > 0)
            counts[f"eligible_{split}_exact_wdl"] += int(
                row.get("exact_wdl") is not None
            )
            counts[f"eligible_{split}_from_truncated_game"] += int(
                row["game_truncated"]
            )

    def split_summary(split: str) -> dict:
        return {
            "games": counts[f"games_{split}"],
            "selected": counts[f"selected_{split}"],
            "eligible": counts[f"eligible_{split}_total"],
            "with_kings": counts[f"eligible_{split}_with_kings"],
            "exact_wdl": counts[f"eligible_{split}_exact_wdl"],
            "eligible_from_truncated_games": counts[
                f"eligible_{split}_from_truncated_game"
            ],
            "phases": {
                band: counts[f"eligible_{split}_phase_{band}"]
                for band in ("13_to_16", "9_to_12", "5_to_8")
            },
            "turns": {
                turn: counts[f"eligible_{split}_turn_{turn}"]
                for turn in ("black", "red")
            },
            "rejections": {
                reason: value
                for key, value in sorted(counts.items())
                if key.startswith(f"rejected_{split}_")
                for reason in (key.removeprefix(f"rejected_{split}_"),)
            },
        }

    train = split_summary("train")
    validation = split_summary("validation")
    gates = {
        "train_total_capacity": train["eligible"]
        >= int(requirements["total"]),
        "train_king_capacity": train["with_kings"]
        >= int(requirements["with_kings"]),
        "train_phase_13_to_16_capacity": train["phases"]["13_to_16"]
        >= int(requirements["phase_13_to_16"]),
        "train_phase_9_to_12_capacity": train["phases"]["9_to_12"]
        >= int(requirements["phase_9_to_12"]),
        "train_phase_5_to_8_capacity": train["phases"]["5_to_8"]
        >= int(requirements["phase_5_to_8"]),
        "train_black_turn_capacity": train["turns"]["black"]
        >= int(requirements["turn_black"]),
        "train_red_turn_capacity": train["turns"]["red"]
        >= int(requirements["turn_red"]),
        "validation_capacity": validation["eligible"]
        >= int(requirements["validation_total"]),
        "sealed_test_manifest_remains_large_and_unopened": (
            sealed_test_selected_positions
            == EXPECTED_SEALED_TEST_SELECTED_POSITIONS
        ),
        "zero_development_position_duplicates": True,
        "zero_truncated_game_outcome_labels": True,
    }
    return {
        "train": train,
        "validation": validation,
        "unique_development_positions": len(seen_positions),
    }, gates


def verify_locked_sources(
    work_dir: Path,
) -> tuple[dict, dict, dict, dict, dict]:
    config_path = work_dir / "config.json"
    commitment_path = work_dir / "selection_partition_commitment.json"
    full_manifest_path = work_dir / "full_run_manifest.json"
    development_path = work_dir / "development_selection_manifest.json"
    checks = {
        ROOT / "scratch" / "nnue_quiet_leaf_acquire.py": (
            EXPECTED_ACQUISITION_SHA256
        ),
        ROOT / "scratch" / "nnue_scaling_preflight.py": (
            EXPECTED_COORDINATOR_SHA256
        ),
        ROOT / "scratch" / "nnue_scaling_full_run.py": (
            EXPECTED_SUPERVISOR_SHA256
        ),
        ROOT / "makhos" / "workload_isolation.py": (
            EXPECTED_WORKLOAD_ISOLATION_SHA256
        ),
    }
    for path, expected in checks.items():
        if sha256(path) != expected:
            raise RuntimeError(f"locked input changed: {path}")

    config, config_sha = load_json_bytes_with_sha256(config_path)
    commitment, commitment_sha = load_json_bytes_with_sha256(commitment_path)
    full_manifest, full_manifest_sha = load_json_bytes_with_sha256(
        full_manifest_path
    )
    capacity, capacity_sha = load_json_bytes_with_sha256(CAPACITY_AUDIT_PATH)
    development, development_sha = load_json_bytes_with_sha256(development_path)
    json_hashes = {
        str(config_path): (config_sha, EXPECTED_CONFIG_SHA256),
        str(commitment_path): (commitment_sha, EXPECTED_COMMITMENT_SHA256),
        str(full_manifest_path): (
            full_manifest_sha,
            EXPECTED_FULL_RUN_MANIFEST_SHA256,
        ),
        str(CAPACITY_AUDIT_PATH): (
            capacity_sha,
            EXPECTED_CAPACITY_AUDIT_SHA256,
        ),
        str(development_path): (
            development_sha,
            EXPECTED_DEVELOPMENT_MANIFEST_SHA256,
        ),
    }
    for name, (actual, expected) in json_hashes.items():
        if actual != expected:
            raise RuntimeError(f"locked JSON input changed: {name}")
    if sha256(Path(config["accepted_library"])) != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity changed")

    if (
        full_manifest.get("format") != "thai-makhos-nnue-scaling-full-run-v1"
        or full_manifest.get("kind") != "locked-full-run-manifest"
        or full_manifest.get("contract") != EXPECTED_FULL_RUN_CONTRACT
        or full_manifest.get("acquisition_script_sha256")
        != EXPECTED_ACQUISITION_SHA256
        or full_manifest.get("coordinator_script_sha256")
        != EXPECTED_COORDINATOR_SHA256
        or full_manifest.get("supervisor_script_sha256")
        != EXPECTED_SUPERVISOR_SHA256
        or full_manifest.get("workload_isolation_sha256")
        != EXPECTED_WORKLOAD_ISOLATION_SHA256
        or full_manifest.get("config_sha256") != EXPECTED_CONFIG_SHA256
        or full_manifest.get("sealed_test_labels_opened") is not False
        or full_manifest.get("model_trained") is not False
        or full_manifest.get("playing_code_changed") is not False
    ):
        raise RuntimeError("full-run manifest contract changed")
    authorization = full_manifest.get("authorization", {})
    if (
        authorization.get("accepted_library_sha256")
        != EXPECTED_ACCEPTED_SHA256
        or authorization.get("capacity_audit_sha256")
        != EXPECTED_CAPACITY_AUDIT_SHA256
        or authorization.get("preflight_summary_sha256")
        != EXPECTED_PREFLIGHT_SUMMARY_SHA256
    ):
        raise RuntimeError("full-run authorization changed")

    expected_development_path = development_path.resolve()
    expected_sealed_path = (
        work_dir / "sealed_test_selection_manifest.json"
    ).resolve()
    if Path(commitment.get("development_manifest", "")).resolve() != (
        expected_development_path
    ):
        raise RuntimeError("commitment development path changed")
    if Path(commitment.get("sealed_test_manifest", "")).resolve() != (
        expected_sealed_path
    ):
        raise RuntimeError("commitment sealed-test path changed")
    if commitment.get("test_analysis_files_may_be_read") is not False:
        raise RuntimeError("commitment test-read policy changed")

    validate_selection_manifest(development)
    games = development.get("games")
    if (
        development.get("format")
        != "thai-makhos-nnue-quiet-leaf-acquisition-v1"
        or development.get("kind") != "development-selection-manifest"
        or development.get("split_before_sampling") is not True
        or not isinstance(games, list)
        or len(games) != EXPECTED_DEVELOPMENT_GAMES
        or any(game.get("split") not in {"train", "validation"} for game in games)
        or [game["game_id"] for game in games]
        != sorted(game["game_id"] for game in games)
    ):
        raise RuntimeError("development selection manifest is malformed")
    games_by_split = Counter(game["split"] for game in games)
    selected_by_split = Counter(
        game["split"] for game in games for _row in game["selected"]
    )
    phase_counts = Counter(
        row["phase_band"] for game in games for row in game["selected"]
    )
    if (
        development.get("games_by_split") != dict(sorted(games_by_split.items()))
        or development.get("selected_by_split")
        != dict(sorted(selected_by_split.items()))
        or development.get("selected_phase_bands")
        != dict(sorted(phase_counts.items()))
        or development.get("selected_mixed_king_positions")
        != sum(
            row["king_count"] > 0
            for game in games
            for row in game["selected"]
        )
        or development.get("sealed_test_commitment")
        != {
            "manifest_sha256": EXPECTED_SEALED_TEST_MANIFEST_SHA256,
            "games": EXPECTED_SEALED_TEST_GAMES,
            "selected_positions": EXPECTED_SEALED_TEST_SELECTED_POSITIONS,
            "model_selection_may_read": False,
        }
    ):
        raise RuntimeError("development manifest aggregates differ")

    if (
        capacity.get("verdict")
        != "SCALING_SIZE_READY_FOR_HARNESS_PREFLIGHT"
        or capacity.get("model_trained") is not False
        or capacity.get("playing_code_changed") is not False
        or capacity.get("test_policy", {}).get("future_test_rows_may_select_model")
        is not False
    ):
        raise RuntimeError("capacity-audit authorization changed")
    return config, commitment, full_manifest, capacity, development


def build_audit(work_dir: Path) -> dict:
    work_dir = work_dir.resolve()
    config, commitment, full_manifest, capacity, development = (
        verify_locked_sources(work_dir)
    )
    summary_path = work_dir / "preflight_summary.json"
    if not summary_path.exists():
        raise RuntimeError("coordinator final PASS summary does not exist")
    coordinator_summary, coordinator_summary_sha = load_json_bytes_with_sha256(
        summary_path
    )
    expected_hashes = validate_final_summary(coordinator_summary, commitment)
    development_games = {
        game["game_id"]: game for game in development["games"]
    }

    analyses_dir = work_dir / "analyses"
    paths = sorted(analyses_dir.glob("*.analysis.json"))
    if len(paths) != EXPECTED_DEVELOPMENT_GAMES:
        raise RuntimeError("development analysis directory is incomplete")
    if {path.name for path in paths} != set(expected_hashes):
        raise RuntimeError("analysis filenames differ from coordinator proof")

    set_rows = []

    def validated_payloads() -> Iterable[tuple[str, dict, dict]]:
        # Stream the projected ~1.5 GiB analysis pool.  Retaining every decoded
        # JSON object would multiply memory use on the 16-GiB target host.
        for path in paths:
            payload, file_sha = load_json_bytes_with_sha256(path)
            if expected_hashes[path.name] != file_sha:
                raise RuntimeError(
                    f"analysis changed after coordinator PASS: {path.name}"
                )
            game_id = path.name.removesuffix(".analysis.json")
            game = development_games.get(game_id)
            if game is None:
                raise RuntimeError(
                    f"analysis is absent from development manifest: {path.name}"
                )
            set_rows.append((path.name, file_sha))
            yield path.name, payload, game

    requirements = capacity["sizing_contract"]["requirements"]
    coverage, coverage_gates = audit_payloads(
        validated_payloads(),
        accepted_library=Path(config["accepted_library"]),
        requirements=requirements,
        sealed_test_selected_positions=commitment[
            "sealed_test_selected_positions"
        ],
    )
    gates = {
        "coordinator_pass_and_reproduced": True,
        "development_manifest_hash_and_rows_verified": True,
        "all_development_analyses_match_coordinator_hashes": True,
        "accepted_teacher_and_full_contract_only": True,
        "development_splits_only": True,
        "test_analysis_files_read_zero": True,
        "sealed_test_manifest_read_zero": True,
        **coverage_gates,
    }
    if not all(gates.values()):
        raise RuntimeError(f"final development-data gate failed: {gates}")

    return {
        "format": FORMAT,
        "kind": "final-development-data-readiness-audit",
        "verdict": "PASS",
        "playing_code_changed": False,
        "model_trained": False,
        "trainer_authorized_by_this_artifact": False,
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "config_sha256": EXPECTED_CONFIG_SHA256,
        "capacity_audit_sha256": EXPECTED_CAPACITY_AUDIT_SHA256,
        "full_run_manifest_sha256": EXPECTED_FULL_RUN_MANIFEST_SHA256,
        "coordinator_summary_sha256": coordinator_summary_sha,
        "development_manifest_sha256": (
            EXPECTED_DEVELOPMENT_MANIFEST_SHA256
        ),
        "sealed_test_manifest_sha256": EXPECTED_SEALED_TEST_MANIFEST_SHA256,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "analysis_set_sha256": analysis_set_sha256(set_rows),
        "analysis_files": len(paths),
        "coverage_requirements": requirements,
        "coverage": coverage,
        "gates": gates,
        "next_gate": (
            "reproduce this artifact byte-for-byte, run the complete test suite "
            "after all workers are idle, then freeze the first float-trainer "
            "experiment; sealed test labels remain unopened"
        ),
        "bound_full_run_contract": full_manifest["contract"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    audit = build_audit(args.work_dir)
    write_locked_json(args.output.resolve(), audit)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": sha256(args.output.resolve()),
                "analysis_files": audit["analysis_files"],
                "train_eligible": audit["coverage"]["train"]["eligible"],
                "validation_eligible": audit["coverage"]["validation"][
                    "eligible"
                ],
                "sealed_test_manifest_read": False,
                "verdict": audit["verdict"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
