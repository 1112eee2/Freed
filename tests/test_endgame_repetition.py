"""Endgame decisions must respect the game's repetition and progress clocks."""

from collections import Counter
from dataclasses import replace
from pathlib import Path
import unittest

from makhos.core import (
    Rules, apply_move, legal_moves, parse_position, terminal_status,
)
from makhos.exact import Outcome
from makhos.ranked_tablebase import RankedTablebase
from makhos.search import (
    Engine, INFINITY, MATE_SCORE, Mode, RootCandidate, SearchLimits, SearchTimeout,
    TTEntry, TTFlag, UNKNOWN_WDL, WDLBound,
)


TB4_PATH = Path(__file__).resolve().parents[1] / "build/tb4_np80.compact.bin"
WINNING_MOVES = {"5-32", "6-10", "6-15", "6-19", "6-24"}


def repetition_fixture():
    state = parse_position("B:BK1,5,9:RK32")
    history = Counter({state.position_key: 1})
    for notation in ("9-6", "32-28", "6-9", "28-32", "9-6", "32-28"):
        move = next(move for move in legal_moves(state) if move.notation == notation)
        state = apply_move(state, move)
        history[state.position_key] += 1
    return state, history


@unittest.skipUnless(TB4_PATH.is_file(), "local TB4 artifact is required")
class RankedEndgameRepetitionTests(unittest.TestCase):
    def test_winning_endgame_does_not_allow_repetition_reply(self):
        state, history = repetition_fixture()
        with RankedTablebase(TB4_PATH) as tablebase:
            for mode in Mode:
                for depth in (1, 2, 3, 8):
                    with self.subTest(mode=mode, depth=depth):
                        result = Engine(ranked_tablebase=tablebase).search(
                            state, SearchLimits(depth=depth), mode=mode, history=history
                        )
                        self.assertIn(result.move.notation, WINNING_MOVES)
                        child = apply_move(state, result.move)
                        after_move_history = history.copy()
                        after_move_history[child.position_key] += 1
                        for reply in legal_moves(child):
                            after_reply = apply_move(child, reply)
                            status = terminal_status(
                                after_reply,
                                repetition_count=after_move_history[after_reply.position_key] + 1,
                            )
                            self.assertFalse(status.terminal and status.winner is None)

    def test_clock_78_wins_by_reset_but_clock_79_is_a_draw(self):
        state, history = repetition_fixture()
        with RankedTablebase(TB4_PATH) as tablebase:
            for clock in (78, 79):
                root = replace(state, reversible_plies=clock)
                for mode in Mode:
                    for depth in (1, 2, 3, 8):
                        with self.subTest(clock=clock, mode=mode, depth=depth):
                            result = Engine(ranked_tablebase=tablebase).search(
                                root, SearchLimits(depth=depth), mode=mode, history=history
                            )
                            if clock == 78:
                                self.assertIn(result.move.notation, WINNING_MOVES - {"5-32"})
                                self.assertEqual(result.bound.exact_outcome, Outcome.WIN)
                                child = apply_move(root, result.move)
                                reply, = legal_moves(child)
                                self.assertTrue(reply.is_capture)
                                self.assertEqual(apply_move(child, reply).reversible_plies, 0)
                            else:
                                self.assertEqual(result.score, 0)
                                self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)
                                self.assertEqual(
                                    terminal_status(apply_move(root, result.move)).reason,
                                    "no_progress",
                                )

    def test_losing_side_takes_available_repetition_draw(self):
        state, history = repetition_fixture()
        shuffling_move = next(m for m in legal_moves(state) if m.notation == "6-9")
        state = apply_move(state, shuffling_move)
        history[state.position_key] += 1
        with RankedTablebase(TB4_PATH) as tablebase:
            self.assertEqual(tablebase.probe(state).outcome, Outcome.LOSS)
            for mode in Mode:
                for depth in (1, 2, 3, 8):
                    with self.subTest(mode=mode, depth=depth):
                        result = Engine(ranked_tablebase=tablebase).search(
                            state, SearchLimits(depth=depth), mode=mode, history=history
                        )
                        self.assertEqual(result.move.notation, "28-32")
                        self.assertEqual(result.score, 0)
                        self.assertEqual(result.bound.exact_outcome, Outcome.DRAW)

    def test_exact_tablebase_outcomes_still_cut_off_without_evaluation(self):
        def unexpected_evaluation(*_args):
            self.fail("an exact tablebase result must not fall through to evaluation")

        cases = (
            (Rules(repetition_limit=None), "B:BK1,5,6:RK28", Outcome.WIN, MATE_SCORE),
            (Rules(repetition_limit=3), "B:BK1,2:RK31,32", Outcome.DRAW, 0),
        )
        with RankedTablebase(TB4_PATH) as tablebase:
            for rules, position, outcome, score in cases:
                for boundary in ("negamax", "quiescence"):
                    with self.subTest(rules=rules, boundary=boundary):
                        state = parse_position(position)
                        engine = Engine(
                            rules, ranked_tablebase=tablebase, eval_fn=unexpected_evaluation
                        )
                        history = Counter({state.position_key: 1})
                        if boundary == "negamax":
                            actual, pv, bound = engine._negamax(
                                state, 3, -INFINITY, INFINITY, history, ply_from_root=0
                            )
                        else:
                            actual, pv, bound = engine._quiescence(
                                state, -INFINITY, INFINITY, history, 0
                            )
                        self.assertEqual((actual, pv, bound), (score, (), WDLBound.exact(outcome)))

    def test_draw_cutoff_retains_the_tablebase_upper_bound(self):
        state, history = repetition_fixture()
        state = apply_move(state, next(m for m in legal_moves(state) if m.notation == "6-9"))
        history[state.position_key] += 1
        with RankedTablebase(TB4_PATH) as tablebase:
            engine = Engine(ranked_tablebase=tablebase)
            score, _, bound = engine._negamax(
                state, 1, -INFINITY, INFINITY, history, ply_from_root=0
            )
            self.assertEqual(score, 0)
            self.assertEqual(bound, WDLBound.exact(Outcome.DRAW))

    def test_quiet_evaluation_is_clamped_to_known_nonloss_or_nonwin(self):
        cases = (
            ("B:BK1,5,6:RK28", -200, WDLBound(Outcome.DRAW, Outcome.WIN)),
            ("R:BK1,5,9:RK28", 200, WDLBound(Outcome.LOSS, Outcome.DRAW)),
        )
        with RankedTablebase(TB4_PATH) as tablebase:
            for position, evaluation, expected in cases:
                with self.subTest(position=position):
                    state = parse_position(position)
                    engine = Engine(ranked_tablebase=tablebase,
                                    eval_fn=lambda *_args: evaluation)
                    score, _, bound = engine._quiescence(
                        state, -INFINITY, INFINITY, Counter({state.position_key: 1}), 0
                    )
                    self.assertEqual(score, 0)
                    self.assertEqual(bound, expected)

    def test_tt_score_from_another_history_cannot_replace_endgame_search(self):
        state, history = repetition_fixture()
        with RankedTablebase(TB4_PATH) as tablebase:
            for flag in TTFlag:
                with self.subTest(flag=flag):
                    engine = Engine(ranked_tablebase=tablebase)
                    move = legal_moves(state)[0]
                    engine._tt[state.position_key] = TTEntry(
                        state.position_key, 99, -123456 if flag == TTFlag.ALPHA else 123456,
                        flag, move,
                    )
                    # The board itself has occurred only once in this variant;
                    # endgame scores still cannot be keyed solely by the board.
                    history[state.position_key] = 1
                    score, _, bound = engine._negamax(
                        state, 3, -10, 10, history, ply_from_root=0
                    )
                    self.assertNotEqual(abs(score), 123456)
                    self.assertGreaterEqual(bound.lower, Outcome.DRAW)

    def test_alternating_histories_no_state_leakage(self):
        state, h_threat = repetition_fixture()
        h_clean = Counter({state.position_key: 1})
        with RankedTablebase(TB4_PATH) as tablebase:
            engine = Engine(ranked_tablebase=tablebase)
            # 1. Search with clean history
            res1 = engine.search(state, SearchLimits(depth=3), mode=Mode.WIN, history=h_clean)
            # 2. Search with repetition threat history (H2)
            res2 = engine.search(state, SearchLimits(depth=3), mode=Mode.WIN, history=h_threat)
            self.assertIn(res2.move.notation, WINNING_MOVES)
            # 3. Search with clean history (H1) again on the same engine instance
            res3 = engine.search(state, SearchLimits(depth=3), mode=Mode.WIN, history=h_clean)
            self.assertEqual(res1.move.notation, res3.move.notation)
            self.assertEqual(res1.score, res3.score)
            self.assertEqual(res1.bound, res3.bound)

    def test_extended_repetition_cycle_longer_than_2_plies(self):
        state = parse_position("B:BK1,5,9:RK32")
        history = Counter({state.position_key: 2})
        with RankedTablebase(TB4_PATH) as tablebase:
            engine = Engine(ranked_tablebase=tablebase)
            res = engine.search(state, SearchLimits(depth=3), mode=Mode.WIN, history=history)
            child = apply_move(state, res.move)
            status = terminal_status(child, repetition_count=history[child.position_key] + 1)
            self.assertFalse(status.terminal and status.winner is None)

    def test_piece_count_transitions_6_to_3(self):
        tb5_path = Path(__file__).resolve().parents[1] / "build/tb5_np80.compact.bin"
        tb6_path = Path(__file__).resolve().parents[1] / "build/tb6_np80.compact.bin"
        if not tb5_path.is_file() or not tb6_path.is_file():
            self.skipTest("TB5 and TB6 compact binaries required")
        with RankedTablebase(TB4_PATH) as tb4, RankedTablebase(tb5_path) as tb5, RankedTablebase(tb6_path) as tb6:
            engine = Engine(ranked_tablebases=(tb4, tb5, tb6))
            state, history = repetition_fixture()
            res = engine.search(state, SearchLimits(depth=3), mode=Mode.BEST, history=history)
            self.assertIn(res.move.notation, WINNING_MOVES)

    def test_zero_window_bound_consistency(self):
        state, history = repetition_fixture()
        with RankedTablebase(TB4_PATH) as tablebase:
            engine = Engine(ranked_tablebase=tablebase)
            for alpha, beta in ((-1, 1), (0, 1), (-1, 0), (-10, 0), (0, 10)):
                with self.subTest(alpha=alpha, beta=beta):
                    score, pv, bound = engine._negamax(
                        state, depth=2, alpha=alpha, beta=beta, counts=history, ply_from_root=0
                    )
                    self.assertLessEqual(bound.lower, bound.upper)
                    if bound.exact_outcome == Outcome.WIN:
                        self.assertGreaterEqual(score, MATE_SCORE - 1000)



