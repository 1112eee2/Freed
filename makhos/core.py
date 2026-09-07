"""Rules and move generation for Thai checkers (Makhos).

The implementation deliberately models a complete capture chain as one move.
Captured pieces are removed after each jump, and a flying king must land on the
first square immediately beyond the captured piece (the Thai "king halt" rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping, Sequence

EMPTY = 0
RED_MAN = 1
BLACK_MAN = 2
RED_KING = 3
BLACK_KING = 4

RED = 1
BLACK = 2
PLAYABLE_SQUARES = 32

PIECE_TO_PLAYER = {
    RED_MAN: RED,
    RED_KING: RED,
    BLACK_MAN: BLACK,
    BLACK_KING: BLACK,
}
KING_FOR_PLAYER = {RED: RED_KING, BLACK: BLACK_KING}
MAN_FOR_PLAYER = {RED: RED_MAN, BLACK: BLACK_MAN}


def opponent(player: int) -> int:
    if player == RED:
        return BLACK
    if player == BLACK:
        return RED
    raise ValueError(f"invalid player: {player}")


def index_to_coord(square: int) -> tuple[int, int]:
    if not 0 <= square < PLAYABLE_SQUARES:
        raise ValueError(f"square outside 0..31: {square}")
    row, offset = divmod(square, 4)
    col = offset * 2 + (1 if row % 2 == 0 else 0)
    return row, col


def coord_to_index(row: int, col: int) -> int | None:
    if not (0 <= row < 8 and 0 <= col < 8):
        return None
    if (row + col) % 2 != 1:
        return None
    return row * 4 + col // 2


def piece_player(piece: int) -> int | None:
    return PIECE_TO_PLAYER.get(piece)


def is_king(piece: int) -> bool:
    return piece in (RED_KING, BLACK_KING)


def promotion_row(player: int) -> int:
    return 7 if player == RED else 0


@dataclass(frozen=True, slots=True)
class Rules:
    """Rules that affect terminal-state semantics.

    Tournament draw rules are not uniform across all Thai-checkers venues.  The
    defaults make games finite for engine play: threefold repetition and 80
    reversible plies (40 full moves by each side combined without a capture or
    promotion).  They are explicit and replaceable rather than hidden in search.
    """

    name: str = "thai-makhos-fmjd-king-halt"
    starting_player: int = BLACK
    repetition_limit: int | None = 3
    no_progress_plies: int = 80

    def __post_init__(self) -> None:
        if self.starting_player not in (RED, BLACK):
            raise ValueError("starting_player must be RED or BLACK")
        if self.repetition_limit is not None and self.repetition_limit < 2:
            raise ValueError("repetition_limit must be at least 2")
        if self.no_progress_plies < 1:
            raise ValueError("no_progress_plies must be positive")


DEFAULT_RULES = Rules()


@dataclass(frozen=True, slots=True)
class Move:
    """One complete legal turn, including every mandatory continuation jump."""

    path: tuple[int, ...]
    captures: tuple[int, ...] = ()
    promotes: bool = False

    def __post_init__(self) -> None:
        if len(self.path) < 2:
            raise ValueError("a move needs at least a start and an end square")
        if self.captures and len(self.captures) != len(self.path) - 1:
            raise ValueError("each capture jump must have one captured square")

    @property
    def start(self) -> int:
        return self.path[0]

    @property
    def end(self) -> int:
        return self.path[-1]

    @property
    def is_capture(self) -> bool:
        return bool(self.captures)

    @property
    def notation(self) -> str:
        separator = "x" if self.is_capture else "-"
        return separator.join(str(square + 1) for square in self.path)


@dataclass(frozen=True, slots=True)
class State:
    board: tuple[int, ...]
    turn: int
    reversible_plies: int = 0
    ply: int = 0

    def __post_init__(self) -> None:
        if len(self.board) != PLAYABLE_SQUARES:
            raise ValueError("board must contain exactly 32 playable squares")
        if self.turn not in (RED, BLACK):
            raise ValueError("turn must be RED or BLACK")
        if any(piece not in (EMPTY, RED_MAN, BLACK_MAN, RED_KING, BLACK_KING) for piece in self.board):
            raise ValueError("board contains an invalid piece")
        if any(self.board[square] == BLACK_MAN for square in range(4)):
            raise ValueError("black man cannot remain on its promotion row")
        if any(self.board[square] == RED_MAN for square in range(28, 32)):
            raise ValueError("red man cannot remain on its promotion row")
        if self.reversible_plies < 0 or self.ply < 0:
            raise ValueError("counters cannot be negative")

    @property
    def position_key(self) -> tuple[tuple[int, ...], int]:
        return self.board, self.turn


@dataclass(frozen=True, slots=True)
class TerminalStatus:
    terminal: bool
    winner: int | None = None
    reason: str = "ongoing"

    @property
    def is_draw(self) -> bool:
        return self.terminal and self.winner is None


def initial_state(first_player: int | None = None, rules: Rules = DEFAULT_RULES) -> State:
    board = [EMPTY] * PLAYABLE_SQUARES
    for square in range(0, 8):
        board[square] = RED_MAN
    for square in range(24, 32):
        board[square] = BLACK_MAN
    return State(tuple(board), rules.starting_player if first_player is None else first_player)


def state_from_pieces(
    pieces: Mapping[tuple[int, int], int],
    turn: int,
    *,
    reversible_plies: int = 0,
    ply: int = 0,
) -> State:
    """Build a state from (row, col) coordinates; primarily useful for tests."""

    board = [EMPTY] * PLAYABLE_SQUARES
    for (row, col), piece in pieces.items():
        square = coord_to_index(row, col)
        if square is None:
            raise ValueError(f"({row}, {col}) is not a playable square")
        if board[square] != EMPTY:
            raise ValueError(f"duplicate square ({row}, {col})")
        board[square] = piece
    return State(tuple(board), turn, reversible_plies, ply)


def parse_position(text: str, *, reversible_plies: int = 0, ply: int = 0) -> State:
    """Parse a compact 1-32 position such as ``B:BM25,26:BK29:RM6:RK1``."""

    fields = [field.strip().upper() for field in text.split(":") if field.strip()]
    if not fields or fields[0] not in ("B", "R"):
        raise ValueError("position must begin with B: or R: to identify side-to-move")
    turn = BLACK if fields[0] == "B" else RED
    prefix_to_piece = {
        "BM": BLACK_MAN,
        "BK": BLACK_KING,
        "RM": RED_MAN,
        "RK": RED_KING,
    }
    board = [EMPTY] * PLAYABLE_SQUARES
    for field in fields[1:]:
        prefix = field[:2]
        if prefix not in prefix_to_piece:
            raise ValueError(f"unknown piece group: {field}")
        square_text = field[2:].lstrip("=")
        if not square_text:
            continue
        for token in square_text.split(","):
            try:
                square = int(token) - 1
            except ValueError as exc:
                raise ValueError(f"invalid square in {field}: {token}") from exc
            if not 0 <= square < PLAYABLE_SQUARES:
                raise ValueError(f"square must be in 1..32: {square + 1}")
            if board[square] != EMPTY:
                raise ValueError(f"square {square + 1} is listed more than once")
            board[square] = prefix_to_piece[prefix]
    return State(tuple(board), turn, reversible_plies, ply)


def format_position(state: State) -> str:
    groups = (
        ("BM", BLACK_MAN),
        ("BK", BLACK_KING),
        ("RM", RED_MAN),
        ("RK", RED_KING),
    )
    fields = ["B" if state.turn == BLACK else "R"]
    for prefix, piece in groups:
        squares = [str(square + 1) for square, value in enumerate(state.board) if value == piece]
        if squares:
            fields.append(prefix + ",".join(squares))
    return ":".join(fields)


def _man_capture_steps(board: Sequence[int], square: int, piece: int) -> Iterator[tuple[int, int]]:
    player = piece_player(piece)
    assert player is not None
    row, col = index_to_coord(square)
    direction = 1 if player == RED else -1
    enemy = opponent(player)
    for dc in (-1, 1):
        jumped = coord_to_index(row + direction, col + dc)
        landing = coord_to_index(row + 2 * direction, col + 2 * dc)
        if jumped is None or landing is None:
            continue
        if piece_player(board[jumped]) == enemy and board[landing] == EMPTY:
            yield jumped, landing


def _king_capture_steps(board: Sequence[int], square: int, piece: int) -> Iterator[tuple[int, int]]:
    player = piece_player(piece)
    assert player is not None
    enemy = opponent(player)
    row, col = index_to_coord(square)
    for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        scan_row, scan_col = row + dr, col + dc
        while True:
            target = coord_to_index(scan_row, scan_col)
            if target is None:
                break
            target_piece = board[target]
            if target_piece == EMPTY:
                scan_row += dr
                scan_col += dc
                continue
            if piece_player(target_piece) != enemy:
                break
            landing = coord_to_index(scan_row + dr, scan_col + dc)
            if landing is not None and board[landing] == EMPTY:
                # Thai king-halt: only the first square behind the victim.
                yield target, landing
            break


def _capture_steps(board: Sequence[int], square: int, piece: int) -> Iterable[tuple[int, int]]:
    if is_king(piece):
        return _king_capture_steps(board, square, piece)
    return _man_capture_steps(board, square, piece)


def _capture_sequences(
    board: tuple[int, ...],
    square: int,
    piece: int,
    path: tuple[int, ...],
    captures: tuple[int, ...],
) -> Iterator[Move]:
    found_continuation = False
    player = piece_player(piece)
    assert player is not None

    for captured, landing in _capture_steps(board, square, piece):
        found_continuation = True
        next_board = list(board)
        next_board[square] = EMPTY
        next_board[captured] = EMPTY  # Thai rules remove it immediately.
        promotes = not is_king(piece) and index_to_coord(landing)[0] == promotion_row(player)
        moved_piece = KING_FOR_PLAYER[player] if promotes else piece
        next_board[landing] = moved_piece
        next_path = path + (landing,)
        next_captures = captures + (captured,)

        if promotes:
            # Reaching the king row ends this turn, even if the new king could jump.
            yield Move(next_path, next_captures, promotes=True)
            continue

        yield from _capture_sequences(
            tuple(next_board), landing, moved_piece, next_path, next_captures
        )

    if not found_continuation and captures:
        yield Move(path, captures, promotes=False)


def _quiet_moves(board: tuple[int, ...], square: int, piece: int) -> Iterator[Move]:
    player = piece_player(piece)
    assert player is not None
    row, col = index_to_coord(square)
    if not is_king(piece):
        direction = 1 if player == RED else -1
        for dc in (-1, 1):
            landing = coord_to_index(row + direction, col + dc)
            if landing is not None and board[landing] == EMPTY:
                promotes = index_to_coord(landing)[0] == promotion_row(player)
                yield Move((square, landing), promotes=promotes)
        return

    for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        scan_row, scan_col = row + dr, col + dc
        while True:
            landing = coord_to_index(scan_row, scan_col)
            if landing is None or board[landing] != EMPTY:
                break
            yield Move((square, landing))
            scan_row += dr
            scan_col += dc


def legal_moves(state: State) -> tuple[Move, ...]:
    captures: list[Move] = []
    for square, piece in enumerate(state.board):
        if piece_player(piece) == state.turn:
            captures.extend(_capture_sequences(state.board, square, piece, (square,), ()))
    if captures:
        return tuple(sorted(set(captures), key=lambda move: (move.path, move.captures)))

    quiet: list[Move] = []
    for square, piece in enumerate(state.board):
        if piece_player(piece) == state.turn:
            quiet.extend(_quiet_moves(state.board, square, piece))
    return tuple(sorted(quiet, key=lambda move: move.path))


def apply_move(state: State, move: Move, *, validate: bool = True) -> State:
    if validate and move not in legal_moves(state):
        raise ValueError(f"illegal move: {move.notation}")
    piece = state.board[move.start]
    if piece_player(piece) != state.turn:
        raise ValueError("move does not start on a piece belonging to side-to-move")

    board = list(state.board)
    board[move.start] = EMPTY
    for captured in move.captures:
        board[captured] = EMPTY
    player = state.turn
    if move.promotes:
        piece = KING_FOR_PLAYER[player]
    board[move.end] = piece

    irreversible = move.is_capture or move.promotes
    return State(
        tuple(board),
        opponent(player),
        reversible_plies=0 if irreversible else state.reversible_plies + 1,
        ply=state.ply + 1,
    )


def terminal_status(
    state: State,
    *,
    repetition_count: int = 1,
    rules: Rules = DEFAULT_RULES,
) -> TerminalStatus:
    if rules.repetition_limit is not None and repetition_count >= rules.repetition_limit:
        return TerminalStatus(True, None, "repetition")
    if state.reversible_plies >= rules.no_progress_plies:
        return TerminalStatus(True, None, "no_progress")
    if not legal_moves(state):
        return TerminalStatus(True, opponent(state.turn), "no_legal_move")
    return TerminalStatus(False)


def perft(state: State, depth: int) -> int:
    """Count leaf nodes. A complete multi-capture chain counts as one ply."""

    if depth < 0:
        raise ValueError("depth cannot be negative")
    if depth == 0:
        return 1
    moves = legal_moves(state)
    if depth == 1:
        return len(moves)
    return sum(perft(apply_move(state, move, validate=False), depth - 1) for move in moves)


def format_board(state: State) -> str:
    symbols = {
        EMPTY: ".",
        RED_MAN: "r",
        BLACK_MAN: "b",
        RED_KING: "R",
        BLACK_KING: "B",
    }
    lines = ["    0 1 2 3 4 5 6 7"]
    for row in range(8):
        cells: list[str] = []
        for col in range(8):
            square = coord_to_index(row, col)
            cells.append(" " if square is None else symbols[state.board[square]])
        lines.append(f"{row} | " + " ".join(cells))
    side = "BLACK" if state.turn == BLACK else "RED"
    lines.append(f"turn: {side}  reversible plies: {state.reversible_plies}")
    return "\n".join(lines)
