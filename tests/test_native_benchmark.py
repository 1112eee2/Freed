"""Tests for deterministic native-search A/B benchmark infrastructure."""

from contextlib import redirect_stdout
import io
import json
import math
import unittest
from unittest.mock import patch

from makhos.cli import build_parser
from makhos.core import DEFAULT_RULES, terminal_status
from makhos.native_benchmark import (
    NativeBenchmarkReport,
    NativeBenchmarkRow,
    NativeBenchmarkRun,
    generate_native_benchmark_cases,
    summarize_native_benchmark,
)


def _synthetic_report(nnue_sha256: str | None = None) -> NativeBenchmarkReport:
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
    )
    return NativeBenchmarkReport(
        candidate_path="candidate.so",
        candidate_sha256="c" * 64,
        candidate_abi=5,
        baseline_path="baseline.so",
        baseline_sha256="b" * 64,
        baseline_abi=5,
        seed=99,
        hash_power=18,
        ply_schedule=(4,),
        rows=rows,
        summary=summarize_native_benchmark(rows, depth=12, repetitions=1),
        candidate_nnue_model_sha256=nnue_sha256,
        baseline_nnue_model_sha256=nnue_sha256,
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

    def _run_bench_native(self, argv, report):
        args = build_parser().parse_args(["bench-native", *argv])
        output = io.StringIO()
        with patch(
            "makhos.native_benchmark.compare_native_libraries",
            return_value=report,
        ) as compare, redirect_stdout(output):
            self.assertEqual(args.func(args), 0)
        return compare, output.getvalue().splitlines()

    def test_bench_native_command_prints_config_rows_and_summary(self) -> None:
        # Regression: the Phase 2C handler read report keys and row/summary
        # attributes that do not exist, so the command crashed before output.
        compare, lines = self._run_bench_native(
            [
                "--candidate-library", "candidate.so",
                "--baseline-library", "baseline.so",
                "--cases", "1",
                "--depth", "12",
                "--repetitions", "1",
                "--seed", "99",
                "--search-hash-power", "18",
            ],
            _synthetic_report(),
        )

        compare.assert_called_once_with(
            "candidate.so",
            "baseline.so",
            count=1,
            depth=12,
            repetitions=1,
            seed=99,
            hash_power=18,
            candidate_nnue_model=None,
            baseline_nnue_model=None,
        )
        self.assertTrue(lines[0].startswith("NATIVE_BENCH_CONFIG "))
        config = json.loads(lines[0].removeprefix("NATIVE_BENCH_CONFIG "))
        self.assertEqual(
            (config["cases"], config["depth"], config["repetitions"]),
            (1, 12, 1),
        )
        self.assertEqual(config["candidate_sha256"], "c" * 64)
        self.assertIsNone(config["candidate_nnue_model_sha256"])
        self.assertIn("nodes 80/100 (0.8000x)", lines[1])
        self.assertIn("move 1-5/1-5", lines[1])
        self.assertTrue(lines[-1].startswith("NATIVE_BENCH_RESULT "))
        result = json.loads(lines[-1].removeprefix("NATIVE_BENCH_RESULT "))
        self.assertEqual(result["same_move_cases"], 1)
        self.assertAlmostEqual(result["candidate_node_ratio"], 0.8)

    def test_bench_native_command_passes_nnue_models_through(self) -> None:
        compare, lines = self._run_bench_native(
            [
                "--candidate-library", "candidate.so",
                "--baseline-library", "baseline.so",
                "--candidate-nnue-model", "model.mknnue",
                "--baseline-nnue-model", "model.mknnue",
            ],
            _synthetic_report("a" * 64),
        )

        kwargs = compare.call_args.kwargs
        self.assertEqual(kwargs["candidate_nnue_model"], "model.mknnue")
        self.assertEqual(kwargs["baseline_nnue_model"], "model.mknnue")
        config = json.loads(lines[0].removeprefix("NATIVE_BENCH_CONFIG "))
        self.assertEqual(config["candidate_nnue_model_sha256"], "a" * 64)
        self.assertEqual(config["baseline_nnue_model_sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
