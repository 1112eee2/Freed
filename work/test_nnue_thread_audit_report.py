"""Synthetic reporting-contract tests; never run an engine or read match data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import nnue_thread_audit_report as audit


class ThreadAuditReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("ctypes.CDLL", side_effect=AssertionError("DLL loading forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("Subprocess forbidden")):
            cls.header = audit.synthetic_header()
            cls.rows = list(audit.synthetic_rows(cls.header))
            cls.complete = audit.summarize(cls.header, cls.rows)
        cls.validator = audit.ObservationValidator(cls.header)

    def test_complete_matrix_has_all_threads_budgets_and_separate_strata(self):
        report = self.complete
        self.assertEqual(report["valid_rows"], 5760)
        self.assertEqual(report["missing_rows"], 0)
        self.assertEqual(report["status"], "COMPLETE_DIAGNOSTIC")
        self.assertEqual({r["threads"] for r in report["summaries"]}, {1, 2, 4, 6, 8, 12})
        self.assertEqual({r["budget_ms"] for r in report["summaries"]}, {1000, 2000})
        self.assertEqual({r["category"] for r in report["summaries"]}, {"forced", "clock_edge", "playout"})
        for budget in (1000, 2000):
            for threads in (1, 2, 4, 6, 8, 12):
                self.assertEqual(sum(r["observations"] for r in report["summaries"]
                    if r["threads"] == threads and r["budget_ms"] == budget), 96 * 5)
        self.assertFalse(report["strength_evidence"])
        self.assertIsNone(report["recommended_threads"])
        self.assertFalse(report["production_promoted"])
        self.assertIn("FABRICATED", report["synthetic_warning"])

    def test_actual_tt_not_requested_hash_is_reported(self):
        for row in self.complete["summaries"]:
            self.assertEqual(row["metrics"]["allocated_tt_mb"]["median"], 40 * row["threads"])

    def test_missing_telemetry_remains_null_and_blocks_profile_completion(self):
        report = self.complete
        self.assertFalse(report["profile_coverage_complete"])
        self.assertEqual(set(report["missing_telemetry_rows"].values()), {5760})
        for row in report["summaries"]:
            self.assertEqual(row["metrics"]["qnodes"], {"available": 0, "median": None, "p95": None})

    def test_matched_comparisons_and_repeatability_have_exact_denominators(self):
        for row in self.complete["comparisons_vs_1t"]:
            self.assertEqual(row["same_move"], row["matched_observations"])
            self.assertEqual(row["depth_delta_vs_1t"]["median"], 0)
        self.assertEqual(sum(row["matched_observations"] for row in self.complete["comparisons_vs_1t"]), 4800)
        self.assertEqual(sum(row["positions"] for row in self.complete["repeatability"]), 96 * 12)
        for row in self.complete["repeatability"]:
            self.assertEqual(row["all_repetitions_same_move"], row["positions"])

    def test_pairs_match_by_position_repetition_and_budget_not_adjacent_rows(self):
        rows = copy.deepcopy(self.rows)
        target = next(i for i, s in enumerate(self.validator.schedule)
                      if s["threads"] == 6 and audit.case_category(self.validator.cases[s["case"]]) == "playout")
        schedule = self.validator.schedule[target]
        base_index = next(i for i, s in enumerate(self.validator.schedule)
                          if s["case"] == schedule["case"] and s["repetition"] == schedule["repetition"]
                          and s["budget_ms"] == schedule["budget_ms"] and s["threads"] == 1)
        rows[target]["result"]["depth"] = 13
        rows[base_index]["result"]["depth"] = 15
        report = audit.summarize(self.header, rows)
        comparison = next(r for r in report["comparisons_vs_1t"]
            if r["threads"] == 6 and r["budget_ms"] == schedule["budget_ms"] and r["category"] == "playout")
        # Inspect a statistic sensitive to one changed pair, independently of median rounding.
        self.assertEqual(comparison["shallower_than_1t"], 1)
        self.assertEqual(comparison["deeper_than_1t"], 0)

    def test_partial_schedule_has_progress_but_no_comparison_or_recommendation(self):
        for rows in ([], self.rows[:12], self.rows[:-1]):
            report = audit.summarize(self.header, rows)
            self.assertEqual(report["status"], "INCOMPLETE_DIAGNOSTIC")
            self.assertEqual(report["missing_rows"], 5760 - len(rows))
            self.assertEqual(report["comparisons_vs_1t"], [])
            self.assertEqual(report["repeatability"], [])
            self.assertIsNone(report["recommended_threads"])

    def test_no_observation_can_be_duplicated_skipped_or_reordered(self):
        row = copy.deepcopy(self.rows[0])
        for index in (True, -1, 1, 5760):
            row["schedule_index"] = index
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validator.validate(row, 0)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.summarize(self.header, [self.rows[0], self.rows[0]])

    def test_fixture_schedule_history_and_configuration_drift_are_rejected(self):
        for key, value in (("fixtures_sha256", "F" * 64), ("release_manifest_sha256", "not-a-hash")):
            header = copy.deepcopy(self.header)
            header[key] = value
            with self.assertRaises(ValueError):
                audit.validate_header(header, self.validator.fixtures)
        header = copy.deepcopy(self.header)
        header["settings"]["restore_fixture_history"] = False
        with self.assertRaisesRegex(ValueError, "settings"):
            audit.validate_header(header, self.validator.fixtures)
        fixtures = copy.deepcopy(self.validator.fixtures)
        fixtures["cases"][0]["history"][0]["count"] += 1
        with self.assertRaisesRegex(ValueError, "binding"):
            audit.validate_header(self.header, fixtures)

    def test_mixed_run_library_model_and_tablebase_identities_are_rejected(self):
        for key in ("native_library_sha256", "nnue_model_sha256", "native_search_abi", "tablebase_sha256"):
            row = copy.deepcopy(self.rows[0])
            row["identity"][key] = "changed"
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity"):
                self.validator.validate(row, 0)
        row = copy.deepcopy(self.rows[0])
        row["run_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Mixed run"):
            self.validator.validate(row, 0)

    def test_fallback_errors_and_wrong_backend_do_not_enter_aggregates(self):
        for value in ("python", "python-fallback", "forced", "native-single"):
            row = copy.deepcopy(self.rows[0])
            scheduled = self.validator.schedule[0]
            self.assertGreater(self.validator.cases[scheduled["case"]]["legal_moves"], 1)
            # Pick a backend other than the actual expected native path.
            if value == row["result"]["backend"]:
                value = "native-root-split"
            row["result"]["backend"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validator.validate(row, 0)
        row = copy.deepcopy(self.rows[0])
        row["result"]["native_error"] = "failed model load"
        with self.assertRaisesRegex(ValueError, "runtime error"):
            self.validator.validate(row, 0)

    def test_illegal_move_and_pv_tail_are_rejected(self):
        for field, value in (("move", "1-99"), ("pv", []), ("pv", ["1-99"]),
                             ("pv", self.rows[0]["result"]["pv"] + ["1-99"])):
            row = copy.deepcopy(self.rows[0])
            row["result"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validator.validate(row, 0)

    def test_nan_infinity_boolean_and_negative_measurements_are_rejected(self):
        for value in (float("nan"), float("inf"), True, -1):
            row = copy.deepcopy(self.rows[0])
            row["result"]["wall_ms"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validator.validate(row, 0)
        row = copy.deepcopy(self.rows[0])
        row["telemetry"]["qnodes"] = 1.5
        with self.assertRaises(ValueError):
            self.validator.validate(row, 0)

    def test_worker_count_and_total_hash_budget_are_enforced(self):
        row = copy.deepcopy(self.rows[0])
        row["tt_bytes_by_worker"] = []
        with self.assertRaisesRegex(ValueError, "worker count"):
            self.validator.validate(row, 0)
        row = copy.deepcopy(self.rows[0])
        row["tt_bytes_by_worker"][0] = 513 * 1024 * 1024
        with self.assertRaisesRegex(ValueError, "Hash budget"):
            self.validator.validate(row, 0)
        row = copy.deepcopy(self.rows[0])
        row["telemetry"]["active_workers"] = len(row["tt_bytes_by_worker"]) + 1
        with self.assertRaisesRegex(ValueError, "Active workers"):
            self.validator.validate(row, 0)

    def test_partial_last_line_is_preserved_and_never_counts_as_a_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.jsonl"
            raw = (json.dumps(self.header) + '\n' + json.dumps(self.rows[0]) + '\n').encode() + b'{"schedule_index":'
            path.write_bytes(raw)
            report = audit.read_report(path)
            self.assertEqual(report["valid_rows"], 1)
            self.assertEqual(report["trailing_partial_bytes"], len(b'{"schedule_index":'))
            self.assertEqual(report["comparisons_vs_1t"], [])
            self.assertEqual(path.read_bytes(), raw)

    def test_partial_tail_after_full_schedule_still_withholds_comparisons(self):
        report = audit.summarize(self.header, self.rows, trailing_partial_bytes=7)
        self.assertEqual(report["valid_rows"], 5760)
        self.assertEqual(report["missing_rows"], 0)
        self.assertEqual(report["status"], "INCOMPLETE_DIAGNOSTIC")
        self.assertEqual(report["comparisons_vs_1t"], [])

    def test_measured_claim_and_different_host_never_authorize_strength(self):
        header = copy.deepcopy(self.header)
        header["data_kind"] = "measured"
        header["host"].update(physical_cores=4, logical_threads=8)
        rows = copy.deepcopy(self.rows[:12])
        for row in rows:
            row["run_sha256"] = audit.digest(header)
        report = audit.summarize(header, rows)
        self.assertFalse(report["target_host_matches"])
        self.assertFalse(report["strength_evidence"])
        self.assertIsNone(report["recommended_threads"])
        self.assertFalse(report["production_promoted"])
        self.assertIsNone(report["synthetic_warning"])
        with self.assertRaisesRegex(ValueError, "synthetic header"):
            list(audit.synthetic_rows(header))

    def test_crlf_and_lf_observations_have_identical_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.jsonl"
            raw = ('\n'.join(json.dumps(r) for r in [self.header, *self.rows[:12]]) + '\n').encode()
            path.write_bytes(raw)
            lf = audit.read_report(path)
            path.write_bytes(raw.replace(b'\n', b'\r\n'))
            crlf = audit.read_report(path)
            self.assertNotEqual(lf.pop("input_sha256"), crlf.pop("input_sha256"))
            self.assertEqual(lf, crlf)

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_incomplete_header(self):
        for encoded in ('{"a":1,"a":2}', '{"value":NaN}', '{"value":Infinity}'):
            with self.assertRaises(ValueError):
                audit.strict_json(encoded)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.jsonl"
            path.write_bytes(b'{"format":')
            with self.assertRaisesRegex(ValueError, "header is incomplete"):
                audit.read_report(path)

    def test_null_does_not_mean_measured_zero_and_p95_is_nearest_rank(self):
        self.assertEqual(audit.metric([None, 0, None, 0])["available"], 2)
        self.assertEqual(audit.metric([None, 0])["median"], 0)
        self.assertEqual(audit.metric(range(1, 21))["p95"], 19)

    def test_report_writer_refuses_to_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            audit.write_new_json(path, self.complete)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                audit.write_new_json(path, {})
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
