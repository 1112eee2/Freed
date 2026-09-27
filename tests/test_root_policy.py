from __future__ import annotations

import itertools
import unittest
from unittest import mock

from makhos.core import Move
from makhos.distance import EndgameDistance
from makhos.exact import Outcome
from makhos.parallel_native import ParallelNativeSearch, _RootResult
from makhos.policy_value import PolicyValueEstimate
from makhos.root_policy import choose_root
from makhos.search import (
    Engine,
    MATE_SCORE,
    Mode,
    RootCandidate,
    UNKNOWN_WDL,
    WDLBound,
)


def _move(index: int) -> Move:
    return Move((index, index + 4))


def _candidate(
    index: int,
    *,
    score: int,
    bound: WDLBound = UNKNOWN_WDL,
    distance: EndgameDistance = EndgameDistance.unknown(),
    policy: PolicyValueEstimate = PolicyValueEstimate.neutral(),
    pressure: float = 0.0,
    pv_extra: tuple[Move, ...] = (),
) -> RootCandidate:
    move = _move(index)
    return RootCandidate(
        move=move,
        score=score,
        pv=(move,) + pv_extra,
        pressure=pressure,
        bound=bound,
        policy_value=policy,
        distance=distance,
    )


def _legacy_engine_choose(
    engine: Engine,
    candidates: tuple[RootCandidate, ...],
    mode: Mode,
    win_margin: int,
    *,
    proof_guided: bool = False,
) -> RootCandidate:
    best_rank = max(engine._safety_rank(item.bound) for item in candidates)
    ranked = [
        item
        for item in candidates
        if engine._safety_rank(item.bound) == best_rank
    ]
    best_score = max(item.score for item in ranked)
    if mode == Mode.BEST:
        return max(
            ranked,
            key=lambda item: (
                item.score,
                engine._distance_rank(item.distance),
                item.policy_value.win,
                item.policy_value.policy,
                -len(item.pv),
                item.move.notation,
            ),
        )

    safe = ranked if proof_guided else [
        item for item in ranked if item.score >= best_score - win_margin
    ]
    return max(
        safe,
        key=lambda item: (
            item.bound.exact_outcome == Outcome.WIN,
            item.score if item.score >= MATE_SCORE - 10_000 else 0,
            engine._decisive_distance_rank(item.distance),
            item.policy_value.win,
            item.policy_value.expected_score,
            engine._draw_distance_rank(item.distance),
            item.pressure,
            item.score,
            item.move.notation,
        ),
    )


class RootPolicyParityTests(unittest.TestCase):
    def test_python_and_endgame_policy_matches_frozen_legacy_oracle(self):
        engine = Engine()
        candidate_sets = (
            (
                _candidate(0, score=200),
                _candidate(
                    1,
                    score=200,
                    policy=PolicyValueEstimate(0.40, 0.40, 0.20, 0.60),
                ),
                _candidate(2, score=180, pressure=12.0),
            ),
            (
                _candidate(0, score=900),
                _candidate(
                    1,
                    score=25,
                    bound=WDLBound.exact(Outcome.DRAW),
                    distance=EndgameDistance(
                        outcome=Outcome.DRAW, dtr=12, exact=True
                    ),
                ),
                _candidate(
                    2,
                    score=20,
                    bound=WDLBound.exact(Outcome.DRAW),
                    distance=EndgameDistance(
                        outcome=Outcome.DRAW, dtr=8, exact=True
                    ),
                ),
            ),
            (
                _candidate(
                    0,
                    score=MATE_SCORE - 30,
                    bound=WDLBound.exact(Outcome.WIN),
                    distance=EndgameDistance(
                        outcome=Outcome.WIN, dtm=9, exact=True
                    ),
                ),
                _candidate(
                    1,
                    score=MATE_SCORE - 40,
                    bound=WDLBound.exact(Outcome.WIN),
                    distance=EndgameDistance(
                        outcome=Outcome.WIN, dtm=5, exact=True
                    ),
                    policy=PolicyValueEstimate(0.60, 0.30, 0.10, 0.20),
                ),
                _candidate(
                    2,
                    score=MATE_SCORE - 60,
                    bound=WDLBound.exact(Outcome.WIN),
                    pressure=100.0,
                ),
            ),
        )

        for candidates in candidate_sets:
            for permutation in itertools.permutations(candidates):
                for mode in Mode:
                    for win_margin in (0, 20, 100):
                        for proof_guided in (False, True):
                            with self.subTest(
                                moves=tuple(item.move.notation for item in permutation),
                                mode=mode,
                                win_margin=win_margin,
                                proof_guided=proof_guided,
                            ):
                                expected = _legacy_engine_choose(
                                    engine,
                                    permutation,
                                    mode,
                                    win_margin,
                                    proof_guided=proof_guided,
                                )
                                actual = engine._choose(
                                    permutation,
                                    mode,
                                    win_margin,
                                    proof_guided=proof_guided,
                                )
                                self.assertEqual(actual, expected)

    def test_parallel_policy_matches_first_legal_legacy_tie_break(self):
        moves = (_move(0), _move(1), _move(2))
        result_by_move = {
            moves[0]: _RootResult(moves[0], 50, 8, 10, (moves[0],)),
            moves[1]: _RootResult(moves[1], 80, 8, 11, (moves[1],)),
            moves[2]: _RootResult(moves[2], 80, 8, 12, (moves[2],)),
        }
        expected = result_by_move[moves[1]]
        for permutation in itertools.permutations(result_by_move.values()):
            with self.subTest(
                result_order=tuple(item.move.notation for item in permutation)
            ):
                actual = ParallelNativeSearch._choose(moves, permutation)
                self.assertEqual(actual, expected)

    def test_both_adapters_route_through_shared_policy(self):
        engine = Engine()
        candidate = _candidate(0, score=1)
        with mock.patch("makhos.search.choose_root", wraps=choose_root) as shared:
            self.assertEqual(
                engine._choose((candidate,), Mode.BEST, 0),
                candidate,
            )
            shared.assert_called_once()

        result = _RootResult(candidate.move, 1, 1, 1, (candidate.move,))
        with mock.patch(
            "makhos.parallel_native.choose_root", wraps=choose_root
        ) as shared:
            self.assertEqual(
                ParallelNativeSearch._choose((candidate.move,), (result,)),
                result,
            )
            shared.assert_called_once()

    def test_shared_policy_rejects_invalid_contracts(self):
        callbacks = dict(
            safety_rank=lambda item: (0, 0),
            score=lambda item: item,
            best_rank=lambda item: item,
        )
        with self.assertRaisesRegex(ValueError, "at least one"):
            choose_root((), mode="best", win_margin=0, **callbacks)
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            choose_root((1,), mode="best", win_margin=-1, **callbacks)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            choose_root((1,), mode="other", win_margin=0, **callbacks)
        with self.assertRaisesRegex(ValueError, "win_rank"):
            choose_root((1,), mode="win", win_margin=0, **callbacks)


if __name__ == "__main__":
    unittest.main()
