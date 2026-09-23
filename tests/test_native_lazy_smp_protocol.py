"""Exercise the production publication and construction paths, not a replica.

ASan checks memory access; it is deliberately not advertised as a race detector.
Run through the verification runner to obtain workload isolation.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLANG = shutil.which("clang") or str(Path("C:/Program Files/LLVM/bin/clang.exe"))


@unittest.skipUnless(os.name == "nt" and Path(CLANG).is_file(),
                     "Windows LLVM is required for the native lifecycle harness")
class NativeLazySmpProtocolTests(unittest.TestCase):
    def run_harness(self, sanitize):
        # Only this temporary directory is owned and removed by the test.
        with tempfile.TemporaryDirectory(prefix="makhos-smp-protocol-") as directory:
            executable = Path(directory) / "protocol.exe"
            command = [CLANG, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-Wno-unused-function", str(ROOT / "tests/native_lazy_smp_protocol.c"),
                       "-o", str(executable)]
            environment = os.environ.copy()
            if sanitize:
                command += ["-fsanitize=address", "-g"]
                resource = subprocess.run([CLANG, "-print-resource-dir"],
                                          capture_output=True, text=True, check=True,
                                          timeout=15).stdout.strip()
                runtime = Path(resource) / "lib/windows"
                self.assertTrue((runtime / "clang_rt.asan_dynamic-x86_64.dll").is_file(),
                                "ASan runtime must be installed for this gate")
                environment["PATH"] = str(runtime) + os.pathsep + environment.get("PATH", "")
                environment["ASAN_OPTIONS"] = "halt_on_error=1"
            compiled = subprocess.run(command, cwd=ROOT, capture_output=True,
                                      text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(executable)], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("torn=0", result.stdout)
            self.assertIn("allocation/event/thread failures and repeated teardown: PASS",
                          result.stdout)

    def test_actual_publication_and_failure_cleanup(self):
        self.run_harness(False)

    def test_actual_publication_and_failure_cleanup_asan(self):
        self.run_harness(True)
