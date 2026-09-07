"""Deterministic fixed-depth A/B benchmarks for native search DLLs."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import random
from statistics import median
import time

from .core import (
    DEFAULT_RULES,
    Rules,
    State,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    terminal_status,
)
from .native import NativeSearch, NativeSearchResult


PositionKey = tuple[tuple[int, ...], int]


@dataclass(frozen=True, slots=True)
class NativeBenchmarkCase:
    index: int
    target_plies: int
    state: State
    history: dict[PositionKey, int]


@dataclass(frozen=True, slots=True)
class NativeBenchmarkRun:
    move: str
    score: int
    depth: int
    nodes: int
    wall_ms: float


@dataclass(frozen=True, slots=True)
class NativeBenchmarkRow:
    case: int
    target_plies: int
    position: str
    legal_moves: int
    forced_capture: bool
    candidate: NativeBenchmarkRun
    baseline: NativeBenchmarkRun


@dataclass(frozen=True, slots=True)
class NativeBenchmarkSummary:
    cases: int
    depth: int
    repetitions: int
    candidate_total_nodes: int
    baseline_total_nodes: int
    candidate_node_ratio: float
    candidate_total_ms: float
    baseline_total_ms: float
    candidate_time_ratio: float
    same_move_cases: int
    same_score_cases: int
    candidate_fewer_node_cases: int
    equal_node_cases: int
    baseline_fewer_node_cases: int


@dataclass(frozen=True, slots=True)
class NativeBenchmarkReport:
    candidate_path: str
    candidate_sha256: str
    candidate_abi: int
    baseline_path: str
    baseline_sha256: str
    baseline_abi: int
    seed: int
    hash_power: int
    ply_schedule: tuple[int, ...]
    rows: tuple[NativeBenchmarkRow, ...]
    summary: NativeBenchmarkSummary
    candidate_nnue_model_sha256: str | None = None
    baseline_nnue_model_sha256: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def generate_native_benchmark_cases(
    *,
    count: int,
    seed: int,
    ply_schedule: tuple[int, ...] = (4, 8, 12, 16, 20, 24, 28, 32),
    rules: Rules = DEFAULT_RULES,
) -> tuple[NativeBenchmarkCase, ...]:
    """Generate reproducible non-terminal positions from independent playouts."""

    if count < 1:
        raise ValueError("count must be positive")
    if not ply_schedule or any(ply < 0 for ply in ply_schedule):
        raise ValueError("ply_schedule must contain non-negative plies")

    rng = random.Random(seed)
    cases: list[NativeBenchmarkCase] = []
    attempts = 0
    max_attempts = max(100, count * 100)
    while len(cases) < count and attempts < max_attempts:
        target_plies = ply_schedule[len(cases) % len(ply_schedule)]
        state = initial_state(rules=rules)
        history: Counter[PositionKey] = Counter({state.position_key: 1})
        reached = True
        for _ in range(target_plies):
            status = terminal_status(
                state,
                repetition_count=history[state.position_key],
                rules=rules,
            )
            if status.terminal:
                reached = False
                break
            moves = legal_moves(state)
            state = apply_move(state, rng.choice(moves), validate=False)
            history[state.position_key] += 1
        attempts += 1
        if not reached:
            continue
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=rules,
        )
        if status.terminal:
            continue
        cases.append(
            NativeBenchmarkCase(
                index=len(cases) + 1,
                target_plies=target_plies,
                state=state,
                history=dict(history),
            )
        )
    if len(cases) != count:
        raise RuntimeError(
            f"could generate only {len(cases)} of {count} benchmark positions"
        )
    return tuple(cases)


def _search_case(
    engine: NativeSearch,
    case: NativeBenchmarkCase,
    *,
    depth: int,
    rules: Rules,
) -> tuple[NativeSearchResult, float]:
    engine.clear()
    started = time.perf_counter()
    result = engine.search(
        case.state,
        depth=depth,
        time_ms=None,
        no_progress_plies=rules.no_progress_plies,
        repetition_limit=rules.repetition_limit,
        history=case.history,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if result.depth != depth:
        raise RuntimeError(
            f"case {case.index} completed depth {result.depth}, expected {depth}"
        )
    return result, wall_ms


def _stable_run(
    results: list[tuple[NativeSearchResult, float]],
    *,
    label: str,
    case_index: int,
) -> NativeBenchmarkRun:
    first = results[0][0]
    for result, _ in results[1:]:
        if (
            result.move != first.move
            or result.score != first.score
            or result.depth != first.depth
            or result.nodes != first.nodes
        ):
            raise RuntimeError(
                f"{label} search is not deterministic on case {case_index}"
            )
    return NativeBenchmarkRun(
        move=first.move.notation,
        score=first.score,
        depth=first.depth,
        nodes=first.nodes,
        wall_ms=median(wall_ms for _, wall_ms in results),
    )


def summarize_native_benchmark(
    rows: tuple[NativeBenchmarkRow, ...],
    *,
    depth: int,
    repetitions: int,
) -> NativeBenchmarkSummary:
    if not rows:
        raise ValueError("rows must not be empty")
    node_ratios = [
        row.candidate.nodes / row.baseline.nodes
        for row in rows
        if row.candidate.nodes > 0 and row.baseline.nodes > 0
    ]
    if len(node_ratios) != len(rows):
        raise ValueError("every benchmark run must search at least one node")
    geometric_node_ratio = math.exp(
        math.fsum(math.log(ratio) for ratio in node_ratios) / len(node_ratios)
    )
    candidate_ms = math.fsum(row.candidate.wall_ms for row in rows)
    baseline_ms = math.fsum(row.baseline.wall_ms for row in rows)
    return NativeBenchmarkSummary(
        cases=len(rows),
        depth=depth,
        repetitions=repetitions,
        candidate_total_nodes=sum(row.candidate.nodes for row in rows),
        baseline_total_nodes=sum(row.baseline.nodes for row in rows),
        candidate_node_ratio=geometric_node_ratio,
        candidate_total_ms=candidate_ms,
        baseline_total_ms=baseline_ms,
        candidate_time_ratio=candidate_ms / baseline_ms,
        same_move_cases=sum(row.candidate.move == row.baseline.move for row in rows),
        same_score_cases=sum(row.candidate.score == row.baseline.score for row in rows),
        candidate_fewer_node_cases=sum(
            row.candidate.nodes < row.baseline.nodes for row in rows
        ),
        equal_node_cases=sum(
            row.candidate.nodes == row.baseline.nodes for row in rows
        ),
        baseline_fewer_node_cases=sum(
            row.candidate.nodes > row.baseline.nodes for row in rows
        ),
    )


def compare_native_libraries(
    candidate_library: str | Path,
    baseline_library: str | Path,
    *,
    count: int = 24,
    depth: int = 14,
    repetitions: int = 2,
    seed: int = 0x4D414B484F53,
    hash_power: int = 18,
    ply_schedule: tuple[int, ...] = (4, 8, 12, 16, 20, 24, 28, 32),
    rules: Rules = DEFAULT_RULES,
    candidate_nnue_model: str | Path | None = None,
    baseline_nnue_model: str | Path | None = None,
) -> NativeBenchmarkReport:
    """Compare deterministic search work after clearing both persistent contexts."""

    if depth < 1:
        raise ValueError("depth must be positive")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    candidate_path = Path(candidate_library).resolve()
    baseline_path = Path(baseline_library).resolve()
    if not candidate_path.is_file():
        raise FileNotFoundError(f"candidate DLL not found: {candidate_path}")
    if not baseline_path.is_file():
        raise FileNotFoundError(f"baseline DLL not found: {baseline_path}")
    if candidate_path == baseline_path:
        raise ValueError("candidate and baseline DLL must be different files")

    cases = generate_native_benchmark_cases(
        count=count,
        seed=seed,
        ply_schedule=ply_schedule,
        rules=rules,
    )
    rows: list[NativeBenchmarkRow] = []
    with NativeSearch(
        candidate_path,
        hash_power=hash_power,
        persistent=True,
        nnue_model=candidate_nnue_model,
    ) as candidate, NativeSearch(
        baseline_path,
        hash_power=hash_power,
        persistent=True,
        nnue_model=baseline_nnue_model,
    ) as baseline:
        if candidate.abi_version < 3 or baseline.abi_version < 3:
            raise RuntimeError("fixed-depth A/B benchmark requires search ABI 3")
        for case in cases:
            candidate_runs: list[tuple[NativeSearchResult, float]] = []
            baseline_runs: list[tuple[NativeSearchResult, float]] = []
            for repetition in range(repetitions):
                if (case.index + repetition) % 2:
                    candidate_runs.append(
                        _search_case(candidate, case, depth=depth, rules=rules)
                    )
                    baseline_runs.append(
                        _search_case(baseline, case, depth=depth, rules=rules)
                    )
                else:
                    baseline_runs.append(
                        _search_case(baseline, case, depth=depth, rules=rules)
                    )
                    candidate_runs.append(
                        _search_case(candidate, case, depth=depth, rules=rules)
                    )
            candidate_run = _stable_run(
                candidate_runs, label="candidate", case_index=case.index
            )
            baseline_run = _stable_run(
                baseline_runs, label="baseline", case_index=case.index
            )
            moves = legal_moves(case.state)
            rows.append(
                NativeBenchmarkRow(
                    case=case.index,
                    target_plies=case.target_plies,
                    position=format_position(case.state),
                    legal_moves=len(moves),
                    forced_capture=bool(moves[0].captures),
                    candidate=candidate_run,
                    baseline=baseline_run,
                )
            )

    rows_tuple = tuple(rows)
    return NativeBenchmarkReport(
        candidate_path=str(candidate_path),
        candidate_sha256=hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        candidate_abi=candidate.abi_version,
        baseline_path=str(baseline_path),
        baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        baseline_abi=baseline.abi_version,
        seed=seed,
        hash_power=hash_power,
        ply_schedule=ply_schedule,
        rows=rows_tuple,
        summary=summarize_native_benchmark(
            rows_tuple, depth=depth, repetitions=repetitions
        ),
        candidate_nnue_model_sha256=candidate.nnue_model_sha256,
        baseline_nnue_model_sha256=baseline.nnue_model_sha256,
    )
