#!/usr/bin/env python3
"""G4 acceptance scaling matrix for the Native Lazy SMP candidate.

Each matrix cell runs in its own child process. That is not decoration: the
native layer reads ``MAKHOS_LAZY_SMP_DISABLE_HINTS`` with ``getenv()`` when a
handle is created (``native/makhos_native.c``), and the C runtime may cache the
environment block, so an in-process toggle is not a trustworthy ON/OFF
comparison. The parent therefore fixes the variable in the child environment
before the DLL is ever loaded.

Backends
--------
``lazy_smp``    the opt-in candidate backend (``NativeLazySmpSearch``).
``root_split``  the production backend (``NativeSearch`` at 1T,
                ``ParallelNativeSearch`` above 1T).

The r3 same-source strict control DLL is compiled *without*
``-DMAKHOS_NATIVE_LAZY_SMP=1``, so it cannot be driven through the Lazy SMP ABI
at all. The meaningful runtime comparison the G4 gate asks for is therefore
Lazy SMP against the production root-split backend on the same DLLs, the same
positions, the same fixed total Hash and the same time controls. The default
role mapping does exactly that.

This harness measures; it does not decide. It records identities (candidate,
control, model, source inventory) so a result can never be attributed to a
file name alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CANDIDATE = ROOT / "build/lazy_smp_acceptance_20260916_r3/candidate/makhos_native_lazy_smp_candidate_v1.dll"
DEFAULT_CONTROL = ROOT / "build/lazy_smp_acceptance_20260916_r3/control/makhos_native_nnue_candidate_v1.dll"
DEFAULT_MODEL = ROOT / "build/nnue_quantized_v1/model_a.mknnue"
DEFAULT_THREADS = (1, 2, 4, 6, 8, 12)
DEFAULT_TIME_MS = (1000, 2000)
DEFAULT_HASH_MB = 512
FORMAT = "makhos-lazy-smp-scaling-v1"

BACKEND_LAZY = "lazy_smp"
BACKEND_ROOT_SPLIT = "root_split"

# Held-out suite. The parity gate already uses initial/tactical/middlegame/
# multi-capture/promotion/clock-79 fixtures, so these are different positions.
# opening_8/early_14/mid_20/late_26 come from seeded legal play (seeds
# 101/202/303/404) and are reproducible from that description.
POSITIONS: tuple[tuple[str, str, str], ...] = (
    ("reference_initial", "initial", "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"),
    ("opening_8", "opening", "B:BM19,22,26,27,28,29,30,32:RM1,3,4,5,7,9,10,12"),
    ("early_14", "opening", "B:BM16,25,26,27,28,29,30:RM1,2,3,4,5,13,17"),
    ("mid_20", "middlegame", "B:BM18,24,25,26,30:RM1,3,4,5,12,23"),
    ("late_26", "middlegame", "B:BM17,23,24,27,29,32:RM2,5,9,12,15,18,21"),
    ("mg_center", "middlegame", "B:BM11,14,18,21,24,26,28:BK29:RM3,6,9,13,17,19,22:RK4"),
    ("multi_capture_alt2", "tactical", "B:BM21,24:BK15:RM13,14,18,19,25"),
    ("tactical_exchange", "tactical", "B:BM13,17,20,22,25:BK31:RM6,9,12,16,19,24:RK1"),
    ("dense_cluster", "tactical", "B:BM16,17,18,22,23,24:BK30:RM8,9,10,14,15,20:RK3"),
    ("endgame_2v2", "endgame", "B:BM12,16:BK25:RM17,21:RK4"),
    ("endgame_3v2", "endgame", "B:BM9,13,17:BK27:RM20,24:RK2"),
)

LAZY_ONLY_FIELDS = (
    "aggregate_nodes", "leader_nodes", "worker_nodes", "worker_depth",
    "completed_threads", "shared_hint_entries", "shared_hint_allocated_bytes",
    "private_tt_allocated_bytes", "tt_allocated_bytes",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _source_inventory_sha256() -> tuple[str, int]:
    """Reuse the gate's own inventory so results stay comparable."""

    from tools.verification import full_suite_attestation as gate

    paths = gate.source_inventory_paths()
    return gate.inventory_sha256(paths), len(paths)


