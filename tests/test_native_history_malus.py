"""HISTORY_MALUS_01: bounded quiet history with a malus for failed quiet moves.

The candidate (MAKHOS_HISTORY_GRAVITY=1 and MAKHOS_HISTORY_MALUS=1) is
compiled from source; the default build keeps the unbounded d*d history with
no malus.  A gravity-only build separates the malus from the bounded update.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from makhos.core import apply_move, initial_state, legal_moves, parse_position
from makhos.native import NativeSearch

ROOT = Path(__file__).resolve().parents[1]
SEARCH = dict(time_ms=None, no_progress_plies=80, repetition_limit=3)
# Train-split middlegame and endgame positions (as in test_native_lmr).
POSITIONS = (
    "R:BM12,17,20,22,25,26,30:RM1,3,4,7,9:RK24",
    "R:BM13,14,26,27,28,29,32:RM1,4,6,7,8,15,19",
    "B:BM21,22,24,25,30,31,32:RM1,2,4,6,10,14,16",
    "R:BM14,19,30:BK22:RM5,12:RK2",
)


def _compiler() -> str | None:
    clang = Path(r"C:\Program Files\LLVM\bin\clang.exe")
    return str(clang) if clang.is_file() else shutil.which("clang") or shutil.which("gcc")


def _outcome(result):
    return result.move.notation, result.score, result.nodes, tuple(
        move.notation for move in result.pv
    )


class NativeHistoryMalusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = _compiler()
        if cls.compiler is None:
            raise unittest.SkipTest("a C compiler is required for the history candidate")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.build = Path(tempfile.mkdtemp(prefix="history-malus-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, cls.build, ignore_errors=True)
        cls.flags = ["-O2", "-std=c17", "-shared", "-DMAKHOS_NO_MAIN=1"]
        if os.name != "nt":
            cls.flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.control_path = cls.build / ("control" + suffix)
        cls.gravity_path = cls.build / ("gravity" + suffix)
        cls.candidate_path = cls.build / ("candidate" + suffix)
        for output, defines in (
            (cls.control_path, []),
            (cls.gravity_path, ["-DMAKHOS_HISTORY_GRAVITY=1"]),
            (cls.candidate_path,
             ["-DMAKHOS_HISTORY_GRAVITY=1", "-DMAKHOS_HISTORY_MALUS=1"]),
        ):
            process = cls.compile(output, defines)
            if process.returncode:
                raise AssertionError(process.stderr)

    @classmethod
    def compile(cls, output, defines):
        return subprocess.run(
            [cls.compiler, *cls.flags, *defines,
             str(ROOT / "native" / "makhos_native.c"), "-o", str(output)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def search(self, library, position, depth):
        state = parse_position(position) if isinstance(position, str) else position
        with NativeSearch(library, hash_power=16, persistent=True) as engine:
            result = engine.search(
                state, depth=depth, history={state.position_key: 1}, **SEARCH
            )
        self.assertEqual(result.depth, depth)
        self.assertIn(result.move, legal_moves(state))
        return result

    def test_malus_requires_the_bounded_update(self):
        process = self.compile(
            self.build / "malus_only.dll", ["-DMAKHOS_HISTORY_MALUS=1"]
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("bounded history-gravity update", process.stderr)

    def test_deep_searches_complete_with_legal_moves(self):
        for position in (initial_state(), *POSITIONS):
            with self.subTest(position=position):
                self.search(self.candidate_path, position, 12)

    def test_malus_changes_the_search_beyond_gravity(self):
        changed = sum(
            _outcome(self.search(self.candidate_path, position, 10))
            != _outcome(self.search(self.gravity_path, position, 10))
            for position in (initial_state(), *POSITIONS)
        )
        self.assertGreater(changed, 0)

    def test_candidate_changes_the_search(self):
        changed = sum(
            _outcome(self.search(self.candidate_path, position, 10))
            != _outcome(self.search(self.control_path, position, 10))
            for position in (initial_state(), *POSITIONS)
        )
        self.assertGreater(changed, 0)

    def test_persistent_history_stays_usable_over_many_searches(self):
        # Persistent search keeps history across moves of a game; a long
        # sequence of searches must keep returning legal moves.
        state = initial_state()
        with NativeSearch(self.candidate_path, hash_power=16, persistent=True) as engine:
            history = {state.position_key: 1}
            for _ in range(24):
                if not legal_moves(state):
                    break
                result = engine.search(state, depth=8, history=history, **SEARCH)
                self.assertIn(result.move, legal_moves(state))
                state = apply_move(state, result.move)
                history[state.position_key] = history.get(state.position_key, 0) + 1


if __name__ == "__main__":
    unittest.main()
