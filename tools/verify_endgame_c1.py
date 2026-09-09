"""Attest the complete discovered suite for an isolated C1 checkout.

No tests are filtered. Missing dependencies/binaries and skips prevent PASS.
Run after tools/build_endgame_c1.ps1, while GUI/arena are idle.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from makhos.native_endgame import DEFAULT_LIBRARY
from scratch.nnue_full_suite_attestation import (
    ExclusiveSuiteLease, ProductionOpenGuard, execute_suite, inventory_sha256,
    source_inventory_paths, test_inventory_paths,
)
from scratch.nnue_scaling_final_audit import DEFAULT_WORK_DIR


def run(output):
    output = output.resolve()
    if output.is_relative_to(ROOT / "build/nnue_sprt_6t_vs_12t"):
        raise ValueError("output cannot be inside the frozen Experiment A directory")
    if not DEFAULT_LIBRARY.is_file():
        raise FileNotFoundError(f"build isolated C1 library first: {DEFAULT_LIBRARY}")
    if os.name == "nt":
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    guard = ProductionOpenGuard(DEFAULT_WORK_DIR)
    guard.forbidden_roots.add((ROOT / "build/nnue_sprt_6t_vs_12t").resolve())
    sys.addaudithook(guard.hook)
    with ExclusiveSuiteLease(ROOT) as lease:
        output.mkdir(parents=True, exist_ok=False)
        sources = sorted(set(source_inventory_paths()) | {
            ROOT / "benchmarks/native_endgame_ranked.py", Path(__file__).resolve(),
            ROOT / "tools/build_endgame_c1.ps1",
        })
        # Permit running this same verifier against the unchanged C1 TB3 base.
        sources = [p for p in sources if p.is_file()]
        source_hash = inventory_sha256(sources)
        test_hash = inventory_sha256(test_inventory_paths())
        library_hash = hashlib.sha256(DEFAULT_LIBRARY.read_bytes()).hexdigest()
        per_file = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sources}
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        discovered = suite.countTestCases()
        print(f"Discovered {discovered} tests", flush=True)
        result, log, elapsed = execute_suite(suite, checkpoint=lease.checkpoint)
        unchanged = (source_hash == inventory_sha256(sources)
                     and test_hash == inventory_sha256(test_inventory_paths())
                     and library_hash == hashlib.sha256(DEFAULT_LIBRARY.read_bytes()).hexdigest())
        report = dict(
            format="thai-makhos-c1-suite-v1", created_at=datetime.now(timezone.utc).isoformat(),
            platform=platform.platform(), python=sys.version,
            base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            tests_discovered=discovered, tests_run=result.testsRun,
            failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
            failure_ids=[t.id() for t, _ in result.failures], error_ids=[t.id() for t, _ in result.errors],
            skip_reasons=[(t.id(), reason) for t, reason in result.skipped],
            elapsed_seconds=elapsed, source_inventory_sha256=source_hash, test_inventory_sha256=test_hash,
            source_sha256=per_file, library=str(DEFAULT_LIBRARY), library_sha256=library_hash,
            inventories_unchanged=unchanged, protected_open_attempts=len(guard.triggered),
        )
        report["status"] = "PASS" if (result.wasSuccessful() and not result.skipped
            and result.testsRun == discovered and unchanged and not guard.triggered) else "NOT_PASS"
        (output / "full_suite.log").write_text(log, encoding="utf-8")
        (output / "full_suite.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "source_sha256"}, indent=2), flush=True)
        return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    sys.exit(run(parser.parse_args().output))
