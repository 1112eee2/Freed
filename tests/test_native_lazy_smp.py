"""LAZY_SMP_01: native Lazy SMP over one lockless shared TT (Track F1).

The candidate (MAKHOS_SHARED_TT=1, MAKHOS_LOCKLESS_TT=1,
MAKHOS_NATIVE_LAZY_SMP=1, MAKHOS_NATIVE_LAZY_SMP_SKIP_DEPTH=1) is compiled
from source next to a control with the same search flags.  At one thread the
Lazy-SMP handle must replay the control's persistent search node for node.
Above one thread the result is not deterministic, so only legality, the
completed depth and the deadline are checked.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from makhos.core import initial_state, legal_moves, parse_position
from makhos.native import NativeLazySmpSearch, NativeSearch

ROOT = Path(__file__).resolve().parents[1]
SEARCH = dict(no_progress_plies=80, repetition_limit=3)
# The SEARCH_INT_01 flags of the RC-2 line.
SEARCH_FLAGS = [
    "-DMAKHOS_STRICT_SEARCH_POSITION_KEY=1",
    "-DMAKHOS_NULL_EVAL_GUARD=1",
    "-DMAKHOS_LMR_LOG=1",
    "-DMAKHOS_HISTORY_GRAVITY=1",
    "-DMAKHOS_HISTORY_MALUS=1",
]
LAZY_FLAGS = [
    "-DMAKHOS_SHARED_TT=1",
    "-DMAKHOS_LOCKLESS_TT=1",
    "-DMAKHOS_NATIVE_LAZY_SMP=1",
    "-DMAKHOS_NATIVE_LAZY_SMP_SKIP_DEPTH=1",
]
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
    return result.move.notation, result.score, result.depth, result.nodes, tuple(
        move.notation for move in result.pv
    )


def _states():
    return (initial_state(), *(parse_position(text) for text in POSITIONS))


@unittest.skipUnless(os.name == "nt", "native Lazy SMP uses Win32 threads")
class NativeLazySmpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = _compiler()
        if compiler is None:
            raise unittest.SkipTest("a C compiler is required for the Lazy-SMP candidate")
        (ROOT / "build").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix="lazy-smp-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, build, ignore_errors=True)
        flags = ["-O2", "-std=c17", "-shared", "-DMAKHOS_NO_MAIN=1", *SEARCH_FLAGS]
        cls.control_path = build / "control.dll"
        cls.candidate_path = build / "candidate.dll"
        for output, defines in (
            (cls.control_path, []),
            (cls.candidate_path, LAZY_FLAGS),
        ):
            process = subprocess.run(
                [compiler, *flags, *defines,
                 str(ROOT / "native" / "makhos_native.c"), "-o", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            if process.returncode:
                raise AssertionError(process.stderr)

    def test_one_thread_replays_the_control_search(self):
        # Both handles keep their TT across the sequence, so the replacement
        # rule and the generation must match as well as the search.
        with NativeSearch(
            self.control_path, hash_power=16, persistent=True
        ) as control, NativeLazySmpSearch(
            self.candidate_path, threads=1, hash_mb=3
        ) as lazy:
            self.assertEqual(lazy.hash_power, control.hash_power)
            for state in _states():
                for depth in (6, 11):
                    with self.subTest(state=state, depth=depth):
                        options = dict(
                            depth=depth,
                            time_ms=None,
                            history={state.position_key: 1},
                            **SEARCH,
                        )
                        self.assertEqual(
                            _outcome(lazy.search(state, **options)),
                            _outcome(control.search(state, **options)),
                        )

    def test_four_threads_complete_the_requested_depth(self):
        with NativeLazySmpSearch(self.candidate_path, threads=4, hash_mb=16) as lazy:
            for state in _states():
                with self.subTest(state=state):
                    result = lazy.search(
                        state,
                        depth=10,
                        time_ms=None,
                        history={state.position_key: 1},
                        **SEARCH,
                    )
                    stats = lazy.stats
                    self.assertIn(result.move, legal_moves(state))
                    self.assertEqual(result.depth, 10)
                    self.assertEqual(stats.leader_depth, 10)
                    self.assertEqual(stats.completed_threads, 4)
                    self.assertTrue(all(depth <= 10 for depth in stats.worker_depth))
                    self.assertGreaterEqual(stats.aggregate_nodes, stats.leader_nodes)

    def test_four_threads_stop_at_the_deadline(self):
        state = parse_position(POSITIONS[0])
        with NativeLazySmpSearch(self.candidate_path, threads=4, hash_mb=16) as lazy:
            started = time.perf_counter()
            result = lazy.search(
                state,
                depth=64,
                time_ms=150,
                history={state.position_key: 1},
                **SEARCH,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
        self.assertIn(result.move, legal_moves(state))
        self.assertGreater(result.depth, 0)
        self.assertLess(elapsed_ms, 1000.0)

    def test_root_rotation_and_depth_skipping_are_exclusive(self):
        process = subprocess.run(
            [_compiler(), "-std=c17", "-fsyntax-only", "-DMAKHOS_NO_MAIN=1",
             *LAZY_FLAGS, "-DMAKHOS_NATIVE_LAZY_SMP_ROOT_ROTATION=1",
             str(ROOT / "native" / "makhos_native.c")],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("one diversification rule", process.stderr)


if __name__ == "__main__":
    unittest.main()
