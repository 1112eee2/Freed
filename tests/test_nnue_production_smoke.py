"""Unit tests for tools.verification.nnue_production_smoke and its legacy wrapper."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.verification import nnue_production_smoke as canonical_smoke
from work import nnue_production_smoke as legacy_smoke


class NnueProductionSmokeTests(unittest.TestCase):
    def test_canonical_and_legacy_constants_and_symbols(self):
        self.assertEqual(canonical_smoke.INITIAL, legacy_smoke.INITIAL)
        self.assertEqual(canonical_smoke.MANIFEST, legacy_smoke.MANIFEST)
        self.assertIs(canonical_smoke.post, legacy_smoke.post)
        self.assertIs(canonical_smoke.freeze, legacy_smoke.freeze)
        self.assertIs(canonical_smoke.smoke, legacy_smoke.smoke)
        self.assertIs(canonical_smoke.running_server, legacy_smoke.running_server)

    def test_cli_help_works_from_both_locations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for mod in (canonical_smoke, legacy_smoke):
                result = subprocess.run(
                    [sys.executable, str(Path(mod.__file__).resolve()), "--help"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("{freeze,smoke}", result.stdout)
                self.assertIn("--profile {nnue,hce}", result.stdout)


if __name__ == "__main__":
    unittest.main()
