"""Source-isolated multi-process arena for Thai Makhos engine evaluation.

Coordinates matches between two distinct git trees/commits (e.g. ba9481d Control
vs main Candidate) running in isolated subprocesses with isolated PYTHONPATHs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import (
    BLACK,
    RED,
    DEFAULT_RULES,
    State,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    parse_position,
    terminal_status,
)

DEFAULT_CONTROL_PATH = r"D:\ThaiMakhosEngine_control"
DEFAULT_CANDIDATE_PATH = r"D:\ThaiMakhosEngine"
DEFAULT_TB4_PATH = str(ROOT / "build" / "tb4_np80.compact.bin")
DEFAULT_TB3_PATH = str(ROOT / "build" / "makhos_native_accepted.dll")
WORKER_SCRIPT = str(ROOT / "work" / "endgame_worker.py")
PILOT_OUT = str(ROOT / "work" / "endgame_diagnosis_20260908" / "arena_pilot_result.json")

REPRODUCER_POS = "B:BK1,5,6:RK28"
REPRODUCER_HISTORY = {
    "B:BK1,5,9:RK32": 2,
    "R:BK1,5,6:RK32": 2,
    "B:BK1,5,6:RK28": 2,
    "R:BK1,5,9:RK28": 1,
}
WINNING_CANDIDATE_MOVES = {"5-32", "6-10", "6-15", "6-19", "6-24"}


class IsolatedEngineClient:
    """Controls a single engine running inside an isolated worker subprocess."""

    def __init__(
        self,
        name: str,
        repo_path: str,
        tb4_path: str = DEFAULT_TB4_PATH,
        tb3_path: str | None = DEFAULT_TB3_PATH,
        *,
        engine_type: str = "python",
        threads: int = 1,
        hash_mb: int = 64,
        nnue_model: str | None = None,
    ) -> None:
        self.name = name
        self.repo_path = repo_path
        cmd = [
            sys.executable,
            WORKER_SCRIPT,
            "--repo-path", repo_path,
            "--tb4-path", tb4_path,
            "--engine-type", engine_type,
            "--threads", str(threads),
            "--hash-mb", str(hash_mb),
        ]
        if tb3_path and os.path.isfile(tb3_path):
            cmd.extend(["--tb3-path", tb3_path])
        if nnue_model and os.path.isfile(nnue_model):
            cmd.extend(["--nnue-model", nnue_model])
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        line = self.proc.stdout.readline()
        self.ready_info = json.loads(line)
        if self.ready_info.get("status") != "ready":
            raise RuntimeError(f"Engine {name} failed to initialize: {line}")

    def reset(self) -> None:
        self.proc.stdin.write(json.dumps({"command": "reset"}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        res = json.loads(line)
        if res.get("status") != "ok":
            raise RuntimeError(f"Engine {self.name} reset failed: {line}")

    def search(
        self,
        state: State,
        history_by_str: dict[str, int],
        *,
        mode: str = "BEST",
        time_ms: int | None = None,
        depth: int = 6,
    ) -> dict:
        req = {
            "command": "search",
            "position": format_position(state),
            "reversible_plies": state.reversible_plies,
            "clock": state.reversible_plies,
            "ply": state.ply,
            "mode": mode,
            "time_ms": time_ms,
            "depth": depth,
            "history": history_by_str,
        }
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        res = json.loads(line)
        if res.get("status") == "error":
            raise RuntimeError(f"Engine {self.name} search error: {res.get('error')}")
        return res

    def close(self) -> None:
        try:
            self.proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass
        self.proc.terminate()
        self.proc.wait()


def play_game(
    black_player: IsolatedEngineClient,
    red_player: IsolatedEngineClient,
    initial_state: State,
    initial_history: dict[str, int] | None = None,
    *,
    mode: str = "BEST",
    time_ms: int | None = 1000,
    depth: int = 32,
    max_plies: int = 200,
) -> dict:
    black_player.reset()
    red_player.reset()

    state = initial_state
    history = Counter(initial_history or {})
    pos_str = format_position(state)
    history[pos_str] = max(1, history[pos_str])
    moves_record = []
    
    status = terminal_status(state, repetition_count=history[pos_str], rules=DEFAULT_RULES)
    while not status.terminal and len(moves_record) < max_plies:
        current_client = black_player if state.turn == BLACK else red_player
        res = current_client.search(state, dict(history), mode=mode, time_ms=time_ms, depth=depth)
        move_notation = res.get("move")
        if not move_notation:
            break
            
        # Find matching legal move
        matched_move = None
        for move in legal_moves(state):
            if move.notation == move_notation:
                matched_move = move
                break
        if matched_move is None:
            raise RuntimeError(f"Engine {current_client.name} played illegal move {move_notation}")
            
        moves_record.append({
            "ply": len(moves_record) + 1,
            "turn": "BLACK" if state.turn == BLACK else "RED",
            "player": current_client.name,
            "move": move_notation,
            "score": res.get("score"),
            "depth": res.get("depth"),
            "elapsed_ms": res.get("elapsed_ms"),
        })
        
        state = apply_move(state, matched_move, validate=False)
        pos_str = format_position(state)
        history[pos_str] += 1
        status = terminal_status(state, repetition_count=history[pos_str], rules=DEFAULT_RULES)

    if not status.terminal:
        raise RuntimeError(
            f"Game aborted without terminal outcome after {len(moves_record)} plies (reason: {status.reason})"
        )

    winner_name = None
    if status.winner == BLACK:
        winner_name = black_player.name
    elif status.winner == RED:
        winner_name = red_player.name
    else:
        winner_name = "DRAW"

    return {
        "black": black_player.name,
        "red": red_player.name,
        "terminal": status.terminal,
        "winner": winner_name,
        "reason": status.reason,
        "plies": len(moves_record),
        "moves": moves_record,
    }


def play_pair(
    candidate: IsolatedEngineClient,
    control: IsolatedEngineClient,
    state: State,
    history: dict[str, int] | None = None,
    *,
    mode: str = "BEST",
    time_ms: int | None = 1000,
    depth: int = 32,
) -> dict:
    """Play a paired match (alternating colors) from the same initial state."""
    # Game 1: Candidate is BLACK, Control is RED
    g1 = play_game(
        black_player=candidate,
        red_player=control,
        initial_state=state,
        initial_history=history,
        mode=mode,
        time_ms=time_ms,
        depth=depth,
    )
    # Game 2: Control is BLACK, Candidate is RED
    g2 = play_game(
        black_player=control,
        red_player=candidate,
        initial_state=state,
        initial_history=history,
        mode=mode,
        time_ms=time_ms,
        depth=depth,
    )
    
    # Outcomes from Candidate perspective: 'W', 'D', 'L'
    res1 = 'W' if g1['winner'] == 'Candidate' else ('L' if g1['winner'] == 'Control' else 'D')
    res2 = 'W' if g2['winner'] == 'Candidate' else ('L' if g2['winner'] == 'Control' else 'D')
    
    pair_code = res1 + res2
    # Pentanomial classification:
    # 'WW' -> +2 (score 2.0)
    # 'WD' / 'DW' -> +1 (score 1.5)
    # 'DD' / 'WL' / 'LW' -> 0 (score 1.0)
    # 'LD' / 'DL' -> -1 (score 0.5)
    # 'LL' -> -2 (score 0.0)
    if pair_code == "WW":
        p_class = "WW"
        pts = 2.0
    elif pair_code in ("WD", "DW"):
        p_class = "WD"
        pts = 1.5
    elif pair_code in ("DD", "WL", "LW"):
        p_class = "DD"
        pts = 1.0
    elif pair_code in ("LD", "DL"):
        p_class = "LD"
        pts = 0.5
    else:
        p_class = "LL"
        pts = 0.0
        
    return {
        "game1": g1,
        "game2": g2,
        "pair_code": pair_code,
        "pentanomial_class": p_class,
        "candidate_points": pts,
    }


def run_pilot():
    print("=== Running Arena Pilot Verification on Endgame Repetition Bug ===")
    print(f"Control Repo:   {DEFAULT_CONTROL_PATH}")
    print(f"Candidate Repo: {DEFAULT_CANDIDATE_PATH}")
    print(f"Position:       {REPRODUCER_POS}")
    
    control = IsolatedEngineClient("Control", DEFAULT_CONTROL_PATH)
    candidate = IsolatedEngineClient("Candidate", DEFAULT_CANDIDATE_PATH)
    
    state = parse_position(REPRODUCER_POS, reversible_plies=6)
    
    # Game 1: Candidate as Black vs Control as Red
    print("\n--- Pilot Game 1: Candidate (BLACK) vs Control (RED) ---")
    g1 = play_game(
        black_player=candidate,
        red_player=control,
        initial_state=state,
        initial_history=REPRODUCER_HISTORY,
        mode="WIN",
        time_ms=1000,
        depth=16,
    )
    first_cand_move = g1["moves"][0]["move"] if g1["moves"] else None
    print(f"Candidate Black Move: {first_cand_move}")
    print(f"Winner: {g1['winner']} (reason: {g1['reason']}, plies: {g1['plies']})")
    
    # Assertions for Game 1
    assert first_cand_move in WINNING_CANDIDATE_MOVES, (
        f"Candidate chose {first_cand_move}, expected one of {WINNING_CANDIDATE_MOVES}"
    )
    assert first_cand_move != "6-9", "Candidate chose 6-9 which allows repetition draw!"
    assert g1["winner"] == "Candidate", f"Candidate should win Game 1, got {g1['winner']}"

    # Game 2: Control as Black vs Candidate as Red
    print("\n--- Pilot Game 2: Control (BLACK) vs Candidate (RED) ---")
    g2 = play_game(
        black_player=control,
        red_player=candidate,
        initial_state=state,
        initial_history=REPRODUCER_HISTORY,
        mode="WIN",
        time_ms=1000,
        depth=16,
    )
    first_ctrl_move = g2["moves"][0]["move"] if g2["moves"] else None
    print(f"Control Black Move: {first_ctrl_move}")
    print(f"Winner: {g2['winner']} (reason: {g2['reason']}, plies: {g2['plies']})")

    # Assertions for Game 2
    assert first_ctrl_move == "6-9", (
        f"Control should repeat the bug move 6-9, got {first_ctrl_move}"
    )
    assert g2["winner"] == "DRAW", f"Control Black should end in DRAW, got {g2['winner']}"
    assert "repetition" in str(g2["reason"]).lower(), (
        f"Game 2 should terminate due to repetition, got {g2['reason']}"
    )

    control.close()
    candidate.close()

    pilot_result = {
        "status": "PASS",
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "control_commit": "ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5",
        "candidate_commit": "main",
        "position": REPRODUCER_POS,
        "game1_candidate_black": {
            "first_move": first_cand_move,
            "winner": g1["winner"],
            "reason": g1["reason"],
            "plies": g1["plies"],
            "moves_sequence": [m["move"] for m in g1["moves"]],
        },
        "game2_control_black": {
            "first_move": first_ctrl_move,
            "winner": g2["winner"],
            "reason": g2["reason"],
            "plies": g2["plies"],
            "moves_sequence": [m["move"] for m in g2["moves"]],
        },
        "verdict": (
            "PASS: Candidate avoids 6-9 repetition threat and wins with Black (played "
            f"{first_cand_move}); Control plays 6-9 and is held to a 3-fold repetition DRAW."
        ),
    }

    with open(PILOT_OUT, "w", encoding="utf-8") as f:
        json.dump(pilot_result, f, indent=2)
    print(f"\nPilot verification results saved to: {PILOT_OUT}")
    print(f"Verdict: {pilot_result['verdict']}")
    return pilot_result


def main():
    parser = argparse.ArgumentParser(description="Source-isolated multi-process arena")
    parser.add_argument("--pilot", action="store_true", help="Run reproducer pilot verification")
    parser.add_argument("--pairs", type=int, default=0, help="Run N pairs of games")
    parser.add_argument("--time-ms", type=int, default=1000, help="Movetime limit per search (ms)")
    parser.add_argument("--mode", choices=["BEST", "WIN"], default="BEST", help="Engine search mode")
    args = parser.parse_args()
    
    if args.pairs > 0:
        print(f"=== Running {args.pairs} pairs in Source-Isolated Arena ===")
        control = IsolatedEngineClient("Control", DEFAULT_CONTROL_PATH)
        candidate = IsolatedEngineClient("Candidate", DEFAULT_CANDIDATE_PATH)
        penta_counts = Counter()
        total_pts = 0.0
        
        positions = [
            parse_position(REPRODUCER_POS),
            parse_position("B:BK6,15:RK28"),
            parse_position("B:BK1,5,10:RK24"),
            parse_position("B:BK6,15:RK24,28"),
            parse_position("B:BM12:BK5,9:RM21:RK28"),
        ]
        
        for p_idx in range(args.pairs):
            pos = positions[p_idx % len(positions)]
            pair = play_pair(candidate, control, pos, mode=args.mode, time_ms=args.time_ms)
            penta_counts[pair["pentanomial_class"]] += 1
            total_pts += pair["candidate_points"]
            print(f"Pair {p_idx+1}/{args.pairs}: {pair['pair_code']} ({pair['pentanomial_class']}) - Cand pts: {pair['candidate_points']:.1f}/2.0")

        control.close()
        candidate.close()
        print("\n=== Pentanomial Summary ===")
        print(f"Counts: WW={penta_counts['WW']}, WD={penta_counts['WD']}, DD={penta_counts['DD']}, LD={penta_counts['LD']}, LL={penta_counts['LL']}")
        print(f"Candidate Score: {total_pts} / {args.pairs * 2.0} ({(total_pts / (args.pairs * 2.0))*100:.1f}%)")
    else:
        run_pilot()

if __name__ == "__main__":
    main()
