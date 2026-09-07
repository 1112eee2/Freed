"""Small, auditable policy--value model trained from self-play outcomes.

The proof/search layer treats these probabilities as preferences only.  They
never constitute a WDL proof and must never be allowed to cross a proven WDL
lower-bound tier.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Protocol

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    Move,
    RED_KING,
    RED_MAN,
    State,
    apply_move,
    index_to_coord,
    legal_moves,
)


MODEL_FORMAT = "makhos-policy-value"
MODEL_VERSION = 1


@dataclass(frozen=True, slots=True)
class PolicyValueEstimate:
    """Probabilities from the mover's perspective plus a policy prior."""

    win: float
    draw: float
    loss: float
    policy: float
    samples: float = 0.0

    def __post_init__(self) -> None:
        values = (self.win, self.draw, self.loss, self.policy, self.samples)
        if any(value < 0.0 for value in values):
            raise ValueError("policy/value fields cannot be negative")
        if abs(self.win + self.draw + self.loss - 1.0) > 1e-9:
            raise ValueError("W/D/L probabilities must sum to one")

    @property
    def expected_score(self) -> float:
        return self.win + 0.5 * self.draw

    @classmethod
    def neutral(cls, policy: float = 0.0) -> "PolicyValueEstimate":
        return cls(0.25, 0.50, 0.25, policy, 0.0)


class PolicyValueModel(Protocol):
    """Search-facing contract implemented by empirical or neural models."""

    def predict(
        self,
        state: State,
        moves: Iterable[Move] | None = None,
    ) -> dict[Move, PolicyValueEstimate]: ...


def _zone(row: int, player: int) -> int:
    relative = 7 - row if player == BLACK else row
    if relative <= 1:
        return 0
    if relative <= 5:
        return 1
    return 2


def _bucket_key(parts: tuple[object, ...]) -> str:
    return "|".join(str(part) for part in parts)


