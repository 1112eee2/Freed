"""Low-resource lifecycle tests; no native engine, arena, or sealed data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import nnue_gate_c_control as control
from makhos.sprt import calculate_pentanomial_sprt


class GateControlTests(unittest.TestCase):
    def setUp(self):
        self.config = {"elo0": 0, "elo1": 2, "max_pairs": 10000}
        buckets = [2, 65, 233, 175, 71]
        status, llr, elo, error = calculate_pentanomial_sprt(tuple(buckets))
        self.payload = {"format": "thai-makhos-sprt-result-v2", "complete": True,
            "config": self.config, "result": {"pairs": 546, "games": 1092,
                "wins": 472, "draws": 396, "losses": 224, "pentanomial": buckets,
                "status": status, "llr": llr, "elo": elo, "elo_95_error": error}}

    def test_real_pentanomial_reproduces_pass(self):
        self.assertEqual(control.checked_result(self.payload, self.config)["status"], "PASS")

    def test_rejects_config_drift(self):
        with self.assertRaises(ValueError):
            control.checked_result(self.payload, {**self.config, "threads": 6})

    def test_rejects_count_statistic_and_type_corruption(self):
        mutations = [("pairs", 547), ("wins", 471), ("games", 1094),
                     ("llr", 3.0), ("elo", float("nan")), ("status", "FAIL"),
                     ("pentanomial", [2, 65, 233, 175, True])]
        for key, value in mutations:
            with self.subTest(key=key):
                payload = copy.deepcopy(self.payload)
                payload["result"][key] = value
                with self.assertRaises(ValueError):
                    control.checked_result(payload, self.config)

    def test_score_mass_must_match_pentanomial(self):
        self.payload["result"]["wins"] += 1
        self.payload["result"]["losses"] -= 1
        with self.assertRaises(ValueError):
            control.checked_result(self.payload, self.config)

    def test_early_inconclusive_cannot_be_final(self):
        buckets = [0, 0, 1, 0, 0]
        status, llr, elo, error = calculate_pentanomial_sprt(tuple(buckets))
        self.payload["result"] = {"pairs": 1, "games": 2, "wins": 0, "draws": 2,
            "losses": 0, "pentanomial": buckets, "status": status, "llr": llr,
            "elo": elo, "elo_95_error": error}
        with self.assertRaises(ValueError):
            control.checked_result(self.payload, self.config)
        self.payload["complete"] = False
        control.checked_result(self.payload, self.config)
        self.payload["complete"] = True
        self.config["max_pairs"] = 1
        control.checked_result(self.payload, self.config)

    def test_pid_reuse_is_not_a_live_arena(self):
        recorded = {"pid": 42, "creation_ticks": 100}
        self.assertFalse(control.same_live_process(recorded, None))
        self.assertFalse(control.same_live_process(recorded, {**recorded, "creation_ticks": 101, "live": True}))
        self.assertFalse(control.same_live_process(recorded, {**recorded, "live": False}))
        self.assertTrue(control.same_live_process(recorded, {**recorded, "live": True}))

    def test_runtime_states_do_not_invent_progress(self):
        self.assertEqual(control.run_state(None, False, 0, False), "NOT_STARTED")
        self.assertEqual(control.run_state(None, True, 0, False), "RUNNING")
        self.assertEqual(control.run_state(None, True, 0, True), "YIELDING_TO_GUI")
        self.assertEqual(control.run_state(None, False, 0, True), "PAUSED_FOR_GUI")
        self.assertEqual(control.run_state(self.payload, False, 0, False), "FINISHED_PASS")
        self.assertEqual(control.run_state(self.payload, False, 8, False), "ERROR_REVIEW_LOG")
        self.payload["complete"] = False
        self.assertEqual(control.run_state(self.payload, False, 0, False), "STOPPED_REQUIRES_VERIFIED_RESUME")

    def test_contract_hash_drift_rejected_before_payload_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / control.CONTRACT
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contract hash"):
                control.contract_at(root)

    def test_shared_read_does_not_prevent_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(self.payload), encoding="utf-8")
            replacement = path.with_suffix(".tmp")
            replacement.write_text("{}", encoding="utf-8")
            original_load = json.load
            def replace_while_reader_is_open(stream):
                replacement.replace(path)
                return original_load(stream)
            with patch.object(control.json, "load", side_effect=replace_while_reader_is_open):
                self.assertEqual(control.read_json(path), self.payload)
            self.assertEqual(control.read_json(path), {})

    def test_missing_active_manifest_is_normal(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(control.active_manifest(Path(directory)))

    def test_live_status_never_opens_the_arena_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first.json", root / "second.json"
            first.write_text("{}")
            second.write_text("{}")
            stdout, stderr = root / "stdout.log", root / "stderr.log"
            stdout.write_text('SPRT_CONFIG ' + json.dumps(self.config) + '\n'
                'Pair 546 (1092 games) | W: 472 D: 396 L: 224 | Ptnml: 2/65/233/175/71 | LLR: +2.95 | Elo: +80.3 +/-95% 13.5 | Status: PASS\n', encoding="utf-8")
            stderr.write_text("")
            identity = {"pid": 42, "creation_ticks": 100, "live": True}
            manifest = {"output": "second.json", "process": identity,
                        "stdout": str(stdout), "stderr": str(stderr)}
            contract = {"matches": [{"output": "first.json", "fixed_move_time_ms": 1000},
                                    {"output": "second.json", "fixed_move_time_ms": 2000}]}
            def guarded_read(path):
                if Path(path) == second:
                    raise AssertionError("Monitor opened a live checkpoint")
                return self.payload
            with patch.object(control, "contract_at", return_value=contract), \
                 patch.object(control, "expected_configs", return_value=[self.config, self.config]), \
                 patch.object(control, "active_manifest", return_value=manifest), \
                 patch.object(control, "process_identity", return_value=identity), \
                 patch.object(control, "read_json", side_effect=guarded_read), \
                 patch("makhos.workload_isolation.interactive_session_active", return_value=False):
                result = control.snapshot(root)
            self.assertEqual(result["matches"][1]["result"]["pairs"], 546)
            self.assertEqual(result["matches"][1]["state"], "RUNNING")

    def test_predecessor_hash_cannot_be_substituted(self):
        with patch.object(control, "sha", return_value="WRONG"):
            with self.assertRaisesRegex(ValueError, "1000ms result changed"):
                control.expected_configs({"matches": [{"output": "unused"}]})

    def test_live_log_does_not_count_a_partial_line_or_accept_config_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stdout.log"
            path.write_text('SPRT_CONFIG ' + json.dumps(self.config) + '\nPair 1 (2 games)', encoding="utf-8")
            self.assertIsNone(control.read_live_result(path, self.config))
            with self.assertRaisesRegex(ValueError, "configuration mismatch"):
                control.read_live_result(path, {**self.config, "seed": 123})

    def test_pointer_publication_retries_only_permission_denial(self):
        with patch.object(control.os, "replace", side_effect=[PermissionError(), None]) as replace, \
             patch.object(control.time, "sleep"):
            control.publish_pointer("temporary", "pointer")
            self.assertEqual(replace.call_count, 2)
        with patch.object(control.os, "replace", side_effect=FileNotFoundError()), \
             patch.object(control.time, "sleep") as sleep:
            with self.assertRaises(FileNotFoundError):
                control.publish_pointer("temporary", "pointer")
            sleep.assert_not_called()

    def test_config_derivation_changes_only_budget_and_seed(self):
        contract = {"matches": [{"output": "first", "fixed_move_time_ms": 1000, "seed": 11},
                                {"output": "second", "fixed_move_time_ms": 2000, "seed": 12}]}
        self.config.update(fixed_move_time_ms=1000, seed=11)
        with patch.object(control, "sha", return_value=control.FIRST_PASS_SHA), patch.object(control, "read_json", return_value=self.payload):
            first, second = control.expected_configs(contract)
        self.assertEqual(first, self.config)
        self.assertEqual(second, {**self.config, "fixed_move_time_ms": 2000, "seed": 12})
        self.assertIsNot(first, self.config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
