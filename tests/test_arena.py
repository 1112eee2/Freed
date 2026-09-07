import unittest

from makhos.arena import compare_modes_against_shallow_opponent, paired_match
from makhos.search import Mode, SearchLimits


class ArenaTests(unittest.TestCase):
    def test_paired_match_completes_and_accounts_for_every_game(self):
        score = paired_match(
            pairs=1,
            mode_a=Mode.WIN,
            mode_b=Mode.BEST,
            limits=SearchLimits(depth=1),
            opening_plies=2,
            seed=7,
            exact_piece_limit=2,
        )
        self.assertEqual(len(score.games), 2)
        self.assertEqual(score.a_wins + score.draws + score.b_wins, 2)

    def test_gauntlet_gives_each_mode_the_same_number_of_games(self):
        score = compare_modes_against_shallow_opponent(
            pairs=1,
            mode_a=Mode.WIN,
            mode_b=Mode.BEST,
            challenger_limits=SearchLimits(depth=2),
            opponent_limits=SearchLimits(depth=1),
            opening_plies=2,
            seed=9,
            exact_piece_limit=0,
            opponent_error_rate=0.25,
        )
        a_games = score.mode_a.wins + score.mode_a.draws + score.mode_a.losses
        b_games = score.mode_b.wins + score.mode_b.draws + score.mode_b.losses
        self.assertEqual(a_games, 2)
        self.assertEqual(b_games, 2)
        self.assertEqual(len(score.games), 4)


if __name__ == "__main__":
    unittest.main()