def _set_below_normal_priority() -> str:
    from makhos.cli_handlers.sprt_handler import _set_batch_process_priority

    return _set_batch_process_priority()


def _rss_bytes() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.Process().memory_info().rss)


def _cpu_ms() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    times = psutil.Process().cpu_times()
    return (times.user + times.system) * 1000.0


def _pv_is_legal(state, pv, legal_moves) -> bool:
    from makhos.core import apply_move

    position = state
    for move in pv:
        if move not in legal_moves(position):
            return False
        position = apply_move(position, move)
    return True


def _blank_lazy_fields() -> dict:
    return {name: None for name in LAZY_ONLY_FIELDS} | {
        "worker_nodes": [], "worker_depth": [],
    }


def _measure_stop_latency(engine, state, cell) -> dict:
    """Start a long search and measure the drain latency of an external stop."""

    import threading

    outcome: dict = {}
    returned = [0.0]

    def worker() -> None:
        try:
            outcome["result"] = engine.search(
                state, depth=64, time_ms=cell["stop_after_ms"] * 20,
                no_progress_plies=80, repetition_limit=3,
            )
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        returned[0] = time.perf_counter()

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(cell["stop_after_ms"] / 1000.0)
    sent = time.perf_counter()
    engine.stop()
    thread.join(timeout=30.0)
    latency_ms = (returned[0] - sent) * 1000.0
    return _blank_lazy_fields() | {
        "main_depth": None,
        "main_nodes": None,
        "wall_ms": None,
        "deadline_overshoot_ms": None,
        "stop_latency_ms": round(latency_ms, 3),
        "stop_thread_alive": thread.is_alive(),
        "stop_error": outcome.get("error"),
        "move": None if "result" not in outcome else str(outcome["result"].move),
        "score": None if "result" not in outcome else outcome["result"].score,
        "pv_legal": None,
    }


def _allocated_tt_bytes(engine, *, lazy: bool) -> tuple[int | None, float | None]:
    """Read the Hash allocation at construction time, before any search.

    ``NativeSearch.memory_bytes`` is not stable across a search: measured on the
    r3 control it grows from 484.9 MiB to 520.6 MiB at 12T once a search has run
    (lazily committed structures, with ``workspace_lists`` still 0), so reading it
    afterwards overstates the Hash allocation and can look like a budget overrun.
    The stable figures are the native stats for Lazy SMP and the Python-side
    ``allocated_hash_mb`` for root-split.
    """

    if lazy:
        stats = engine.stats
        total = stats.private_tt_allocated_bytes + stats.shared_hint_allocated_bytes
        return int(total), engine.allocated_hash_mb
    allocated_mb = getattr(engine, "allocated_hash_mb", None)
    return (
        None if allocated_mb is None else int(round(allocated_mb * 1024 * 1024)),
        allocated_mb,
    )


def _measure_search(engine, state, cell, *, lazy: bool) -> dict:
    from makhos.core import legal_moves

    if cell["state"] == "warm":
        # One discarded search on the same handle keeps TT/hints warm.
        engine.search(state, depth=64, time_ms=min(250, cell["time_ms"]),
                      no_progress_plies=80, repetition_limit=3)
    engine.clear()
    started = time.perf_counter()
    result = engine.search(state, depth=64, time_ms=cell["time_ms"],
                           no_progress_plies=80, repetition_limit=3)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    record = {
        "main_depth": result.depth,
        "main_nodes": result.nodes,
        "wall_ms": round(elapsed_ms, 3),
        "deadline_overshoot_ms": round(elapsed_ms - cell["time_ms"], 3),
        "stop_latency_ms": None,
        "move": str(result.move),
        "score": result.score,
        "pv_legal": _pv_is_legal(state, result.pv, legal_moves),
    }
    if lazy:
        stats = engine.stats
        record |= {
            "aggregate_nodes": stats.aggregate_nodes,
            "leader_nodes": stats.leader_nodes,
            "worker_nodes": list(stats.worker_nodes),
            "worker_depth": list(stats.worker_depth),
            "completed_threads": stats.completed_threads,
            "shared_hint_entries": stats.shared_hint_entries,
            "shared_hint_allocated_bytes": stats.shared_hint_allocated_bytes,
            "private_tt_allocated_bytes": stats.private_tt_allocated_bytes,
        }
    else:
        record |= _blank_lazy_fields()
    return record


