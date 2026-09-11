"""Backward-compatibility wrapper for run_sprt_step4_1000ms.

Canonical implementation has moved to tools.arena.run_sprt_step4_1000ms.
This module preserves legacy command lines.
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    canonical = Path(__file__).resolve().parents[1] / "tools" / "arena" / "run_sprt_step4_1000ms.py"
    runpy.run_path(str(canonical), run_name="__main__")
