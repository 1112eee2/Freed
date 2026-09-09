import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def _sha256(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_args():
    parser = argparse.ArgumentParser(description="Isolated endgame search worker")
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--tb4-path", required=True)
    parser.add_argument("--tb3-path", default=None)
    parser.add_argument("--tb5-path", default=None)
    parser.add_argument("--tb6-path", default=None)
    parser.add_argument("--engine-type", choices=["python", "native"], default="python")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=64)
    parser.add_argument("--nnue-model", default=None)
    parser.add_argument("--rules-profile", default="project")
    return parser.parse_args()


def main():
    args = parse_args()
    repo_path = os.path.abspath(args.repo_path)
    if repo_path not in sys.path:
        sys.path.insert(0, repo_path)

    import psutil
    from collections import Counter
    from makhos.core import parse_position, DEFAULT_RULES, Rules
    from makhos.search import Engine, SearchLimits, Mode
    from makhos.ranked_tablebase import RankedTablebase
    from makhos.native_tablebase import NativeTablebase

    proc = psutil.Process(os.getpid())

    tb4 = RankedTablebase(args.tb4_path) if args.tb4_path and os.path.isfile(args.tb4_path) else None
    tb5 = RankedTablebase(args.tb5_path) if args.tb5_path and os.path.isfile(args.tb5_path) else None
    tb6 = RankedTablebase(args.tb6_path) if args.tb6_path and os.path.isfile(args.tb6_path) else None
    ranked = tuple(t for t in (tb4, tb5, tb6) if t is not None)

    tb3 = None
    if args.tb3_path and os.path.isfile(args.tb3_path):
        try:
            tb3 = NativeTablebase(args.tb3_path)
        except Exception:
            tb3 = None

    native_search = None
    if args.engine_type == "native" and args.tb3_path and os.path.isfile(args.tb3_path):
        from makhos.server import _create_native_search
        native_search = _create_native_search(
            Path(args.tb3_path),
            threads=args.threads,
            hash_mb=args.hash_mb,
            nnue_model=Path(args.nnue_model) if args.nnue_model else None,
        )

    engine = Engine(
        rules=DEFAULT_RULES,
        ranked_tablebases=ranked,
        native_tablebase=tb3,
        native_search=native_search,
    )

    ready_payload = {
        "status": "ready",
        "pid": os.getpid(),
        "repo_path": repo_path,
        "engine_type": args.engine_type,
        "threads": args.threads,
        "hash_mb": args.hash_mb,
        "search_sha256": _sha256(os.path.join(repo_path, "makhos", "search.py")),
        "core_sha256": _sha256(os.path.join(repo_path, "makhos", "core.py")),
        "tb4_loaded": tb4 is not None,
        "tb3_loaded": tb3 is not None,
    }
    sys.stdout.write(json.dumps(ready_payload) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as err:
            sys.stdout.write(json.dumps({"status": "error", "error": f"JSON parse error: {err}"}) + "\n")
            sys.stdout.flush()
            continue

        cmd = req.get("command")
        if cmd == "quit":
            break
        elif cmd == "reset":
            if hasattr(engine, "clear"):
                engine.clear()
            else:
                if hasattr(engine, "_tt") and engine._tt is not None:
                    engine._tt.clear()
                if hasattr(engine, "_move_hints"):
                    engine._move_hints.clear()
                if hasattr(engine, "_killer_moves"):
                    engine._killer_moves.clear()
                if hasattr(engine, "_history_scores"):
                    engine._history_scores.clear()
                if hasattr(engine, "native_search") and engine.native_search is not None:
                    engine.native_search.clear()
            sys.stdout.write(json.dumps({"status": "ok"}) + "\n")
            sys.stdout.flush()
        elif cmd == "search":
            try:
                pos_str = req["position"]
                clock = req.get("reversible_plies", req.get("clock", 0))
                mode_str = req.get("mode", "BEST")
                mode = Mode.WIN if mode_str == "WIN" else Mode.BEST
                time_ms = req.get("time_ms")
                depth = req.get("depth", 6)
                history_dict = req.get("history", {})

                history = Counter()
                for k, v in history_dict.items():
                    if isinstance(k, str) and (":" in k):
                        try:
                            history[parse_position(k).position_key] = v
                        except Exception:
                            history[k] = v
                    else:
                        history[k] = v

                limits = SearchLimits(depth=depth, time_ms=time_ms)
                state = parse_position(pos_str, reversible_plies=clock)

                mem_before = proc.memory_info().rss / (1024 * 1024)
                t0 = time.perf_counter()
                res = engine.search(state, limits, mode=mode, history=history)
                t1 = time.perf_counter()
                mem_after = proc.memory_info().rss / (1024 * 1024)
                elapsed_ms = (t1 - t0) * 1000.0
                resp = {
                    "status": "ok",
                    "move": res.move.notation if res.move else None,
                    "score": res.score,
                    "depth": res.depth,
                    "nodes": res.nodes,
                    "elapsed_ms": elapsed_ms,
                    "bound": [res.bound.lower.name, res.bound.upper.name] if res.bound else None,
                    "mem_rss_mb": mem_after,
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as err:
                sys.stdout.write(json.dumps({"status": "error", "error": str(err)}) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
