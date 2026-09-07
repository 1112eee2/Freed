"""Tests for deterministic native-search A/B benchmark infrastructure."""

import math
import unittest

from makhos.cli import build_parser
from makhos.core import DEFAULT_RULES, terminal_status
from makhos.native_benchmark import (
    NativeBenchmarkRow,
    NativeBenchmarkRun,
    generate_native_benchmark_cases,
    summarize_native_benchmark,
)


class NativeBenchmarkTests(unittest.TestCase):

    def test_case_generation_is_deterministic_and_non_terminal(self) -> None:
        first = generate_native_benchmark_cases(count=8, seed=12345)
        second = generate_native_benchmark_cases(count=8, seed=12345)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(case.target_plies for case in first),
            (4, 8, 12, 16, 20, 24, 28, 32),
        )
        for case in first:
            status = terminal_status(
                case.state,
                repetition_count=case.history[case.state.position_key],
                rules=DEFAULT_RULES,
            )
            self.assertFalse(status.terminal)

    def test_summary_uses_geometric_per_position_node_ratio(self) -> None:
        rows = (
            NativeBenchmarkRow(
                case=1,
                target_plies=4,
                position="first",
                legal_moves=4,
                forced_capture=False,
                candidate=NativeBenchmarkRun("1-5", 10, 12, 80, 10.0),
                baseline=NativeBenchmarkRun("1-5", 10, 12, 100, 11.0),
            ),
            NativeBenchmarkRow(
                case=2,
                target_plies=8,
                position="second",
                legal_moves=2,
                forced_capture=True,
                candidate=NativeBenchmarkRun("2x9", 20, 12, 120, 12.0),
                baseline=NativeBenchmarkRun("2x11", 19, 12, 100, 11.0),
            ),
        )

        summary = summarize_native_benchmark(rows, depth=12, repetitions=2)

        self.assertEqual(summary.candidate_total_nodes, 200)
        self.assertEqual(summary.baseline_total_nodes, 200)
        self.assertAlmostEqual(
            summary.candidate_node_ratio, math.sqrt(0.8 * 1.2)
        )
        self.assertEqual(summary.candidate_time_ratio, 1.0)
        self.assertEqual(summary.same_move_cases, 1)
        self.assertEqual(summary.same_score_cases, 1)
        self.assertEqual(summary.candidate_fewer_node_cases, 1)
        self.assertEqual(summary.equal_node_cases, 0)
        self.assertEqual(summary.baseline_fewer_node_cases, 1)

    def test_cli_exposes_reproducible_benchmark_controls(self) -> None:
        args = build_parser().parse_args(
            [
                "bench-native",
                "--cases",
                "12",
                "--depth",
                "13",
                "--repetitions",
                "3",
                "--seed",
                "99",
            ]
        )

        self.assertEqual(args.cases, 12)
        self.assertEqual(args.depth, 13)
        self.assertEqual(args.repetitions, 3)
        self.assertEqual(args.seed, 99)

    def test_cli_exposes_reproducible_profile_controls(self) -> None:
        args = build_parser().parse_args(
            [
                "profile-native",
                "--library",
                "profile.dll",
                "--cases",
                "16",
                "--depth",
                "14",
                "--seed",
                "101",
                "--search-hash-power",
                "18",
            ]
        )

        self.assertEqual(args.library, "profile.dll")
        self.assertEqual(args.cases, 16)
        self.assertEqual(args.depth, 14)
        self.assertEqual(args.seed, 101)
        self.assertEqual(args.search_hash_power, 18)


if __name__ == "__main__":
    unittest.main()
