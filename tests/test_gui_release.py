"""Release failures must be visible and must not silently activate HCE."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from makhos.gui_release import load_release
from makhos import server
from tests.test_server import DummyHandler


class GuiReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pointer = self.root / "pointer.json"
        self.manifest = self.root / "manifest.json"
        self.dll = self.root / "nnue.dll"
        self.model = self.root / "model.mknnue"
        self.dll.write_bytes(b"frozen DLL")
        self.model.write_bytes(b"frozen model")
        (self.root / "RULESET.json").write_bytes(b"frozen rules")
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest().upper()
        profile = {"native_library": "nnue.dll", "native_library_sha256": digest(self.dll),
                   "nnue_model": "model.mknnue", "nnue_model_sha256": digest(self.model),
                   "nnue_enabled": True, "native_search_abi": 5,
                   "nnue_feature_abi": "thai-makhos-shared-137-v1"}
        self.bundle = {"format": "thai-makhos-gui-release-v1", "release_id": "test",
                       "profiles": {"nnue": profile, "hce": {**profile, "nnue_enabled": False,
                                    "nnue_model": None, "nnue_model_sha256": None}},
                       "rules_sha256": digest(self.root / "RULESET.json"),
                       "settings": {"threads": 12, "hash_mb_total": 512}, "tablebases": []}
        self.publish()

    def publish(self):
        self.manifest.write_text(json.dumps(self.bundle), encoding="utf-8")
        self.pointer.write_text(json.dumps({"format": "thai-makhos-gui-release-pointer-v1",
            "manifest": "manifest.json", "profile": "nnue",
            "manifest_sha256": hashlib.sha256(self.manifest.read_bytes()).hexdigest().upper()}), encoding="utf-8")

    def load(self, **kwargs):
        return load_release(self.pointer, root=self.root, **kwargs)

    def test_release_binds_exact_files_and_allows_explicit_hce_rollback(self):
        self.assertEqual(self.load()["nnue_model"], self.model)
        rollback = self.load(profile="hce")
        self.assertFalse(rollback["nnue_enabled"])
        self.assertIsNone(rollback["nnue_model"])

    def test_missing_model_fails(self):
        self.model.unlink()
        with self.assertRaises(FileNotFoundError): self.load()

    def test_corrupt_model_fails_instead_of_selecting_hce(self):
        self.model.write_bytes(b"damaged model")
        with self.assertRaisesRegex(ValueError, "nnue_model checksum"): self.load()

    def test_dll_drift_fails(self):
        self.dll.write_bytes(b"new candidate")
        with self.assertRaisesRegex(ValueError, "native_library checksum"): self.load()

    def test_manifest_drift_fails(self):
        self.manifest.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "manifest checksum"): self.load()

    def test_mandatory_tablebase_missing_fails(self):
        self.bundle["tablebases"] = [{"path": "missing.bin", "bytes": 100}]
        self.publish()
        with self.assertRaises(FileNotFoundError): self.load()

    def test_artifact_cannot_escape_project(self):
        self.bundle["profiles"]["nnue"]["native_library"] = "../outside.dll"
        self.publish()
        with self.assertRaisesRegex(ValueError, "escapes"): self.load()

    def test_null_nnue_model_fails(self):
        self.bundle["profiles"]["nnue"]["nnue_model"] = None
        self.publish()
        with self.assertRaisesRegex(ValueError, "missing nnue_model"): self.load()

    def test_settings_failure_returns_http_error(self):
        handler = DummyHandler({"position": "B:BM25,26:RM1,2"})
        handler.path = "/api/bestmove"
        with patch.object(server, "get_default_engine", side_effect=RuntimeError("NNUE model missing")):
            handler.do_POST()
        self.assertEqual(handler.response_status, 503)
        result = json.loads(handler.wfile.bytes)
        self.assertTrue(result["engine_unavailable"])
        self.assertNotIn("bestmove", result)

    def test_forced_move_never_initializes_unused_tb3(self):
        server.close_global_engine()
        self.addCleanup(server.close_global_engine)
        handler = DummyHandler({})
        with patch.object(server, "ensure_native_tablebase_ready", side_effect=AssertionError("unnecessary TB3 initialization")):
            handler.handle_bestmove({"position": "B:BM18:RM14,1", "threads": 1, "hash_mb": 16})
        result = json.loads(handler.wfile.bytes)
        self.assertEqual(handler.response_status, 200)
        self.assertEqual(result["search_backend"], "forced")
        self.assertEqual(result["nodes"], 1)


if __name__ == "__main__": unittest.main()
