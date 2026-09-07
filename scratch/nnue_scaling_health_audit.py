"""Read-only health snapshot for the live full NNUE acquisition.

The monitor deliberately avoids the volatile supervisor-status file, the
sealed-test selection manifest, and every analysis payload.  It validates the
locked non-test inputs through the prepared final-audit verifier, then inspects
only filenames, log sizes, temporary artifacts, disk space, and live process
commands.  It never authorizes training or final data readiness.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scratch.nnue_quiet_leaf_acquire import analysis_shard, sha256
from scratch.nnue_scaling_final_audit import (
    DEFAULT_WORK_DIR,
    EXPECTED_ACCEPTED_SHA256,
    EXPECTED_DEVELOPMENT_MANIFEST_SHA256,
    EXPECTED_FULL_RUN_MANIFEST_SHA256,
    EXPECTED_SEALED_TEST_GAMES,
    EXPECTED_SEALED_TEST_MANIFEST_SHA256,
    EXPECTED_SEALED_TEST_SELECTED_POSITIONS,
    verify_locked_sources,
)
from scratch.nnue_scaling_full_run import live_full_run_processes


FORMAT = "thai-makhos-nnue-scaling-health-v1"
PIPELINE_ENTRYPOINTS = {
    "supervisor": "nnue_scaling_full_run.py",
    "coordinator": "nnue_scaling_preflight.py",
    "worker": "nnue_quiet_leaf_acquire.py",
}
EXPECTED_RUNNING_ROLES = {
    "supervisor": 1,
    "coordinator": 1,
    "worker": 6,
}


def process_role_counts(processes: Iterable[dict]) -> dict[str, int]:
    """Classify exact Python entrypoint tokens, not parent command text."""

    counts: Counter[str] = Counter()
    for process in processes:
        command = [str(value) for value in process.get("command", [])]
        entrypoints = {
            Path(value.strip('"')).name.casefold()
            for value in command
            if value.strip('"')
            and not any(character.isspace() for character in value.strip('"'))
        }
        matched = [
            role
            for role, filename in PIPELINE_ENTRYPOINTS.items()
            if filename in entrypoints
        ]
        if len(matched) != 1:
            counts["unknown"] += 1
        else:
            counts[matched[0]] += 1
    return {
        role: int(counts.get(role, 0))
        for role in (*PIPELINE_ENTRYPOINTS, "unknown")
    }


def collect_inventory(
    work_dir: Path,
    development_games: list[dict],
    processes: Iterable[dict],
    *,
    expected_source_files: int,
    shard_count: int,
) -> dict:
    """Collect metadata without opening source games or analysis payloads."""

    work_dir = work_dir.resolve()
    expected_names = {
        f"{game['game_id']}.analysis.json" for game in development_games
    }
    actual_names = {
        path.name for path in (work_dir / "analyses").glob("*.analysis.json")
    }
    completed_names = expected_names & actual_names
    extra_names = sorted(actual_names - expected_names)
    missing_names = sorted(expected_names - actual_names)

    expected_shards = [0] * shard_count
    completed_shards = [0] * shard_count
    for game in development_games:
        expected_shards[analysis_shard(game["game_id"], shard_count)] += 1
    for filename in completed_names:
        game_id = filename.removesuffix(".analysis.json")
        completed_shards[analysis_shard(game_id, shard_count)] += 1

    stderr_paths = sorted(
        list((work_dir / "worker_logs").glob("*.stderr.log"))
        + list((work_dir / "supervisor_logs").glob("*.stderr.log"))
    )
    stderr_bytes = sum(path.stat().st_size for path in stderr_paths)
    temporary_paths = sorted(work_dir.rglob("*.tmp"))
    source_files = len(list((work_dir / "games").glob("*.json")))
    roles = process_role_counts(processes)
    process_total = sum(roles.values())

    errors = []
    if source_files != expected_source_files:
        errors.append(
            f"source file count {source_files} != {expected_source_files}"
        )
    if extra_names:
        errors.append(f"unexpected analysis files: {len(extra_names)}")
    if stderr_bytes:
        errors.append(f"stderr is non-empty: {stderr_bytes} bytes")
    if temporary_paths:
        errors.append(f"temporary artifacts exist: {len(temporary_paths)}")

    complete = len(completed_names) == len(expected_names) and not extra_names
    if roles["unknown"]:
        errors.append(f"unknown pipeline processes exist: {roles['unknown']}")
    if (
        roles["supervisor"] > EXPECTED_RUNNING_ROLES["supervisor"]
        or roles["coordinator"] > EXPECTED_RUNNING_ROLES["coordinator"]
        or roles["worker"] > EXPECTED_RUNNING_ROLES["worker"]
    ):
        errors.append(f"duplicate or excess pipeline processes exist: {roles}")
    if process_total and not complete and roles != {
        **EXPECTED_RUNNING_ROLES,
        "unknown": 0,
    }:
        errors.append(f"live process roles differ: {roles}")

    if errors:
        state = "UNHEALTHY"
    elif complete:
        state = "COMPLETE_PENDING_FINAL_GATES"
    elif process_total == 0:
        state = "PAUSED_OR_STOPPED_CLEAN"
    else:
        state = "RUNNING_HEALTHY"

    return {
        "state": state,
        "source_files": source_files,
        "expected_source_files": expected_source_files,
        "development_analyses": len(completed_names),
        "expected_development_analyses": len(expected_names),
        "missing_development_analyses": len(missing_names),
        "missing_examples": missing_names[:10],
        "extra_analysis_files": extra_names,
        "analysis_shards": [
            {
                "shard": index,
                "completed": completed_shards[index],
                "expected": expected_shards[index],
            }
            for index in range(shard_count)
        ],
        "process_roles": roles,
        "stderr_files": len(stderr_paths),
        "stderr_bytes": stderr_bytes,
        "temporary_files": len(temporary_paths),
        "temporary_examples": [str(path) for path in temporary_paths[:10]],
        "errors": errors,
        "safe_to_resume_locked_supervisor": (
            state == "PAUSED_OR_STOPPED_CLEAN"
        ),
    }


def build_health_snapshot(
    work_dir: Path = DEFAULT_WORK_DIR,
    *,
    processes: list[dict] | None = None,
) -> dict:
    """Validate locked development inputs and return a dynamic health snapshot."""

    work_dir = work_dir.resolve()
    _config, commitment, full_manifest, _capacity, development = (
        verify_locked_sources(work_dir)
    )
    if processes is None:
        processes = live_full_run_processes(work_dir)

    contract = full_manifest["contract"]
    inventory = collect_inventory(
        work_dir,
        development["games"],
        processes,
        expected_source_files=int(contract["games"]),
        shard_count=int(contract["shard_count"]),
    )
    disk = shutil.disk_usage(work_dir)
    return {
        "format": FORMAT,
        "kind": "read-only-live-acquisition-health",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "health_script_sha256": sha256(Path(__file__).resolve()),
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "full_run_manifest_sha256": EXPECTED_FULL_RUN_MANIFEST_SHA256,
        "development_manifest_sha256": (
            EXPECTED_DEVELOPMENT_MANIFEST_SHA256
        ),
        "sealed_test_commitment": {
            "manifest_sha256": EXPECTED_SEALED_TEST_MANIFEST_SHA256,
            "games": EXPECTED_SEALED_TEST_GAMES,
            "selected_positions": EXPECTED_SEALED_TEST_SELECTED_POSITIONS,
            "matches_partition_commitment": (
                commitment.get("sealed_test_manifest_sha256")
                == EXPECTED_SEALED_TEST_MANIFEST_SHA256
                and commitment.get("sealed_test_games")
                == EXPECTED_SEALED_TEST_GAMES
                and commitment.get("sealed_test_selected_positions")
                == EXPECTED_SEALED_TEST_SELECTED_POSITIONS
            ),
        },
        "isolation": {
            "volatile_supervisor_status_read": False,
            "sealed_test_manifest_read": False,
            "test_analysis_files_read": 0,
            "analysis_payloads_read": 0,
        },
        "inventory": inventory,
        "disk_free_bytes": int(disk.free),
        "training_authorized": False,
        "final_data_readiness": False,
        "next_action": (
            "continue the locked supervisor"
            if inventory["state"] == "RUNNING_HEALTHY"
            else "inspect this snapshot before any resume or final gate"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    args = parser.parse_args()
    snapshot = build_health_snapshot(args.work_dir)
    print(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
