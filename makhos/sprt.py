"""SPRT (Sequential Probability Ratio Test) Testing Harness for Thai Makhos Engine.

Used for rigorous, statistical hypothesis testing (Fishtest-style) to verify whether
candidate evaluation tweaks or search changes yield statistically significant Elo gains.

Protocol:
- Time Control: 10 seconds + 0.1 second increment per move (10s + 0.1s)
- Paired games (Dev as Black / Master as Red, then Master as Black / Dev as Red)
- Hash: 64 MB
- LLR bounds: H0 (Elo = 0) vs H1 (Elo = 5), alpha=0.05, beta=0.05 -> [-2.94, +2.94]
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import random
import time
from typing import Callable

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
from .search import Engine, Mode, SearchLimits, TimeManager


@dataclass(frozen=True, slots=True)
class SPRTResult:
    status: str  # "PASS", "FAIL", or "INCONCLUSIVE"
    llr: float
    elo: float
    elo_error: float
    wins: int
    draws: int
    losses: int
    games: int
    pentanomial: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)


def elo_from_score(score: float) -> float:
    if score <= 0.0:
        return -MATE_SCORE
    if score >= 1.0:
        return MATE_SCORE
    return -400.0 * math.log10(1.0 / score - 1.0)


def _regularize(results: tuple[int, ...]) -> tuple[float, ...]:
    if len(results) not in (3, 5):
        raise ValueError("SPRT results must be trinomial or pentanomial")
    if any(result < 0 for result in results):
        raise ValueError("SPRT frequencies cannot be negative")
    return tuple(1e-3 if result == 0 else float(result) for result in results)


def _results_pdf(results: tuple[int, ...]) -> tuple[float, tuple[tuple[float, float], ...]]:
    regularized = _regularize(results)
    total = sum(regularized)
    denominator = len(regularized) - 1
    return total, tuple(
        (index / denominator, frequency / total)
        for index, frequency in enumerate(regularized)
    )


def _mle_expected(
    pdf: tuple[tuple[float, float], ...],
    expected_score: float,
) -> tuple[tuple[float, float], ...]:
    """Fishtest generalized-MLE distribution at a fixed expectation."""

    shifted = tuple((value - expected_score, probability) for value, probability in pdf)
    negative = min(value for value, _ in shifted)
    positive = max(value for value, _ in shifted)
    if negative >= 0 or positive <= 0:
        raise ValueError("SPRT expectation must lie inside the outcome support")
    epsilon = 1e-12
    low = -1.0 / positive + epsilon
    high = -1.0 / negative - epsilon

    def secular(multiplier: float) -> float:
        return sum(
            probability * value / (1.0 + multiplier * value)
            for value, probability in shifted
        )

    for _ in range(100):
        middle = (low + high) / 2.0
        if secular(middle) > 0:
            low = middle
        else:
            high = middle
    multiplier = (low + high) / 2.0
    return tuple(
        (
            value,
            probability / (1.0 + multiplier * (value - expected_score)),
        )
        for value, probability in pdf
    )


def _logistic_llr(
    results: tuple[int, ...],
    elo0: float,
    elo1: float,
) -> float:
    """Exact generalized logistic LLR used by official Fishtest."""

    total, pdf = _results_pdf(results)
    score0 = 1.0 / (1.0 + 10.0 ** (-elo0 / 400.0))
    score1 = 1.0 / (1.0 + 10.0 ** (-elo1 / 400.0))
    mle0 = _mle_expected(pdf, score0)
    mle1 = _mle_expected(pdf, score1)
    return total * sum(
        empirical_probability * math.log(mle1[index][1] / mle0[index][1])
        for index, (_, empirical_probability) in enumerate(pdf)
    )


def _elo_estimate(results: tuple[int, ...]) -> tuple[float, float]:
    """Logistic Elo and 95% CI half-width, preserving paired variance."""

    regularized = _regularize(results)
    samples = sum(regularized)
    games_per_sample = (len(regularized) - 1) / 2.0
    games = samples * games_per_sample
    score = sum(
        frequency * (index / 2.0)
        for index, frequency in enumerate(regularized)
    ) / games
    sample_mean = games_per_sample * score
    variance = sum(
        frequency * (index / 2.0 - sample_mean) ** 2
        for index, frequency in enumerate(regularized)
    ) / games
    standard_error = math.sqrt(variance / games)
    low = max(0.001, score - 1.959963984540054 * standard_error)
    high = min(0.999, score + 1.959963984540054 * standard_error)
    return elo_from_score(score), (elo_from_score(high) - elo_from_score(low)) / 2.0


def _calculate_sprt_results(
    results: tuple[int, ...],
    elo0: float = 0.0,
    elo1: float = 2.0,
    alpha: float = 0.05,
    beta: float = 0.05,
) -> tuple[str, float, float, float]:
    if sum(results) == 0:
        return "INCONCLUSIVE", 0.0, 0.0, 0.0
    if not 0.0 < alpha < 1.0 or not 0.0 < beta < 1.0:
        raise ValueError("alpha and beta must lie in 0..1")
    if elo1 <= elo0:
        raise ValueError("elo1 must be greater than elo0")

    llr = _logistic_llr(results, elo0, elo1)
    elo, elo_error = _elo_estimate(results)

    # Bounds
    lower_bound = math.log(beta / (1.0 - alpha))  # ~ -2.944
    upper_bound = math.log((1.0 - beta) / alpha)  # ~ +2.944

    status = "INCONCLUSIVE"
    if llr >= upper_bound:
        status = "PASS"
    elif llr <= lower_bound:
        status = "FAIL"

    return status, llr, elo, elo_error


def calculate_sprt(
    wins: int,
    draws: int,
    losses: int,
    elo0: float = 0.0,
    elo1: float = 2.0,
    alpha: float = 0.05,
    beta: float = 0.05,
) -> tuple[str, float, float, float]:
    """Calculate a generalized trinomial SPRT for compatibility callers."""

    return _calculate_sprt_results(
        (losses, draws, wins), elo0, elo1, alpha, beta
    )


def calculate_pentanomial_sprt(
    pentanomial: tuple[int, int, int, int, int],
    elo0: float = 0.0,
    elo1: float = 2.0,
    alpha: float = 0.05,
    beta: float = 0.05,
) -> tuple[str, float, float, float]:
    """Calculate Fishtest paired-game SPRT from 0..2 pair-score buckets."""

    return _calculate_sprt_results(
        pentanomial, elo0, elo1, alpha, beta
    )


def pentanomial_index(first_score: float, second_score: float) -> int:
    """Map two candidate game scores to LL..WW bucket 0..4."""

    index = round(2.0 * (first_score + second_score))
    if index not in range(5):
        raise ValueError("game scores must each be 0, 0.5, or 1")
    if first_score not in (0.0, 0.5, 1.0) or second_score not in (0.0, 0.5, 1.0):
        raise ValueError("game scores must each be 0, 0.5, or 1")
    return index


def play_timed_game(
    state: State,
    history: Counter,
    *,
    black_engine: Engine,
    black_mode: Mode,
    red_engine: Engine,
    red_mode: Mode,
    initial_time_ms: int = 10000,
    inc_ms: int = 100,
    rules: Rules = DEFAULT_RULES,
    max_game_plies: int = 300,
    move_time_cap_ms: int | None = None,
    fixed_move_time_ms: int | None = None,
    workload_checkpoint: Callable[[str], None] | None = None,
) -> tuple[int | None, str]:
    """Play one game under timed clock controls (10s + 0.1s)."""

    if fixed_move_time_ms is not None:
        if type(fixed_move_time_ms) is not int or fixed_move_time_ms < 1:
            raise ValueError("fixed_move_time_ms must be a positive integer")
        if move_time_cap_ms is not None:
            raise ValueError("fixed move time and clock cap are mutually exclusive")
    black_time = initial_time_ms
    red_time = initial_time_ms

    for ply_index in range(max_game_plies):
        if workload_checkpoint is not None:
            workload_checkpoint(f"SPRT game ply {ply_index + 1}")
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=rules,
        )
        if status.terminal:
            return status.winner, status.reason

        turn = state.turn
        if turn == BLACK:
            alloc_time = fixed_move_time_ms if fixed_move_time_ms is not None else TimeManager.allocate_time(
                black_time, red_time, inc_ms, inc_ms
            )
            if move_time_cap_ms is not None:
                alloc_time = min(alloc_time, move_time_cap_ms)
            start = time.perf_counter()
            result = black_engine.search(
                state,
                SearchLimits(depth=64, time_ms=alloc_time),
                mode=black_mode,
                history=history,
            )
            used_ms = int((time.perf_counter() - start) * 1000)
            black_time = max(10, black_time - used_ms + inc_ms)
        else:
            alloc_time = fixed_move_time_ms if fixed_move_time_ms is not None else TimeManager.allocate_time(
                red_time, black_time, inc_ms, inc_ms
            )
            if move_time_cap_ms is not None:
                alloc_time = min(alloc_time, move_time_cap_ms)
            start = time.perf_counter()
            result = red_engine.search(
                state,
                SearchLimits(depth=64, time_ms=alloc_time),
                mode=red_mode,
                history=history,
            )
            used_ms = int((time.perf_counter() - start) * 1000)
            red_time = max(10, red_time - used_ms + inc_ms)

        state = apply_move(state, result.move, validate=False)
        history[state.position_key] += 1

    return None, "sprt_max_plies"


def run_sprt_match(
    dev_factory: Callable[[], Engine],
    master_factory: Callable[[], Engine],
    *,
    max_pairs: int = 10000,
    elo0: float = 0.0,
    elo1: float = 2.0,
    initial_time_ms: int = 10000,
    inc_ms: int = 100,
    opening_plies: int = 4,
    seed: int = 1,
    verbose: bool = True,
    move_time_cap_ms: int | None = None,
    fixed_move_time_ms: int | None = None,
    parallel_games: int = 1,
    max_game_plies: int = 300,
    workload_checkpoint: Callable[[str], None] | None = None,
    resume_result: SPRTResult | None = None,
    on_pair_completed: Callable[[SPRTResult], None] | None = None,
) -> SPRTResult:
    """Run an SPRT match between candidate dev engine and baseline master engine."""

    if fixed_move_time_ms is not None:
        if type(fixed_move_time_ms) is not int or fixed_move_time_ms < 1:
            raise ValueError("fixed_move_time_ms must be a positive integer")
        if move_time_cap_ms is not None:
            raise ValueError("fixed move time and clock cap are mutually exclusive")
    rng = random.Random(seed)
    if parallel_games not in (1, 2):
        raise ValueError("parallel_games must be 1 or 2")
    if max_game_plies < 1:
        raise ValueError("max_game_plies must be positive")
    if max_pairs < 1:
        raise ValueError("max_pairs must be positive")
    rules = DEFAULT_RULES
    if resume_result is None:
        wins = draws = losses = 0
        pentanomial = [0, 0, 0, 0, 0]
        completed_pairs = 0
    else:
        wins = resume_result.wins
        draws = resume_result.draws
        losses = resume_result.losses
        pentanomial = list(resume_result.pentanomial)
        completed_pairs = sum(pentanomial)
        if len(pentanomial) != 5 or any(
            not isinstance(value, int) or value < 0 for value in pentanomial
        ):
            raise ValueError("resume pentanomial must contain five nonnegative integers")
        if min(wins, draws, losses) < 0:
            raise ValueError("resume W/D/L counts must be nonnegative")
        if resume_result.games != wins + draws + losses:
            raise ValueError("resume game count does not match W/D/L")
        if resume_result.games != 2 * completed_pairs:
            raise ValueError("resume game count does not match completed pairs")
        if completed_pairs > max_pairs:
            raise ValueError("resume contains more pairs than max_pairs")
        status, llr, elo, elo_err = calculate_pentanomial_sprt(
            tuple(pentanomial), elo0=elo0, elo1=elo1
        )
        if (
            resume_result.status != status
            or not math.isclose(resume_result.llr, llr, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(resume_result.elo, elo, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(
                resume_result.elo_error,
                elo_err,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise ValueError("resume statistics do not match the pentanomial")
        if status != "INCONCLUSIVE" or completed_pairs == max_pairs:
            return resume_result

    def generate_opening() -> tuple[State, Counter]:
        state = initial_state(rules=rules)
        history = Counter({state.position_key: 1})
        for _ in range(opening_plies):
            moves = legal_moves(state)
            if not moves:
                break
            move = rng.choice(moves)
            state = apply_move(state, move, validate=False)
            history[state.position_key] += 1
        return state, history

    for _ in range(completed_pairs):
        generate_opening()

    if verbose:
        print("==================================================", flush=True)
        print("  Starting SPRT Match: Candidate Dev vs Master", flush=True)
        if fixed_move_time_ms is None:
            print(f"  Time Control: {initial_time_ms / 1000:g}s + {inc_ms / 1000:g}s increment per move", flush=True)
        else:
            print(f"  Time Control: fixed {fixed_move_time_ms} ms per move (no clock allocation)", flush=True)
        print(f"  STC Bounds: H0 ({elo0:g} Elo) vs H1 ({elo1:g} Elo) -> LLR [-2.94, +2.94]", flush=True)
        print("==================================================", flush=True)

    executor = (
        ThreadPoolExecutor(max_workers=2, thread_name_prefix="makhos-sprt")
        if parallel_games == 2 else None
    )
    for pair_idx in range(completed_pairs + 1, max_pairs + 1):
        try:
            if workload_checkpoint is not None:
                workload_checkpoint(f"SPRT pair {pair_idx}")
        except BaseException:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            raise

        state, history = generate_opening()

        def play_assignment(dev_is_black: bool) -> tuple[int | None, str]:
            dev_engine = dev_factory()
            master_engine = master_factory()
            try:
                return play_timed_game(
                    state,
                    Counter(history),
                    black_engine=dev_engine if dev_is_black else master_engine,
                    black_mode=Mode.WIN,
                    red_engine=master_engine if dev_is_black else dev_engine,
                    red_mode=Mode.WIN,
                    initial_time_ms=initial_time_ms,
                    inc_ms=inc_ms,
                    rules=rules,
                    move_time_cap_ms=move_time_cap_ms,
                    fixed_move_time_ms=fixed_move_time_ms,
                    max_game_plies=max_game_plies,
                    workload_checkpoint=workload_checkpoint,
                )
            finally:
                for engine in (dev_engine, master_engine):
                    if engine.native_search is not None:
                        engine.native_search.close()

        try:
            if executor is None:
                winner1, reason1 = play_assignment(True)
                winner2, reason2 = play_assignment(False)
            else:
                black_future = executor.submit(play_assignment, True)
                red_future = executor.submit(play_assignment, False)
                winner1, reason1 = black_future.result()
                winner2, reason2 = red_future.result()
        except BaseException:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            raise

        if reason1 == "sprt_max_plies" or reason2 == "sprt_max_plies":
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            raise RuntimeError(
                f"SPRT pair {pair_idx} truncated at "
                f"max_game_plies={max_game_plies}: "
                f"candidate_black={reason1}, candidate_red={reason2}; "
                "no result was recorded"
            )

        if winner1 == BLACK:
            wins += 1
            first_score = 1.0
        elif winner1 == RED:
            losses += 1
            first_score = 0.0
        else:
            draws += 1
            first_score = 0.5

        if winner2 == RED:
            wins += 1
            second_score = 1.0
        elif winner2 == BLACK:
            losses += 1
            second_score = 0.0
        else:
            draws += 1
            second_score = 0.5

        pentanomial[pentanomial_index(first_score, second_score)] += 1

        # Evaluate SPRT condition
        status, llr, elo, elo_err = calculate_pentanomial_sprt(
            tuple(pentanomial), elo0=elo0, elo1=elo1
        )
        total_games = wins + draws + losses
        pair_result = SPRTResult(
            status=status,
            llr=llr,
            elo=elo,
            elo_error=elo_err,
            wins=wins,
            draws=draws,
            losses=losses,
            games=total_games,
            pentanomial=tuple(pentanomial),
        )
        if on_pair_completed is not None:
            on_pair_completed(pair_result)

        if verbose:
            print(
                f"Pair {pair_idx:3d} ({total_games:3d} games) | "
                f"W: {wins:3d} D: {draws:3d} L: {losses:3d} | "
                f"Ptnml: {'/'.join(str(value) for value in pentanomial)} | "
                f"LLR: {llr:+6.2f} | Elo: {elo:+5.1f} +/-95% {elo_err:4.1f} | "
                f"Status: {status}",
                flush=True,
            )

        if status != "INCONCLUSIVE":
            break

    if executor is not None:
        executor.shutdown(wait=True)

    return pair_result
