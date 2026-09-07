"""Executable oracle for the locked Thai Makhos NNUE v1 feature ABI.

This module is intentionally pure and is not imported by the playing path.  It
defines the sparse feature indices that the future trainer, scalar native
oracle, incremental accumulator, and AVX2 path must reproduce exactly.
Terminal/proof/tablebase precedence remains the caller's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    is_king,
    opponent,
    piece_player,
)


FEATURE_SPEC_NAME = "thai-makhos-shared-137-v1"
PIECE_SQUARE_FEATURES = 128
CLOCK_BUCKETS = (
    "0",
    "1_to_9",
    "10_to_19",
    "20_to_29",
    "30_to_39",
    "40_to_49",
    "50_to_59",
    "60_to_69",
    "70_to_79",
)
CLOCK_FEATURE_OFFSET = PIECE_SQUARE_FEATURES
INPUT_DIMENSIONS = PIECE_SQUARE_FEATURES + len(CLOCK_BUCKETS)
PERSPECTIVE_CATEGORIES = (
    "own_man",
    "own_king",
    "opponent_man",
    "opponent_king",
)

OWN_MAN = 0
OWN_KING = 1
OPPONENT_MAN = 2
OPPONENT_KING = 3


def _checked_perspective(perspective: int) -> int:
    if isinstance(perspective, bool) or perspective not in (BLACK, RED):
        raise ValueError("perspective must be BLACK or RED")
    return perspective


def canonical_square(square: int, perspective: int) -> int:
    """Return the v1 canonical 0-based square for one accumulator."""

    perspective = _checked_perspective(perspective)
    if isinstance(square, bool) or not isinstance(square, int):
        raise TypeError("square must be an integer")
    if not 0 <= square < PLAYABLE_SQUARES:
        raise ValueError("square must be in 0..31")
    return square if perspective == BLACK else PLAYABLE_SQUARES - 1 - square


def relative_piece_category(piece: int, perspective: int) -> int:
    """Map a non-empty piece to own/opponent man/king for a perspective."""

    perspective = _checked_perspective(perspective)
    player = piece_player(piece)
    if player is None:
        raise ValueError("piece must be a non-empty Thai Makhos piece")
    own = player == perspective
    king = is_king(piece)
    if own:
        return OWN_KING if king else OWN_MAN
    return OPPONENT_KING if king else OPPONENT_MAN


def piece_feature_index(piece: int, square: int, perspective: int) -> int:
    """Return one of the 128 category-by-canonical-square feature indices."""

    category = relative_piece_category(piece, perspective)
    return category * PLAYABLE_SQUARES + canonical_square(square, perspective)


def clock_bucket(reversible_plies: int) -> int:
    """Return the 0..8 reversible-clock bucket; ply 80 is terminal."""

    if isinstance(reversible_plies, bool) or not isinstance(reversible_plies, int):
        raise TypeError("reversible_plies must be an integer")
    if not 0 <= reversible_plies < 80:
        raise ValueError("NNUE clock features require reversible plies in 0..79")
    if reversible_plies == 0:
        return 0
    return 1 + reversible_plies // 10


def clock_feature_index(reversible_plies: int) -> int:
    return CLOCK_FEATURE_OFFSET + clock_bucket(reversible_plies)


def perspective_active_features(state: State, perspective: int) -> tuple[int, ...]:
    """Return sorted sparse indices for one player's accumulator."""

    perspective = _checked_perspective(perspective)
    active = [
        piece_feature_index(piece, square, perspective)
        for square, piece in enumerate(state.board)
        if piece != EMPTY
    ]
    active.append(clock_feature_index(state.reversible_plies))
    result = tuple(sorted(active))
    if len(result) != len(set(result)):
        raise AssertionError("NNUE feature collision in a legal state")
    return result


@dataclass(frozen=True, slots=True)
class OrderedAccumulatorFeatures:
    """Sparse accumulator inputs in the locked network concatenation order."""

    side_to_move_player: int
    side_to_move: tuple[int, ...]
    opponent: tuple[int, ...]


def ordered_accumulator_features(state: State) -> OrderedAccumulatorFeatures:
    """Return side-to-move first, then opponent, without a global turn feature."""

    return OrderedAccumulatorFeatures(
        side_to_move_player=state.turn,
        side_to_move=perspective_active_features(state, state.turn),
        opponent=perspective_active_features(state, opponent(state.turn)),
    )


@dataclass(frozen=True, slots=True)
class FeatureDelta:
    """Sparse remove/add operations for one fixed perspective accumulator."""

    perspective: int
    removed: tuple[int, ...]
    added: tuple[int, ...]


def perspective_feature_delta(
    parent: State,
    child: State,
    perspective: int,
) -> FeatureDelta:
    """Derive an oracle delta from authoritative parent/child board state."""

    perspective = _checked_perspective(perspective)
    before = set(perspective_active_features(parent, perspective))
    after = set(perspective_active_features(child, perspective))
    return FeatureDelta(
        perspective=perspective,
        removed=tuple(sorted(before - after)),
        added=tuple(sorted(after - before)),
    )


def both_perspective_feature_deltas(
    parent: State,
    child: State,
) -> tuple[FeatureDelta, FeatureDelta]:
    """Return deltas in stable BLACK, RED accumulator order."""

    return (
        perspective_feature_delta(parent, child, BLACK),
        perspective_feature_delta(parent, child, RED),
    )


def feature_spec_payload() -> dict:
    """Return the exact machine-readable feature contract validated by gates."""

    return {
        "name": FEATURE_SPEC_NAME,
        "input_dimensions": INPUT_DIMENSIONS,
        "piece_square_features": PIECE_SQUARE_FEATURES,
        "clock_buckets": list(CLOCK_BUCKETS),
        "black_canonical_square": "identity",
        "red_canonical_square": "31_minus_square",
        "perspective_categories": list(PERSPECTIVE_CATEGORIES),
        "active_features": "piece_count_plus_one",
        "concatenation_order": ["side_to_move", "opponent"],
    }


ALL_PIECES = (RED_MAN, BLACK_MAN, RED_KING, BLACK_KING)

