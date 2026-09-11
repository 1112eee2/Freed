"""Backward-compatibility wrapper for nnue_production_smoke.

Canonical implementation has moved to tools.verification.nnue_production_smoke.
This module preserves legacy CLI invocations and imports.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.nnue_production_smoke import (  # noqa: F401, E402
    INITIAL,
    MANIFEST,
    ROOT,
    freeze,
    main,
    post,
    running_server,
    sha,
    smoke,
    write_new,
)

if __name__ == "__main__":
    main()
