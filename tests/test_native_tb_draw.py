"""TBDRAW_01: exact tablebase draws inside the main native search.

The candidate is compiled from source with MAKHOS_SEARCH_TB_DRAW=1 and only
changes behavior once a tablebase is attached; the default build has no hook.
"""

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from makhos.compact_tb3 import CompactTablebase
from makhos.core import initial_state, legal_moves, parse_position
from makhos.native import NativeSearch
from makhos.native_endgame import NativeEndgameTablebase
from makhos.parallel_native import ParallelNativeSearch

ROOT = Path(__file__).resolve().parents[1]
# Exact TB3 DRAW positions whose every legal reply is also an exact draw, yet
# the unattached HCE search scores them away from zero.
ALL_DRAW_FIXTURES = ("B:BK1:RM8,14", "R:BM15,19:RK5", "R:BM6,11:RK2")
SEARCH = dict(depth=6, time_ms=None, no_progress_plies=80, repetition_limit=3)


def _compiler() -> str | None:
    clang = Path(r"C:\Program Files\LLVM\bin\clang.exe")
    return str(clang) if clang.is_file() else shutil.which("clang") or shutil.which("gcc")


def _outcome(result):
    return result.move.notation, result.score, result.nodes, tuple(
        move.notation for move in result.pv
    )


class NativeTablebaseDrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = _compiler()
        if compiler is None:
            raise unittest.SkipTest("a C compiler is required for the TB draw candidate")
        (ROOT / "build").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix="tb-draw-tests-", dir=ROOT / "build"))
        cls.addClassCleanup(shutil.rmtree, build, ignore_errors=True)
        flags = ["-O2", "-std=c17", "-shared"]
        if os.name != "nt":
            flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.control_path = build / ("control" + suffix)
        cls.candidate_path = build / ("candidate" + suffix)
        cls.tb_library = build / ("endgame_tb" + suffix)
        for output, source, defines in (
            (cls.control_path, "native/makhos_native.c", ["-DMAKHOS_NO_MAIN=1"]),
            (
                cls.candidate_path,
                "native/makhos_native.c",
                ["-DMAKHOS_NO_MAIN=1", "-DMAKHOS_SEARCH_TB_DRAW=1"],
            ),
            (cls.tb_library, "native/makhos_endgame_tb.c", []),
        ):
            process = subprocess.run(
                [compiler, *flags, *defines, str(ROOT / source), "-o", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            if process.returncode:
                raise AssertionError(process.stderr)
        cls.tb3 = CompactTablebase()
        cls.addClassCleanup(cls.tb3.close)
        cls.tablebase = NativeEndgameTablebase(cls.tb3, library=cls.tb_library)
        cls.addClassCleanup(cls.tablebase.close)

    def search(self, library, fen, *, tablebase=None, **overrides):
        state = parse_position(fen) if isinstance(fen, str) else fen
        arguments = {**SEARCH, **overrides, "history": {state.position_key: 1}}
        with NativeSearch(library, hash_power=16, persistent=True) as engine:
            if tablebase is not None:
                engine.attach_tablebase(tablebase)
            result = engine.search(state, **arguments)
            return result, engine.tablebase_counters()

    def test_default_build_exposes_no_tablebase_hook(self):
        with NativeSearch(self.control_path, hash_power=16, persistent=True) as engine:
            self.assertFalse(engine.supports_tablebase_draw)
            with self.assertRaises(RuntimeError):
                engine.attach_tablebase(self.tablebase)

    def test_unattached_candidate_matches_control_node_for_node(self):
        positions = (*ALL_DRAW_FIXTURES, initial_state(), "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17")
        for position in positions:
            with self.subTest(position=position):
                control, _ = self.search(self.control_path, position)
                candidate, counters = self.search(self.candidate_path, position)
                self.assertEqual(_outcome(candidate), _outcome(control))
                self.assertEqual(counters, (0, 0, 0))

    def test_attached_candidate_scores_exact_draw_replies_as_draws(self):
        for fen in ALL_DRAW_FIXTURES:
            with self.subTest(fen=fen):
                control, _ = self.search(self.control_path, fen)
                attached, (probes, draws, errors) = self.search(
                    self.candidate_path, fen, tablebase=self.tablebase
                )
                self.assertNotEqual(control.score, 0)
                self.assertEqual(attached.score, 0)
                self.assertGreater(draws, 0)
                self.assertEqual(probes, draws)
                self.assertEqual(errors, 0)
                self.assertLess(attached.nodes, control.nodes)

    def test_detach_restores_control_behavior(self):
        state = parse_position(ALL_DRAW_FIXTURES[0])
        arguments = {**SEARCH, "history": {state.position_key: 1}}
        control, _ = self.search(self.control_path, state)
        with NativeSearch(self.candidate_path, hash_power=16, persistent=True) as engine:
            engine.attach_tablebase(self.tablebase)
            self.assertEqual(engine.search(state, **arguments).score, 0)
            engine.detach_tablebase()
            engine.clear()
            self.assertEqual(_outcome(engine.search(state, **arguments)), _outcome(control))

    def test_probes_only_with_the_tablebase_no_progress_horizon(self):
        fen = ALL_DRAW_FIXTURES[0]
        control, _ = self.search(self.control_path, fen, no_progress_plies=40)
        attached, counters = self.search(
            self.candidate_path, fen, tablebase=self.tablebase, no_progress_plies=40
        )
        self.assertEqual(counters, (0, 0, 0))
        self.assertEqual(_outcome(attached), _outcome(control))

    def test_attach_requires_a_persistent_search(self):
        with NativeSearch(self.candidate_path, hash_power=16) as engine:
            with self.assertRaises(ValueError):
                engine.attach_tablebase(self.tablebase)

    def test_probe_errors_fail_closed(self):
        prototype = ctypes.CFUNCTYPE(
            ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )
        corrupt = prototype(lambda _set, _position, _output: 4)  # MK_EG_CORRUPT
        released = []

        class CorruptTablebase:
            no_progress_plies = 80
            max_pieces = 3

            def borrow_for_search(self):
                address = ctypes.cast(corrupt, ctypes.c_void_p).value
                return address, address, lambda: released.append(True)

        state = parse_position(ALL_DRAW_FIXTURES[0])
        with NativeSearch(self.candidate_path, hash_power=16, persistent=True) as engine:
            engine.attach_tablebase(CorruptTablebase())
            with self.assertRaisesRegex(RuntimeError, "tablebase probe failed"):
                engine.search(state, **SEARCH, history={state.position_key: 1})
        self.assertEqual(released, [True])

    def test_root_split_attaches_every_worker(self):
        state = parse_position(ALL_DRAW_FIXTURES[1])
        with ParallelNativeSearch(self.candidate_path, threads=2, hash_mb=16) as engine:
            self.assertTrue(engine.supports_tablebase_draw)
            engine.attach_tablebase(self.tablebase)
            result = engine.search(state, **SEARCH, history={state.position_key: 1})
            probes, draws, errors = engine.tablebase_counters()
            engine.detach_tablebase()
        self.assertIn(result.move, legal_moves(state))
        self.assertGreater(draws, 0)
        self.assertEqual(errors, 0)
        self.assertGreaterEqual(probes, draws)


if __name__ == "__main__":
    unittest.main()
