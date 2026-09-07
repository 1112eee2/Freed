"""Exact WDL solver for small Thai-Makhos positions.

The solver uses the explicit no-progress counter to make the game graph finite.
It intentionally requires repetition adjudication to be disabled: repetition is
history-dependent, while a reusable tablebase key contains only the board, side
to move, and no-progress counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .core import Rules, State, apply_move, legal_moves


class Outcome(IntEnum):
    LOSS = -1
    DRAW = 0
    WIN = 1


@dataclass(frozen=True, slots=True)
class ExactResult:
    outcome: Outcome
    distance: int | None
    states: int
    best_moves: tuple


class StateLimitExceeded(RuntimeError):
    pass


class ExactSolver:
    """Memoized, exhaustive solver suitable for low-material positions.

    WIN distance is the shortest forced win; LOSS distance is the longest the
    losing side can resist. DRAW has no distance. No heuristic evaluation or
    unsafe pruning is used.
    """

    def __init__(self, rules: Rules, *, max_states: int = 1_000_000) -> None:
        if rules.repetition_limit is not None:
            raise ValueError(
                "exact tablebase states cannot encode repetition history; "
                "use Rules(repetition_limit=None, ...)"
            )
        if max_states < 1:
            raise ValueError("max_states must be positive")
        self.rules = rules
        self.max_states = max_states
        self._memo: dict[tuple, tuple[Outcome, int | None, tuple]] = {}
        self._visiting: set[tuple] = set()

    @staticmethod
    def _key(state: State) -> tuple:
        return state.board, state.turn, state.reversible_plies

    def solve(self, state: State) -> ExactResult:
        outcome, distance, best_moves = self._solve(state)
        return ExactResult(outcome, distance, len(self._memo), best_moves)

    def clear(self) -> None:
        self._memo.clear()
        self._visiting.clear()

    @property
    def state_count(self) -> int:
        return len(self._memo)

    def _solve(self, state: State) -> tuple[Outcome, int | None, tuple]:
        key = self._key(state)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        if len(self._memo) + len(self._visiting) >= self.max_states:
            raise StateLimitExceeded(
                f"exact solve exceeded the configured limit of {self.max_states:,} states"
            )
        if key in self._visiting:
            # With a finite no-progress counter, captures/removals and promotions
            # are irreversible, so a repeated full key indicates an implementation
            # error rather than a legitimate game cycle.
            raise RuntimeError("cycle detected in supposedly finite exact state graph")

        if state.reversible_plies >= self.rules.no_progress_plies:
            result = (Outcome.DRAW, None, ())
            self._memo[key] = result
            return result

        moves = legal_moves(state)
        if not moves:
            result = (Outcome.LOSS, 0, ())
            self._memo[key] = result
            return result

        self._visiting.add(key)
        children: list[tuple[object, Outcome, int | None]] = []
        try:
            for move in moves:
                child = apply_move(state, move, validate=False)
                child_outcome, child_distance, _ = self._solve(child)
                children.append((move, child_outcome, child_distance))
        finally:
            self._visiting.remove(key)

        losing_children = [item for item in children if item[1] == Outcome.LOSS]
        if losing_children:
            min_distance = min(int(item[2]) for item in losing_children)
            best = tuple(item[0] for item in losing_children if item[2] == min_distance)
            result = (Outcome.WIN, min_distance + 1, best)
        else:
            drawing_children = [item for item in children if item[1] == Outcome.DRAW]
            if drawing_children:
                result = (Outcome.DRAW, None, tuple(item[0] for item in drawing_children))
            else:
                max_distance = max(int(item[2]) for item in children)
                best = tuple(item[0] for item in children if item[2] == max_distance)
                result = (Outcome.LOSS, max_distance + 1, best)

        self._memo[key] = result
        return result
