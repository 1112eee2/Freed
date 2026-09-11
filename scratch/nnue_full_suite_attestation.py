"""Backward-compatibility wrapper for full_suite_attestation.

Canonical implementation has moved to tools.verification.full_suite_attestation.
This module re-exports all public symbols, preserving legacy imports and CLI usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.full_suite_attestation import (  # noqa: F401, E402
    DEFAULT_WORK_DIR,
    ExclusiveSuiteLease,
    FORMAT,
    FullSuiteGateError,
    GuardedTextResult,
    InteractivePriorityChanged,
    KIND,
    LOCK_SLOTS,
    ProductionOpenGuard,
    ROOT,
    SOURCE_DIRECTORIES,
    SOURCE_SUFFIXES,
    TOP_LEVEL_SOURCES,
    build_attestation,
    discover_complete_suite,
    execute_suite,
    inventory_sha256,
    main,
    require_complete_health,
    run_complete_suite,
    sha256,
    source_inventory_paths,
    test_inventory_paths,
    validate_run_preconditions,
    write_locked_json,
)

if __name__ == "__main__":
    main()
