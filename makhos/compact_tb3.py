"""Immutable TB3 WDL + distance vectors; no DLL, solver or IO during probes.

Version 1 stores a dense colex board index and deduplicated clock vectors,
compressed with zlib. Repetition history deliberately remains in search.py.
"""

from __future__ import annotations

import hashlib
from math import comb
from pathlib import Path
import struct
import zlib

from .core import RED_MAN, BLACK_MAN, RED_KING, BLACK_KING, State
from .exact import Outcome
from .native_tablebase import NativeProbe

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "data" / "tb3_np80.tb3"
MAGIC = b"MKTB3V1\0"
HEADER = struct.Struct("<8s6I32s32s32s")
U32 = struct.Struct("<I")
U16 = struct.Struct("<H")
COUNTS = tuple(comb(32, n) * (4 ** n) * 2 for n in (1, 2, 3))
BOARD_COUNT = sum(COUNTS)
OFFSETS = (0, 0, COUNTS[0], COUNTS[0] + COUNTS[1])
MAX_PAYLOAD = 64 * 1024 * 1024
PIECE_CODES = {RED_MAN: 0, BLACK_MAN: 1, RED_KING: 2, BLACK_KING: 3}


def invariant_digest(path: Path) -> bytes:
    """Bind source bytes with LF newlines, portable across Git CRLF checkouts."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest()


def board_index(state: State) -> int:
    rank = types = pieces = 0
    for square, piece in enumerate(state.board):
        if piece:
            types |= PIECE_CODES[piece] << (2 * pieces)
            pieces += 1
            rank += comb(square, pieces)
    if not 1 <= pieces <= 3:
        raise ValueError("compact TB3 probes require 1..3 total pieces")
    return OFFSETS[pieces] + (rank * (4 ** pieces) + types) * 2 + state.turn - 1


class CompactTablebase:
    max_pieces = 3

    def __init__(self, path: str | Path = DEFAULT_ARTIFACT, *, no_progress_plies: int = 80):
        self.path = Path(path).resolve()
        self._data: bytes | None = None
        with self.path.open("rb") as stream:
            encoded = stream.read(MAX_PAYLOAD + HEADER.size + 1)
        if len(encoded) < HEADER.size or len(encoded) > MAX_PAYLOAD + HEADER.size:
            raise ValueError("invalid TB3 artifact size")
        (magic, version, clock, boards, vectors, raw_size, packed_size,
         rules_sha, core_sha, payload_sha) = HEADER.unpack_from(encoded)
        if magic != MAGIC or version != 1:
            raise ValueError("unsupported TB3 artifact format/version")
        if clock != no_progress_plies or not 1 <= clock <= 200:
            raise ValueError("incompatible TB3 no-progress rule")
        if (rules_sha != invariant_digest(ROOT / "RULESET.json")
                or core_sha != invariant_digest(ROOT / "makhos/core.py")):
            raise ValueError("TB3 rules/core identity mismatch")
        stride = (clock + 1) * 2
        if (boards != BOARD_COUNT or not 1 <= vectors <= boards
                or raw_size != boards * 4 + vectors * stride
                or raw_size > MAX_PAYLOAD or len(encoded) != HEADER.size + packed_size):
            raise ValueError("invalid TB3 layout/length")
        inflater = zlib.decompressobj()
        try:
            data = inflater.decompress(encoded[HEADER.size:], raw_size + 1)
        except zlib.error as error:
            raise ValueError("corrupt TB3 compressed payload") from error
        if (len(data) != raw_size or not inflater.eof or inflater.unused_data
                or inflater.unconsumed_tail or hashlib.sha256(data).digest() != payload_sha):
            raise ValueError("TB3 payload checksum/length mismatch")
        self.no_progress_plies = clock
        self.vector_count = vectors
        self._stride = stride
        self._vector_start = boards * 4
        self.sha256 = hashlib.sha256(encoded).hexdigest()
        self.payload_bytes = len(data)
        self.file_bytes = len(encoded)
        self._data = data

    def probe(self, state: State) -> NativeProbe:
        data = self._data
        if data is None:
            raise RuntimeError("compact TB3 instance is closed")
        if not 0 <= state.reversible_plies <= self.no_progress_plies:
            raise ValueError("TB3 clock outside artifact range")
        index = board_index(state)
        vector = U32.unpack_from(data, index * 4)[0]
        if vector >= self.vector_count:
            raise ValueError("corrupt TB3 vector reference")
        value = U16.unpack_from(data, self._vector_start + vector * self._stride
                                + state.reversible_plies * 2)[0]
        if value == 0:
            return NativeProbe(Outcome.DRAW, None)
        tag, distance = value >> 14, value & 0x3fff
        if tag not in (1, 2):
            raise ValueError("invalid TB3 value/unsupported board")
        return NativeProbe(Outcome.LOSS if tag == 1 else Outcome.WIN, distance)

    def close(self) -> None:
        self._data = None

    def export_native_image(self) -> tuple[bytes, int, int]:
        """Return verified immutable payload, clock horizon and vector count.

        Native consumers must copy the image during preparation, never retain
        a borrowed Python pointer. This snapshot remains valid after close().
        """
        data = self._data
        if data is None:
            raise RuntimeError("compact TB3 instance is closed")
        return data, self.no_progress_plies, self.vector_count

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
