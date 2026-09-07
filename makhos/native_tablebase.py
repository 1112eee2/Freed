"""ctypes bridge to the persistent native three-piece exact tablebase."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import threading

from .core import BLACK_KING, BLACK_MAN, RED_KING, RED_MAN, State
from .exact import Outcome


@dataclass(frozen=True, slots=True)
class NativeProbe:
    outcome: Outcome
    distance: int | None


@dataclass(slots=True)
class _SharedNativeTablebase:
    library: ctypes.CDLL
    no_progress_plies: int
    hash_power: int
    references: int = 1


class NativeTablebase:
    """Build once, then probe exact results for positions with up to 3 pieces."""

    max_pieces = 3
    _registry_lock = threading.RLock()
    _registry: dict[Path, _SharedNativeTablebase] = {}

    def __init__(
        self,
        library: str | Path = "build/makhos_native.dll",
        *,
        no_progress_plies: int = 80,
        hash_power: int = 25,
    ) -> None:
        self.path = Path(library).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.no_progress_plies = no_progress_plies
        self.hash_power = hash_power
        self._closed = True
        self._shared: _SharedNativeTablebase | None = None
        with self._registry_lock:
            shared = self._registry.get(self.path)
            if shared is not None:
                if (
                    shared.no_progress_plies != no_progress_plies or
                    shared.hash_power != hash_power
                ):
                    raise ValueError(
                        "native tablebase is already live with an incompatible "
                        "no-progress/hash configuration"
                    )
                shared.references += 1
            else:
                native_library = ctypes.CDLL(str(self.path))
                self._configure_signatures(native_library)
                result = native_library.makhos_tb3_init(
                    no_progress_plies, hash_power
                )
                if result != 0:
                    raise RuntimeError(
                        "native tablebase initialization failed with code "
                        f"{result}"
                    )
                shared = _SharedNativeTablebase(
                    native_library,
                    no_progress_plies,
                    hash_power,
                )
                self._registry[self.path] = shared
            self._shared = shared
            self._library = shared.library
            self._closed = False

    @staticmethod
    def _configure_signatures(library: ctypes.CDLL) -> None:
        library.makhos_tb3_init.argtypes = [ctypes.c_int, ctypes.c_int]
        library.makhos_tb3_init.restype = ctypes.c_int
        library.makhos_tb3_probe.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        library.makhos_tb3_probe.restype = ctypes.c_int
        library.makhos_tb3_state_count.argtypes = []
        library.makhos_tb3_state_count.restype = ctypes.c_uint64
        library.makhos_tb3_root_count.argtypes = []
        library.makhos_tb3_root_count.restype = ctypes.c_uint64
        library.makhos_tb3_shutdown.argtypes = []
        library.makhos_tb3_shutdown.restype = None

    @property
    def state_count(self) -> int:
        with self._registry_lock:
            shared = self._require_open_locked()
            return int(shared.library.makhos_tb3_state_count())

    @property
    def root_count(self) -> int:
        with self._registry_lock:
            shared = self._require_open_locked()
            return int(shared.library.makhos_tb3_root_count())

    def probe(self, state: State) -> NativeProbe:
        red = black = kings = 0
        piece_count = 0
        for square, piece in enumerate(state.board):
            bit = 1 << square
            if piece in (RED_MAN, RED_KING):
                red |= bit
                piece_count += 1
            elif piece in (BLACK_MAN, BLACK_KING):
                black |= bit
                piece_count += 1
            if piece in (RED_KING, BLACK_KING):
                kings |= bit
        if not 1 <= piece_count <= self.max_pieces:
            raise ValueError("native tablebase probes require 1..3 total pieces")
        outcome = ctypes.c_int()
        distance = ctypes.c_int()
        with self._registry_lock:
            shared = self._require_open_locked()
            result = shared.library.makhos_tb3_probe(
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                ctypes.byref(outcome),
                ctypes.byref(distance),
            )
        if result != 0:
            raise RuntimeError(f"native tablebase probe failed with code {result}")
        return NativeProbe(
            Outcome(outcome.value),
            None if distance.value < 0 else distance.value,
        )

    def _require_open_locked(self) -> _SharedNativeTablebase:
        shared = self._shared
        if self._closed or shared is None:
            raise RuntimeError("native tablebase instance is closed")
        if self._registry.get(self.path) is not shared:
            raise RuntimeError("native tablebase shared state is unavailable")
        return shared

    def close(self) -> None:
        with self._registry_lock:
            if self._closed:
                return
            shared = self._require_open_locked()
            self._closed = True
            self._shared = None
            shared.references -= 1
            if shared.references > 0:
                return
            del self._registry[self.path]
            shared.library.makhos_tb3_shutdown()
