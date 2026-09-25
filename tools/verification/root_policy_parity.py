"""Emit or compare fixed-depth 1T/12T root-choice fingerprints.

Run this script in separate processes for the baseline and candidate checkout.
It deliberately compares only move, score, depth and PV: throughput, node count
and elapsed time are not strength or behavior-parity evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


CASES = (
    ("opening", None),
    ("tactical12", "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17"),
    ("quiet8", "B:BM13,17,21,25:RM8,12,16,20"),
    ("wide19", "B:BK4,11,13,25:RK2,12,14,31"),
)
THREADS = (1, 12)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _signature(report: dict) -> list[dict]:
    fields = ("case", "threads", "move", "score", "depth", "pv")
    return [
        {field: row[field] for field in fields}
        for row in report["records"]
    ]


def _run(args: argparse.Namespace) -> dict:
    root = args.repo_root.resolve()
    library = args.library.resolve()
    model = args.model.resolve()
    if not library.is_file():
        raise FileNotFoundError(f"accepted DLL is missing: {library}")
    if not model.is_file():
        raise FileNotFoundError(f"accepted NNUE model is missing: {model}")

    sys.path.insert(0, str(root))
    from makhos.core import initial_state, parse_position
    from makhos.native import (
        NativeSearch,
        hash_power_for_megabytes,
        native_tt_entry_bytes,
    )
    from makhos.parallel_native import ParallelNativeSearch
    from makhos.workload_isolation import BatchWorkLease

    states = tuple(
        (
            name,
            initial_state() if position is None else parse_position(position),
        )
        for name, position in CASES
    )
    records: list[dict] = []
    with BatchWorkLease(root) as lease:
        for threads in THREADS:
            if threads == 1:
                hash_power = hash_power_for_megabytes(
                    args.hash_mb,
                    entry_bytes=native_tt_entry_bytes(library),
                )
                backend = NativeSearch(
                    library,
                    hash_power=hash_power,
                    persistent=True,
                    nnue_model=model,
                )
            else:
                backend = ParallelNativeSearch(
                    library,
                    threads=threads,
                    hash_mb=args.hash_mb,
                    nnue_model=model,
                )
            with backend:
                for name, state in states:
                    lease.checkpoint(f"{threads}T {name}")
                    backend.clear()
                    result = backend.search(
                        state,
                        depth=args.depth,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                        history={state.position_key: 1},
                    )
                    if result.depth != args.depth:
                        raise RuntimeError(
                            f"{threads}T {name} completed depth "
                            f"{result.depth}, expected {args.depth}"
                        )
                    records.append(
                        {
                            "case": name,
                            "threads": threads,
                            "move": result.move.notation,
                            "score": result.score,
                            "depth": result.depth,
                            "pv": [move.notation for move in result.pv],
                        }
                    )

    return {
        "format": "thai-makhos-root-policy-parity-v1",
        "source_commit": _source_commit(root),
        "library": str(library),
        "library_sha256": _sha256(library),
        "model": str(model),
        "model_sha256": _sha256(model),
        "depth": args.depth,
        "hash_mb": args.hash_mb,
        "threads": list(THREADS),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--library",
        type=Path,
        default=Path("build/makhos_native_accepted.dll"),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("build/nnue_quantized_v1/model_a.mknnue"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--hash-mb", type=int, default=64)
    args = parser.parse_args()
    if args.depth < 1 or args.hash_mb < 1:
        parser.error("depth and hash-mb must be positive")

    report = _run(args)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.compare is not None:
        expected = json.loads(args.compare.read_text(encoding="utf-8"))
        if expected.get("format") != report["format"]:
            raise RuntimeError("comparison report format mismatch")
        for field in ("library_sha256", "model_sha256", "depth", "hash_mb", "threads"):
            if expected.get(field) != report[field]:
                raise RuntimeError(f"comparison provenance mismatch: {field}")
        expected_signature = _signature(expected)
        actual_signature = _signature(report)
        if actual_signature != expected_signature:
            print(
                json.dumps(
                    {
                        "status": "FAIL",
                        "expected": expected_signature,
                        "actual": actual_signature,
                    },
                    indent=2,
                )
            )
            return 1
        print(json.dumps({"status": "PASS", "records": len(actual_signature)}))
    else:
        print(json.dumps({"status": "CAPTURED", "records": len(report["records"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
