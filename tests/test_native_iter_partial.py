"""ITER_PARTIAL_01: keep a better root move from an interrupted iteration.

The candidate (MAKHOS_ITER_PARTIAL=1) is compiled from source.  The test-only
MAKHOS_TEST_STOP_AFTER_NODES stop makes an interrupted iteration reproducible
without a wall-clock deadline.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from makhos.core import initial_state, legal_moves, parse_position
from makhos.native import NativeSearch

ROOT = Path(__file__).resolve().parents[1]
SEARCH = dict(time_ms=None, no_progress_plies=80, repetition_limit=3)
STOP_NODES = 300000
# Train-split positions from corpora/nnue_quiet_leaf_pilot_v4.jsonl.  At the
# 300,000-node stop the last two interrupt an iteration after a later root
# move has beaten the first one.
POSITIONS = (
    "R:BM12,17,20,22,25,26,30:RM1,3,4,7,9:RK24",
    "R:BM13,14,26,27,28,29,32:RM1,4,6,7,8,15,19",
    "R:BM22,23,24,25,28,29,30,31:RM1,3,4,6,7,8,9,11",
    "B:BM23,24,25,26,27,29,30,32:RM1,2,3,4,5,7,12,14",
    "B:BM11,22,24,29,30,32:RM2,4,6,8,9",
)


def _compiler() -> str | None:
    clang = Path(r"C:\Program Files\LLVM\bin\clang.exe")
    return str(clang) if clang.is_file() else shutil.which("clang") or shutil.which("gcc")


def _outcome(result):
    return result.move.notation, result.score, result.depth, result.nodes, tuple(
        move.notation for move in result.pv
    )


class NativeIterPartialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = _compiler()
        if compiler is None:
            raise unittest.SkipTest("a C compiler is required for the candidate")
        (ROOT / "build").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix="iter-partial-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, build, ignore_errors=True)
        flags = ["-O2", "-std=c17", "-shared", "-DMAKHOS_NO_MAIN=1"]
        if os.name != "nt":
            flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
        suffix = ".dll" if os.name == "nt" else ".so"
        stop = f"-DMAKHOS_TEST_STOP_AFTER_NODES={STOP_NODES}"
        cls.libraries = {}
        for name, defines in (
            ("control", []),
            ("candidate", ["-DMAKHOS_ITER_PARTIAL=1"]),
            ("control_stop", [stop]),
            ("candidate_stop", [stop, "-DMAKHOS_ITER_PARTIAL=1"]),
        ):
            output = build / (name + suffix)
            process = subprocess.run(
                [compiler, *flags, *defines,
                 str(ROOT / "native" / "makhos_native.c"), "-o", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            if process.returncode:
                raise AssertionError(process.stderr)
            cls.libraries[name] = output

    def search(self, name, position, depth):
        state = parse_position(position) if isinstance(position, str) else position
        with NativeSearch(self.libraries[name], hash_power=16, persistent=True) as engine:
            result = engine.search(
                state, depth=depth, history={state.position_key: 1}, **SEARCH
            )
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.pv[0], result.move)
        return result

    def test_uninterrupted_searches_match_the_control(self):
        # Without a stop every iteration completes, so the candidate's tree,
        # move, score and PV are the control's at every depth.
        for position in (initial_state(), *POSITIONS):
            for depth in (1, 4, 9):
                with self.subTest(position=position, depth=depth):
                    self.assertEqual(
                        _outcome(self.search("candidate", position, depth)),
                        _outcome(self.search("control", position, depth)),
                    )

    def test_interrupted_searches_keep_the_completed_depth(self):
        # The rule only changes what is returned: the same nodes are searched
        # and the reported depth is the last completed iteration.
        for position in (initial_state(), *POSITIONS):
            with self.subTest(position=position):
                candidate = self.search("candidate_stop", position, 40)
                control = self.search("control_stop", position, 40)
                self.assertLess(control.depth, 40)
                self.assertEqual(candidate.depth, control.depth)
                self.assertEqual(candidate.nodes, control.nodes)

    def test_interrupted_iteration_can_change_the_move(self):
        changed = [
            position for position in POSITIONS
            if self.search("candidate_stop", position, 40).move
            != self.search("control_stop", position, 40).move
        ]
        self.assertGreater(len(changed), 0)


if __name__ == "__main__":
    unittest.main()
