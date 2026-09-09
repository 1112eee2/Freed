"""Opt-in Phase 1C reader bridge. Not used by production search yet."""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import threading

from .compact_tb3 import CompactTablebase
from .core import State, RED_MAN, RED_KING, BLACK_MAN, BLACK_KING
from .exact import Outcome
from .native_tablebase import NativeProbe

DEFAULT_LIBRARY = Path(__file__).resolve().parents[1] / "build/native_endgame_c1/makhos_endgame_tb.dll"


class Position(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ("red", "black", "kings", "turn", "reversible_plies")]


class Probe(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("version", C.c_uint32),
                ("outcome", C.c_int32), ("distance", C.c_int32),
                ("material_count", C.c_uint32), ("reserved", C.c_uint32)]


class NativeEndgameTablebase:
    """Own a native immutable TB3 copy; close cannot race an active probe.

    The lock protects this Python owner's lifetime only. Native search workers
    will retain their own references and probe without this Python lock.
    """
    max_pieces = 3

    def __init__(self, source: CompactTablebase, library=DEFAULT_LIBRARY):
        self._lock = threading.RLock()
        self._handle = C.c_void_p()
        self._dll = dll = C.CDLL(str(Path(library).resolve()))
        dll.makhos_endgame_api_version.restype = C.c_uint32
        if dll.makhos_endgame_api_version() != 1:
            raise ValueError("unsupported native endgame API")
        dll.makhos_tb3_create.argtypes = [C.c_void_p, C.c_uint64, C.c_uint32,
                                         C.c_uint32, C.POINTER(C.c_void_p)]
        dll.makhos_tb3_create.restype = C.c_int32
        for name in ("makhos_tb_set_retain", "makhos_tb_set_release"):
            function = getattr(dll, name)
            function.argtypes = [C.c_void_p]
            function.restype = None
        dll.makhos_tb_set_probe.argtypes = [C.c_void_p, C.POINTER(Position), C.POINTER(Probe)]
        dll.makhos_tb_set_probe.restype = C.c_int32
        image, clock, vectors = source.export_native_image()
        status = dll.makhos_tb3_create(image, len(image), clock, vectors, C.byref(self._handle))
        if status:
            raise ValueError(f"native TB3 preparation failed: status={status}")
        self.no_progress_plies = clock

    def probe(self, state: State) -> NativeProbe:
        if len(state.board) != 32 or state.turn not in (1, 2):
            raise ValueError("invalid native tablebase position")
        if not 0 <= state.reversible_plies <= self.no_progress_plies:
            raise ValueError("native tablebase clock outside artifact range")
        red = black = kings = 0
        for square, piece in enumerate(state.board):
            if piece in (RED_MAN, RED_KING):
                red |= 1 << square
            elif piece in (BLACK_MAN, BLACK_KING):
                black |= 1 << square
            elif piece != 0:
                raise ValueError("unknown piece")
            if piece in (RED_KING, BLACK_KING):
                kings |= 1 << square
        position = Position(red, black, kings, state.turn, state.reversible_plies)
        output = Probe(C.sizeof(Probe), 1)
        with self._lock:
            if not self._handle:
                raise RuntimeError("native endgame tablebase is closed")
            status = self._dll.makhos_tb_set_probe(self._handle, C.byref(position), C.byref(output))
        if status:
            raise ValueError(f"native tablebase probe failed: status={status}")
        return NativeProbe(Outcome(output.outcome), None if output.distance < 0 else output.distance)

    def close(self):
        with self._lock:
            if self._handle:
                self._dll.makhos_tb_set_release(self._handle)
                self._handle = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
