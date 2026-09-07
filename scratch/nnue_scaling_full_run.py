"""Supervise the locked 15,360-game NNUE data-acquisition run.

This launches only the accepted classical teacher/data pipeline.  It trains no
model, never opens sealed test labels, and automatically resumes after an
interactive GUI session releases priority.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.workload_isolation import interactive_session_active  # noqa: E402
from scratch.nnue_pilot_resume import atomic_write_json  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    EXPECTED_ACCEPTED_SHA256,
    sha256,
    write_locked_json,
)
from scratch.nnue_scaling_preflight import run_config_lock  # noqa: E402


FORMAT = "thai-makhos-nnue-scaling-full-run-v1"
FULL_GAMES = 15_360
FULL_SEED_START = 20_280_001
FULL_SEED_END = FULL_SEED_START + FULL_GAMES - 1
PREFLIGHT_SEED_START = 20_270_001
PREFLIGHT_SEED_END = 20_270_096
FULL_SHARDS = 6
FULL_AFFINITIES = (0, 2, 4, 6, 8, 10)
GENERATION_DEPTH = 7
MAX_GAME_PLIES = 200
MAX_POSITIONS_PER_GAME = 64
HASH_MB = 256
BUDGETS_MS = "100,500,2000"
GENERATION_TIMEOUT_MINUTES = 360
ANALYSIS_TIMEOUT_MINUTES = 5_760
EXPECTED_CAPACITY_AUDIT_SHA256 = (
    "9F27BCEAADA11695E1049D4F68A34D26ACAF509E25DFDF1D914E9AA74E360C59"
)
DEFAULT_WORK_DIR = ROOT / "build" / "nnue_scaling_full_v1"
DEFAULT_CORPUS = ROOT / "corpora" / "nnue_scaling_full_v1_unused.jsonl"
DEFAULT_PREFLIGHT_SUMMARY = (
    ROOT / "build" / "nnue_scaling_preflight_v1" / "preflight_summary.json"
)
DEFAULT_CAPACITY_AUDIT = ROOT / "build" / "nnue_scaling_capacity_audit_v1.json"
DEFAULT_ACCEPTED = ROOT / "build" / "makhos_native_accepted.dll"


def parse_affinities(text: str) -> tuple[int, ...]:
    return tuple(int(value) for value in text.split(","))


def validate_locked_contract(args: argparse.Namespace) -> dict:
    affinities = parse_affinities(args.affinities)
    expected = {
        "games": FULL_GAMES,
        "seed_start": FULL_SEED_START,
        "generation_depth": GENERATION_DEPTH,
        "max_game_plies": MAX_GAME_PLIES,
        "max_positions_per_game": MAX_POSITIONS_PER_GAME,
        "hash_mb": HASH_MB,
        "budgets_ms": BUDGETS_MS,
        "shard_count": FULL_SHARDS,
        "affinities": FULL_AFFINITIES,
        "generation_timeout_minutes": GENERATION_TIMEOUT_MINUTES,
        "analysis_timeout_minutes": ANALYSIS_TIMEOUT_MINUTES,
    }
    actual = {
        "games": args.games,
        "seed_start": args.seed_start,
        "generation_depth": args.generation_depth,
        "max_game_plies": args.max_game_plies,
        "max_positions_per_game": args.max_positions_per_game,
        "hash_mb": args.hash_mb,
        "budgets_ms": args.budgets_ms,
        "shard_count": args.shard_count,
        "affinities": affinities,
        "generation_timeout_minutes": args.generation_timeout_minutes,
        "analysis_timeout_minutes": args.analysis_timeout_minutes,
    }
    if actual != expected:
        differences = {
            key: {"expected": expected[key], "actual": actual[key]}
            for key in expected
            if actual[key] != expected[key]
        }
        raise RuntimeError(f"full-run contract changed: {differences}")
    seed_end = args.seed_start + args.games - 1
    if not (seed_end < PREFLIGHT_SEED_START or args.seed_start > PREFLIGHT_SEED_END):
        raise RuntimeError("full-run seed range overlaps the sealed preflight")
    if args.games % args.shard_count:
        raise RuntimeError("full-run games do not divide evenly across shards")
    available = psutil.cpu_count(logical=True) or 1
    if any(value < 0 or value >= available for value in affinities):
        raise RuntimeError("full-run affinity is unavailable on this host")
    return {**actual, "seed_end": seed_end}


def validate_authorization(args: argparse.Namespace) -> dict:
    accepted_sha = sha256(args.accepted_library.resolve())
    if accepted_sha != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity changed before full acquisition")
    capacity_sha = sha256(args.capacity_audit.resolve())
    if capacity_sha != EXPECTED_CAPACITY_AUDIT_SHA256:
        raise RuntimeError("scaling-capacity audit identity changed")
    preflight_path = args.preflight_summary.resolve()
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("verdict") != "PASS" or not all(
        preflight.get("gates", {}).values()
    ):
        raise RuntimeError("scalable-harness preflight is not a clean PASS")
    if preflight.get("accepted_library_sha256") != accepted_sha:
        raise RuntimeError("preflight accepted DLL differs from full-run control")
    if preflight.get("acquisition_script_sha256") != sha256(
        ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"
    ):
        raise RuntimeError("preflight does not bind the current acquisition worker")
    if preflight.get("coordinator_script_sha256") != sha256(
        ROOT / "scratch" / "nnue_scaling_preflight.py"
    ):
        raise RuntimeError("preflight does not bind the current coordinator")
    if preflight.get("outputs", {}).get("test_analysis_files_read") != 0:
        raise RuntimeError("preflight test-analysis isolation gate changed")
    return {
        "accepted_library_sha256": accepted_sha,
        "capacity_audit_sha256": capacity_sha,
        "preflight_summary_sha256": sha256(preflight_path),
    }


def coordinator_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        "-B",
        str(ROOT / "scratch" / "nnue_scaling_preflight.py"),
        "--work-dir",
        str(args.work_dir.resolve()),
        "--corpus",
        str(args.corpus.resolve()),
        "--accepted-library",
        str(args.accepted_library.resolve()),
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
        "--shard-count",
        str(args.shard_count),
        "--affinities",
        args.affinities,
        "--generation-timeout-minutes",
        str(args.generation_timeout_minutes),
        "--analysis-timeout-minutes",
        str(args.analysis_timeout_minutes),
    ]


def verify_current_bindings(args: argparse.Namespace, manifest: dict) -> None:
    expected = {
        "config_sha256": sha256(args.work_dir / "config.json"),
        "acquisition_script_sha256": sha256(
            ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"
        ),
        "coordinator_script_sha256": sha256(
            ROOT / "scratch" / "nnue_scaling_preflight.py"
        ),
        "supervisor_script_sha256": sha256(Path(__file__).resolve()),
        "workload_isolation_sha256": sha256(
            ROOT / "makhos" / "workload_isolation.py"
        ),
    }
    for key, actual in expected.items():
        if manifest.get(key) != actual:
            raise RuntimeError(f"full-run resume binding changed: {key}")
    authorization = manifest.get("authorization", {})
    current_authorization = validate_authorization(args)
    if authorization != current_authorization:
        raise RuntimeError("full-run authorization artifacts changed")
    if manifest.get("coordinator_command") != coordinator_command(args):
        raise RuntimeError("full-run coordinator command changed")


def progress_counts(work_dir: Path) -> dict:
    return {
        "source_files": len(list((work_dir / "games").glob("*.json"))),
        "development_analyses": len(
            list((work_dir / "analyses").glob("*.analysis.json"))
        ),
    }


def classify_coordinator_exit(returncode: int, status: dict, stderr_bytes: int) -> str:
    if returncode or stderr_bytes:
        return "FAILED"
    state = status.get("state")
    if state == "PASS":
        return "PASS"
    if state == "PAUSED_FOR_INTERACTIVE_PLAY":
        return "PAUSED_FOR_INTERACTIVE_PLAY"
    return "FAILED"


def live_full_run_processes(work_dir: Path) -> list[dict]:
    work_text = str(work_dir.resolve()).casefold()
    names = (
        "nnue_scaling_full_run.py",
        "nnue_scaling_preflight.py",
        "nnue_quiet_leaf_acquire.py",
    )
    rows = []
    for process in psutil.process_iter(("pid", "cmdline", "create_time")):
        if process.pid == os.getpid():
            continue
        try:
            command = [str(value) for value in (process.info["cmdline"] or [])]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        joined = " ".join(command).casefold()
        entrypoints = {
            Path(value.strip('"')).name.casefold()
            for value in command
            if value.strip('"')
            and not any(character.isspace() for character in value.strip('"'))
        }
        full_supervisor = "nnue_scaling_full_run.py" in entrypoints
        scoped_worker = work_text in joined and any(
            name in entrypoints for name in names[1:]
        )
        if full_supervisor or scoped_worker:
            rows.append(
                {
                    "pid": int(process.pid),
                    "create_time": float(process.info["create_time"]),
                    "command": command,
                }
            )
    return rows


def creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        subprocess.CREATE_NO_WINDOW
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--accepted-library", type=Path, default=DEFAULT_ACCEPTED)
    parser.add_argument(
        "--preflight-summary", type=Path, default=DEFAULT_PREFLIGHT_SUMMARY
    )
    parser.add_argument("--capacity-audit", type=Path, default=DEFAULT_CAPACITY_AUDIT)
    parser.add_argument("--games", type=int, default=FULL_GAMES)
    parser.add_argument("--seed-start", type=int, default=FULL_SEED_START)
    parser.add_argument("--generation-depth", type=int, default=GENERATION_DEPTH)
    parser.add_argument("--max-game-plies", type=int, default=MAX_GAME_PLIES)
    parser.add_argument(
        "--max-positions-per-game", type=int, default=MAX_POSITIONS_PER_GAME
    )
    parser.add_argument("--hash-mb", type=int, default=HASH_MB)
    parser.add_argument("--budgets-ms", default=BUDGETS_MS)
    parser.add_argument("--shard-count", type=int, default=FULL_SHARDS)
    parser.add_argument(
        "--affinities", default=",".join(str(value) for value in FULL_AFFINITIES)
    )
    parser.add_argument(
        "--generation-timeout-minutes",
        type=int,
        default=GENERATION_TIMEOUT_MINUTES,
    )
    parser.add_argument(
        "--analysis-timeout-minutes",
        type=int,
        default=ANALYSIS_TIMEOUT_MINUTES,
    )
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--retry-seconds", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.work_dir = args.work_dir.resolve()
    args.corpus = args.corpus.resolve()
    args.accepted_library = args.accepted_library.resolve()
    args.preflight_summary = args.preflight_summary.resolve()
    args.capacity_audit = args.capacity_audit.resolve()
    if args.poll_seconds < 1 or args.retry_seconds < 1:
        raise ValueError("poll and retry intervals must be positive")
    contract = validate_locked_contract(args)
    authorization = validate_authorization(args)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    status_path = args.work_dir / "full_run_supervisor_status.json"
    manifest_path = args.work_dir / "full_run_manifest.json"
    coordinator_status_path = args.work_dir / "preflight_status.json"
    conflicts = live_full_run_processes(args.work_dir)
    if conflicts:
        raise RuntimeError(f"full acquisition already has live processes: {conflicts}")

    while True:
        config = run_config_lock(args)
        if config["state"] == "PASS":
            break
        atomic_write_json(
            status_path,
            {
                "format": FORMAT,
                "state": "PAUSED_FOR_INTERACTIVE_PLAY",
                "stage": "config-lock",
                **progress_counts(args.work_dir),
            },
        )
        time.sleep(args.retry_seconds)
    games_dir = args.work_dir / "games"
    if not manifest_path.exists() and games_dir.exists() and any(games_dir.iterdir()):
        raise RuntimeError("source files exist before the full-run manifest lock")
    command = coordinator_command(args)
    run_manifest = {
        "format": FORMAT,
        "kind": "locked-full-run-manifest",
        "playing_code_changed": False,
        "model_trained": False,
        "sealed_test_labels_opened": False,
        "contract": contract,
        "authorization": authorization,
        "config_sha256": config["config_sha256"],
        "acquisition_script_sha256": sha256(
            ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"
        ),
        "coordinator_script_sha256": sha256(
            ROOT / "scratch" / "nnue_scaling_preflight.py"
        ),
        "supervisor_script_sha256": sha256(Path(__file__).resolve()),
        "workload_isolation_sha256": sha256(
            ROOT / "makhos" / "workload_isolation.py"
        ),
        "coordinator_command": command,
        "resume_policy": "wait while GUI is active; rerun the locked coordinator",
    }
    write_locked_json(manifest_path, run_manifest)
    manifest_sha = sha256(manifest_path)
    attempt = 0
    while True:
        if interactive_session_active():
            atomic_write_json(
                status_path,
                {
                    "format": FORMAT,
                    "state": "PAUSED_FOR_INTERACTIVE_PLAY",
                    "attempt": attempt,
                    "full_run_manifest_sha256": manifest_sha,
                    **progress_counts(args.work_dir),
                },
            )
            time.sleep(args.retry_seconds)
            continue
        verify_current_bindings(args, run_manifest)
        attempt += 1
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        log_dir = args.work_dir / "supervisor_logs"
        stdout_path = log_dir / f"coordinator_{stamp}_attempt_{attempt:03d}.stdout.log"
        stderr_path = log_dir / f"coordinator_{stamp}_attempt_{attempt:03d}.stderr.log"
        log_dir.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creation_flags(),
                close_fds=True,
            )
        while process.poll() is None:
            coordinator_state = None
            if coordinator_status_path.exists():
                try:
                    coordinator_state = json.loads(
                        coordinator_status_path.read_text(encoding="utf-8")
                    ).get("state")
                except (json.JSONDecodeError, OSError):
                    coordinator_state = "updating"
            atomic_write_json(
                status_path,
                {
                    "format": FORMAT,
                    "state": "DRAINING_FOR_INTERACTIVE_PLAY"
                    if interactive_session_active()
                    else "RUNNING",
                    "attempt": attempt,
                    "coordinator_pid": process.pid,
                    "coordinator_state": coordinator_state,
                    "full_run_manifest_sha256": manifest_sha,
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                    **progress_counts(args.work_dir),
                },
            )
            time.sleep(args.poll_seconds)
        stderr_bytes = stderr_path.stat().st_size
        coordinator_status = (
            json.loads(coordinator_status_path.read_text(encoding="utf-8"))
            if coordinator_status_path.exists()
            else {}
        )
        outcome = classify_coordinator_exit(
            int(process.returncode), coordinator_status, stderr_bytes
        )
        final_status = {
            "format": FORMAT,
            "state": outcome,
            "attempt": attempt,
            "coordinator_exit_code": int(process.returncode),
            "coordinator_state": coordinator_status.get("state"),
            "coordinator_status_sha256": sha256(coordinator_status_path)
            if coordinator_status_path.exists()
            else None,
            "stderr_bytes": stderr_bytes,
            "full_run_manifest_sha256": manifest_sha,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            **progress_counts(args.work_dir),
        }
        atomic_write_json(status_path, final_status)
        if outcome == "PASS":
            print(json.dumps(final_status, sort_keys=True), flush=True)
            return
        if outcome == "PAUSED_FOR_INTERACTIVE_PLAY":
            time.sleep(args.retry_seconds)
            continue
        raise RuntimeError(f"full-run coordinator failed: {final_status}")


if __name__ == "__main__":
    main()
