"""Unit tests for the native measurement collector in work/nnue_thread_audit_collect.py."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.nnue_thread_audit_collect import (
    prepare_pilot,
    verify_release,
    AuditCollector,
    PILOT_CASE_IDS,
)
from tools.verification.prepare_nnue_thread_audit import THREADS, BUDGETS, digest
from tools.verification.nnue_thread_audit_report import ObservationValidator


class NnueThreadAuditCollectTests(unittest.TestCase):
    def test_pilot_preparation_schema_and_coverage(self):
        pilot = prepare_pilot()
        self.assertEqual(pilot["format"], "thai-makhos-thread-audit-preparation-v1")
        self.assertEqual(len(pilot["cases"]), 4)
        case_ids = [c["id"] for c in pilot["cases"]]
        for target in PILOT_CASE_IDS:
            self.assertIn(target, case_ids)

        # 4 cases * 2 budgets * 6 thread counts = 48 observations
        self.assertEqual(len(pilot["schedule"]), 48)
        observed_threads = {s["threads"] for s in pilot["schedule"]}
        self.assertEqual(observed_threads, set(THREADS))
        observed_budgets = {s["budget_ms"] for s in pilot["schedule"]}
        self.assertEqual(observed_budgets, set(BUDGETS))

        # Check coverage categories: quiet, multi_capture, clock_edge, forced
        cases_by_id = {c["id"]: c for c in pilot["cases"]}
        self.assertTrue(cases_by_id["playout-062"]["multi_capture"])
        self.assertTrue(cases_by_id["clock-edge-0-1"]["id"].startswith("clock-edge-"))
        self.assertEqual(cases_by_id["playout-039"]["legal_moves"], 1)

    def test_verify_release_passes_with_promoted_release(self):
        release, manifest, identity = verify_release()
        self.assertEqual(release["profile"], "nnue")
        self.assertTrue(release["nnue_enabled"])
        self.assertEqual(release["native_search_abi"], 5)
        self.assertEqual(release["nnue_feature_abi"], "thai-makhos-shared-137-v1")
        self.assertEqual(set(identity["tablebase_sha256"].keys()), {"4", "5", "6"})
        for sha in identity["tablebase_sha256"].values():
            self.assertEqual(len(sha), 64)

    def test_tt_bytes_allocation_bounds(self):
        release, manifest, identity = verify_release()
        fixtures = prepare_pilot()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "obs.jsonl"
            collector = AuditCollector(release, manifest, identity, fixtures, output)
            self.addCleanup(collector.close)

            from makhos.native import hash_power_for_megabytes
            for t in THREADS:
                hp = hash_power_for_megabytes(512, partitions=t, entry_bytes=collector.entry_bytes)
                per_worker = (1 << hp) * collector.entry_bytes
                total = per_worker * t
                self.assertLessEqual(total, 512 * 1024 * 1024)
                self.assertGreater(total, 0)

    def test_interactive_session_pauses_collector(self):
        release, manifest, identity = verify_release()
        fixtures = prepare_pilot()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "obs.jsonl"
            collector = AuditCollector(release, manifest, identity, fixtures, output)
            self.addCleanup(collector.close)

            # Assert GUI activity pauses collection
            with patch("tools.verification.nnue_thread_audit_collect.interactive_session_active", return_value=True):
                result = collector.run(limit=5)
                self.assertEqual(result["status"], "PAUSED_FOR_INTERACTIVE_PLAY")
                self.assertEqual(result["completed"], 0)

    def test_pilot_execution_and_resume(self):
        release, manifest, identity = verify_release()
        fixtures = prepare_pilot()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "obs.jsonl"
            collector = AuditCollector(release, manifest, identity, fixtures, output)
            self.addCleanup(collector.close)

            # Run first 2 observations (forced moves or small limit)
            res1 = collector.run(limit=2)
            self.assertEqual(res1["status"], "PARTIAL")
            self.assertEqual(res1["completed"], 2)

            # Verify file exists and has 3 lines: header + 2 observations
            lines = output.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 3)

            # Validate each row
            header = json.loads(lines[0])
            validator = ObservationValidator(header, fixtures=fixtures)
            for idx in range(2):
                row = json.loads(lines[idx + 1])
                validator.validate(row, idx)

            # Resume to run 2 more observations (total 4)
            collector2 = AuditCollector(release, manifest, identity, fixtures, output)
            self.addCleanup(collector2.close)
            res2 = collector2.run(limit=2)
            self.assertEqual(res2["status"], "PARTIAL")
            self.assertEqual(res2["completed"], 4)

            lines2 = output.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines2), 5)  # header + 4 rows
            for idx in range(4):
                row = json.loads(lines2[idx + 1])
                validator.validate(row, idx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
