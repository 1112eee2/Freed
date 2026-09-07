"""Exhaustive verification helpers for exact endgames."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    Rules,
    State,
    index_to_coord,
)
from .exact import ExactSolver, Outcome


@dataclass(frozen=True, slots=True)
class EndgameVerification:
    positions: int
    wins: int
    draws: int
    losses: int
    solved_states: int
    elapsed_ms: int


def verify_one_vs_one(
    *,
    no_progress_plies: int = 80,
    max_states: int = 2_000_000,
) -> EndgameVerification:
    """Classify every legal one-piece-vs-one-piece placement at clock zero."""

    rules = Rules(repetition_limit=None, no_progress_plies=no_progress_plies)
    solver = ExactSolver(rules, max_states=max_states)
    counts: Counter[Outcome] = Counter()
    positions = 0
    start = time.perf_counter()

    for black_piece in (BLACK_MAN, BLACK_KING):
        for red_piece in (RED_MAN, RED_KING):
            for black_square in range(32):
                black_row, _ = index_to_coord(black_square)
                if black_piece == BLACK_MAN and black_row == 0:
                    continue
                for red_square in range(32):
                    if black_square == red_square:
                        continue
                    red_row, _ = index_to_coord(red_square)
                    if red_piece == RED_MAN and red_row == 7:
                        continue
                    board = [EMPTY] * 32
                    board[black_square] = black_piece
                    board[red_square] = red_piece
                    for turn in (BLACK, RED):
                        result = solver.solve(State(tuple(board), turn))
                        counts[result.outcome] += 1
                        positions += 1

    elapsed_ms = round((time.perf_counter() - start) * 1000)
    return EndgameVerification(
        positions=positions,
        wins=counts[Outcome.WIN],
        draws=counts[Outcome.DRAW],
        losses=counts[Outcome.LOSS],
        solved_states=solver.state_count,
        elapsed_ms=elapsed_ms,
    )
