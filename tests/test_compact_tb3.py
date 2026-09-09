"""Portable artifact and startup regressions; no native build required."""

from collections import Counter
from dataclasses import replace
import hashlib
from itertools import combinations
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zlib

from makhos.compact_tb3 import (BOARD_COUNT, DEFAULT_ARTIFACT, HEADER,
                                CompactTablebase, board_index, invariant_digest)
from makhos.core import Rules, State, parse_position
from makhos.exact import ExactSolver, Outcome
from makhos.search import Engine, SearchLimits
from makhos.tb3_service import TB3Service
from tests.test_server import DummyHandler


class CompactTB3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = DEFAULT_ARTIFACT.read_bytes()

    def load_bytes(self, encoded):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.tb3"
            path.write_bytes(encoded)
            return CompactTablebase(path)

    def corrupt_header(self, index, value):
        fields = list(HEADER.unpack_from(self.encoded))
        fields[index] = value
        return HEADER.pack(*fields) + self.encoded[HEADER.size:]

    def test_load_is_independent_of_native_dll_and_solver(self):
        with patch("ctypes.CDLL", side_effect=AssertionError("no DLL allowed")), \
                patch.object(ExactSolver, "solve", side_effect=AssertionError("no solve allowed")), \
                CompactTablebase() as tb:
            self.assertEqual(tb.probe(parse_position("B:BK6,15:RK28")).outcome, Outcome.WIN)
            self.assertLess(tb.payload_bytes, 4 * 1024 * 1024)

    def test_rejects_header_identity_version_and_rule_drift(self):
        for index, value in ((0, b"INVALID!"), (1, 2), (2, 79), (3, BOARD_COUNT - 1),
                             (4, 0), (5, 1), (6, 1), (7, b"x" * 32), (8, b"x" * 32)):
            with self.subTest(field=index), self.assertRaises(ValueError):
                self.load_bytes(self.corrupt_header(index, value))

    def test_rejects_corrupt_truncated_and_appended_data(self):
        damaged = bytearray(self.encoded)
        damaged[-10] ^= 1
        for encoded in (b"", self.encoded[:64], self.encoded[:-1], self.encoded + b"x", damaged):
            with self.subTest(size=len(encoded)), self.assertRaises(ValueError):
                self.load_bytes(encoded)

    def test_rejects_wrong_payload_checksum(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.load_bytes(self.corrupt_header(9, b"x" * 32))

    def test_rejects_expansion_beyond_declared_length(self):
        fields = list(HEADER.unpack_from(self.encoded))
        packed = zlib.compress(b"\0" * (fields[5] + 1))
        fields[6] = len(packed)
        with self.assertRaisesRegex(ValueError, "length"):
            self.load_bytes(HEADER.pack(*fields) + packed)

    def test_rejects_bad_vector_reference_even_with_valid_checksum(self):
        fields = list(HEADER.unpack_from(self.encoded))
        data = bytearray(zlib.decompress(self.encoded[HEADER.size:]))
        state = parse_position("B:BK6,15:RK28")
        index = board_index(state) * 4
        data[index:index + 4] = b"\xff" * 4
        packed = zlib.compress(data)
        fields[6], fields[9] = len(packed), hashlib.sha256(data).digest()
        with self.load_bytes(HEADER.pack(*fields) + packed) as tb:
            with self.assertRaisesRegex(ValueError, "reference"):
                tb.probe(state)

    def test_closed_instance_cannot_probe_and_close_is_idempotent(self):
        tb = CompactTablebase()
        tb.close()
        tb.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            tb.probe(parse_position("B:BK1:RK32"))

    def test_clock_and_material_limits(self):
        with CompactTablebase() as tb:
            for position in ("B:BK1:RK32", "B:BM5:RM1"):
                state = parse_position(position, reversible_plies=80)
                self.assertEqual(tb.probe(state).outcome, Outcome.DRAW)
                with self.assertRaises(ValueError):
                    tb.probe(replace(state, reversible_plies=81))
            with self.assertRaises(ValueError):
                tb.probe(parse_position("B:BK1,5:RK28,32"))
            with self.assertRaises(ValueError):
                tb.probe(State((0,) * 32, 1))

    def test_rule_identity_is_portable_across_git_newline_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_bytes(b"first\nsecond\n")
            expected = invariant_digest(path)
            path.write_bytes(b"first\r\nsecond\r\n")
            self.assertEqual(invariant_digest(path), expected)

    def test_independent_colex_rank_and_type_turn_layout(self):
        # All square combinations, both sides; kings avoid invalid man rows.
        offset = 0
        for pieces in (1, 2, 3):
            ordered = sorted(combinations(range(32), pieces), key=lambda x: tuple(reversed(x)))
            for rank, squares in enumerate(ordered):
                for turn in (1, 2):
                    board = [0] * 32
                    for square in squares:
                        board[square] = 3  # RED_KING
                    state = State(tuple(board), turn)
                    types = sum(2 << (i * 2) for i in range(pieces))
                    self.assertEqual(board_index(state), offset + (rank * 4 ** pieces + types) * 2 + turn - 1)
            offset += len(ordered) * 4 ** pieces * 2
        self.assertEqual(offset, BOARD_COUNT)

    def test_python_exact_oracle_matches_clock_and_capture_boundaries(self):
        rules = Rules(repetition_limit=None)
        solver = ExactSolver(rules, max_states=200_000)
        with CompactTablebase() as tb:
            for position in ("B:BK6,15:RK28", "B:BM18:RM14,1", "B:BK1:RK32", "B:BM5:RM1"):
                for clock in (78, 79, 80):
                    state = parse_position(position, reversible_plies=clock)
                    solver.clear()
                    expected = solver.solve(state)
                    got = tb.probe(state)
                    self.assertEqual((got.outcome, got.distance), (expected.outcome, expected.distance))

    def test_repetition_remains_authoritative_over_artifact(self):
        with CompactTablebase() as tb:
            state = parse_position("B:BK6,15:RK28")
            self.assertEqual(tb.probe(state).outcome, Outcome.WIN)
            engine = Engine(native_tablebase=tb)
            for count in (1, 3, 1):
                if count == 3:
                    with self.assertRaisesRegex(ValueError, "terminal"):
                        engine.search(state, SearchLimits(depth=3), history=Counter({state.position_key: count}))
                    continue
                result = engine.search(state, SearchLimits(depth=3),
                                       history=Counter({state.position_key: count}))
                self.assertEqual(result.bound.exact_outcome, Outcome.WIN)


class TB3ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.service = TB3Service()
        self.addCleanup(self.service.close)

    def test_one_load_shared_across_concurrent_starts(self):
        release = threading.Event()
        entered = threading.Event()
        fake = Mock(sha256="test")
        def load(*_):
            entered.set()
            release.wait(2)
            return fake
        with patch("makhos.tb3_service.CompactTablebase", side_effect=load) as loader:
            first = self.service.start()
            self.assertTrue(entered.wait(1))
            self.assertIs(self.service.start(), first)
            self.assertIsNone(self.service.ready())
            release.set()
            first.join(2)
            self.assertIs(self.service.ready(), fake)
            loader.assert_called_once()

    def test_missing_or_corrupt_artifact_fails_without_live_build(self):
        for exception in (FileNotFoundError("missing"), ValueError("checksum")):
            service = TB3Service()
            with patch("makhos.tb3_service.CompactTablebase", side_effect=exception) as load:
                service.start().join(2)
                self.assertEqual(service.status()["state"], "error")
                self.assertIsNone(service.start())
                self.assertIsNone(service.ready())
                load.assert_called_once()
            service.close()

    def test_timeout_never_publishes_late_result(self):
        entered, release = threading.Event(), threading.Event()
        fake = Mock(sha256="late")
        def load(*_):
            entered.set()
            release.wait(2)
            return fake
        with patch("makhos.tb3_service.CompactTablebase", side_effect=load):
            thread = self.service.start()
            self.assertTrue(entered.wait(1))
            with patch("makhos.tb3_service.time.perf_counter", return_value=self.service._started + 3):
                self.assertEqual(self.service.status()["state"], "timeout")
            release.set()
            thread.join(2)
            self.assertIsNone(self.service.ready())
            fake.close.assert_called_once()

    def test_close_during_load_cannot_attach_to_next_generation(self):
        entered, release = threading.Event(), threading.Event()
        stale = Mock(sha256="stale")
        def load(*_):
            entered.set()
            release.wait(2)
            return stale
        with patch("makhos.tb3_service.CompactTablebase", side_effect=load):
            thread = self.service.start()
            self.assertTrue(entered.wait(1))
            self.service.close()
            release.set()
            thread.join(2)
            self.assertEqual(self.service.status()["state"], "unloaded")
            stale.close.assert_called_once()

    def test_readiness_endpoint_does_not_acquire_search_lock(self):
        handler = DummyHandler({})
        handler.path = "/api/readiness"
        with patch("makhos.server.TB3_SERVICE", self.service), \
                patch("makhos.server.ENGINE_SEARCH_LOCK") as lock:
            handler.do_GET()
            lock.__enter__.assert_not_called()
        self.assertEqual(json.loads(handler.wfile.bytes)["tb3"]["state"], "unloaded")

    def test_unready_endgame_returns_503_without_search_or_wait(self):
        engine = Engine(exact_piece_limit=0)
        # Cover root TB3 and a ranked TB4 position that can reach TB3.
        for position, ranked in (("B:BK6,15:RK28", {}), ("B:BK1,5,6:RK28", {4: Mock()})):
            engine.ranked_tablebases = ranked
            handler = DummyHandler({})
            with patch("makhos.server.TB3_SERVICE", self.service), \
                    patch("makhos.server.start_native_tablebase_warmup"), \
                    patch("makhos.server.get_default_engine", return_value=engine), \
                    patch.object(engine, "search") as search:
                handler.handle_bestmove({"position": position, "time_sec": 0.01})
                search.assert_not_called()
            self.assertEqual(handler.response_status, 503)
            self.assertNotIn("bestmove", json.loads(handler.wfile.bytes))

    def test_forced_move_bypasses_unready_artifact(self):
        engine = Engine(exact_piece_limit=0)
        handler = DummyHandler({})
        with patch("makhos.server.TB3_SERVICE", self.service), \
                patch("makhos.server.get_default_engine", return_value=engine), \
                patch("makhos.server.GUI_NNUE_MODEL_OVERRIDE", None), \
                patch("makhos.server.ensure_native_tablebase_ready", side_effect=AssertionError("must not wait")):
            handler.handle_bestmove({"position": "B:BM18:RM14,1"})
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(json.loads(handler.wfile.bytes)["search_backend"], "forced")

    def test_new_game_keeps_loaded_oracle_without_rebuilding(self):
        from makhos import server
        engine = Engine(exact_piece_limit=0)
        self.service.start().join(2)
        with patch.object(server, "TB3_SERVICE", self.service), \
                patch.object(server, "GLOBAL_ENGINE", engine):
            self.assertTrue(server.ensure_native_tablebase_ready(engine))
            oracle = engine.native_tablebase
            for _ in range(3):
                DummyHandler({}).handle_get_state({})
                self.assertTrue(server.ensure_native_tablebase_ready(engine))
                self.assertIs(engine.native_tablebase, oracle)
                self.assertEqual(oracle.probe(parse_position("B:BK6,15:RK28")).outcome, Outcome.WIN)


if __name__ == "__main__":
    unittest.main()
