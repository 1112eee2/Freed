import unittest

from scratch.nnue_pilot_finalize import game_shard, validate_pass_summary


class NnuePilotFinalizerTests(unittest.TestCase):
    def test_game_shards_are_stable_and_partition_games(self):
        first = [game_shard(f"game-{index:04d}", 4) for index in range(1000)]
        second = [game_shard(f"game-{index:04d}", 4) for index in range(1000)]
        self.assertEqual(first, second)
        self.assertTrue(all(0 <= shard < 4 for shard in first))

    def test_pass_summary_requires_pass_verdict_and_every_gate(self):
        validate_pass_summary({"verdict": "PASS", "gates": {"one": True}})
        with self.assertRaises(RuntimeError):
            validate_pass_summary({"verdict": "INCOMPLETE", "gates": {"one": True}})
        with self.assertRaises(RuntimeError):
            validate_pass_summary({"verdict": "PASS", "gates": {"one": False}})


if __name__ == "__main__":
    unittest.main()
