import unittest

from makhos.verify import verify_one_vs_one


class EndgameVerificationTests(unittest.TestCase):
    def test_exhaustive_one_vs_one_accounts_for_every_root(self):
        result = verify_one_vs_one(no_progress_plies=2, max_states=250_000)
        self.assertGreater(result.positions, 5_000)
        self.assertEqual(result.wins + result.draws + result.losses, result.positions)
        self.assertGreater(result.solved_states, result.positions)


if __name__ == "__main__":
    unittest.main()

