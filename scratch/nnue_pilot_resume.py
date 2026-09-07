"""Safely resume the locked NNUE quiet-leaf acquisition pilot.

This coordinator changes no playing code and trains no model.  It validates
the locked v4 evidence, starts one whole-game worker per shard, and records a
reproducible resume entry before a detached finalizer watches the run.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
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

from makhos.workload_isolation import (  # noqa: E402
    ensure_interactive_session_inactive,
)
from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    validate_existing_analysis,
    validate_selection_manifest,
)


DEFAULT_WORK_DIR = ROOT / "build" / "nnue_quiet_leaf_pilot_v4"
DEFAULT_CORPUS = ROOT / "corpora" / "nnue_quiet_leaf_pilot_v4.jsonl"
DEFAULT_AFFINITIES = (0, 2, 4, 6)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    replace_with_retry(temporary, path)


def replace_with_retry(
    temporary: Path,
    destination: Path,
    *,
    attempts: int = 100,
    delay_seconds: float = 0.05,
) -> None:
    """Atomically replace a status file despite transient Windows readers."""

    if attempts < 1 or delay_seconds < 0:
        raise ValueError("replace retry settings must be non-negative and non-empty")
    for attempt in range(attempts):
        try:
            temporary.replace(destination)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(delay_seconds)


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != expected.upper():
        raise RuntimeError(f"{label} SHA-256 changed: expected {expected}, got {actual}")
    return actual


def active_pilot_processes(work_dir: Path) -> list[dict]:
    """Return live acquisition/finalizer processes for this exact work dir."""

    work_text = str(work_dir.resolve()).casefold()
    conflicts = []
    for process in psutil.process_iter(("pid", "cmdline", "create_time")):
        try:
            command = [str(part) for part in (process.info["cmdline"] or [])]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        joined = " ".join(command).casefold()
        is_pilot = (
            "nnue_quiet_leaf_acquire.py" in joined
            or "nnue_pilot_finalize.py" in joined
        )
        if is_pilot and work_text in joined:
            conflicts.append(
                {
                    "pid": int(process.info["pid"]),
                    "create_time": float(process.info["create_time"]),
                    "command": command,
                }
            )
    return conflicts


def worker_command(
    *,
    config: dict,
    work_dir: Path,
    corpus: Path,
    shard_count: int,
    shard_index: int,
) -> list[str]:
    command = [
        sys.executable,
        "-B",
        str(ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"),
        "--accepted-library",
        str(Path(config["accepted_library"]).resolve()),
        "--work-dir",
        str(work_dir.resolve()),
        "--corpus",
        str(corpus.resolve()),
        "--games",
        str(config["games"]),
        "--seed-start",
        str(config["seed_start"]),
        "--generation-depth",
        str(config["generation_depth"]),
        "--max-game-plies",
        str(config["max_game_plies"]),
        "--max-positions-per-game",
        str(config["max_positions_per_game"]),
        "--hash-mb",
        str(config["hash_mb"]),
        "--budgets-ms",
        ",".join(str(value) for value in config["budgets_ms"]),
        "--tablebase-provenance",
        str(Path(config["tablebase_provenance"]).resolve()),
        "--coverage-target",
        str(config["coverage_target"]),
        "--analysis-shard-count",
        str(shard_count),
        "--analysis-shard-index",
        str(shard_index),
    ]
    for tablebase in config["tablebases"]:
        command.extend(("--tablebase", str(Path(tablebase["path"]).resolve())))
    return command


def finalizer_command(
    *,
    config: dict,
    work_dir: Path,
    corpus: Path,
    worker_pids: list[int],
    poll_seconds: int,
    stall_minutes: int,
) -> list[str]:
    return [
        sys.executable,
        "-B",
        str(ROOT / "scratch" / "nnue_pilot_finalize.py"),
        "--work-dir",
        str(work_dir.resolve()),
        "--corpus",
        str(corpus.resolve()),
        "--games",
        str(config["games"]),
        "--seed-start",
        str(config["seed_start"]),
        "--coverage-target",
        str(config["coverage_target"]),
        "--worker-pids",
        ",".join(str(pid) for pid in worker_pids),
        "--poll-seconds",
        str(poll_seconds),
        "--stall-minutes",
        str(stall_minutes),
    ]


def validate_resume_state(
    work_dir: Path,
    *,
    shard_count: int,
) -> dict:
    ensure_interactive_session_inactive("NNUE pilot resume validation")
    work_dir = work_dir.resolve()
    config_path = work_dir / "config.json"
    selection_path = work_dir / "selection_manifest.json"
    preflight_path = work_dir / "preflight_summary.json"
    run_manifest_path = work_dir / "acquisition_run_manifest.json"
    config = read_json(config_path)
    selection = read_json(selection_path)
    run_manifest = read_json(run_manifest_path)
    validate_selection_manifest(selection)

    required_config = {
        "format": "thai-makhos-nnue-quiet-leaf-acquisition-v1",
        "kind": "locked-config",
        "threads": 1,
        "persistent_search": True,
    }
    for key, expected in required_config.items():
        if config.get(key) != expected:
            raise RuntimeError(f"locked config {key} differs: {config.get(key)!r}")
    if shard_count != int(run_manifest["worker_count"]):
        raise RuntimeError("requested shard count differs from acquisition manifest")
    if len(config.get("budgets_ms", [])) < 2 or config.get("coverage_target") is None:
        raise RuntimeError("locked config lacks teacher budgets or coverage target")

    hashes = {
        "config_sha256": require_hash(
            config_path, run_manifest["config_sha256"], "locked config"
        ),
        "selection_manifest_sha256": require_hash(
            selection_path,
            run_manifest["selection_manifest_sha256"],
            "selection manifest",
        ),
        "preflight_summary_sha256": require_hash(
            preflight_path,
            run_manifest["preflight_summary_sha256"],
            "preflight summary",
        ),
        "accepted_library_sha256": require_hash(
            Path(config["accepted_library"]),
            run_manifest["accepted_library_sha256"],
            "accepted library",
        ),
        "acquisition_script_sha256": require_hash(
            ROOT / "scratch" / "nnue_quiet_leaf_acquire.py",
            run_manifest["acquisition_script_sha256_for_resume"],
            "acquisition script",
        ),
        "finalizer_script_sha256": require_hash(
            ROOT / "scratch" / "nnue_pilot_finalize.py",
            run_manifest["finalizer_script_sha256_for_resume"],
            "finalizer script",
        ),
        "workload_isolation_sha256": require_hash(
            ROOT / "makhos" / "workload_isolation.py",
            run_manifest["workload_isolation"]["source_sha256"],
            "workload isolation",
        ),
    }
    if hashes["accepted_library_sha256"] != config["accepted_library_sha256"]:
        raise RuntimeError("accepted library differs between locked config and run manifest")

    shard_paths = sorted((work_dir / "execution_shards").glob("*.json"))
    expected_shard_hashes = run_manifest["execution_shard_manifest_sha256"]
    if len(shard_paths) != shard_count or len(expected_shard_hashes) != shard_count:
        raise RuntimeError("execution-shard manifest count differs")
    for index, (path, expected) in enumerate(zip(shard_paths, expected_shard_hashes)):
        require_hash(path, expected, f"execution shard {index}")

    games = selection["games"]
    game_by_id = {game["game_id"]: game for game in games}
    if len(game_by_id) != len(games):
        raise RuntimeError("selection manifest contains duplicate game ids")
    analysis_paths = sorted((work_dir / "analyses").glob("*.analysis.json"))
    for path in analysis_paths:
        game_id = path.name.removesuffix(".analysis.json")
        if game_id not in game_by_id:
            raise RuntimeError(f"unexpected analysis outside locked manifest: {path.name}")
        validate_existing_analysis(
            read_json(path),
            game=game_by_id[game_id],
            library_sha256=config["accepted_library_sha256"],
            budgets_ms=tuple(config["budgets_ms"]),
        )

    stderr_bytes = sum(
        path.stat().st_size
        for path in (work_dir / "worker_logs").glob("*.stderr.log")
    )
    if stderr_bytes:
        raise RuntimeError(f"existing worker stderr is non-empty: {stderr_bytes} bytes")
    conflicts = active_pilot_processes(work_dir)
    if conflicts:
        raise RuntimeError(f"pilot already has live processes: {conflicts}")

    return {
        "config": config,
        "selection": selection,
        "run_manifest": run_manifest,
        "hashes": hashes,
        "completed_analyses": len(analysis_paths),
        "required_analyses": len(games),
        "stderr_bytes": stderr_bytes,
    }


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        subprocess.CREATE_NO_WINDOW
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    )


def _spawn(command: list[str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=environment,
            creationflags=_creation_flags(),
            close_fds=True,
        )


def _stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5.0
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument("--affinities", default="0,2,4,6")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--stall-minutes", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    affinities = tuple(int(value) for value in args.affinities.split(","))
    if args.shard_count < 1 or len(affinities) != args.shard_count:
        parser.error("affinities must contain exactly one processor per shard")
    if len(set(affinities)) != len(affinities) or min(affinities) < 0:
        parser.error("affinities must be unique non-negative processor indexes")
    if args.poll_seconds < 1 or args.stall_minutes < 1:
        parser.error("poll seconds and stall minutes must be positive")

    work_dir = args.work_dir.resolve()
    corpus = args.corpus.resolve()
    state = validate_resume_state(work_dir, shard_count=args.shard_count)
    config = state["config"]
    commands = [
        worker_command(
            config=config,
            work_dir=work_dir,
            corpus=corpus,
            shard_count=args.shard_count,
            shard_index=shard,
        )
        for shard in range(args.shard_count)
    ]
    preflight = {
        "kind": "nnue-pilot-resume-preflight",
        "verdict": "PASS",
        "completed_analyses": state["completed_analyses"],
        "required_analyses": state["required_analyses"],
        "stderr_bytes": state["stderr_bytes"],
        "hashes": state["hashes"],
        "affinities": list(affinities),
        "worker_commands": commands,
    }
    if args.dry_run:
        print(json.dumps(preflight, indent=2, sort_keys=True), flush=True)
        return

    ensure_interactive_session_inactive("NNUE pilot worker launch")
    stamp = datetime.now().astimezone()
    file_stamp = stamp.strftime("%Y%m%dT%H%M%S%z")
    log_dir = work_dir / "worker_logs"
    processes: list[subprocess.Popen] = []
    workers = []
    try:
        for shard, (affinity, command) in enumerate(zip(affinities, commands)):
            stdout_path = log_dir / f"resume_{file_stamp}_shard_{shard:02d}.stdout.log"
            stderr_path = log_dir / f"resume_{file_stamp}_shard_{shard:02d}.stderr.log"
            process = _spawn(command, stdout_path, stderr_path)
            processes.append(process)
            native_process = psutil.Process(process.pid)
            native_process.cpu_affinity([affinity])
            workers.append(
                {
                    "shard": shard,
                    "pid": process.pid,
                    "create_time": native_process.create_time(),
                    "logical_processor_affinity": affinity,
                    "priority": "BelowNormal",
                    "command": command,
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                }
            )
        time.sleep(1.0)
        early_exits = [process.pid for process in processes if process.poll() is not None]
        if early_exits:
            raise RuntimeError(f"workers exited during launch: {early_exits}")
        ensure_interactive_session_inactive("NNUE pilot finalizer launch")

        finalizer_stdout = work_dir / f"finalizer.resume_{file_stamp}.stdout.log"
        finalizer_stderr = work_dir / f"finalizer.resume_{file_stamp}.stderr.log"
        finalize_command = finalizer_command(
            config=config,
            work_dir=work_dir,
            corpus=corpus,
            worker_pids=[process.pid for process in processes],
            poll_seconds=args.poll_seconds,
            stall_minutes=args.stall_minutes,
        )
        finalizer = _spawn(finalize_command, finalizer_stdout, finalizer_stderr)
        processes.append(finalizer)
        finalizer_native = psutil.Process(finalizer.pid)
        time.sleep(0.5)
        if finalizer.poll() is not None:
            raise RuntimeError("finalizer exited during launch")

        resume_entry = {
            "started_local": stamp.isoformat(timespec="seconds"),
            "launcher": str(Path(__file__).resolve()),
            "launcher_sha256": sha256(Path(__file__).resolve()),
            "initial_completed_analyses": state["completed_analyses"],
            "required_analyses": state["required_analyses"],
            "hashes": state["hashes"],
            "workers": workers,
            "finalizer": {
                "pid": finalizer.pid,
                "create_time": finalizer_native.create_time(),
                "priority": "BelowNormal",
                "command": finalize_command,
                "stdout": str(finalizer_stdout),
                "stderr": str(finalizer_stderr),
            },
        }
        run_manifest = state["run_manifest"]
        run_manifest.setdefault("resume_history", []).append(resume_entry)
        run_manifest["state"] = "RUNNING"
        run_manifest["worker_pids"] = [process.pid for process in processes[:-1]]
        run_manifest["finalizer_pid"] = finalizer.pid
        run_manifest["last_resumed_local"] = resume_entry["started_local"]
        atomic_write_json(work_dir / "acquisition_run_manifest.json", run_manifest)
        atomic_write_json(
            work_dir / "finalizer_status.json",
            {
                "kind": "acquisition-finalizer-status",
                "state": "RESUME_STARTED",
                "completed_analyses": state["completed_analyses"],
                "required_analyses": state["required_analyses"],
                "worker_pids": run_manifest["worker_pids"],
                "finalizer_pid": finalizer.pid,
            },
        )
        print(json.dumps(resume_entry, indent=2, sort_keys=True), flush=True)
    except Exception:
        _stop_processes(processes)
        raise


if __name__ == "__main__":
    main()