def _open_engine(cell):
    from makhos.core import initial_state, parse_position
    from makhos.native import NativeLazySmpSearch

    dll = Path(cell["dll"])
    model = None if cell["nnue_model"] is None else Path(cell["nnue_model"])
    if cell["backend"] == BACKEND_LAZY:
        return NativeLazySmpSearch(
            dll, threads=cell["threads"], hash_mb=cell["hash_mb"], nnue_model=model
        )
    from makhos.engine_manager import _create_native_search

    return _create_native_search(
        dll, threads=cell["threads"], hash_mb=cell["hash_mb"], nnue_model=model
    )


def run_cell(cell: dict) -> dict:
    """Execute one matrix cell in this process and return its measurements."""

    from makhos.core import initial_state, parse_position

    fen = cell["fen"]
    state = initial_state() if fen == "initial" else parse_position(fen)
    lazy = cell["backend"] == BACKEND_LAZY

    record = {
        "position_id": cell["position_id"],
        "category": cell["category"],
        "fen": fen,
        "dll_role": cell["dll_role"],
        "dll_sha256": _sha256_file(Path(cell["dll"])),
        "backend": cell["backend"],
        "threads": cell["threads"],
        "time_ms": cell["time_ms"],
        "repeat": cell["repeat"],
        "state": cell["state"],
        "hints": cell["hints"],
        "mode": cell["mode"],
    }

    rss_before = _rss_bytes()
    cpu_before = _cpu_ms()

    with _open_engine(cell) as engine:
        # Sample the Hash allocation before any search runs; see _allocated_tt_bytes.
        record["tt_allocated_bytes"], record["allocated_hash_mb"] = _allocated_tt_bytes(
            engine, lazy=lazy
        )
        if cell["mode"] == "stop_latency":
            record |= _measure_stop_latency(engine, state, cell)
        else:
            record |= _measure_search(engine, state, cell, lazy=lazy)

    cpu_after = _cpu_ms()
    rss_after = _rss_bytes()
    if cpu_before is not None and cpu_after is not None:
        record["cpu_ms"] = round(cpu_after - cpu_before, 3)
        wall = record.get("wall_ms")
        record["cpu_utilization"] = (
            None if wall is None else round((cpu_after - cpu_before) / max(wall, 1.0), 3)
        )
    else:
        record["cpu_ms"] = None
        record["cpu_utilization"] = None
    record["rss_before_bytes"] = rss_before
    record["peak_rss_bytes"] = rss_after
    return record


def build_cells(args) -> list[dict]:
    def role_spec(role: str) -> tuple[str, str]:
        if role == "candidate":
            return str(args.candidate_dll), args.candidate_backend
        return str(args.control_dll), args.control_backend

    positions = POSITIONS
    if args.positions:
        wanted = {name.strip() for name in args.positions.split(",") if name.strip()}
        positions = tuple(item for item in POSITIONS if item[0] in wanted)
        missing = wanted - {item[0] for item in positions}
        if missing:
            raise SystemExit(f"unknown positions: {sorted(missing)}")

    roles = [value.strip() for value in args.roles.split(",") if value.strip()]
    threads = [int(value) for value in args.threads.split(",")]
    times = [int(value) for value in args.time_ms.split(",")]
    hints_modes = args.hints.split(",")
    states = args.mode.split(",")

    cells: list[dict] = []
    for role in roles:
        dll, backend = role_spec(role)
        # Root-split ignores the hints switch entirely; label it honestly.
        role_hints = hints_modes if backend == BACKEND_LAZY else ["n/a"]
        for position_id, category, fen in positions:
            for thread_count in threads:
                for time_ms in times:
                    for hints in role_hints:
                        for state in states:
                            for repeat in range(args.repeats):
                                cells.append({
                                    "position_id": position_id,
                                    "category": category,
                                    "fen": fen,
                                    "dll_role": role,
                                    "dll": dll,
                                    "backend": backend,
                                    "nnue_model": None if args.nnue_model is None else str(args.nnue_model),
                                    "threads": thread_count,
                                    "time_ms": time_ms,
                                    "hash_mb": args.hash_mb,
                                    "hints": hints,
                                    "state": state,
                                    "repeat": repeat,
                                    "mode": "search",
                                    "stop_after_ms": args.stop_after_ms,
                                })
    if args.stop_latency:
        # Only the Lazy SMP ABI exposes an external stop().
        for role in roles:
            dll, backend = role_spec(role)
            if backend != BACKEND_LAZY:
                continue
            for thread_count in threads:
                cells.append({
                    "position_id": "stop_latency",
                    "category": "lifecycle",
                    "fen": "initial",
                    "dll_role": role,
                    "dll": dll,
                    "backend": backend,
                    "nnue_model": None if args.nnue_model is None else str(args.nnue_model),
                    "threads": thread_count,
                    "time_ms": args.stop_after_ms,
                    "hash_mb": args.hash_mb,
                    "hints": "on",
                    "state": "cold",
                    "repeat": 0,
                    "mode": "stop_latency",
                    "stop_after_ms": args.stop_after_ms,
                })
    if args.interleave_roles:
        # Block ordering is a confound: a transient external event during the first
        # block hits only that block. Putting repeat before hints and role makes the
        # schedule alternate both within each repeat, so ON/OFF and candidate/control
        # see the same conditions. Python's sort is stable.
        cells.sort(key=lambda c: (
            c["position_id"], c["threads"], c["time_ms"], c["state"],
            c["repeat"], c["hints"], c["mode"],
            0 if c["dll_role"] == "candidate" else 1,
        ))
    return cells


