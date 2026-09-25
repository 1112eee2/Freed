"""RFP_01: guarded reverse futility pruning in the main native search.

The candidate (MAKHOS_REVERSE_FUTILITY=1) and its measurement census
(MAKHOS_RFP_CENSUS=1) are compiled from source; the default build has neither.
"""

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from makhos.core import initial_state, legal_moves, parse_position
from makhos.native import NativeSearch

ROOT = Path(__file__).resolve().parents[1]
SEARCH = dict(depth=9, time_ms=None, no_progress_plies=80, repetition_limit=3)
# Train-split middlegame positions with 11 to 16 pieces, with and without kings.
MIDDLEGAME = (
    "R:BM12,17,20,22,25,26,30:RM1,3,4,7,9:RK24",
    "R:BM9,13,14,24,27,32:RM4,5,7,11,18:RK31",
    "R:BM24,27,30,31,32:BK3:RM1,4,5,8,20",
    "R:BM13,14,26,27,28,29,32:RM1,4,6,7,8,15,19",
    "B:BM21,22,24,25,30,31,32:RM1,2,4,6,10,14,16",
    "R:BM18,19,20,23,26,29,31:RM1,3,6,8,9,11,14",
)
# Train-split positions below the candidate's 11-piece guard.
ENDGAME = (
    "R:BM14,19,30:BK22:RM5,12:RK2",
    "R:BM21,23,28,29:BK25:RM1,2,3,5:RK31",
    "R:BM21,29,30:BK27:RM13,20:RK19",
)
DEPTHS = 4
REASONS = (
    "eligible", "mate_window", "capture", "pieces", "repetition",
    "no_progress", "threat_capture", "threat_promotion",
)
BINS = 128


class RfpCensus(ctypes.Structure):
    _fields_ = [
        ("rejected", (ctypes.c_uint64 * len(REASONS)) * DEPTHS),
        ("below_beta", (ctypes.c_uint64 * 2) * DEPTHS),
        ("fail_low", (ctypes.c_uint64 * BINS) * DEPTHS),
        ("fail_high", (ctypes.c_uint64 * BINS) * DEPTHS),
    ]


def _compiler() -> str | None:
    clang = Path(r"C:\Program Files\LLVM\bin\clang.exe")
    return str(clang) if clang.is_file() else shutil.which("clang") or shutil.which("gcc")


def _flags() -> list[str]:
    flags = ["-O2", "-std=c17", "-shared", "-DMAKHOS_NO_MAIN=1"]
    if os.name != "nt":
        flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
    return flags


def _outcome(result):
    return result.move.notation, result.score, result.nodes, tuple(
        move.notation for move in result.pv
    )


class NativeReverseFutilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = _compiler()
        if cls.compiler is None:
            raise unittest.SkipTest("a C compiler is required for the RFP candidate")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.build = Path(tempfile.mkdtemp(prefix="rfp-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, cls.build, ignore_errors=True)
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.control_path = cls.build / ("control" + suffix)
        cls.candidate_path = cls.build / ("candidate" + suffix)
        cls.census_path = cls.build / ("census" + suffix)
        for output, defines in (
            (cls.control_path, []),
            (cls.candidate_path, ["-DMAKHOS_REVERSE_FUTILITY=1"]),
            (cls.census_path, ["-DMAKHOS_RFP_CENSUS=1"]),
        ):
            process = cls.compile(defines, output)
            if process.returncode:
                raise AssertionError(process.stderr)

    @classmethod
    def compile(cls, defines, output):
        return subprocess.run(
            [cls.compiler, *_flags(), *defines,
             str(ROOT / "native" / "makhos_native.c"), "-o", str(output)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def search(self, library, position, *, census=False, **overrides):
        state = parse_position(position) if isinstance(position, str) else position
        arguments = {**SEARCH, **overrides, "history": {state.position_key: 1}}
        with NativeSearch(library, hash_power=16, persistent=True) as engine:
            result = engine.search(state, **arguments)
            counts = None
            if census:
                counts = RfpCensus()
                read = engine._library.makhos_search_rfp_census
                read.argtypes = [ctypes.c_void_p, ctypes.POINTER(RfpCensus)]
                read.restype = ctypes.c_int
                self.assertEqual(read(engine._handle, ctypes.byref(counts)), 0)
        self.assertEqual(result.depth, arguments["depth"])
        self.assertIn(result.move, legal_moves(state))
        return result, counts

    def test_only_the_census_build_exports_the_census(self):
        for path, exported in (
            (self.control_path, False),
            (self.candidate_path, False),
            (self.census_path, True),
        ):
            with self.subTest(library=path.name):
                library = ctypes.CDLL(str(path))
                self.assertEqual(hasattr(library, "makhos_search_rfp_census"), exported)

    def test_census_and_pruning_cannot_be_combined(self):
        process = self.compile(
            ["-DMAKHOS_REVERSE_FUTILITY=1", "-DMAKHOS_RFP_CENSUS=1"],
            self.build / "combined.bin",
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("MAKHOS_RFP_CENSUS measures the unpruned search", process.stderr)

    def test_census_build_searches_like_the_control(self):
        for position in (initial_state(), *MIDDLEGAME, *ENDGAME):
            with self.subTest(position=position):
                control, _ = self.search(self.control_path, position)
                census, _ = self.search(self.census_path, position, census=True)
                self.assertEqual(_outcome(census), _outcome(control))

    def test_census_gives_every_guarded_node_one_outcome(self):
        totals = [dict.fromkeys(REASONS, 0) for _ in range(DEPTHS)]
        for position in (initial_state(), *MIDDLEGAME):
            _, counts = self.search(self.census_path, position, census=True)
            for d in range(DEPTHS):
                outcomes = (
                    sum(counts.fail_low[d]) + sum(counts.fail_high[d])
                    + counts.below_beta[d][0] + counts.below_beta[d][1]
                )
                self.assertEqual(outcomes, counts.rejected[d][0], f"depth {d + 1}")
                for index, reason in enumerate(REASONS):
                    totals[d][reason] += counts.rejected[d][index]
        for reason in ("eligible", "mate_window", "capture", "pieces",
                       "threat_capture", "threat_promotion"):
            with self.subTest(reason=reason):
                self.assertGreater(sum(row[reason] for row in totals), 0)

    def test_census_guards_nodes_near_the_no_progress_limit(self):
        # With a 70-ply clock, nodes stay unguarded until a capture or a
        # promotion resets the clock.
        eligible = {}
        for clock in (0, 70):
            state = parse_position(MIDDLEGAME[5], reversible_plies=clock)
            _, counts = self.search(self.census_path, state, census=True)
            eligible[clock] = sum(counts.rejected[d][0] for d in range(DEPTHS))
            no_progress = sum(counts.rejected[d][5] for d in range(DEPTHS))
            if clock == 0:
                self.assertEqual(no_progress, 0)
            else:
                self.assertGreater(no_progress, 0)
        self.assertLess(eligible[70], eligible[0])

    def test_candidate_is_inert_below_the_piece_guard(self):
        for position in ENDGAME:
            with self.subTest(position=position):
                control, _ = self.search(self.control_path, position)
                candidate, _ = self.search(self.candidate_path, position)
                self.assertEqual(_outcome(candidate), _outcome(control))

    def test_candidate_changes_the_middlegame_search(self):
        # Pruned subtrees also skip their TT stores and history updates, so the
        # node count may move either way; the hook must be active, and every
        # search must still complete with a legal move.
        changed = 0
        for position in (initial_state(), *MIDDLEGAME):
            control, _ = self.search(self.control_path, position)
            candidate, _ = self.search(self.candidate_path, position)
            changed += _outcome(candidate) != _outcome(control)
        self.assertGreater(changed, 0)


if __name__ == "__main__":
    unittest.main()
