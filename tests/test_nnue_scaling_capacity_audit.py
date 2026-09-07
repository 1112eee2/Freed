import unittest

from scratch.nnue_scaling_capacity_audit import (
    METRICS,
    bootstrap_mean_lower_bounds,
    required_source_files,
    wilson_lower_bound,
)


class NnueScalingCapacityAuditTests(unittest.TestCase):
    def test_wilson_lower_bound_is_conservative(self):
        lower = wilson_lower_bound(766, 768, 2.5758293035489004)
        self.assertGreater(lower, 0.95)
        self.assertLess(lower, 766 / 768)

    def test_bootstrap_is_deterministic_at_source_game_unit(self):
        rows = []
        for index in range(32):
            row = {metric: index % 5 + 1 for metric in METRICS}
            row["with_kings"] = index % 3
            rows.append(row)
        first = bootstrap_mean_lower_bounds(
            rows,
            repetitions=500,
            seed=12345,
            lower_fraction=0.01,
        )
        second = bootstrap_mean_lower_bounds(
            rows,
            repetitions=500,
            seed=12345,
            lower_fraction=0.01,
        )
        self.assertEqual(first, second)
        self.assertGreater(first["total"], 0.0)

    def test_sizing_uses_strictest_stratum_and_rounds_up(self):
        yields = {metric: 20.0 for metric in METRICS}
        yields["with_kings"] = 2.0
        recommended, by_requirement = required_source_files(
            per_unique_game_lcb=yields,
            unique_trajectory_rate_lcb=0.99,
            train_fraction=0.8,
            validation_fraction=0.1,
            test_fraction=0.1,
            requirements={
                "total": 125_000,
                "with_kings": 37_500,
                "validation_total": 10_000,
                "sealed_test_total": 10_000,
            },
            round_to=1024,
        )
        self.assertGreater(by_requirement["with_kings"], by_requirement["total"])
        self.assertEqual(recommended % 1024, 0)
        self.assertGreaterEqual(recommended, by_requirement["with_kings"])


if __name__ == "__main__":
    unittest.main()
