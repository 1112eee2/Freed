"""Proof-guided self-play data generation for the policy--value model."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random

from .core import BLACK, RED, Rules, State, apply_move, initial_state, terminal_status
from .policy_value import EmpiricalPolicyValueModel
from .search import Engine, Mode, RootCandidate, SearchLimits


@dataclass(frozen=True, slots=True)
class SelfPlaySummary:
    games: int
    black_wins: int
    draws: int
    red_wins: int
    samples: int
    plies: int
    truncated: int


def _explore_candidate(
    candidates: tuple[RootCandidate, ...],
    rng: random.Random,
    *,
    score_margin: int,
    temperature: float,
) -> RootCandidate:
    """Sample only inside the best proven WDL lower-bound tier."""

    best_wdl = max(candidate.bound.lower for candidate in candidates)
    wdl_safe = [candidate for candidate in candidates if candidate.bound.lower == best_wdl]
    best_score = max(candidate.score for candidate in wdl_safe)
    pool = [candidate for candidate in wdl_safe if candidate.score >= best_score - score_margin]
    weights = [
        max(candidate.policy_value.policy, 1e-9) ** (1.0 / temperature)
        for candidate in pool
    ]
    return rng.choices(pool, weights=weights, k=1)[0]


def train_self_play(
    model: EmpiricalPolicyValueModel,
    engine: Engine,
    limits: SearchLimits,
    *,
    games: int,
    rules: Rules,
    seed: int = 1,
    exploration_rate: float = 0.15,
    exploration_score_margin: int = 50,
    temperature: float = 1.0,
    max_game_plies: int = 300,
    start: State | None = None,
) -> SelfPlaySummary:
    if games < 1:
        raise ValueError("games must be positive")
    if not 0.0 <= exploration_rate <= 1.0:
        raise ValueError("exploration_rate must be in 0..1")
    if exploration_score_margin < 0:
        raise ValueError("exploration_score_margin cannot be negative")
    if temperature <= 0.0 or max_game_plies < 1:
        raise ValueError("temperature and max_game_plies must be positive")
    if engine.policy_value_model is not model:
        raise ValueError("engine and trainer must share the same policy-value model")
    if engine.rules != rules:
        raise ValueError("engine and trainer must use identical rules")

    rng = random.Random(seed)
    black_wins = draws = red_wins = total_samples = total_plies = truncated = 0
    for _ in range(games):
        state = start if start is not None else initial_state(rules=rules)
        history: Counter = Counter({state.position_key: 1})
        trajectory = []
        winner: int | None = None
        completed = False
        for _ply in range(max_game_plies):
            status = terminal_status(
                state,
                repetition_count=history[state.position_key],
                rules=rules,
            )
            if status.terminal:
                winner = status.winner
                completed = True
                break
            result = engine.search(state, limits, mode=Mode.WIN, history=history)
            move = result.move
            exploration_candidates = result.candidates
            if result.proof_safe_moves:
                safe_moves = set(result.proof_safe_moves)
                exploration_candidates = tuple(
                    candidate for candidate in result.candidates
                    if candidate.move in safe_moves
                )
            if (
                rng.random() < exploration_rate and
                len(exploration_candidates) > 1
            ):
                move = _explore_candidate(
                    exploration_candidates,
                    rng,
                    score_margin=exploration_score_margin,
                    temperature=temperature,
                ).move
            trajectory.append((state, move))
            state = apply_move(state, move, validate=False)
            history[state.position_key] += 1
        else:
            status = terminal_status(
                state,
                repetition_count=history[state.position_key],
                rules=rules,
            )
            if status.terminal:
                winner = status.winner
                completed = True
            else:
                truncated += 1

        total_plies += len(trajectory)
        if completed:
            model.update_game(trajectory, winner)
            total_samples += len(trajectory)
            if winner == BLACK:
                black_wins += 1
            elif winner == RED:
                red_wins += 1
            else:
                draws += 1

    return SelfPlaySummary(
        games,
        black_wins,
        draws,
        red_wins,
        total_samples,
        total_plies,
        truncated,
    )
