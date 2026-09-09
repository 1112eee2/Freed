"""Unit tests for the Web GUI Server API endpoints."""

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import hashlib
import json
import socket
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from makhos.server import (
    close_global_engine,
    configure_gui_native_search,
    EngineRequestHandler,
    MakhosHTTPServer,
    production_native_library,
    get_default_engine,
    ensure_native_tablebase_ready,
    start_native_tablebase_warmup,
)
import makhos.server as server_module


class MockWfile:

    def __init__(self):
        self.bytes = b""

    def write(self, b):
        self.bytes += b


class MockRfile:

    def __init__(self, data_bytes):
        self.data_bytes = data_bytes

    def read(self, length):
        return self.data_bytes[:length]


class DummyHandler(EngineRequestHandler):

    def __init__(self, request_body: dict):
        self.rfile = MockRfile(json.dumps(request_body).encode("utf-8"))
        self.wfile = MockWfile()
        self.headers = {"Content-Length": str(len(self.rfile.data_bytes))}
        self.response_status = None
        self.response_headers = {}

    def send_response(self, code, message=None):
        self.response_status = code

    def send_header(self, keyword, value):
        self.response_headers[keyword] = value

    def end_headers(self):
        pass


class ServerApiTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls) -> None:
        close_global_engine()

    def test_production_prefers_accepted_native_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            build.mkdir()
            candidate = build / "makhos_native.dll"
            accepted = build / "makhos_native_accepted.dll"
            candidate.write_bytes(b"candidate")

            self.assertEqual(production_native_library(root), candidate)
            accepted.write_bytes(b"accepted")
            self.assertEqual(production_native_library(root), accepted)

    def test_idle_browser_connection_cannot_block_api_requests(self) -> None:
        server = MakhosHTTPServer(("127.0.0.1", 0), EngineRequestHandler)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        idle = socket.create_connection(server.server_address, timeout=2)
        connection = HTTPConnection(*server.server_address, timeout=2)
        try:
            # Give the server time to accept the browser-style speculative
            # socket and block its worker while waiting for a request line.
            time.sleep(0.05)
            body = json.dumps({"position": "B:BM25,26:RM1,2"})
            connection.request(
                "POST",
                "/api/state",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            data = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(data["turn"], "black")
        finally:
            connection.close()
            idle.close()
            server.shutdown()
            server.server_close()
            serving.join(timeout=2)

    def test_second_server_cannot_share_the_same_port(self) -> None:
        first = MakhosHTTPServer(("127.0.0.1", 0), EngineRequestHandler)
        try:
            with self.assertRaises(OSError):
                MakhosHTTPServer(first.server_address, EngineRequestHandler)
        finally:
            first.server_close()

    def test_handle_get_state(self) -> None:
        handler = DummyHandler({})
        handler.handle_get_state({})
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["turn"], "black")
        self.assertEqual(
            data["position"],
            "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8",
        )
        self.assertEqual(len(data["board"]), 32)
        self.assertGreater(len(data["legal_moves"]), 0)

        round_trip = DummyHandler({})
        round_trip.handle_get_state({"position": data["position"]})
        repeated = json.loads(round_trip.wfile.bytes.decode("utf-8"))
        self.assertEqual(repeated["position"], data["position"])

    def test_handle_legal_moves(self) -> None:
        handler = DummyHandler({})
        pos_str = "B:BM25,26:RM1,2"
        handler.handle_legal_moves({"position": pos_str})
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["turn"], "black")
        self.assertGreater(len(data["legal_moves"]), 0)

    def test_handle_apply_move(self) -> None:
        handler = DummyHandler({})
        pos_str = "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"
        handler.handle_apply_move({"position": pos_str, "move": "28-24"})
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["turn"], "red")
        self.assertEqual(len(data["board"]), 32)

    def test_apply_move_declares_threefold_from_browser_history(self) -> None:
        handler = DummyHandler({})
        current = "R:BM5:BK8:RK1,2"
        repeated_child = "B:BM5:BK8:RK1,6"
        handler.handle_apply_move({
            "position": current,
            "move": "2-6",
            "clock": 19,
            "history": [
                repeated_child,
                current,
                repeated_child,
                current,
            ],
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertTrue(data["terminal"])
        self.assertEqual(data["reason"], "repetition")

    def test_apply_move_rejects_move_after_threefold(self) -> None:
        handler = DummyHandler({})
        current = "B:BM5:BK8:RK1,6"
        handler.handle_apply_move({
            "position": current,
            "move": "8-4",
            "clock": 20,
            "history": [current, current, current],
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 409)
        self.assertTrue(data["terminal"])
        self.assertEqual(data["reason"], "repetition")

    def test_external_profile_does_not_adjudicate_threefold(self) -> None:
        handler = DummyHandler({})
        current = "B:BM5:BK8:RK1,6"
        handler.handle_apply_move({
            "position": current,
            "move": "8-4",
            "clock": 20,
            "history": [current, current, current],
            "rules_profile": "external-no-repetition",
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertFalse(data["terminal"])
        self.assertEqual(data["rules_profile"], "external-no-repetition")

    def test_rejects_unknown_rules_profile(self) -> None:
        handler = DummyHandler({})
        handler.handle_get_state({"rules_profile": "unknown"})
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 400)
        self.assertIn("rules_profile", data["error"])

    def test_position_history_must_end_at_current_position(self) -> None:
        handler = DummyHandler({})
        handler.handle_apply_move({
            "position": "B:BM25,26:RM1,2",
            "move": "25-21",
            "history": ["R:BM25,26:RM1,2"],
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 400)
        self.assertIn("history must end", data["error"])

    def test_handle_bestmove(self) -> None:
        handler = DummyHandler({})
        pos_str = "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"
        handler.handle_bestmove({
            "position": pos_str,
            "time_sec": 0.1,
            "depth": 2,
            "threads": 1,
            "hash_mb": 16,
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertIn("bestmove", data)
        self.assertIn("score", data)
        self.assertIn("pv", data)
        self.assertGreater(data["elapsed_ms"], 50)
        self.assertGreaterEqual(data["request_elapsed_ms"] + 1, data["elapsed_ms"])
        self.assertGreaterEqual(data["pre_search_setup_ms"], 0)
        self.assertEqual(data["runtime_isolation"], "interactive-exclusive-v1")
        self.assertEqual(data["threads"], 1)
        self.assertEqual(data["hash_mb"], 16)
        self.assertEqual(data["hash_allocated_mb"], 10.0)
        self.assertEqual(data["provenance_version"], "search-v1")
        self.assertEqual(data["search_backend"], "native-single")
        self.assertEqual(data["requested_time_ms"], 100)
        self.assertEqual(data["depth_limit"], 64)
        self.assertEqual(data["mode"], "win")
        native_library = Path(data["native_library"])
        self.assertEqual(native_library.name, "makhos_native_accepted.dll")
        self.assertEqual(
            data["native_library_sha256"],
            hashlib.sha256(native_library.read_bytes()).hexdigest(),
        )
        self.assertGreaterEqual(data["native_search_abi"], 5)
        self.assertIsNone(data["native_error"])

    def test_handle_bestmove_reports_parallel_backend(self) -> None:
        handler = DummyHandler({})
        pos_str = "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"
        handler.handle_bestmove({
            "position": pos_str,
            "time_sec": 0.02,
            "depth": 2,
            "threads": 2,
            "hash_mb": 16,
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(data["search_backend"], "native-root-split")
        self.assertEqual(data["threads"], 2)
        self.assertEqual(data["provenance_version"], "search-v1")
        self.assertIsNone(data["native_error"])

    def test_opt_in_nnue_gui_reports_exact_model_provenance(self) -> None:
        candidate = (
            Path(__file__).resolve().parents[1]
            / "build"
            / "nnue_search_v1_r5"
            / "makhos_native_nnue_candidate_v1.dll"
        )
        model = (
            Path(__file__).resolve().parents[1]
            / "build"
            / "nnue_quantized_v1"
            / "model_a.mknnue"
        )
        if not candidate.is_file() or not model.is_file():
            self.skipTest("reproducible NNUE candidate artifacts are absent")
        try:
            configure_gui_native_search(candidate, model)
            handler = DummyHandler({})
            handler.handle_bestmove({
                "position": "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8",
                "time_sec": 0.02,
                "threads": 2,
                "hash_mb": 16,
            })
            data = json.loads(handler.wfile.bytes.decode("utf-8"))
            self.assertEqual(handler.response_status, 200)
            self.assertTrue(data["nnue_enabled"])
            self.assertEqual(data["nnue_feature_abi"], "thai-makhos-shared-137-v1")
            self.assertEqual(
                data["nnue_model_sha256"],
                "07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C",
            )
            self.assertEqual(Path(data["native_library"]), candidate.resolve())
        finally:
            configure_gui_native_search()

    def test_handle_bestmove_rejects_invalid_engine_settings(self) -> None:
        handler = DummyHandler({})
        handler.handle_bestmove({
            "position": "B:BM25,26:RM1,2",
            "threads": 0,
        })
        data = json.loads(handler.wfile.bytes.decode("utf-8"))

        self.assertEqual(handler.response_status, 400)
        self.assertIn("threads", data["error"])

    def test_handle_bestmove_rejects_threads_above_supported_max(self) -> None:
        handler = DummyHandler({})
        with patch(
            "makhos.server.get_default_engine",
            side_effect=AssertionError("out-of-range Threads reached engine factory"),
        ) as get_engine:
            handler.handle_bestmove({
                "position": "B:BM25,26:RM1,2",
                "threads": 13,
            })

        data = json.loads(handler.wfile.bytes.decode("utf-8"))
        self.assertEqual(handler.response_status, 400)
        self.assertIn("1..12", data["error"])
        get_engine.assert_not_called()

    def test_engine_reconfiguration_reuses_tablebases_and_engine(self) -> None:
        close_global_engine()
        first = get_default_engine(threads=1, hash_mb=16)
        ranked = first.ranked_tablebases
        with patch("makhos.server._create_native_search") as create_search:
            replacement = Mock()
            replacement.abi_version = 5
            replacement.allocated_hash_mb = 32
            create_search.return_value = replacement
            second = get_default_engine(threads=2, hash_mb=32)

        self.assertIs(second, first)
        self.assertIs(second.ranked_tablebases, ranked)
        self.assertIs(second.native_search, replacement)

    def test_background_native_tablebase_attaches_and_clears_distance_caches(self) -> None:
        close_global_engine()
        engine = get_default_engine(threads=1, hash_mb=16)
        engine._distance._dtm_cache[("old",)] = 1
        engine._distance._dtr_cache[("old",)] = 1
        fake_tablebase = Mock()
        fake_tablebase.max_pieces = 3
        with patch("makhos.tb3_service.CompactTablebase", return_value=fake_tablebase):
            thread = start_native_tablebase_warmup()
            self.assertIsNotNone(thread)
            thread.join(timeout=2)
            self.assertTrue(ensure_native_tablebase_ready(engine))

        self.assertFalse(thread.is_alive())
        self.assertIs(engine.native_tablebase, fake_tablebase)
        self.assertIs(engine._distance.native, fake_tablebase)
        self.assertEqual(engine._distance._dtm_cache, {})
        self.assertEqual(engine._distance._dtr_cache, {})

    def test_three_piece_tablebase_attaches_loaded_bytes_and_reuses_one_oracle(self) -> None:
        close_global_engine()
        engine = get_default_engine(threads=1, hash_mb=16)
        fake_tablebase = Mock()
        fake_tablebase.max_pieces = 3
        with patch("makhos.tb3_service.CompactTablebase", return_value=fake_tablebase) as load:
            start_native_tablebase_warmup().join(timeout=2)
            self.assertTrue(ensure_native_tablebase_ready(engine))
            self.assertTrue(ensure_native_tablebase_ready(engine))

        load.assert_called_once()
        self.assertIs(engine.native_tablebase, fake_tablebase)


if __name__ == "__main__":
    unittest.main()
