"""Run the bounded fresh-seed preflight for scalable NNUE acquisition.

The coordinator generates source games in disjoint shards, seals the test
selection, analyzes development games only, and verifies byte-identical resume.
It trains no model and changes no playing code.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

import psutil


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.workload_isolation import (  # noqa: E402
    BatchWorkLease,
    InteractiveSessionActive,
    ensure_interactive_session_inactive,
)
from scratch.nnue_pilot_resume import (  # noqa: E402
    _spawn,
    _stop_processes,
    active_pilot_processes,
    atomic_write_json,
)
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    build_selection_manifest,
    game_schedule,
    sha256,
    validate_existing_analysis,
    validate_selection_manifest,
    write_locked_json,
)


FORMAT = "thai-makhos-nnue-scaling-preflight-v1"
DEFAULT_WORK_DIR = ROOT / "build" / "nnue_scaling_preflight_v1"
DEFAULT_CORPUS = ROOT / "corpora" / "nnue_scaling_preflight_v1_unused.jsonl"
DEFAULT_ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"
DEFAULT_AFFINITIES = (0, 2, 4, 6, 8, 10)
ALL_SPLITS = ("train", "validation", "test")
DEVELOPMENT_SPLITS = ("train", "validation")


def subset_manifest(full: dict, games: list[dict], *, kind: str) -> dict:
    selected = [row for game in games for row in game["selected"]]
    manifest = {
        "format": full["format"],
        "kind": kind,
        "split_rule": full["split_rule"],
        "split_before_sampling": full["split_before_sampling"],
        "position_identity": full["position_identity"],
        "generated_source_game_files": full["generated_source_game_files"],
        "unique_source_game_trajectories": full["unique_source_game_trajectories"],
        "global_deduplication": {
            "duplicate_source_game_files_dropped": full[
                "duplicate_source_game_files_dropped"
            ],
            "cross_split_symmetry_duplicates_dropped": full[
                "cross_split_symmetry_duplicates_dropped"
            ],
            "within_split_duplicates_dropped": full[
                "within_split_duplicates_dropped"
            ],
        },
        "games_by_split": dict(
            sorted(Counter(game["split"] for game in games).items())
        ),
        "selected_by_split": dict(
            sorted(
                Counter(
                    game["split"] for game in games for _row in game["selected"]
                ).items()
            )
        ),
        "selected_phase_bands": dict(
            sorted(Counter(row["phase_band"] for row in selected).items())
        ),
        "selected_mixed_king_positions": sum(
            row["king_count"] > 0 for row in selected
        ),
        "games": sorted(games, key=lambda game: game["game_id"]),
    }
    validate_selection_manifest(manifest)
    return manifest


def partition_and_seal_manifest(
    full: dict,
    *,
    development_path: Path,
    sealed_test_path: Path,
    commitment_path: Path,
) -> dict:
    development_games = [
        game for game in full["games"] if game["split"] in DEVELOPMENT_SPLITS
    ]
    test_games = [game for game in full["games"] if game["split"] == "test"]
    if not development_games or not test_games:
        raise RuntimeError("preflight split lacks development or test games")
    if len(development_games) + len(test_games) != len(full["games"]):
        raise RuntimeError("selection partition is incomplete")

    sealed = subset_manifest(
        full,
        test_games,
        kind="sealed-test-selection-manifest",
    )
    write_locked_json(sealed_test_path, sealed)
    sealed_hash = sha256(sealed_test_path)
    development = subset_manifest(
        full,
        development_games,
        kind="development-selection-manifest",
    )
    development["sealed_test_commitment"] = {
        "manifest_sha256": sealed_hash,
        "games": len(test_games),
        "selected_positions": sum(
            game["selected_positions"] for game in test_games
        ),
        "model_selection_may_read": False,
    }
    write_locked_json(development_path, development)
    commitment = {
        "format": FORMAT,
        "kind": "selection-partition-commitment",
        "development_manifest": str(development_path.resolve()),
        "development_manifest_sha256": sha256(development_path),
        "development_games": len(development_games),
        "sealed_test_manifest": str(sealed_test_path.resolve()),
        "sealed_test_manifest_sha256": sealed_hash,
        "sealed_test_games": len(test_games),
        "sealed_test_selected_positions": sum(
            game["selected_positions"] for game in test_games
        ),
        "test_analysis_files_may_be_read": False,
        "global_unique_trajectories": len(full["games"]),
        "generated_source_game_files": full["generated_source_game_files"],
    }
    write_locked_json(commitment_path, commitment)
    return commitment


def acquisition_base_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        "-B",
        str(ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"),
        "--accepted-library",
        str(args.accepted_library.resolve()),
        "--work-dir",
        str(args.work_dir.resolve()),
        "--corpus",
        str(args.corpus.resolve()),
        "--games",
        str(args.games),
        "--seed-start",
        str(args.seed_start),
        "--generation-depth",
        str(args.generation_depth),
        "--max-game-plies",
        str(args.max_game_plies),
        "--max-positions-per-game",
        str(args.max_positions_per_game),
        "--hash-mb",
        str(args.hash_mb),
        "--budgets-ms",
        args.budgets_ms,
    ]


def generation_commands(args: argparse.Namespace) -> list[list[str]]:
    base = acquisition_base_command(args)
    return [
        base
        + [
            "--generation-only",
            "--generation-shard-count",
            str(args.shard_count),
            "--generation-shard-index",
            str(shard),
        ]
        for shard in range(args.shard_count)
    ]


def analysis_commands(
    args: argparse.Namespace,
    development_manifest: Path,
) -> list[list[str]]:
    base = acquisition_base_command(args)
    return [
        base
        + [
            "--selection-manifest",
            str(development_manifest.resolve()),
            "--analysis-splits",
            "train,validation",
            "--analysis-shard-count",
            str(args.shard_count),
            "--analysis-shard-index",
            str(shard),
        ]
        for shard in range(args.shard_count)
    ]


def run_config_lock(args: argparse.Namespace) -> dict:
    command = acquisition_base_command(args) + ["--config-only"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode or completed.stderr:
        raise RuntimeError(
            "config lock failed: "
            f"exit={completed.returncode}, stderr={completed.stderr!r}"
        )
    if "paused-for-interactive-play" in completed.stdout:
        return {"state": "PAUSED_FOR_INTERACTIVE_PLAY", "command": command}
    config_path = args.work_dir.resolve() / "config.json"
    if not config_path.exists():
        raise RuntimeError("config-only run did not create the locked config")
    return {
        "state": "PASS",
        "command": command,
        "stdout": completed.stdout.splitlines(),
        "config_sha256": sha256(config_path),
    }


def run_worker_stage(
    *,
    work_dir: Path,
    stage: str,
    commands: list[list[str]],
    affinities: tuple[int, ...],
    timeout_minutes: int,
) -> dict:
    ensure_interactive_session_inactive(f"{stage} worker launch")
    if active_pilot_processes(work_dir):
        raise RuntimeError(f"{stage} cannot start while pilot workers are live")
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    log_dir = work_dir / "worker_logs"
    processes: list[subprocess.Popen] = []
    workers = []
    started = time.monotonic()
    try:
        for shard, (command, affinity) in enumerate(zip(commands, affinities)):
            stdout_path = log_dir / f"{stage}_{stamp}_shard_{shard:02d}.stdout.log"
            stderr_path = log_dir / f"{stage}_{stamp}_shard_{shard:02d}.stderr.log"
            process = _spawn(command, stdout_path, stderr_path)
            processes.append(process)
            native = psutil.Process(process.pid)
            native.cpu_affinity([affinity])
            workers.append(
                {
                    "shard": shard,
                    "pid": process.pid,
                    "create_time": native.create_time(),
                    "logical_processor_affinity": affinity,
                    "priority": "BelowNormal",
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                    "command": command,
                }
            )
        deadline = time.monotonic() + timeout_minutes * 60
        while any(process.poll() is None for process in processes):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{stage} exceeded {timeout_minutes} minutes")
            time.sleep(1.0)
        exits = [int(process.returncode) for process in processes]
        stderr_bytes = sum(Path(worker["stderr"]).stat().st_size for worker in workers)
        paused = any(
            "paused-for-interactive-play"
            in Path(worker["stdout"]).read_text(encoding="utf-8")
            for worker in workers
        )
        if stderr_bytes or any(exits):
            raise RuntimeError(
                f"{stage} worker failure: exits={exits}, stderr={stderr_bytes}"
            )
        return {
            "stage": stage,
            "state": "PAUSED_FOR_INTERACTIVE_PLAY" if paused else "PASS",
            "elapsed_seconds": time.monotonic() - started,
            "stderr_bytes": stderr_bytes,
            "exit_codes": exits,
            "workers": workers,
        }
    except Exception:
        _stop_processes(processes)
        raise


def scheduled_game_paths(args: argparse.Namespace) -> list[Path]:
    games_dir = args.work_dir.resolve() / "games"
    return [
        games_dir
        / f"game_{index:03d}_seed_{args.seed_start + index - 1}.json"
        for index in range(1, args.games + 1)
    ]


def path_hashes(
    paths: list[Path],
    *,
    checkpoint: Callable[[str], None] | None = None,
) -> dict[str, str]:
    hashes = {}
    for path in sorted(paths):
        if checkpoint is not None:
            checkpoint(f"hash artifact {path.name}")
        hashes[path.name] = sha256(path)
    return hashes


def validate_preflight_outputs(
    args: argparse.Namespace,
    *,
    development_manifest_path: Path,
    commitment_path: Path,
    checkpoint: Callable[[str], None] | None = None,
) -> dict:
    work_dir = args.work_dir.resolve()
    game_paths = scheduled_game_paths(args)
    missing_games = [path for path in game_paths if not path.exists()]
    if missing_games:
        raise RuntimeError(f"missing generated source files: {len(missing_games)}")
    temporary_files = list(work_dir.rglob("*.tmp"))
    if temporary_files:
        raise RuntimeError(f"temporary artifacts remain: {temporary_files}")
    generation_shards = sorted((work_dir / "generation_shards").glob("*.json"))
    analysis_shards = sorted((work_dir / "execution_shards").glob("*.json"))
    if len(generation_shards) != args.shard_count:
        raise RuntimeError("generation shard manifest count differs")
    if len(analysis_shards) != args.shard_count:
        raise RuntimeError("analysis shard manifest count differs")
    assigned = []
    for path in generation_shards:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assigned.extend(int(row["index"]) for row in manifest["assigned_schedules"])
    if sorted(assigned) != list(range(1, args.games + 1)) or len(set(assigned)) != len(
        assigned
    ):
        raise RuntimeError("generation shard schedules overlap or leave gaps")

    development = json.loads(development_manifest_path.read_text(encoding="utf-8"))
    validate_selection_manifest(development)
    commitment = json.loads(commitment_path.read_text(encoding="utf-8"))
    dev_games = {game["game_id"]: game for game in development["games"]}
    analysis_paths = sorted((work_dir / "analyses").glob("*.analysis.json"))
    if len(analysis_paths) != len(dev_games):
        raise RuntimeError(
            "analysis directory contains missing or non-development game files"
        )
    config = json.loads((work_dir / "config.json").read_text(encoding="utf-8"))
    eligible = Counter()
    development_analysis_hashes = {}
    for path in analysis_paths:
        if checkpoint is not None:
            checkpoint(f"validate development analysis {path.name}")
        game_id = path.name.removesuffix(".analysis.json")
        game = dev_games.get(game_id)
        if game is None:
            raise RuntimeError("test or unknown analysis file entered development pool")
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_existing_analysis(
            payload,
            game=game,
            library_sha256=config["accepted_library_sha256"],
            budgets_ms=config["budgets_ms"],
        )
        development_analysis_hashes[path.name] = sha256(path)
        for position in payload["positions"]:
            if not position["eligible"]:
                continue
            eligible["total"] += 1
            eligible[f"phase_{position['phase_band']}"] += 1
            eligible[f"turn_{position['turn']}"] += 1
            eligible["with_kings"] += int(position["king_count"] > 0)
    stderr_paths = list((work_dir / "worker_logs").glob("*.stderr.log"))
    stderr_bytes = sum(path.stat().st_size for path in stderr_paths)
    if stderr_bytes:
        raise RuntimeError("preflight worker stderr is non-empty")
    return {
        "generated_source_files": len(game_paths),
        "source_game_hashes": path_hashes(game_paths, checkpoint=checkpoint),
        "generation_shard_manifest_hashes": path_hashes(
            generation_shards, checkpoint=checkpoint
        ),
        "analysis_shard_manifest_hashes": path_hashes(
            analysis_shards, checkpoint=checkpoint
        ),
        "development_games": len(dev_games),
        "development_manifest_sha256": sha256(development_manifest_path),
        "sealed_test_games": commitment["sealed_test_games"],
        "sealed_test_selected_positions": commitment[
            "sealed_test_selected_positions"
        ],
        "sealed_test_manifest_sha256": commitment[
            "sealed_test_manifest_sha256"
        ],
        "test_analysis_files_read": 0,
        "analysis_files": len(analysis_paths),
        "development_analysis_hashes": dict(
            sorted(development_analysis_hashes.items())
        ),
        "eligible_development_labels": dict(sorted(eligible.items())),
        "stderr_logs": len(stderr_paths),
        "stderr_bytes": stderr_bytes,
        "temporary_files": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--accepted-library", type=Path, default=DEFAULT_ACCEPTED)
    parser.add_argument("--games", type=int, default=96)
    parser.add_argument("--seed-start", type=int, default=20270001)
    parser.add_argument("--generation-depth", type=int, default=7)
    parser.add_argument("--max-game-plies", type=int, default=200)
    parser.add_argument("--max-positions-per-game", type=int, default=64)
    parser.add_argument("--hash-mb", type=int, default=256)
    parser.add_argument("--budgets-ms", default="100,500,2000")
    parser.add_argument("--shard-count", type=int, default=6)
    parser.add_argument("--affinities", default="0,2,4,6,8,10")
    parser.add_argument("--generation-timeout-minutes", type=int, default=180)
    parser.add_argument("--analysis-timeout-minutes", type=int, default=180)
    parser.add_argument("--skip-resume-reproduction", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.work_dir = args.work_dir.resolve()
    args.corpus = args.corpus.resolve()
    args.accepted_library = args.accepted_library.resolve()
    affinities = tuple(int(value) for value in args.affinities.split(","))
    if args.games < 1 or args.shard_count < 1 or len(affinities) != args.shard_count:
        raise ValueError("games, shards, and affinities are inconsistent")
    if args.games % args.shard_count:
        raise ValueError("preflight games must divide evenly across generation shards")
    available = psutil.cpu_count(logical=True) or 1
    if len(set(affinities)) != len(affinities) or any(
        affinity < 0 or affinity >= available for affinity in affinities
    ):
        raise ValueError("affinities must be unique available logical processors")

    work_dir = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    status_path = work_dir / "preflight_status.json"
    summary_path = work_dir / "preflight_summary.json"
    development_manifest = work_dir / "development_selection_manifest.json"
    sealed_test_manifest = work_dir / "sealed_test_selection_manifest.json"
    commitment_path = work_dir / "selection_partition_commitment.json"
    ensure_interactive_session_inactive("scaling preflight startup")
    status = {
        "format": FORMAT,
        "state": "starting",
        "games": args.games,
        "seed_start": args.seed_start,
        "shards": args.shard_count,
    }
    atomic_write_json(status_path, status)
    try:
        config = run_config_lock(args)
        if config["state"] != "PASS":
            atomic_write_json(status_path, {**status, "state": config["state"]})
            return

        initial_game_count = sum(path.exists() for path in scheduled_game_paths(args))
        generation = run_worker_stage(
            work_dir=work_dir,
            stage="generation",
            commands=generation_commands(args),
            affinities=affinities,
            timeout_minutes=args.generation_timeout_minutes,
        )
        if generation["state"] != "PASS":
            atomic_write_json(status_path, {**status, "state": generation["state"]})
            return
        game_paths = scheduled_game_paths(args)
        if not all(path.exists() for path in game_paths):
            raise RuntimeError("generation stage did not complete every source file")
        with BatchWorkLease(ROOT) as coordinator_lease:
            full_manifest, _selected = build_selection_manifest(
                game_paths,
                max_positions_per_game=args.max_positions_per_game,
                checkpoint=coordinator_lease.checkpoint,
            )
            coordinator_lease.checkpoint("selection partition sealing")
            commitment = partition_and_seal_manifest(
                full_manifest,
                development_path=development_manifest,
                sealed_test_path=sealed_test_manifest,
                commitment_path=commitment_path,
            )

        initial_analysis_count = len(list((work_dir / "analyses").glob("*.analysis.json")))
        analysis = run_worker_stage(
            work_dir=work_dir,
            stage="analysis",
            commands=analysis_commands(args, development_manifest),
            affinities=affinities,
            timeout_minutes=args.analysis_timeout_minutes,
        )
        if analysis["state"] != "PASS":
            atomic_write_json(status_path, {**status, "state": analysis["state"]})
            return
        with BatchWorkLease(ROOT) as coordinator_lease:
            first = validate_preflight_outputs(
                args,
                development_manifest_path=development_manifest,
                commitment_path=commitment_path,
                checkpoint=coordinator_lease.checkpoint,
            )
        reproduction = None
        if not args.skip_resume_reproduction:
            generation_resume = run_worker_stage(
                work_dir=work_dir,
                stage="generation_resume",
                commands=generation_commands(args),
                affinities=affinities,
                timeout_minutes=args.generation_timeout_minutes,
            )
            if generation_resume["state"] != "PASS":
                atomic_write_json(
                    status_path, {**status, "state": generation_resume["state"]}
                )
                return
            with BatchWorkLease(ROOT) as coordinator_lease:
                reproduced_full, _selected = build_selection_manifest(
                    game_paths,
                    max_positions_per_game=args.max_positions_per_game,
                    checkpoint=coordinator_lease.checkpoint,
                )
                coordinator_lease.checkpoint("resume selection partition sealing")
                partition_and_seal_manifest(
                    reproduced_full,
                    development_path=development_manifest,
                    sealed_test_path=sealed_test_manifest,
                    commitment_path=commitment_path,
                )
            analysis_resume = run_worker_stage(
                work_dir=work_dir,
                stage="analysis_resume",
                commands=analysis_commands(args, development_manifest),
                affinities=affinities,
                timeout_minutes=args.analysis_timeout_minutes,
            )
            if analysis_resume["state"] != "PASS":
                atomic_write_json(
                    status_path, {**status, "state": analysis_resume["state"]}
                )
                return
            with BatchWorkLease(ROOT) as coordinator_lease:
                second = validate_preflight_outputs(
                    args,
                    development_manifest_path=development_manifest,
                    commitment_path=commitment_path,
                    checkpoint=coordinator_lease.checkpoint,
                )
            reproduction = {
                "generation": generation_resume,
                "analysis": analysis_resume,
                "source_games_byte_identical": first["source_game_hashes"]
                == second["source_game_hashes"],
                "development_analyses_byte_identical": first[
                    "development_analysis_hashes"
                ]
                == second["development_analysis_hashes"],
                "development_manifest_byte_identical": first[
                    "development_manifest_sha256"
                ]
                == second["development_manifest_sha256"],
                "sealed_test_manifest_byte_identical": first[
                    "sealed_test_manifest_sha256"
                ]
                == second["sealed_test_manifest_sha256"],
            }
            if not all(
                value
                for key, value in reproduction.items()
                if key.endswith("byte_identical")
            ):
                raise RuntimeError("resume reproduction changed locked artifacts")

        deterministic_outputs = {
            key: first[key]
            for key in (
                "generated_source_files",
                "source_game_hashes",
                "generation_shard_manifest_hashes",
                "analysis_shard_manifest_hashes",
                "development_games",
                "development_manifest_sha256",
                "sealed_test_games",
                "sealed_test_selected_positions",
                "sealed_test_manifest_sha256",
                "test_analysis_files_read",
                "analysis_files",
                "development_analysis_hashes",
                "eligible_development_labels",
                "stderr_bytes",
                "temporary_files",
            )
        }
        deterministic_summary = {
            "format": FORMAT,
            "kind": "scalable-acquisition-harness-preflight-summary",
            "verdict": "PASS",
            "playing_code_changed": False,
            "model_trained": False,
            "contract": {
                "games": args.games,
                "seed_start": args.seed_start,
                "generation_depth": args.generation_depth,
                "max_game_plies": args.max_game_plies,
                "max_positions_per_game": args.max_positions_per_game,
                "hash_mb": args.hash_mb,
                "budgets_ms": args.budgets_ms,
                "shard_count": args.shard_count,
                "analysis_splits": list(DEVELOPMENT_SPLITS),
            },
            "accepted_library_sha256": sha256(args.accepted_library),
            "acquisition_script_sha256": sha256(
                ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"
            ),
            "coordinator_script_sha256": sha256(Path(__file__).resolve()),
            "workload_isolation_sha256": sha256(
                ROOT / "makhos" / "workload_isolation.py"
            ),
            "config_sha256": config["config_sha256"],
            "selection_partition": commitment,
            "outputs": deterministic_outputs,
            "resume_reproduction": {
                key: value
                for key, value in (reproduction or {}).items()
                if key.endswith("byte_identical")
            },
            "gates": {
                "all_source_files_generated": first["generated_source_files"]
                == args.games,
                "all_development_games_analyzed": first["analysis_files"]
                == first["development_games"],
                "development_workers_read_zero_test_analyses": first[
                    "test_analysis_files_read"
                ]
                == 0,
                "empty_worker_stderr": first["stderr_bytes"] == 0,
                "no_temporary_artifacts": first["temporary_files"] == 0,
                "generation_resume_byte_identical": bool(
                    reproduction
                    and reproduction["source_games_byte_identical"]
                ),
                "analysis_resume_byte_identical": bool(
                    reproduction
                    and reproduction["development_analyses_byte_identical"]
                ),
                "development_manifest_resume_byte_identical": bool(
                    reproduction
                    and reproduction["development_manifest_byte_identical"]
                ),
                "sealed_test_manifest_resume_byte_identical": bool(
                    reproduction
                    and reproduction["sealed_test_manifest_byte_identical"]
                ),
            },
            "next_gate": (
                "authorize the locked 15360-file acquisition only after this "
                "PASS is documented; NNUE training remains unauthorized"
            ),
        }
        if not all(deterministic_summary["gates"].values()):
            raise RuntimeError("deterministic preflight summary has failed gates")
        atomic_write_json(summary_path, deterministic_summary)
        final = {
            "format": FORMAT,
            "kind": "scalable-acquisition-harness-preflight",
            "state": "PASS",
            "playing_code_changed": False,
            "model_trained": False,
            "accepted_library_sha256": sha256(args.accepted_library),
            "acquisition_script_sha256": sha256(
                ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"
            ),
            "coordinator_script_sha256": sha256(Path(__file__).resolve()),
            "workload_isolation_sha256": sha256(
                ROOT / "makhos" / "workload_isolation.py"
            ),
            "config": config,
            "generation": {
                **generation,
                "initial_source_files": initial_game_count,
                "new_source_files": args.games - initial_game_count,
            },
            "selection_partition": commitment,
            "analysis": {
                **analysis,
                "initial_analysis_files": initial_analysis_count,
                "new_analysis_files": first["analysis_files"]
                - initial_analysis_count,
            },
            "outputs": first,
            "resume_reproduction": reproduction,
            "test_analysis_files_read": 0,
            "deterministic_summary": str(summary_path),
            "deterministic_summary_sha256": sha256(summary_path),
            "next_gate": (
                "authorize the locked 15360-file acquisition only after this "
                "PASS is documented; NNUE training remains unauthorized"
            ),
        }
        atomic_write_json(status_path, final)
        print(
            json.dumps(
                {
                    "status": str(status_path),
                    "status_sha256": sha256(status_path),
                    "summary": str(summary_path),
                    "summary_sha256": sha256(summary_path),
                    "state": "PASS",
                    "generated_source_files": first["generated_source_files"],
                    "development_analyses": first["analysis_files"],
                    "sealed_test_games": first["sealed_test_games"],
                    "test_analysis_files_read": 0,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    except InteractiveSessionActive as error:
        paused = {
            **status,
            "state": "PAUSED_FOR_INTERACTIVE_PLAY",
            "reason": str(error),
        }
        atomic_write_json(status_path, paused)
        print(json.dumps(paused, sort_keys=True), flush=True)
    except Exception as error:
        failure = {**status, "state": "FAILED", "error": str(error)}
        atomic_write_json(status_path, failure)
        raise


if __name__ == "__main__":
    main()
