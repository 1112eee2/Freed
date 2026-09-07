"""Exact-on-success DTM/DTR probes layered on WDL endgame oracles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .core import EMPTY, Move, Rules, State, apply_move, legal_moves
from .exact import ExactSolver, Outcome, StateLimitExceeded
from .native_tablebase import NativeProbe, NativeTablebase
from .ranked_tablebase import RankedTablebase


@dataclass(frozen=True, slots=True)
class EndgameDistance:
    """Distance attached to a root move, measured in plies.

    DTM is shortest forced mate for a win and longest resistance for a loss.
    DTR is minimax distance to the next capture/promotion reset (or the
    no-progress terminal) while both sides preserve an exact draw.
    """

    outcome: Outcome | None = None
    dtm: int | None = None
    dtr: int | None = None
    exact: bool = False

    @classmethod
    def unknown(cls) -> "EndgameDistance":
        return cls()


class DistanceBudgetExceeded(RuntimeError):
    pass


class DistanceOracle:
    """Derive distances without weakening the WDL oracle.

    Three-piece/native and Python exact probes return DTM directly.  Ranked
    four/five-piece files contain WDL only, so distance is derived on demand by
    following only WDL-preserving edges.  A value is returned only if the whole
    required minimax subgraph fits the configured budget.
    """

    def __init__(
        self,
        rules: Rules,
        *,
        native: NativeTablebase | None = None,
        ranked_tablebases: Iterable[RankedTablebase] = (),
        exact_solver: ExactSolver | None = None,
        exact_piece_limit: int = 0,
        max_nodes: int = 0,
    ) -> None:
        if rules.repetition_limit is not None:
            raise ValueError("distance oracle requires history-free no-progress rules")
        if max_nodes < 0:
            raise ValueError("distance max_nodes cannot be negative")
        if (
            native is not None and
            getattr(native, "no_progress_plies", None) != rules.no_progress_plies
        ):
            raise ValueError("distance/native tablebase no-progress mismatch")
        tablebases = tuple(ranked_tablebases)
        if any(
            tablebase.no_progress_plies != rules.no_progress_plies
            for tablebase in tablebases
        ):
            raise ValueError("distance/ranked tablebase no-progress mismatch")
        if len({tablebase.piece_count for tablebase in tablebases}) != len(tablebases):
            raise ValueError("duplicate ranked distance tablebase")
        self.rules = rules
        self.native = native
        self.ranked = {tablebase.piece_count: tablebase for tablebase in tablebases}
        self.exact_solver = exact_solver
        self.exact_piece_limit = exact_piece_limit
        self.max_nodes = max_nodes
        self._nodes = 0
        self._dtm_cache: dict[tuple, int] = {}
        self._dtr_cache: dict[tuple, int] = {}

    @staticmethod
    def _key(state: State) -> tuple:
        return state.board, state.turn, state.reversible_plies

    @staticmethod
    def _piece_count(state: State) -> int:
        return sum(piece != EMPTY for piece in state.board)

    def _tick(self) -> None:
        self._nodes += 1
        if self._nodes > self.max_nodes:
            raise DistanceBudgetExceeded

    def probe(self, state: State) -> NativeProbe | None:
        if state.reversible_plies >= self.rules.no_progress_plies:
            return NativeProbe(Outcome.DRAW, None)
        moves = legal_moves(state)
        if not moves:
            return NativeProbe(Outcome.LOSS, 0)
        pieces = self._piece_count(state)
        ranked = self.ranked.get(pieces)
        if ranked is not None:
            return ranked.probe(state)
        if self.native is not None and 1 <= pieces <= self.native.max_pieces:
            return self.native.probe(state)
        if (
            self.exact_solver is not None
            and self.exact_piece_limit > 0
            and pieces <= self.exact_piece_limit
        ):
            try:
                solved = self.exact_solver.solve(state)
            except (StateLimitExceeded, RecursionError):
                return None
            return NativeProbe(solved.outcome, solved.distance)
        return None

    def for_move(self, state: State, move: Move) -> EndgameDistance:
        """Return an exact distance for this move, or an explicit unknown."""

        child = apply_move(state, move, validate=False)
        child_probe = self.probe(child)
        if child_probe is None:
            return EndgameDistance.unknown()
        outcome = Outcome(-child_probe.outcome)
        self._nodes = 0
        try:
            if outcome in (Outcome.WIN, Outcome.LOSS):
                child_distance = child_probe.distance
                if child_distance is None:
                    child_distance = self._dtm(child)
                if child_distance is None:
                    return EndgameDistance(outcome=outcome)
                return EndgameDistance(outcome, dtm=child_distance + 1, exact=True)
            # The fallback Python solver proves draw WDL but intentionally does
            # not store a DTR metric.  Avoid rebuilding that full graph merely
            # for a root preference unless a persistent endgame oracle is open.
            if self.native is None and not self.ranked:
                return EndgameDistance(outcome=outcome)
            if move.is_capture or move.promotes:
                return EndgameDistance(outcome, dtr=1, exact=True)
            child_distance = self._dtr(child, state.turn)
            return EndgameDistance(outcome, dtr=child_distance + 1, exact=True)
        except (DistanceBudgetExceeded, RecursionError):
            return EndgameDistance(outcome=outcome)

    def _dtm(self, state: State) -> int | None:
        key = self._key(state)
        cached = self._dtm_cache.get(key)
        if cached is not None:
            return cached
        self._tick()
        result = self.probe(state)
        if result is None or result.outcome == Outcome.DRAW:
            return None
        if result.distance is not None:
            self._dtm_cache[key] = result.distance
            return result.distance

        distances: list[int] = []
        for move in legal_moves(state):
            child = apply_move(state, move, validate=False)
            child_result = self.probe(child)
            if child_result is None:
                return None
            if child_result.outcome != Outcome(-result.outcome):
                if result.outcome == Outcome.LOSS:
                    return None
                continue
            distance = child_result.distance
            if distance is None:
                distance = self._dtm(child)
            if distance is None:
                return None
            distances.append(distance + 1)
        if not distances:
            return None
        distance = min(distances) if result.outcome == Outcome.WIN else max(distances)
        self._dtm_cache[key] = distance
        return distance

    def _dtr(self, state: State, target_player: int) -> int:
        key = (self._key(state), target_player)
        cached = self._dtr_cache.get(key)
        if cached is not None:
            return cached
        self._tick()
        result = self.probe(state)
        if result is None or result.outcome != Outcome.DRAW:
            raise DistanceBudgetExceeded
        if state.reversible_plies >= self.rules.no_progress_plies:
            self._dtr_cache[key] = 0
            return 0

        distances: list[int] = []
        for move in legal_moves(state):
            child = apply_move(state, move, validate=False)
            child_result = self.probe(child)
            if child_result is None:
                raise DistanceBudgetExceeded
            if child_result.outcome != Outcome.DRAW:
                continue
            if move.is_capture or move.promotes:
                distances.append(1)
            else:
                distances.append(self._dtr(child, target_player) + 1)
        if not distances:
            # A no-move terminal is already handled by probe as LOSS, so this
            # means some dependency was unavailable rather than a proven DTR.
            raise DistanceBudgetExceeded
        distance = min(distances) if state.turn == target_player else max(distances)
        self._dtr_cache[key] = distance
        return distance
