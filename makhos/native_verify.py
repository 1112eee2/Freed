"""Cross-language differential verification for the native move generator."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import random
import subprocess

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    State,
    apply_move,
    format_position,
    index_to_coord,
    legal_moves,
    piece_player,
)
from .exact import ExactSolver
from .core import Rules


@dataclass(frozen=True, slots=True)
class NativeVerification:
    samples: int
    compared_moves: int
    exact_samples: int


NativeMoveState = tuple[str, int, int, int, int, int]
_MOVE_STATE_KEYS = ("red", "black", "kings", "turn", "clock")


def _native_moves(executable: Path, state: State) -> Counter[str]:
    completed = subprocess.run(
        [str(executable), "moves", format_position(state)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return Counter(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _parse_native_move_states(output: str) -> Counter[NativeMoveState]:
    records: Counter[NativeMoveState] = Counter()
    for line_number, raw_line in enumerate(output.splitlines(), 1):
        if not raw_line:
            continue
        fields = raw_line.split("\t")
        if len(fields) != 6 or not fields[0]:
            raise ValueError(f"malformed native move-state line {line_number}")
        values: list[int] = []
        for index, expected_key in enumerate(_MOVE_STATE_KEYS, 1):
            key, separator, text = fields[index].partition("=")
            if key != expected_key or separator != "=" or not text:
                raise ValueError(
                    f"malformed native move-state field {line_number}:{index + 1}"
                )
            try:
                base = 16 if expected_key in ("red", "black", "kings") else 10
                if base == 16 and len(text) != 8:
                    raise ValueError
                values.append(int(text, base))
            except ValueError as exc:
                raise ValueError(
                    f"invalid native move-state value {line_number}:{index + 1}"
                ) from exc
        red, black, kings, turn, clock = values
        if (
            not 0 <= red <= 0xFFFFFFFF or
            not 0 <= black <= 0xFFFFFFFF or
            not 0 <= kings <= 0xFFFFFFFF or
            red & black or
            kings & ~(red | black) or
            turn not in (RED, BLACK) or
            not 0 <= clock <= 255
        ):
            raise ValueError(f"invalid native child state on line {line_number}")
        records[(fields[0], red, black, kings, turn, clock)] += 1
    return records


def _native_move_states(
    executable: Path,
    state: State,
) -> Counter[NativeMoveState]:
    completed = subprocess.run(
        [
            str(executable),
            "moves-state",
            format_position(state),
            str(state.reversible_plies),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return _parse_native_move_states(completed.stdout)


def _state_bitboards(state: State) -> tuple[int, int, int]:
    red = 0
    black = 0
    kings = 0
    for square, piece in enumerate(state.board):
        bit = 1 << square
        if piece in (RED_MAN, RED_KING):
            red |= bit
        elif piece in (BLACK_MAN, BLACK_KING):
            black |= bit
        if piece in (RED_KING, BLACK_KING):
            kings |= bit
    return red, black, kings


def verify_native_moves(
    executable: str | Path,
    *,
    samples: int = 200,
    seed: int = 0x4D414B484F53,
    exact_samples: int = 10,
    exact_no_progress: int = 8,
) -> NativeVerification:
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    rng = random.Random(seed)
    compared_moves = 0

    fixed = [
        State(
            tuple(BLACK_KING if i == 17 else RED_MAN if i in (10, 21) else EMPTY for i in range(32)),
            BLACK,
            reversible_plies=79,
        ),
        State(
            tuple(BLACK_MAN if i == 24 else RED_MAN if i in (21, 14) else EMPTY for i in range(32)),
            BLACK,
            reversible_plies=43,
        ),
        State(
            tuple(BLACK_KING if i == 0 else RED_KING if i == 31 else EMPTY for i in range(32)),
            BLACK,
            reversible_plies=79,
        ),
        State(
            tuple(BLACK_MAN if i == 8 else RED_MAN if i in (5, 6) else EMPTY for i in range(32)),
            BLACK,
            reversible_plies=37,
        ),
    ]
    positions: list[State] = list(fixed)
    piece_choices = (RED_MAN, BLACK_MAN, RED_KING, BLACK_KING)
    for _ in range(samples):
        board = [EMPTY] * 32
        for square in rng.sample(range(32), rng.randint(2, 12)):
            piece = rng.choice(piece_choices)
            row, _ = index_to_coord(square)
            if piece == RED_MAN and row == 7:
                piece = RED_KING
            elif piece == BLACK_MAN and row == 0:
                piece = BLACK_KING
            board[square] = piece
        if not any(piece_player(piece) == RED for piece in board):
            board[0] = RED_MAN
        if not any(piece_player(piece) == BLACK for piece in board):
            board[31] = BLACK_MAN
        positions.append(State(
            tuple(board),
            rng.choice((RED, BLACK)),
            reversible_plies=rng.randrange(81),
        ))

    for state in positions:
        expected: Counter[NativeMoveState] = Counter()
        for move in legal_moves(state):
            child = apply_move(state, move, validate=False)
            red, black, kings = _state_bitboards(child)
            expected[
                (
                    move.notation,
                    red,
                    black,
                    kings,
                    child.turn,
                    child.reversible_plies,
                )
            ] += 1
        actual = _native_move_states(executable, state)
        expected_notation = Counter(record[0] for record in expected.elements())
        actual_notation = Counter(record[0] for record in actual.elements())
        if actual_notation != expected_notation:
            raise AssertionError(
                f"native notation mismatch for {format_position(state)} "
                f"at clock {state.reversible_plies}\n"
                f"expected={expected_notation}\nactual={actual_notation}"
            )
        if actual != expected:
            raise AssertionError(
                f"native child-state mismatch for {format_position(state)} "
                f"at clock {state.reversible_plies}\n"
                f"expected={expected}\nactual={actual}"
            )
        compared_moves += sum(expected.values())
    exact_checked = _verify_native_exact(
        executable,
        samples=exact_samples,
        no_progress_plies=exact_no_progress,
        seed=seed ^ 0x4558414354,
    )
    return NativeVerification(len(positions), compared_moves, exact_checked)


def _native_exact(executable: Path, state: State, no_progress_plies: int) -> tuple[str, int | None]:
    completed = subprocess.run(
        [
            str(executable),
            "solve",
            format_position(state),
            str(no_progress_plies),
            "20",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    fields: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    distance_text = fields.get("distance")
    distance = None if distance_text == "-" else int(distance_text or "0")
    return fields["outcome"], distance


def _verify_native_exact(
    executable: Path,
    *,
    samples: int,
    no_progress_plies: int,
    seed: int,
) -> int:
    if samples < 0:
        raise ValueError("exact_samples cannot be negative")
    if samples == 0:
        return 0
    rng = random.Random(seed)
    rules = Rules(repetition_limit=None, no_progress_plies=no_progress_plies)
    oracle = ExactSolver(rules, max_states=2_000_000)
    checked = 0
    while checked < samples:
        squares = rng.sample(range(32), 3)
        owner_mask = rng.randint(1, 6)
        if owner_mask in (0, 7):
            continue
        board = [EMPTY] * 32
        valid = True
        for index, square in enumerate(squares):
            player = BLACK if (owner_mask >> index) & 1 else RED
            king = bool(rng.getrandbits(1))
            row, _ = index_to_coord(square)
            if not king and ((player == BLACK and row == 0) or (player == RED and row == 7)):
                valid = False
                break
            if player == BLACK:
                board[square] = BLACK_KING if king else BLACK_MAN
            else:
                board[square] = RED_KING if king else RED_MAN
        if not valid:
            continue
        state = State(tuple(board), rng.choice((RED, BLACK)))
        expected = oracle.solve(state)
        actual_outcome, actual_distance = _native_exact(
            executable, state, no_progress_plies
        )
        if actual_outcome != expected.outcome.name or actual_distance != expected.distance:
            raise AssertionError(
                f"native exact mismatch for {format_position(state)}: "
                f"expected {expected.outcome.name}/{expected.distance}, "
                f"actual {actual_outcome}/{actual_distance}"
            )
        checked += 1
    return checked
