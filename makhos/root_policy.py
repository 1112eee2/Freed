"""Backend-neutral root-choice policy.

Search backends may expose different root metadata, but every backend must
apply the same safety-tier and score-envelope steps before its historical
tie-break. Keeping the tie-break callback explicit lets this refactor preserve
the current Python/endgame ordering and the native root-split's first-legal
ordering exactly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar


CandidateT = TypeVar("CandidateT")


def choose_root(
    candidates: Sequence[CandidateT],
    *,
    mode: object,
    win_margin: int,
    safety_rank: Callable[[CandidateT], tuple[int, int]],
    score: Callable[[CandidateT], int],
    best_rank: Callable[[CandidateT], object],
    win_rank: Callable[[CandidateT], object] | None = None,
    proof_guided: bool = False,
) -> CandidateT:
    """Choose one root candidate without changing backend tie-breaks.

    The rank callbacks include the backend's existing tie-break. Python and
    native-endgame candidates use their rich distance/value ranks; native root
    split supplies results in legal-move order and ranks by score, so Python's
    stable max keeps the first legal move on an equal score.
    """

    if not candidates:
        raise ValueError("root policy requires at least one candidate")
    if win_margin < 0:
        raise ValueError("win_margin cannot be negative")

    mode_name = getattr(mode, "value", mode)
    if mode_name not in ("best", "win"):
        raise ValueError(f"unsupported root policy mode: {mode_name!r}")

    best_safety = max(safety_rank(candidate) for candidate in candidates)
    ranked = tuple(
        candidate
        for candidate in candidates
        if safety_rank(candidate) == best_safety
    )
    best_score = max(score(candidate) for candidate in ranked)

    if mode_name == "best":
        return max(ranked, key=best_rank)

    if win_rank is None:
        raise ValueError("win mode requires a win_rank callback")
    safe = ranked if proof_guided else tuple(
        candidate
        for candidate in ranked
        if score(candidate) >= best_score - win_margin
    )
    return max(safe, key=win_rank)
