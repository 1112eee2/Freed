"""NNUE V2 self-play generator: games and per-ply fixed-depth labels.

Every non-forced, non-random ply is chosen by one fixed-depth native search on
a cleared context, and that search's score is the position's label (side to
move).  Random opening plies and exploration moves are drawn from a per-game
seeded RNG, so a game is a pure function of its seed and the engine identity.
Positions are written only with their legality-checked successor, using the
Python rules reference for every move that is played.

Output: one JSON line per game in a per-worker shard; a rerun skips the seeds
already present, so the run resumes after any interruption.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import (  # noqa: E402
    DEFAULT_RULES,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    terminal_status,
)
from makhos.native import NativeSearch  # noqa: E402

FORMAT = "thai-makhos-nnue2-selfplay-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lower_priority(idle: bool) -> None:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x40 if idle else 0x4000)
    else:
        os.nice(19 if idle else 10)


def game_schedule(seed: int, args) -> dict:
    rng = random.Random(seed)
    return {
        "seed": seed,
        "opening_plies": rng.randint(args.opening_min, args.opening_max),
        "exploration_rate": round(rng.uniform(args.explore_min, args.explore_max), 4),
    }


def play_game(engine: NativeSearch, schedule: dict, args) -> dict:
    rng = random.Random(schedule["seed"] * 7919 + 1)
    state = initial_state()
    history = Counter({state.position_key: 1})
    plies = []
    status = terminal_status(state, repetition_count=1, rules=DEFAULT_RULES)
    for ply in range(1, args.max_plies + 1):
        status = terminal_status(
            state, repetition_count=history[state.position_key], rules=DEFAULT_RULES
        )
        if status.terminal:
            break
        legal = legal_moves(state)
        record = {
            "ply": ply,
            "position": format_position(state),
            "reversible_plies": state.reversible_plies,
            "repetition": history[state.position_key],
            "legal": len(legal),
            "capture": legal[0].is_capture,
        }
        random_opening = ply <= schedule["opening_plies"]
        explore = (
            not random_opening and len(legal) > 1
            and rng.random() < schedule["exploration_rate"]
        )
        if random_opening or explore:
            move = rng.choice(legal)
            record["actor"] = "random"
        elif len(legal) == 1:
            move = legal[0]
            record["actor"] = "forced"
        else:
            engine.clear()
            result = engine.search(
                state,
                depth=args.depth,
                time_ms=None,
                no_progress_plies=DEFAULT_RULES.no_progress_plies,
                repetition_limit=DEFAULT_RULES.repetition_limit,
                history=dict(history),
            )
            move = result.move
            if move not in legal:
                raise RuntimeError(f"native move {move.notation} is illegal at ply {ply}")
            record.update(
                actor="engine", score=result.score, depth=result.depth, nodes=result.nodes,
            )
        record["move"] = move.notation
        plies.append(record)
        state = apply_move(state, move)
        history[state.position_key] += 1
    else:
        status = terminal_status(
            state, repetition_count=history[state.position_key], rules=DEFAULT_RULES
        )
    winner = getattr(status, "winner", None)
    return {
        "kind": "game",
        "seed": schedule["seed"],
        "schedule": schedule,
        "terminal": bool(status.terminal),
        "reason": getattr(status, "reason", None) if status.terminal else "max_plies",
        "winner": None if winner is None else int(winner),
        "plies": plies,
        "final_position": format_position(state),
    }


_ENGINE = None
_ARGS = None


def _init(args) -> None:
    global _ENGINE, _ARGS
    lower_priority(args.idle)
    _ARGS = args
    _ENGINE = NativeSearch(
        str(args.library), hash_power=args.hash_power, persistent=True,
        nnue_model=str(args.model),
    )


def _run(seed: int) -> str:
    started = time.perf_counter()
    game = play_game(_ENGINE, game_schedule(seed, _ARGS), _ARGS)
    game["seconds"] = round(time.perf_counter() - started, 2)
    return json.dumps(game, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--hash-power", type=int, default=20)
    parser.add_argument("--opening-min", type=int, default=2)
    parser.add_argument("--opening-max", type=int, default=12)
    parser.add_argument("--explore-min", type=float, default=0.05)
    parser.add_argument("--explore-max", type=float, default=0.20)
    parser.add_argument("--max-plies", type=int, default=300)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--idle", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    header = {
        "kind": "header",
        "format": FORMAT,
        "library_sha256": sha256(args.library),
        "model_sha256": sha256(args.model),
        "generator_sha256": sha256(Path(__file__)),
        "seed_start": args.seed_start,
        "games": args.games,
        "depth": args.depth,
        "hash_power": args.hash_power,
        "threads": 1,
        "opening_plies": [args.opening_min, args.opening_max],
        "exploration_rate": [args.explore_min, args.explore_max],
        "max_plies": args.max_plies,
        "rules": "project",
        "label": "fixed-depth score, side to move, cleared context per search, game history",
    }
    done = set()
    if args.output.exists():
        with args.output.open(encoding="utf-8") as stream:
            lines = [json.loads(line) for line in stream if line.strip()]
        if not lines or lines[0] != header:
            raise SystemExit("existing output was written with a different configuration")
        done = {line["seed"] for line in lines[1:]}
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(header, sort_keys=True) + "\n")
    seeds = [
        seed for seed in range(args.seed_start, args.seed_start + args.games)
        if seed not in done
    ]
    print(json.dumps({"games": args.games, "done": len(done), "todo": len(seeds)}), flush=True)
    lower_priority(args.idle)
    started = time.perf_counter()
    labels = 0
    with multiprocessing.Pool(args.workers, initializer=_init, initargs=(args,)) as pool, \
            args.output.open("a", encoding="utf-8", newline="\n") as stream:
        for count, line in enumerate(pool.imap_unordered(_run, seeds), 1):
            stream.write(line + "\n")
            stream.flush()
            labels += line.count('"actor":"engine"')
            if count % 25 == 0:
                elapsed = time.perf_counter() - started
                print(f"{count}/{len(seeds)} games, {labels / elapsed * 3600:.0f} engine labels/hour", flush=True)
    print(json.dumps({"games_written": len(seeds), "seconds": round(time.perf_counter() - started, 1)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
