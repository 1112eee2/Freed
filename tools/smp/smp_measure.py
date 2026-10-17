"""Track F2 measurements for native Lazy SMP (LAZY_SMP_01).

Two subcommands, both for an idle machine (no SPRT gate, no GUI):

``m1``       Hardware ceiling.  Runs k one-thread engine processes at once
             (k = 1, 2, 4, 6, 8, 10, 12) on the same fixed-time searches and
             reports the NPS per process and the aggregate.  The aggregate at
             12 processes bounds what any SMP design can reach on this box.

``scaling``  Lazy SMP at 1/2/4/6/8/12 threads against the production root
             split at 12 threads (and one thread of the control DLL): depth
             and NPS at a fixed time, and wall time to a fixed depth.  Every
             search starts from an empty TT.

    python -B tools/smp/smp_measure.py m1 --output build/lazy_smp_01/m1.json
    python -B tools/smp/smp_measure.py scaling --output build/lazy_smp_01/scaling.json

Both refuse to start while a ``makhos sprt`` process or the GUI is running
(``--force`` overrides the SPRT check only) and run below normal priority.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, parse_position  # noqa: E402
from makhos.native import (  # noqa: E402
    NativeLazySmpSearch,
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.parallel_native import ParallelNativeSearch  # noqa: E402
from makhos.workload_isolation import ensure_interactive_session_inactive  # noqa: E402

PROJECT = Path(r"D:\ThaiMakhosEngine")
DEFAULT_CONTROL = PROJECT / "build" / "search_int01" / "candidate" / "makhos_native_nnue_candidate_v1.dll"
DEFAULT_LAZY = ROOT / "build" / "lazy_smp_01" / "candidate" / "makhos_native_nnue_candidate_v1.dll"
DEFAULT_MODEL = PROJECT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
DEFAULT_CORPUS = ROOT / "corpora" / "middlegame_search_v5.jsonl"
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def _below_normal() -> None:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)


def _running_sprt_pids() -> list[int]:
    if os.name != "nt":
        return []
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match '-m makhos sprt' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    output = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [int(item) for item in output.split()]


def _require_idle_machine(force: bool) -> None:
    ensure_interactive_session_inactive("an SMP measurement")
    pids = _running_sprt_pids()
    if pids and not force:
        raise SystemExit(
            f"an SPRT gate is running (pids {pids}); measure in a gap without a gate"
        )


def load_samples(path: Path, count: int) -> list[dict[str, object]]:
    """The first ``count`` stable samples, in corpus order."""
    samples = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            label = record.get("label") or {}
            if record.get("kind") != "sample" or label.get("classification") != "stable":
                continue
            samples.append(
                {
                    "id": record["id"],
                    "position": record["position"],
                    "reversible_plies": int(record.get("reversible_plies", 0)),
                    "long_move": label.get("long_move"),
                }
            )
            if len(samples) == count:
                break
    return samples


def _state(sample: dict[str, object]):
    return parse_position(
        str(sample["position"]), reversible_plies=int(sample["reversible_plies"])
    )


def _search_options(depth: int, time_ms: int | None) -> dict[str, object]:
    return {
        "depth": depth,
        "time_ms": time_ms,
        "no_progress_plies": DEFAULT_RULES.no_progress_plies,
        "repetition_limit": DEFAULT_RULES.repetition_limit,
    }


# --- M1: hardware ceiling -------------------------------------------------


def _m1_worker(library, model, hash_power, samples, time_ms, barrier, results) -> None:
    _below_normal()
    nodes = 0
    elapsed_ms = 0
    with NativeSearch(library, hash_power=hash_power, persistent=True, nnue_model=model) as engine:
        barrier.wait()
        for sample in samples:
            engine.clear()
            result = engine.search(_state(sample), **_search_options(64, time_ms))
            nodes += result.nodes
            elapsed_ms += result.elapsed_ms
    results.put((nodes, elapsed_ms))


def command_m1(args: argparse.Namespace) -> dict[str, object]:
    samples = load_samples(args.corpus, args.positions)
    hash_power = hash_power_for_megabytes(
        args.hash_mb, entry_bytes=native_tt_entry_bytes(args.library)
    )
    context = mp.get_context("spawn")
    rows = []
    for processes in args.processes:
        ensure_interactive_session_inactive(f"M1 with {processes} processes")
        barrier = context.Barrier(processes)
        results = context.Queue()
        workers = [
            context.Process(
                target=_m1_worker,
                args=(args.library, args.nnue_model, hash_power, samples, args.time_ms, barrier, results),
            )
            for _ in range(processes)
        ]
        for worker in workers:
            worker.start()
        # A worker that dies before reporting must not hang the measurement.
        timeout_s = 120.0 + 3.0 * len(samples) * args.time_ms / 1000.0
        totals = [results.get(timeout=timeout_s) for _ in workers]
        for worker in workers:
            worker.join()
            if worker.exitcode != 0:
                raise RuntimeError(f"M1 worker failed with exit code {worker.exitcode}")
        per_process = [nodes * 1000.0 / max(1, elapsed) for nodes, elapsed in totals]
        rows.append(
            {
                "processes": processes,
                "nps_per_process_mean": statistics.fmean(per_process),
                "nps_per_process_min": min(per_process),
                "nps_aggregate": sum(per_process),
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    base = rows[0]["nps_aggregate"] if rows and rows[0]["processes"] == 1 else None
    for row in rows:
        row["aggregate_vs_one_process"] = None if base is None else row["nps_aggregate"] / base
    return {
        "format": "thai-makhos-smp-m1-v1",
        "library": str(args.library.resolve()),
        "nnue_model": str(args.nnue_model.resolve()),
        "positions": len(samples),
        "time_ms": args.time_ms,
        "hash_mb_per_process": args.hash_mb,
        "rows": rows,
    }


# --- F2: Lazy-SMP scaling -------------------------------------------------


def _configs(args: argparse.Namespace):
    yield "control-1t", lambda: NativeSearch(
        args.control_library,
        hash_power=hash_power_for_megabytes(
            args.hash_mb, entry_bytes=native_tt_entry_bytes(args.control_library)
        ),
        persistent=True,
        nnue_model=args.nnue_model,
    )
    yield f"root-split-{args.root_split_threads}t", lambda: ParallelNativeSearch(
        args.control_library,
        threads=args.root_split_threads,
        hash_mb=args.hash_mb,
        nnue_model=args.nnue_model,
    )
    for threads in args.threads:
        yield f"lazy-{threads}t", lambda threads=threads: NativeLazySmpSearch(
            args.lazy_library,
            threads=threads,
            hash_mb=args.hash_mb,
            nnue_model=args.nnue_model,
        )


def _measure(engine, samples, options) -> list[dict[str, object]]:
    rows = []
    for sample in samples:
        engine.clear()
        state = _state(sample)
        started = time.perf_counter()
        result = engine.search(state, **options)
        wall_ms = (time.perf_counter() - started) * 1000.0
        stats = engine.stats if isinstance(engine, NativeLazySmpSearch) else None
        rows.append(
            {
                "id": sample["id"],
                "move": result.move.notation,
                "matches_long_move": result.move.notation == sample["long_move"],
                "depth": result.depth,
                "nodes": result.nodes,
                "aggregate_nodes": result.nodes if stats is None else stats.aggregate_nodes,
                "wall_ms": wall_ms,
            }
        )
    return rows


def _summarise(rows: list[dict[str, object]]) -> dict[str, object]:
    wall_s = sum(row["wall_ms"] for row in rows) / 1000.0
    return {
        "mean_depth": statistics.fmean(row["depth"] for row in rows),
        "long_move_matches": sum(bool(row["matches_long_move"]) for row in rows),
        "leader_nps": sum(row["nodes"] for row in rows) / wall_s,
        "aggregate_nps": sum(row["aggregate_nodes"] for row in rows) / wall_s,
        "total_wall_s": wall_s,
    }


def command_scaling(args: argparse.Namespace) -> dict[str, object]:
    samples = load_samples(args.corpus, args.positions)
    fixed_time = _search_options(64, args.time_ms)
    fixed_depth = _search_options(args.depth, None)
    results: dict[str, dict[str, object]] = {}
    for name, factory in _configs(args):
        ensure_interactive_session_inactive(f"scaling {name}")
        with factory() as engine:
            timed = _measure(engine, samples, fixed_time)
            to_depth = _measure(engine, samples, fixed_depth)
        results[name] = {
            "fixed_time": _summarise(timed),
            "fixed_depth": _summarise(to_depth),
            "positions": {"fixed_time": timed, "fixed_depth": to_depth},
        }
        print(name, json.dumps({k: v for k, v in results[name].items() if k != "positions"}), flush=True)

    # Time-to-depth speedup over one control thread: geometric mean per position.
    base = {row["id"]: row["wall_ms"] for row in results["control-1t"]["positions"]["fixed_depth"]}
    for entry in results.values():
        ratios = [
            base[row["id"]] / row["wall_ms"]
            for row in entry["positions"]["fixed_depth"]
            if row["wall_ms"] > 0
        ]
        entry["fixed_depth"]["speedup_vs_control_1t"] = math.exp(
            statistics.fmean(math.log(ratio) for ratio in ratios)
        )
    return {
        "format": "thai-makhos-smp-scaling-v1",
        "lazy_library": str(args.lazy_library.resolve()),
        "control_library": str(args.control_library.resolve()),
        "nnue_model": str(args.nnue_model.resolve()),
        "positions": len(samples),
        "time_ms": args.time_ms,
        "depth": args.depth,
        "hash_mb": args.hash_mb,
        "results": results,
    }


def _int_list(text: str) -> list[int]:
    return [int(item) for item in text.split(",") if item]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("m1", "scaling"):
        command = sub.add_parser(name)
        command.add_argument("--nnue-model", type=Path, default=DEFAULT_MODEL)
        command.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
        command.add_argument("--time-ms", type=int, default=1000)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--force", action="store_true")
    m1 = sub.choices["m1"]
    m1.add_argument("--library", type=Path, default=DEFAULT_CONTROL)
    m1.add_argument("--positions", type=int, default=12)
    m1.add_argument("--hash-mb", type=int, default=64)
    m1.add_argument("--processes", type=_int_list, default=[1, 2, 4, 6, 8, 10, 12])
    scaling = sub.choices["scaling"]
    scaling.add_argument("--lazy-library", type=Path, default=DEFAULT_LAZY)
    scaling.add_argument("--control-library", type=Path, default=DEFAULT_CONTROL)
    scaling.add_argument("--positions", type=int, default=24)
    scaling.add_argument("--depth", type=int, default=18)
    scaling.add_argument("--hash-mb", type=int, default=512)
    scaling.add_argument("--threads", type=_int_list, default=[1, 2, 4, 6, 8, 12])
    scaling.add_argument("--root-split-threads", type=int, default=12)
    args = parser.parse_args()

    _require_idle_machine(args.force)
    _below_normal()
    report = command_m1(args) if args.command == "m1" else command_scaling(args)
    report["measured_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
