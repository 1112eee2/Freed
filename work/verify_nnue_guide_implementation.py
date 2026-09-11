"""Backward-compatibility wrapper for verify_nnue_guide_implementation.

Canonical implementation has moved to tools.verification.verify_nnue_guide_implementation.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification.verify_nnue_guide_implementation import *

if __name__ == "__main__":
    from tools.verification.verify_nnue_guide_implementation import main
    main()
