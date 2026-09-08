"""Isolated TB4/repetition regression; does not build or change playing code.

Run from the repository: python -B work/endgame_diagnosis_20260908/reproduce.py
Exit 0 means every trial selects a verified three-ply winning move and denies
an immediate draw reply. No native search or tablebase builder is started.
"""
from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if sys.platform == "win32":
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x4000
    )  # BelowNormal; this diagnostic uses no native search or TB builders.

from makhos.core import (
    BLACK, DEFAULT_RULES, apply_move, format_position, legal_moves,
    parse_position, terminal_status,
)
from makhos.exact import Outcome
from makhos.ranked_tablebase import RankedTablebase
from makhos.search import Engine, Mode, SearchLimits
from makhos.server import parse_position_history

WINNING_MOVES = {"5-32", "6-10", "6-15", "6-19", "6-24"}


def named_move(state, notation):
    return next(move for move in legal_moves(state) if move.notation == notation)


def main():
    state = parse_position("B:BK1,5,9:RK32")
    positions = [format_position(state)]
    prefix = ["9-6", "32-28", "6-9", "28-32", "9-6", "32-28"]
    for notation in prefix:
        state = apply_move(state, named_move(state, notation))
        positions.append(format_position(state))
    history = parse_position_history({"history": positions}, state)
    assert not terminal_status(
        state, repetition_count=history[state.position_key]
    ).terminal

    # Verify a real winning alternative using only the immutable rules oracle.
    winning = state
    win_history = history.copy()
    winning_line = ["6-24", "28x19", "1x24"]
    for index, notation in enumerate(winning_line):
        moves = legal_moves(winning)
        if index > 0:
            assert len(moves) == 1, "winning continuation must be forced"
        winning = apply_move(winning, named_move(winning, notation))
        win_history[winning.position_key] += 1
        status = terminal_status(
            winning, repetition_count=win_history[winning.position_key]
        )
        assert not status.terminal or status.winner == BLACK
    assert status.terminal and status.winner == BLACK

    trials = []
    with RankedTablebase(ROOT / "build/tb4_np80.compact.bin") as tablebase:
        assert tablebase.probe(state).outcome == Outcome.WIN
        for mode, depth in ((Mode.BEST, 1), (Mode.BEST, 8),
                            (Mode.WIN, 1), (Mode.WIN, 8)):
            engine = Engine(rules=DEFAULT_RULES, ranked_tablebase=tablebase)
            result = engine.search(state, SearchLimits(depth=depth),
                                   history=history, mode=mode)
            child = apply_move(state, result.move)
            child_history = history.copy()
            child_history[child.position_key] += 1
            drawing_replies = []
            for reply in legal_moves(child):
                after = apply_move(child, reply)
                status = terminal_status(
                    after, repetition_count=child_history[after.position_key] + 1
                )
                if status.terminal and status.winner is None:
                    drawing_replies.append({"move": reply.notation,
                                            "reason": status.reason})
            trials.append({
                "mode": mode.value, "depth": depth, "selected": result.move.notation,
                "score": result.score, "backend": engine.last_search_backend,
                "tablebase_hits": result.tablebase_hits,
                "distance_budget": engine._distance.max_nodes,
                "drawing_replies": drawing_replies,
                "candidates": [{
                    "move": candidate.move.notation, "score": candidate.score,
                    "bound": [candidate.bound.lower.name, candidate.bound.upper.name],
                    "dtm": candidate.distance.dtm,
                    "distance_exact": candidate.distance.exact,
                } for candidate in result.candidates],
            })
    report = {
        "initial": positions[0], "legal_prefix": prefix,
        "root": format_position(state), "clock": state.reversible_plies,
        "rules": {"repetition_limit": DEFAULT_RULES.repetition_limit,
                  "no_progress_plies": DEFAULT_RULES.no_progress_plies},
        "history": positions, "root_tablebase": "WIN",
        "verified_forced_win": winning_line, "trials": trials,
        "bug_reproduced": any(trial["drawing_replies"] for trial in trials),
        "scope": "Real Engine and local TB4; no native DLL, model, TB3 builder, or live GUI",
    }
    print(json.dumps(report, indent=2))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for trial in trials:
        assert trial["selected"] in WINNING_MOVES, (
            f"{trial['mode']} depth {trial['depth']}: selected {trial['selected']}; "
            f"expected a verified winning move in {sorted(WINNING_MOVES)}"
        )
    assert not report["bug_reproduced"], (
        "A selected move allows an immediate draw despite the verified winning alternatives."
    )


if __name__ == "__main__":
    main()
