"""Wait for acquisition shards, then reproduce and validate the pilot corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.workload_isolation import interactive_session_active  # noqa: E402


def game_shard(game_id: str, shard_count: int) -> int:
    return int(hashlib.sha256(game_id.encode("ascii")).hexdigest(), 16) % shard_count


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def validate_pass_summary(summary: dict) -> None:
    if summary.get("verdict") != "PASS":
        raise RuntimeError(f"pilot summary is not PASS: {summary.get('verdict')}")
    failed = [name for name, passed in summary.get("gates", {}).items() if not passed]
    if failed:
        raise RuntimeError(f"pilot summary has failed gates: {failed}")


def process_matches(pid: int, create_time: float) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and abs(process.create_time() - create_time) < 0.01
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--coverage-target", type=int, required=True)
    parser.add_argument("--worker-pids", required=True)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--stall-minutes", type=int, default=30)
    args = parser.parse_args()

    pids = [int(value) for value in args.worker_pids.split(",")]
    if not pids or len(set(pids)) != len(pids):
        parser.error("worker-pids must be a non-empty unique comma-separated list")
    if args.games < 1 or args.coverage_target < 1 or args.poll_seconds < 1:
        parser.error("games, coverage target, and poll seconds must be positive")

    work_dir = args.work_dir.resolve()
    analyses_dir = work_dir / "analyses"
    stderr_dir = work_dir / "worker_logs"
    status_path = work_dir / "finalizer_status.json"
    summary_path = work_dir / "summary.json"
    manifest = json.loads((work_dir / "selection_manifest.json").read_text(encoding="utf-8"))
    game_ids = [game["game_id"] for game in manifest["games"]]
    if manifest.get("generated_source_game_files") != args.games:
        raise RuntimeError("selection manifest source-file count differs from finalizer config")
    if len(set(game_ids)) != len(game_ids):
        raise RuntimeError("selection manifest still contains duplicate game ids")
    required_analyses = len(game_ids)
    shard_count = len(pids)
    assigned = {
        shard: {game_id for game_id in game_ids if game_shard(game_id, shard_count) == shard}
        for shard in range(shard_count)
    }
    create_times = {pid: psutil.Process(pid).create_time() for pid in pids}
    last_count = -1
    last_progress = time.monotonic()

    try:
        while True:
            completed = {
                path.name.removesuffix(".analysis.json")
                for path in analyses_dir.glob("*.analysis.json")
            }
            if interactive_session_active():
                status = {
                    "kind": "acquisition-finalizer-status",
                    "state": "PAUSED_FOR_INTERACTIVE_PLAY",
                    "completed_analyses": len(completed),
                    "required_analyses": required_analyses,
                    "generated_source_game_files": args.games,
                }
                write_status(status_path, status)
                print(json.dumps(status, sort_keys=True), flush=True)
                return
            if len(completed) > last_count:
                last_count = len(completed)
                last_progress = time.monotonic()
            stderr_bytes = sum(path.stat().st_size for path in stderr_dir.glob("*.stderr.log"))
            shard_rows = []
            for shard, pid in enumerate(pids):
                done = len(assigned[shard] & completed)
                alive = process_matches(pid, create_times[pid])
                shard_rows.append(
                    {
                        "shard": shard,
                        "pid": pid,
                        "assigned": len(assigned[shard]),
                        "completed": done,
                        "alive": alive,
                    }
                )
                if not alive and done < len(assigned[shard]):
                    raise RuntimeError(f"shard {shard} exited before completing its games")
            status = {
                "kind": "acquisition-finalizer-status",
                "state": "waiting",
                "completed_analyses": len(completed),
                "required_analyses": required_analyses,
                "generated_source_game_files": args.games,
                "stderr_bytes": stderr_bytes,
                "shards": shard_rows,
            }
            write_status(status_path, status)
            print(json.dumps(status, sort_keys=True), flush=True)
            if stderr_bytes:
                raise RuntimeError("worker stderr is non-empty")
            all_done = len(completed) == required_analyses and all(
                row["completed"] == row["assigned"] for row in shard_rows
            )
            if all_done and not any(row["alive"] for row in shard_rows):
                break
            if time.monotonic() - last_progress > args.stall_minutes * 60:
                raise RuntimeError("analysis acquisition made no progress before stall limit")
            time.sleep(args.poll_seconds)

        command = [
            sys.executable,
            "-B",
            str(ROOT / "scratch" / "nnue_quiet_leaf_acquire.py"),
            "--work-dir",
            str(work_dir),
            "--corpus",
            str(args.corpus.resolve()),
            "--games",
            str(args.games),
            "--seed-start",
            str(args.seed_start),
            "--coverage-target",
            str(args.coverage_target),
        ]
        for reproduction in (1, 2):
            completed_run = subprocess.run(command, cwd=ROOT, check=False)
            if completed_run.returncode:
                raise RuntimeError(
                    f"corpus reproduction {reproduction} failed: {completed_run.returncode}"
                )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        validate_pass_summary(summary)
        final_status = {
            "kind": "acquisition-finalizer-status",
            "state": "PASS",
            "completed_analyses": required_analyses,
            "generated_source_game_files": args.games,
            "summary": str(summary_path),
            "summary_sha256": sha256(summary_path),
            "corpus": str(args.corpus.resolve()),
            "corpus_sha256": sha256(args.corpus.resolve()),
        }
        write_status(status_path, final_status)
        print(json.dumps(final_status, sort_keys=True), flush=True)
    except Exception as error:
        failure = {
            "kind": "acquisition-finalizer-status",
            "state": "FAILED",
            "error": str(error),
        }
        write_status(status_path, failure)
        print(json.dumps(failure, sort_keys=True), file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
