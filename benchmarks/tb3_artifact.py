"""Verify artifact against a separately loaded legacy oracle and time real loads.

python -m benchmarks.tb3_artifact --native-library build/makhos_native_accepted.dll \
    --output build/tb3-local-verification
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import time

from makhos.compact_tb3 import CompactTablebase, DEFAULT_ARTIFACT, ROOT
from makhos.core import State, Rules, parse_position
from makhos.native_tablebase import NativeTablebase
from makhos.search import Engine, Mode, SearchLimits
from benchmarks.endgame_latency import percentiles


def positions(seed: int, boards: int):
    rng = random.Random(seed)
    for index in range(boards):
        while True:
            board = [0] * 32
            for square in rng.sample(range(32), 1 + index % 3):
                board[square] = rng.randint(1, 4)
            try:
                yield State(tuple(board), 1 + (index // 3) % 2)
                break
            except ValueError:
                pass


def signature(result):
    return {"move": result.move.notation if result.move else None,
            "score": result.score, "pv": [move.notation for move in result.pv],
            "depth": result.depth, "nodes": result.nodes,
            "bound": [int(result.bound.lower), int(result.bound.upper)],
            "tablebase_hits": result.tablebase_hits}


def run(args):
    from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease
    with ExclusiveSuiteLease(ROOT) as lease:
        args.output.mkdir(parents=True, exist_ok=False)
        load_times = []
        for _ in range(args.loads):
            started = time.perf_counter()
            with CompactTablebase(args.artifact) as tb:
                load_times.append((time.perf_counter() - started) * 1000)
                digest = tb.sha256
                payload_bytes = tb.payload_bytes
        started = time.perf_counter()
        legacy = NativeTablebase(args.native_library)
        legacy_init_ms = (time.perf_counter() - started) * 1000
        probes = 0
        signatures = []
        try:
            with CompactTablebase(args.artifact) as compact:
                for index, state in enumerate(positions(args.seed, args.boards)):
                    lease.checkpoint(f"before board {index}")
                    for clock in range(81):
                        state = replace(state, reversible_plies=clock)
                        old, new = legacy.probe(state), compact.probe(state)
                        if old != new:
                            raise AssertionError(f"probe mismatch: {state}: {old} != {new}")
                        probes += 1
                # Same source, exact history, mode and fixed depth. Only oracle
                # representation changes; nodes/bounds/PV must remain identical.
                for position in ("B:BK6,15:RK28", "B:BM18:RM14,1", "B:BK1:RK32",
                                 "B:BK1,5,6:RK28"):
                    for clock in (0, 78, 79):
                        state = parse_position(position, reversible_plies=clock)
                        for repetition in (None, 3):
                            rules = Rules(repetition_limit=repetition)
                            for mode in Mode:
                                engines = [Engine(rules=rules, native_tablebase=oracle, exact_piece_limit=0)
                                           for oracle in (legacy, compact)]
                                for history_count in (1, 2, 1):
                                    history = Counter({state.position_key: history_count})
                                    results = [signature(engine.search(state, SearchLimits(depth=3),
                                               mode=mode, history=history)) for engine in engines]
                                    if results[0] != results[1]:
                                        raise AssertionError(f"fixed search mismatch: {position}: {results}")
                                    signatures.append({"position": position, "clock": clock, "mode": mode.value,
                                                       "repetition_limit": repetition, "history_count": history_count,
                                                       "result": results[0]})
        finally:
            legacy.close()
        result = {"format": "thai-makhos-tb3-verification-v1", "status": "PARITY_PASS",
                  "platform": platform.platform(), "seed": args.seed, "boards": args.boards,
                  "probe_comparisons": probes, "fixed_search_comparisons": len(signatures),
                  "load_ms": percentiles(load_times), "load_samples_ms": load_times,
                  "legacy_init_ms": legacy_init_ms, "payload_bytes": payload_bytes,
                  "artifact_sha256": digest,
                  "native_library_sha256": hashlib.sha256(args.native_library.read_bytes()).hexdigest(),
                  "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                      "makhos/compact_tb3.py", "makhos/search.py", "makhos/distance.py", "makhos/core.py",
                      "RULESET.json", "benchmarks/tb3_artifact.py")},
                  "cold_os_cache": "uncontrolled; first load is process-cold, remaining loads are repeated",
                  "load_under_50ms": max(load_times) < 50,
                  "strength_evidence": False, "fixed_search_results": signatures}
        (args.output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "fixed_search_results"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-library", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boards", type=int, default=600)
    parser.add_argument("--loads", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260909)
    args = parser.parse_args()
    if args.boards < 1 or args.loads < 1:
        parser.error("boards and loads must be positive")
    run(args)
