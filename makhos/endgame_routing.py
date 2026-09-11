"""Shared admission policy for native endgame readiness and search.

Admission covers the whole root search, not just the moves that hit a tablebase.
It says nothing about the position's WDL or availability of a particular TB file.
"""

from .core import EMPTY, State, legal_moves


def is_native_endgame_position(state: State) -> bool:
    """Admit <=6 pieces or a legal capture landing inside that boundary.

    Thai multi-captures may cross from eight or more pieces in one ply. Each
    captured square removes one piece; promotion does not change material.
    Counting the verified move's captures avoids allocating child states here.
    Quiet midgames and captures whose children all remain >6 stay on their
    existing route. All legal alternatives must still be searched once admitted.
    """
    pieces = sum(piece != EMPTY for piece in state.board)
    if pieces <= 6:
        return True
    return any(pieces - len(move.captures) <= 6 for move in legal_moves(state))
