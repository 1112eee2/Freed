"""Offline validation/reporting for the prepared NNUE thread audit.

No DLL loading, native search, process inspection or promotion. The demo uses
fabricated observations to exercise the reporting contract, never engine data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
from itertools import chain
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from makhos.core import apply_move, legal_moves, parse_position, terminal_status
from makhos.nnue_features import FEATURE_SPEC_NAME
from work.prepare_nnue_thread_audit import prepare, digest

FORMAT = "thai-makhos-thread-observations-v1"
REPORT_FORMAT = "thai-makhos-thread-report-v1"
OPTIONAL_METRICS = (
    "active_workers", "qnodes", "coordinator_ms", "cpu_time_ms",
    "process_peak_rss_bytes", "nnue_ms", "movegen_ms", "tablebase_ms",
    "duplicate_nodes", "cpu_frequency_mhz", "temperature_c",
)
COUNT_METRICS = {"active_workers", "qnodes", "process_peak_rss_bytes", "duplicate_nodes"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, f"Invalid integer: {label}")
    return value


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"Invalid finite nonnegative number: {label}")
    return value


def checksum(value, label):
    require(isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdefABCDEF" for c in value), f"Invalid SHA-256: {label}")


def exact_keys(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys), f"Invalid fields: {label}")


def validate_header(header, fixtures):
    exact_keys(header, ("format", "run_id", "data_kind", "fixtures_sha256",
        "release_manifest_sha256", "host", "identity", "settings"), "header")
    require(header["format"] == FORMAT, "Unsupported observation format")
    require(isinstance(header["run_id"], str) and header["run_id"].strip(), "Missing run_id")
    require(header["data_kind"] in ("synthetic_fixture", "measured"), "Invalid data_kind")
    require(header["fixtures_sha256"] == digest(fixtures), "Fixture/schedule binding mismatch")
    checksum(header["release_manifest_sha256"], "release_manifest_sha256")
    exact_keys(header["host"], ("id", "physical_cores", "logical_threads"), "host")
    require(isinstance(header["host"]["id"], str) and header["host"]["id"].strip(), "Missing host id")
    physical = integer(header["host"]["physical_cores"], "physical_cores", 1)
    logical = integer(header["host"]["logical_threads"], "logical_threads", 1)
    require(physical <= logical, "Physical cores exceed logical threads")
    identity = header["identity"]
    exact_keys(identity, ("native_library_sha256", "nnue_model_sha256",
        "native_search_abi", "nnue_feature_abi", "tablebase_sha256"), "identity")
    for key in ("native_library_sha256", "nnue_model_sha256"):
        checksum(identity[key], key)
    integer(identity["native_search_abi"], "native_search_abi", 1)
    require(identity["nnue_feature_abi"] == FEATURE_SPEC_NAME, "NNUE feature ABI mismatch")
    exact_keys(identity["tablebase_sha256"], ("4", "5", "6"), "tablebase identities")
    for value in identity["tablebase_sha256"].values():
        checksum(value, "tablebase")
    require(digest(header["settings"]) == digest({"mode": "win", "hash_mb_total": 512,
        "fresh_state_per_observation": True, "restore_fixture_history": True,
        "tt_layout": "private-per-worker"}), "Unsupported or inconsistent audit settings")


class ObservationValidator:
    def __init__(self, header):
        # Reproduce the existing approved preparation; callers cannot silently
        # substitute a smaller/easier schedule or altered repetition history.
        self.fixtures = prepare()
        validate_header(header, self.fixtures)
        self.header = header
        self.run_sha256 = digest(header)
        self.cases = {case["id"]: case for case in self.fixtures["cases"]}
        self.schedule = self.fixtures["schedule"]
        self.root_states = {}
        self.root_moves = {}
        for case_id, case in self.cases.items():
            state = parse_position(case["position"], reversible_plies=case["reversible_plies"])
            self.root_states[case_id] = state
            self.root_moves[case_id] = {move.notation: move for move in legal_moves(state)}

    @lru_cache(maxsize=8192)
    def validate_pv(self, case_id, pv):
        state = self.root_states[case_id]
        history = Counter({parse_position(h["position"]).position_key: h["count"]
                           for h in self.cases[case_id]["history"]})
        for notation in pv:
            require(not terminal_status(state, repetition_count=history[state.position_key]).terminal,
                    "PV continues after a terminal position")
            moves = {move.notation: move for move in legal_moves(state)}
            require(notation in moves, "Illegal PV move")
            state = apply_move(state, moves[notation], validate=False)
            history[state.position_key] += 1

    def validate(self, row, expected_index):
        exact_keys(row, ("run_sha256", "schedule_index", "identity", "result",
                         "tt_bytes_by_worker", "telemetry"), "observation")
        require(row["run_sha256"] == self.run_sha256, "Mixed run/configuration binding")
        index = integer(row["schedule_index"], "schedule_index")
        require(index == expected_index and index < len(self.schedule),
                "Duplicate, missing, reordered or extra observation")
        require(digest(row["identity"]) == digest(self.header["identity"]), "Runtime identity drift")
        scheduled = self.schedule[index]
        case = self.cases[scheduled["case"]]
        result = row["result"]
        exact_keys(result, ("move", "score", "depth", "nodes", "pv", "wall_ms",
                           "elapsed_ms", "tablebase_hits", "backend", "native_error"), "result")
        require(result["native_error"] is None, "Native runtime error")
        expected_backend = "native-single" if scheduled["threads"] == 1 else "native-root-split"
        require(result["backend"] in (expected_backend, "forced"), "Backend fallback or drift")
        if result["backend"] == "forced":
            require(case["legal_moves"] == 1, "Forced backend with multiple legal moves")
        require(isinstance(result["move"], str) and result["move"] in self.root_moves[case["id"]],
                "Illegal selected move")
        pv = result["pv"]
        require(isinstance(pv, list) and pv and all(isinstance(m, str) for m in pv)
                and pv[0] == result["move"], "PV must start with the selected move")
        self.validate_pv(case["id"], tuple(pv))
        require(type(result["score"]) is int, "Invalid score")
        for field in ("depth", "nodes", "tablebase_hits"):
            integer(result[field], field)
        for field in ("wall_ms", "elapsed_ms"):
            number(result[field], field)
        allocations = row["tt_bytes_by_worker"]
        require(isinstance(allocations, list) and len(allocations) == scheduled["threads"],
                "Allocated worker count differs from requested Threads")
        for size in allocations:
            integer(size, "worker TT allocation", 1)
        require(sum(allocations) <= scheduled["hash_mb_total"] * 1024 * 1024,
                "Actual TT allocation exceeds the total Hash budget")
        telemetry = row["telemetry"]
        exact_keys(telemetry, OPTIONAL_METRICS, "telemetry (use null when unavailable)")
        for field, value in telemetry.items():
            if value is not None:
                (integer if field in COUNT_METRICS else number)(value, field)
        active = telemetry["active_workers"]
        if active is not None:
            require(active <= len(allocations), "Active workers exceed allocated workers")
            if result["backend"] == "forced":
                require(active == 0, "Forced return cannot report active search workers")
        return scheduled


def metric(values):
    values = [value for value in values if value is not None]
    ordered = sorted(values)
    return {"available": len(values), "median": statistics.median(values) if values else None,
            "p95": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None}


def case_category(case):
    if case["legal_moves"] == 1:
        return "forced"
    return "clock_edge" if case["id"].startswith("clock-edge-") else "playout"


def summarize(header, observations, *, trailing_partial_bytes=0):
    integer(trailing_partial_bytes, "trailing_partial_bytes")
    validator = ObservationValidator(header)
    groups, by_key, stability = defaultdict(list), {}, defaultdict(list)
    count = 0
    for count, row in enumerate(observations, start=1):
        scheduled = validator.validate(row, count - 1)
        case_id, threads, budget = scheduled["case"], scheduled["threads"], scheduled["budget_ms"]
        category = case_category(validator.cases[case_id])
        groups[(budget, threads, category)].append(row)
        by_key[(case_id, scheduled["repetition"], budget, threads)] = row
        stability[(case_id, budget, threads)].append(row["result"]["move"])
    complete = count == len(validator.schedule) and trailing_partial_bytes == 0
    rows = []
    for (budget, threads, category), observations in sorted(groups.items()):
        metrics = {field: metric(row["result"][field] for row in observations)
                   for field in ("depth", "nodes", "wall_ms", "elapsed_ms", "tablebase_hits")}
        metrics["overshoot_ms"] = metric(max(0, row["result"]["wall_ms"] - budget) for row in observations)
        metrics["allocated_tt_mb"] = metric(sum(row["tt_bytes_by_worker"]) / (1024 * 1024)
                                             for row in observations)
        metrics.update({field: metric(row["telemetry"][field] for row in observations)
                        for field in OPTIONAL_METRICS})
        rows.append({"budget_ms": budget, "threads": threads, "category": category,
                     "observations": len(observations), "metrics": metrics})
    comparisons, repeatability = [], []
    # Partial schedules have order/coverage bias. Do not select a configuration
    # or publish matched-comparison statistics until every scheduled row exists.
    if complete:
        paired = defaultdict(list)
        for (case_id, repetition, budget, threads), row in by_key.items():
            if threads == 1:
                continue
            base = by_key[(case_id, repetition, budget, 1)]
            category = case_category(validator.cases[case_id])
            paired[(budget, threads, category)].append((row["result"], base["result"]))
        for (budget, threads, category), pairs in sorted(paired.items()):
            comparisons.append({"budget_ms": budget, "threads": threads, "category": category,
                "matched_observations": len(pairs),
                "same_move": sum(a["move"] == b["move"] for a, b in pairs),
                "deeper_than_1t": sum(a["depth"] > b["depth"] for a, b in pairs),
                "shallower_than_1t": sum(a["depth"] < b["depth"] for a, b in pairs),
                "depth_delta_vs_1t": metric(a["depth"] - b["depth"] for a, b in pairs),
                "wall_delta_ms_vs_1t": metric(a["wall_ms"] - b["wall_ms"] for a, b in pairs)})
        repeat_groups = defaultdict(list)
        for (case_id, budget, threads), moves in stability.items():
            repeat_groups[(budget, threads, case_category(validator.cases[case_id]))].append(moves)
        for (budget, threads, category), lists in sorted(repeat_groups.items()):
            repeatability.append({"budget_ms": budget, "threads": threads, "category": category,
                "positions": len(lists), "all_repetitions_same_move": sum(len(set(m)) == 1 for m in lists),
                "modal_move_fraction": metric(max(Counter(m).values()) / len(m) for m in lists)})
    missing = {field: count - sum(group["metrics"][field]["available"] for group in rows)
               for field in OPTIONAL_METRICS}
    return {"format": REPORT_FORMAT, "data_kind": header["data_kind"], "run_id": header["run_id"],
        "run_sha256": validator.run_sha256, "status": "COMPLETE_DIAGNOSTIC" if complete else "INCOMPLETE_DIAGNOSTIC",
        "synthetic_warning": "FABRICATED TEST DATA; NOT ENGINE MEASUREMENTS" if header["data_kind"] == "synthetic_fixture" else None,
        "schedule_rows": len(validator.schedule), "valid_rows": count,
        "missing_rows": len(validator.schedule) - count, "trailing_partial_bytes": trailing_partial_bytes,
        "host": header["host"], "identity": header["identity"],
        "target_host_matches": (header["host"]["physical_cores"], header["host"]["logical_threads"]) == (6, 12),
        "summaries": rows, "comparisons_vs_1t": comparisons, "repeatability": repeatability,
        "missing_telemetry_rows": missing, "profile_coverage_complete": complete and not any(missing.values()),
        "strength_evidence": False, "recommended_threads": None, "production_promoted": False,
        "limitations": ["Input identities and metrics are recorded claims, not independently measured by this reader.",
            "Release manifest, workload isolation, and profiling provenance need host verification.",
            "Move agreement and deeper search do not establish the correct move or an Elo improvement.",
            "Unavailable telemetry is null, never zero; full profile completion is separate from schedule completion.",
            "Forced positions and synthetic clock edges are reported separately from the main playout positions."]}


def strict_json(encoded):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")
    return json.loads(encoded, object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def read_report(path):
    # Explicit offline input only. Never discover/open Gate C runtime paths.
    raw = Path(path).read_bytes()
    boundary = raw.rfind(b"\n")
    require(boundary >= 0, "Observation header is incomplete")
    lines = raw[:boundary + 1].splitlines()
    require(bool(lines) and all(line.strip() for line in lines), "Empty observation line")
    header = strict_json(lines[0])
    report = summarize(header, (strict_json(line) for line in lines[1:]),
                       trailing_partial_bytes=len(raw) - boundary - 1)
    report["input_sha256"] = hashlib.sha256(raw).hexdigest().upper()
    return report


def synthetic_header():
    return {"format": FORMAT, "run_id": "synthetic-report-contract-demo", "data_kind": "synthetic_fixture",
        "fixtures_sha256": digest(prepare()), "release_manifest_sha256": "0" * 64,
        "host": {"id": "FABRICATED_HOST", "physical_cores": 6, "logical_threads": 12},
        "identity": {"native_library_sha256": "1" * 64, "nnue_model_sha256": "2" * 64,
            "native_search_abi": 5, "nnue_feature_abi": FEATURE_SPEC_NAME,
            "tablebase_sha256": {str(n): str(n) * 64 for n in (4, 5, 6)}},
        "settings": {"mode": "win", "hash_mb_total": 512, "fresh_state_per_observation": True,
                     "restore_fixture_history": True, "tt_layout": "private-per-worker"}}


def synthetic_rows(header):
    require(header["data_kind"] == "synthetic_fixture", "Demo requires a synthetic header")
    validator = ObservationValidator(header)
    for index, scheduled in enumerate(validator.schedule):
        case = validator.cases[scheduled["case"]]
        forced = case["legal_moves"] == 1
        move = next(iter(validator.root_moves[case["id"]]))
        threads, budget = scheduled["threads"], scheduled["budget_ms"]
        yield {"run_sha256": validator.run_sha256, "schedule_index": index,
            "identity": header["identity"], "tt_bytes_by_worker": [40 * 1024 * 1024] * threads,
            "result": {"move": move, "score": 0, "depth": 0 if forced else 10,
                "nodes": 0 if forced else 1000 * threads, "pv": [move],
                "wall_ms": 1 if forced else budget + index % 17,
                "elapsed_ms": 1 if forced else budget, "tablebase_hits": 0,
                "backend": "forced" if forced else "native-single" if threads == 1 else "native-root-split",
                "native_error": None}, "telemetry": {field: None for field in OPTIONAL_METRICS}}


def write_new_json(path, payload):
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    demo = sub.add_parser("demo", help="Generate fabricated observations; performs no search")
    demo.add_argument("--output-dir", type=Path, required=True)
    report = sub.add_parser("summarize", help="Read a stopped/copied observation stream")
    report.add_argument("--input", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "demo":
        args.output_dir.mkdir(parents=True, exist_ok=False)
        header = synthetic_header()
        source = args.output_dir / "synthetic_observations.jsonl"
        with source.open("x", encoding="utf-8", newline="\n") as stream:
            for row in chain((header,), synthetic_rows(header)):
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        output = args.output_dir / "synthetic_report.json"
    else:
        source, output = args.input, args.output
    result = read_report(source)
    write_new_json(output, result)
    print(json.dumps({"output": str(output), "status": result["status"], "data_kind": result["data_kind"],
                      "valid_rows": result["valid_rows"], "strength_evidence": False}))


if __name__ == "__main__":
    main()
