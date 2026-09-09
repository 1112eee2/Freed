"""Offline, exclusively leased TB3 build. Never writes accepted DLLs or TB4+.

python -m tools.build_tb3 --output build/tb3-phase1b --compiler gcc
The output directory must be new. Copy its reviewed .tb3 to data/ for deployment.
"""

from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import zlib

from makhos.compact_tb3 import BOARD_COUNT, HEADER, MAGIC, ROOT, CompactTablebase, invariant_digest


def compact(raw: Path, target: Path, clock: int) -> dict:
    stride = (clock + 1) * 2
    if raw.stat().st_size != BOARD_COUNT * stride:
        raise ValueError("incomplete dense TB3 export")
    lookup: dict[bytes, int] = {}
    indices = array("I")
    with raw.open("rb") as stream:
        for _ in range(BOARD_COUNT):
            vector = stream.read(stride)
            indices.append(lookup.setdefault(vector, len(lookup)))
    if indices.itemsize != 4:
        raise RuntimeError("32-bit unsigned array required")
    if sys.byteorder != "little":
        indices.byteswap()
    payload = indices.tobytes() + b"".join(lookup)
    packed = zlib.compress(payload, level=9)
    header = HEADER.pack(MAGIC, 1, clock, BOARD_COUNT, len(lookup), len(payload), len(packed),
                         invariant_digest(ROOT / "RULESET.json"),
                         invariant_digest(ROOT / "makhos/core.py"), hashlib.sha256(payload).digest())
    with target.open("xb") as stream:
        stream.write(header + packed)
    # Validate the entire encoded matrix against the dense oracle output.
    # No sampling: every board/side/clock entry, including invalid slots.
    with CompactTablebase(target, no_progress_plies=clock) as tb, raw.open("rb") as stream:
        from makhos.compact_tb3 import U32
        for index in range(BOARD_COUNT):
            vector = U32.unpack_from(tb._data, index * 4)[0]
            start = tb._vector_start + vector * stride
            if tb._data[start:start + stride] != stream.read(stride):
                raise ValueError(f"TB3 round-trip mismatch at board index {index}")
        return {"artifact_sha256": tb.sha256, "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "file_bytes": tb.file_bytes, "loaded_bytes": tb.payload_bytes,
                "vectors": tb.vector_count, "board_slots": BOARD_COUNT,
                "roundtrip_clock_entries": BOARD_COUNT * (clock + 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument("--clock", type=int, default=80, choices=range(1, 201))
    parser.add_argument("--hash-power", type=int, default=26, choices=range(16, 29))
    args = parser.parse_args()
    from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease

    output = args.output.resolve()
    if output.is_relative_to(ROOT / "build/nnue_sprt_6t_vs_12t"):
        raise ValueError("frozen Experiment A directory is protected")
    with ExclusiveSuiteLease(ROOT) as lease:
        output.mkdir(parents=True, exist_ok=False)
        started = time.perf_counter()
        source_names = ("native/makhos_native.c", "native/makhos_tb3_export.c",
                        "makhos/core.py", "RULESET.json", "makhos/compact_tb3.py", "tools/build_tb3.py")
        sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_names}
        executable = output / ("makhos_tb3_export.exe" if sys.platform == "win32" else "makhos_tb3_export")
        command = [args.compiler, "-O3", "-std=c17", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-function", "-Wno-type-limits",
                   str(ROOT / "native/makhos_tb3_export.c"), "-o", str(executable)]
        subprocess.run(command, check=True)
        lease.checkpoint("before TB3 export")
        raw = output / "dense.raw"
        with (output / "export.log").open("wb") as log:
            # Own and stop this one child on interruption; never orphan a solver.
            process = subprocess.Popen([str(executable), str(raw), str(args.clock), str(args.hash_power)],
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
            try:
                while True:
                    try:
                        code = process.wait(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        lease.checkpoint("during TB3 export")
                if code:
                    raise RuntimeError(f"TB3 exporter failed ({code}); see {output / 'export.log'}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
        lease.checkpoint("before compacting TB3")
        target = output / f"tb3_np{args.clock}.tb3"
        result = compact(raw, target, args.clock)
        lease.checkpoint("after TB3 verification")
        if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha for name, sha in sources.items()):
            raise RuntimeError("source changed during TB3 build")
        result.update({"format": "thai-makhos-tb3-build-v1", "status": "ROUNDTRIP_PASS",
                       "created_at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                       "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                       "source_sha256": sources, "compiler_command": command,
                       "compiler_version": subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0],
                       "exporter_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                       "no_progress_plies": args.clock, "hash_power": args.hash_power,
                       "elapsed_sec": time.perf_counter() - started,
                       "independent_oracle_parity": "separate verification required", "strength_evidence": False})
        (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
