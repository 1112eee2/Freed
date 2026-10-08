"""Build a development NNUE search DLL bound to a pilot model identity.

Uses the search-candidate flags of tools/build/build_orchestrator.ps1 with the
strict TT key, builds twice and requires byte-identical output.  Without
--identity it builds the default v1-bound strict-key DLL, which must match the
strict control 8b82fef8 used by the current screens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CLANG = r"C:\Program Files\LLVM\bin\clang.exe"
FLAGS = [
    "-O3", "-march=x86-64", "-std=c17", "-Wall", "-Wextra", "-Werror",
    "-Wno-unused-function", "-shared", "-Wl,/Brepro",
    "-DMAKHOS_STRICT_SEARCH_POSITION_KEY=1",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    flags = list(FLAGS)
    if args.identity:
        header = args.identity.resolve().as_posix()
        flags.append(f'-DMAKHOS_NNUE_MODEL_IDENTITY_HEADER="{header}"')
    source = ROOT / "native" / "makhos_native_nnue.c"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    digests = []
    targets = []
    for suffix in ("repro_a", "repro_b"):
        target = args.output.parent / suffix / args.output.name
        target.parent.mkdir(exist_ok=True)
        process = subprocess.run(
            [CLANG, *flags, str(source), "-o", str(target)],
            capture_output=True, text=True,
        )
        if process.returncode:
            raise SystemExit(process.stderr)
        digests.append(hashlib.sha256(target.read_bytes()).hexdigest())
        targets.append(target)
    if digests[0] != digests[1]:
        raise SystemExit("builds are not byte-identical")
    args.output.write_bytes(targets[0].read_bytes())
    manifest = {
        "dll": str(args.output),
        "sha256": digests[0],
        "flags": flags,
        "source_sha256": {
            name: hashlib.sha256((ROOT / "native" / name).read_bytes()).hexdigest()
            for name in ("makhos_native.c", "makhos_native_nnue.c")
        },
        "identity": None if not args.identity else {
            "path": str(args.identity),
            "sha256": hashlib.sha256(args.identity.read_bytes()).hexdigest(),
        },
        "reproducible_builds": 2,
    }
    args.output.with_suffix(".build.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"sha256": digests[0], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
