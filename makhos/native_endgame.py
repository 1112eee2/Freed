"""Opt-in Phase 1C reader bridge. Not used by production search yet."""
from __future__ import annotations

import ctypes as C
import hashlib
import os
from pathlib import Path
import threading

from .compact_tb3 import CompactTablebase
from .core import State, RED_MAN, RED_KING, BLACK_MAN, BLACK_KING
from .exact import Outcome
from .native_tablebase import NativeProbe

DEFAULT_LIBRARY = Path(__file__).resolve().parents[1] / (
    "build/native_endgame_c1/makhos_endgame_tb" + (".dll" if os.name == "nt" else ".so")
)


class Position(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ("red", "black", "kings", "turn", "reversible_plies")]


class Probe(C.Structure):
    _fields_ = [("struct_size", C.c_uint32), ("version", C.c_uint32),
                ("outcome", C.c_int32), ("distance", C.c_int32),
                ("material_count", C.c_uint32), ("reserved", C.c_uint32)]


class RankedInfo(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in (
        "struct_size", "version", "material_count", "no_progress_plies",
        "signature_count", "checksum_verified",
    )] + [(name, C.c_uint64) for name in (
        "file_bytes", "total_positions", "total_states", "expected_checksum",
        "file_device", "file_id",
    )]


class NativeEndgameTablebase:
    """Own a TB3 copy and/or read-only compact TB4/5/6 mappings.

    The lock protects this Python owner's lifetime only. Native search workers
    will retain their own references and probe without this Python lock.
    Prepare once, outside search deadlines. Files must stay immutable until
    close. Metadata checks are mandatory; full checksum/provenance scans are
    explicit startup operations, never performed per probe. Raw WDL carries no
    repetition history and is not itself a history-aware search proof.
    """
    max_pieces = 3

    def __init__(self, source: CompactTablebase | None = None, library=DEFAULT_LIBRARY,
                 *, ranked_paths=(), no_progress_plies: int | None = None,
                 verify_checksum: bool = False):
        self._lock = threading.RLock()
        self._handle = C.c_void_p()
        if isinstance(ranked_paths, (str, bytes, os.PathLike)):
            raise TypeError("ranked_paths must be a sequence of paths")
        paths = tuple(str(Path(path).resolve()).encode("utf-8") for path in ranked_paths)
        if len(paths) > 3 or any(b"\0" in path for path in paths):
            raise ValueError("expected at most three UTF-8 tablebase paths without NUL")
        image, clock, vectors = (source.export_native_image() if source is not None
                                 else (None, 80, 0))
        if no_progress_plies is not None:
            if source is not None and no_progress_plies != clock:
                raise ValueError("TB3 and ranked horizons must agree")
            clock = no_progress_plies
        max_clock = 126 if paths else 200
        if not isinstance(clock, int) or not 1 <= clock <= max_clock:
            raise ValueError(f"native tablebase horizon must be in 1..{max_clock}")
        if source is None and not paths:
            raise ValueError("provide TB3 or at least one ranked artifact")
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
        if hasattr(dll, "makhos_tb_set_create"):
            dll.makhos_tb_set_create.argtypes = [
                C.c_void_p, C.c_uint64, C.c_uint32, C.c_uint32,
                C.POINTER(C.c_char_p), C.c_uint32, C.c_uint32, C.POINTER(C.c_void_p),
            ]
            dll.makhos_tb_set_create.restype = C.c_int32
            dll.makhos_tb_set_ranked_info.argtypes = [
                C.c_void_p, C.c_uint32, C.POINTER(RankedInfo),
            ]
            dll.makhos_tb_set_ranked_info.restype = C.c_int32
            dll.makhos_tb_set_ranked_bytes.argtypes = [
                C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p), C.POINTER(C.c_uint64),
            ]
            dll.makhos_tb_set_ranked_bytes.restype = C.c_int32
        if paths:
            if not hasattr(dll, "makhos_tb_set_create"):
                raise ValueError("rebuild isolated C1 library for ranked reader support")
            native_paths = (C.c_char_p * len(paths))(*paths)
            status = dll.makhos_tb_set_create(
                image, len(image) if image is not None else 0, clock, vectors,
                native_paths, len(paths), bool(verify_checksum), C.byref(self._handle),
            )
        else:
            status = dll.makhos_tb3_create(image, len(image), clock, vectors,
                                          C.byref(self._handle))
        if status:
            raise ValueError(f"native tablebase preparation failed: status={status}")
        self.no_progress_plies = clock
        try:
            counts = [3] if source is not None else []
            if paths:
                for pieces in (4, 5, 6):
                    info = RankedInfo(C.sizeof(RankedInfo), 1)
                    result = dll.makhos_tb_set_ranked_info(self._handle, pieces, C.byref(info))
                    if result == 0:
                        counts.append(pieces)
                    elif result != 1:
                        raise ValueError(f"native ranked metadata failed: status={result}")
            self.piece_counts = tuple(counts)
            self.max_pieces = max(counts)
        except BaseException:
            self.close()
            raise

    def borrow_for_search(self):
        """Retain the native set for a main-search context.

        Returns the set address, the address of this library's probe and a
        release callback. The caller keeps this object open until it has
        called release, which it does exactly once.
        """
        with self._lock:
            if not self._handle:
                raise RuntimeError("native endgame tablebase is closed")
            self._dll.makhos_tb_set_retain(self._handle)
            address = self._handle.value
        probe = C.cast(self._dll.makhos_tb_set_probe, C.c_void_p).value
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                self._dll.makhos_tb_set_release(C.c_void_p(address))

        return address, probe, release

    def ranked_info(self, pieces: int) -> dict[str, int]:
        """Return metadata/identity from the mapped file, without reopening it."""
        if pieces not in (4, 5, 6):
            raise ValueError("ranked material must be 4, 5 or 6")
        with self._lock:
            if not self._handle:
                raise RuntimeError("native endgame tablebase is closed")
            if not hasattr(self._dll, "makhos_tb_set_ranked_info"):
                raise ValueError("ranked artifact is not loaded")
            info = RankedInfo(C.sizeof(RankedInfo), 1)
            status = self._dll.makhos_tb_set_ranked_info(self._handle, pieces, C.byref(info))
            if status:
                raise ValueError(f"native ranked metadata failed: status={status}")
            return {name: getattr(info, name) for name, _ in info._fields_}

    def mapped_sha256(self, pieces: int) -> str:
        """Explicit full-file scan of the actual mapping while retaining its owner."""
        with self._lock:
            self.ranked_info(pieces)  # validates material and lifetime
            address, length = C.c_void_p(), C.c_uint64()
            status = self._dll.makhos_tb_set_ranked_bytes(
                self._handle, pieces, C.byref(address), C.byref(length),
            )
            if status:
                raise ValueError(f"native mapped bytes failed: status={status}")
            digest = hashlib.sha256()
            for offset in range(0, length.value, 8 << 20):
                digest.update(C.string_at(address.value + offset,
                                          min(8 << 20, length.value - offset)))
            return digest.hexdigest()

    def verify_provenance(self, manifest_path=None):
        """Validate rules/generator binding and SHA-256 of every loaded ranked map.

        This can scan gigabytes. Call during explicit acceptance/warm-up only.
        It does not authenticate a mutable file against future external writes.
        """
        from .provenance import (DEFAULT_MANIFEST_PATH, TablebaseProvenanceError,
                                 load_provenance_manifest)
        manifest = load_provenance_manifest(
            DEFAULT_MANIFEST_PATH if manifest_path is None else manifest_path,
        )
        bindings = []
        with self._lock:
            if not self._handle:
                raise RuntimeError("native endgame tablebase is closed")
            for pieces in self.piece_counts:
                if pieces == 3:
                    continue
                info = self.ranked_info(pieces)
                binding = manifest.artifact_for(pieces, self.no_progress_plies, "compact")
                if (info["file_bytes"] != binding.file_bytes
                        or info["expected_checksum"] != binding.fnv1a64
                        or self.mapped_sha256(pieces) != binding.sha256):
                    raise TablebaseProvenanceError(f"mapped TB{pieces} provenance mismatch")
                bindings.append(binding)
        return tuple(bindings)

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
