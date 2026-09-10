"""Opt-in C1 parity against real compact TB4/5/6, with immutable map hashes.

Run while GUI and arena are idle. This samples every material signature; it is
not exhaustive verification of all boards or a strength/promotion gate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import time

from makhos.native_endgame import DEFAULT_LIBRARY, NativeEndgameTablebase
from makhos.provenance import DEFAULT_MANIFEST_PATH
from makhos.ranked_tablebase import RankedTablebase
from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("RULESET.json", "makhos/core.py", "makhos/native_endgame.py",
           "makhos/ranked_tablebase.py", "native/makhos_endgame_tb.c",
           "native/makhos_endgame_tb.h", "benchmarks/native_endgame_ranked.py")


def run(args):
    output = args.output.resolve()
    if output.is_relative_to(ROOT / "build/nnue_sprt_6t_vs_12t"):
        raise ValueError("output cannot be inside the frozen Experiment A directory")
    with ExclusiveSuiteLease(ROOT) as lease, ExitStack() as stack:
        output.mkdir(parents=True, exist_ok=False)
        report = dict(format="thai-makhos-c1-ranked-parity-v1", status="RUNNING",
                      created_at=datetime.now(timezone.utc).isoformat(),
                      source_commit=subprocess.check_output(
                          ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      platform=platform.platform(), seed=args.seed,
                      library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest(),
                      source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES},
                      artifacts=[], signature_comparisons=[], total_probes=0,
                      complete_139_signatures=False, strength_evidence=False,
                      full_file_hash_scan="explicit; performed after parity and outside probe timing")
        try:
            started = time.perf_counter()
            native = stack.enter_context(NativeEndgameTablebase(
                library=args.library, ranked_paths=args.tablebase,
                no_progress_plies=args.clock, verify_checksum=args.verify_checksum,
            ))
            report["prepare_ms"] = (time.perf_counter() - started) * 1000
            report["prepare_includes_checksum_scan"] = args.verify_checksum
            report["os_cache"] = "uncontrolled; do not interpret as disk-cold latency"
            rng = random.Random(args.seed)
            seen = set()
            for path in args.tablebase:
                reference = stack.enter_context(RankedTablebase(path))
                n = reference.piece_count
                seen.add(n)
                for counts in reference.material_signatures:
                    lease.checkpoint(f"before TB{n} signature {counts}")
                    boards = reference.board_count(counts)
                    ranks = sorted({0, 1, boards // 2, boards - 2, boards - 1,
                                    *rng.sample(range(2, boards - 2), min(args.ranks - 5, boards - 4))})
                    probes = 0
                    outcomes = Counter()
                    for rank in ranks:
                        for turn in (1, 2):
                            for clock in range(args.clock + 1):
                                state = reference.state_from_rank(counts, rank, turn, reversible_plies=clock)
                                expected, actual = reference.probe(state), native.probe(state)
                                if actual != expected:
                                    raise AssertionError(f"TB{n} {counts} rank={rank} turn={turn} "
                                                         f"clock={clock}: {actual} != {expected}")
                                probes += 1
                                outcomes[actual.outcome.name] += 1
                    report["total_probes"] += probes
                    report["signature_comparisons"].append(dict(
                        pieces=n, counts=counts, boards=boards, ranks=ranks,
                        probes=probes, outcomes=dict(outcomes), mismatches=0,
                    ))
                lease.checkpoint(f"before TB{n} map SHA-256")
                report["artifacts"].append(dict(path=str(path.resolve()),
                    mapped_sha256=native.mapped_sha256(n), **native.ranked_info(n)))
            if args.verify_provenance:
                lease.checkpoint("before provenance verification")
                native.verify_provenance(args.manifest)
            report["provenance_verified"] = args.verify_provenance
            report["complete_139_signatures"] = seen == {4, 5, 6} and len(report["signature_comparisons"]) == 139
            report["status"] = "PARITY_PASS" if report["complete_139_signatures"] else "PARTIAL_PARITY_PASS"
            after = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}
            if after != report["source_sha256"] or hashlib.sha256(args.library.read_bytes()).hexdigest() != report["library_sha256"]:
                raise RuntimeError("source/library identity changed during verification")
        except BaseException as error:
            report["status"] = "FAILED"
            report["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "status", "total_probes", "complete_139_signatures", "prepare_ms", "provenance_verified",
        )}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--tablebase", type=Path, nargs="+", required=True)
    parser.add_argument("--clock", type=int, default=80)
    parser.add_argument("--ranks", type=int, default=64, help="including five boundary/interior ranks per signature")
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--verify-checksum", action="store_true", help="full native payload FNV scan at prepare")
    parser.add_argument("--verify-provenance", action="store_true", help="strict rules/generator/artifact manifest gate")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.ranks < 5 or not 1 <= args.clock <= 126:
        parser.error("ranks must be >= 5 and clock must be in 1..126")
    run(args)
