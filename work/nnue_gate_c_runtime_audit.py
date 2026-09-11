"""Backward-compatibility wrapper for nnue_gate_c_runtime_audit.

Canonical implementation has moved to tools.verification.nnue_gate_c_runtime_audit.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.nnue_gate_c_runtime_audit import *

if __name__ == "__main__":
    import runpy
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "verification" / "nnue_gate_c_runtime_audit.py"), run_name="__main__")
