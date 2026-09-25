"""Root-parallel native search used by the web GUI Threads option."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import math
import time
from typing import Mapping

from .core import Move, Rules, State, apply_move, legal_moves, terminal_status
from .native import (
    NativeSearch,
    NativeRootMoveResult,
    NativeSearchResult,
    NativeSearchTelemetry,
    hash_megabytes_for_power,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from .root_policy import choose_root

MATE_SCORE = 1_000_000
SEARCH_INFINITY = 2_000_000
MAX_PARALLEL_NATIVE_THREADS = 12


@dataclass(frozen=True, slots=True)
class _RootWork:
    move: Move
    child: State
    history: dict[tuple[tuple[int, ...], int], int]


@dataclass(frozen=True, slots=True)
class _RootResult:
    move: Move
    score: int
    depth: int
    nodes: int
    pv: tuple[Move, ...]
    telemetry: NativeSearchTelemetry | None = None


class ParallelNativeSearch:
    """Iterative-deepening root split across independent native workers.

    Each worker owns a persistent TT partition.  A depth is accepted only when
    every legal root move completed that depth, so faster branches never gain an
    unfair score-comparison advantage over slower branches.
    """

    def __init__(
        self,
        library: str | Path,
        *,
        threads: int,
        hash_mb: int,
        selective_root: bool = False,
        selective_reserve: float = 0.30,
        selective_candidates: int = 4,
        selective_margin: int = 120,
        root_alpha: bool = False,
        root_alpha_margin: int = 32,
        root_alpha_min_depth: int = 16,
        shared_tt: bool = False,
        shared_tt_group_size: int = 4,
        iterative_session: bool = False,
        iterative_session_warmup_depth: int = 12,
        nnue_model: str | Path | None = None,
    ) -> None:
        if not 2 <= threads <= MAX_PARALLEL_NATIVE_THREADS:
            raise ValueError(
                "parallel native search requires threads in 2..12"
            )
        if not 0.05 <= selective_reserve <= 0.8:
            raise ValueError("selective_reserve must be in 0.05..0.8")
        if not 1 <= selective_candidates <= MAX_PARALLEL_NATIVE_THREADS:
            raise ValueError("selective_candidates must be in 1..12")
        if selective_margin < 0:
            raise ValueError("selective_margin must be non-negative")
        if root_alpha and selective_root:
            raise ValueError("root-alpha and selective root are separate experiments")
        if iterative_session and (root_alpha or selective_root):
            raise ValueError(
                "iterative session cannot combine with root-alpha or selective root"
            )
        if not 3 <= iterative_session_warmup_depth <= 64:
            raise ValueError("iterative_session_warmup_depth must be in 3..64")
        if not 1 <= root_alpha_margin <= 1000:
            raise ValueError("root_alpha_margin must be in 1..1000")
        if not 2 <= root_alpha_min_depth <= 64:
            raise ValueError("root_alpha_min_depth must be in 2..64")
        if not 2 <= shared_tt_group_size <= MAX_PARALLEL_NATIVE_THREADS:
            raise ValueError("shared_tt_group_size must be in 2..12")
        self.path = Path(library)
        self.threads = threads
        self.requested_hash_mb = hash_mb
        self.selective_root = selective_root
        self.selective_reserve = selective_reserve
        # A selective layer searches one candidate per worker concurrently.
        # Keep the public default useful at 2-3 Threads by capping the active
        # candidate count to the available workers.
        self.selective_candidates = min(selective_candidates, threads)
        self.selective_margin = selective_margin
        self.root_alpha = root_alpha
        self.root_alpha_margin = root_alpha_margin
        self.root_alpha_min_depth = root_alpha_min_depth
        self.shared_tt = shared_tt
        self.shared_tt_group_size = min(shared_tt_group_size, threads)
        self.iterative_session = iterative_session
        self.iterative_session_warmup_depth = iterative_session_warmup_depth
        self.shared_tt_groups = (
            math.ceil(threads / self.shared_tt_group_size)
            if shared_tt
            else threads
        )
        self.tt_entry_bytes = native_tt_entry_bytes(self.path)
        self.hash_power = hash_power_for_megabytes(
            hash_mb,
            partitions=self.shared_tt_groups,
            entry_bytes=self.tt_entry_bytes,
        )
        self.allocated_hash_mb = hash_megabytes_for_power(
            self.hash_power,
            partitions=self.shared_tt_groups,
            entry_bytes=self.tt_entry_bytes,
        )
        workers: list[NativeSearch] = []
        try:
            for worker_index in range(threads):
                group_owner_index = (
                    worker_index
                    - (worker_index % self.shared_tt_group_size)
                )
                workers.append(
                    NativeSearch(
                        self.path,
                        hash_power=self.hash_power,
                        persistent=True,
                        nnue_model=nnue_model,
                        shared_with=(
                            workers[group_owner_index]
                            if shared_tt and worker_index != group_owner_index
                            else None
                        ),
                    )
                )
        except Exception:
            for worker in workers:
                worker.close()
            raise
        self._workers = tuple(workers)
        self._closed = False
        if iterative_session and not all(
            worker.supports_iterative_session for worker in self._workers
        ):
            self.close()
            raise RuntimeError("iterative native session is unavailable in this DLL")

    @property
    def persistent(self) -> bool:
        return True

    @property
    def abi_version(self) -> int:
        """Return the common native ABI loaded by every root worker."""

        self._require_open()
        return self._workers[0].abi_version

    @property
    def nnue_enabled(self) -> bool:
        """Report whether every root worker uses the bound NNUE model."""

        self._require_open()
        return all(worker.nnue_enabled for worker in self._workers)

    @property
    def nnue_feature_abi(self) -> str | None:
        self._require_open()
        return self._workers[0].nnue_feature_abi

    @property
    def nnue_model_path(self) -> Path | None:
        self._require_open()
        return self._workers[0].nnue_model_path

    @property
    def nnue_model_sha256(self) -> str | None:
        self._require_open()
        return self._workers[0].nnue_model_sha256

    @property
    def nnue_source_model_sha256(self) -> str | None:
        self._require_open()
        return self._workers[0].nnue_source_model_sha256

    @property
    def memory_bytes(self) -> int | None:
        """Return the total persistent native allocation across all workers."""

        self._require_open()
        values = tuple(worker.memory_bytes for worker in self._workers)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @property
    def workspace_lists(self) -> int | None:
        """Return the total lazily allocated move lists across all workers."""

        self._require_open()
        values = tuple(worker.workspace_lists for worker in self._workers)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @property
    def supports_tablebase_draw(self) -> bool:
        self._require_open()
        return all(worker.supports_tablebase_draw for worker in self._workers)

    def attach_tablebase(self, tablebase) -> None:
        """Attach one shared tablebase to every worker; see NativeSearch."""

        self._require_open()
        try:
            for worker in self._workers:
                worker.attach_tablebase(tablebase)
        except BaseException:
            self.detach_tablebase()
            raise

    def detach_tablebase(self) -> None:
        self._require_open()
        for worker in self._workers:
            worker.detach_tablebase()

    def tablebase_counters(self) -> tuple[int, int, int]:
        """Probes, exact-draw cutoffs and probe errors summed over workers."""

        self._require_open()
        totals = [0, 0, 0]
        for worker in self._workers:
            for index, value in enumerate(worker.tablebase_counters()):
                totals[index] += value
        return totals[0], totals[1], totals[2]

    def clear(self) -> None:
        self._require_open()
        for worker_index, worker in enumerate(self._workers):
            is_group_owner = (
                not self.shared_tt or
                worker_index % self.shared_tt_group_size == 0
            )
            if is_group_owner:
                worker.clear()
            else:
                worker.clear_local()

    def close(self) -> None:
        if self._closed:
            return
        for worker in reversed(self._workers):
            worker.close()
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("parallel native search is closed")

    def __enter__(self) -> "ParallelNativeSearch":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def evaluate(self, state: State) -> int:
        self._require_open()
        return self._workers[0].evaluate(state)

    @staticmethod
    def _terminal_result(
        work: _RootWork,
        *,
        root_player: int,
        root_depth: int,
        rules: Rules,
    ) -> _RootResult | None:
        status = terminal_status(
            work.child,
            repetition_count=work.history.get(work.child.position_key, 1),
            rules=rules,
        )
        if not status.terminal:
            return None
        if status.winner is None:
            score = 0
        elif status.winner == root_player:
            score = MATE_SCORE - 1
        else:
            score = -MATE_SCORE + 1
        return _RootResult(work.move, score, root_depth, 1, (work.move,))

    def _search_group(
        self,
        worker: NativeSearch,
        group: tuple[_RootWork, ...],
        *,
        root_player: int,
        root_depth: int,
        deadline: float,
        no_progress_plies: int,
        repetition_limit: int | None,
        rules: Rules,
    ) -> tuple[tuple[_RootResult, ...], bool]:
        results: list[_RootResult] = []
        complete = True
        child_depth = max(1, root_depth - 1)
        for index, work in enumerate(group):
            terminal = self._terminal_result(
                work,
                root_player=root_player,
                root_depth=root_depth,
                rules=rules,
            )
            if terminal is not None:
                results.append(terminal)
                continue

            child_time_ms = None
            if deadline is not None:
                remaining_ms = max(1, int((deadline - time.perf_counter()) * 1000))
                remaining_calls = len(group) - index
                child_time_ms = max(1, remaining_ms // remaining_calls)
            native = worker.search(
                work.child,
                depth=child_depth,
                time_ms=child_time_ms,
                no_progress_plies=no_progress_plies,
                repetition_limit=repetition_limit,
                history=work.history,
            )
            complete = complete and native.depth >= child_depth
            results.append(
                _RootResult(
                    move=work.move,
                    score=-native.score,
                    depth=native.depth + 1,
                    nodes=native.nodes + 1,
                    pv=(work.move,) + native.pv,
                    telemetry=native.telemetry,
                )
            )
        return tuple(results), complete

    def _search_session_work(
        self,
        worker: NativeSearch,
        work: _RootWork,
        *,
        root_player: int,
        root_depth: int,
        deadline: float | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        rules: Rules,
        started: bool,
        prior_nodes: int,
        attach: bool,
    ) -> tuple[_RootResult, int, bool]:
        """Advance one ungrouped root child through its native ID session."""

        terminal = self._terminal_result(
            work,
            root_player=root_player,
            root_depth=root_depth,
            rules=rules,
        )
        if terminal is not None:
            return terminal, prior_nodes, started
        child_depth = max(1, root_depth - 1)
        if started:
            native = worker.advance_iterative_session(depth=child_depth)
        else:
            remaining_ms = (
                None
                if deadline is None
                else max(1, int((deadline - time.perf_counter()) * 1000))
            )
            if attach:
                native = worker.attach_iterative_session(
                    work.child,
                    completed_depth=child_depth - 1,
                    depth=child_depth,
                    time_ms=remaining_ms,
                    no_progress_plies=no_progress_plies,
                    repetition_limit=repetition_limit,
                    history=work.history,
                )
            else:
                native = worker.begin_iterative_session(
                    work.child,
                    depth=child_depth,
                    time_ms=remaining_ms,
                    no_progress_plies=no_progress_plies,
                    repetition_limit=repetition_limit,
                    history=work.history,
                )
            started = True
        delta_nodes = max(0, native.nodes - prior_nodes)
        return (
            _RootResult(
                move=work.move,
                score=-native.score,
                depth=native.depth + 1,
                nodes=delta_nodes,
                pv=(work.move,) + native.pv,
                # Session telemetry is cumulative.  Do not report it as a
                # per-layer delta until an explicit native delta ABI exists.
                telemetry=None,
            ),
            native.nodes,
            started,
        )

    def _search_fixed_work(
        self,
        worker: NativeSearch,
        work: _RootWork,
        *,
        root_player: int,
        root_depth: int,
        deadline: float,
        no_progress_plies: int,
        repetition_limit: int | None,
        rules: Rules,
    ) -> _RootResult:
        terminal = self._terminal_result(
            work,
            root_player=root_player,
            root_depth=root_depth,
            rules=rules,
        )
        if terminal is not None:
            return terminal
        remaining_ms = max(1, int((deadline - time.perf_counter()) * 1000))
        native = worker.search_fixed(
            work.child,
            depth=max(1, root_depth - 1),
            time_ms=remaining_ms,
            no_progress_plies=no_progress_plies,
            repetition_limit=repetition_limit,
            history=work.history,
        )
        return _RootResult(
            move=work.move,
            score=-native.score,
            depth=native.depth + 1,
            nodes=native.nodes + 1,
            pv=(work.move,) + native.pv,
            telemetry=native.telemetry,
        )

    def _search_window_work(
        self,
        worker: NativeSearch,
        work: _RootWork,
        *,
        root_player: int,
        root_depth: int,
        root_alpha: int | None,
        deadline: float | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        rules: Rules,
    ) -> _RootResult:
        terminal = self._terminal_result(
            work,
            root_player=root_player,
            root_depth=root_depth,
            rules=rules,
        )
        if terminal is not None:
            return terminal
        remaining_ms = (
            None
            if deadline is None
            else max(1, int((deadline - time.perf_counter()) * 1000))
        )
        child_alpha, child_beta = (
            (-SEARCH_INFINITY, SEARCH_INFINITY)
            if root_alpha is None
            else (-root_alpha - 1, -root_alpha)
        )
        native = worker.search_window(
            work.child,
            depth=max(1, root_depth - 1),
            alpha=child_alpha,
            beta=child_beta,
            time_ms=remaining_ms,
            no_progress_plies=no_progress_plies,
            repetition_limit=repetition_limit,
            history=work.history,
        )
        return _RootResult(
            move=work.move,
            score=-native.score,
            depth=native.depth + 1,
            nodes=native.nodes + 1,
            pv=(work.move,) + native.pv,
            telemetry=native.telemetry,
        )

    @staticmethod
    def _choose(
        root_moves: tuple[Move, ...],
        results: tuple[_RootResult, ...],
    ) -> _RootResult:
        by_move = {result.move: result for result in results}
        ordered = tuple(by_move[move] for move in root_moves)
        return choose_root(
            ordered,
            mode="best",
            win_margin=0,
            safety_rank=lambda _item: (0, 0),
            score=lambda item: item.score,
            best_rank=lambda item: item.score,
        )

    def search(
        self,
        state: State,
        *,
        depth: int,
        time_ms: int | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        history: Mapping[tuple[tuple[int, ...], int], int] | None = None,
    ) -> NativeSearchResult:
        self._require_open()
        root_moves = legal_moves(state)
        if not root_moves:
            raise RuntimeError("position is terminal")

        started = time.perf_counter()
        deadline = started + time_ms / 1000 if time_ms is not None else None
        rules = Rules(
            name="native-root-parallel",
            starting_player=state.turn,
            repetition_limit=repetition_limit,
            no_progress_plies=no_progress_plies,
        )
        root_history = dict(history or {})
        works: list[_RootWork] = []
        for move in root_moves:
            child = apply_move(state, move, validate=False)
            child_history = root_history.copy()
            child_history[child.position_key] = child_history.get(child.position_key, 0) + 1
            works.append(_RootWork(move, child, child_history))

        active_threads = min(self.threads, len(works))
        selective_enabled = (
            self.selective_root
            and deadline is not None
            and all(
                worker.supports_fixed_search
                for worker in self._workers[:active_threads]
            )
        )
        root_alpha_enabled = (
            self.root_alpha
            and len(works) <= self.threads
            and not selective_enabled
            and all(
                worker.supports_window_search
                for worker in self._workers[:active_threads]
            )
        )
        session_enabled = (
            self.iterative_session
            and not selective_enabled
            and not root_alpha_enabled
            and len(works) == active_threads
        )
        common_deadline = deadline
        if selective_enabled:
            common_deadline = started + (
                time_ms / 1000 * (1.0 - self.selective_reserve)
            )
        groups = tuple(
            tuple(works[index::active_threads]) for index in range(active_threads)
        )
        work_by_move = {work.move: work for work in works}
        work_index = {work.move: index for index, work in enumerate(works)}
        total_nodes = 0
        total_telemetry: NativeSearchTelemetry | None = None
        session_state: dict[Move, tuple[bool, int]] = {
            work.move: (False, 0) for work in works
        }
        session_workers: set[int] = set()

        # Depth one is a complete static root pass and guarantees a legal result
        # even when an exceptionally short time limit expires immediately.
        completed_results: tuple[_RootResult, ...] = tuple(
            self._terminal_result(
                work,
                root_player=state.turn,
                root_depth=1,
                rules=rules,
            )
            or _RootResult(
                work.move,
                -self._workers[0].evaluate(work.child),
                1,
                1,
                (work.move,),
            )
            for work in works
        )
        total_nodes += len(works)
        completed_depth = 1
        common_depth = 1
        selective_completed = False

        with ThreadPoolExecutor(max_workers=active_threads) as executor:
            root_depth = 2
            while root_depth <= depth:
                if (
                    common_deadline is not None
                    and time.perf_counter() >= common_deadline
                ):
                    break
                iteration_results: list[_RootResult] = []
                iteration_complete = True
                accounting_results: list[_RootResult] = []
                if root_alpha_enabled and root_depth >= self.root_alpha_min_depth:
                    ordered = sorted(
                        completed_results,
                        key=lambda item: item.score,
                        reverse=True,
                    )
                    first_work = work_by_move[ordered[0].move]
                    first_index = work_index[first_work.move]
                    first_group, first_complete = self._search_group(
                        self._workers[first_index],
                        (first_work,),
                        root_player=state.turn,
                        root_depth=root_depth,
                        deadline=common_deadline,
                        no_progress_plies=no_progress_plies,
                        repetition_limit=repetition_limit,
                        rules=rules,
                    )
                    iteration_complete = first_complete
                    iteration_results.extend(first_group)
                    accounting_results.extend(first_group)
                    if first_complete:
                        root_bound = first_group[0].score
                        other_works = tuple(
                            work for work in works if work.move != first_work.move
                        )
                        window_futures = [
                            (
                                work,
                                executor.submit(
                                    self._search_window_work,
                                    self._workers[work_index[work.move]],
                                    work,
                                    root_player=state.turn,
                                    root_depth=root_depth,
                                    root_alpha=root_bound,
                                    deadline=common_deadline,
                                    no_progress_plies=no_progress_plies,
                                    repetition_limit=repetition_limit,
                                    rules=rules,
                                ),
                            )
                            for work in other_works
                        ]
                        window_results: list[_RootResult] = []
                        for _work, future in window_futures:
                            try:
                                window_results.append(future.result())
                            except TimeoutError:
                                iteration_complete = False
                        accounting_results.extend(window_results)
                        fail_low = tuple(
                            item for item in window_results
                            if item.score > root_bound
                        )
                        replacements: dict[Move, _RootResult] = {}
                        if iteration_complete and fail_low:
                            research_futures = [
                                (
                                    item,
                                    executor.submit(
                                        self._search_group,
                                        self._workers[work_index[item.move]],
                                        (work_by_move[item.move],),
                                        root_player=state.turn,
                                        root_depth=root_depth,
                                        deadline=common_deadline,
                                        no_progress_plies=no_progress_plies,
                                        repetition_limit=repetition_limit,
                                        rules=rules,
                                    ),
                                )
                                for item in fail_low
                            ]
                            for _item, future in research_futures:
                                try:
                                    group_results, group_complete = future.result()
                                except TimeoutError:
                                    iteration_complete = False
                                    continue
                                iteration_complete = (
                                    iteration_complete and group_complete
                                )
                                accounting_results.extend(group_results)
                                if group_results:
                                    replacements[group_results[0].move] = group_results[0]
                        iteration_results.extend(
                            replacements.get(item.move, item)
                            for item in window_results
                        )
                    if iteration_complete:
                        by_move = {item.move: item for item in iteration_results}
                        iteration_results = [by_move[move] for move in root_moves]
                elif (
                    session_enabled
                    and root_depth >= self.iterative_session_warmup_depth
                ):
                    session_futures = [
                        (
                            work,
                            executor.submit(
                                self._search_session_work,
                                self._workers[work_index[work.move]],
                                work,
                                root_player=state.turn,
                                root_depth=root_depth,
                                deadline=common_deadline,
                                no_progress_plies=no_progress_plies,
                                repetition_limit=repetition_limit,
                                rules=rules,
                                started=session_state[work.move][0],
                                prior_nodes=session_state[work.move][1],
                                attach=not session_state[work.move][0],
                            ),
                        )
                        for work in works
                    ]
                    for work, future in session_futures:
                        item, cumulative_nodes, was_started = future.result()
                        session_state[work.move] = (was_started, cumulative_nodes)
                        if was_started:
                            session_workers.add(work_index[work.move])
                        iteration_results.append(item)
                        accounting_results.append(item)
                        iteration_complete = (
                            iteration_complete and item.depth >= root_depth
                        )
                else:
                    futures = [
                        executor.submit(
                            self._search_group,
                            self._workers[index],
                            group,
                            root_player=state.turn,
                            root_depth=root_depth,
                            deadline=common_deadline,
                            no_progress_plies=no_progress_plies,
                            repetition_limit=repetition_limit,
                            rules=rules,
                        )
                        for index, group in enumerate(groups)
                    ]
                    for future in futures:
                        group_results, group_complete = future.result()
                        iteration_results.extend(group_results)
                        iteration_complete = iteration_complete and group_complete
                    accounting_results.extend(iteration_results)
                total_nodes += sum(result.nodes for result in accounting_results)
                for item in accounting_results:
                    if item.telemetry is not None:
                        total_telemetry = (
                            item.telemetry
                            if total_telemetry is None
                            else total_telemetry + item.telemetry
                        )
                if not iteration_complete or len(iteration_results) != len(root_moves):
                    # A branch may consume its slice before all siblings finish
                    # this common depth.  Persistent TT work is retained, so use
                    # any remaining clock to retry the same depth rather than
                    # returning conspicuously early with an older iteration.
                    if (
                        common_deadline is not None
                        and time.perf_counter() < common_deadline
                    ):
                        continue
                    break
                completed_results = tuple(iteration_results)
                completed_depth = root_depth
                common_depth = root_depth
                root_depth += 1

            choice_results = completed_results
            reported_results = completed_results
            if selective_enabled and deadline is not None:
                def select_candidates(
                    results: tuple[_RootResult, ...],
                ) -> tuple[_RootResult, ...]:
                    ordered = sorted(results, key=lambda item: item.score, reverse=True)
                    best_score = ordered[0].score
                    return tuple(
                        item
                        for item in ordered
                        if item.score >= best_score - self.selective_margin
                    )[: self.selective_candidates]

                candidates = select_candidates(completed_results)
                target_depth = completed_depth + 1
                while target_depth <= depth and time.perf_counter() < deadline:
                    used_workers: set[int] = set()
                    assignments: list[tuple[int, _RootResult]] = []
                    for candidate in candidates:
                        preferred = work_index[candidate.move] % active_threads
                        worker_index = preferred
                        if worker_index in used_workers:
                            worker_index = next(
                                index
                                for index in range(active_threads)
                                if index not in used_workers
                            )
                        used_workers.add(worker_index)
                        assignments.append((worker_index, candidate))
                    fixed_futures = [
                        executor.submit(
                            self._search_fixed_work,
                            self._workers[worker_index],
                            work_by_move[candidate.move],
                            root_player=state.turn,
                            root_depth=target_depth,
                            deadline=deadline,
                            no_progress_plies=no_progress_plies,
                            repetition_limit=repetition_limit,
                            rules=rules,
                        )
                        for worker_index, candidate in assignments
                    ]
                    try:
                        fixed_results = tuple(
                            future.result() for future in fixed_futures
                        )
                    except TimeoutError:
                        break
                    if any(item.depth != target_depth for item in fixed_results):
                        break
                    total_nodes += sum(item.nodes for item in fixed_results)
                    for item in fixed_results:
                        if item.telemetry is not None:
                            total_telemetry = (
                                item.telemetry
                                if total_telemetry is None
                                else total_telemetry + item.telemetry
                            )
                    choice_results = fixed_results
                    replacement = {item.move: item for item in fixed_results}
                    reported_results = tuple(
                        replacement.get(item.move, item) for item in reported_results
                    )
                    completed_depth = target_depth
                    selective_completed = True
                    candidates = select_candidates(fixed_results)
                    target_depth += 1

        for worker_index in session_workers:
            self._workers[worker_index].end_iterative_session()

        choice_moves = tuple(
            move for move in root_moves
            if any(result.move == move for result in choice_results)
        )

        chosen = self._choose(choice_moves, choice_results)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return NativeSearchResult(
            move=chosen.move,
            score=chosen.score,
            depth=completed_depth,
            nodes=total_nodes,
            elapsed_ms=elapsed_ms,
            pv=chosen.pv,
            telemetry=total_telemetry,
            common_depth=common_depth,
            selective_root=selective_completed,
            root_moves=tuple(
                NativeRootMoveResult(
                    move=result.move,
                    score=result.score,
                    depth=result.depth,
                    nodes=result.nodes,
                    pv=result.pv,
                )
                for result in reported_results
            ),
        )
