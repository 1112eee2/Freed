"""Run the complete discovered suite and emit a bound PASS attestation.

The real runner is intentionally unavailable while the full NNUE acquisition
is active.  It requires completed acquisition health, a validated final-data
audit, no pipeline process, no interactive GUI session, and an exclusive lock
over every workload slot.  It writes no artifact unless every discovered test
passes and the source/test inventories remain unchanged.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.workload_isolation import (  # noqa: E402
    LOCK_SLOTS,
    _RangeLock,
    interactive_session_active,
)
from scratch import nnue_trainer_contract_gate as contract_gate  # noqa: E402
from scratch.nnue_quiet_leaf_acquire import sha256, write_locked_json  # noqa: E402
from scratch.nnue_scaling_final_audit import DEFAULT_WORK_DIR  # noqa: E402
from scratch.nnue_scaling_full_run import live_full_run_processes  # noqa: E402
from scratch.nnue_scaling_health_audit import build_health_snapshot  # noqa: E402


FORMAT = contract_gate.SUITE_FORMAT
KIND = "post-acquisition-complete-suite"
# Maintained code/configuration only: frozen runs, user games and local build
# artifacts keep their separate identities and are never swept into this scan.
SOURCE_DIRECTORIES = (
    ".github", "config", "makhos", "native", "schemas", "scratch", "tests", "tools", "web",
)
SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".css",
    ".h",
    ".hpp",
    ".html",
    ".js",
    ".json",
    ".mjs",
    ".ps1",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}
TOP_LEVEL_SOURCES = (
    "RULESET.json",
    "build_native.ps1",
    "build_nnue_avx2.ps1",
    "build_nnue_avx2_update.ps1",
    "build_nnue_incremental.ps1",
    "build_nnue_search_candidate.ps1",
    "build_nnue_scalar.ps1",
    "follow_dfpn_saturated_line_on_d.ps1",
    "pyproject.toml",
    "run_dfpn_on_d.ps1",
    "run_gui.ps1",
    "server.py",
)


class FullSuiteGateError(RuntimeError):
    """Raised when the full suite cannot produce trustworthy evidence."""


class InteractivePriorityChanged(FullSuiteGateError):
    """Raised when a GUI session takes priority during the suite."""


def source_inventory_paths(root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    paths = []
    for name in SOURCE_DIRECTORIES:
        directory = root / name
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix.casefold() in SOURCE_SUFFIXES
            ):
                paths.append(path.resolve())
    for name in TOP_LEVEL_SOURCES:
        path = root / name
        if path.exists():
            paths.append(path.resolve())
    return sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())


def test_inventory_paths(root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    return sorted(
        (
            path.resolve()
            for path in (root / "tests").rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def inventory_sha256(paths: Iterable[Path], *, root: Path = ROOT) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    rows = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as error:
            raise FullSuiteGateError(f"inventory path escapes root: {resolved}") from error
        rows.append((relative, sha256(resolved)))
    for relative, file_sha in sorted(rows):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


class ExclusiveSuiteLease:
    """Own every workload byte without asserting GUI priority itself."""

    def __init__(
        self,
        project_root: Path,
        *,
        interactive_probe: Callable[[], bool] = interactive_session_active,
        lock_factory: Callable[[Path], object] = _RangeLock,
    ) -> None:
        self._interactive_probe = interactive_probe
        self._lock = lock_factory(
            project_root.resolve() / "build" / "runtime" / "workload.lock"
        )

    def __enter__(self) -> "ExclusiveSuiteLease":
        if self._interactive_probe():
            self._lock.close()
            raise InteractivePriorityChanged(
                "interactive GUI session is active before full-suite lock"
            )
        if not self._lock.try_lock(0, LOCK_SLOTS):
            self._lock.close()
            raise FullSuiteGateError(
                "full suite requires every batch workload slot to be idle"
            )
        if self._interactive_probe():
            self._lock.close()
            raise InteractivePriorityChanged(
                "interactive GUI session started during full-suite lock"
            )
        return self

    def checkpoint(self, stage: str) -> None:
        if self._interactive_probe():
            raise InteractivePriorityChanged(
                f"interactive GUI session took priority {stage}"
            )

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._lock.close()


class GuardedTextResult(unittest.TextTestResult):
    def __init__(self, *args, checkpoint: Callable[[str], None], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._checkpoint = checkpoint

    def startTest(self, test) -> None:  # noqa: N802 - unittest API
        self._checkpoint(f"before test {test.id()}")
        super().startTest(test)

    def stopTest(self, test) -> None:  # noqa: N802 - unittest API
        super().stopTest(test)
        self._checkpoint(f"after test {test.id()}")


def execute_suite(
    suite: unittest.TestSuite,
    *,
    checkpoint: Callable[[str], None],
    verbosity: int = 2,
) -> tuple[unittest.TextTestResult, str, float]:
    stream = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=stream,
        verbosity=verbosity,
        resultclass=lambda *args, **kwargs: GuardedTextResult(
            *args,
            checkpoint=checkpoint,
            **kwargs,
        ),
    )
    started = time.perf_counter()
    result = runner.run(suite)
    duration = time.perf_counter() - started
    return result, stream.getvalue(), duration


class ProductionOpenGuard:
    """Audit-hook guard for actual scaling artifacts during the test process."""

    def __init__(self, work_dir: Path) -> None:
        work_dir = work_dir.resolve()
        self.forbidden_exact = {
            (work_dir / "sealed_test_selection_manifest.json").resolve(),
            (work_dir / "full_run_supervisor_status.json").resolve(),
        }
        self.forbidden_roots = {
            (work_dir / "analyses").resolve(),
            (work_dir / "test_analyses").resolve(),
            (work_dir / "sealed_test_analyses").resolve(),
        }
        self.triggered: list[Path] = []

    def hook(self, event: str, args: tuple) -> None:
        if event != "open" or not args:
            return
        raw_path = args[0]
        if isinstance(raw_path, int):
            return
        try:
            path = Path(os.fsdecode(raw_path)).resolve()
        except (OSError, TypeError, ValueError):
            return
        forbidden = path in self.forbidden_exact or any(
            path == root or path.is_relative_to(root)
            for root in self.forbidden_roots
        )
        if forbidden:
            self.triggered.append(path)
            raise FullSuiteGateError(
                f"full suite attempted to open protected production data: {path}"
            )


def validate_run_preconditions(
    *,
    work_dir: Path,
    final_audit_path: Path,
    output_path: Path,
) -> tuple[contract_gate.JsonSnapshot, dict]:
    work_dir = work_dir.resolve()
    output_path = output_path.resolve()
    if output_path.is_relative_to(work_dir):
        raise FullSuiteGateError(
            "full-suite attestation must stay outside the locked run directory"
        )
    if any(
        output_path.is_relative_to(ROOT / directory)
        for directory in SOURCE_DIRECTORIES
    ):
        raise FullSuiteGateError(
            "full-suite attestation must stay outside source/test inventory trees"
        )
    if output_path.exists():
        raise FullSuiteGateError("full-suite attestation output already exists")
    processes = live_full_run_processes(work_dir)
    if processes:
        raise FullSuiteGateError(
            f"pipeline processes are still active: {[row['pid'] for row in processes]}"
        )
    if interactive_session_active():
        raise InteractivePriorityChanged("interactive GUI session is active")
    health = build_health_snapshot(work_dir, processes=[])
    require_complete_health(health)
    audit = contract_gate.load_json_snapshot(final_audit_path)
    contract_gate._validate_final_audit(audit)
    return audit, health


def require_complete_health(health: dict) -> None:
    inventory = health.get("inventory", {})
    if (
        inventory.get("state") != "COMPLETE_PENDING_FINAL_GATES"
        or inventory.get("errors")
        or inventory.get("development_analyses")
        != inventory.get("expected_development_analyses")
        or inventory.get("stderr_bytes") != 0
        or inventory.get("temporary_files") != 0
    ):
        raise FullSuiteGateError("acquisition is not complete and clean")


def build_attestation(
    *,
    final_audit_sha256: str,
    started_at_utc: str,
    completed_at_utc: str,
    duration_seconds: float,
    discovered_tests: int,
    result: unittest.TextTestResult,
    result_output: str,
    test_inventory_sha256: str,
    source_inventory_sha256: str,
    test_files: int,
    source_files: int,
    command: list[str],
    runner_path: Path | None = None,
) -> dict:
    if (
        discovered_tests <= 0
        or not command
        or not all(isinstance(item, str) and item for item in command)
        or not result.wasSuccessful()
        or result.testsRun != discovered_tests
        or result.failures
        or result.errors
        or result.unexpectedSuccesses
    ):
        raise FullSuiteGateError("complete discovered suite did not PASS")
    effective_runner = (
        runner_path.resolve()
        if runner_path is not None
        else Path(__file__).resolve()
    )
    return {
        "format": FORMAT,
        "kind": KIND,
        "verdict": "PASS",
        "workers_idle": True,
        "interactive_session_inactive_before_and_after": True,
        "health_state_before_and_after": [
            "COMPLETE_PENDING_FINAL_GATES",
            "COMPLETE_PENDING_FINAL_GATES",
        ],
        "exit_code": 0,
        "discovered_tests": discovered_tests,
        "tests_run": int(result.testsRun),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "skipped": len(result.skipped),
        "duration_seconds": float(duration_seconds),
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "command": command,
        "python_version": platform.python_version(),
        "test_files": test_files,
        "source_files": source_files,
        "test_inventory_sha256": test_inventory_sha256,
        "source_inventory_sha256": source_inventory_sha256,
        "runner_sha256": sha256(effective_runner),
        "result_output_sha256": hashlib.sha256(
            result_output.encode("utf-8")
        ).hexdigest().upper(),
        "accepted_library_sha256": contract_gate.EXPECTED_ACCEPTED_SHA256,
        "final_data_audit_sha256": final_audit_sha256,
        "analysis_payloads_read": 0,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "production_open_guard_triggered": False,
    }


def discover_complete_suite() -> unittest.TestSuite:
    """Discover the repository suite without requiring tests/ to be a package."""

    tests_dir = ROOT / "tests"
    return unittest.TestLoader().discover(
        start_dir=str(tests_dir),
        pattern="test*.py",
        top_level_dir=str(tests_dir),
    )


def run_complete_suite(
    *,
    work_dir: Path,
    final_audit_path: Path,
    output_path: Path,
    runner_path: Path | None = None,
) -> dict:
    work_dir = work_dir.resolve()
    audit, _health_before = validate_run_preconditions(
        work_dir=work_dir,
        final_audit_path=final_audit_path,
        output_path=output_path,
    )
    accepted_before = sha256(contract_gate.ACCEPTED_LIBRARY)
    if accepted_before != contract_gate.EXPECTED_ACCEPTED_SHA256:
        raise FullSuiteGateError("accepted DLL changed before full suite")
    test_paths_before = test_inventory_paths(ROOT)
    source_paths_before = source_inventory_paths(ROOT)
    test_hash_before = inventory_sha256(test_paths_before, root=ROOT)
    source_hash_before = inventory_sha256(source_paths_before, root=ROOT)
    open_guard = ProductionOpenGuard(work_dir)
    sys.addaudithook(open_guard.hook)
    suite = discover_complete_suite()
    discovered_tests = suite.countTestCases()
    if discovered_tests <= 0:
        raise FullSuiteGateError("unittest discovery found no tests")
    started_at = datetime.now(timezone.utc).isoformat()
    with ExclusiveSuiteLease(ROOT) as lease:
        lease.checkpoint("before full suite")
        result, result_output, duration = execute_suite(
            suite,
            checkpoint=lease.checkpoint,
        )
        lease.checkpoint("after full suite")
        completed_at = datetime.now(timezone.utc).isoformat()

        if open_guard.triggered:
            raise FullSuiteGateError("production open guard was triggered")
        if live_full_run_processes(work_dir):
            raise FullSuiteGateError("pipeline process appeared during full suite")
        lease.checkpoint("before post-suite health verification")
        health_after = build_health_snapshot(work_dir, processes=[])
        require_complete_health(health_after)
        lease.checkpoint("after post-suite health verification")
        if sha256(contract_gate.ACCEPTED_LIBRARY) != accepted_before:
            raise FullSuiteGateError("accepted DLL changed during full suite")
        audit_after = contract_gate.load_json_snapshot(final_audit_path)
        if audit_after.encoded != audit.encoded:
            raise FullSuiteGateError("final audit changed during full suite")
        test_paths_after = test_inventory_paths(ROOT)
        source_paths_after = source_inventory_paths(ROOT)
        test_hash_after = inventory_sha256(test_paths_after, root=ROOT)
        source_hash_after = inventory_sha256(source_paths_after, root=ROOT)
        if (
            test_paths_after != test_paths_before
            or source_paths_after != source_paths_before
            or test_hash_after != test_hash_before
            or source_hash_after != source_hash_before
        ):
            raise FullSuiteGateError("source/test inventory changed during full suite")
        if live_full_run_processes(work_dir):
            raise FullSuiteGateError("pipeline process appeared during post-suite checks")
        lease.checkpoint("before full-suite attestation write")

        effective_runner = (
            runner_path.resolve()
            if runner_path is not None
            else Path(__file__).resolve()
        )
        attestation = build_attestation(
            final_audit_sha256=audit.sha256,
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            duration_seconds=duration,
            discovered_tests=discovered_tests,
            result=result,
            result_output=result_output,
            test_inventory_sha256=test_hash_before,
            source_inventory_sha256=source_hash_before,
            test_files=len(test_paths_before),
            source_files=len(source_paths_before),
            command=[
                sys.executable,
                str(effective_runner),
                "--work-dir",
                str(work_dir),
                "--final-audit",
                str(final_audit_path.resolve()),
                "--output",
                str(output_path.resolve()),
            ],
            runner_path=effective_runner,
        )
        write_locked_json(output_path.resolve(), attestation)
        return attestation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--final-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    attestation = run_complete_suite(
        work_dir=args.work_dir,
        final_audit_path=args.final_audit,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": sha256(args.output.resolve()),
                "tests_run": attestation["tests_run"],
                "verdict": attestation["verdict"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