def context_key(state: State, move_count: int | None = None) -> str:
    """Coarse side-relative position features shared across many positions."""

    own_man = own_king = enemy_man = enemy_king = 0
    for piece in state.board:
        own = piece in (
            BLACK_MAN if state.turn == BLACK else RED_MAN,
            BLACK_KING if state.turn == BLACK else RED_KING,
        )
        if piece in (BLACK_MAN, RED_MAN):
            if own:
                own_man += 1
            else:
                enemy_man += 1
        elif piece in (BLACK_KING, RED_KING):
            if own:
                own_king += 1
            else:
                enemy_king += 1
    moves = legal_moves(state) if move_count is None else None
    count = len(moves) if moves is not None else move_count
    forced_capture = bool(moves and moves[0].is_capture)
    if moves is None:
        # A caller providing only the count obtains capture context through the
        # move bucket, so use a neutral marker here.
        forced_capture = False
    return _bucket_key((
        own_man,
        own_king,
        enemy_man,
        enemy_king,
        min(state.reversible_plies // 10, 8),
        min(int(count), 12),
        int(forced_capture),
    ))


def action_key(state: State, move: Move) -> str:
    """Generalized move features; no square-specific memorization is required."""

    piece = state.board[move.start]
    is_king = piece in (BLACK_KING, RED_KING)
    start_row, _ = index_to_coord(move.start)
    end_row, end_col = index_to_coord(move.end)
    advance = (start_row - end_row) if state.turn == BLACK else (end_row - start_row)
    if advance < 0:
        advance_bucket = -1
    elif advance == 0:
        advance_bucket = 0
    elif advance == 1:
        advance_bucket = 1
    else:
        advance_bucket = 2
    center = int(2 <= end_row <= 5 and 2 <= end_col <= 5)
    return _bucket_key((
        int(is_king),
        min(len(move.captures), 4),
        int(move.promotes),
        _zone(start_row, state.turn),
        _zone(end_row, state.turn),
        advance_bucket,
        center,
    ))


class EmpiricalPolicyValueModel:
    """Versioned Bayesian frequency model suitable as a safe first learner.

    Counts are stored both by position-context/action and by action alone.  The
    latter supplies a weak back-off estimate for contexts not yet seen in
    self-play.  A neural implementation can later replace this class without
    changing the proof-guided selection contract.
    """

    def __init__(
        self,
        *,
        value_prior: tuple[float, float, float] = (1.0, 2.0, 1.0),
        policy_prior: float = 1.0,
        backoff_weight: float = 0.25,
    ) -> None:
        if len(value_prior) != 3 or any(value <= 0 for value in value_prior):
            raise ValueError("value_prior must contain three positive values")
        if policy_prior <= 0 or not 0.0 <= backoff_weight <= 1.0:
            raise ValueError("invalid policy prior or back-off weight")
        self.value_prior = tuple(float(value) for value in value_prior)
        self.policy_prior = float(policy_prior)
        self.backoff_weight = float(backoff_weight)
        self.context_action: dict[str, list[int]] = {}
        self.action: dict[str, list[int]] = {}
        self.games = 0
        self.samples = 0

    @staticmethod
    def _combined_key(context: str, action: str) -> str:
        return context + "/" + action

    @staticmethod
    def _increment(table: dict[str, list[int]], key: str, result_index: int) -> None:
        counts = table.setdefault(key, [0, 0, 0])
        counts[result_index] += 1

    def update(self, state: State, move: Move, outcome: int) -> None:
        """Add one sample: outcome is +1 win, 0 draw, -1 loss for mover."""

        if outcome not in (-1, 0, 1):
            raise ValueError("outcome must be -1, 0, or 1")
        moves = legal_moves(state)
        if move not in moves:
            raise ValueError("cannot train on an illegal move")
        context = context_key(state)
        action = action_key(state, move)
        result_index = {1: 0, 0: 1, -1: 2}[outcome]
        self._increment(self.context_action, self._combined_key(context, action), result_index)
        self._increment(self.action, action, result_index)
        self.samples += 1

    def update_game(
        self,
        trajectory: Iterable[tuple[State, Move]],
        winner: int | None,
    ) -> None:
        for state, move in trajectory:
            outcome = 0 if winner is None else (1 if winner == state.turn else -1)
            self.update(state, move, outcome)
        self.games += 1

    def predict(
        self,
        state: State,
        moves: Iterable[Move] | None = None,
    ) -> dict[Move, PolicyValueEstimate]:
        legal = tuple(legal_moves(state) if moves is None else moves)
        if not legal:
            return {}
        context = context_key(state)
        rows: list[tuple[Move, list[int], list[int], float]] = []
        policy_evidence: list[float] = []
        for move in legal:
            action = action_key(state, move)
            local = self.context_action.get(self._combined_key(context, action), [0, 0, 0])
            global_counts = self.action.get(action, [0, 0, 0])
            evidence = sum(local) + self.backoff_weight * sum(global_counts)
            rows.append((move, local, global_counts, evidence))
            policy_evidence.append(evidence + self.policy_prior)
        policy_total = sum(policy_evidence)

        predictions: dict[Move, PolicyValueEstimate] = {}
        for (move, local, global_counts, evidence), policy_count in zip(rows, policy_evidence):
            weighted = [
                local[index] + self.backoff_weight * global_counts[index]
                for index in range(3)
            ]
            posterior = [weighted[index] + self.value_prior[index] for index in range(3)]
            total = sum(posterior)
            predictions[move] = PolicyValueEstimate(
                posterior[0] / total,
                posterior[1] / total,
                posterior[2] / total,
                policy_count / policy_total,
                evidence,
            )
        return predictions

    def to_dict(self) -> dict[str, object]:
        return {
            "format": MODEL_FORMAT,
            "version": MODEL_VERSION,
            "games": self.games,
            "samples": self.samples,
            "value_prior": list(self.value_prior),
            "policy_prior": self.policy_prior,
            "backoff_weight": self.backoff_weight,
            "context_action": self.context_action,
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "EmpiricalPolicyValueModel":
        if data.get("format") != MODEL_FORMAT or data.get("version") != MODEL_VERSION:
            raise ValueError("unsupported policy-value model format")
        model = cls(
            value_prior=tuple(float(value) for value in data["value_prior"]),
            policy_prior=float(data["policy_prior"]),
            backoff_weight=float(data["backoff_weight"]),
        )
        for name in ("context_action", "action"):
            source = data.get(name)
            if not isinstance(source, dict):
                raise ValueError(f"model field {name} must be an object")
            target = getattr(model, name)
            for key, raw_counts in source.items():
                if not isinstance(key, str) or not isinstance(raw_counts, list) or len(raw_counts) != 3:
                    raise ValueError(f"invalid counts in model field {name}")
                counts = [int(value) for value in raw_counts]
                if any(value < 0 for value in counts):
                    raise ValueError("model counts cannot be negative")
                target[key] = counts
        model.games = int(data.get("games", 0))
        model.samples = int(data.get("samples", 0))
        if model.games < 0 or model.samples < 0:
            raise ValueError("model totals cannot be negative")
        return model

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> "EmpiricalPolicyValueModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("policy-value model root must be an object")
        return cls.from_dict(data)
