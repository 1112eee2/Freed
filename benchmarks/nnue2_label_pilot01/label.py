"""Label pilot rows with one native search per position (NNUE2_LABEL_PILOT_01).

Each position gets a cleared search context, one thread, project rules and a
single-entry history.  Output is append-only JSON lines keyed by
canonical_position_id, so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import ctypes
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, parse_position  # noqa: E402
from makhos.native import NativeSearch  # noqa: E402

PHASES = ("13_to_16", "9_to_12", "5_to_8")


def lower_priority(idle: bool) -> None:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x40 if idle else 0x4000)
    else:
        os.nice(19 if idle else 10)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def select(rows: list[dict], args) -> list[dict]:
    rows = [row for row in rows if row["split"] in args.splits]
    if args.sample_per_phase:
        rng = random.Random(args.seed)
        chosen = []
        for phase in PHASES:
            pool = sorted(
                (row for row in rows if row["phase_band"] == phase),
                key=lambda row: row["canonical_position_id"],
            )
            chosen.extend(rng.sample(pool, args.sample_per_phase))
        rows = chosen
    return rows


_ENGINE = None
_CONFIG = None


def _init(config: dict) -> None:
    global _ENGINE, _CONFIG
    lower_priority(config["idle"])
    _CONFIG = config
    _ENGINE = NativeSearch(
        config["library"],
        hash_power=config["hash_power"],
        persistent=True,
        nnue_model=config["model"],
    )


def _label(row: dict) -> dict:
    state = parse_position(
        row["position"], reversible_plies=row["reversible_plies"], ply=row["ply"]
    )
    out = {"canonical_position_id": row["canonical_position_id"]}
    for key, depth, time_ms in _CONFIG["searches"]:
        _ENGINE.clear()
        started = time.perf_counter()
        result = _ENGINE.search(
            state,
            depth=depth,
            time_ms=time_ms,
            no_progress_plies=DEFAULT_RULES.no_progress_plies,
            repetition_limit=DEFAULT_RULES.repetition_limit,
            history={state.position_key: 1},
        )
        out[key] = {
            "score": result.score,
            "depth": result.depth,
            "nodes": result.nodes,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "move": result.move.notation,
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=ROOT / "build/nnue2_pilot01/v1_rows.jsonl.gz")
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=["train", "validation"])
    parser.add_argument("--sample-per-phase", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--depths", type=int, nargs="*", default=[])
    parser.add_argument("--time-ms", type=int, default=0)
    parser.add_argument("--hash-power", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--idle", action="store_true", help="Idle instead of BelowNormal")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    searches = [(f"d{depth}", depth, None) for depth in args.depths]
    if args.time_ms:
        searches.append((f"t{args.time_ms}", 60, args.time_ms))
    if not searches:
        raise SystemExit("nothing to search")
    config = {
        "library": str(args.library.resolve()),
        "model": str(args.model.resolve()),
        "hash_power": args.hash_power,
        "searches": searches,
        "idle": args.idle,
    }
    rows = select(load_rows(args.rows), args)
    header = {
        "kind": "header",
        "format": "thai-makhos-nnue2-pilot-labels-v1",
        "rows_sha256": sha256(args.rows),
        "library_sha256": sha256(args.library),
        "model_sha256": sha256(args.model),
        "splits": args.splits,
        "sample_per_phase": args.sample_per_phase,
        "seed": args.seed,
        "searches": searches,
        "hash_power": args.hash_power,
        "threads": 1,
        "history": "single entry, cleared context per search",
        "selected_rows": len(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.output.exists():
        with args.output.open(encoding="utf-8") as stream:
            lines = [json.loads(line) for line in stream if line.strip()]
        if not lines or {k: v for k, v in lines[0].items()} != json.loads(json.dumps(header)):
            raise SystemExit("existing output was written with a different configuration")
        done = {line["canonical_position_id"] for line in lines[1:]}
    else:
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(header, sort_keys=True) + "\n")
    todo = [row for row in rows if row["canonical_position_id"] not in done]
    print(json.dumps({"selected": len(rows), "done": len(done), "todo": len(todo)}), flush=True)
    lower_priority(args.idle)
    started = time.perf_counter()
    with multiprocessing.Pool(args.workers, initializer=_init, initargs=(config,)) as pool, \
            args.output.open("a", encoding="utf-8", newline="\n") as stream:
        for count, labelled in enumerate(pool.imap_unordered(_label, todo, chunksize=8), 1):
            stream.write(json.dumps(labelled, sort_keys=True) + "\n")
            if count % 500 == 0:
                stream.flush()
                rate = count / (time.perf_counter() - started)
                print(f"{count}/{len(todo)} labelled, {rate:.1f}/s", flush=True)
    print(json.dumps({"labelled": len(todo), "seconds": round(time.perf_counter() - started, 1)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
