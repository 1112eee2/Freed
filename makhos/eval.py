"""Advanced Handcrafted Evaluation for Thai Makhos (Thai Checkers).

Includes positional PSTs, piece mobility, pawn advancement & passed man detection,
defensive formation structures, back-rank protection, king activity, and endgame trade incentives.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    PLAYABLE_SQUARES,
    RED,
    RED_KING,
    RED_MAN,
    State,
    coord_to_index,
    index_to_coord,
    legal_moves,
    piece_player,
)

# Base piece values in centipawns
MAN_VALUE = 100
KING_VALUE = 330


@dataclass(frozen=True, slots=True)
class SideEvaluation:
    """Auditable terms for one side of the handcrafted evaluator."""

    material: int = 0
    man_pst: int = 0
    king_pst: int = 0
    support: int = 0
    back_rank: int = 0
    passed_men: int = 0
    simplification: int = 0
    king_edge: int = 0
    king_mobility: int = 0

    @property
    def total(self) -> int:
        return sum(asdict(self).values())


@dataclass(frozen=True, slots=True)
class EvaluationTrace:
    """A score decomposition that exactly mirrors ``evaluate_handcrafted``."""

    perspective: int
    red: SideEvaluation
    black: SideEvaluation
    terminal_score: int | None = None

    @property
    def score(self) -> int:
        if self.terminal_score is not None:
            return self.terminal_score
        red_minus_black = self.red.total - self.black.total
        return red_minus_black if self.perspective == RED else -red_minus_black

    @property
    def relative_terms(self) -> dict[str, int]:
        """Return signed term contributions from ``perspective``."""

        direction = 1 if self.perspective == RED else -1
        red_terms = asdict(self.red)
        black_terms = asdict(self.black)
        return {
            name: direction * (red_terms[name] - black_terms[name])
            for name in red_terms
        }


@dataclass(frozen=True, slots=True)
class EvaluationFeatures:
    """Linear, side-relative basis of the current non-terminal evaluator."""

    men: int
    kings: int
    man_pst: int
    king_pst: int
    support: int
    back_rank: int
    passed_men: int
    simplification: int
    king_edge: int
    king_mobility: int

    def score(self, weights: dict[str, float] | None = None) -> float:
        active = CURRENT_EVALUATION_WEIGHTS if weights is None else weights
        return sum(
            getattr(self, name) * active[name]
            for name in self.__dataclass_fields__
        )


CURRENT_EVALUATION_WEIGHTS: dict[str, float] = {
    "men": float(MAN_VALUE),
    "kings": float(KING_VALUE),
    "man_pst": 1.0,
    "king_pst": 1.0,
    "support": 8.0,
    "back_rank": 15.0,
    "passed_men": 1.0,
    "simplification": 6.0,
    "king_edge": -12.0,
    "king_mobility": 4.0,
}

# Precalculated square properties
SQUARE_ROW: list[int] = [0] * PLAYABLE_SQUARES
SQUARE_COL: list[int] = [0] * PLAYABLE_SQUARES
IS_CENTER: list[bool] = [False] * PLAYABLE_SQUARES
IS_EDGE: list[bool] = [False] * PLAYABLE_SQUARES
IS_MAIN_DIAGONAL: list[bool] = [False] * PLAYABLE_SQUARES

# Precalculated neighbors for each square
# Tuple of (up_left, up_right, down_left, down_right)
DIAG_NEIGHBORS: list[list[int]] = [[] for _ in range(PLAYABLE_SQUARES)]

# For RED (moves towards row 7)
RED_FORWARD_NEIGHBORS: list[list[int]] = [[] for _ in range(PLAYABLE_SQUARES)]
RED_BACKWARD_NEIGHBORS: list[list[int]] = [[] for _ in range(PLAYABLE_SQUARES)]

# For BLACK (moves towards row 0)
BLACK_FORWARD_NEIGHBORS: list[list[int]] = [[] for _ in range(PLAYABLE_SQUARES)]
BLACK_BACKWARD_NEIGHBORS: list[list[int]] = [[] for _ in range(PLAYABLE_SQUARES)]

for sq in range(PLAYABLE_SQUARES):
    r, c = index_to_coord(sq)
    SQUARE_ROW[sq] = r
    SQUARE_COL[sq] = c
    IS_CENTER[sq] = (2 <= r <= 5) and (2 <= c <= 5)
    IS_EDGE[sq] = (r in (0, 7)) or (c in (0, 7))
    IS_MAIN_DIAGONAL[sq] = (r == c) or (r + c == 7)

    # Calculate neighbors
    for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        n_sq = coord_to_index(r + dr, c + dc)
        if n_sq is not None:
            DIAG_NEIGHBORS[sq].append(n_sq)
            if dr > 0:  # Increasing row = RED forward = BLACK backward
                RED_FORWARD_NEIGHBORS[sq].append(n_sq)
                BLACK_BACKWARD_NEIGHBORS[sq].append(n_sq)
            else:  # Decreasing row = RED backward = BLACK forward
                RED_BACKWARD_NEIGHBORS[sq].append(n_sq)
                BLACK_FORWARD_NEIGHBORS[sq].append(n_sq)


# Advancement bonus for men based on how close they are to promotion
# RED man starts at row 0, 1; advances to row 7
RED_ADVANCEMENT_BONUS = [0, 5, 12, 22, 35, 55, 80, 0]
# BLACK man starts at row 6, 7; advances to row 0
BLACK_ADVANCEMENT_BONUS = [0, 80, 55, 35, 22, 12, 5, 0]

# Piece Square Tables for Men (Center control & positioning)
# Positional bonus for men on each of the 32 squares
MAN_PST_RED: list[int] = [0] * PLAYABLE_SQUARES
MAN_PST_BLACK: list[int] = [0] * PLAYABLE_SQUARES

for sq in range(PLAYABLE_SQUARES):
    r, c = SQUARE_ROW[sq], SQUARE_COL[sq]

    # Base advancement
    red_adv = RED_ADVANCEMENT_BONUS[r]
    black_adv = BLACK_ADVANCEMENT_BONUS[r]

    # Center preference (columns 2,3,4,5 get bonus, edges get slight penalty)
    center_bonus = 6 if IS_CENTER[sq] else (-4 if IS_EDGE[sq] else 2)

    # Back rank defense (holding back rank early)
    red_back_rank = 15 if r == 0 else 0
    black_back_rank = 15 if r == 7 else 0

    MAN_PST_RED[sq] = red_adv + center_bonus + red_back_rank
    MAN_PST_BLACK[sq] = black_adv + center_bonus + black_back_rank

# PST for Kings
KING_PST: list[int] = [0] * PLAYABLE_SQUARES
for sq in range(PLAYABLE_SQUARES):
    r, c = SQUARE_ROW[sq], SQUARE_COL[sq]
    bonus = 0
    if IS_CENTER[sq]:
        bonus += 20
    if IS_MAIN_DIAGONAL[sq]:
        bonus += 12
    if IS_EDGE[sq]:
        bonus -= 8
    KING_PST[sq] = bonus


def evaluate_handcrafted(state: State, perspective: int) -> int:
    """Comprehensive handcrafted evaluation function for Thai Makhos.

    Returns score in centipawns from the perspective of `perspective` (RED or BLACK).
    Positive score means advantage for `perspective`.
    """
    board = state.board

    red_man_count = 0
    black_man_count = 0
    red_king_count = 0
    black_king_count = 0

    red_mg_score = 0
    black_mg_score = 0

    red_men_sqs: list[int] = []
    black_men_sqs: list[int] = []
    red_king_sqs: list[int] = []
    black_king_sqs: list[int] = []

    # 1. Material and Positional PST evaluation
    for sq, piece in enumerate(board):
        if piece == EMPTY:
            continue
        if piece == RED_MAN:
            red_man_count += 1
            red_men_sqs.append(sq)
            red_mg_score += MAN_VALUE + MAN_PST_RED[sq]
        elif piece == BLACK_MAN:
            black_man_count += 1
            black_men_sqs.append(sq)
            black_mg_score += MAN_VALUE + MAN_PST_BLACK[sq]
        elif piece == RED_KING:
            red_king_count += 1
            red_king_sqs.append(sq)
            red_mg_score += KING_VALUE + KING_PST[sq]
        elif piece == BLACK_KING:
            black_king_count += 1
            black_king_sqs.append(sq)
            black_mg_score += KING_VALUE + KING_PST[sq]

    red_total_pieces = red_man_count + red_king_count
    black_total_pieces = black_man_count + black_king_count

    # If side has no pieces, it's a loss
    if red_total_pieces == 0:
        return -999999 if perspective == RED else 999999
    if black_total_pieces == 0:
        return 999999 if perspective == RED else -999999

    # 2. Structural Defensive Formations (Support Chains)
    # A man is supported if there is a friendly piece behind it diagonally
    red_support_bonus = 0
    for sq in red_men_sqs:
        # Behind RED man is RED_BACKWARD_NEIGHBORS
        for b_sq in RED_BACKWARD_NEIGHBORS[sq]:
            if board[b_sq] in (RED_MAN, RED_KING):
                red_support_bonus += 8
                break

    black_support_bonus = 0
    for sq in black_men_sqs:
        # Behind BLACK man is BLACK_BACKWARD_NEIGHBORS
        for b_sq in BLACK_BACKWARD_NEIGHBORS[sq]:
            if board[b_sq] in (BLACK_MAN, BLACK_KING):
                black_support_bonus += 8
                break

    red_mg_score += red_support_bonus
    black_mg_score += black_support_bonus

    # 3. Back-rank Protection / Bridge Bonus
    # Holding back rank pieces (Row 0 for Red: sq 0, 1, 2, 3; Row 7 for Black: sq 28, 29, 30, 31)
    if black_man_count > 0:  # If Black still has men advancing, Red back rank is crucial
        red_back_count = sum(1 for sq in (0, 1, 2, 3) if board[sq] == RED_MAN)
        if red_back_count >= 2:
            red_mg_score += 15

    if red_man_count > 0:  # If Red still has men advancing, Black back rank is crucial
        black_back_count = sum(1 for sq in (28, 29, 30, 31) if board[sq] == BLACK_MAN)
        if black_back_count >= 2:
            black_mg_score += 15

    # 4. Passed Men Detection
    # A man is passed if no enemy pieces are ahead of it on its path to promotion
    red_passed_bonus = 0
    for sq in red_men_sqs:
        r, c = SQUARE_ROW[sq], SQUARE_COL[sq]
        if r >= 4:  # Deeply advanced RED man
            # Check if any black piece is in front of it
            blocked = False
            for f_row in range(r + 1, 8):
                for f_col in (c - (f_row - r), c + (f_row - r)):
                    if 0 <= f_col < 8:
                        f_sq = coord_to_index(f_row, f_col)
                        if f_sq is not None and board[f_sq] in (BLACK_MAN, BLACK_KING):
                            blocked = True
                            break
                if blocked:
                    break
            if not blocked:
                red_passed_bonus += 30 + (r - 4) * 20

    black_passed_bonus = 0
    for sq in black_men_sqs:
        r, c = SQUARE_ROW[sq], SQUARE_COL[sq]
        if r <= 3:  # Deeply advanced BLACK man
            blocked = False
            for f_row in range(r - 1, -1, -1):
                for f_col in (c - (r - f_row), c + (r - f_row)):
                    if 0 <= f_col < 8:
                        f_sq = coord_to_index(f_row, f_col)
                        if f_sq is not None and board[f_sq] in (RED_MAN, RED_KING):
                            blocked = True
                            break
                if blocked:
                    break
            if not blocked:
                black_passed_bonus += 30 + (3 - r) * 20

    red_mg_score += red_passed_bonus
    black_mg_score += black_passed_bonus

    # 5. Trade Incentive in Endgames
    # When ahead in material, encourage trading; when behind, avoid trading
    raw_material_diff = (
        (red_man_count * MAN_VALUE + red_king_count * KING_VALUE) -
        (black_man_count * MAN_VALUE + black_king_count * KING_VALUE)
    )

    total_pieces = red_total_pieces + black_total_pieces
    if total_pieces <= 8 and raw_material_diff != 0:
        # Fewer total pieces with material advantage gives extra bonus
        simplification_bonus = (16 - total_pieces) * 6
        if raw_material_diff > 0:
            red_mg_score += simplification_bonus
        else:
            black_mg_score += simplification_bonus

    # 6. King Mobility and Edge Penalty
    for sq in red_king_sqs:
        if IS_EDGE[sq]:
            red_mg_score -= 12
        mobility = sum(1 for n_sq in DIAG_NEIGHBORS[sq] if board[n_sq] == EMPTY)
        red_mg_score += mobility * 4

    for sq in black_king_sqs:
        if IS_EDGE[sq]:
            black_mg_score -= 12
        mobility = sum(1 for n_sq in DIAG_NEIGHBORS[sq] if board[n_sq] == EMPTY)
        black_mg_score += mobility * 4

    # Calculate final relative score
    final_score = red_mg_score - black_mg_score
    return final_score if perspective == RED else -final_score


def evaluate_endgame_king_value(
    state: State,
    perspective: int,
    *,
    king_value: int = 204,
    king_edge: int = -12,
) -> int:
    """Experimental exact-WDL-backed king-term taper for candidate builds."""

    score = evaluate_handcrafted(state, perspective)
    if (
        not any(piece in (RED_MAN, RED_KING) for piece in state.board)
        or not any(piece in (BLACK_MAN, BLACK_KING) for piece in state.board)
    ):
        return score
    total_pieces = sum(piece != EMPTY for piece in state.board)
    if total_pieces > 12:
        return score
    blend = 6 if total_pieces <= 7 else 13 - total_pieces
    correction = int((king_value - KING_VALUE) * blend / 6)
    direction = 1 if perspective == RED else -1
    king_difference = (
        sum(piece == RED_KING for piece in state.board)
        - sum(piece == BLACK_KING for piece in state.board)
    )
    edge_difference = (
        sum(piece == RED_KING and IS_EDGE[square]
            for square, piece in enumerate(state.board))
        - sum(piece == BLACK_KING and IS_EDGE[square]
              for square, piece in enumerate(state.board))
    )
    edge_correction = int((king_edge + 12) * blend / 6)
    return score + direction * (
        king_difference * correction + edge_difference * edge_correction
    )


def trace_evaluation(state: State, perspective: int) -> EvaluationTrace:
    """Explain the current evaluator without changing its hot search path.

    This intentionally mirrors the arithmetic in ``evaluate_handcrafted``.
    Randomized parity tests guard the diagnostic copy against drift while the
    playing evaluator remains allocation-free.
    """

    board = state.board
    red_men = [sq for sq, piece in enumerate(board) if piece == RED_MAN]
    black_men = [sq for sq, piece in enumerate(board) if piece == BLACK_MAN]
    red_kings = [sq for sq, piece in enumerate(board) if piece == RED_KING]
    black_kings = [sq for sq, piece in enumerate(board) if piece == BLACK_KING]
    red_total = len(red_men) + len(red_kings)
    black_total = len(black_men) + len(black_kings)
    empty = SideEvaluation()
    if red_total == 0:
        score = -999999 if perspective == RED else 999999
        return EvaluationTrace(perspective, empty, empty, score)
    if black_total == 0:
        score = 999999 if perspective == RED else -999999
        return EvaluationTrace(perspective, empty, empty, score)

    red_material = len(red_men) * MAN_VALUE + len(red_kings) * KING_VALUE
    black_material = len(black_men) * MAN_VALUE + len(black_kings) * KING_VALUE
    red_man_pst = sum(MAN_PST_RED[square] for square in red_men)
    black_man_pst = sum(MAN_PST_BLACK[square] for square in black_men)
    red_king_pst = sum(KING_PST[square] for square in red_kings)
    black_king_pst = sum(KING_PST[square] for square in black_kings)

    red_support = sum(
        8
        for square in red_men
        if any(board[behind] in (RED_MAN, RED_KING)
               for behind in RED_BACKWARD_NEIGHBORS[square])
    )
    black_support = sum(
        8
        for square in black_men
        if any(board[behind] in (BLACK_MAN, BLACK_KING)
               for behind in BLACK_BACKWARD_NEIGHBORS[square])
    )

    red_back_rank = 0
    if black_men and sum(board[square] == RED_MAN for square in (0, 1, 2, 3)) >= 2:
        red_back_rank = 15
    black_back_rank = 0
    if red_men and sum(board[square] == BLACK_MAN for square in (28, 29, 30, 31)) >= 2:
        black_back_rank = 15

    red_passed = 0
    for square in red_men:
        row, col = SQUARE_ROW[square], SQUARE_COL[square]
        if row < 4:
            continue
        blocked = False
        for forward_row in range(row + 1, 8):
            for forward_col in (
                col - (forward_row - row),
                col + (forward_row - row),
            ):
                if 0 <= forward_col < 8:
                    forward = coord_to_index(forward_row, forward_col)
                    if forward is not None and board[forward] in (BLACK_MAN, BLACK_KING):
                        blocked = True
                        break
            if blocked:
                break
        if not blocked:
            red_passed += 30 + (row - 4) * 20

    black_passed = 0
    for square in black_men:
        row, col = SQUARE_ROW[square], SQUARE_COL[square]
        if row > 3:
            continue
        blocked = False
        for forward_row in range(row - 1, -1, -1):
            for forward_col in (
                col - (row - forward_row),
                col + (row - forward_row),
            ):
                if 0 <= forward_col < 8:
                    forward = coord_to_index(forward_row, forward_col)
                    if forward is not None and board[forward] in (RED_MAN, RED_KING):
                        blocked = True
                        break
            if blocked:
                break
        if not blocked:
            black_passed += 30 + (3 - row) * 20

    red_simplification = 0
    black_simplification = 0
    material_difference = red_material - black_material
    total_pieces = red_total + black_total
    if total_pieces <= 8 and material_difference != 0:
        bonus = (16 - total_pieces) * 6
        if material_difference > 0:
            red_simplification = bonus
        else:
            black_simplification = bonus

    red_king_edge = -12 * sum(IS_EDGE[square] for square in red_kings)
    black_king_edge = -12 * sum(IS_EDGE[square] for square in black_kings)
    red_king_mobility = 4 * sum(
        sum(board[neighbor] == EMPTY for neighbor in DIAG_NEIGHBORS[square])
        for square in red_kings
    )
    black_king_mobility = 4 * sum(
        sum(board[neighbor] == EMPTY for neighbor in DIAG_NEIGHBORS[square])
        for square in black_kings
    )

    red = SideEvaluation(
        material=red_material,
        man_pst=red_man_pst,
        king_pst=red_king_pst,
        support=red_support,
        back_rank=red_back_rank,
        passed_men=red_passed,
        simplification=red_simplification,
        king_edge=red_king_edge,
        king_mobility=red_king_mobility,
    )
    black = SideEvaluation(
        material=black_material,
        man_pst=black_man_pst,
        king_pst=black_king_pst,
        support=black_support,
        back_rank=black_back_rank,
        passed_men=black_passed,
        simplification=black_simplification,
        king_edge=black_king_edge,
        king_mobility=black_king_mobility,
    )
    return EvaluationTrace(perspective, red, black)


def evaluation_features(state: State, perspective: int) -> EvaluationFeatures:
    """Return an auditable linear basis for exact-label tuning."""

    trace = trace_evaluation(state, perspective)
    if trace.terminal_score is not None:
        raise ValueError("terminal material positions have no linear features")
    direction = 1 if perspective == RED else -1
    red_men = sum(piece == RED_MAN for piece in state.board)
    black_men = sum(piece == BLACK_MAN for piece in state.board)
    red_kings = sum(piece == RED_KING for piece in state.board)
    black_kings = sum(piece == BLACK_KING for piece in state.board)
    terms = trace.relative_terms
    features = EvaluationFeatures(
        men=direction * (red_men - black_men),
        kings=direction * (red_kings - black_kings),
        man_pst=terms["man_pst"],
        king_pst=terms["king_pst"],
        support=terms["support"] // 8,
        back_rank=terms["back_rank"] // 15,
        passed_men=terms["passed_men"],
        simplification=terms["simplification"] // 6,
        king_edge=terms["king_edge"] // -12,
        king_mobility=terms["king_mobility"] // 4,
    )
    if int(features.score()) != trace.score:
        raise RuntimeError("evaluation feature basis drifted from evaluator")
    return features
