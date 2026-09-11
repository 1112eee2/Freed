"""Unit and regression tests for tools/build/build_orchestrator.ps1."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "tools" / "build" / "build_orchestrator.ps1"

ALL_VARIANTS = (
    "native",
    "nnue_scalar",
    "nnue_incremental",
    "nnue_avx2",
    "nnue_avx2_update",
    "nnue_search_candidate",
    "endgame_c1",
    "endgame_c2",
    "endgame_c3",
    "endgame_c4",
)


class BuildOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ORCHESTRATOR.exists(), f"Orchestrator missing: {ORCHESTRATOR}")

    def run_pwsh(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ORCHESTRATOR),
            *args,
        ]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )

    def test_verify_only_all_supported_variants(self):
        for variant in ALL_VARIANTS:
            with self.subTest(variant=variant):
                proc = self.run_pwsh("-Variant", variant, "-VerifyOnly")
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"Variant {variant} failed verification:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
                )
                self.assertIn("verified", proc.stdout.lower())

    def test_unknown_variant_rejected(self):
        proc = self.run_pwsh("-Variant", "non_existent_variant")
        self.assertNotEqual(proc.returncode, 0)

    def test_output_directory_escaping_build_root_rejected(self):
        proc = self.run_pwsh(
            "-Variant",
            "nnue_scalar",
            "-OutputDirectory",
            str(ROOT / "makhos"),
            "-VerifyOnly",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(
            "must stay inside the project build directory" in proc.stderr
            or "must stay inside the project build directory" in proc.stdout
        )


if __name__ == "__main__":
    unittest.main()
