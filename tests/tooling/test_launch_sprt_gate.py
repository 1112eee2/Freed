import hashlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "arena"))
import launch_sprt_gate as gate  # noqa: E402


class LaunchSprtGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cwd = Path(self._tmp.name)
        for name in ("a.dll", "b.dll", "m.mknnue", "tb.bin", "eg.dll"):
            (self.cwd / name).write_bytes(name.encode())
        self.args = [
            "--dev-library", "a.dll", "--master-library", "b.dll",
            "--dev-nnue-model", "m.mknnue", "--master-nnue-model", "m.mknnue",
            "--ranked-tablebase", "tb.bin", "--native-endgame-library", "eg.dll",
        ]

    def test_complete_arguments_pass(self) -> None:
        sha = hashlib.sha256(b"a.dll").hexdigest()
        self.assertEqual(gate.preflight(self.args, self.cwd, [f"a.dll={sha}"]), [])

    def test_hash_mismatch_and_missing_file_fail(self) -> None:
        wrong = "0" * 64
        self.assertTrue(gate.preflight(self.args, self.cwd, [f"a.dll={wrong}"]))
        self.assertTrue(gate.preflight(self.args, self.cwd, [f"absent.dll={wrong}"]))
        self.assertTrue(gate.preflight(self.args, self.cwd, ["a.dll"]))

    def test_tablebases_and_endgame_library_must_be_explicit(self) -> None:
        no_tb = [a for a in self.args if a not in ("--ranked-tablebase", "tb.bin")]
        no_eg = [a for a in self.args if a not in ("--native-endgame-library", "eg.dll")]
        self.assertTrue(any("tablebases" in p for p in gate.preflight(no_tb, self.cwd, [])))
        self.assertTrue(any("endgame" in p for p in gate.preflight(no_eg, self.cwd, [])))
        self.assertEqual(gate.preflight(no_tb + ["--no-tablebase"], self.cwd, []), [])

    def test_missing_named_file_fails(self) -> None:
        (self.cwd / "tb.bin").unlink()
        self.assertTrue(any("tb.bin" in p for p in gate.preflight(self.args, self.cwd, [])))

    def test_equals_form_is_understood(self) -> None:
        args = ["--ranked-tablebase=tb.bin", "--native-endgame-library=eg.dll"]
        self.assertEqual(gate.preflight(args, self.cwd, []), [])

    def test_owner_identity_needs_pid_and_creation_time(self) -> None:
        pid = os.getpid()
        created = gate.process_creation_utc(pid)
        self.assertIsNotNone(created)
        launch = self.cwd / "launch.txt"
        launch.write_text(f"pid={pid}\ncreation={created.isoformat()}\n", encoding="utf-8")
        self.assertTrue(gate.owner_is_alive(launch))
        stale = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        launch.write_text(f"pid={pid}\ncreation={stale}\n", encoding="utf-8")
        self.assertFalse(gate.owner_is_alive(launch))
        self.assertFalse(gate.owner_is_alive(self.cwd / "absent.txt"))

    def test_parse_launch_handles_bom_and_equals_in_values(self) -> None:
        record = gate.parse_launch("﻿pid=7\ncommand=a --x=1\n")
        self.assertEqual(record, {"pid": "7", "command": "a --x=1"})

    def test_dry_run_fails_closed_without_starting_anything(self) -> None:
        code = gate.main(
            ["--run-dir", "run", "--cwd", str(self.cwd), "--dry-run", "--", "--seed", "1"]
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.cwd / "run").exists())
        code = gate.main(
            ["--run-dir", "run", "--cwd", str(self.cwd), "--dry-run", "--", *self.args]
        )
        self.assertEqual(code, 0)
        self.assertFalse((self.cwd / "run").exists())


if __name__ == "__main__":
    unittest.main()
