"""Bounded C4 transition acceptance on an idle host; never launches an arena.

Default requires real TB4-6. --tb3-only is a clearly labelled Linux diagnostic
of missing-ranked fallback, not evidence for the human game's DRAW result.
"""
from collections import Counter
from contextlib import ExitStack
from dataclasses import replace
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from makhos.compact_tb3 import CompactTablebase
from makhos.core import apply_move, legal_moves, parse_position
from makhos.exact import Outcome
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import ParallelNativeEndgameSearch
from makhos.search import Engine, Mode, SearchLimits, WDLBound
from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease

MAGNUM = "B:BM23,26:BK15:RM13,14,19,21,27"
NINE = "B:BK6,13,14:RK4,16,17,18,19,21"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def observed_rss(process):
    # Use this process's status on Linux. Some container PID views make
    # psutil's /proc/<pid>/statm disagree with /proc/self/status.
    if sys.platform.startswith("linux"):
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
        return None
    return process.memory_info().rss


def human_prefix():
    """Reconstruct clocks/counts from legal moves, not board-only snapshots."""
    path = ROOT / "benchmarks/game_reviews/e26872d254ea0041/game.json"
    game = json.loads(path.read_text(encoding="utf-8"))
    state = replace(parse_position(game["start_position"]),
                    reversible_plies=game["start_reversible_plies"])
    history = Counter({state.position_key: 1})
    target = parse_position(MAGNUM).position_key
    for notation in game["position_history"][1:]:
        expected = parse_position(notation)
        children = [apply_move(state, m) for m in legal_moves(state)]
        state = next(c for c in children if c.position_key == expected.position_key)
        history[state.position_key] += 1
        if state.position_key == target:
            return state, history, sha(path)
    raise ValueError("human-game transition prefix not found")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    suffix = ".dll" if os.name == "nt" else ".so"
    parser.add_argument("--library", type=Path, default=ROOT / f"build/native_endgame_c4/makhos_endgame_search_nnue{suffix}")
    parser.add_argument("--model", type=Path, default=ROOT / "build/nnue_quantized_v1/model_a.mknnue")
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 12])
    parser.add_argument("--time-ms", type=int, nargs="+", default=[1000, 2000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tb3-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or any(t < 1 or t > 12 for t in args.threads) or any(t < 1 for t in args.time_ms):
        parser.error("positive repeats/time and threads in 1..12 required")
    output = args.output.resolve()
    # Evidence cannot overwrite checkpoints, existing results, or source files.
    allowed = (ROOT / "build/endgame_transition_acceptance").resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        parser.error("use a NEW output directory below build/endgame_transition_acceptance/")
    ranked = () if args.tb3_only else tuple(ROOT / f"build/tb{n}_np80.compact.bin" for n in (4, 5, 6))
    for path in (args.library, args.model, *ranked):
        if not path.is_file():
            parser.error(f"required artifact missing: {path}")
    state, history, game_sha = human_prefix()
    cases = (("human_ply51", state, history),
             ("nine_to_six", parse_position(NINE), Counter()))
    invariant_paths = [ROOT / p for p in ("RULESET.json", "makhos/core.py", "build/makhos_native_accepted.dll")]
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in invariant_paths}
    rows, setup = [], []
    process = psutil.Process()
    with ExclusiveSuiteLease(ROOT) as lease, ExitStack() as stack:
        output.mkdir(parents=True)
        started = time.perf_counter()
        tb3 = stack.enter_context(CompactTablebase())
        tb = stack.enter_context(NativeEndgameTablebase(tb3, library=args.library, ranked_paths=ranked))
        tb_setup_ms = (time.perf_counter() - started) * 1000
        # Full mapped artifact identity scans occur outside search time budgets.
        tb_sha = {str(n): tb.mapped_sha256(n) for n in (4, 5, 6)} if ranked else {}
        for threads in args.threads:
            started = time.perf_counter()
            with ParallelNativeEndgameSearch(tb, threads=threads, nnue_model=args.model) as native:
                setup.append({"threads": threads, "session_setup_ms": (time.perf_counter() - started) * 1000})
                engine = Engine(native_endgame_search=native, native_endgame_enabled=True,
                                native_tablebase=tb3, exact_piece_limit=0)
                for name, root, counts in cases:
                    for mode in Mode:
                        for budget in args.time_ms:
                            for repeat in range(args.repeats):
                                lease.checkpoint("before transition search")
                                saved = counts.copy()
                                started = time.perf_counter()
                                result = engine.search(root, SearchLimits(depth=64, time_ms=budget), mode=mode, history=counts)
                                wall = (time.perf_counter() - started) * 1000
                                assert counts == saved
                                assert engine.last_search_backend == "native-endgame", engine.last_native_error
                                assert {c.move for c in result.candidates} == set(legal_moves(root))
                                if ranked and name == "human_ply51":
                                    draw = next(c for c in result.candidates if c.move.notation == "15x24x31")
                                    assert (draw.score, draw.bound) == (0, WDLBound.exact(Outcome.DRAW))
                                row = dict(case=name, threads=threads, mode=mode.value, budget_ms=budget,
                                           repeat=repeat, wall_ms=wall, overshoot_ms=max(0, wall-budget),
                                           backend=engine.last_search_backend, depth=result.depth, nodes=result.nodes,
                                           tb_hits=result.tablebase_hits, move=result.move.notation,
                                           score=result.score, bound=[int(result.bound.lower), int(result.bound.upper)],
                                           observed_rss_bytes=observed_rss(process),
                                           pv=[m.notation for m in result.pv],
                                           roots=[dict(move=c.move.notation, score=c.score,
                                                       bound=[int(c.bound.lower), int(c.bound.upper)],
                                                       pv=[m.notation for m in c.pv]) for c in result.candidates])
                                rows.append(row)
                                print(f"{name} {threads}T {mode.value} {budget}ms repeat={repeat}: {wall:.1f}ms depth={result.depth}", flush=True)
        assert before == {p.relative_to(ROOT).as_posix(): sha(p) for p in invariant_paths}
        overshoots = sorted(r["overshoot_ms"] for r in rows)
        sources = ("makhos/endgame_routing.py", "makhos/native_endgame_search.py", "makhos/server.py",
                   "makhos/search.py", "native/makhos_endgame_search.c", "native/makhos_endgame_search_nnue.c",
                   "native/makhos_endgame_tb.c", "benchmarks/endgame_transition.py", "tests/test_endgame_transition.py")
        report = dict(format="thai-makhos-endgame-transition-runtime-v1",
                      status="DIAGNOSTIC_TB3_ONLY" if args.tb3_only else "PASS_ROUTING_PROOF",
                      strength_evidence=False, gui_http_measured=False, platform=platform.platform(),
                      git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      source_sha256={p: sha(ROOT / p) for p in sources},
                      library=str(args.library.resolve()), library_sha256=sha(args.library),
                      model_sha256=sha(args.model), tb_sha256=tb_sha, game_sha256=game_sha,
                      invariant_sha256=before, tb_setup_ms=tb_setup_ms, session_setup=setup,
                      observations=len(rows), overshoot_mean_ms=statistics.mean(overshoots),
                      overshoot_p95_ms=overshoots[math.ceil(.95*len(overshoots))-1],
                      overshoot_max_ms=max(overshoots),
                      rss_source="/proc/self/status:VmRSS" if sys.platform.startswith("linux") else "psutil:memory_info.rss",
                      max_observed_rss_bytes=max((r["observed_rss_bytes"] for r in rows
                                                 if r["observed_rss_bytes"] is not None), default=None), rows=rows)
        (output / "runtime.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {output / 'runtime.json'}", flush=True)


if __name__ == "__main__":
    main()