def run_cell_in_child(cell: dict, *, timeout_s: float) -> dict:
    env = dict(os.environ)
    env["MAKHOS_LAZY_SMP_DISABLE_HINTS"] = "1" if cell["hints"] == "off" else "0"
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", json.dumps(cell)]
    try:
        completed = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {**cell, "error": f"child timed out after {timeout_s:.0f}s"}
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        return {**cell, "error": f"child exit {completed.returncode}: {' | '.join(tail)}"}
    for line in reversed((completed.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {**cell, "error": "child produced no JSON result"}


def preflight(args) -> list[str]:
    """Fail before the matrix if a role cannot be constructed at all."""

    from makhos.engine_manager import _create_native_search
    from makhos.native import NativeLazySmpSearch

    model = None if args.nnue_model is None else Path(args.nnue_model)
    problems: list[str] = []
    for role, dll, backend in (
        ("candidate", Path(args.candidate_dll), args.candidate_backend),
        ("control", Path(args.control_dll), args.control_backend),
    ):
        try:
            if backend == BACKEND_LAZY:
                with NativeLazySmpSearch(dll, threads=1, hash_mb=64, nnue_model=model):
                    pass
            else:
                with _create_native_search(dll, threads=1, hash_mb=64, nnue_model=model):
                    pass
            print(f"preflight {role:9} {backend:10} OK  ({dll.name})")
        except Exception as error:  # noqa: BLE001 - reported to the operator
            message = f"preflight {role} {backend} FAILED: {type(error).__name__}: {error}"
            print(message)
            problems.append(message)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dll", default=str(DEFAULT_CANDIDATE))
    parser.add_argument("--control-dll", default=str(DEFAULT_CONTROL))
    parser.add_argument("--nnue-model", default=str(DEFAULT_MODEL))
    parser.add_argument("--candidate-backend", choices=(BACKEND_LAZY, BACKEND_ROOT_SPLIT),
                        default=BACKEND_LAZY)
    parser.add_argument("--control-backend", choices=(BACKEND_LAZY, BACKEND_ROOT_SPLIT),
                        default=BACKEND_ROOT_SPLIT)
    parser.add_argument("--positions", default=None,
                        help="comma-separated subset of position ids (default: all)")
    parser.add_argument("--roles", default="candidate,control",
                        help="comma-separated: candidate,control")
    parser.add_argument("--threads", default=",".join(str(v) for v in DEFAULT_THREADS))
    parser.add_argument("--time-ms", default=",".join(str(v) for v in DEFAULT_TIME_MS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=DEFAULT_HASH_MB,
                        help="fixed total Hash budget for every cell")
    parser.add_argument("--hints", default="on,off",
                        help="Lazy SMP hint modes; ignored by root-split cells")
    parser.add_argument("--mode", default="cold,warm")
    parser.add_argument("--stop-latency", action="store_true",
                        help="add one stop-latency cell per Lazy SMP role and thread count")
    parser.add_argument("--stop-after-ms", type=int, default=60)
    parser.add_argument("--interleave-roles", action="store_true",
                        help="alternate candidate/control cells so a transient event hits both roles")
    parser.add_argument("--child-timeout-s", type=float, default=300.0)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--output", default=None,
                        help="path for the JSON report (required outside --worker mode)")
    parser.add_argument("--worker", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.worker is not None:
        cell = json.loads(args.worker)
        _set_below_normal_priority()
        print(json.dumps(run_cell(cell)))
        return 0

    if args.output is None:
        parser.error("--output is required")

    for path in (Path(args.candidate_dll), Path(args.control_dll)):
        if not path.is_file():
            raise SystemExit(f"DLL not found: {path}")
    if args.nnue_model is not None and not Path(args.nnue_model).is_file():
        raise SystemExit(f"NNUE model not found: {args.nnue_model}")

    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing evidence: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_preflight:
        problems = preflight(args)
        if problems:
            raise SystemExit(
                "preflight failed; the matrix was not started:\n  " + "\n  ".join(problems)
            )

    from makhos.workload_isolation import BatchWorkLease

    cells = build_cells(args)
    identity = {
        "candidate_dll": {"path": str(Path(args.candidate_dll).resolve()),
                          "sha256": _sha256_file(Path(args.candidate_dll))},
        "control_dll": {"path": str(Path(args.control_dll).resolve()),
                        "sha256": _sha256_file(Path(args.control_dll))},
        "nnue_model": (None if args.nnue_model is None
                       else {"path": str(Path(args.nnue_model).resolve()),
                             "sha256": _sha256_file(Path(args.nnue_model))}),
        "harness_sha256": _sha256_file(Path(__file__).resolve()),
    }
    inventory_sha, inventory_files = _source_inventory_sha256()
    identity["source_inventory_sha256"] = inventory_sha
    identity["source_files"] = inventory_files

    report = {
        "format": FORMAT,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "identities": identity,
        "host": {
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "python": sys.version.split()[0],
            "hints_isolation": "separate child process per cell (CRT getenv caching)",
        },
        "config": {
            "roles": args.roles,
            "candidate_backend": args.candidate_backend,
            "control_backend": args.control_backend,
            "threads": [int(v) for v in args.threads.split(",")],
            "time_ms": [int(v) for v in args.time_ms.split(",")],
            "hash_mb": args.hash_mb,
            "repeats": args.repeats,
            "hints": args.hints.split(","),
            "mode": args.mode.split(","),
            "stop_latency": bool(args.stop_latency),
            "stop_after_ms": args.stop_after_ms,
            "interleave_roles": bool(args.interleave_roles),
        },
        "cell_count": len(cells),
        "cells": [],
    }

    priority = _set_below_normal_priority()
    report["host"]["process_priority"] = priority
    errors = 0
    with BatchWorkLease(ROOT) as lease:
        for index, cell in enumerate(cells, start=1):
            lease.checkpoint(f"cell {index}/{len(cells)}")
            result = run_cell_in_child(cell, timeout_s=args.child_timeout_s)
            report["cells"].append(result)
            if "error" in result:
                errors += 1
            label = (f"{result.get('dll_role')}/{result.get('backend')}"
                     f"/{result.get('position_id')}/{result.get('threads')}T"
                     f"/{result.get('time_ms')}ms/{result.get('state')}"
                     f"/hints={result.get('hints')}")
            detail = (f"depth={result.get('main_depth')} nodes={result.get('main_nodes')} "
                      f"wall={result.get('wall_ms')}ms "
                      f"overshoot={result.get('deadline_overshoot_ms')}ms "
                      f"stop={result.get('stop_latency_ms')}ms"
                      if "error" not in result else result["error"])
            print(f"[{index}/{len(cells)}] {label} -> {detail}", flush=True)

    report["errors"] = errors
    report["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\nwrote {output} ({len(cells)} cells, {errors} errors)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
