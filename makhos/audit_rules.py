"""Independent Thai-checkers rules implementation for final proof audits.

This module intentionally does not call the reference move generator, move
application helpers, or coordinate helpers in :mod:`makhos.core`.  It uses a
separate bitboard implementation so a proof closure can be checked by two
implementations instead of trusting the implementation that produced the
certificate edges.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    State,
    TerminalStatus,
)


_DIRECTIONS = ((-1, -1), (-1, 1), (1, -1), (1, 1))


def _build_geometry() -> tuple[
    tuple[tuple[int, int], ...],
    tuple[tuple[tuple[int, ...], ...], ...],
]:
    coordinates: list[tuple[int, int]] = []
    lookup: dict[tuple[int, int], int] = {}
    for square in range(32):
        row, offset = divmod(square, 4)
        coordinate = (row, offset * 2 + (1 if row % 2 == 0 else 0))
        coordinates.append(coordinate)
        lookup[coordinate] = square

    rays: list[tuple[tuple[int, ...], ...]] = []
    for row, column in coordinates:
        square_rays: list[tuple[int, ...]] = []
        for row_step, column_step in _DIRECTIONS:
            ray: list[int] = []
            target = (row + row_step, column + column_step)
            while target in lookup:
                ray.append(lookup[target])
                target = (target[0] + row_step, target[1] + column_step)
            square_rays.append(tuple(ray))
        rays.append(tuple(square_rays))
    return tuple(coordinates), tuple(rays)


_COORDINATES, _RAYS = _build_geometry()
_COORDINATE_TO_SQUARE = {
    coordinate: square for square, coordinate in enumerate(_COORDINATES)
}


@dataclass(frozen=True, slots=True)
class AuditedMove:
    """A legal move and child state produced by the audit implementation."""

    path: tuple[int, ...]
    captures: tuple[int, ...]
    promotes: bool
    child: State

    @property
    def notation(self) -> str:
        separator = "x" if self.captures else "-"
        return separator.join(str(square + 1) for square in self.path)


def _other(player: int) -> int:
    return BLACK if player == RED else RED


def _state_bitboards(state: State) -> tuple[int, int, int]:
    red = black = kings = 0
    for square, piece in enumerate(state.board):
        bit = 1 << square
        if piece in (RED_MAN, RED_KING):
            red |= bit
        elif piece in (BLACK_MAN, BLACK_KING):
            black |= bit
        if piece in (RED_KING, BLACK_KING):
            kings |= bit
    return red, black, kings


def _state_from_bitboards(
    red: int,
    black: int,
    kings: int,
    turn: int,
    reversible_plies: int,
    ply: int,
) -> State:
    board = [EMPTY] * 32
    for square in range(32):
        bit = 1 << square
        if red & bit:
            board[square] = RED_KING if kings & bit else RED_MAN
        elif black & bit:
            board[square] = BLACK_KING if kings & bit else BLACK_MAN
    return State(tuple(board), turn, reversible_plies, ply)


def _capture_targets(
    red: int,
    black: int,
    square: int,
    player: int,
    king: bool,
):
    occupied = red | black
    enemy = black if player == RED else red
    if king:
        for ray in _RAYS[square]:
            for index, target in enumerate(ray):
                target_bit = 1 << target
                if not occupied & target_bit:
                    continue
                if (
                    enemy & target_bit and
                    index + 1 < len(ray) and
                    not occupied & (1 << ray[index + 1])
                ):
                    yield target, ray[index + 1]
                break
        return

    forward = 1 if player == RED else -1
    row, column = _COORDINATES[square]
    for column_step in (-1, 1):
        captured = _COORDINATE_TO_SQUARE.get((row + forward, column + column_step))
        landing = _COORDINATE_TO_SQUARE.get(
            (row + 2 * forward, column + 2 * column_step)
        )
        if (
            captured is not None and
            landing is not None and
            enemy & (1 << captured) and
            not occupied & (1 << landing)
        ):
            yield captured, landing


class IndependentRulesAuditor:
    """Generate legal edges without using the engine's reference helpers."""

    def legal_moves(self, state: State) -> tuple[AuditedMove, ...]:
        red, black, kings = _state_bitboards(state)
        player = state.turn
        own = red if player == RED else black
        captures: dict[tuple[tuple[int, ...], tuple[int, ...]], AuditedMove] = {}

        def capture_sequences(
            current_red: int,
            current_black: int,
            current_kings: int,
            square: int,
            king: bool,
            path: tuple[int, ...],
            victims: tuple[int, ...],
        ) -> None:
            continued = False
            for captured, landing in _capture_targets(
                current_red,
                current_black,
                square,
                player,
                king,
            ):
                continued = True
                from_bit = 1 << square
                captured_bit = 1 << captured
                landing_bit = 1 << landing
                next_red = current_red
                next_black = current_black
                if player == RED:
                    next_red = (next_red & ~from_bit) | landing_bit
                    next_black &= ~captured_bit
                else:
                    next_black = (next_black & ~from_bit) | landing_bit
                    next_red &= ~captured_bit
                next_kings = current_kings & ~(from_bit | captured_bit)
                promotion_row = 7 if player == RED else 0
                promotes = not king and _COORDINATES[landing][0] == promotion_row
                if king or promotes:
                    next_kings |= landing_bit
                next_path = path + (landing,)
                next_victims = victims + (captured,)
                if promotes:
                    child = _state_from_bitboards(
                        next_red,
                        next_black,
                        next_kings,
                        _other(player),
                        0,
                        state.ply + 1,
                    )
                    move = AuditedMove(next_path, next_victims, True, child)
                    captures[(next_path, next_victims)] = move
                else:
                    capture_sequences(
                        next_red,
                        next_black,
                        next_kings,
                        landing,
                        king,
                        next_path,
                        next_victims,
                    )
            if not continued and victims:
                child = _state_from_bitboards(
                    current_red,
                    current_black,
                    current_kings,
                    _other(player),
                    0,
                    state.ply + 1,
                )
                move = AuditedMove(path, victims, False, child)
                captures[(path, victims)] = move

        remaining = own
        while remaining:
            least_bit = remaining & -remaining
            square = least_bit.bit_length() - 1
            capture_sequences(
                red,
                black,
                kings,
                square,
                bool(kings & least_bit),
                (square,),
                (),
            )
            remaining ^= least_bit
        if captures:
            return tuple(captures[key] for key in sorted(captures))

        occupied = red | black
        quiet: list[AuditedMove] = []
        remaining = own
        while remaining:
            least_bit = remaining & -remaining
            square = least_bit.bit_length() - 1
            king = bool(kings & least_bit)
            destinations: list[int] = []
            if king:
                for ray in _RAYS[square]:
                    for landing in ray:
                        if occupied & (1 << landing):
                            break
                        destinations.append(landing)
            else:
                forward = 1 if player == RED else -1
                row, column = _COORDINATES[square]
                for column_step in (-1, 1):
                    landing = _COORDINATE_TO_SQUARE.get(
                        (row + forward, column + column_step)
                    )
                    if landing is not None and not occupied & (1 << landing):
                        destinations.append(landing)

            for landing in destinations:
                from_bit = 1 << square
                landing_bit = 1 << landing
                next_red = red
                next_black = black
                if player == RED:
                    next_red = (next_red & ~from_bit) | landing_bit
                else:
                    next_black = (next_black & ~from_bit) | landing_bit
                next_kings = kings & ~from_bit
                promotion_row = 7 if player == RED else 0
                promotes = not king and _COORDINATES[landing][0] == promotion_row
                if king or promotes:
                    next_kings |= landing_bit
                child = _state_from_bitboards(
                    next_red,
                    next_black,
                    next_kings,
                    _other(player),
                    0 if promotes else state.reversible_plies + 1,
                    state.ply + 1,
                )
                quiet.append(AuditedMove((square, landing), (), promotes, child))
            remaining ^= least_bit
        return tuple(sorted(quiet, key=lambda move: move.path))

    def terminal_status(
        self,
        state: State,
        *,
        no_progress_plies: int,
    ) -> TerminalStatus:
        if state.reversible_plies >= no_progress_plies:
            return TerminalStatus(True, None, "no_progress")
        if not self.legal_moves(state):
            return TerminalStatus(True, _other(state.turn), "no_legal_move")
        return TerminalStatus(False)
