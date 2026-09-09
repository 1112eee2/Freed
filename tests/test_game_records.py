"""Saved games must replay, retain provenance, and separate labels from rules."""

from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from makhos.core import BLACK, DEFAULT_RULES, apply_move, format_position, legal_moves, parse_position
from makhos.game_analysis import GameRecordError, load_game_record, replay_game
from makhos.game_records import save_game_record
from makhos.server import EngineRequestHandler, MakhosHTTPServer


def record_for(position="B:BM25:RM1", moves=(), clock=0, source="user", winner="black"):
    state = parse_position(position, reversible_plies=clock)
    record = {
        "format": "thai-makhos-game-v1", "start_position": position,
        "start_reversible_plies": clock, "moves": [], "position_history": [position],
        "engine": {"rules_profile": "project"},
        "result": {"source": source, "winner": winner},
    }
    for notation in moves:
        move = next(m for m in legal_moves(state) if m.notation == notation)
        record["moves"].append({"ply": len(record["moves"]) + 1,
                                "player": "black" if state.turn == BLACK else "red",
                                "notation": notation, "actor": "human"})
        state = apply_move(state, move)
        record["position_history"].append(format_position(state))
    record.update(final_position=format_position(state), reversible_plies=state.reversible_plies)
    return record


class GameRecordSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "saved_games"

    def save(self, record):
        return save_game_record(record, self.directory, rules=DEFAULT_RULES)

    def test_user_win_loss_draw_are_annotations_not_proofs(self):
        for winner in ("black", "red", None):
            with self.subTest(winner=winner):
                record = record_for(moves=("25-21",), winner=winner)
                record["moves"][0].update(actor="engine", engine={
                    "native_library_sha256": "dll", "nnue_model_sha256": "model", "depth": 12,
                })
                path = self.save(record)
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["result"], {
                    "source": "user", "winner": winner, "reason": "user_adjudication",
                })
                self.assertFalse(saved["rules_result"]["terminal"])
                self.assertEqual(saved["moves"], record["moves"])
                self.assertEqual(format_position(replay_game(load_game_record(path)).final), saved["final_position"])

    def test_natural_capture_win_and_80_ply_draw(self):
        for record in (
            record_for("B:BM25:RM22,15", ("25x18x11",), source="rules"),
            record_for("B:BK1:RK32", ("1-5",), clock=79, source="rules", winner=None),
        ):
            with self.subTest(position=record["start_position"]):
                saved = json.loads(self.save(record).read_text())
                self.assertTrue(saved["rules_result"]["terminal"])
                self.assertEqual(saved["rules_result"]["winner"], record["result"]["winner"])

    def test_repetition_draw_retains_entire_history(self):
        record = record_for("B:BK1:RK32", ("1-5", "32-28", "5-1", "28-32") * 2,
                            source="rules", winner=None)
        saved = json.loads(self.save(record).read_text())
        self.assertEqual(saved["rules_result"]["reason"], "repetition")
        self.assertEqual(len(saved["position_history"]), 9)

    def test_invalid_records_create_no_files(self):
        valid = record_for(moves=("25-21",))
        mutations = [
            lambda r: r.update(result=None),
            lambda r: r.update(result={"source": "rules", "winner": "black"}),
            lambda r: r.update(result={"source": "user"}),
            lambda r: r.update(result={"source": "user", "winner": "human"}),
            lambda r: r.update(final_position="B:BM25:RM1"),
            lambda r: r.update(reversible_plies=80),
            lambda r: r["position_history"].pop(),
            lambda r: r["position_history"].__setitem__(1, "B:BK1:RK32"),
            lambda r: r["moves"][0].update(notation="25-1"),
            lambda r: r["moves"][0].update(player="red"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                record = deepcopy(valid)
                mutate(record)
                with self.assertRaises(ValueError):
                    self.save(record)
                self.assertFalse(self.directory.exists())

    def test_natural_result_cannot_be_falsified_but_user_can_override(self):
        record = record_for("B:BM25:RM22,15", ("25x18x11",), source="rules", winner="red")
        with self.assertRaises(GameRecordError):
            self.save(record)
        record["result"]["source"] = "user"
        saved = json.loads(self.save(record).read_text())
        self.assertEqual(saved["result"]["winner"], "red")
        self.assertEqual(saved["rules_result"]["winner"], "black")

    def test_unique_files_ignore_client_filename_and_survive_next_save(self):
        record = record_for()
        record.update(filename="../../outside.json", path="../../outside.json")
        first = self.save(record)
        original = first.read_bytes()
        second = self.save(record)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.directory)
        self.assertEqual(second.parent, self.directory)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(len(list(Path(self.temp.name).rglob("*.json"))), 2)

    def test_write_failure_removes_partial_record(self):
        with patch("makhos.game_records.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.save(record_for())
        self.assertEqual(list(self.directory.iterdir()), [])


class GameRecordHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MakhosHTTPServer(("127.0.0.1", 0), EngineRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, body, headers=None):
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request("POST", "/api/save-game", body=body,
                               headers=headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_http_save_is_replayable_without_loading_engine(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("makhos.server.GAME_RECORDS_DIR", Path(directory)), \
                patch("makhos.server.get_default_engine", side_effect=AssertionError("must not load engine")):
            code, response = self.request(json.dumps(record_for(moves=("25-21",))))
            self.assertEqual(code, 201)
            self.assertTrue(response["saved"])
            self.assertEqual(response["path"], "saved_games/" + response["filename"])
            self.assertEqual(len(replay_game(load_game_record(Path(directory) / response["filename"])).plies), 1)

    def test_bad_json_and_rules_are_rejected(self):
        bad_profile = record_for()
        bad_profile["engine"]["rules_profile"] = "unknown"
        for body in ("{", "[]", "null", json.dumps(bad_profile)):
            with self.subTest(body=body):
                self.assertEqual(self.request(body)[0], 400)
        self.assertEqual(self.request("{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("", {"Content-Type": "application/json", "Content-Length": "5000000"})[0], 413)

    def test_http_write_failure_is_reported_for_retry(self):
        with patch("makhos.server.save_game_record", side_effect=OSError("disk full")):
            code, response = self.request(json.dumps(record_for()))
        self.assertEqual(code, 500)
        self.assertIn("cannot write", response["error"])


if __name__ == "__main__":
    unittest.main()
