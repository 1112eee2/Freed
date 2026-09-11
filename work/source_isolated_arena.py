"""Backward-compatibility wrapper for source_isolated_arena.

Canonical implementation has moved to tools.arena.source_isolated_arena.
This module preserves legacy CLI invocations and imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.arena.source_isolated_arena import (  # noqa: F401, E402
    DEFAULT_CANDIDATE_PATH,
    DEFAULT_CONTROL_PATH,
    DEFAULT_TB3_PATH,
    DEFAULT_TB4_PATH,
    PILOT_OUT,
    REPRODUCER_HISTORY,
    REPRODUCER_POS,
    ROOT,
    WINNING_CANDIDATE_MOVES,
    WORKER_SCRIPT,
    IsolatedEngineClient,
    main,
    play_game,
    run_pilot,
)

if __name__ == "__main__":
    main()
