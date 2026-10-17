"""One-thread parity: native Lazy SMP against the ordinary persistent search.

At one thread the Lazy-SMP handle must replay the control DLL's persistent
search node for node: same move, score, depth, nodes and PV for every
position, with both handles keeping their TT across the whole sequence.

    python -B tools/verification/lazy_smp_parity.py \
        --lazy-library build/lazy_smp_01/candidate/makhos_native_nnue_candidate_v1.dll \
        --control-library build/search_int01/candidate/makhos_native_nnue_candidate_v1.dll \
        --nnue-model build/nnue_quantized_v1/model_a.mknnue --depth 9 --positions 120

Exit status 0 means every position matched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, parse_position  # noqa: E402
from makhos.native import (  # noqa: E402
    NativeLazySmpSearch,
    NativeSearch,
    hash_megabytes_for_power,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)


def corpus_positions(path: Path, limit: int):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("kind") != "sample":
                continue
            yield record["id"], parse_position(
                record["position"],
                reversible_plies=int(record.get("reversible_plies", 0)),
            )
            limit -= 1
            if limit == 0:
                return


def summary(result) -> dict[str, object]:
    return {
        "move": str(result.move),
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "pv": [str(move) for move in result.pv],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lazy-library", type=Path, required=True)
    parser.add_argument("--control-library", type=Path, required=True)
    parser.add_argument("--nnue-model", type=Path, default=None)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v5.jsonl",
    )
    parser.add_argument("--positions", type=int, default=120)
    parser.add_argument("--depth", type=int, default=9)
    parser.add_argument("--hash-mb", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    # The control handle takes a hash power; give the lazy handle the same one.
    hash_power = hash_power_for_megabytes(
        args.hash_mb,
        entry_bytes=native_tt_entry_bytes(args.lazy_library),
    )
    hash_mb = hash_megabytes_for_power(
        hash_power,
        entry_bytes=native_tt_entry_bytes(args.lazy_library),
    )
    rules = DEFAULT_RULES
    mismatches: list[dict[str, object]] = []
    compared = 0
    with NativeSearch(
        args.control_library,
        hash_power=hash_power,
        persistent=True,
        nnue_model=args.nnue_model,
    ) as control, NativeLazySmpSearch(
        args.lazy_library,
        threads=1,
        hash_mb=args.hash_mb,
        nnue_model=args.nnue_model,
    ) as lazy:
        if lazy.hash_power != hash_power:
            raise RuntimeError(
                f"hash power differs: lazy {lazy.hash_power}, control {hash_power}"
            )
        for sample_id, state in corpus_positions(args.corpus, args.positions):
            options = {
                "depth": args.depth,
                "time_ms": None,
                "no_progress_plies": rules.no_progress_plies,
                "repetition_limit": rules.repetition_limit,
            }
            expected = summary(control.search(state, **options))
            actual = summary(lazy.search(state, **options))
            compared += 1
            if actual != expected:
                mismatches.append(
                    {"id": sample_id, "control": expected, "lazy": actual}
                )

    report = {
        "format": "thai-makhos-lazy-smp-parity-v1",
        "lazy_library": str(args.lazy_library.resolve()),
        "control_library": str(args.control_library.resolve()),
        "nnue_model": None if args.nnue_model is None else str(args.nnue_model.resolve()),
        "depth": args.depth,
        "hash_power": hash_power,
        "hash_mb": hash_mb,
        "positions": compared,
        "mismatches": len(mismatches),
        "first_mismatches": mismatches[:5],
        "verdict": "PASS" if compared > 0 and not mismatches else "FAIL",
    }
    encoded = json.dumps(report, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
