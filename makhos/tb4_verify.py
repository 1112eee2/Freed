"""Independent Python-oracle verification for ranked tablebases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    Rules,
    State,
    format_position,
    coord_to_index,
    index_to_coord,
    legal_moves,
    opponent,
    parse_position,
)
from .exact import ExactSolver, Outcome
from .ranked_tablebase import RankedTablebase


@dataclass(frozen=True, slots=True)
class TablebaseVerification:
    piece_count: int
    samples: int
    wins: int
    draws: int
    losses: int
    oracle_states: int


def _random_position(
    rng: random.Random,
    no_progress_plies: int,
    piece_count: int,
) -> State:
    squares = rng.sample(range(32), piece_count)
    owner_mask = rng.randint(1, (1 << piece_count) - 2)
    board = [EMPTY] * 32
    for index, square in enumerate(squares):
        player = BLACK if (owner_mask >> index) & 1 else RED
        king = bool(rng.getrandbits(1))
        row, _ = index_to_coord(square)
        if not king and (
            (player == BLACK and row == 0) or
            (player == RED and row == 7)
        ):
            king = True
        if player == BLACK:
            board[square] = BLACK_KING if king else BLACK_MAN
        else:
            board[square] = RED_KING if king else RED_MAN
    return State(
        tuple(board),
        rng.choice((RED, BLACK)),
        rng.randrange(no_progress_plies + 1),
    )


def _tactical_positions(no_progress_plies: int) -> tuple[State, ...]:
    return (
        # Two symmetric immediate multi-capture wins exercise removal and turn.
        parse_position("B:BM29:BK18:RM11,22"),
        parse_position("R:BM11,22:RM4:RK15"),
        # A forced capture leading to an exact loss (distance 10 at 80 plies).
        parse_position("B:BK4:RM18,27:RK12"),
        # The no-progress terminal check takes precedence at the clock limit.
        parse_position(
            "B:BK1,5:RK2,6", reversible_plies=no_progress_plies
        ),
    )


_SWAP_PIECE = {
    EMPTY: EMPTY,
    RED_MAN: BLACK_MAN,
    BLACK_MAN: RED_MAN,
    RED_KING: BLACK_KING,
    BLACK_KING: RED_KING,
}


def _rotate_and_swap(state: State) -> State:
    board = [EMPTY] * 32
    for square, piece in enumerate(state.board):
        row, col = index_to_coord(square)
        rotated = coord_to_index(7 - row, 7 - col)
        assert rotated is not None
        board[rotated] = _SWAP_PIECE[piece]
    return State(
        tuple(board),
        opponent(state.turn),
        state.reversible_plies,
        state.ply,
    )


def verify_ranked_tablebase(
    tablebase: str | Path,
    *,
    no_progress_plies: int,
    samples: int = 50,
    seed: int = 0x54423457444C,
    max_states: int = 5_000_000,
    tactical: bool = False,
    captures_only: bool = False,
    min_captures: int = 0,
) -> TablebaseVerification:
    tablebase = Path(tablebase).resolve()
    if not tablebase.is_file():
        raise FileNotFoundError(tablebase)
    if no_progress_plies < 1:
        raise ValueError("no_progress_plies must be positive")
    if samples < 0 or (samples == 0 and not tactical):
        raise ValueError("samples must be positive unless tactical cases are enabled")
    if min_captures < 0:
        raise ValueError("min_captures cannot be negative")

    rng = random.Random(seed)
    oracle = ExactSolver(
        Rules(repetition_limit=None, no_progress_plies=no_progress_plies),
        max_states=max_states,
    )
    counts = {Outcome.WIN: 0, Outcome.DRAW: 0, Outcome.LOSS: 0}
    with RankedTablebase(tablebase) as ranked:
        if ranked.no_progress_plies != no_progress_plies:
            raise ValueError(
                "requested no-progress rule does not match the tablebase file"
            )
        if tactical and ranked.piece_count != 4:
            raise ValueError("built-in tactical cases require a four-piece tablebase")
        positions = list(_tactical_positions(no_progress_plies) if tactical else ())
        while len(positions) < samples + int(tactical) * len(
            _tactical_positions(no_progress_plies)
        ):
            state = _random_position(
                rng, no_progress_plies, ranked.piece_count
            )
            if captures_only or min_captures:
                state = State(state.board, state.turn, 0, state.ply)
                moves = legal_moves(state)
                if not moves or not moves[0].is_capture:
                    continue
                if min_captures and any(
                    len(move.captures) < min_captures for move in moves
                ):
                    continue
            positions.append(state)
        for state in positions:
            expected = oracle.solve(state).outcome
            actual = ranked.probe(state).outcome
            if actual != expected:
                raise AssertionError(
                    f"{ranked.piece_count}-piece tablebase mismatch for "
                    f"{format_position(state)} "
                    f"at clock {state.reversible_plies}: "
                    f"expected {expected.name}, actual {actual.name}"
                )
            symmetric = ranked.probe(_rotate_and_swap(state)).outcome
            if symmetric != actual:
                raise AssertionError(
                    f"{ranked.piece_count}-piece tablebase breaks color-rotation "
                    f"symmetry for {format_position(state)} at clock "
                    f"{state.reversible_plies}: {actual.name} vs {symmetric.name}"
                )
            counts[actual] += 1
        return TablebaseVerification(
            piece_count=ranked.piece_count,
            samples=len(positions),
            wins=counts[Outcome.WIN],
            draws=counts[Outcome.DRAW],
            losses=counts[Outcome.LOSS],
            oracle_states=oracle.state_count,
        )
