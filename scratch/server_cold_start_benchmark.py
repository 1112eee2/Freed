"""Measure browser readiness and the first production GUI search."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
INITIAL_POSITION = "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def post_json(url: str, payload: dict, *, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def reserve_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time-ms", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--hash-mb", type=int, default=512)
    args = parser.parse_args()
    if args.time_ms < 10 or args.threads < 1 or args.hash_mb < 4:
        parser.error("time, Threads, and Hash must be positive production values")

    port = reserve_ephemeral_port()
    command = [
        sys.executable,
        str(ROOT / "server.py"),
        "--port",
        str(port),
        "--no-browser",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    state = None
    try:
        deadline = time.perf_counter() + 10.0
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"server exited before readiness: {process.returncode}")
            try:
                state = post_json(
                    f"http://127.0.0.1:{port}/api/state",
                    {},
                    timeout=0.25,
                )
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.01)
        if state is None:
            raise RuntimeError("server did not become ready within 10 seconds")
        ready_ms = (time.perf_counter() - started) * 1000

        search_started = time.perf_counter()
        result = post_json(
            f"http://127.0.0.1:{port}/api/bestmove",
            {
                "position": INITIAL_POSITION,
                "history": [INITIAL_POSITION],
                "time_sec": args.time_ms / 1000.0,
                "depth": 64,
                "threads": args.threads,
                "hash_mb": args.hash_mb,
                "mode": "win",
                "rules_profile": "project",
            },
            timeout=max(10.0, args.time_ms / 1000.0 + 5.0),
        )
        first_search_wall_ms = (time.perf_counter() - search_started) * 1000
        payload = {
            "kind": "server-cold-start-benchmark",
            "ready_ms": round(ready_ms, 3),
            "first_search_wall_ms": round(first_search_wall_ms, 3),
            "requested_time_ms": args.time_ms,
            "threads": args.threads,
            "hash_mb": args.hash_mb,
            "state_position_round_trip": state.get("position") == INITIAL_POSITION,
            "response": result,
            "server_source_sha256": sha256(ROOT / "makhos" / "server.py"),
            "isolation_source_sha256": sha256(
                ROOT / "makhos" / "workload_isolation.py"
            ),
        }
        if args.output is not None:
            atomic_write_json(args.output.resolve(), payload)
        print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        if process.returncode not in (0, 1):
            print(f"server exit code: {process.returncode}", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr, end="")


if __name__ == "__main__":
    main()
