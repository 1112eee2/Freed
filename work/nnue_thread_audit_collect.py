"""Backward-compatibility wrapper for nnue_thread_audit_collect.

Canonical implementation has moved to tools.verification.nnue_thread_audit_collect.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.nnue_thread_audit_collect import *

if __name__ == "__main__":
    from tools.verification.nnue_thread_audit_collect import main
    main()
