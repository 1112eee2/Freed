"""Backward-compatibility wrapper for nnue_gate_c_control.

Canonical implementation has moved to tools.arena.nnue_gate_c_control.
This module preserves legacy CLI invocations and imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.arena.nnue_gate_c_control import (  # noqa: F401, E402
    ACTIVE,
    CONTRACT,
    CONTRACT_SHA,
    FIRST_PASS_SHA,
    ROOT,
    active_manifest,
    checked_pair_counts,
    checked_result,
    contract_at,
    expected_configs,
    launch,
    main,
    process_identity,
    publish_pointer,
    read_json,
    read_live_result,
    repository_preflight,
    require_resumable_result,
    run_state,
    same_live_process,
    sha,
    snapshot,
    verify_bindings,
)

if __name__ == "__main__":
    main()
