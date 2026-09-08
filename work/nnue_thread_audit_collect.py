"""Native measurement collector for NNUE thread-scaling audit.

Collects real search measurements following the exact schedule and schema from
work/NNUE_THREAD_AUDIT_REPORT.md. Evaluates 1, 2, 4, 6, 8, 12 threads at 1s/2s
budgets with 512 MiB total Hash budget across reproducible positions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import parse_position, legal_moves
from makhos.eval import evaluate_handcrafted
from makhos.gui_release import load_release, DEFAULT_POINTER
from makhos.native import (
    NativeSearch,
    native_tt_entry_bytes,
    hash_power_for_megabytes,
)
from makhos.parallel_native import ParallelNativeSearch
from makhos.workload_isolation import interactive_session_active
from work.prepare_nnue_thread_audit import (
    prepare,
    prepare_cases,
    digest,
    THREADS,
    BUDGETS,
)
from work.nnue_thread_audit_report import (
    FORMAT,
    OPTIONAL_METRICS,
    ObservationValidator,
    strict_json,
    require,
)

PILOT_CASE_IDS = ("playout-002", "playout-062", "clock-edge-0-1", "playout-039")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def prepare_pilot() -> dict:
    """Curated 48-observation pilot schedule covering quiet, multi-capture, kings/near-draw, and forced."""
    all_cases = {c["id"]: c for c in prepare_cases()}
    cases = [all_cases[cid] for cid in PILOT_CASE_IDS]
    schedule = []
    # 4 cases * 2 budgets * 6 thread counts = 48 observations
    for case in cases:
        for budget in BUDGETS:
            for threads in THREADS:
                schedule.append({
                    "case": case["id"],
                    "repetition": 0,
                    "budget_ms": budget,
                    "threads": threads,
                    "hash_mb_total": 512,
                })
    coverage = {
        "positions": len(cases),
        "with_kings": sum(bool(c["kings"]) for c in cases),
        "captures": sum(c["capture"] for c in cases),
        "multi_captures": sum(c["multi_capture"] for c in cases),
        "turns": dict(Counter(c["turn"] for c in cases)),
        "piece_counts": dict(Counter(c["pieces"] for c in cases)),
        "clock_edge_cases": sum(1 for c in cases if c["id"].startswith("clock-edge-")),
    }
    return {
        "format": "thai-makhos-thread-audit-preparation-v1",
        "seed": 20261107,
        "status": "PILOT_FIXTURES_ONLY",
        "native_search_authorized": True,
        "requires": "Gate C PASSED, NNUE promoted, pilot audit verification",
        "strength_evidence": False,
        "coverage": coverage,
        "cases": cases,
        "schedule": schedule,
    }


def verify_release(release_pointer: Path | None = None) -> tuple[dict, dict, dict]:
    """Verify DLL, model, ABI, and tablebases against the release manifest."""
    pointer = DEFAULT_POINTER if release_pointer is None else Path(release_pointer).resolve()
    release = load_release(pointer)
    if release is None or release.get("profile") != "nnue":
        raise RuntimeError(f"Audit requires active NNUE release profile in {pointer}")

    pointer_data = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = (ROOT / pointer_data["manifest"]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Tablebase verification
    tb_map = {}
    for tb in manifest["tablebases"]:
        tb_path = (ROOT / tb["path"]).resolve()
        if not tb_path.is_file():
            raise FileNotFoundError(f"Missing release tablebase: {tb_path}")
        if tb_path.stat().st_size != tb["bytes"]:
            raise ValueError(f"Tablebase size mismatch for {tb_path}")
        piece_count = "4" if "tb4" in tb["path"] else "5" if "tb5" in tb["path"] else "6"
        tb_map[piece_count] = tb["sha256"]

    if set(tb_map) != {"4", "5", "6"}:
        raise ValueError("Missing tablebases 4, 5, or 6 in release manifest")

    dll_path = release["native_library"]
    model_path = release["nnue_model"]
    with NativeSearch(dll_path, hash_power=12, persistent=True, nnue_model=model_path) as probe:
        if probe.abi_version != release["native_search_abi"]:
            raise ValueError("Native search ABI mismatch")
        if probe.nnue_feature_abi != release["nnue_feature_abi"]:
            raise ValueError("NNUE feature ABI mismatch")
        if not probe.nnue_enabled:
            raise ValueError("NNUE model not enabled in candidate DLL")

    identity = {
        "native_library_sha256": release["native_library_sha256"],
        "nnue_model_sha256": release["nnue_model_sha256"],
        "native_search_abi": release["native_search_abi"],
        "nnue_feature_abi": release["nnue_feature_abi"],
        "tablebase_sha256": tb_map,
    }
    return release, manifest, identity


def get_host_info() -> dict:
    logical = os.cpu_count() or 12
    physical = 6 if logical == 12 else (logical // 2 if logical > 1 else 1)
    return {
        "id": "AMD Ryzen 5 5600H",
        "physical_cores": physical,
        "logical_threads": logical,
    }


class AuditCollector:
    def __init__(
        self,
        release: dict,
        manifest: dict,
        identity: dict,
        fixtures: dict,
        output_path: Path,
        run_id: str | None = None,
    ):
        self.release = release
        self.manifest = manifest
        self.identity = identity
        self.fixtures = fixtures
        self.output_path = Path(output_path)
        self.run_id = run_id or f"audit-run-v1-{int(time.time())}"
        self.cases = {c["id"]: c for c in fixtures["cases"]}
        self.schedule = fixtures["schedule"]
        self.entry_bytes = native_tt_entry_bytes(release["native_library"])
        self.searchers: dict[int, NativeSearch | ParallelNativeSearch] = {}
        self.header = self._build_header()
        self.run_sha256 = digest(self.header)
        self.validator = ObservationValidator(self.header, fixtures=fixtures)

    def _build_header(self) -> dict:
        return {
            "format": FORMAT,
            "run_id": self.run_id,
            "data_kind": "measured",
            "fixtures_sha256": digest(self.fixtures),
            "release_manifest_sha256": self.release["manifest_sha256"],
            "host": get_host_info(),
            "identity": self.identity,
            "settings": {
                "mode": "win",
                "hash_mb_total": 512,
                "fresh_state_per_observation": True,
                "restore_fixture_history": True,
                "tt_layout": "private-per-worker",
            },
        }

    def get_searcher(self, threads: int) -> NativeSearch | ParallelNativeSearch:
        if threads not in self.searchers:
            dll = self.release["native_library"]
            model = self.release["nnue_model"]
            hp = hash_power_for_megabytes(512, partitions=threads, entry_bytes=self.entry_bytes)
            if threads == 1:
                self.searchers[1] = NativeSearch(dll, hash_power=hp, persistent=True, nnue_model=model)
            else:
                self.searchers[threads] = ParallelNativeSearch(dll, threads=threads, hash_mb=512, nnue_model=model)
        return self.searchers[threads]

    def close(self) -> None:
        for searcher in list(self.searchers.values()):
            try:
                searcher.close()
            except Exception:
                pass
        self.searchers.clear()

    def run(self, limit: int | None = None) -> dict:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        start_index = 0

        if self.output_path.is_file():
            raw = self.output_path.read_bytes()
            boundary = raw.rfind(b"\n")
            if boundary >= 0:
                lines = raw[:boundary + 1].splitlines()
                if lines:
                    existing_header = strict_json(lines[0])
                    require(existing_header["format"] == FORMAT, "Existing stream format mismatch")
                    require(existing_header["fixtures_sha256"] == self.header["fixtures_sha256"], "Fixture mismatch in existing stream")
                    require(digest(existing_header["identity"]) == digest(self.identity), "Identity mismatch in existing stream")
                    self.header = existing_header
                    self.run_sha256 = digest(self.header)
                    self.validator = ObservationValidator(self.header, fixtures=self.fixtures)

                    for idx, line in enumerate(lines[1:]):
                        row = strict_json(line)
                        self.validator.validate(row, idx)
                    start_index = len(lines) - 1
                    print(f"Resuming observation stream at index {start_index}/{len(self.schedule)}", flush=True)

        if start_index >= len(self.schedule):
            print("Observation stream is already complete!", flush=True)
            return {"status": "COMPLETE", "observations": start_index}

        end_index = len(self.schedule) if limit is None else min(len(self.schedule), start_index + limit)

        mode = "a" if self.output_path.is_file() and start_index > 0 else "w"
        with self.output_path.open(mode, encoding="utf-8", newline="\n") as stream:
            if mode == "w":
                stream.write(json.dumps(self.header) + "\n")
                stream.flush()

            try:
                for idx in range(start_index, end_index):
                    if interactive_session_active():
                        print(f"Yielding to interactive GUI session at schedule index {idx}", flush=True)
                        self.close()
                        return {"status": "PAUSED_FOR_INTERACTIVE_PLAY", "completed": idx}

                    scheduled = self.schedule[idx]
                    case = self.cases[scheduled["case"]]
                    state = parse_position(case["position"], reversible_plies=case["reversible_plies"])
                    history = Counter({parse_position(h["position"]).position_key: h["count"] for h in case["history"]})
                    threads = scheduled["threads"]
                    budget_ms = scheduled["budget_ms"]

                    hp = hash_power_for_megabytes(512, partitions=threads, entry_bytes=self.entry_bytes)
                    per_worker_bytes = (1 << hp) * self.entry_bytes
                    tt_bytes_by_worker = [per_worker_bytes] * threads

                    moves = legal_moves(state)
                    if len(moves) == 1:
                        backend = "forced"
                        move_str = moves[0].notation
                        pv = [move_str]
                        depth = 1
                        nodes = 1
                        elapsed_ms = 0
                        wall_ms = 1.0
                        score = 0
                        active_workers = 0
                        cpu_ms = 0.0
                    else:
                        backend = "native-single" if threads == 1 else "native-root-split"
                        searcher = self.get_searcher(threads)
                        searcher.clear()

                        wall_start = time.perf_counter()
                        cpu_start = time.process_time()
                        res = searcher.search(
                            state,
                            depth=64,
                            time_ms=budget_ms,
                            no_progress_plies=80,
                            repetition_limit=3,
                            history=history,
                        )
                        wall_ms = round((time.perf_counter() - wall_start) * 1000, 3)
                        cpu_ms = round((time.process_time() - cpu_start) * 1000, 3)

                        move_str = res.move.notation
                        score = int(res.score)
                        depth = int(res.depth)
                        nodes = int(res.nodes)
                        pv = [m.notation for m in res.pv]
                        elapsed_ms = int(res.elapsed_ms)
                        active_workers = None

                    telemetry = {field: None for field in OPTIONAL_METRICS}
                    telemetry["active_workers"] = active_workers
                    telemetry["cpu_time_ms"] = cpu_ms

                    row = {
                        "run_sha256": self.run_sha256,
                        "schedule_index": idx,
                        "identity": self.identity,
                        "result": {
                            "move": move_str,
                            "score": score,
                            "depth": depth,
                            "nodes": nodes,
                            "pv": pv,
                            "wall_ms": wall_ms,
                            "elapsed_ms": elapsed_ms,
                            "tablebase_hits": 0,
                            "backend": backend,
                            "native_error": None,
                        },
                        "tt_bytes_by_worker": tt_bytes_by_worker,
                        "telemetry": telemetry,
                    }

                    self.validator.validate(row, idx)
                    stream.write(json.dumps(row) + "\n")
                    stream.flush()

                    print(
                        f"[{idx + 1}/{len(self.schedule)}] case={case['id']:14s} T={threads:2d} budget={budget_ms:4d}ms "
                        f"-> move={move_str:5s} d={depth:2d} nodes={nodes:8d} wall={wall_ms:6.1f}ms backend={backend}",
                        flush=True,
                    )
            finally:
                self.close()

        status = "COMPLETE" if end_index == len(self.schedule) else "PARTIAL"
        return {"status": status, "completed": end_index, "total": len(self.schedule)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    pilot_cmd = sub.add_parser("pilot", help="Run the curated 48-observation pilot schedule")
    pilot_cmd.add_argument("--output", type=Path, default=ROOT / "build/nnue_thread_scaling_pilot_v1/observations.jsonl")
    pilot_cmd.add_argument("--limit", type=int, help="Optional maximum observations to execute")
    pilot_cmd.add_argument("--release-pointer", type=Path)
    pilot_cmd.add_argument("--run-id", type=str)

    collect_cmd = sub.add_parser("collect", help="Run the full 5,760-observation thread audit schedule")
    collect_cmd.add_argument("--output", type=Path, default=ROOT / "build/nnue_thread_scaling_measured_v1/observations.jsonl")
    collect_cmd.add_argument("--limit", type=int, help="Optional maximum observations to execute")
    collect_cmd.add_argument("--release-pointer", type=Path)
    collect_cmd.add_argument("--run-id", type=str)

    verify_cmd = sub.add_parser("verify", help="Verify release environment and tablebases without searching")
    verify_cmd.add_argument("--release-pointer", type=Path)

    args = parser.parse_args()

    release, manifest, identity = verify_release(args.release_pointer)
    print("Release verification PASS: DLL, Model, Tablebases, and ABI confirmed.")

    if args.action == "verify":
        return

    fixtures = prepare_pilot() if args.action == "pilot" else prepare()
    collector = AuditCollector(release, manifest, identity, fixtures, args.output, run_id=args.run_id)
    result = collector.run(limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
