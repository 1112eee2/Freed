"""Opt-in attribution for one request thread, never for strength measurements."""

from __future__ import annotations

import cProfile
from collections import defaultdict
from pathlib import Path
import pstats


def _category(filename: str, function: str) -> str:
    name = Path(filename).name
    if name == "native_tablebase.py":
        return "tb3_probe" if function == "probe" else "tb3_lifecycle"
    if name == "ranked_tablebase.py":
        return "ranked_tb_rank_decode_load"
    if name == "exact.py":
        return "exact_solver"
    if name == "core.py":
        return "terminal_rules" if function == "terminal_status" else "move_generation_state"
    if name in ("native.py", "parallel_native.py"):
        return "native_bridge_orchestration"
    if name in ("eval.py", "policy_value.py"):
        return "evaluation_policy"
    if name == "distance.py":
        return "distance"
    if name == "search.py":
        if function in ("_negamax", "_quiescence", "_search_root"):
            return "python_tree"
        return "python_search_other"
    return "other"


class RequestProfiler:
    """Profile setup and search on the calling thread; restore on exceptions.

    Self times form a non-overlapping partition of observed function time.
    Cumulative times are diagnostic only: recursive/nested calls overlap.
    Foreign native calls are opaque; helper threads are not profiled.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._profile = cProfile.Profile() if enabled else None

    def __enter__(self) -> RequestProfiler:
        if self._profile is not None:
            self._profile.enable()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._profile is not None:
            self._profile.disable()

    def report(self) -> dict | None:
        if self._profile is None:
            return None
        buckets = defaultdict(lambda: {"calls": 0, "self_ms": 0.0})
        functions = []
        stats = pstats.Stats(self._profile)
        for (filename, line, function), (_, calls, own, cumulative, _) in stats.stats.items():
            bucket = buckets[_category(filename, function)]
            bucket["calls"] += calls
            bucket["self_ms"] += own * 1000
            functions.append({
                "function": f"{Path(filename).name}:{line}:{function}",
                "calls": calls,
                "self_ms": round(own * 1000, 3),
                "cumulative_ms": round(cumulative * 1000, 3),
            })
        return {
            "format": "thai-makhos-request-profile-v1",
            "scope": "request-thread-engine-setup-tb3-search",
            "strength_evidence": False,
            "native_internals_measured": False,
            "io_wait_separated": False,
            "total_self_ms": round(stats.total_tt * 1000, 3),
            "categories": {
                name: {**values, "self_ms": round(values["self_ms"], 3)}
                for name, values in sorted(buckets.items())
            },
            "hot_functions": sorted(functions, key=lambda item: item["self_ms"], reverse=True)[:20],
        }
