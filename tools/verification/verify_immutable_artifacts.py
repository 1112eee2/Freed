"""Verify the files listed in config/immutable_artifacts.json against their SHA-256.

Exit code 0 when every checked file matches, 1 otherwise. Entries whose file
is absent are failures unless ``--skip-untracked-missing`` is given, which is
for fresh checkouts that do not carry the untracked build/ tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "config" / "immutable_artifacts.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root: Path, manifest: Path, *, skip_untracked_missing: bool = False) -> list[str]:
    """Return one problem string per artifact that is absent or differs."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("format") != "thai-makhos-immutable-artifacts-v1":
        return [f"unsupported manifest format: {data.get('format')!r}"]
    problems = []
    for entry in data["artifacts"]:
        path = root / entry["path"]
        if not path.is_file():
            if skip_untracked_missing and not entry.get("tracked", True):
                continue
            problems.append(f"absent: {entry['path']}")
        elif sha256_file(path).lower() != entry["sha256"].lower():
            problems.append(f"hash differs: {entry['path']}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_MANIFEST.parents[1])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--skip-untracked-missing", action="store_true")
    options = parser.parse_args(argv)
    problems = verify(
        options.root.resolve(),
        options.manifest,
        skip_untracked_missing=options.skip_untracked_missing,
    )
    for problem in problems:
        print(f"IMMUTABLE FAIL: {problem}", file=sys.stderr)
    if not problems:
        print("IMMUTABLE OK")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
