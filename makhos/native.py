"""ctypes bridge to the native Thai Makhos alpha-beta search core."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, fields
import math
from pathlib import Path
import threading
from typing import Mapping

from .core import (
    BLACK_KING,
    BLACK_MAN,
    Move,
    RED_KING,
    RED_MAN,
    State,
)

MAX_PATH = 17
MAX_PLY = 96
SEARCH_ABI_VERSION = 6
MIN_SEARCH_ABI_VERSION = 2


class _PackedMove(ctypes.Structure):
    _fields_ = [
        ("path", ctypes.c_uint8 * MAX_PATH),
        ("captured", ctypes.c_uint8 * (MAX_PATH - 1)),
        ("path_len", ctypes.c_uint8),
        ("capture_count", ctypes.c_uint8),
        ("promotes", ctypes.c_uint8),
    ]


class _SearchResult(ctypes.Structure):
    _fields_ = [
        ("score", ctypes.c_int32),
        ("depth", ctypes.c_uint32),
        ("nodes", ctypes.c_uint64),
        ("elapsed_ms", ctypes.c_uint32),
        ("pv_len", ctypes.c_uint32),
        ("best_move", _PackedMove),
        ("pv", _PackedMove * MAX_PLY),
    ]


class _HistoryEntry(ctypes.Structure):
    _fields_ = [
        ("red", ctypes.c_uint32),
        ("black", ctypes.c_uint32),
        ("kings", ctypes.c_uint32),
        ("turn", ctypes.c_uint8),
        ("count", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 2),
    ]


class _SearchTelemetry(ctypes.Structure):
    _fields_ = [
        ("qnodes", ctypes.c_uint64),
        ("movegen_calls", ctypes.c_uint64),
        ("moves_generated", ctypes.c_uint64),
        ("ordering_calls", ctypes.c_uint64),
        ("moves_ordered", ctypes.c_uint64),
        ("tt_probes", ctypes.c_uint64),
        ("tt_hits", ctypes.c_uint64),
        ("tt_cutoffs", ctypes.c_uint64),
        ("tt_collisions", ctypes.c_uint64),
        ("tt_stores", ctypes.c_uint64),
        ("tt_replacements", ctypes.c_uint64),
        ("null_attempts", ctypes.c_uint64),
        ("null_cutoffs", ctypes.c_uint64),
        ("beta_cutoffs", ctypes.c_uint64),
        ("beta_cutoff_first", ctypes.c_uint64),
        ("beta_cutoff_index_sum", ctypes.c_uint64),
        ("q_beta_cutoffs", ctypes.c_uint64),
        ("pvs_researches", ctypes.c_uint64),
        ("lmr_researches", ctypes.c_uint64),
    ]


class _IirCensusTelemetry(ctypes.Structure):
    _fields_ = [
        ("post_tt_nodes", ctypes.c_uint64),
        ("eligible_nodes", ctypes.c_uint64),
        ("depth_ge6_nodes", ctypes.c_uint64),
        ("full_window_nodes", ctypes.c_uint64),
        ("null_window_nodes", ctypes.c_uint64),
        ("capture_nodes", ctypes.c_uint64),
        ("quiet_nodes", ctypes.c_uint64),
        ("with_tt_move", ctypes.c_uint64),
        ("without_tt_move", ctypes.c_uint64),
        ("missing_full_window", ctypes.c_uint64),
        ("missing_null_window", ctypes.c_uint64),
        ("missing_capture", ctypes.c_uint64),
        ("missing_quiet", ctypes.c_uint64),
        ("missing_depth4", ctypes.c_uint64),
        ("missing_depth5", ctypes.c_uint64),
        ("missing_depth6_plus", ctypes.c_uint64),
        ("missing_depth_sum", ctypes.c_uint64),
    ]


class _RepetitionCensusTelemetry(ctypes.Structure):
    _fields_ = [
        ("calls", ctypes.c_uint64),
        ("normal_calls", ctypes.c_uint64),
        ("qsearch_calls", ctypes.c_uint64),
        ("initial_linear_calls", ctypes.c_uint64),
        ("initial_linear_entries", ctypes.c_uint64),
        ("initial_hash_calls", ctypes.c_uint64),
        ("initial_hash_probes", ctypes.c_uint64),
        ("initial_hits", ctypes.c_uint64),
        ("line_entries", ctypes.c_uint64),
        ("line_matches", ctypes.c_uint64),
        ("draw_hits", ctypes.c_uint64),
        ("span_zero", ctypes.c_uint64),
        ("span_1_4", ctypes.c_uint64),
        ("span_5_16", ctypes.c_uint64),
        ("span_17_plus", ctypes.c_uint64),
    ]


_NATIVE_LAZY_SMP_MAX_THREADS = 12


class _LazySmpStats(ctypes.Structure):
    _fields_ = [
        ("requested_threads", ctypes.c_uint32),
        ("completed_threads", ctypes.c_uint32),
        ("aggregate_nodes", ctypes.c_uint64),
        ("leader_nodes", ctypes.c_uint64),
        ("leader_depth", ctypes.c_uint32),
        ("worker_nodes", ctypes.c_uint64 * _NATIVE_LAZY_SMP_MAX_THREADS),
        ("worker_depth", ctypes.c_uint32 * _NATIVE_LAZY_SMP_MAX_THREADS),
    ]


class _RootPvsShadowStats(ctypes.Structure):
    _fields_ = [
        ("requested_threads", ctypes.c_uint32),
        ("effective_threads", ctypes.c_uint32),
        ("active_helpers", ctypes.c_uint32),
        ("completed_depth", ctypes.c_uint32),
        ("attempted_depth", ctypes.c_uint32),
        ("main_hash_power", ctypes.c_uint32),
        ("helper_hash_power", ctypes.c_uint32),
        ("shadow_iterations", ctypes.c_uint32),
        ("allocated_tt_bytes", ctypes.c_uint64),
        ("main_nodes", ctypes.c_uint64),
        ("helper_nodes", ctypes.c_uint64),
        ("scout_tasks_started", ctypes.c_uint64),
        ("scout_tasks_completed", ctypes.c_uint64),
        ("scout_fail_highs", ctypes.c_uint64),
        ("scout_ready_before_main", ctypes.c_uint64),
        ("scout_ready_fail_highs", ctypes.c_uint64),
        ("scout_ready_above_current_alpha", ctypes.c_uint64),
        ("scout_tasks_aborted", ctypes.c_uint64),
        ("worker_failures", ctypes.c_uint64),
        ("main_wait_us", ctypes.c_uint64),
    ]


class _LegacyNativePositionLayout(ctypes.Structure):
    _fields_ = [
        ("red", ctypes.c_uint32),
        ("black", ctypes.c_uint32),
        ("kings", ctypes.c_uint32),
        ("turn", ctypes.c_uint8),
        ("reversible_plies", ctypes.c_uint8),
    ]


class _LegacyNativeMoveLayout(ctypes.Structure):
    _fields_ = [
        ("next", _LegacyNativePositionLayout),
        ("path", ctypes.c_uint8 * MAX_PATH),
        ("captured", ctypes.c_uint8 * (MAX_PATH - 1)),
        ("path_len", ctypes.c_uint8),
        ("capture_count", ctypes.c_uint8),
        ("promotes", ctypes.c_uint8),
    ]


class _LegacyNativeTTEntryLayout(ctypes.Structure):
    """ABI 2..4 TT layout retained for safe legacy DLL budgeting."""

    _fields_ = [
        ("key", ctypes.c_uint64),
        ("score", ctypes.c_int32),
        ("depth", ctypes.c_int16),
        ("flag", ctypes.c_uint8),
        ("generation", ctypes.c_uint8),
        ("best_move", _LegacyNativeMoveLayout),
    ]


class _NativeCompactMoveLayout(ctypes.Structure):
    _fields_ = [
        ("path_low", ctypes.c_uint64),
        ("captured_low", ctypes.c_uint64),
        ("path_high_meta", ctypes.c_uint32),
        ("captured_high_meta", ctypes.c_uint32),
    ]


class _NativeTTEntryLayout(ctypes.Structure):
    """Exact ABI-5 C TT layout for GUI Hash budgeting."""

    _fields_ = [
        ("key", ctypes.c_uint64),
        ("score", ctypes.c_int32),
        ("depth", ctypes.c_int16),
        ("flag", ctypes.c_uint8),
        ("generation", ctypes.c_uint8),
        ("best_move", _NativeCompactMoveLayout),
    ]


LEGACY_NATIVE_TT_ENTRY_BYTES = ctypes.sizeof(_LegacyNativeTTEntryLayout)
NATIVE_TT_ENTRY_BYTES = ctypes.sizeof(_NativeTTEntryLayout)


def hash_power_for_megabytes(
    hash_mb: int,
    *,
    partitions: int = 1,
    entry_bytes: int = NATIVE_TT_ENTRY_BYTES,
) -> int:
    """Return the largest power-of-two TT that fits the requested total Hash."""

    if hash_mb < 1:
        raise ValueError("hash_mb must be positive")
    if partitions < 1:
        raise ValueError("partitions must be positive")
    if entry_bytes < 1:
        raise ValueError("entry_bytes must be positive")
    bytes_per_partition = hash_mb * 1024 * 1024 // partitions
    entries = max(1, bytes_per_partition // entry_bytes)
    return max(12, min(24, int(math.floor(math.log2(entries)))))


def hash_megabytes_for_power(
    hash_power: int,
    *,
    partitions: int = 1,
    entry_bytes: int = NATIVE_TT_ENTRY_BYTES,
) -> float:
    """Report the actual total TT allocation for a native hash power."""

    if not 12 <= hash_power <= 24:
        raise ValueError("hash_power must be in 12..24")
    if partitions < 1:
        raise ValueError("partitions must be positive")
    if entry_bytes < 1:
        raise ValueError("entry_bytes must be positive")
    return (
        ((1 << hash_power) * entry_bytes * partitions)
        / (1024 * 1024)
    )


@dataclass(frozen=True, slots=True)
class NativeSearchTelemetry:
    qnodes: int
    movegen_calls: int
    moves_generated: int
    ordering_calls: int
    moves_ordered: int
    tt_probes: int
    tt_hits: int
    tt_cutoffs: int
    tt_collisions: int
    tt_stores: int
    tt_replacements: int
    null_attempts: int
    null_cutoffs: int
    beta_cutoffs: int
    beta_cutoff_first: int
    beta_cutoff_index_sum: int
    q_beta_cutoffs: int
    pvs_researches: int
    lmr_researches: int

    def __add__(self, other: "NativeSearchTelemetry") -> "NativeSearchTelemetry":
        if not isinstance(other, NativeSearchTelemetry):
            return NotImplemented
        return NativeSearchTelemetry(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )


@dataclass(frozen=True, slots=True)
class NativeIirCensusTelemetry:
    post_tt_nodes: int
    eligible_nodes: int
    depth_ge6_nodes: int
    full_window_nodes: int
    null_window_nodes: int
    capture_nodes: int
    quiet_nodes: int
    with_tt_move: int
    without_tt_move: int
    missing_full_window: int
    missing_null_window: int
    missing_capture: int
    missing_quiet: int
    missing_depth4: int
    missing_depth5: int
    missing_depth6_plus: int
    missing_depth_sum: int


@dataclass(frozen=True, slots=True)
class NativeRepetitionCensusTelemetry:
    calls: int
    normal_calls: int
    qsearch_calls: int
    initial_linear_calls: int
    initial_linear_entries: int
    initial_hash_calls: int
    initial_hash_probes: int
    initial_hits: int
    line_entries: int
    line_matches: int
    draw_hits: int
    span_zero: int
    span_1_4: int
    span_5_16: int
    span_17_plus: int


@dataclass(frozen=True, slots=True)
class NativeLazySmpStats:
    requested_threads: int
    completed_threads: int
    aggregate_nodes: int
    leader_nodes: int
    leader_depth: int
    worker_nodes: tuple[int, ...]
    worker_depth: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NativeRootPvsShadowStats:
    requested_threads: int
    effective_threads: int
    active_helpers: int
    completed_depth: int
    attempted_depth: int
    main_hash_power: int
    helper_hash_power: int
    shadow_iterations: int
    allocated_tt_bytes: int
    main_nodes: int
    helper_nodes: int
    scout_tasks_started: int
    scout_tasks_completed: int
    scout_fail_highs: int
    scout_ready_before_main: int
    scout_ready_fail_highs: int
    scout_ready_above_current_alpha: int
    scout_tasks_aborted: int
    worker_failures: int
    main_wait_us: int


def _unpack_lazy_smp_stats(raw: _LazySmpStats) -> NativeLazySmpStats:
    threads = min(int(raw.requested_threads), _NATIVE_LAZY_SMP_MAX_THREADS)
    return NativeLazySmpStats(
        requested_threads=threads,
        completed_threads=min(int(raw.completed_threads), threads),
        aggregate_nodes=int(raw.aggregate_nodes),
        leader_nodes=int(raw.leader_nodes),
        leader_depth=int(raw.leader_depth),
        worker_nodes=tuple(int(raw.worker_nodes[index]) for index in range(threads)),
        worker_depth=tuple(int(raw.worker_depth[index]) for index in range(threads)),
    )


def _unpack_root_pvs_shadow_stats(
    raw: _RootPvsShadowStats,
) -> NativeRootPvsShadowStats:
    return NativeRootPvsShadowStats(
        **{
            field.name: int(getattr(raw, field.name))
            for field in fields(NativeRootPvsShadowStats)
        }
    )


def _unpack_telemetry(raw: _SearchTelemetry) -> NativeSearchTelemetry:
    return NativeSearchTelemetry(
        **{
            field.name: int(getattr(raw, field.name))
            for field in fields(NativeSearchTelemetry)
        }
    )


def _unpack_iir_census(raw: _IirCensusTelemetry) -> NativeIirCensusTelemetry:
    return NativeIirCensusTelemetry(
        **{
            field.name: int(getattr(raw, field.name))
            for field in fields(NativeIirCensusTelemetry)
        }
    )


def _unpack_repetition_census(
    raw: _RepetitionCensusTelemetry,
) -> NativeRepetitionCensusTelemetry:
    return NativeRepetitionCensusTelemetry(
        **{
            field.name: int(getattr(raw, field.name))
            for field in fields(NativeRepetitionCensusTelemetry)
        }
    )


@dataclass(frozen=True, slots=True)
class NativeRootMoveResult:
    move: Move
    score: int
    depth: int
    nodes: int
    pv: tuple[Move, ...]


@dataclass(frozen=True, slots=True)
class NativeSearchResult:
    move: Move
    score: int
    depth: int
    nodes: int
    elapsed_ms: int
    pv: tuple[Move, ...]
    telemetry: NativeSearchTelemetry | None = None
    root_moves: tuple[NativeRootMoveResult, ...] = ()
    common_depth: int | None = None
    selective_root: bool = False


def project_native_library() -> Path:
    """Return the accepted production DLL, falling back for fresh builds."""

    build_dir = Path(__file__).resolve().parent.parent / "build"
    accepted = build_dir / "makhos_native_accepted.dll"
    return accepted if accepted.is_file() else build_dir / "makhos_native.dll"


def native_tt_entry_bytes(library: str | Path | None = None) -> int:
    """Read the native TT layout size, with safe ABI 2..4 compatibility."""

    path = Path(library) if library is not None else project_native_library()
    loaded = ctypes.CDLL(str(path.resolve()))
    loaded.makhos_search_abi_version.argtypes = []
    loaded.makhos_search_abi_version.restype = ctypes.c_int
    abi_version = int(loaded.makhos_search_abi_version())
    if abi_version < 5:
        return LEGACY_NATIVE_TT_ENTRY_BYTES
    loaded.makhos_search_tt_entry_bytes.argtypes = []
    loaded.makhos_search_tt_entry_bytes.restype = ctypes.c_uint64
    loaded.makhos_search_compact_move_selftest.argtypes = []
    loaded.makhos_search_compact_move_selftest.restype = ctypes.c_int
    entry_bytes = int(loaded.makhos_search_tt_entry_bytes())
    if entry_bytes != NATIVE_TT_ENTRY_BYTES:
        raise RuntimeError(
            "native TT layout mismatch: Python expects "
            f"{NATIVE_TT_ENTRY_BYTES} bytes, DLL reports {entry_bytes}"
        )
    selftest = int(loaded.makhos_search_compact_move_selftest())
    if selftest != 0:
        raise RuntimeError(f"native compact move self-test failed ({selftest})")
    return entry_bytes


def _board_bitboards(board: tuple[int, ...]) -> tuple[int, int, int]:
    red = 0
    black = 0
    kings = 0
    for square, piece in enumerate(board):
        bit = 1 << square
        if piece in (RED_MAN, RED_KING):
            red |= bit
        elif piece in (BLACK_MAN, BLACK_KING):
            black |= bit
        if piece in (RED_KING, BLACK_KING):
            kings |= bit
    return red, black, kings


def _bitboards(state: State) -> tuple[int, int, int]:
    return _board_bitboards(state.board)


def _unpack_move(packed: _PackedMove) -> Move:
    path_len = int(packed.path_len)
    capture_count = int(packed.capture_count)
    if not 2 <= path_len <= MAX_PATH:
        raise RuntimeError(f"native search returned invalid path length {path_len}")
    if capture_count not in (0, path_len - 1):
        raise RuntimeError(
            f"native search returned invalid capture count {capture_count}"
        )
    return Move(
        tuple(int(packed.path[index]) for index in range(path_len)),
        tuple(int(packed.captured[index]) for index in range(capture_count)),
        bool(packed.promotes),
    )


class NativeSearch:
    """Fast native search with a stable, deliberately small Python surface."""

    def __init__(
        self,
        library: str | Path | None = None,
        *,
        hash_power: int = 20,
        persistent: bool = False,
        shared_with: "NativeSearch | None" = None,
        nnue_model: str | Path | None = None,
    ) -> None:
        if not 12 <= hash_power <= 24:
            raise ValueError("hash_power must be in 12..24")
        self.path = Path(library) if library is not None else project_native_library()
        if not self.path.is_file():
            raise FileNotFoundError(f"native search library not found: {self.path}")
        self.hash_power = hash_power
        self._library = ctypes.CDLL(str(self.path.resolve()))
        self._lock = threading.RLock()
        self._handle: int | None = None
        self._closed = False
        self.supports_fixed_search = False
        self.supports_window_search = False
        self.supports_shared_tt = False
        self.supports_iterative_session = False
        self.supports_iir_census = False
        self.supports_repetition_census = False
        self.nnue_enabled = False
        self.nnue_model_path: Path | None = None
        self.nnue_model_sha256: str | None = None
        self.nnue_source_model_sha256: str | None = None
        self.nnue_feature_abi: str | None = None
        self.supports_nnue_telemetry = False
        self.supports_tablebase_draw = False
        self._tablebase = None
        self._tablebase_release = None
        self._tablebase_errors_seen = 0
        self.shared_tt = shared_with is not None
        self._iterative_session_active = False
        if shared_with is not None and not persistent:
            raise ValueError("shared TT requires persistent search")
        self._configure_signatures()
        self.abi_version = int(self._library.makhos_search_abi_version())
        if not MIN_SEARCH_ABI_VERSION <= self.abi_version <= SEARCH_ABI_VERSION:
            raise RuntimeError(
                "native search ABI mismatch: expected "
                f"{MIN_SEARCH_ABI_VERSION}..{SEARCH_ABI_VERSION}, got {self.abi_version}"
            )
        self._configure_nnue_candidate(nnue_model)
        if persistent and self.abi_version < 3:
            raise RuntimeError("persistent search requires native ABI 3")
        if self.abi_version >= 4:
            self._configure_telemetry_signatures()
        if self.abi_version >= 5:
            self._configure_layout_signatures()
            self.tt_entry_bytes = int(
                self._library.makhos_search_tt_entry_bytes()
            )
            if self.tt_entry_bytes != NATIVE_TT_ENTRY_BYTES:
                raise RuntimeError(
                    "native TT layout mismatch: Python expects "
                    f"{NATIVE_TT_ENTRY_BYTES} bytes, DLL reports "
                    f"{self.tt_entry_bytes}"
                )
            selftest = int(self._library.makhos_search_compact_move_selftest())
            if selftest != 0:
                raise RuntimeError(
                    f"native compact move self-test failed ({selftest})"
                )
        else:
            self.tt_entry_bytes = LEGACY_NATIVE_TT_ENTRY_BYTES
        if self.abi_version >= 6:
            self._configure_search_telemetry_signatures()
        if persistent:
            self._configure_persistent_signatures()
            if shared_with is not None:
                shared_with._require_open()
                if self.path.resolve() != shared_with.path.resolve():
                    raise ValueError("shared TT workers must use the same DLL")
                if self.hash_power != shared_with.hash_power:
                    raise ValueError("shared TT workers must use one hash power")
                if not self.supports_shared_tt:
                    raise RuntimeError("shared TT is unavailable in this DLL")
                handle = self._library.makhos_search_create_shared(
                    shared_with._require_handle()
                )
            else:
                handle = self._library.makhos_search_create(self.hash_power)
            if not handle:
                raise MemoryError("native persistent search allocation failed")
            self._handle = int(handle)

    def _configure_nnue_candidate(self, model: str | Path | None) -> None:
        library = self._library
        candidate = all(
            hasattr(library, name)
            for name in (
                "makhos_search_nnue_load_model",
                "makhos_search_nnue_ready",
                "makhos_search_nnue_feature_abi",
                "makhos_search_nnue_model_sha256",
                "makhos_search_nnue_source_model_sha256",
                "makhos_search_nnue_last_error",
            )
        )
        if not candidate:
            if model is not None:
                raise ValueError("nnue_model requires an NNUE candidate DLL")
            return
        if model is None:
            raise ValueError("NNUE candidate DLL requires an explicit nnue_model")
        path = Path(model)
        if not path.is_file():
            raise FileNotFoundError(f"NNUE model not found: {path}")
        library.makhos_search_nnue_load_model.argtypes = [ctypes.c_char_p]
        library.makhos_search_nnue_load_model.restype = ctypes.c_int
        library.makhos_search_nnue_ready.argtypes = []
        library.makhos_search_nnue_ready.restype = ctypes.c_int
        for name in (
            "makhos_search_nnue_feature_abi",
            "makhos_search_nnue_model_sha256",
            "makhos_search_nnue_source_model_sha256",
            "makhos_search_nnue_last_error",
        ):
            function = getattr(library, name)
            function.argtypes = []
            function.restype = ctypes.c_char_p
        status = int(
            library.makhos_search_nnue_load_model(
                str(path.resolve()).encode("utf-8")
            )
        )
        if status != 0 or not library.makhos_search_nnue_ready():
            encoded = library.makhos_search_nnue_last_error()
            detail = encoded.decode("utf-8", errors="replace") if encoded else ""
            raise RuntimeError(
                f"NNUE candidate model load failed ({status})"
                + (f": {detail}" if detail else "")
            )
        self.nnue_enabled = True
        self.nnue_model_path = path.resolve()
        self.nnue_model_sha256 = (
            library.makhos_search_nnue_model_sha256().decode("ascii")
        )
        self.nnue_source_model_sha256 = (
            library.makhos_search_nnue_source_model_sha256().decode("ascii")
        )
        self.nnue_feature_abi = (
            library.makhos_search_nnue_feature_abi().decode("ascii")
        )
        self.supports_nnue_telemetry = hasattr(
            library, "makhos_search_nnue_telemetry"
        )
        if self.supports_nnue_telemetry:
            library.makhos_search_nnue_telemetry.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint64),
                ctypes.POINTER(ctypes.c_uint64),
                ctypes.POINTER(ctypes.c_uint64),
            ]
            library.makhos_search_nnue_telemetry.restype = ctypes.c_int

    def _configure_signatures(self) -> None:
        library = self._library
        library.makhos_search_abi_version.argtypes = []
        library.makhos_search_abi_version.restype = ctypes.c_int
        library.makhos_evaluate.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        library.makhos_evaluate.restype = ctypes.c_int
        library.makhos_search.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_HistoryEntry),
            ctypes.c_uint32,
            ctypes.POINTER(_SearchResult),
        ]
        library.makhos_search.restype = ctypes.c_int

    def _configure_persistent_signatures(self) -> None:
        library = self._library
        library.makhos_search_create.argtypes = [ctypes.c_int]
        library.makhos_search_create.restype = ctypes.c_void_p
        library.makhos_search_destroy.argtypes = [ctypes.c_void_p]
        library.makhos_search_destroy.restype = None
        library.makhos_search_clear.argtypes = [ctypes.c_void_p]
        library.makhos_search_clear.restype = ctypes.c_int
        library.makhos_search_run.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_HistoryEntry),
            ctypes.c_uint32,
            ctypes.POINTER(_SearchResult),
        ]
        library.makhos_search_run.restype = ctypes.c_int
        self.supports_iir_census = hasattr(library, "makhos_search_iir_census")
        if self.supports_iir_census:
            library.makhos_search_iir_census.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_IirCensusTelemetry),
            ]
            library.makhos_search_iir_census.restype = ctypes.c_int
        self.supports_repetition_census = hasattr(
            library, "makhos_search_repetition_census"
        )
        if self.supports_repetition_census:
            library.makhos_search_repetition_census.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_RepetitionCensusTelemetry),
            ]
            library.makhos_search_repetition_census.restype = ctypes.c_int
        self.supports_tablebase_draw = hasattr(
            library, "makhos_search_attach_tablebase"
        )
        if self.supports_tablebase_draw:
            library.makhos_search_attach_tablebase.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            library.makhos_search_attach_tablebase.restype = ctypes.c_int
            library.makhos_search_tablebase_counters.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint64),
            ]
            library.makhos_search_tablebase_counters.restype = ctypes.c_int
        self.supports_fixed_search = hasattr(library, "makhos_search_fixed")
        if self.supports_fixed_search:
            library.makhos_search_fixed.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(_HistoryEntry),
                ctypes.c_uint32,
                ctypes.POINTER(_SearchResult),
            ]
            library.makhos_search_fixed.restype = ctypes.c_int
        self.supports_window_search = hasattr(library, "makhos_search_window")
        if self.supports_window_search:
            library.makhos_search_window.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(_HistoryEntry),
                ctypes.c_uint32,
                ctypes.POINTER(_SearchResult),
            ]
            library.makhos_search_window.restype = ctypes.c_int
        if all(
            hasattr(library, name)
            for name in (
                "makhos_search_shared_tt_available",
                "makhos_search_create_shared",
                "makhos_search_clear_local",
            )
        ):
            library.makhos_search_shared_tt_available.argtypes = []
            library.makhos_search_shared_tt_available.restype = ctypes.c_int
            self.supports_shared_tt = bool(
                library.makhos_search_shared_tt_available()
            )
            library.makhos_search_create_shared.argtypes = [ctypes.c_void_p]
            library.makhos_search_create_shared.restype = ctypes.c_void_p
            library.makhos_search_clear_local.argtypes = [ctypes.c_void_p]
            library.makhos_search_clear_local.restype = ctypes.c_int
        if all(
            hasattr(library, name)
            for name in (
                "makhos_search_session_available",
                "makhos_search_session_begin",
                "makhos_search_session_attach",
                "makhos_search_session_advance",
                "makhos_search_session_end",
            )
        ):
            library.makhos_search_session_available.argtypes = []
            library.makhos_search_session_available.restype = ctypes.c_int
            self.supports_iterative_session = bool(
                library.makhos_search_session_available()
            )
            library.makhos_search_session_begin.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(_HistoryEntry),
                ctypes.c_uint32,
                ctypes.POINTER(_SearchResult),
            ]
            library.makhos_search_session_begin.restype = ctypes.c_int
            library.makhos_search_session_attach.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(_HistoryEntry),
                ctypes.c_uint32,
                ctypes.POINTER(_SearchResult),
            ]
            library.makhos_search_session_attach.restype = ctypes.c_int
            library.makhos_search_session_advance.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(_SearchResult),
            ]
            library.makhos_search_session_advance.restype = ctypes.c_int
            library.makhos_search_session_end.argtypes = [ctypes.c_void_p]
            library.makhos_search_session_end.restype = ctypes.c_int

    def _configure_telemetry_signatures(self) -> None:
        library = self._library
        library.makhos_search_memory_bytes.argtypes = [ctypes.c_void_p]
        library.makhos_search_memory_bytes.restype = ctypes.c_uint64
        library.makhos_search_workspace_lists.argtypes = [ctypes.c_void_p]
        library.makhos_search_workspace_lists.restype = ctypes.c_uint64

    def _configure_layout_signatures(self) -> None:
        library = self._library
        library.makhos_search_tt_entry_bytes.argtypes = []
        library.makhos_search_tt_entry_bytes.restype = ctypes.c_uint64
        library.makhos_search_compact_move_selftest.argtypes = []
        library.makhos_search_compact_move_selftest.restype = ctypes.c_int

    def _configure_search_telemetry_signatures(self) -> None:
        library = self._library
        library.makhos_search_telemetry.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SearchTelemetry),
        ]
        library.makhos_search_telemetry.restype = ctypes.c_int

    @property
    def persistent(self) -> bool:
        return self._handle is not None

    @property
    def allocated_hash_mb(self) -> float:
        return hash_megabytes_for_power(
            self.hash_power,
            entry_bytes=self.tt_entry_bytes,
        )

    @property
    def memory_bytes(self) -> int | None:
        """Return persistent native allocation size when ABI telemetry exists."""

        with self._lock:
            self._require_open()
            if self.abi_version < 4 or not self.persistent:
                return None
            return int(
                self._library.makhos_search_memory_bytes(self._require_handle())
            )

    @property
    def workspace_lists(self) -> int | None:
        """Return the number of lazily allocated per-ply move lists."""

        with self._lock:
            self._require_open()
            if self.abi_version < 4 or not self.persistent:
                return None
            return int(
                self._library.makhos_search_workspace_lists(
                    self._require_handle()
                )
            )

    def _read_telemetry_locked(self) -> NativeSearchTelemetry | None:
        if self.abi_version < 6 or not self.persistent:
            return None
        raw = _SearchTelemetry()
        status = self._library.makhos_search_telemetry(
            self._require_handle(), ctypes.byref(raw)
        )
        if status != 0:
            raise RuntimeError(
                f"native search telemetry failed with status {status}"
            )
        return _unpack_telemetry(raw)

    @property
    def telemetry(self) -> NativeSearchTelemetry | None:
        """Return counters for the most recent persistent native search."""

        with self._lock:
            self._require_open()
            return self._read_telemetry_locked()

    @property
    def iir_census(self) -> NativeIirCensusTelemetry | None:
        """Return measurement-only IIR eligibility counters when available."""

        with self._lock:
            self._require_open()
            if not self.persistent or not self.supports_iir_census:
                return None
            raw = _IirCensusTelemetry()
            status = self._library.makhos_search_iir_census(
                self._require_handle(), ctypes.byref(raw)
            )
            if status != 0:
                raise RuntimeError(
                    f"native IIR census failed with status {status}"
                )
            return _unpack_iir_census(raw)

    @property
    def repetition_census(self) -> NativeRepetitionCensusTelemetry | None:
        """Return measurement-only repetition-scan counters when available."""

        with self._lock:
            self._require_open()
            if not self.persistent or not self.supports_repetition_census:
                return None
            raw = _RepetitionCensusTelemetry()
            status = self._library.makhos_search_repetition_census(
                self._require_handle(), ctypes.byref(raw)
            )
            if status != 0:
                raise RuntimeError(
                    "native repetition census failed with status " f"{status}"
                )
            return _unpack_repetition_census(raw)

    def clear(self) -> None:
        """Clear persistent TT/history at a new-game boundary."""
        with self._lock:
            self._require_open()
            if not self.persistent:
                return
            handle = self._require_handle()
            status = self._library.makhos_search_clear(handle)
            if status != 0:
                raise RuntimeError(f"native search clear failed with status {status}")
            self._iterative_session_active = False

    def clear_local(self) -> None:
        """Clear worker-local heuristics without clearing a shared TT."""

        with self._lock:
            self._require_open()
            if not self.persistent:
                return
            if not self.supports_shared_tt:
                raise RuntimeError("local-only clear is unavailable in this DLL")
            status = self._library.makhos_search_clear_local(
                self._require_handle()
            )
            if status != 0:
                raise RuntimeError(
                    f"native local search clear failed with status {status}"
                )

    def attach_tablebase(self, tablebase) -> None:
        """Return exact tablebase draws at non-root nodes of later searches.

        Needs a persistent search from a ``MAKHOS_SEARCH_TB_DRAW`` build. The
        native set stays retained until detach or close; keep ``tablebase``
        (a NativeEndgameTablebase) open meanwhile.
        """
        with self._lock:
            self._require_open()
            if not self.persistent:
                raise ValueError("tablebase draw probes require persistent search")
            if not self.supports_tablebase_draw:
                raise RuntimeError("native search library lacks tablebase draw probes")
            self._detach_tablebase_locked()
            address, probe, release = tablebase.borrow_for_search()
            status = self._library.makhos_search_attach_tablebase(
                self._require_handle(),
                address,
                probe,
                tablebase.no_progress_plies,
                tablebase.max_pieces,
            )
            if status != 0:
                release()
                raise RuntimeError(f"native tablebase attach failed ({status})")
            self._tablebase = tablebase
            self._tablebase_release = release
            self._tablebase_errors_seen = self._tablebase_counters_locked()[2]

    def detach_tablebase(self) -> None:
        with self._lock:
            self._detach_tablebase_locked()

    def tablebase_counters(self) -> tuple[int, int, int]:
        """Cumulative tablebase probes, exact-draw cutoffs and probe errors."""
        with self._lock:
            self._require_open()
            return self._tablebase_counters_locked()

    def _detach_tablebase_locked(self) -> None:
        release = self._tablebase_release
        if release is None:
            return
        if self._handle is not None:
            self._library.makhos_search_attach_tablebase(self._handle, None, None, 0, 0)
        self._tablebase = None
        self._tablebase_release = None
        release()

    def _tablebase_counters_locked(self) -> tuple[int, int, int]:
        if not self.supports_tablebase_draw or self._handle is None:
            return (0, 0, 0)
        values = (ctypes.c_uint64 * 3)()
        if self._library.makhos_search_tablebase_counters(self._handle, values) != 0:
            raise RuntimeError("native tablebase counters failed")
        return (int(values[0]), int(values[1]), int(values[2]))

    def _check_tablebase_errors_locked(self) -> None:
        """Fail closed: a corrupt or invalid probe must not pass as a result."""
        if self._tablebase_release is None:
            return
        errors = self._tablebase_counters_locked()[2]
        if errors != self._tablebase_errors_seen:
            self._tablebase_errors_seen = errors
            raise RuntimeError("native tablebase probe failed during search")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._detach_tablebase_locked()
            if self._handle is not None:
                self._library.makhos_search_destroy(self._handle)
                self._handle = None
            self._iterative_session_active = False
            self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("native search is closed")

    def _require_handle(self) -> int:
        if self._handle is None:
            raise RuntimeError("native search is closed")
        return self._handle

    def __enter__(self) -> "NativeSearch":
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
        red, black, kings = _bitboards(state)
        score = ctypes.c_int()
        status = self._library.makhos_evaluate(
            red,
            black,
            kings,
            state.turn,
            state.reversible_plies,
            ctypes.byref(score),
        )
        if status != 0:
            raise RuntimeError(f"native evaluation failed with status {status}")
        return int(score.value)

    def nnue_telemetry(self) -> tuple[int, int, int] | None:
        """Return root refreshes, child updates, and NNUE evaluations."""

        self._require_open()
        if not self.nnue_enabled or not self.supports_nnue_telemetry:
            return None
        if not self.persistent:
            raise RuntimeError("NNUE telemetry requires persistent search")
        refreshes = ctypes.c_uint64()
        updates = ctypes.c_uint64()
        evaluations = ctypes.c_uint64()
        status = self._library.makhos_search_nnue_telemetry(
            self._require_handle(),
            ctypes.byref(refreshes),
            ctypes.byref(updates),
            ctypes.byref(evaluations),
        )
        if status != 0:
            raise RuntimeError(f"NNUE telemetry failed ({status})")
        return int(refreshes.value), int(updates.value), int(evaluations.value)

    @staticmethod
    def _decode_native_result(
        result: _SearchResult,
        telemetry: NativeSearchTelemetry | None,
    ) -> NativeSearchResult:
        move = _unpack_move(result.best_move)
        pv_length = min(int(result.pv_len), MAX_PLY)
        pv = tuple(_unpack_move(result.pv[index]) for index in range(pv_length))
        if not pv or pv[0] != move:
            pv = (move,) + tuple(item for item in pv if item != move)
        return NativeSearchResult(
            move=move,
            score=int(result.score),
            depth=int(result.depth),
            nodes=int(result.nodes),
            elapsed_ms=int(result.elapsed_ms),
            pv=pv,
            telemetry=telemetry,
            common_depth=int(result.depth),
        )

    def begin_iterative_session(
        self,
        state: State,
        *,
        depth: int,
        time_ms: int | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        history: Mapping[tuple[tuple[int, ...], int], int] | None = None,
    ) -> NativeSearchResult:
        """Begin a candidate-only native iterative-deepening session.

        The session owns a copy of the supplied history in native memory and
        can subsequently advance to deeper complete iterations without
        reconstructing the earlier iterative layers.
        """

        if not self.persistent or not self.supports_iterative_session:
            raise RuntimeError("iterative native session is unavailable in this DLL")
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        with self._lock:
            self._require_open()
            status = self._library.makhos_search_session_begin(
                self._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                depth,
                time_ms or 0,
                no_progress_plies,
                repetition_limit or 0,
                history_array if history_items else None,
                len(history_items),
                ctypes.byref(result),
            )
            telemetry = (
                self._read_telemetry_locked() if status == 0 else None
            )
            self._iterative_session_active = status == 0
        if status != 0:
            messages = {
                1: "invalid iterative-session arguments",
                2: "native iterative-session allocation failed",
                4: "position is terminal",
            }
            raise RuntimeError(
                messages.get(status, f"native iterative session failed ({status})")
            )
        return self._decode_native_result(result, telemetry)

    def attach_iterative_session(
        self,
        state: State,
        *,
        completed_depth: int,
        depth: int,
        time_ms: int | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        history: Mapping[tuple[tuple[int, ...], int], int] | None = None,
    ) -> NativeSearchResult:
        """Continue from a completed ordinary search on this same position.

        This candidate-only API preserves the persistent worker's TT and
        heuristics, then advances only the next iterative-deepening layer.
        """

        if not self.persistent or not self.supports_iterative_session:
            raise RuntimeError("iterative native session is unavailable in this DLL")
        if completed_depth < 1 or completed_depth >= depth:
            raise ValueError("completed_depth must be in 1..depth - 1")
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        with self._lock:
            self._require_open()
            status = self._library.makhos_search_session_attach(
                self._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                completed_depth,
                depth,
                time_ms or 0,
                no_progress_plies,
                repetition_limit or 0,
                history_array if history_items else None,
                len(history_items),
                ctypes.byref(result),
            )
            telemetry = (
                self._read_telemetry_locked() if status == 0 else None
            )
            self._iterative_session_active = status == 0
        if status != 0:
            messages = {
                1: "invalid iterative-session attach arguments",
                2: "native iterative-session allocation failed",
                4: "position is terminal",
            }
            raise RuntimeError(
                messages.get(status, f"native iterative-session attach failed ({status})")
            )
        return self._decode_native_result(result, telemetry)

    def advance_iterative_session(self, *, depth: int) -> NativeSearchResult:
        """Advance an active native iterative session through ``depth``."""

        if not self.persistent or not self.supports_iterative_session:
            raise RuntimeError("iterative native session is unavailable in this DLL")
        result = _SearchResult()
        with self._lock:
            self._require_open()
            if not self._iterative_session_active:
                raise RuntimeError("native iterative session is not active")
            status = self._library.makhos_search_session_advance(
                self._require_handle(), depth, ctypes.byref(result)
            )
            telemetry = (
                self._read_telemetry_locked() if status == 0 else None
            )
        if status != 0:
            raise RuntimeError(f"native iterative session failed ({status})")
        return self._decode_native_result(result, telemetry)

    def end_iterative_session(self) -> None:
        if not self.persistent or not self.supports_iterative_session:
            return
        with self._lock:
            self._require_open()
            if not self._iterative_session_active:
                return
            status = self._library.makhos_search_session_end(
                self._require_handle()
            )
            self._iterative_session_active = False
        if status != 0:
            raise RuntimeError(f"native iterative-session close failed ({status})")

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
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        common_args = (
            red,
            black,
            kings,
            state.turn,
            state.reversible_plies,
            depth,
            time_ms or 0,
            no_progress_plies,
            repetition_limit or 0,
        )
        with self._lock:
            self._require_open()
            if self.persistent:
                self._iterative_session_active = False
                status = self._library.makhos_search_run(
                    self._require_handle(),
                    *common_args,
                    history_array if history_items else None,
                    len(history_items),
                    ctypes.byref(result),
                )
            else:
                status = self._library.makhos_search(
                    *common_args,
                    self.hash_power,
                    history_array if history_items else None,
                    len(history_items),
                    ctypes.byref(result),
                )
            telemetry = (
                self._read_telemetry_locked() if status == 0 else None
            )
            if status == 0:
                self._check_tablebase_errors_locked()
        if status != 0:
            messages = {
                1: "invalid search arguments",
                2: "native search allocation failed",
                4: "position is terminal",
            }
            raise RuntimeError(messages.get(status, f"native search failed ({status})"))
        move = _unpack_move(result.best_move)
        pv_length = min(int(result.pv_len), MAX_PLY)
        pv = tuple(_unpack_move(result.pv[index]) for index in range(pv_length))
        if not pv or pv[0] != move:
            pv = (move,) + tuple(item for item in pv if item != move)
        return NativeSearchResult(
            move=move,
            score=int(result.score),
            depth=int(result.depth),
            nodes=int(result.nodes),
            elapsed_ms=int(result.elapsed_ms),
            pv=pv,
            telemetry=telemetry,
            common_depth=int(result.depth),
        )

    def search_fixed(
        self,
        state: State,
        *,
        depth: int,
        time_ms: int | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        history: Mapping[tuple[tuple[int, ...], int], int] | None = None,
    ) -> NativeSearchResult:
        """Search exactly one depth using the persistent TT or time out."""

        if not self.persistent or not self.supports_fixed_search:
            raise RuntimeError("fixed-depth search is unavailable in this DLL")
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        with self._lock:
            self._require_open()
            status = self._library.makhos_search_fixed(
                self._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                depth,
                time_ms or 0,
                no_progress_plies,
                repetition_limit or 0,
                history_array if history_items else None,
                len(history_items),
                ctypes.byref(result),
            )
            telemetry = (
                self._read_telemetry_locked() if status == 0 else None
            )
            if status in (0, 5):
                self._check_tablebase_errors_locked()
        if status == 5:
            raise TimeoutError("fixed-depth native search timed out")
        if status != 0:
            messages = {
                1: "invalid search arguments",
                2: "native search allocation failed",
                4: "position is terminal",
            }
            raise RuntimeError(messages.get(status, f"native search failed ({status})"))
        move = _unpack_move(result.best_move)
        pv_length = min(int(result.pv_len), MAX_PLY)
        pv = tuple(_unpack_move(result.pv[index]) for index in range(pv_length))
        if not pv or pv[0] != move:
            pv = (move,) + tuple(item for item in pv if item != move)
        return NativeSearchResult(
            move=move,
            score=int(result.score),
            depth=int(result.depth),
            nodes=int(result.nodes),
            elapsed_ms=int(result.elapsed_ms),
            pv=pv,
            telemetry=telemetry,
            common_depth=int(result.depth),
        )

    def search_window(
        self,
        state: State,
        *,
        depth: int,
        alpha: int,
        beta: int,
        time_ms: int | None,
        no_progress_plies: int,
        repetition_limit: int | None,
        history: Mapping[tuple[tuple[int, ...], int], int] | None = None,
    ) -> NativeSearchResult:
        """Search one exact depth inside an explicit alpha-beta window."""

        if not self.persistent or not self.supports_window_search:
            raise RuntimeError("windowed search is unavailable in this DLL")
        if alpha >= beta:
            raise ValueError("alpha must be less than beta")
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        with self._lock:
            self._require_open()
            status = self._library.makhos_search_window(
                self._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                depth,
                alpha,
                beta,
                time_ms or 0,
                no_progress_plies,
                repetition_limit or 0,
                history_array if history_items else None,
                len(history_items),
                ctypes.byref(result),
            )
            telemetry = (
                self._read_telemetry_locked() if status == 0 else None
            )
            if status in (0, 5):
                self._check_tablebase_errors_locked()
        if status == 5:
            raise TimeoutError("windowed native search timed out")
        if status != 0:
            messages = {
                1: "invalid search arguments",
                2: "native search allocation failed",
                4: "position is terminal",
            }
            raise RuntimeError(messages.get(status, f"native search failed ({status})"))
        move = _unpack_move(result.best_move)
        pv_length = min(int(result.pv_len), MAX_PLY)
        pv = tuple(_unpack_move(result.pv[index]) for index in range(pv_length))
        if not pv or pv[0] != move:
            pv = (move,) + tuple(item for item in pv if item != move)
        return NativeSearchResult(
            move=move,
            score=int(result.score),
            depth=int(result.depth),
            nodes=int(result.nodes),
            elapsed_ms=int(result.elapsed_ms),
            pv=pv,
            telemetry=telemetry,
            common_depth=int(result.depth),
        )


class NativeLazySmpSearch:
    """Candidate-only native Lazy-SMP search handle.

    The returned result is always native worker zero's completed iteration.
    Helper workers have private search state and share only the guarded native
    TT, so this class must not be substituted for the accepted engine path
    without the full multi-thread strength gate.
    """

    def __init__(
        self,
        library: str | Path,
        *,
        threads: int,
        hash_mb: int,
    ) -> None:
        if not 1 <= threads <= _NATIVE_LAZY_SMP_MAX_THREADS:
            raise ValueError("lazy SMP threads must be in 1..12")
        self.path = Path(library)
        if not self.path.is_file():
            raise FileNotFoundError(f"native search library not found: {self.path}")
        self.threads = threads
        self.requested_hash_mb = hash_mb
        self._library = ctypes.CDLL(str(self.path.resolve()))
        self._lock = threading.RLock()
        self._handle: int | None = None
        self._closed = False
        required = (
            "makhos_lazy_smp_available",
            "makhos_lazy_smp_create",
            "makhos_lazy_smp_destroy",
            "makhos_lazy_smp_clear",
            "makhos_lazy_smp_run",
            "makhos_lazy_smp_memory_bytes",
            "makhos_lazy_smp_stats",
        )
        if not all(hasattr(self._library, name) for name in required):
            raise RuntimeError("native Lazy-SMP is unavailable in this DLL")
        self._library.makhos_search_abi_version.argtypes = []
        self._library.makhos_search_abi_version.restype = ctypes.c_int
        self.abi_version = int(self._library.makhos_search_abi_version())
        if not MIN_SEARCH_ABI_VERSION <= self.abi_version <= SEARCH_ABI_VERSION:
            raise RuntimeError(
                "native search ABI mismatch: expected "
                f"{MIN_SEARCH_ABI_VERSION}..{SEARCH_ABI_VERSION}, got {self.abi_version}"
            )
        self.tt_entry_bytes = native_tt_entry_bytes(self.path)
        self.hash_power = hash_power_for_megabytes(
            hash_mb,
            partitions=1,
            entry_bytes=self.tt_entry_bytes,
        )
        self.allocated_hash_mb = hash_megabytes_for_power(
            self.hash_power,
            partitions=1,
            entry_bytes=self.tt_entry_bytes,
        )
        self._configure_signatures()
        if not self._library.makhos_lazy_smp_available():
            raise RuntimeError("native Lazy-SMP is unavailable in this DLL")
        handle = self._library.makhos_lazy_smp_create(
            self.threads,
            self.hash_power,
        )
        if not handle:
            raise RuntimeError("native Lazy-SMP allocation failed")
        self._handle = int(handle)

    def _configure_signatures(self) -> None:
        library = self._library
        library.makhos_lazy_smp_available.argtypes = []
        library.makhos_lazy_smp_available.restype = ctypes.c_int
        library.makhos_lazy_smp_create.argtypes = [ctypes.c_int, ctypes.c_int]
        library.makhos_lazy_smp_create.restype = ctypes.c_void_p
        library.makhos_lazy_smp_destroy.argtypes = [ctypes.c_void_p]
        library.makhos_lazy_smp_destroy.restype = None
        library.makhos_lazy_smp_clear.argtypes = [ctypes.c_void_p]
        library.makhos_lazy_smp_clear.restype = ctypes.c_int
        library.makhos_lazy_smp_run.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_HistoryEntry),
            ctypes.c_uint32,
            ctypes.POINTER(_SearchResult),
        ]
        library.makhos_lazy_smp_run.restype = ctypes.c_int
        library.makhos_lazy_smp_memory_bytes.argtypes = [ctypes.c_void_p]
        library.makhos_lazy_smp_memory_bytes.restype = ctypes.c_uint64
        library.makhos_lazy_smp_stats.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_LazySmpStats),
        ]
        library.makhos_lazy_smp_stats.restype = ctypes.c_int

    def _require_open(self) -> None:
        if self._closed or self._handle is None:
            raise RuntimeError("native Lazy-SMP search is closed")

    def _require_handle(self) -> int:
        self._require_open()
        assert self._handle is not None
        return self._handle

    @property
    def memory_bytes(self) -> int:
        with self._lock:
            return int(
                self._library.makhos_lazy_smp_memory_bytes(
                    self._require_handle()
                )
            )

    @property
    def stats(self) -> NativeLazySmpStats:
        raw = _LazySmpStats()
        with self._lock:
            status = self._library.makhos_lazy_smp_stats(
                self._require_handle(),
                ctypes.byref(raw),
            )
        if status != 0:
            raise RuntimeError(f"native Lazy-SMP stats failed ({status})")
        return _unpack_lazy_smp_stats(raw)

    def clear(self) -> None:
        with self._lock:
            status = self._library.makhos_lazy_smp_clear(self._require_handle())
        if status != 0:
            raise RuntimeError(f"native Lazy-SMP clear failed ({status})")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._handle is not None:
                self._library.makhos_lazy_smp_destroy(self._handle)
                self._handle = None
            self._closed = True

    def __enter__(self) -> "NativeLazySmpSearch":
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
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        with self._lock:
            status = self._library.makhos_lazy_smp_run(
                self._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                depth,
                time_ms or 0,
                no_progress_plies,
                repetition_limit or 0,
                history_array if history_items else None,
                len(history_items),
                ctypes.byref(result),
            )
        if status != 0:
            messages = {
                1: "invalid Lazy-SMP search arguments",
                2: "native Lazy-SMP allocation or worker failure",
                4: "position is terminal",
            }
            raise RuntimeError(
                messages.get(status, f"native Lazy-SMP search failed ({status})")
            )
        return NativeSearch._decode_native_result(result, None)


class NativeRootPvsShadowSearch:
    """Candidate-only authoritative main search with shadow root scouts.

    Helper results are measurement-only: the returned move, score, PV, depth,
    and node count always come from the ordinary main search context.
    """

    def __init__(
        self,
        library: str | Path,
        *,
        threads: int,
        hash_mb: int,
    ) -> None:
        if not 1 <= threads <= _NATIVE_LAZY_SMP_MAX_THREADS:
            raise ValueError("root-PVS shadow threads must be in 1..12")
        if hash_mb < 1:
            raise ValueError("root-PVS shadow Hash must be positive")
        self.path = Path(library)
        if not self.path.is_file():
            raise FileNotFoundError(f"native search library not found: {self.path}")
        self.threads = threads
        self.requested_hash_mb = hash_mb
        self._library = ctypes.CDLL(str(self.path.resolve()))
        self._lock = threading.RLock()
        self._handle: int | None = None
        self._closed = False
        required = (
            "makhos_root_pvs_shadow_available",
            "makhos_root_pvs_shadow_backend",
            "makhos_root_pvs_shadow_create",
            "makhos_root_pvs_shadow_destroy",
            "makhos_root_pvs_shadow_clear",
            "makhos_root_pvs_shadow_run",
            "makhos_root_pvs_shadow_stats",
            "makhos_root_pvs_shadow_memory_bytes",
        )
        if not all(hasattr(self._library, name) for name in required):
            raise RuntimeError("native root-PVS shadow search is unavailable")
        self._configure_signatures()
        if not self._library.makhos_root_pvs_shadow_available():
            raise RuntimeError("native root-PVS shadow search is unavailable")
        backend = self._library.makhos_root_pvs_shadow_backend()
        self.backend = backend.decode("ascii")
        handle = self._library.makhos_root_pvs_shadow_create(threads, hash_mb)
        if not handle:
            raise MemoryError("native root-PVS shadow allocation failed")
        self._handle = int(handle)

    def _configure_signatures(self) -> None:
        library = self._library
        library.makhos_root_pvs_shadow_available.argtypes = []
        library.makhos_root_pvs_shadow_available.restype = ctypes.c_int
        library.makhos_root_pvs_shadow_backend.argtypes = []
        library.makhos_root_pvs_shadow_backend.restype = ctypes.c_char_p
        library.makhos_root_pvs_shadow_create.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
        ]
        library.makhos_root_pvs_shadow_create.restype = ctypes.c_void_p
        library.makhos_root_pvs_shadow_destroy.argtypes = [ctypes.c_void_p]
        library.makhos_root_pvs_shadow_destroy.restype = None
        library.makhos_root_pvs_shadow_clear.argtypes = [ctypes.c_void_p]
        library.makhos_root_pvs_shadow_clear.restype = ctypes.c_int
        library.makhos_root_pvs_shadow_run.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_HistoryEntry),
            ctypes.c_uint32,
            ctypes.POINTER(_SearchResult),
        ]
        library.makhos_root_pvs_shadow_run.restype = ctypes.c_int
        library.makhos_root_pvs_shadow_stats.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_RootPvsShadowStats),
        ]
        library.makhos_root_pvs_shadow_stats.restype = ctypes.c_int
        library.makhos_root_pvs_shadow_memory_bytes.argtypes = [ctypes.c_void_p]
        library.makhos_root_pvs_shadow_memory_bytes.restype = ctypes.c_uint64

    def _require_handle(self) -> int:
        if self._closed or self._handle is None:
            raise RuntimeError("native root-PVS shadow search is closed")
        return self._handle

    @property
    def stats(self) -> NativeRootPvsShadowStats:
        raw = _RootPvsShadowStats()
        with self._lock:
            status = self._library.makhos_root_pvs_shadow_stats(
                self._require_handle(),
                ctypes.byref(raw),
            )
        if status != 0:
            raise RuntimeError(f"native root-PVS shadow stats failed ({status})")
        return _unpack_root_pvs_shadow_stats(raw)

    @property
    def allocated_hash_mb(self) -> float:
        return self.stats.allocated_tt_bytes / (1024 * 1024)

    @property
    def memory_bytes(self) -> int:
        with self._lock:
            return int(
                self._library.makhos_root_pvs_shadow_memory_bytes(
                    self._require_handle()
                )
            )

    def clear(self) -> None:
        with self._lock:
            status = self._library.makhos_root_pvs_shadow_clear(
                self._require_handle()
            )
        if status != 0:
            raise RuntimeError(f"native root-PVS shadow clear failed ({status})")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._handle is not None:
                self._library.makhos_root_pvs_shadow_destroy(self._handle)
                self._handle = None
            self._closed = True

    def __enter__(self) -> "NativeRootPvsShadowSearch":
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
        red, black, kings = _bitboards(state)
        history_items = [
            (key, count)
            for key, count in (history or {}).items()
            if count > 0
        ]
        history_array = (_HistoryEntry * len(history_items))()
        for index, ((board, turn), count) in enumerate(history_items):
            item_red, item_black, item_kings = _board_bitboards(board)
            history_array[index] = _HistoryEntry(
                item_red,
                item_black,
                item_kings,
                turn,
                min(int(count), 255),
                (ctypes.c_uint8 * 2)(0, 0),
            )
        result = _SearchResult()
        with self._lock:
            status = self._library.makhos_root_pvs_shadow_run(
                self._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                depth,
                time_ms or 0,
                no_progress_plies,
                repetition_limit or 0,
                history_array if history_items else None,
                len(history_items),
                ctypes.byref(result),
            )
        if status != 0:
            messages = {
                1: "invalid root-PVS shadow search arguments",
                2: "native root-PVS shadow main-search failure",
                4: "position is terminal",
            }
            raise RuntimeError(
                messages.get(status, f"native root-PVS shadow search failed ({status})")
            )
        return NativeSearch._decode_native_result(result, None)
