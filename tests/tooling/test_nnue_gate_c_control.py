"""Low-resource lifecycle tests; no native engine, arena, or sealed data."""
import copy
import hashlib
import json
from itertools import product
from pathlib import Path
import tempfile
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tools.arena import nnue_gate_c_control as control
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

    def test_pair_counts_match_all_realizable_results_through_three_pairs(self):
        # Independent enumeration of game outcomes: 0=L, 1=D, 2=W.
        for pairs in range(4):
            possible = {}
            for outcomes in product(range(3), repeat=2 * pairs):
                buckets = tuple(sum(outcomes[i] + outcomes[i + 1] == b
                                    for i in range(0, 2 * pairs, 2)) for b in range(5))
                possible.setdefault(buckets, set()).add(
                    (outcomes.count(2), outcomes.count(1), outcomes.count(0)))
            for buckets, valid_counts in possible.items():
                for wins in range(2 * pairs + 1):
                    for draws in range(2 * pairs - wins + 1):
                        losses = 2 * pairs - wins - draws
                        result = dict(pairs=pairs, games=2 * pairs, wins=wins,
                                      draws=draws, losses=losses, pentanomial=buckets)
                        if (wins, draws, losses) in valid_counts:
                            control.checked_pair_counts(result, 3)
                        else:
                            with self.assertRaises(ValueError):
                                control.checked_pair_counts(result, 3)

    def test_equal_score_mass_does_not_prove_possible_game_results(self):
        # LL + WW has score 2, as do four draws, but they cannot be the same pairs.
        with self.assertRaisesRegex(ValueError, "cannot be realized"):
            control.checked_pair_counts(dict(pairs=2, games=4, wins=0, draws=4,
                                             losses=0, pentanomial=[1, 0, 0, 0, 1]), 10000)

    def test_unfinalized_cap_checkpoint_is_a_stop_condition(self):
        self.payload["complete"] = False
        self.config["max_pairs"] = 1
        status, llr, elo, error = calculate_pentanomial_sprt((0, 0, 1, 0, 0))
        self.payload["result"] = dict(pairs=1, games=2, wins=0, draws=2, losses=0,
            pentanomial=[0, 0, 1, 0, 0], status=status, llr=llr, elo=elo, elo_95_error=error)
        with self.assertRaisesRegex(RuntimeError, "stop condition"):
            control.require_resumable_result(self.payload, self.config)
        self.config["max_pairs"] = 2
        control.require_resumable_result(self.payload, self.config)

    def test_pass_or_fail_stops_even_before_final_publication(self):
        self.payload["complete"] = False
        with self.assertRaisesRegex(RuntimeError, "stop condition"):
            control.require_resumable_result(self.payload, self.config)
        r = self.payload["result"]
        r["wins"], r["losses"] = r["losses"], r["wins"]
        r["pentanomial"].reverse()
        r["status"], r["llr"], r["elo"], r["elo_95_error"] = calculate_pentanomial_sprt(tuple(r["pentanomial"]))
        self.assertEqual(r["status"], "FAIL")
        with self.assertRaisesRegex(RuntimeError, "stop condition"):
            control.require_resumable_result(self.payload, self.config)

    def log_line(self, pairs, wins, draws, losses, buckets):
        status = calculate_pentanomial_sprt(tuple(buckets))[0]
        return (f"Pair {pairs} ({2 * pairs} games) | W: {wins} D: {draws} L: {losses} | "
                f"Ptnml: {'/'.join(map(str, buckets))} | LLR: diagnostic | Status: {status}\n")

    def read_lines(self, *lines):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stdout.log"
            content = ('SPRT_CONFIG ' + json.dumps(self.config) + '\n' + ''.join(lines)).encode("utf-8")
            path.write_bytes(content)
            return control.read_live_result(path, self.config)

    def test_live_pairs_must_be_contiguous_and_never_rewrite_past_outcomes(self):
        first = self.log_line(1, 0, 2, 0, [0, 0, 1, 0, 0])
        second = self.log_line(2, 0, 4, 0, [0, 0, 2, 0, 0])
        self.assertEqual(self.read_lines(first, second)["result"]["pairs"], 2)
        invalid = [first, self.log_line(3, 0, 6, 0, [0, 0, 3, 0, 0]),
                   self.log_line(2, 2, 0, 2, [0, 0, 2, 0, 0]),
                   self.log_line(2, 2, 0, 2, [1, 0, 0, 0, 1])]
        for line in invalid:
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.read_lines(first, line)

    def test_live_log_rejects_extra_pair_after_pass(self):
        first = self.log_line(546, 472, 396, 224, [2, 65, 233, 175, 71])
        second = self.log_line(547, 472, 398, 224, [2, 65, 234, 175, 71])
        with self.assertRaisesRegex(ValueError, "stop condition"):
            self.read_lines(first, second)

    def test_live_tail_handles_clipped_line_and_exact_line_boundary(self):
        pair = self.log_line(546, 472, 396, 224, [2, 65, 233, 175, 71])
        for suffix in ("x" * (65536 - len(pair) - 1) + "\n", "x" * 65536 + "\n"):
            # In one case the 64 KiB window begins at Pair; in the other
            # it starts inside an unrelated diagnostic line.
            result = self.read_lines("x" * 70000 + "\n", pair, suffix)
            if len(suffix) < 65536:
                self.assertEqual(result["result"]["pairs"], 546)
            else:
                self.assertIsNone(result)
        result = self.read_lines("x" * 70000 + "\n", pair)
        self.assertEqual(result["result"]["pairs"], 546)

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

    def test_preflight_reports_missing_evidence_without_claiming_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            report = control.repository_preflight(Path(directory))
        self.assertEqual(report["status"], "BLOCKED_LOCAL_PREREQUISITES")
        self.assertEqual(report["runtime_state"], "UNKNOWN_NOT_INSPECTED")
        self.assertFalse(report["native_search_authorized"])
        self.assertFalse(report["production_promoted"])

    def test_preflight_diagnoses_checkout_newlines_but_still_rejects_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / control.CONTRACT
            path.parent.mkdir(parents=True)
            contract = {"artifact_sha256": {}, "evidence_sha256": {},
                "matches": [{"output": "first.json"}, {"output": "second.json"}],
                "python_executable": sys.executable, "python_version": sys.version.split()[0]}
            raw = (json.dumps(contract, indent=2) + '\n').encode()
            path.write_bytes(raw)
            frozen = hashlib.sha256(raw.replace(b'\n', b'\r\n')).hexdigest().upper()
            with patch.object(control, "CONTRACT_SHA", frozen):
                report = control.repository_preflight(root)
                with self.assertRaisesRegex(ValueError, "contract hash"):
                    control.contract_at(root)
            self.assertEqual(report["status"], "BLOCKED_LOCAL_PREREQUISITES")
            self.assertIn("contract_checkout", report)
            self.assertEqual(path.read_bytes(), raw)
            self.assertIn({"kind": "missing_runtime_evidence", "path": "second.json"}, report["blockers"])

    def test_preflight_never_opens_results_manifest_or_large_tablebase(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build/runtime").mkdir(parents=True)
            small = root / "model"
            small.write_bytes(b"model")
            tablebase = root / "tablebase"
            with tablebase.open("wb") as stream:
                stream.truncate(1024 * 1024 + 1)
            protected = [root / control.ACTIVE, root / "first.json", root / "second.json", tablebase]
            for path in protected[:-1]:
                path.write_text("intentionally invalid JSON: must not be parsed")
            contract = {"artifact_sha256": {"model": control.sha(small), "tablebase": "unread"},
                "evidence_sha256": {"first.json": "unread"},
                "matches": [{"output": "first.json"}, {"output": "second.json"}],
                "python_executable": sys.executable, "python_version": sys.version.split()[0]}
            original_open = Path.open
            def guarded_open(path, *args, **kwargs):
                if path in protected:
                    raise AssertionError(f"Preflight read protected payload: {path}")
                return original_open(path, *args, **kwargs)
            with patch.object(control, "contract_at", return_value=contract), \
                 patch.object(control, "process_identity", side_effect=AssertionError("No process probe")), \
                 patch.object(Path, "open", guarded_open):
                report = control.repository_preflight(root)
            self.assertEqual(report["result_payload_reads"], 0)
            self.assertEqual(report["files"][0]["check"], "MATCH")
            self.assertEqual(report["files"][1]["check"], "PRESENT_NOT_HASHED")
            self.assertFalse(report["native_search_authorized"])
            self.assertFalse(report["production_promoted"])
            self.assertEqual(report["runtime_state"], "UNKNOWN_NOT_INSPECTED")
            if control.os.name == "nt":
                self.assertEqual(report["status"], "LOCAL_PREREQUISITES_PRESENT_HOST_VERIFICATION_REQUIRED")
            else:
                self.assertEqual([b["kind"] for b in report["blockers"]], ["host_platform"])
            with patch.object(control, "contract_at", return_value=contract), \
                 patch.object(control, "os", SimpleNamespace(name="nt")), \
                 patch.object(Path, "open", guarded_open):
                ready = control.repository_preflight(root)
            self.assertEqual(ready["blockers"], [])
            self.assertEqual(ready["status"], "LOCAL_PREREQUISITES_PRESENT_HOST_VERIFICATION_REQUIRED")
            self.assertFalse(ready["native_search_authorized"])
            self.assertFalse(ready["production_promoted"])
            small.write_bytes(b"changed")
            with patch.object(control, "contract_at", return_value=contract):
                report = control.repository_preflight(root)
            self.assertIn({"kind": "hash_mismatch", "path": "model"}, report["blockers"])

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
