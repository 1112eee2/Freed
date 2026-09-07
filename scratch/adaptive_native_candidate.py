"""Rejected adaptive-root candidate retained only for audit reproduction."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from makhos.core import State, legal_moves
from makhos.native import (
    NativeSearch,
    NativeSearchResult,
    hash_megabytes_for_power,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.parallel_native import ParallelNativeSearch


class AdaptiveNativeSearch:
    """Route broad roots to one hash-rich ordinary search for audit only."""

    def __init__(
        self,
        library: str | Path,
        *,
        threads: int,
        hash_mb: int,
        route_min_legal: int = 8,
        single_hash_mb: int = 160,
    ) -> None:
        if not 2 <= threads <= 12:
            raise ValueError("adaptive native search requires threads in 2..12")
        if route_min_legal < 3:
            raise ValueError("route_min_legal must be at least 3")
        if single_hash_mb < 1 or single_hash_mb >= hash_mb:
            raise ValueError("single_hash_mb must be positive and below total Hash")

        self.path = Path(library)
        self.threads = threads
        self.requested_hash_mb = hash_mb
        self.route_min_legal = route_min_legal
        self.single_hash_mb = single_hash_mb
        self.root_split_threads = max(2, min(threads, route_min_legal - 1))
        self._closed = False
        self.last_backend: str | None = None

        entry_bytes = native_tt_entry_bytes(self.path)
        single_hash_power = hash_power_for_megabytes(
            single_hash_mb,
            partitions=1,
            entry_bytes=entry_bytes,
        )
        self.single_allocated_hash_mb = hash_megabytes_for_power(
            single_hash_power,
            partitions=1,
            entry_bytes=entry_bytes,
        )
        single: NativeSearch | None = None
        root_split: ParallelNativeSearch | None = None
        try:
            single = NativeSearch(
                self.path,
                hash_power=single_hash_power,
                persistent=True,
            )
            root_split = ParallelNativeSearch(
                self.path,
                threads=self.root_split_threads,
                hash_mb=hash_mb,
            )
            total_allocated = (
                self.single_allocated_hash_mb + root_split.allocated_hash_mb
            )
            if total_allocated > hash_mb:
                raise ValueError(
                    "adaptive TT allocations exceed the requested Hash budget: "
                    f"{total_allocated:g} > {hash_mb} MiB"
                )
        except Exception:
            if root_split is not None:
                root_split.close()
            if single is not None:
                single.close()
            raise
        self._single = single
        self._root_split = root_split
        self.allocated_hash_mb = (
            self.single_allocated_hash_mb + self._root_split.allocated_hash_mb
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("adaptive native search is closed")

    def clear(self) -> None:
        self._require_open()
        self._single.clear()
        self._root_split.clear()
        self.last_backend = None

    def close(self) -> None:
        if self._closed:
            return
        self._root_split.close()
        self._single.close()
        self._closed = True

    def __enter__(self) -> "AdaptiveNativeSearch":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
        if len(legal_moves(state)) >= self.route_min_legal:
            self.last_backend = "adaptive-single"
            return self._single.search(
                state,
                depth=depth,
                time_ms=time_ms,
                no_progress_plies=no_progress_plies,
                repetition_limit=repetition_limit,
                history=history,
            )
        self.last_backend = "adaptive-root-split"
        return self._root_split.search(
            state,
            depth=depth,
            time_ms=time_ms,
            no_progress_plies=no_progress_plies,
            repetition_limit=repetition_limit,
            history=history,
        )
