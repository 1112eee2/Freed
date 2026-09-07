"""Memory-mapped reader for ranked four-, five-, and six-piece WDL tablebases."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import ctypes
import mmap
import os
from pathlib import Path
import struct

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    State,
)
from .exact import Outcome
from .native_tablebase import NativeProbe


_MAGIC = b"MKT4WDL1"
_COMPACT_MAGIC = b"MKTCWDL1"
_VERSION = 1
_SIGNATURE_COUNTS = {4: 25, 5: 44, 6: 70}
_HEADER = struct.Struct("<8sIIIQQ")


@lru_cache(maxsize=None)
def _canonical_signature_counts(
    piece_count: int,
) -> tuple[tuple[int, int, int, int], ...]:
    """Return the native on-disk material-signature order."""

    expected = _SIGNATURE_COUNTS.get(piece_count)
    if expected is None:
        raise ValueError("unsupported ranked tablebase piece count")
    signatures = []
    for black_men in range(piece_count + 1):
        for black_kings in range(piece_count - black_men + 1):
            for red_men in range(
                piece_count - black_men - black_kings + 1
            ):
                red_kings = (
                    piece_count - black_men - black_kings - red_men
                )
                if black_men + black_kings == 0:
                    continue
                if red_men + red_kings == 0:
                    continue
                signatures.append((
                    black_men,
                    black_kings,
                    red_men,
                    red_kings,
                ))
    signatures.sort(key=lambda counts: (counts[0] + counts[2], *counts))
    if len(signatures) != expected:
        raise RuntimeError("internal ranked signature schema mismatch")
    return tuple(signatures)


def fnv1a_file_ranges(
    path: str | Path,
    ranges: tuple[tuple[int, int], ...],
    native_library: str | Path | None = None,
) -> int | None:
    """Use the native streaming checksum helper when it is available."""

    if not ranges:
        return 1_469_598_103_934_665_603
    candidates: list[Path] = []
    if native_library is not None:
        supplied = Path(native_library).resolve()
        candidates.append(supplied)
        candidates.append(supplied.with_name("makhos_native_next.dll"))
    project_build = Path(__file__).resolve().parent.parent / "build"
    candidates.extend((
        project_build / "makhos_native.dll",
        project_build / "makhos_native_next.dll",
    ))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        try:
            library = ctypes.CDLL(str(candidate))
            function = library.makhos_fnv1a_file_ranges
        except (OSError, AttributeError):
            continue
        count = len(ranges)
        offsets = (ctypes.c_uint64 * count)(
            *(start for start, _end in ranges)
        )
        lengths = (ctypes.c_uint64 * count)(
            *(end - start for start, end in ranges)
        )
        output = ctypes.c_uint64()
        function.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        function.restype = ctypes.c_int
        result = function(
            os.fsencode(Path(path).resolve()),
            offsets,
            lengths,
            count,
            ctypes.byref(output),
        )
        if result != 0:
            raise RuntimeError(f"native file checksum failed with code {result}")
        return int(output.value)
    return None
_COMPACT_HEADER = struct.Struct("<8sIIIIQQQ")
_SIGNATURE_HEADER = struct.Struct("<4BQQ")
_PIECE_TYPE = {
    BLACK_MAN: 0,
    BLACK_KING: 1,
    RED_MAN: 2,
    RED_KING: 3,
}


@dataclass(frozen=True, slots=True)
class _Signature:
    counts: tuple[int, int, int, int]
    boards: int
    byte_count: int
    data_offset: int


def _type_allowed(piece_type: int, square: int) -> bool:
    row = square // 4
    if piece_type == 0:
        return row != 0
    if piece_type == 2:
        return row != 7
    return True


@lru_cache(maxsize=None)
def _completion_count(
    square: int,
    black_men: int,
    black_kings: int,
    red_men: int,
    red_kings: int,
) -> int:
    remaining = (black_men, black_kings, red_men, red_kings)
    if min(remaining) < 0:
        return 0
    if square == 32:
        return int(not any(remaining))
    result = _completion_count(square + 1, *remaining)
    for piece_type, count in enumerate(remaining):
        if count and _type_allowed(piece_type, square):
            child = list(remaining)
            child[piece_type] -= 1
            result += _completion_count(square + 1, *child)
    return result


def _rank_board(
    board: tuple[int, ...],
    counts: tuple[int, int, int, int],
) -> int:
    remaining = list(counts)
    rank = 0
    for square, piece in enumerate(board):
        actual = _PIECE_TYPE.get(piece)
        if actual is None:
            if piece != EMPTY:
                raise ValueError(f"unknown piece value {piece}")
            continue
        rank += _completion_count(square + 1, *remaining)
        for candidate in range(actual):
            if remaining[candidate] <= 0 or not _type_allowed(candidate, square):
                continue
            child = remaining.copy()
            child[candidate] -= 1
            rank += _completion_count(square + 1, *child)
        if remaining[actual] <= 0 or not _type_allowed(actual, square):
            raise ValueError("position does not match its material signature")
        remaining[actual] -= 1
    if any(remaining):
        raise ValueError("position does not match its material signature")
    return rank


def _unrank_board(
    rank: int,
    counts: tuple[int, int, int, int],
) -> tuple[int, ...]:
    """Invert ``_rank_board`` for deterministic tablebase sampling."""

    boards = _completion_count(0, *counts)
    if not 0 <= rank < boards:
        raise ValueError("rank outside material-signature board range")
    remaining = list(counts)
    board = [EMPTY] * 32
    for square in range(32):
        empty_count = _completion_count(square + 1, *remaining)
        if rank < empty_count:
            continue
        rank -= empty_count
        selected = None
        for piece_type, count in enumerate(remaining):
            if count <= 0 or not _type_allowed(piece_type, square):
                continue
            child = remaining.copy()
            child[piece_type] -= 1
            completions = _completion_count(square + 1, *child)
            if rank < completions:
                selected = piece_type
                remaining = child
                break
            rank -= completions
        if selected is None:
            raise RuntimeError("ranked tablebase unranking failed")
        board[square] = (
            BLACK_MAN,
            BLACK_KING,
            RED_MAN,
            RED_KING,
        )[selected]
    if any(remaining) or rank != 0:
        raise RuntimeError("ranked tablebase unranking did not terminate")
    return tuple(board)


class RankedTablebase:
    """Probe exact WDL for positions containing the file's material count.

    The file is mapped rather than copied into Python memory. Its metadata and
    exact byte layout are always validated; the optional checksum pass reads all
    packed data and is intentionally separate because a full 80-ply file is
    several gigabytes for the six-piece frontier.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        verify_checksum: bool = False,
    ) -> None:
        self.path = Path(path).resolve()
        self.checksum_verified = False
        self.provenance_verified = False
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._file = self.path.open("rb")
        try:
            self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            self._read_metadata()
            if verify_checksum:
                self.verify_checksum()
        except Exception:
            if hasattr(self, "_map"):
                self._map.close()
            self._file.close()
            raise

    def _read_metadata(self) -> None:
        if len(self._map) < 8:
            raise ValueError("truncated ranked tablebase header")
        magic = self._map[:8]
        if magic == _MAGIC:
            if len(self._map) < _HEADER.size:
                raise ValueError("truncated ranked tablebase header")
            (
                _magic,
                version,
                self.no_progress_plies,
                signature_count,
                self.total_states,
                self.expected_checksum,
            ) = _HEADER.unpack_from(self._map, 0)
            self.piece_count = 4
            self._compact = False
            declared_positions = None
            offset = _HEADER.size
        elif magic == _COMPACT_MAGIC:
            if len(self._map) < _COMPACT_HEADER.size:
                raise ValueError("truncated compact tablebase header")
            (
                _magic,
                version,
                piece_count,
                self.no_progress_plies,
                signature_count,
                declared_positions,
                self.total_states,
                self.expected_checksum,
            ) = _COMPACT_HEADER.unpack_from(self._map, 0)
            if piece_count not in _SIGNATURE_COUNTS:
                raise ValueError("unsupported compact tablebase piece count")
            self.piece_count = piece_count
            self._compact = True
            offset = _COMPACT_HEADER.size
        else:
            raise ValueError("unsupported ranked tablebase format")
        if version != _VERSION:
            raise ValueError("unsupported ranked tablebase version")
        maximum_horizon = 126 if self._compact else 200
        if not 1 <= self.no_progress_plies <= maximum_horizon:
            raise ValueError("ranked tablebase no-progress horizon is invalid")
        if signature_count != _SIGNATURE_COUNTS[self.piece_count]:
            raise ValueError("unexpected ranked tablebase signature count")
        canonical_signatures = _canonical_signature_counts(self.piece_count)

        signatures: dict[tuple[int, int, int, int], _Signature] = {}
        total_states = 0
        total_positions = 0
        data_ranges: list[tuple[int, int]] = []
        for signature_index in range(signature_count):
            if offset + _SIGNATURE_HEADER.size > len(self._map):
                raise ValueError("truncated ranked tablebase signature")
            bm, bk, rm, rk, boards, byte_count = _SIGNATURE_HEADER.unpack_from(
                self._map, offset
            )
            offset += _SIGNATURE_HEADER.size
            counts = (bm, bk, rm, rk)
            if counts != canonical_signatures[signature_index]:
                raise ValueError(
                    "ranked tablebase signatures are not in canonical order"
                )
            if (
                sum(counts) != self.piece_count or
                bm + bk == 0 or
                rm + rk == 0 or
                counts in signatures
            ):
                raise ValueError("invalid ranked tablebase material signature")
            expected_boards = _completion_count(0, *counts)
            state_count = boards * 2 * (self.no_progress_plies + 1)
            expected_bytes = boards * 2 if self._compact else (state_count + 3) // 4
            if boards != expected_boards or byte_count != expected_bytes:
                raise ValueError("ranked tablebase signature size mismatch")
            end = offset + byte_count
            if end > len(self._map):
                raise ValueError("truncated ranked tablebase data")
            signatures[counts] = _Signature(counts, boards, byte_count, offset)
            data_ranges.append((offset, end))
            total_states += state_count
            total_positions += boards * 2
            offset = end
        if offset != len(self._map) or total_states != self.total_states:
            raise ValueError("ranked tablebase total size mismatch")
        if declared_positions is not None and declared_positions != total_positions:
            raise ValueError("compact tablebase position count mismatch")
        self.total_positions = total_positions
        self._signatures = signatures
        self._data_ranges = tuple(data_ranges)

    def verify_checksum(
        self,
        native_library: str | Path | None = None,
    ) -> None:
        value = fnv1a_file_ranges(
            self.path,
            self._data_ranges,
            native_library,
        )
        if value is None:
            value = 1_469_598_103_934_665_603
            mask = (1 << 64) - 1
            for start, end in self._data_ranges:
                for offset in range(start, end, 1 << 20):
                    for byte in self._map[offset:min(offset + (1 << 20), end)]:
                        value ^= byte
                        value = (value * 1_099_511_628_211) & mask
        if value != self.expected_checksum:
            raise ValueError(
                f"ranked tablebase checksum mismatch: "
                f"expected {self.expected_checksum:016x}, got {value:016x}"
            )
        self.checksum_verified = True

    def verify_provenance(
        self,
        manifest_path: str | Path | None = None,
        *,
        verify_file_hash: bool = True,
    ):
        """Verify the committed rules/source/file SHA-256 binding."""

        from .provenance import (
            DEFAULT_MANIFEST_PATH,
            verify_tablebase_artifact,
        )

        binding = verify_tablebase_artifact(
            self.path,
            piece_count=self.piece_count,
            no_progress_plies=self.no_progress_plies,
            representation="compact" if self._compact else "full",
            expected_fnv1a64=self.expected_checksum,
            manifest_path=(
                DEFAULT_MANIFEST_PATH
                if manifest_path is None
                else manifest_path
            ),
            verify_file_hash=verify_file_hash,
        )
        self.provenance_verified = True
        return binding

    def probe(self, state: State) -> NativeProbe:
        counts = [0, 0, 0, 0]
        for piece in state.board:
            piece_type = _PIECE_TYPE.get(piece)
            if piece_type is not None:
                counts[piece_type] += 1
            elif piece != EMPTY:
                raise ValueError(f"unknown piece value {piece}")
        signature = self._signatures.get(tuple(counts))
        if signature is None:
            raise ValueError(
                f"ranked tablebase probes require exactly {self.piece_count} "
                "pieces with both colors present"
            )
        if not 0 <= state.reversible_plies <= self.no_progress_plies:
            raise ValueError("no-progress clock outside ranked tablebase range")
        rank = _rank_board(state.board, signature.counts)
        turn_index = 1 if state.turn == BLACK else 0
        if self._compact:
            encoded = self._map[
                signature.data_offset + rank * 2 + turn_index
            ]
            if encoded == 0:
                return NativeProbe(Outcome.DRAW, None)
            threshold_code = encoded & 0x7F
            if (
                threshold_code == 0 or
                threshold_code > self.no_progress_plies
            ):
                raise ValueError("invalid compact WDL threshold")
            threshold = threshold_code - 1
            if state.reversible_plies > threshold:
                return NativeProbe(Outcome.DRAW, None)
            outcome = Outcome.WIN if encoded & 0x80 else Outcome.LOSS
            return NativeProbe(outcome, None)
        index = (
            (state.reversible_plies * signature.boards + rank) * 2 + turn_index
        )
        packed = self._map[signature.data_offset + (index >> 2)]
        value = (packed >> ((index & 3) * 2)) & 3
        if value > 2:
            raise ValueError("invalid packed WDL value")
        return NativeProbe(Outcome(value - 1), None)

    @property
    def material_signatures(self) -> tuple[tuple[int, int, int, int], ...]:
        return tuple(self._signatures)

    def board_count(self, counts: tuple[int, int, int, int]) -> int:
        signature = self._signatures.get(counts)
        if signature is None:
            raise ValueError("unknown material signature")
        return signature.boards

    def state_from_rank(
        self,
        counts: tuple[int, int, int, int],
        rank: int,
        turn: int,
        *,
        reversible_plies: int = 0,
    ) -> State:
        """Reconstruct an exact tablebase state without scanning the file."""

        signature = self._signatures.get(counts)
        if signature is None:
            raise ValueError("unknown material signature")
        if turn not in (RED, BLACK):
            raise ValueError("turn must be RED or BLACK")
        if not 0 <= reversible_plies <= self.no_progress_plies:
            raise ValueError("no-progress clock outside ranked tablebase range")
        return State(
            _unrank_board(rank, signature.counts),
            turn,
            reversible_plies,
        )

    def close(self) -> None:
        self._map.close()
        self._file.close()

    def __enter__(self) -> "RankedTablebase":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
