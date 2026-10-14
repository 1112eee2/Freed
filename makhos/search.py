"""Correctness-first alpha-beta search and root policies."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
import math
import time
from typing import Callable, Iterable, Mapping

from .eval import evaluate_handcrafted
from .exact import ExactSolver, Outcome, StateLimitExceeded
from .distance import DistanceOracle, EndgameDistance
from .native_tablebase import NativeTablebase
from .native import NativeSearch, NativeSearchResult
from .policy_value import EmpiricalPolicyValueModel, PolicyValueEstimate, PolicyValueModel
from .proof import MappedProofStrategy, ProofStrategy
from .ranked_tablebase import RankedTablebase
from .root_policy import choose_root

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    DEFAULT_RULES,
    EMPTY,
    Move,
    RED,
    RED_KING,
    RED_MAN,
    Rules,
    State,
    apply_move,
    index_to_coord,
    legal_moves,
    opponent,
    piece_player,
    terminal_status,
)

INFINITY = 2_000_000
MATE_SCORE = 1_000_000


class TTFlag(int, Enum):
    EXACT = 1
    BETA = 2   # Lowerbound (score >= beta)
    ALPHA = 3  # Upperbound (score <= alpha)


@dataclass(slots=True)
class TTEntry:
    key: tuple[tuple[int, ...], int]
    depth: int
    score: int
    flag: TTFlag
    best_move: Move | None = None


class Mode(str, Enum):
    BEST = "best"
    WIN = "win"


@dataclass(frozen=True, slots=True)
class WDLBound:
    """Conservative interval for the game result from side-to-move's view."""

    lower: Outcome
    upper: Outcome

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("WDL lower bound cannot exceed upper bound")

    @classmethod
    def exact(cls, outcome: Outcome) -> "WDLBound":
        return cls(outcome, outcome)

    @property
    def exact_outcome(self) -> Outcome | None:
        return self.lower if self.lower == self.upper else None

    @property
    def text(self) -> str:
        """Provenance form: the exact outcome, UNKNOWN, or LOWER..UPPER."""
        exact = self.exact_outcome
        if exact is not None:
            return exact.name
        if self.lower == Outcome.LOSS and self.upper == Outcome.WIN:
            return "UNKNOWN"
        return f"{self.lower.name}..{self.upper.name}"


UNKNOWN_WDL = WDLBound(Outcome.LOSS, Outcome.WIN)


@dataclass(frozen=True, slots=True)
class SearchLimits:
    depth: int = 6
    time_ms: int | None = None
    # WIN mode never crosses this many evaluation points below the best search
    # score.  Zero is the safety-first default.
    win_margin: int = 0

    def __post_init__(self) -> None:
        if self.depth < 1:
            raise ValueError("depth must be at least 1")
        if self.time_ms is not None and self.time_ms < 1:
            raise ValueError("time_ms must be positive")
        if self.win_margin < 0:
            raise ValueError("win_margin cannot be negative")


class TimeManager:
    """Dynamic clock allocation for tournament and time-controlled play."""

    @staticmethod
    def allocate_time(
        my_time_ms: int,
        opp_time_ms: int = 0,
        my_inc_ms: int = 0,
        opp_inc_ms: int = 0,
        moves_to_go: int | None = None,
    ) -> int:
        if my_time_ms <= 0:
            return 100

        target_moves = moves_to_go if (moves_to_go and moves_to_go > 0) else 25
        base_alloc = (my_time_ms / max(target_moves, 15)) + (my_inc_ms * 0.75)

        # Safety caps: don't use more than 40% of remaining time or time minus buffer
        max_allowed = min(my_time_ms * 0.4, max(50.0, my_time_ms - 200.0))
        allocated = int(min(base_alloc, max_allowed))
        return max(50, allocated)


@dataclass(frozen=True, slots=True)
class RootCandidate:
    move: Move
    score: int
    pv: tuple[Move, ...]
    pressure: float
    bound: WDLBound
    policy_value: PolicyValueEstimate = PolicyValueEstimate.neutral()
    distance: EndgameDistance = EndgameDistance.unknown()


@dataclass(frozen=True, slots=True)
class SearchResult:
    move: Move
    score: int
    depth: int
    nodes: int
    elapsed_ms: int
    pv: tuple[Move, ...]
    mode: Mode
    candidates: tuple[RootCandidate, ...]
    tablebase_hits: int
    bound: WDLBound
    policy_value: PolicyValueEstimate
    distance: EndgameDistance
    proof_strategy_used: bool = False
    proof_safe_moves: tuple[Move, ...] = ()
    common_depth: int | None = None
    selective_root: bool = False


class SearchTimeout(RuntimeError):
    pass


def evaluate(state: State, perspective: int) -> int:
    """Rich handcrafted evaluation function in centipawn units."""
    return evaluate_handcrafted(state, perspective)



def _match_legal(moves: Iterable[Move], move: Move) -> Move | None:
    """The legal move with the same path and captures as ``move``, if any."""

    for candidate in moves:
        if candidate.path == move.path and candidate.captures == move.captures:
            return candidate
    return None


