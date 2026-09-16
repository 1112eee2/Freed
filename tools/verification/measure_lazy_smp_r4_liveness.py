#!/usr/bin/env python3
"""Measure the liveness and payload-consistency behaviour of a frozen race probe.

The r4 TSan run aborted on the frozen assertion `assert(atomic_load(&accepted) > 0)`
in most probe runs while one run passed with accepted=961. This tool quantifies that
without changing a single byte of the frozen handoff: it re-verifies the snapshot,
compiles the probe exactly as the handoff README specifies, and runs it many times,
recording the exit code, the aborting assertion and the `accepted` count each run
reports.

It accepts any handoff directory that has a manifest.json with a probe_sha256 and a
verify_snapshot.py, so the same measurement can be run against the frozen r3 probe
(C11 threads) as a differential control for the r4 pthread revision.

This is a *measurement of an existing artifact*, not gate evidence and not a
re-run of the gate. It never weakens an assertion and never edits a handoff.

Usage::

    python3 measure_lazy_smp_r4_liveness.py --repeats 20 --output build/r4-liveness
    python3 measure_lazy_smp_r4_liveness.py --handoff handoffs/lazy-smp-g2-r3 \\
        --repeats 20 --output build/r3-liveness
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ACCEPTED_RE = re.compile(r"accepted=(\d+)")
ASSERTION_RE = re.compile(r"Assertion `([^']*)' failed")
VARIANTS = (
    ("clang_tsan", "clang", "-fsanitize=thread "),
    ("gcc_tsan", "gcc", "-fsanitize=thread "),
    ("clang_plain", "clang", ""),
)
# Linux-only by design; the override exists so the script's plumbing can be exercised
# on a Windows developer machine (TSan builds there are expected to fail, not to run).
SHELL_BIN = os.environ.get("MAKHOS_MEASURE_SHELL", "/bin/bash")


def resolve_binary(binary: Path) -> Path:
    """Honour a platform suffix the compiler may have added (e.g. .exe)."""
    if binary.exists():
        return binary
    for suffix in (".exe", ".bin"):
        candidate = binary.with_name(binary.name + suffix)
        if candidate.exists():
            return candidate
    return binary


def sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def run(command: str, cwd: Path, timeout: int = 180) -> dict:
    started = time.monotonic()
    process = subprocess.run([SHELL_BIN, "-c", command], cwd=str(cwd),
                             capture_output=True, timeout=timeout, check=False)
    return {
        "command": command,
        "exit_code": process.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": process.stdout.decode(errors="replace"),
        "stderr": process.stderr.decode(errors="replace"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, default=Path("handoffs/lazy-smp-g2-r4"))
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--cc-clang", default="clang",
                        help="clang executable; override for a non-standard toolchain")
    parser.add_argument("--cc-gcc", default="gcc",
                        help="gcc executable; override for a non-standard toolchain")
    args = parser.parse_args()
    compilers = {"clang": args.cc_clang, "gcc": args.cc_gcc}

    handoff = args.handoff.resolve()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to reuse {output}")
    output.mkdir(parents=True)

    manifest = json.loads((handoff / "manifest.json").read_text(encoding="utf-8"))
    probe_sha = sha256_of(handoff / "probe.c")
    verification = run("python3 verify_snapshot.py", handoff)
    if verification["exit_code"] != 0:
        raise SystemExit("snapshot verification failed; refusing to measure")
    if probe_sha != manifest["probe_sha256"]:
        raise SystemExit("probe hash does not match the frozen manifest")

    summary = {
        "measured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": "measurement of the frozen r4 probe; NOT gate evidence, NOT a re-run of the gate",
        "handoff_probe_sha256": probe_sha,
        "snapshot_verification": verification["stdout"].strip(),
        "repeats": args.repeats,
        "environment": run(
            "uname -a\nnproc\ngetconf _NPROCESSORS_ONLN\n"
            "clang --version | head -1\ngcc --version | head -1\n"
            "python3 --version\ndpkg-query -W libc6 | head -1",
            handoff,
        )["stdout"],
        "variants": {},
    }

    for name, compiler_key, flags in VARIANTS:
        compiler = shlex.quote(compilers[compiler_key])
        binary = output / name
        compile_result = run(
            f"{compiler} -std=c17 -O1 -g {flags}-pthread probe.c -o {binary.as_posix()}",
            handoff)
        entry = {"compiler": compilers[compiler_key],
                 "compile": {k: compile_result[k] for k in
                             ("command", "exit_code", "elapsed_seconds", "stderr")},
                 "runs": []}
        summary["variants"][name] = entry
        if compile_result["exit_code"] != 0:
            entry["status"] = "NOT_RUN"
            print(f"{name}: NOT_RUN (compile failed)", flush=True)
            continue
        entry["binary_sha256"] = sha256_of(resolve_binary(binary))
        for index in range(args.repeats):
            prefix = "TSAN_OPTIONS=halt_on_error=1 " if flags else ""
            result = run(f"{prefix}timeout {args.timeout}s {resolve_binary(binary).as_posix()}",
                         handoff, timeout=args.timeout + 30)
            match = ACCEPTED_RE.search(result["stdout"])
            assertion = ASSERTION_RE.search(result["stderr"])
            entry["runs"].append({
                "index": index + 1,
                "exit_code": result["exit_code"],
                "elapsed_seconds": result["elapsed_seconds"],
                "accepted": int(match.group(1)) if match else None,
                "aborting_assertion": assertion.group(1) if assertion else None,
                "liveness_assertion": bool(assertion and "accepted) > 0" in assertion.group(1)),
                "stdout": result["stdout"],
                "stderr_tail": result["stderr"][-400:],
            })
        passes = [r for r in entry["runs"] if r["exit_code"] == 0]
        accepted = [r["accepted"] for r in passes if r["accepted"] is not None]
        entry["status"] = "MEASURED"
        entry["pass_count"] = len(passes)
        entry["pass_rate"] = round(len(passes) / max(1, len(entry["runs"])), 4)
        entry["accepted_values"] = accepted
        entry["accepted_min"] = min(accepted) if accepted else None
        entry["accepted_max"] = max(accepted) if accepted else None
        entry["liveness_assertion_failures"] = sum(
            1 for r in entry["runs"] if r["liveness_assertion"])
        kinds: dict[str, int] = {}
        for r in entry["runs"]:
            if r["exit_code"] == 0:
                key = "pass"
            elif r["aborting_assertion"]:
                key = "assert: " + r["aborting_assertion"]
            else:
                key = f"other exit {r['exit_code']}"
            kinds[key] = kinds.get(key, 0) + 1
        entry["outcome_breakdown"] = kinds
        print(f"{name}: {len(passes)}/{len(entry['runs'])} passed, accepted={accepted}, "
              f"breakdown={kinds}", flush=True)

    summary["conclusion"] = (
        "A pass rate strictly between 0 and 1 with a wide accepted spread indicates a "
        "timing-dependent liveness property rather than a deterministic protocol failure. "
        "A rate of exactly 0 across every variant would point at something systematic and "
        "would need a different explanation."
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                         encoding="utf-8")
    print("wrote", output / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