class SearchHistoryContractTests(unittest.TestCase):
    def test_quiescence_respects_terminal_draw_before_captures(self):
        for clock, repetitions in ((80, 1), (0, 3)):
            with self.subTest(clock=clock, repetitions=repetitions):
                state = parse_position("B:BK1:RM6,23", reversible_plies=clock)
                engine = Engine(exact_piece_limit=0)
                score, pv, bound = engine._quiescence(
                    state, -INFINITY, INFINITY,
                    Counter({state.position_key: repetitions}), 7,
                )
                self.assertEqual((score, pv, bound), (0, (), WDLBound.exact(Outcome.DRAW)))

    def test_timeout_restores_history_at_each_recursive_search_boundary(self):
        def timeout(*_args):
            raise SearchTimeout("injected leaf timeout")

        for boundary in ("root", "negamax", "quiescence"):
            with self.subTest(boundary=boundary):
                state = parse_position(
                    "B:BK1:RM6,23" if boundary == "quiescence"
                    else "B:BM25,26,27:RM1,2,3"
                )
                engine = Engine(exact_piece_limit=0, eval_fn=timeout)
                history = Counter({state.position_key: 1})
                before = history.copy()
                with self.assertRaises(SearchTimeout):
                    if boundary == "root":
                        engine._search_root(state, legal_moves(state), 1, history)
                    elif boundary == "negamax":
                        engine._negamax(state, 1, -INFINITY, INFINITY, history, ply_from_root=0)
                    else:
                        engine._quiescence(state, -INFINITY, INFINITY, history, 0)
                self.assertEqual(history, before)

    def test_proved_win_precedes_pressure_and_nonloss_precedes_exact_draw(self):
        state = parse_position("B:BK1,5,6:RK28")
        winning_move = next(m for m in legal_moves(state) if m.notation == "6-24")
        shuffling_move = next(m for m in legal_moves(state) if m.notation == "6-9")
        engine = Engine(exact_piece_limit=0)
        for bound in (WDLBound.exact(Outcome.WIN), UNKNOWN_WDL):
            with self.subTest(bound=bound):
                winning = RootCandidate(winning_move, MATE_SCORE - 3, (winning_move,), 0, bound)
                pressure = RootCandidate(shuffling_move, 100, (shuffling_move,), 999999, UNKNOWN_WDL)
                self.assertEqual(
                    engine._choose((pressure, winning), Mode.WIN, win_margin=MATE_SCORE).move,
                    winning_move,
                )
        nonloss = RootCandidate(
            winning_move, 0, (winning_move,), 0, WDLBound(Outcome.DRAW, Outcome.WIN)
        )
        draw = RootCandidate(
            shuffling_move, 0, (shuffling_move,), 999999, WDLBound.exact(Outcome.DRAW)
        )
        for mode in Mode:
            self.assertEqual(engine._choose((draw, nonloss), mode, win_margin=0).move, winning_move)


if __name__ == "__main__":
    unittest.main()
