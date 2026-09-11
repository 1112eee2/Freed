"""Backward-compatibility wrapper for prepare_nnue_thread_audit.

Canonical implementation has moved to tools.verification.prepare_nnue_thread_audit.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.prepare_nnue_thread_audit import *

if __name__ == "__main__":
    from tools.verification.prepare_nnue_thread_audit import main
    main()
