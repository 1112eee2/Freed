"""Deterministic engine-vs-engine match harness."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
import math
import random

from .core import (
    BLACK,
    RED,
    DEFAULT_RULES,
    Move,
    Rules,
    State,
    apply_move,
    initial_state,
    legal_moves,
    terminal_status,
)
from .search import Engine, Mode, SearchLimits, SearchResult


@dataclass(frozen=True, slots=True)
class PlayedGame:
    winner: int | None
    reason: str
    moves: tuple[Move, ...]


@dataclass(frozen=True, slots=True)
class MatchScore:
    a_wins: int
    draws: int
    b_wins: int
    games: tuple[PlayedGame, ...]


@dataclass(frozen=True, slots=True)
class ModeRecord:
    wins: int
    draws: int
    losses: int


@dataclass(frozen=True, slots=True)
class GauntletScore:
    mode_a: ModeRecord
    mode_b: ModeRecord
    games: tuple[PlayedGame, ...]


class NoisyEngine:
    """Bounded-error opponent model for reproducible practical-mode tests."""

    def __init__(
        self,
        engine: Engine,
        *,
        error_rate: float,
        temperature: float,
        seed: int,
    ) -> None:
        if not 0.0 <= error_rate <= 1.0:
            raise ValueError("error_rate must be in 0..1")
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        self.engine = engine
        self.error_rate = error_rate
        self.temperature = temperature
        self.rng = random.Random(seed)

    def search(self, *args, **kwargs) -> SearchResult:
        result = self.engine.search(*args, **kwargs)
        if self.rng.random() >= self.error_rate:
            return result
        inferior = [candidate for candidate in result.candidates if candidate.score < result.score]
        if not inferior:
            return result
        weights = [
            math.exp(max(-700.0, (candidate.score - result.score) / self.temperature))
            for candidate in inferior
        ]
        if not any(weights):
            chosen = self.rng.choice(inferior)
        else:
            chosen = self.rng.choices(inferior, weights=weights, k=1)[0]
        return replace(
            result,
            move=chosen.move,
            score=chosen.score,
            pv=chosen.pv,
        )


def random_opening(
    state: State,
    plies: int,
    rng: random.Random,
) -> tuple[State, tuple[Move, ...], Counter]:
    history: Counter = Counter({state.position_key: 1})
    moves_played: list[Move] = []
    for _ in range(plies):
        moves = legal_moves(state)
        if not moves:
            break
        move = rng.choice(moves)
        moves_played.append(move)
        state = apply_move(state, move, validate=False)
        history[state.position_key] += 1
    return state, tuple(moves_played), history


def play_game(
    state: State,
    history: Counter,
    *,
    black_engine: Engine,
    black_mode: Mode,
    red_engine: Engine,
    red_mode: Mode,
    limits: SearchLimits | None = None,
    black_limits: SearchLimits | None = None,
    red_limits: SearchLimits | None = None,
    rules: Rules = DEFAULT_RULES,
    prefix: tuple[Move, ...] = (),
    max_game_plies: int = 300,
) -> PlayedGame:
    black_limits = black_limits or limits
    red_limits = red_limits or limits
    if black_limits is None or red_limits is None:
        raise ValueError("search limits must be provided for both players")
    played = list(prefix)
    for _ in range(max_game_plies):
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=rules,
        )
        if status.terminal:
            return PlayedGame(status.winner, status.reason, tuple(played))
        if state.turn == BLACK:
            result = black_engine.search(
                state, black_limits, mode=black_mode, history=history
            )
        else:
            result = red_engine.search(state, red_limits, mode=red_mode, history=history)
        played.append(result.move)
        state = apply_move(state, result.move, validate=False)
        history[state.position_key] += 1
    return PlayedGame(None, "arena_ply_limit", tuple(played))


def paired_match(
    *,
    pairs: int,
    mode_a: Mode | str,
    mode_b: Mode | str,
    limits: SearchLimits,
    opening_plies: int = 4,
    seed: int = 1,
    rules: Rules = DEFAULT_RULES,
    exact_piece_limit: int = 2,
    exact_max_states: int = 250_000,
) -> MatchScore:
    if pairs < 1:
        raise ValueError("pairs must be positive")
    mode_a, mode_b = Mode(mode_a), Mode(mode_b)
    rng = random.Random(seed)
    games: list[PlayedGame] = []
    a_wins = draws = b_wins = 0

    for _ in range(pairs):
        opened, prefix, opening_history = random_opening(
            initial_state(rules=rules), opening_plies, rng
        )
        assignments = (
            (mode_a, mode_b, "a_black"),
            (mode_b, mode_a, "a_red"),
        )
        for black_mode, red_mode, a_color in assignments:
            black_engine = Engine(
                rules,
                exact_piece_limit=exact_piece_limit,
                exact_max_states=exact_max_states,
            )
            red_engine = Engine(
                rules,
                exact_piece_limit=exact_piece_limit,
                exact_max_states=exact_max_states,
            )
            game = play_game(
                opened,
                Counter(opening_history),
                black_engine=black_engine,
                black_mode=black_mode,
                red_engine=red_engine,
                red_mode=red_mode,
                limits=limits,
                rules=rules,
                prefix=prefix,
            )
            games.append(game)
            if game.winner is None:
                draws += 1
            elif (game.winner == BLACK and a_color == "a_black") or (
                game.winner == RED and a_color == "a_red"
            ):
                a_wins += 1
            else:
                b_wins += 1
    return MatchScore(a_wins, draws, b_wins, tuple(games))


def compare_modes_against_shallow_opponent(
    *,
    pairs: int,
    mode_a: Mode | str,
    mode_b: Mode | str,
    challenger_limits: SearchLimits,
    opponent_limits: SearchLimits,
    opening_plies: int = 4,
    seed: int = 1,
    rules: Rules = DEFAULT_RULES,
    exact_piece_limit: int = 2,
    exact_max_states: int = 250_000,
    opponent_error_rate: float = 0.15,
    opponent_temperature: float = 100.0,
) -> GauntletScore:
    """Compare policies against the same shallow bounded-error opponent model."""

    if pairs < 1:
        raise ValueError("pairs must be positive")
    modes = (Mode(mode_a), Mode(mode_b))
    if modes[0] == modes[1]:
        raise ValueError("mode_a and mode_b must differ")
    records = {mode: [0, 0, 0] for mode in modes}  # win, draw, loss
    rng = random.Random(seed)
    games: list[PlayedGame] = []

    for _ in range(pairs):
        opened, prefix, opening_history = random_opening(
            initial_state(rules=rules), opening_plies, rng
        )
        noise_seeds = {BLACK: rng.randrange(2**63), RED: rng.randrange(2**63)}
        for challenger_mode in modes:
            for challenger_color in (BLACK, RED):
                black_is_challenger = challenger_color == BLACK
                black_mode = challenger_mode if black_is_challenger else Mode.BEST
                red_mode = challenger_mode if not black_is_challenger else Mode.BEST
                black_limits = challenger_limits if black_is_challenger else opponent_limits
                red_limits = challenger_limits if not black_is_challenger else opponent_limits
                challenger_engine = Engine(
                    rules,
                    exact_piece_limit=exact_piece_limit,
                    exact_max_states=exact_max_states,
                )
                opponent_engine = NoisyEngine(
                    Engine(
                        rules,
                        exact_piece_limit=exact_piece_limit,
                        exact_max_states=exact_max_states,
                    ),
                    error_rate=opponent_error_rate,
                    temperature=opponent_temperature,
                    seed=noise_seeds[challenger_color],
                )
                game = play_game(
                    opened,
                    Counter(opening_history),
                    black_engine=challenger_engine if black_is_challenger else opponent_engine,
                    black_mode=black_mode,
                    red_engine=opponent_engine if black_is_challenger else challenger_engine,
                    red_mode=red_mode,
                    black_limits=black_limits,
                    red_limits=red_limits,
                    rules=rules,
                    prefix=prefix,
                )
                games.append(game)
                record = records[challenger_mode]
                if game.winner is None:
                    record[1] += 1
                elif game.winner == challenger_color:
                    record[0] += 1
                else:
                    record[2] += 1

    def freeze(mode: Mode) -> ModeRecord:
        win, draw, loss = records[mode]
        return ModeRecord(win, draw, loss)

    return GauntletScore(freeze(modes[0]), freeze(modes[1]), tuple(games))
