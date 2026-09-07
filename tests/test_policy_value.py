import tempfile
import unittest
from pathlib import Path

from makhos.core import BLACK, BLACK_MAN, Move, RED_MAN, Rules, initial_state, legal_moves, parse_position, state_from_pieces
from makhos.exact import Outcome
from makhos.distance import EndgameDistance
from makhos.policy_value import (
    EmpiricalPolicyValueModel,
    PolicyValueEstimate,
    action_key,
)
from makhos.proof import EndgameOracle, NonLossProver, ProofStrategy
from makhos.search import Engine, Mode, RootCandidate, SearchLimits, WDLBound
from makhos.selfplay import train_self_play


class PolicyValueTests(unittest.TestCase):
    def test_self_play_rejects_engine_rules_mismatch(self):
        model = EmpiricalPolicyValueModel()
        engine_rules = Rules(repetition_limit=3, no_progress_plies=80)
        engine = Engine(
            engine_rules,
            exact_piece_limit=0,
            policy_value_model=model,
        )
        with self.assertRaisesRegex(ValueError, "identical rules"):
            train_self_play(
                model,
                engine,
                SearchLimits(depth=1),
                games=1,
                rules=Rules(repetition_limit=None, no_progress_plies=80),
            )

    def test_proof_guided_self_play_allows_covered_opponent_reply(self):
        state = parse_position("B:BK1:RK32")
        proof_rules = Rules(repetition_limit=None, no_progress_plies=2)
        oracle = EndgameOracle()
        certificate, _ = NonLossProver(
            proof_rules, oracle, node_budget=10_000
        ).prove(state, BLACK)
        strategy = ProofStrategy(certificate, oracle)
        model = EmpiricalPolicyValueModel()
        rules = Rules(repetition_limit=3, no_progress_plies=2)
        engine = Engine(
            rules,
            exact_piece_limit=0,
            policy_value_model=model,
            proof_strategy=strategy,
        )
        summary = train_self_play(
            model,
            engine,
            SearchLimits(depth=1),
            games=1,
            rules=rules,
            seed=1,
            start=state,
            exploration_rate=1.0,
            exploration_score_margin=2_000_000,
            max_game_plies=3,
        )
        self.assertEqual(summary.draws, 1)
        self.assertEqual(summary.samples, 2)
        self.assertEqual(summary.truncated, 0)

    def test_self_play_exploration_cannot_override_proof_strategy(self):
        state = parse_position("B:BK1:RK32")
        proof_rules = Rules(repetition_limit=None, no_progress_plies=1)
        oracle = EndgameOracle()
        certificate, _ = NonLossProver(
            proof_rules, oracle, node_budget=100
        ).prove(state, BLACK)
        strategy = ProofStrategy(certificate, oracle)
        proof_move = strategy.move_for(state)
        model = EmpiricalPolicyValueModel()
        rules = Rules(repetition_limit=3, no_progress_plies=1)
        engine = Engine(
            rules,
            exact_piece_limit=0,
            policy_value_model=model,
            proof_strategy=strategy,
        )
        summary = train_self_play(
            model,
            engine,
            SearchLimits(depth=1),
            games=1,
            rules=rules,
            seed=1,
            start=state,
            exploration_rate=1.0,
            exploration_score_margin=2_000_000,
            max_game_plies=2,
        )
        self.assertEqual(summary.draws, 1)
        self.assertEqual(summary.samples, 1)
        self.assertEqual(set(model.action), {action_key(state, proof_move)})

    def test_learning_and_round_trip_preserve_probabilities(self):
        state = parse_position("B:BK1:RM2")
        moves = legal_moves(state)
        winning = next(move for move in moves if move.notation == "1-10")
        losing = next(move for move in moves if move.notation == "1-6")
        model = EmpiricalPolicyValueModel()
        for _ in range(12):
            model.update(state, winning, 1)
            model.update(state, losing, -1)
        predicted = model.predict(state, moves)
        self.assertGreater(predicted[winning].win, predicted[losing].win)
        self.assertGreater(predicted[winning].policy, 0.0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save(path)
            loaded = EmpiricalPolicyValueModel.load(path)
            self.assertEqual(model.to_dict(), loaded.to_dict())
            self.assertEqual(predicted, loaded.predict(state, moves))

    def test_probability_selects_only_within_best_wdl_tier(self):
        engine = Engine(exact_piece_limit=0)
        high = PolicyValueEstimate(0.95, 0.04, 0.01, 0.9, 100)
        low = PolicyValueEstimate(0.10, 0.80, 0.10, 0.1, 100)
        proven_draw = RootCandidate(
            Move((0, 4)), 0, (), 0.0, WDLBound.exact(Outcome.DRAW), low
        )
        unproven = RootCandidate(
            Move((1, 5)), 500, (), 999.0,
            WDLBound(Outcome.LOSS, Outcome.WIN), high,
        )
        chosen = engine._choose((unproven, proven_draw), Mode.WIN, win_margin=1000)
        self.assertEqual(chosen.move, proven_draw.move)

        other_draw = RootCandidate(
            Move((2, 6)), 0, (), 0.0, WDLBound.exact(Outcome.DRAW), high
        )
        chosen = engine._choose((proven_draw, other_draw), Mode.WIN, win_margin=0)
        self.assertEqual(chosen.move, other_draw.move)

    def test_proof_guided_win_uses_probability_across_all_safe_moves(self):
        engine = Engine(exact_piece_limit=0)
        high_probability = PolicyValueEstimate(0.90, 0.08, 0.02, 0.8, 100)
        low_probability = PolicyValueEstimate(0.10, 0.80, 0.10, 0.2, 100)
        heuristic_best = RootCandidate(
            Move((0, 4)), 500, (), 0.0,
            WDLBound.exact(Outcome.DRAW), low_probability,
        )
        likely_human_win = RootCandidate(
            Move((1, 5)), -500, (), 0.0,
            WDLBound.exact(Outcome.DRAW), high_probability,
        )
        chosen = engine._choose(
            (heuristic_best, likely_human_win),
            Mode.WIN,
            win_margin=0,
            proof_guided=True,
        )
        self.assertEqual(chosen.move, likely_human_win.move)

    def test_exact_dtm_closes_a_win_before_learned_probability(self):
        engine = Engine(exact_piece_limit=0)
        high = PolicyValueEstimate(0.95, 0.04, 0.01, 0.9, 100)
        low = PolicyValueEstimate(0.10, 0.80, 0.10, 0.1, 100)
        slow = RootCandidate(
            Move((0, 4)), 1_000_000, (), 0.0,
            WDLBound.exact(Outcome.WIN), high,
            EndgameDistance(Outcome.WIN, dtm=9, exact=True),
        )
        fast = RootCandidate(
            Move((1, 5)), 1_000_000, (), 0.0,
            WDLBound.exact(Outcome.WIN), low,
            EndgameDistance(Outcome.WIN, dtm=3, exact=True),
        )
        chosen = engine._choose((slow, fast), Mode.WIN, win_margin=0)
        self.assertEqual(chosen.move, fast.move)

    def test_short_forced_game_adds_self_play_labels(self):
        rules = Rules(repetition_limit=3, no_progress_plies=8)
        state = state_from_pieces(
            {(4, 3): BLACK_MAN, (3, 2): RED_MAN},
            BLACK,
        )
        model = EmpiricalPolicyValueModel()
        engine = Engine(rules, exact_piece_limit=2, policy_value_model=model)
        summary = train_self_play(
            model,
            engine,
            SearchLimits(depth=1),
            games=2,
            rules=rules,
            start=state,
            exploration_rate=0.0,
            max_game_plies=4,
        )
        self.assertEqual(summary.black_wins, 2)
        self.assertEqual(summary.samples, 2)
        self.assertEqual(model.games, 2)
        self.assertEqual(model.samples, 2)

    def test_game_ending_on_last_allowed_ply_is_not_truncated(self):
        rules = Rules(repetition_limit=3, no_progress_plies=8)
        state = state_from_pieces(
            {(4, 3): BLACK_MAN, (3, 2): RED_MAN},
            BLACK,
        )
        model = EmpiricalPolicyValueModel()
        engine = Engine(rules, exact_piece_limit=2, policy_value_model=model)
        summary = train_self_play(
            model,
            engine,
            SearchLimits(depth=1),
            games=1,
            rules=rules,
            start=state,
            exploration_rate=0.0,
            max_game_plies=1,
        )
        self.assertEqual(summary.black_wins, 1)
        self.assertEqual(summary.samples, 1)
        self.assertEqual(summary.truncated, 0)
        self.assertEqual(model.games, 1)
        self.assertEqual(model.samples, 1)

    def test_truncated_self_play_is_not_falsely_labeled_a_draw(self):
        rules = Rules(repetition_limit=3, no_progress_plies=80)
        model = EmpiricalPolicyValueModel()
        engine = Engine(rules, exact_piece_limit=0, policy_value_model=model)
        summary = train_self_play(
            model,
            engine,
            SearchLimits(depth=1),
            games=1,
            rules=rules,
            start=initial_state(rules=rules),
            exploration_rate=0.0,
            max_game_plies=1,
        )
        self.assertEqual(summary.truncated, 1)
        self.assertEqual(summary.samples, 0)
        self.assertEqual(model.games, 0)
        self.assertEqual(model.samples, 0)


if __name__ == "__main__":
    unittest.main()
