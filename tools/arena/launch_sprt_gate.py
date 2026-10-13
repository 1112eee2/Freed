"""Launch a long ``makhos sprt`` gate with fail-closed preflight and a launch record.

Everything after ``--`` is passed to ``python -B -m makhos sprt``. Before the
process starts the tool checks that

* every ``--require PATH=SHA256`` file exists and has that hash;
* the sprt arguments name their tablebases (``--ranked-tablebase`` or
  ``--no-tablebase``) and their native endgame library
  (``--native-endgame-library`` or ``--no-native-endgame``) explicitly;
* every library, model, tablebase and endgame file named in the arguments
  exists;
* no live process already owns the run directory (PID *and* creation time).

It then starts the match at BelowNormal priority with ``stdout.log`` and
``stderr.log`` in the run directory and writes ``launch.txt`` with the PID and
the process creation time, so later tools can verify process identity.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH_FLAGS = (
    "--dev-library",
    "--master-library",
    "--dev-nnue-model",
    "--master-nnue-model",
    "--ranked-tablebase",
    "--native-endgame-library",
)
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_TOLERANCE_SECONDS = 5.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _flag_values(args: list[str], flag: str) -> list[str]:
    values = []
    for index, token in enumerate(args):
        if token == flag and index + 1 < len(args):
            values.append(args[index + 1])
        elif token.startswith(flag + "="):
            values.append(token.split("=", 1)[1])
    return values


def preflight(sprt_args: list[str], cwd: Path, requires: list[str]) -> list[str]:
    """Return a list of problems; an empty list means the gate may start."""
    problems: list[str] = []
    for spec in requires:
        path_text, _, expected = spec.rpartition("=")
        if not path_text or len(expected) != 64:
            problems.append(f"--require must be PATH=SHA256: {spec!r}")
            continue
        path = (cwd / path_text).resolve()
        if not path.is_file():
            problems.append(f"required file absent: {path}")
        elif sha256_file(path).lower() != expected.lower():
            problems.append(f"required file hash differs: {path}")
    if "--no-tablebase" not in sprt_args and not _flag_values(
        sprt_args, "--ranked-tablebase"
    ):
        problems.append("name tablebases explicitly: --ranked-tablebase or --no-tablebase")
    if "--no-native-endgame" not in sprt_args and not _flag_values(
        sprt_args, "--native-endgame-library"
    ):
        problems.append(
            "name the endgame library explicitly: "
            "--native-endgame-library or --no-native-endgame"
        )
    for flag in PATH_FLAGS:
        for value in _flag_values(sprt_args, flag):
            if not (cwd / value).is_file():
                problems.append(f"{flag} file absent: {(cwd / value).resolve()}")
    return problems


def parse_launch(text: str) -> dict[str, str]:
    record: dict[str, str] = {}
    for line in text.lstrip("﻿").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.isidentifier():
            record[key] = value
    return record


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def process_creation_utc(pid: int) -> datetime | None:
    """Creation time of a live process, or None when it is not running."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            if exited.dwLowDateTime or exited.dwHighDateTime:
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return datetime.fromtimestamp((ticks - 116444736000000000) / 1e7, timezone.utc)
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        boot = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text().splitlines()
            if line.startswith("btime")
        )
        ticks = int(stat[19]) / os.sysconf("SC_CLK_TCK")
        return datetime.fromtimestamp(boot + ticks, timezone.utc)
    except (OSError, IndexError, ValueError, StopIteration):
        return None


def owner_is_alive(launch_file: Path) -> bool:
    """True when launch.txt names a live process with the recorded creation time."""
    if not launch_file.is_file():
        return False
    record = parse_launch(launch_file.read_text(encoding="utf-8"))
    try:
        pid, created = int(record["pid"]), _utc(record["creation"])
    except (KeyError, ValueError):
        return False
    actual = process_creation_utc(pid)
    return (
        actual is not None
        and abs((actual - created).total_seconds()) < CREATION_TOLERANCE_SECONDS
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--require", action="append", default=[], metavar="PATH=SHA256")
    parser.add_argument("--note", default="")
    parser.add_argument("--dry-run", action="store_true", help="run preflight only")
    parser.add_argument("sprt_args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    sprt_args = (
        options.sprt_args[1:] if options.sprt_args[:1] == ["--"] else options.sprt_args
    )
    cwd = options.cwd.resolve()
    run_dir = (cwd / options.run_dir).resolve()

    problems = preflight(sprt_args, cwd, options.require)
    if owner_is_alive(run_dir / "launch.txt"):
        problems.append(f"a live match already owns {run_dir}")
    if problems:
        for problem in problems:
            print(f"PREFLIGHT FAIL: {problem}", file=sys.stderr)
        return 2
    print("PREFLIGHT OK")
    if options.dry_run:
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    for name in ("stdout.log", "stderr.log", "launch.txt"):
        old = run_dir / name
        if old.exists():
            old.rename(run_dir / f"{name}.{stamp}.old")
    command = [sys.executable, "-B", "-m", "makhos", "sprt", *sprt_args]
    flags = BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
    with (run_dir / "stdout.log").open("wb") as out, (run_dir / "stderr.log").open(
        "wb"
    ) as err:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )
    created = process_creation_utc(process.pid) or datetime.now(timezone.utc)
    lines = [
        f"launch_utc={datetime.now(timezone.utc).isoformat()}",
        f"pid={process.pid}",
        f"creation={created.isoformat()}",
        f"cwd={cwd}",
    ]
    if options.note:
        lines.append(f"note={options.note}")
    lines.append("command=" + " ".join(command))
    (run_dir / "launch.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"LAUNCHED pid={process.pid} run_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
