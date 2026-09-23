"""Developer checks: portable reference by default, complete Local suite on request.

Reuse the production-data guard and workload lease, without claiming the
post-acquisition promotion attestation produced by full_suite_attestation.py.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification import full_suite_attestation as gate

# Explicit coverage for a checkout without machine-local DLL/model/TB artifacts.
REFERENCE_TEST_FILES = (
    "test_rules.py", "test_properties.py", "test_audit_rules.py", "test_eval.py",
    "test_exact.py", "test_distance.py", "test_search.py", "test_policy_value.py",
    "test_game_analysis.py", "test_game_records.py", "test_cli_modularization.py",
    "test_web_gui.py", "test_nnue_features.py", "test_nnue_full_suite_attestation.py",
    "test_sprt.py", "test_development_checks.py",
)
NODE_TEST_FILES = (
    "tests/tooling/test_gui_lifecycle.cjs",
    "tests/tooling/test_gui_game_controls.cjs",
)
EXPECTED_RULE_HASHES = {
    "RULESET.json": "77528addc0e08b17217346c511c7c4084bad4af48789955c3ec85ef76a64871f",
    "makhos/core.py": "03152e513bd360e6c2c97ecdf08dc58a290dca0ae6e28889ae70585a381292ab",
}
STOPPED_EXPERIMENT_DIRECTORIES = ("nnue_sprt_6t_vs_12t", "nnue_sprt_6t_vs_12t_c4_v1")


def stopped_experiment_roots() -> tuple[Path, ...]:
    return tuple((ROOT / "build" / name).resolve() for name in STOPPED_EXPERIMENT_DIRECTORIES)


def verify_invariants(root: Path = ROOT) -> dict[str, str]:
    hashes = {}
    for name, expected in EXPECTED_RULE_HASHES.items():
        raw = (root / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        # Git may check out CRLF or LF; never rewrite the reference files.
        if hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise gate.FullSuiteGateError(f"immutable reference changed: {name}")
    accepted = root / "build/makhos_native_accepted.dll"
    if accepted.is_file():
        hashes["build/makhos_native_accepted.dll"] = gate.sha256(accepted)
        if hashes["build/makhos_native_accepted.dll"] != gate.contract_gate.EXPECTED_ACCEPTED_SHA256:
            raise gate.FullSuiteGateError("accepted DLL identity changed")
    return hashes


def discover(suite_name: str) -> unittest.TestSuite:
    if suite_name == "full":
        return gate.discover_complete_suite()
    suite = unittest.TestSuite()
    for filename in REFERENCE_TEST_FILES:
        if not (ROOT / "tests" / filename).is_file():
            raise gate.FullSuiteGateError(f"missing reference test file: {filename}")
        selected = unittest.TestLoader().discover(str(ROOT / "tests"), pattern=filename)
        if not selected.countTestCases():
            raise gate.FullSuiteGateError(f"no tests discovered in {filename}")
        suite.addTests(selected)
    return suite


def python_passed(result: unittest.TestResult, discovered: int) -> bool:
    return (discovered > 0 and result.testsRun == discovered
            and result.wasSuccessful() and not result.skipped
            and not result.expectedFailures and not result.unexpectedSuccesses)


def tap_summary(output: str) -> dict[str, int]:
    counts = {}
    for name in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        matches = re.findall(rf"^# {name} (\d+)\s*$", output, re.MULTILINE)
        if len(matches) != 1:
            raise gate.FullSuiteGateError(f"missing/ambiguous Node TAP count: {name}")
        counts[name] = int(matches[0])
    return counts


def new_output_directory(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(ROOT / "build") or path == ROOT / "build":
        raise gate.FullSuiteGateError("test output must be a new directory inside build/")
    protected = (*stopped_experiment_roots(), gate.DEFAULT_WORK_DIR.resolve())
    if any(path.is_relative_to(root) for root in protected):
        raise gate.FullSuiteGateError("test output must stay outside protected run directories")
    path.mkdir(parents=True, exist_ok=False)
    return path


def below_normal() -> None:
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError(ctypes.get_last_error())


def run(suite_name: str, output: Path) -> int:
    output = new_output_directory(output)
    report = {"format": "thai-makhos-development-checks-v1", "suite": suite_name,
              "promotion_attestation": False, "status": "INCOMPLETE",
              "python_version": sys.version, "started_utc": datetime.now(timezone.utc).isoformat()}
    guard = gate.ProductionOpenGuard(gate.DEFAULT_WORK_DIR)
    guard.forbidden_roots.update(stopped_experiment_roots())
    sys.addaudithook(guard.hook)
    try:
        node = shutil.which("node")
        if node is None:
            raise gate.FullSuiteGateError("Node.js is required for the GUI checks")
        below_normal()
        with gate.ExclusiveSuiteLease(ROOT) as lease:
            before = verify_invariants()
            paths = gate.source_inventory_paths()
            source_before = gate.inventory_sha256(paths)
            suite = discover(suite_name)
            count = suite.countTestCases()
            if not count:
                raise gate.FullSuiteGateError("no Python tests discovered")
            print(f"{suite_name}: {count} Python tests; 2 Node GUI suites", flush=True)
            result, log, seconds = gate.execute_suite(suite, checkpoint=lease.checkpoint)
            (output / "python.txt").write_text(log, encoding="utf-8")
            print(log, end="", flush=True)
            report["python"] = {"discovered": count, "run": result.testsRun, "seconds": seconds,
                                "failures": len(result.failures), "errors": len(result.errors),
                                "skips": len(result.skipped), "expected_failures": len(result.expectedFailures),
                                "unexpected_successes": len(result.unexpectedSuccesses)}
            lease.checkpoint("before Node GUI tests")
            node_result = subprocess.run([node, "--test", "--test-reporter=tap", *NODE_TEST_FILES],
                                         cwd=ROOT, capture_output=True, text=True, timeout=120)
            (output / "node.txt").write_text(node_result.stdout + node_result.stderr, encoding="utf-8")
            counts = tap_summary(node_result.stdout)
            report["node"] = {"exit_code": node_result.returncode, **counts}
            lease.checkpoint("after Node GUI tests")
            after = verify_invariants()
            paths_after = gate.source_inventory_paths()
            source_after = gate.inventory_sha256(paths_after)
            if before != after or paths != paths_after or source_before != source_after:
                raise gate.FullSuiteGateError("source or invariant identity changed during tests")
            report.update(invariant_sha256=after, source_inventory_sha256=source_after,
                          source_files=len(paths_after), protected_read_attempts=len(guard.triggered))
            passed = (python_passed(result, count) and node_result.returncode == 0
                      and counts["tests"] > 0 and counts["pass"] == counts["tests"]
                      and all(counts[k] == 0 for k in ("fail", "cancelled", "skipped", "todo"))
                      and not guard.triggered)
            report["status"] = "PASS" if passed else "FAIL"
    except Exception as error:
        report.update(status="FAIL", error=str(error), protected_read_attempts=len(guard.triggered))
    finally:
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: {output / 'result.json'}", flush=True)
    if report.get("error"):
        print(report["error"], file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("reference", "full"), default="reference")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or ROOT / "build/development_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return run(args.suite, output)


if __name__ == "__main__":
    raise SystemExit(main())
