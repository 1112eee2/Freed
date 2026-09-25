"""Measure how the NNUE search scores exact tablebase results at 4-6 pieces.

Measurement only. For every position of ``corpora/exact_wdl_eval_v1.jsonl``
(exact WIN/DRAW/LOSS labels for the side to move), record the static NNUE
score and a fresh fixed-depth native search score, then bucket each score as
positive (> +margin), near zero, or negative (< -margin). A drawn position
scored beyond the margin is one the main search would misjudge if it reached
it as a leaf; the main native search does not probe tablebases today.

Writes a new JSON report; nothing is overwritten.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, parse_position  # noqa: E402
from makhos.native import NativeSearch  # noqa: E402

CORPUS = ROOT / "corpora" / "exact_wdl_eval_v1.jsonl"
MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
OUTCOMES = ("win", "draw", "loss")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bucket(score: int, margin: int) -> str:
    if score > margin:
        return "positive"
    if score < -margin:
        return "negative"
    return "near_zero"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--margin", type=int, default=50)
    parser.add_argument("--hash-power", type=int, default=18)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")

    with CORPUS.open(encoding="utf-8") as stream:
        stream.readline()  # metadata header
        rows = [json.loads(line) for line in stream]
    counts: dict = collections.defaultdict(collections.Counter)
    started = time.time()
    with NativeSearch(
        args.library, hash_power=args.hash_power, persistent=True, nnue_model=MODEL
    ) as engine:
        if not engine.nnue_enabled:
            raise SystemExit("the library must be an NNUE search build")
        for row in rows:
            state = parse_position(row["position"], reversible_plies=row["reversible_plies"])
            engine.clear()
            search = engine.search(
                state,
                depth=args.depth,
                time_ms=None,
                no_progress_plies=DEFAULT_RULES.no_progress_plies,
                repetition_limit=DEFAULT_RULES.repetition_limit,
                history={state.position_key: 1},
            )
            if search.depth != args.depth:
                raise RuntimeError(f"incomplete search on {row['id']}")
            for label, score in (("static", engine.evaluate(state)), ("search", search.score)):
                key = f"{label}/{row['piece_count']}/{row['outcome']}"
                counts[key][bucket(score, args.margin)] += 1

    table = {
        label: {
            str(pieces): {
                outcome: dict(counts[f"{label}/{pieces}/{outcome}"])
                for outcome in OUTCOMES
            }
            for pieces in (4, 5, 6)
        }
        for label in ("static", "search")
    }
    summary = {}
    for label in ("static", "search"):
        draws = collections.Counter()
        gross = decisive = 0
        for pieces in (4, 5, 6):
            draws.update(counts[f"{label}/{pieces}/draw"])
            gross += counts[f"{label}/{pieces}/win"]["negative"]
            gross += counts[f"{label}/{pieces}/loss"]["positive"]
            decisive += sum(counts[f"{label}/{pieces}/win"].values())
            decisive += sum(counts[f"{label}/{pieces}/loss"].values())
        total_draws = sum(draws.values())
        summary[label] = {
            "draws_scored_decisive": total_draws - draws["near_zero"],
            "draws": total_draws,
            "decisive_sign_errors": gross,
            "decisive": decisive,
        }
    report = {
        "format": "thai-makhos-tb-frontier-draw-misjudgment-v1",
        "config": {"depth": args.depth, "margin": args.margin, "hash_power": args.hash_power},
        "identity": {
            "library": str(args.library.resolve()),
            "library_sha256": sha256(args.library),
            "model_sha256": sha256(MODEL),
            "corpus_sha256": sha256(CORPUS),
            "platform": platform.platform(),
        },
        "elapsed_s": round(time.time() - started, 1),
        "positions": len(rows),
        "summary": summary,
        "table": table,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=1, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
