"""Prepare reproducible positions/schedule only; never load/search a DLL.

The profile executor and promotion binding are deliberately not authorized by
these fixtures. They are groundwork while the frozen Gate C arena is running.
"""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from makhos.core import (BLACK, RED, BLACK_KING, RED_KING, format_position, legal_moves, parse_position,
                         terminal_status)
from makhos.native_benchmark import generate_native_benchmark_cases
from scratch.nnue_quiet_leaf_acquire import write_locked_json

SEED = 20261107
THREADS = (1, 2, 4, 6, 8, 12)
BUDGETS = (1000, 2000)
REPETITIONS = 5
OUTPUT = ROOT / "build/nnue_thread_scaling_preparation_v2"


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def encode_case(case_id, state, history, source):
    moves = legal_moves(state)
    if terminal_status(state, repetition_count=history[state.position_key]).terminal:
        raise ValueError("Terminal position cannot enter a search audit")
    histories = []
    for (board, turn), count in sorted(history.items()):
        historical = replace(state, board=board, turn=turn)
        histories.append({"position": format_position(historical), "count": count})
    return {"id": case_id, "position": format_position(state),
            "reversible_plies": state.reversible_plies, "ply": state.ply,
            "history": histories, "source": source, "turn": state.turn,
            "pieces": sum(piece != 0 for piece in state.board),
            "kings": sum(piece in (BLACK_KING, RED_KING) for piece in state.board),
            "legal_moves": len(moves), "capture": any(move.is_capture for move in moves),
            "multi_capture": any(len(move.captures) > 1 for move in moves),
            "expected_best_move": None, "label_semantics": "unlabelled diagnostic position"}


def prepare_cases():
    cases = []
    for case in generate_native_benchmark_cases(count=80, seed=SEED,
            ply_schedule=(4, 9, 14, 19, 25, 31, 39, 48)):
        cases.append(encode_case(f"playout-{case.index:03}", case.state,
            case.history, "independent rules-only playout; full repetition history"))
    # Explicit runtime edge strata, not sampled game evidence or teacher labels.
    for index, clock in enumerate((0, 10, 39, 60, 69, 70, 78, 79)):
        for turn in (BLACK, RED):
            state = parse_position(f"{'B' if turn == BLACK else 'R'}:BK{25 + index}:RK{1 + index}",
                                   reversible_plies=clock)
            cases.append(encode_case(f"clock-edge-{index}-{turn}", state,
                Counter({state.position_key: 1}), "synthetic two-king clock edge; history reset explicitly"))
    keys = {(case["position"], case["reversible_plies"]) for case in cases}
    if len(keys) != len(cases) or len(cases) != 96:
        raise ValueError("Duplicate/insufficient audit positions")
    if not any(case["multi_capture"] for case in cases):
        raise ValueError("Missing mandatory multi-capture coverage")
    if not any(case["pieces"] >= 13 for case in cases):
        raise ValueError("Missing early-game coverage")
    return cases


def prepare_schedule(cases):
    rng = random.Random(SEED)
    schedule = []
    for repetition in range(REPETITIONS):
        indices = list(range(len(cases)))
        rng.shuffle(indices)
        for index in indices:
            start = (index + repetition) % len(THREADS)
            order = THREADS[start:] + THREADS[:start]
            budgets = BUDGETS if (index + repetition) % 2 == 0 else BUDGETS[::-1]
            for budget in budgets:
                for threads in order:
                    schedule.append({"case": cases[index]["id"], "repetition": repetition,
                                     "budget_ms": budget, "threads": threads, "hash_mb_total": 512})
    return schedule


def prepare():
    cases = prepare_cases()
    schedule = prepare_schedule(cases)
    coverage = {"positions": len(cases), "with_kings": sum(bool(c["kings"]) for c in cases),
                "captures": sum(c["capture"] for c in cases),
                "multi_captures": sum(c["multi_capture"] for c in cases),
                "turns": dict(Counter(c["turn"] for c in cases)),
                "piece_counts": dict(Counter(c["pieces"] for c in cases)),
                "clock_edge_cases": 16}
    return {"format": "thai-makhos-thread-audit-preparation-v1", "seed": SEED,
            "status": "FIXTURES_ONLY_NOT_PROFILED", "native_search_authorized": False,
            "requires": ["both Gate C controls PASS", "verified production release/rollback",
                         "profile executor correctness and isolation gates", "frozen release/model binding"],
            "threads": THREADS, "budgets_ms": BUDGETS, "repetitions": REPETITIONS,
            "hash_mb_total": 512, "coverage": coverage, "cases": cases,
            "cases_sha256": digest(cases), "schedule": schedule, "schedule_sha256": digest(schedule),
            "external_diagnostics": "separate appendix; not included in these 96 cases or selection labels",
            "runtime_protocol": "fresh native state/clear before each observation; restore recorded repetition history",
            "metrics_pending_executor": ["requested/effective hash and workers", "completed depth/move/score/PV",
                "nodes/qnodes/elapsed/overshoot", "worker/coordinator/TT telemetry", "NNUE/update features cost",
                "CPU/RAM/available clock-temperature readings"],
            "strength_evidence": False}


if __name__ == "__main__":
    output = OUTPUT / "fixtures_and_schedule.json"
    payload = prepare()
    write_locked_json(output, payload)
    print(json.dumps({"output": str(output), "coverage": payload["coverage"],
        "searches_scheduled_not_run": len(payload["schedule"]), "cases_sha256": payload["cases_sha256"],
        "schedule_sha256": payload["schedule_sha256"], "native_search_authorized": False}, sort_keys=True))
