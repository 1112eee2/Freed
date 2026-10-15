"""NULL_EVAL_01: null move only at null-window nodes whose static eval reaches beta.

The candidate (MAKHOS_NULL_EVAL_GUARD=1) is compiled from source; the default
build tries null move at every eligible node, PV or not, whatever the
evaluation.  The guard evaluates interior nodes, so the NNUE build is also
checked with the accumulator parity guard.
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
MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
SEARCH = dict(time_ms=None, no_progress_plies=80, repetition_limit=3)
# Train-split middlegame and endgame positions (as in test_native_lmr).
POSITIONS = (
    "R:BM12,17,20,22,25,26,30:RM1,3,4,7,9:RK24",
    "R:BM13,14,26,27,28,29,32:RM1,4,6,7,8,15,19",
    "B:BM21,22,24,25,30,31,32:RM1,2,4,6,10,14,16",
    "R:BM14,19,30:BK22:RM5,12:RK2",
)
# Six pieces: null move needs more than six, and captures only remove pieces,
# so no node of this tree may try it.
SIX_PIECES = "R:BM14,19:BK22:RM5,12:RK2"


def _compiler() -> str | None:
    clang = Path(r"C:\Program Files\LLVM\bin\clang.exe")
    return str(clang) if clang.is_file() else shutil.which("clang") or shutil.which("gcc")


def _outcome(result):
    return result.move.notation, result.score, result.nodes, tuple(
        move.notation for move in result.pv
    )


class NativeNullEvalGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = _compiler()
        if compiler is None:
            raise unittest.SkipTest("a C compiler is required for the null-move candidate")
        (ROOT / "build").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix="null-eval-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, build, ignore_errors=True)
        flags = ["-O2", "-std=c17", "-shared", "-DMAKHOS_NO_MAIN=1"]
        if os.name != "nt":
            flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.control_path = build / ("control" + suffix)
        cls.candidate_path = build / ("candidate" + suffix)
        for output, defines in (
            (cls.control_path, []),
            (cls.candidate_path, ["-DMAKHOS_NULL_EVAL_GUARD=1"]),
        ):
            process = subprocess.run(
                [compiler, *flags, *defines,
                 str(ROOT / "native" / "makhos_native.c"), "-o", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            if process.returncode:
                raise AssertionError(process.stderr)

    def search(self, library, position, depth):
        state = parse_position(position) if isinstance(position, str) else position
        with NativeSearch(library, hash_power=16, persistent=True) as engine:
            result = engine.search(
                state, depth=depth, history={state.position_key: 1}, **SEARCH
            )
        self.assertEqual(result.depth, depth)
        self.assertIn(result.move, legal_moves(state))
        return result

    def test_shallow_searches_match_the_control(self):
        # Null move needs depth 3 at the node, so a depth-2 root search is
        # identical node for node.
        for position in (initial_state(), *POSITIONS):
            with self.subTest(position=position):
                self.assertEqual(
                    _outcome(self.search(self.candidate_path, position, 2)),
                    _outcome(self.search(self.control_path, position, 2)),
                )

    def test_six_piece_searches_match_the_control(self):
        self.assertEqual(
            _outcome(self.search(self.candidate_path, SIX_PIECES, 12)),
            _outcome(self.search(self.control_path, SIX_PIECES, 12)),
        )

    def test_deep_searches_complete_with_legal_moves(self):
        for position in (initial_state(), *POSITIONS):
            with self.subTest(position=position):
                self.search(self.candidate_path, position, 12)

    def test_candidate_changes_the_search(self):
        changed = sum(
            _outcome(self.search(self.candidate_path, position, 10))
            != _outcome(self.search(self.control_path, position, 10))
            for position in (initial_state(), *POSITIONS)
        )
        self.assertGreater(changed, 0)



class NativeNullEvalGuardNnueTests(unittest.TestCase):
    """The NNUE playing build, with every evaluation checked against a refresh."""

    @classmethod
    def setUpClass(cls):
        compiler = _compiler()
        if compiler is None or not MODEL.is_file():
            raise unittest.SkipTest("a C compiler and the NNUE v1 model are required")
        (ROOT / "build").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix="null-eval-nnue-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, build, ignore_errors=True)
        flags = ["-O2", "-march=x86-64", "-std=c17", "-shared",
                 "-DMAKHOS_NNUE_PARITY_GUARD=1"]
        if os.name != "nt":
            flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L", "-lm", "-lpthread"]
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.control_path = build / ("control" + suffix)
        cls.candidate_path = build / ("candidate" + suffix)
        for output, defines in (
            (cls.control_path, []),
            (cls.candidate_path, ["-DMAKHOS_NULL_EVAL_GUARD=1"]),
        ):
            process = subprocess.run(
                [compiler, *flags, *defines, "-I", str(ROOT / "native"),
                 str(ROOT / "native" / "makhos_native_nnue.c"), "-o", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            if process.returncode:
                raise AssertionError(process.stderr)

    def search(self, library, position, depth):
        state = parse_position(position) if isinstance(position, str) else position
        with NativeSearch(
            library, hash_power=16, persistent=True, nnue_model=MODEL
        ) as engine:
            result = engine.search(
                state, depth=depth, history={state.position_key: 1}, **SEARCH
            )
        self.assertEqual(result.depth, depth)
        self.assertIn(result.move, legal_moves(state))
        return result

    def test_shallow_searches_match_the_control(self):
        for position in (initial_state(), *POSITIONS):
            with self.subTest(position=position):
                self.assertEqual(
                    _outcome(self.search(self.candidate_path, position, 2)),
                    _outcome(self.search(self.control_path, position, 2)),
                )

    def test_guarded_searches_keep_accumulator_parity(self):
        # MAKHOS_NNUE_PARITY_GUARD stops the search if any evaluation,
        # including the guard's interior ones, differs from a full refresh.
        for position in (initial_state(), *POSITIONS):
            with self.subTest(position=position):
                self.search(self.candidate_path, position, 10)


if __name__ == "__main__":
    unittest.main()