class Engine:
    """One search core with two root move-selection policies.

    Both modes preserve the strongest conservative WDL tier. BEST then chooses
    the highest minimax score. WIN preserves that score (or a caller-configured
    margin), closes exact endgames by DTM, and uses learned win probability plus
    DTR/human pressure only inside the remaining safety envelope. Neither mode
    changes move legality or the alpha-beta opponent model.
    """

    def __init__(
        self,
        rules: Rules = DEFAULT_RULES,
        *,
        exact_piece_limit: int = 2,
        exact_max_states: int = 250_000,
        native_tablebase: NativeTablebase | None = None,
        ranked_tablebase: RankedTablebase | None = None,
        ranked_tablebases: Iterable[RankedTablebase] = (),
        policy_value_model: PolicyValueModel | None = None,
        distance_max_nodes: int = 0,
        proof_strategy: ProofStrategy | MappedProofStrategy | None = None,
        enable_single_move_pruning: bool = True,
        eval_fn: Callable[[State, int], int] | None = None,
        native_search: NativeSearch | None = None,
        native_endgame_search: object | None = None,
        native_endgame_enabled: bool = False,
        enable_native_endgame: bool | None = None,
        native_endgame: bool | None = None,
        reference_search: bool = False,
    ) -> None:
        if exact_piece_limit < 0:
            raise ValueError("exact_piece_limit cannot be negative")
        self.rules = rules
        # C2 differential configuration: no selective search or scalar TT.
        # Production remains unchanged unless explicitly requested.
        self.reference_search = reference_search
        self.enable_single_move_pruning = enable_single_move_pruning and not reference_search
        self.eval_fn = eval_fn or evaluate_handcrafted
        self.native_search = native_search
        aliases = [flag for flag in (enable_native_endgame, native_endgame) if flag is not None]
        if aliases and any(bool(flag) != bool(aliases[0]) for flag in aliases):
            raise ValueError("conflicting native endgame capability flags")
        if aliases:
            if native_endgame_enabled and bool(aliases[0]) != bool(native_endgame_enabled):
                raise ValueError("conflicting native endgame capability flags")
            native_endgame_enabled = bool(aliases[0])
        self.native_endgame_search = native_endgame_search
        self.native_endgame_enabled = bool(native_endgame_enabled)
        # Server-owned candidate resources are attached after TB3 warm-up.
        # Keeping these slots on every Engine makes cleanup and provenance
        # deterministic for both real and test backends.
        self.native_endgame_tablebase = None
        self.native_endgame_library = None
        self.native_endgame_evaluator = None
        self._native_eval_compatible = eval_fn is None
        self.last_native_error: str | None = None
        # Counts native PV tails cut at an illegal move (diagnostic only).
        self.native_pv_truncations = 0
        # Exposed to the GUI so exported games identify the backend that
        # actually produced each move, including forced-move and Python
        # fallback paths.  A configured native DLL alone is not proof that a
        # particular search result came from it.
        self.last_search_backend = "unsearched"
        if (
            native_tablebase is not None and
            native_tablebase.no_progress_plies != rules.no_progress_plies
        ):
            raise ValueError("native tablebase no-progress rule mismatch")
        if (
            proof_strategy is not None and
            proof_strategy.no_progress_plies != rules.no_progress_plies
        ):
            raise ValueError("proof strategy no-progress rule mismatch")
        self.proof_strategy = proof_strategy
        self.exact_piece_limit = exact_piece_limit
        self.native_tablebase = native_tablebase
        ranked = list(ranked_tablebases)
        if ranked_tablebase is not None:
            ranked.append(ranked_tablebase)
        self.ranked_tablebases: dict[int, RankedTablebase] = {}
        for tablebase in ranked:
            if tablebase.no_progress_plies != rules.no_progress_plies:
                raise ValueError("ranked tablebase no-progress rule mismatch")
            if tablebase.piece_count in self.ranked_tablebases:
                raise ValueError(
                    f"duplicate {tablebase.piece_count}-piece ranked tablebase"
                )
            self.ranked_tablebases[tablebase.piece_count] = tablebase
        # Retained for callers that inspect the original single-tablebase slot.
        self.ranked_tablebase = ranked_tablebase
        self.policy_value_model = policy_value_model or EmpiricalPolicyValueModel()
        exact_rules = Rules(
            name=rules.name + "-no-repetition-tablebase",
            starting_player=rules.starting_player,
            repetition_limit=None,
            no_progress_plies=rules.no_progress_plies,
        )
        self._exact = ExactSolver(exact_rules, max_states=exact_max_states)
        self._distance = DistanceOracle(
            exact_rules,
            native=native_tablebase,
            ranked_tablebases=self.ranked_tablebases.values(),
            exact_solver=self._exact,
            exact_piece_limit=exact_piece_limit,
            max_nodes=distance_max_nodes,
        )
        self._exact_failed: set[tuple] = set()
        self.nodes = 0
        self.tablebase_hits = 0
        self._deadline: float | None = None
        self._move_hints: dict[tuple[tuple[int, ...], int], Move] = {}
        self._tt: dict[tuple[tuple[int, ...], int], TTEntry] = {}
        self._killer_moves: dict[int, list[Move]] = {}
        self._history_scores: dict[tuple[int, Move], int] = {}

    def clear(self) -> None:
        """Clear transposition table, heuristics, and diagnostics at game boundary."""
        if self.native_search is not None:
            self.native_search.clear()
        if self.native_endgame_search is not None:
            clear = getattr(self.native_endgame_search, "clear", None)
            if clear is not None:
                clear()
        self._tt.clear()
        self._move_hints.clear()
        self._exact_failed.clear()
        self._killer_moves.clear()
        self._history_scores.clear()
        self._deadline = None
        if hasattr(self, "_distance") and self._distance is not None:
            self._distance._dtm_cache.clear()
            self._distance._dtr_cache.clear()
            self._distance._nodes = 0
        self.nodes = 0
        self.tablebase_hits = 0
        self.last_native_error = None
        self.last_search_backend = "unsearched"

    def search(
        self,
        state: State,
        limits: SearchLimits = SearchLimits(),
        *,
        mode: Mode | str = Mode.BEST,
        history: Mapping[tuple[tuple[int, ...], int], int] | None = None,
    ) -> SearchResult:
        mode = Mode(mode)
        self.last_native_error = None
        self.last_search_backend = "python"
        start = time.perf_counter()
        self._deadline = (
            None if limits.time_ms is None else start + limits.time_ms / 1000.0
        )
        self.nodes = 0
        self.tablebase_hits = 0
        counts = Counter(history or {})
        counts[state.position_key] = max(1, counts[state.position_key])

        root_status = terminal_status(
            state,
            repetition_count=counts[state.position_key],
            rules=self.rules,
        )
        if root_status.terminal:
            raise ValueError("cannot search a terminal position")
        root_moves = legal_moves(state)
        proof_strategy_used = False
        strategy_moves: tuple[Move, ...] = ()
        if (
            self.proof_strategy is not None and
            state.turn == self.proof_strategy.root_player
        ):
            strategy_moves = self.proof_strategy.moves_for(state)
            proof_strategy_used = True
            if not strategy_moves:
                raise ValueError("verified proof strategy returned no safe moves")
            if (
                len(set(strategy_moves)) != len(strategy_moves) or
                any(move not in root_moves for move in strategy_moves)
            ):
                raise ValueError("verified proof strategy returned invalid moves")
            root_moves = strategy_moves

        # C3 is an explicit capability gate.  It runs before the forced-move
        # shortcut so a transition root still gets a native proof layer, while
        # the resulting roots are handed back to the unchanged Python policy.
        if self._can_use_native_endgame(
            state,
            proof_strategy_used=proof_strategy_used,
        ):
            try:
                native_result = self.native_endgame_search.search(
                    state,
                    depth=limits.depth,
                    time_ms=0 if limits.time_ms is None else limits.time_ms,
                    rules=self.rules,
                    history=counts,
                )
                return self._native_endgame_result(
                    state,
                    root_moves,
                    native_result,
                    mode,
                    limits,
                    start,
                )
            except (OSError, RuntimeError, ValueError) as error:
                # Candidate DLLs are isolated from production.  A failed or
                # unavailable C3 run falls back to the verified Python path;
                # the error remains visible to GUI provenance.
                self.last_native_error = str(error)
                self.last_search_backend = "python-fallback"

        if len(root_moves) == 1 and not proof_strategy_used and self.enable_single_move_pruning:
            self.last_search_backend = "forced"
            single_move = root_moves[0]
            child = apply_move(state, single_move, validate=False)
            status = terminal_status(
                child,
                repetition_count=counts[child.position_key],
                rules=self.rules,
            )
            if status.terminal:
                if status.winner == state.turn:
                    bound = WDLBound.exact(Outcome.WIN)
                    score = MATE_SCORE
                elif status.winner is not None:
                    bound = WDLBound.exact(Outcome.LOSS)
                    score = -MATE_SCORE
                else:
                    bound = WDLBound.exact(Outcome.DRAW)
                    score = 0
            else:
                bound = UNKNOWN_WDL
                score = evaluate(child, state.turn)

            single_candidate = RootCandidate(
                single_move,
                score,
                (single_move,),
                0.0,
                bound,
                1.0,
            )
            return SearchResult(
                single_move,
                score,
                1,
                1,
                0,
                (single_move,),
                mode,
                (single_candidate,),
                0,
                bound,
                1.0,
                0.0,
                False,
                (),
            )

        if self._can_use_native_search(
            state,
            proof_strategy_used=proof_strategy_used,
        ):
            try:
                native_result = self.native_search.search(
                    state,
                    depth=limits.depth,
                    time_ms=limits.time_ms,
                    no_progress_plies=self.rules.no_progress_plies,
                    repetition_limit=self.rules.repetition_limit,
                    history=counts,
                )
                return self._native_result(
                    state,
                    root_moves,
                    native_result,
                    mode,
                    limits,
                    start,
                )
            except (OSError, RuntimeError, ValueError) as error:
                # A missing/stale DLL must not make the reference engine
                # unusable.  Keep the error visible for diagnostics and fall
                # back to the fully verified Python search.
                self.last_native_error = str(error)
                self.last_search_backend = "python-fallback"

        completed: tuple[RootCandidate, ...] | None = None
        completed_depth = 0
        for depth in range(1, limits.depth + 1):
            try:
                candidates = self._search_root(state, root_moves, depth, counts)
            except SearchTimeout:
                break
            completed = candidates
            completed_depth = depth
            root_moves = tuple(candidate.move for candidate in sorted(
                candidates, key=lambda item: item.score, reverse=True
            ))

        if completed is None:
            # Extremely small time limits still return a deterministic legal move.
            fallback = root_moves[0]
            child = apply_move(state, fallback, validate=False)
            completed = (
                RootCandidate(
                    fallback,
                    evaluate(child, state.turn),
                    (fallback,),
                    0.0,
                    UNKNOWN_WDL,
                    self.policy_value_model.predict(state, root_moves)[fallback],
                ),
            )

        if strategy_moves:
            upgraded: list[RootCandidate] = []
            for candidate in completed:
                lower = max(candidate.bound.lower, Outcome.DRAW)
                upper = max(candidate.bound.upper, Outcome.DRAW)
                candidate = replace(
                    candidate,
                    bound=WDLBound(lower, upper),
                )
                upgraded.append(candidate)
            completed = tuple(upgraded)
        completed = self._attach_distances(
            state,
            completed,
            mode,
            limits.win_margin,
            proof_guided=proof_strategy_used,
        )
        chosen = self._choose(
            completed,
            mode,
            limits.win_margin,
            proof_guided=proof_strategy_used,
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return SearchResult(
            chosen.move,
            chosen.score,
            completed_depth,
            self.nodes,
            elapsed_ms,
            chosen.pv,
            mode,
            tuple(sorted(completed, key=lambda item: (-item.score, item.move.notation))),
            self.tablebase_hits,
            chosen.bound,
            chosen.policy_value,
            chosen.distance,
            proof_strategy_used,
            strategy_moves,
        )

    def _can_use_native_search(
        self,
        state: State,
        *,
        proof_strategy_used: bool,
    ) -> bool:
        if (
            self.reference_search or
            self.native_search is None or
            not self._native_eval_compatible or
            proof_strategy_used
        ):
            return False
        # Exact endgames remain on the tablebase-aware Python path.  The
        # native core takes over the large search tree where speed matters.
        exact_limit = max(
            self.exact_piece_limit,
            self.native_tablebase.max_pieces if self.native_tablebase is not None else 0,
            max(self.ranked_tablebases, default=0),
        )
        return sum(piece != EMPTY for piece in state.board) > exact_limit

    def _native_result(
        self,
        state: State,
        root_moves: tuple[Move, ...],
        native: NativeSearchResult,
        mode: Mode,
        limits: SearchLimits,
        start: float,
    ) -> SearchResult:
        # Moves are identified by path and captures.  The native `promotes`
        # flag is not part of a move's identity: a stale transposition-table
        # move can carry it for a king, which must not discard a good search.
        root_move = _match_legal(root_moves, native.move)
        if root_move is None:
            raise RuntimeError("native search returned an illegal root move")
        # The PV tail is read back from the transposition table and may hold a
        # move from a colliding entry.  Keep the legal prefix instead of
        # throwing the whole result away (the old behaviour played a depth-0
        # first-legal move from the Python fallback).
        pv: list[Move] = []
        pv_state = state
        for move in native.pv:
            legal = _match_legal(legal_moves(pv_state), move)
            if legal is None:
                self.native_pv_truncations += 1
                break
            pv.append(legal)
            pv_state = apply_move(pv_state, legal, validate=False)
        if not pv or pv[0] != root_move:
            pv = [root_move]
        native = replace(native, move=root_move, pv=tuple(pv))
        predictions = self.policy_value_model.predict(state, (native.move,))
        candidate = RootCandidate(
            move=native.move,
            score=native.score,
            pv=native.pv,
            pressure=self._human_pressure(
                apply_move(state, native.move, validate=False), state.turn
            ),
            bound=UNKNOWN_WDL,
            policy_value=predictions[native.move],
        )
        candidates = self._attach_distances(
            state,
            (candidate,),
            mode,
            limits.win_margin,
        )
        chosen = candidates[0]
        self.last_search_backend = "native"
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        self.nodes = native.nodes
        self.tablebase_hits = 0
        self.last_native_error = None
        return SearchResult(
            chosen.move,
            chosen.score,
            native.depth,
            native.nodes,
            elapsed_ms,
            chosen.pv,
            mode,
            candidates,
            0,
            chosen.bound,
            chosen.policy_value,
            chosen.distance,
            common_depth=(
                native.common_depth
                if native.common_depth is not None
                else native.depth
            ),
            selective_root=native.selective_root,
        )

    def _can_use_native_endgame(
        self,
        state: State,
        *,
        proof_strategy_used: bool,
    ) -> bool:
        """Check the additive C3 capability without touching normal roots."""
        if (
            self.reference_search
            or not self.native_endgame_enabled
            or self.native_endgame_search is None
            or proof_strategy_used
            or (len(legal_moves(state)) == 1 and self.enable_single_move_pruning)
        ):
            return False
        if (
            getattr(self.native_search, "nnue_enabled", False)
            and getattr(self.native_endgame_search, "evaluator", "hce") != "nnue"
        ):
            # Never silently downgrade a production NNUE profile to an HCE
            # endgame candidate.  The caller can inspect this diagnostic and
            # decide whether to keep the Python fallback or disable C3.
            self.last_native_error = (
                "NNUE production profile requires an NNUE native endgame candidate"
            )
            return False
        supports = getattr(self.native_endgame_search, "supports_position", None)
        if callable(supports):
            try:
                return bool(supports(state))
            except (OSError, RuntimeError, ValueError) as error:
                self.last_native_error = str(error)
                return False
        # Small fake/adaptor backends used by integrations may expose only
        # search().  Keep their fallback gate bounded to the documented C3
        # endgame boundary and never inspect a normal midgame tree.
        return sum(piece != EMPTY for piece in state.board) <= 6

    def _native_endgame_result(
        self,
        state: State,
        root_moves: tuple[Move, ...],
        native,
        mode: Mode,
        limits: SearchLimits,
        start: float,
    ) -> SearchResult:
        if getattr(native, "terminal_reason", 0):
            raise RuntimeError("native endgame returned a terminal root")
        if getattr(native, "status", 0) not in (0, 2):
            raise RuntimeError("native endgame returned an invalid status")
        if getattr(native, "depth", 0) < 1 or not getattr(native, "roots", ()):
            raise RuntimeError("native endgame returned no completed root layer")

        # Validate the native PV before allowing it into the GUI or policy.
        legal_root_moves = set(root_moves)
        for root in native.roots:
            if not root.pv or root.pv[0] not in legal_root_moves:
                raise RuntimeError("native endgame returned an illegal root move")
            cursor = state
            for move in root.pv:
                if move not in legal_moves(cursor):
                    raise RuntimeError("native endgame returned an illegal PV")
                cursor = apply_move(cursor, move, validate=False)

        convert = getattr(native, "candidates", None)
        if not callable(convert):
            raise RuntimeError("native endgame result has no root-policy adapter")
        candidates = tuple(convert(self, state, mode, limits.win_margin))
        if not candidates:
            raise RuntimeError("native endgame result has no candidates")
        chosen = self._choose(candidates, mode, limits.win_margin)
        self.last_search_backend = "native-endgame"
        self.last_native_error = None
        self.nodes = int(getattr(native, "nodes", 0))
        self.tablebase_hits = sum(getattr(native, "tb_hits", ()))
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return SearchResult(
            chosen.move,
            chosen.score,
            int(native.depth),
            self.nodes,
            elapsed_ms,
            chosen.pv,
            mode,
            tuple(sorted(candidates, key=lambda item: (-item.score, item.move.notation))),
            self.tablebase_hits,
            chosen.bound,
            chosen.policy_value,
            chosen.distance,
            False,
            (),
            common_depth=int(native.depth),
            selective_root=False,
        )

    def _check_time(self) -> None:
        if self._deadline is not None and (self.nodes & 63) == 0:
            if time.perf_counter() >= self._deadline:
                raise SearchTimeout

    def _search_root(
        self,
        state: State,
        moves: Iterable[Move],
        depth: int,
        counts: Counter,
    ) -> tuple[RootCandidate, ...]:
        moves = tuple(moves)
        predictions = self.policy_value_model.predict(state, moves)
        candidates: list[RootCandidate] = []
        for move in self._order_moves(state, moves):
            self._check_time()
            child = apply_move(state, move, validate=False)
            counts[child.position_key] += 1
            try:
                score, child_pv, child_bound = self._negamax(
                    child, depth - 1, -INFINITY, INFINITY, counts, ply_from_root=1
                )
            finally:
                counts[child.position_key] -= 1
            score = -score
            pressure = self._human_pressure(child, state.turn)
            candidates.append(
                RootCandidate(
                    move,
                    score,
                    (move,) + child_pv,
                    pressure,
                    self._invert_bound(child_bound),
                    predictions[move],
                )
            )

        best = max(candidates, key=lambda item: (item.score, item.move.notation))
        self._move_hints[state.position_key] = best.move
        return tuple(candidates)

    def _attach_distances(
        self,
        state: State,
        candidates: tuple[RootCandidate, ...],
        mode: Mode,
        win_margin: int,
        *,
        proof_guided: bool = False,
    ) -> tuple[RootCandidate, ...]:
        """Probe distances once, and only for final WDL/score-eligible moves."""

        best_rank = max(self._safety_rank(candidate.bound) for candidate in candidates)
        ranked = [
            candidate for candidate in candidates
            if self._safety_rank(candidate.bound) == best_rank
        ]
        best_score = max(candidate.score for candidate in ranked)
        if mode == Mode.WIN and proof_guided:
            eligible = {candidate.move for candidate in ranked}
        else:
            score_floor = best_score if mode == Mode.BEST else best_score - win_margin
            eligible = {
                candidate.move
                for candidate in ranked
                if candidate.score >= score_floor
            }
        return tuple(
            replace(candidate, distance=self._distance.for_move(state, candidate.move))
            if candidate.move in eligible else candidate
            for candidate in candidates
        )

    def _negamax(
        self,
        state: State,
        depth: int,
        alpha: int,
        beta: int,
        counts: Counter,
        *,
        ply_from_root: int,
    ) -> tuple[int, tuple[Move, ...], WDLBound]:
        self.nodes += 1
        self._check_time()

        status = terminal_status(
            state, repetition_count=counts[state.position_key], rules=self.rules
        )
        if status.terminal:
            if status.winner is None:
                return 0, (), WDLBound.exact(Outcome.DRAW)
            return -MATE_SCORE + ply_from_root, (), WDLBound.exact(Outcome.LOSS)

        moves = legal_moves(state)
        exact_bound = UNKNOWN_WDL
        exact_value = self._probe_exact(state)
        if exact_value is not None:
            exact_score, exact_bound = exact_value
            if exact_bound.exact_outcome is not None:
                return exact_score, (), exact_bound
            # History-free WDL only constrains a repetition-aware search.
            # A WIN/LOSS may become a draw after the opponent's next move.
            if exact_bound.lower == Outcome.DRAW:
                alpha = max(alpha, 0)
            if exact_bound.upper == Outcome.DRAW:
                beta = min(beta, 0)
            if alpha >= beta:
                score = alpha if exact_bound.lower == Outcome.DRAW else beta
                return score, (), exact_bound
        if depth <= 0:
            return self._quiescence(state, alpha, beta, counts, ply_from_root, moves)

        # Transposition Table Probe
        tt_entry = self._tt.get(state.position_key)
        in_repetition_endgame = (
            self.rules.repetition_limit is not None
            and (
                counts[state.position_key] > 1
                or sum(piece != EMPTY for piece in state.board) <= max(
                    self.exact_piece_limit,
                    self.native_tablebase.max_pieces if self.native_tablebase is not None else 0,
                    max(self.ranked_tablebases, default=0),
                )
            )
        )
        if (
            tt_entry is not None
            and not self.reference_search
            and not in_repetition_endgame
            and tt_entry.depth >= depth
            and counts[state.position_key] <= 1
            and state.reversible_plies + depth < self.rules.no_progress_plies
        ):
            score = tt_entry.score
            if score >= MATE_SCORE - 1000:
                score -= ply_from_root
            elif score <= -MATE_SCORE + 1000:
                score += ply_from_root

            tt_move_tuple = (tt_entry.best_move,) if tt_entry.best_move else ()
            if tt_entry.flag == TTFlag.EXACT:
                return score, tt_move_tuple, UNKNOWN_WDL
            if tt_entry.flag == TTFlag.BETA and score >= beta:
                return score, tt_move_tuple, UNKNOWN_WDL
            if tt_entry.flag == TTFlag.ALPHA and score <= alpha:
                return score, tt_move_tuple, UNKNOWN_WDL

        # Null Move Pruning (NMP)
        if (
            not self.reference_search
            and depth >= 3
            and ply_from_root > 0
            and not moves[0].is_capture
            and sum(p != EMPTY for p in state.board) > 6
        ):
            reduction = 3 if depth >= 6 else 2
            null_state = State(
                state.board,
                opponent(state.turn),
                state.reversible_plies + 1,
                state.ply + 1,
            )
            null_score, _, _ = self._negamax(
                null_state,
                depth - 1 - reduction,
                -beta,
                -beta + 1,
                counts,
                ply_from_root=ply_from_root + 1,
            )
            null_score = -null_score
            if null_score >= beta:
                return beta, (), UNKNOWN_WDL

        original_alpha = alpha
        best_score = -INFINITY
        best_pv: tuple[Move, ...] = ()
        move_bounds: list[WDLBound] = []
        complete = True
        ordered_moves = self._order_moves(state, moves, ply=ply_from_root)

        for idx, move in enumerate(ordered_moves):
            child = apply_move(state, move, validate=False)
            counts[child.position_key] += 1
            try:
                if idx == 0:
                    score, child_pv, child_bound = self._negamax(
                        child,
                        depth - 1,
                        -beta,
                        -alpha,
                        counts,
                        ply_from_root=ply_from_root + 1,
                    )
                    score = -score
                else:
                    is_quiet = not move.is_capture and not move.promotes
                    if not self.reference_search and is_quiet and idx >= 3 and depth >= 3:
                        red = 1 + (1 if idx >= 6 else 0)
                        score, child_pv, child_bound = self._negamax(
                            child,
                            depth - 1 - red,
                            -alpha - 1,
                            -alpha,
                            counts,
                            ply_from_root=ply_from_root + 1,
                        )
                        score = -score
                        if score > alpha:
                            score, child_pv, child_bound = self._negamax(
                                child,
                                depth - 1,
                                -beta,
                                -alpha,
                                counts,
                                ply_from_root=ply_from_root + 1,
                            )
                            score = -score
                    else:
                        score, child_pv, child_bound = self._negamax(
                            child,
                            depth - 1,
                            -alpha - 1,
                            -alpha,
                            counts,
                            ply_from_root=ply_from_root + 1,
                        )
                        score = -score
                        if alpha < score < beta:
                            score, child_pv, child_bound = self._negamax(
                                child,
                                depth - 1,
                                -beta,
                                -alpha,
                                counts,
                                ply_from_root=ply_from_root + 1,
                            )
                            score = -score
            finally:
                counts[child.position_key] -= 1
            move_bounds.append(self._invert_bound(child_bound))

            if score > best_score:
                best_score = score
                best_pv = (move,) + child_pv
            if score > alpha:
                alpha = score
            if alpha >= beta:
                complete = False
                self._add_killer(ply_from_root, move)
                self._add_history(state.turn, move, depth)
                break

        if best_pv:
            self._move_hints[state.position_key] = best_pv[0]

        if exact_bound.lower == Outcome.DRAW:
            best_score = max(best_score, 0)
        if exact_bound.upper == Outcome.DRAW:
            best_score = min(best_score, 0)
        if best_score >= beta:
            flag = TTFlag.BETA
        elif best_score > original_alpha:
            flag = TTFlag.EXACT
        else:
            flag = TTFlag.ALPHA

        if not self.reference_search:
            self._tt[state.position_key] = TTEntry(
                key=state.position_key,
                depth=depth,
                score=best_score,
                flag=flag,
                best_move=best_pv[0] if best_pv else None,
            )

        return best_score, best_pv, self._combine_bounds(move_bounds, complete, exact_bound)

    def _probe_exact(self, state: State) -> tuple[int, WDLBound] | None:
        piece_count = sum(piece != EMPTY for piece in state.board)
        ranked = self.ranked_tablebases.get(piece_count)
        if ranked is not None:
            result = ranked.probe(state)
            self.tablebase_hits += 1
            if result.outcome == Outcome.DRAW:
                return 0, self._tablebase_bound(Outcome.DRAW)
            if result.outcome == Outcome.WIN:
                return MATE_SCORE, self._tablebase_bound(Outcome.WIN)
            return -MATE_SCORE, self._tablebase_bound(Outcome.LOSS)
        if self.native_tablebase is not None and piece_count <= self.native_tablebase.max_pieces:
            result = self.native_tablebase.probe(state)
            self.tablebase_hits += 1
            if result.outcome == Outcome.DRAW:
                return 0, self._tablebase_bound(Outcome.DRAW)
            distance = result.distance or 0
            if result.outcome == Outcome.WIN:
                return MATE_SCORE - distance, self._tablebase_bound(Outcome.WIN)
            return -MATE_SCORE + distance, self._tablebase_bound(Outcome.LOSS)
        if self.exact_piece_limit == 0:
            return None
        if piece_count > self.exact_piece_limit:
            return None
        key = (state.board, state.turn, state.reversible_plies)
        if key in self._exact_failed:
            return None
        try:
            result = self._exact.solve(state)
        except (StateLimitExceeded, RecursionError):
            self._exact_failed.add(key)
            return None
        self.tablebase_hits += 1
        if result.outcome == Outcome.DRAW:
            return 0, self._tablebase_bound(Outcome.DRAW)
        distance = result.distance or 0
        if result.outcome == Outcome.WIN:
            return MATE_SCORE - distance, self._tablebase_bound(Outcome.WIN)
        return -MATE_SCORE + distance, self._tablebase_bound(Outcome.LOSS)

    def _tablebase_bound(self, outcome: Outcome) -> WDLBound:
        if self.rules.repetition_limit is None:
            return WDLBound.exact(outcome)
        # The tablebases use no-progress only. Adding automatic repetition can
        # truncate a forced win/loss into a draw, but cannot reverse its winner.
        if outcome == Outcome.WIN:
            return WDLBound(Outcome.DRAW, Outcome.WIN)
        if outcome == Outcome.LOSS:
            return WDLBound(Outcome.LOSS, Outcome.DRAW)
        return WDLBound.exact(Outcome.DRAW)

    def _quiescence(
        self,
        state: State,
        alpha: int,
        beta: int,
        counts: Counter,
        ply_from_root: int,
        moves: tuple[Move, ...] | None = None,
    ) -> tuple[int, tuple[Move, ...], WDLBound]:
        status = terminal_status(
            state, repetition_count=counts[state.position_key], rules=self.rules
        )
        if status.terminal:
            if status.winner is None:
                return 0, (), WDLBound.exact(Outcome.DRAW)
            return -MATE_SCORE + ply_from_root, (), WDLBound.exact(Outcome.LOSS)
        moves = legal_moves(state) if moves is None else moves
        exact_bound = UNKNOWN_WDL
        exact_value = self._probe_exact(state)
        if exact_value is not None:
            exact_score, exact_bound = exact_value
            if exact_bound.exact_outcome is not None:
                return exact_score, (), exact_bound
            if exact_bound.lower == Outcome.DRAW:
                alpha = max(alpha, 0)
            if exact_bound.upper == Outcome.DRAW:
                beta = min(beta, 0)
            if alpha >= beta:
                score = alpha if exact_bound.lower == Outcome.DRAW else beta
                return score, (), exact_bound

        # Every generated capture already includes its full mandatory chain.
        if not moves[0].is_capture:
            score = self.eval_fn(state, state.turn)
            if exact_bound.lower == Outcome.DRAW:
                score = max(score, 0)
            if exact_bound.upper == Outcome.DRAW:
                score = min(score, 0)
            return score, (), exact_bound

        best_score = -INFINITY
        best_pv: tuple[Move, ...] = ()
        move_bounds: list[WDLBound] = []
        complete = True
        for move in self._order_moves(state, moves):
            self.nodes += 1
            self._check_time()
            child = apply_move(state, move, validate=False)
            counts[child.position_key] += 1
            try:
                child_moves = legal_moves(child)
                score, child_pv, child_bound = self._quiescence(
                    child, -beta, -alpha, counts, ply_from_root + 1, child_moves
                )
            finally:
                counts[child.position_key] -= 1
            score = -score
            move_bounds.append(self._invert_bound(child_bound))
            if score > best_score:
                best_score = score
                best_pv = (move,) + child_pv
            if score > alpha:
                alpha = score
            if alpha >= beta:
                complete = False
                break
        if exact_bound.lower == Outcome.DRAW:
            best_score = max(best_score, 0)
        if exact_bound.upper == Outcome.DRAW:
            best_score = min(best_score, 0)
        return best_score, best_pv, self._combine_bounds(move_bounds, complete, exact_bound)

    def _order_moves(self, state: State, moves: Iterable[Move], ply: int = 0) -> tuple[Move, ...]:
        if self.reference_search:
            return tuple(sorted(moves, key=lambda move: move.notation))
        tt_entry = self._tt.get(state.position_key)
        tt_move = tt_entry.best_move if tt_entry and tt_entry.best_move else self._move_hints.get(state.position_key)
        killers = self._killer_moves.get(ply, [])

        def move_weight(move: Move) -> int:
            if move == tt_move:
                return 10_000_000
            if move.is_capture:
                return 1_000_000 + len(move.captures) * 10_000
            if move.promotes:
                return 500_000
            if move in killers:
                return 100_000 if move == killers[0] else 50_000
            return self._history_scores.get((state.turn, move), 0)

        return tuple(sorted(moves, key=move_weight, reverse=True))

    def _add_killer(self, ply: int, move: Move) -> None:
        if move.is_capture:
            return
        killers = self._killer_moves.setdefault(ply, [])
        if move not in killers:
            killers.insert(0, move)
            if len(killers) > 2:
                killers.pop()

    def _add_history(self, turn: int, move: Move, depth: int) -> None:
        if move.is_capture:
            return
        key = (turn, move)
        self._history_scores[key] = self._history_scores.get(key, 0) + depth * depth

    def _choose(
        self,
        candidates: tuple[RootCandidate, ...],
        mode: Mode,
        win_margin: int,
        *,
        proof_guided: bool = False,
    ) -> RootCandidate:
        return choose_root(
            candidates,
            mode=mode,
            win_margin=win_margin,
            safety_rank=lambda item: self._safety_rank(item.bound),
            score=lambda item: item.score,
            best_rank=lambda item: (
                item.score,
                self._distance_rank(item.distance),
                item.policy_value.win,
                item.policy_value.policy,
                -len(item.pv),
                item.move.notation,
            ),
            win_rank=lambda item: (
                item.bound.exact_outcome == Outcome.WIN,
                item.score if item.score >= MATE_SCORE - 10_000 else 0,
                self._decisive_distance_rank(item.distance),
                item.policy_value.win,
                item.policy_value.expected_score,
                self._draw_distance_rank(item.distance),
                item.pressure,
                item.score,
                item.move.notation,
            ),
            proof_guided=proof_guided,
        )

    @staticmethod
    def _distance_rank(distance: EndgameDistance) -> tuple[int, int]:
        if not distance.exact:
            return (0, 0)
        if distance.outcome == Outcome.WIN and distance.dtm is not None:
            return (2, -distance.dtm)
        if distance.outcome == Outcome.LOSS and distance.dtm is not None:
            return (2, distance.dtm)
        if distance.outcome == Outcome.DRAW and distance.dtr is not None:
            return (1, -distance.dtr)
        return (0, 0)

    @staticmethod
    def _decisive_distance_rank(distance: EndgameDistance) -> tuple[int, int]:
        if not distance.exact or distance.dtm is None:
            return (0, 0)
        if distance.outcome == Outcome.WIN:
            return (1, -distance.dtm)
        if distance.outcome == Outcome.LOSS:
            return (1, distance.dtm)
        return (0, 0)

    @staticmethod
    def _draw_distance_rank(distance: EndgameDistance) -> tuple[int, int]:
        if (
            distance.exact
            and distance.outcome == Outcome.DRAW
            and distance.dtr is not None
        ):
            return (1, -distance.dtr)
        return (0, 0)

    @staticmethod
    def _invert_bound(bound: WDLBound) -> WDLBound:
        return WDLBound(Outcome(-bound.upper), Outcome(-bound.lower))

    @staticmethod
    def _combine_bounds(
        move_bounds: list[WDLBound],
        complete: bool,
        known_bound: WDLBound = UNKNOWN_WDL,
    ) -> WDLBound:
        if not move_bounds:
            return known_bound
        lower = max(bound.lower for bound in move_bounds)
        upper = max(bound.upper for bound in move_bounds) if complete else Outcome.WIN
        comb_lower = max(lower, known_bound.lower)
        comb_upper = min(upper, known_bound.upper)
        if comb_lower > comb_upper:
            raise ValueError(
                f"conflicting bounds: search [{lower.name}..{upper.name}] "
                f"contradicts known [{known_bound.lower.name}..{known_bound.upper.name}]"
            )
        return WDLBound(comb_lower, comb_upper)

    @staticmethod
    def _safety_rank(bound: WDLBound) -> tuple[int, int]:
        return int(bound.lower), int(bound.upper)

    def _human_pressure(self, child: State, engine_player: int) -> float:
        """Estimate gain against a bounded-error reply policy.

        The opponent's best static reply is the safety baseline. Inferior replies
        are weighted with a softmax-like decay, so a single spectacular but very
        implausible blunder does not dominate several realistic small mistakes.
        """

        replies = legal_moves(child)
        if not replies:
            return float(MATE_SCORE)
        reply_values: list[int] = []
        for reply in replies:
            after_reply = apply_move(child, reply, validate=False)
            if not legal_moves(after_reply):
                value = MATE_SCORE if after_reply.turn != engine_player else -MATE_SCORE
            else:
                value = evaluate(after_reply, engine_player)
            reply_values.append(value)
        best_defence = min(reply_values)
        mistake_costs = [value - best_defence for value in reply_values if value > best_defence]
        if not mistake_costs:
            return 0.0
        weights = [math.exp(max(-700.0, -cost / 100.0)) for cost in mistake_costs]
        expected_cost = sum(cost * weight for cost, weight in zip(mistake_costs, weights)) / sum(weights)
        return expected_cost + math.log2(len(mistake_costs) + 1)
