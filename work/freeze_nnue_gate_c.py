"""Backward-compatibility wrapper for freeze_nnue_gate_c.

Canonical implementation has moved to tools.verification.freeze_nnue_gate_c.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.freeze_nnue_gate_c import *

if __name__ == "__main__":
    from tools.verification.freeze_nnue_gate_c import main
    main()
