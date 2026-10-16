import ctypes
import random
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from makhos.core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    Move,
    RED,
    RED_KING,
    RED_MAN,
    State,
    apply_move,
    initial_state,
    legal_moves,
    parse_position,
)
from makhos.eval import evaluate_handcrafted
from makhos.eval import evaluate_endgame_king_value
from makhos.native import (
    LEGACY_NATIVE_TT_ENTRY_BYTES,
    NATIVE_TT_ENTRY_BYTES,
    NativeIirCensusTelemetry,
    NativeRepetitionCensusTelemetry,
    NativeSearch,
    NativeSearchTelemetry,
    _HistoryEntry,
    _LegacyNativeMoveLayout,
    _SearchResult,
    _bitboards,
    hash_megabytes_for_power,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
    project_native_library,
)
from makhos.parallel_native import ParallelNativeSearch
from makhos.search import Engine, SearchLimits


LIBRARY = project_native_library()
ABI4_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_workspace_candidate.dll"
)
LEGACY_LIBRARY = (
    ABI4_LIBRARY
    if ABI4_LIBRARY.is_file()
    else Path(__file__).resolve().parent.parent / "build" / "makhos_native.dll"
)
COMPACT_TT_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_compact_tt_candidate.dll"
)
PREORDER_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_preorder_candidate.dll"
)
PREORDER_CONTROL_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_preorder_control.dll"
)
EARLY_TT_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_early_tt_candidate.dll"
)
EARLY_TT_CONTROL_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_early_tt_control.dll"
)
PACKED_PV_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_packed_pv_candidate.dll"
)
PRE_PACKED_PV_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_early_tt_accepted_abi5.dll"
)
TELEMETRY_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_telemetry_candidate.dll"
)
IIR_CENSUS_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_iir_census_candidate.dll"
)
REPETITION_CENSUS_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_repetition_census_candidate.dll"
)
SMALL_HISTORY_HASH_CONTROL_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_small_history_hash_control.dll"
)
SMALL_HISTORY_HASH_CANDIDATE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_small_history_hash_candidate.dll"
)
CURRENT_LINE_SKIP_CONTROL_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_current_line_skip_control.dll"
)
CURRENT_LINE_SKIP_CANDIDATE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_current_line_skip_candidate.dll"
)
BASELINE_LIBRARY = (
    Path(__file__).resolve().parent.parent / "build" / "makhos_native_baseline.dll"
)
SELECTIVE_ROOT_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_selective_root_candidate.dll"
)
SHARED_TT_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_shared_tt_candidate.dll"
)
SHARED_API_CONTROL_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_shared_api_control.dll"
)
KING204_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_eval_king204_candidate.dll"
)
KING204_EDGE31_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_eval_king204_edge31_candidate.dll"
)
ROOT_ALPHA_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_root_alpha_candidate.dll"
)
QSEARCH_CAPTURE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_capture_candidate.dll"
)
QSEARCH_CAPTURE_QUIET_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_capture_quiet_candidate.dll"
)
QSEARCH_CAPTURE_QUIET_ITERATIVE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_capture_quiet_iterative_candidate.dll"
)
QSEARCH_FAST_QUIET_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_fast_quiet_scoped_candidate.dll"
)
QSEARCH_FAST_CAPTURE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_fast_capture_scoped_candidate.dll"
)
QSEARCH_FAST_KING_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_fast_king_scoped_candidate.dll"
)
QSEARCH_FAST_CAPTURE_EXISTS_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_fast_capture_exists_candidate.dll"
)
QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_qsearch_fast_capture_exists_man_geometry_candidate.dll"
)
SEARCH_KEY_CONTROL_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_search_key_control.dll"
)
SEARCH_KEY_CANDIDATE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_search_key_compat_candidate.dll"
)
SEARCH_KEY_LEGACY_INDEX_CANDIDATE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_search_key_legacy_index_candidate.dll"
)
SEARCH_KEY_LEGACY_INDEX_PGO_CANDIDATE_LIBRARY = (
    Path(__file__).resolve().parent.parent
    / "build"
    / "makhos_native_search_key_legacy_index_pgo_candidate.dll"
)


@unittest.skipUnless(LIBRARY.is_file(), "native search library is not built")
class NativeSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = NativeSearch(LIBRARY, hash_power=16)

    def test_native_evaluation_matches_python_reference(self):
        rng = random.Random(20260813)
        state = initial_state()
        for _ in range(200):
            self.assertEqual(
                self.native.evaluate(state),
                evaluate_handcrafted(state, state.turn),
            )
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )

    def test_search_returns_legal_move_and_legal_pv(self):
        state = parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2")
        result = self.native.search(
            state,
            depth=10,
            time_ms=None,
            no_progress_plies=80,
            repetition_limit=3,
        )
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.pv[0], result.move)
        for move in result.pv:
            self.assertIn(move, legal_moves(state))
            state = apply_move(state, move, validate=False)
        self.assertEqual(result.depth, 10)
        self.assertGreater(result.nodes, 0)

    def test_accepted_library_does_not_advertise_experimental_fixed_search(self):
        with NativeSearch(
            LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            self.assertFalse(native.supports_fixed_search)

    def test_engine_dispatches_large_positions_to_native_search(self):
        engine = Engine(exact_piece_limit=2, native_search=self.native)
        result = engine.search(initial_state(), SearchLimits(depth=7))
        self.assertIn(result.move, legal_moves(initial_state()))
        self.assertIsNone(engine.last_native_error)
        self.assertEqual(engine.last_search_backend, "native")
        self.assertEqual(len(result.candidates), 1)
        self.assertGreater(result.nodes, 0)

    def test_external_history_is_forwarded_to_native_search(self):
        state = initial_state()
        engine = Engine(exact_piece_limit=0, native_search=self.native)
        result = engine.search(
            state,
            SearchLimits(depth=7),
            history={state.position_key: 1},
        )
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(len(result.candidates), 1)
        self.assertIsNone(engine.last_native_error)
        self.assertEqual(engine.last_search_backend, "native")

    def test_persistent_tt_is_reused_and_can_be_cleared(self):
        with NativeSearch(LIBRARY, hash_power=16, persistent=True) as native:
            self.assertTrue(native.persistent)
            first = native.search(
                initial_state(),
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            second = native.search(
                initial_state(),
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertLess(second.nodes, first.nodes)
            native.clear()
            cleared = native.search(
                initial_state(),
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertEqual(cleared.nodes, first.nodes)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            native.search(
                initial_state(),
                depth=1,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )

    def test_repetition_dependent_search_keeps_stable_score(self):
        state = parse_position("B:BK1:RK32")
        history = {state.position_key: 2}
        with NativeSearch(LIBRARY, hash_power=16, persistent=True) as native:
            first = native.search(
                state,
                depth=10,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
                history=history,
            )
            reused = native.search(
                state,
                depth=10,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
                history=history,
            )
        self.assertEqual(reused.score, first.score)
        self.assertIn(reused.move, legal_moves(state))

    @unittest.skipUnless(BASELINE_LIBRARY.is_file(), "ABI-v2 baseline is absent")
    def test_abi_v2_baseline_uses_one_shot_compatibility_path(self):
        native = NativeSearch(BASELINE_LIBRARY, hash_power=16)
        self.assertFalse(native.persistent)
        result = native.search(
            initial_state(),
            depth=3,
            time_ms=None,
            no_progress_plies=80,
            repetition_limit=3,
        )
        self.assertIn(result.move, legal_moves(initial_state()))

    def test_production_default_keeps_accepted_one_shot_search(self):
        native = NativeSearch(LIBRARY, hash_power=16)
        self.assertFalse(native.persistent)


class NativeSearchPositionKeyCandidateTests(unittest.TestCase):
    """Compile the key contract from source instead of relying on archived DLLs."""

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        clang = Path(r"C:\Program Files\LLVM\bin\clang.exe")
        compiler = str(clang) if clang.is_file() else shutil.which("clang") or shutil.which("gcc")
        if compiler is None:
            raise unittest.SkipTest("a C compiler is required for TT identity regression")
        (root / "build").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix="tt-key-tests-", dir=root / "build"))
        cls.addClassCleanup(shutil.rmtree, build, ignore_errors=True)
        flags = ["-O2", "-std=c17", "-shared", "-DMAKHOS_NO_MAIN=1",
                 "-DMAKHOS_SEARCH_KEY_TEST_API=1"]
        if os.name != "nt":
            flags += ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.control_path = build / ("control" + suffix)
        candidate_path = build / ("strict" + suffix)
        for path, strict in ((cls.control_path, 0), (candidate_path, 1)):
            proc = subprocess.run(
                [compiler, *flags, f"-DMAKHOS_STRICT_SEARCH_POSITION_KEY={strict}",
                 str(root / "native/makhos_native.c"), "-o", str(path)],
                cwd=root, capture_output=True, text=True, check=False,
            )
            if proc.returncode:
                raise AssertionError(proc.stderr)
        cls.control = ctypes.CDLL(str(cls.control_path))
        cls.candidates = (("strict", candidate_path, ctypes.CDLL(str(candidate_path))),)
        signature = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        for library in (cls.control,) + tuple(
            library for _name, _path, library in cls.candidates
        ):
            library.makhos_search_debug_position_key.argtypes = signature
            library.makhos_search_debug_position_key.restype = ctypes.c_int

    @classmethod
    def _key(cls, library, red, black, kings, turn, clock):
        out_key = ctypes.c_uint64()
        status = library.makhos_search_debug_position_key(
            red,
            black,
            kings,
            turn,
            clock,
            ctypes.byref(out_key),
        )
        if status != 0:
            raise AssertionError(f"search-key debug hook failed ({status})")
        return int(out_key.value)

    def test_strict_key_preserves_every_clock_and_king_bit(self):
        # Every square is occupied solely to make each one-bit king mask valid;
        # this is a key-level regression, not a playable search position.
        red = 0x0000FFFF
        black = 0xFFFF0000
        base_control = self._key(self.control, red, black, 0, BLACK, 0)

        # The legacy OR salt loses clock bit 0 and king bit 0.  The strict
        # candidate must keep both fields injective before the final mixing.
        self.assertEqual(
            base_control,
            self._key(self.control, red, black, 0, BLACK, 1),
        )
        self.assertEqual(
            base_control,
            self._key(self.control, red, black, 1, BLACK, 0),
        )
        for name, _path, candidate in self.candidates:
            with self.subTest(candidate=name):
                base_candidate = self._key(candidate, red, black, 0, BLACK, 0)
                self.assertNotEqual(
                    base_candidate,
                    self._key(candidate, red, black, 0, BLACK, 1),
                )
                self.assertNotEqual(
                    base_candidate,
                    self._key(candidate, red, black, 1, BLACK, 0),
                )
                candidate_clock_keys = {
                    self._key(candidate, red, black, 0, BLACK, clock)
                    for clock in range(256)
                }
                self.assertEqual(len(candidate_clock_keys), 256)
                candidate_king_keys = {
                    self._key(candidate, red, black, 1 << square, BLACK, 0)
                    for square in range(32)
                }
                self.assertNotIn(base_candidate, candidate_king_keys)
                self.assertEqual(len(candidate_king_keys), 32)

    def test_strict_key_prevents_warmed_tt_alias_reuse(self):
        # The target Sian-Thao position is B.  In A, the same black piece on
        # square 20 is a king.  That king bit was formerly masked by the salt,
        # so A and B entered the exact same main-TT slot/key.
        state_a = parse_position("B:BM19,25,27,29,31:BK20:RM1,3,6,8,10,17")
        state_b = parse_position("B:BM19,20,25,27,29,31:RM1,3,6,8,10,17")
        search_args = dict(
            depth=8,
            time_ms=None,
            no_progress_plies=80,
            repetition_limit=None,
        )

        def snapshot(result):
            return result.move, result.score, result.depth

        def warm_then_b(library):
            with NativeSearch(library, hash_power=12, persistent=True) as warm:
                warm.search_fixed(
                    state_a,
                    **search_args,
                )
                # Make the cached-root move belong to a third position.  Any
                # A -> B difference below then comes from the retained TT,
                # not from the root-move hint.
                warm.search_fixed(
                    initial_state(),
                    depth=1,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=None,
                )
                return warm.search_fixed(
                    state_b,
                    **search_args,
                )

        def fresh_b(library):
            with NativeSearch(library, hash_power=12, persistent=True) as fresh:
                fresh.search_fixed(
                    initial_state(),
                    depth=1,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=None,
                )
                return fresh.search_fixed(
                    state_b,
                    **search_args,
                )

        for name, candidate_path, _candidate in self.candidates:
            with self.subTest(candidate=name):
                strict_fresh = fresh_b(candidate_path)
                strict_warmed = warm_then_b(candidate_path)
                self.assertEqual(snapshot(strict_warmed), snapshot(strict_fresh))
                self.assertIn(strict_warmed.move, legal_moves(state_b))

        legacy_fresh = fresh_b(self.control_path)
        legacy_warmed = warm_then_b(self.control_path)
        self.assertNotEqual(snapshot(legacy_warmed), snapshot(legacy_fresh))

    def test_strict_key_prevents_clock_alias_near_no_progress_limit(self):
        # 72 and 76 differ by an erased legacy clock bit.  Their remaining
        # quiet-move budget before the 80-ply draw is materially different.
        state_a = parse_position("R:BK16:RM6:RK10", reversible_plies=72)
        state_b = parse_position("R:BK16:RM6:RK10", reversible_plies=76)
        search_args = dict(
            depth=4,
            time_ms=None,
            no_progress_plies=80,
            repetition_limit=None,
        )

        def snapshot(result):
            return result.move, result.score, result.depth

        def warm_then_b(library):
            with NativeSearch(library, hash_power=12, persistent=True) as warm:
                warm.search_fixed(state_a, **search_args)
                warm.search_fixed(
                    initial_state(),
                    depth=1,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=None,
                )
                return warm.search_fixed(state_b, **search_args)

        def fresh_b(library):
            with NativeSearch(library, hash_power=12, persistent=True) as fresh:
                fresh.search_fixed(
                    initial_state(),
                    depth=1,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=None,
                )
                return fresh.search_fixed(state_b, **search_args)

        for name, candidate_path, _candidate in self.candidates:
            with self.subTest(candidate=name):
                strict_fresh = fresh_b(candidate_path)
                strict_warmed = warm_then_b(candidate_path)
                self.assertEqual(snapshot(strict_warmed), snapshot(strict_fresh))
                self.assertIn(strict_warmed.move, legal_moves(state_b))

        legacy_fresh = fresh_b(self.control_path)
        legacy_warmed = warm_then_b(self.control_path)
        self.assertNotEqual(snapshot(legacy_warmed), snapshot(legacy_fresh))


class NativeHashSizingTests(unittest.TestCase):
    def test_hash_megabytes_are_split_across_threads_as_a_total_budget(self):
        single_power = hash_power_for_megabytes(64, partitions=1)
        four_thread_power = hash_power_for_megabytes(64, partitions=4)

        self.assertEqual(NATIVE_TT_ENTRY_BYTES, 40)
        self.assertEqual(single_power, 20)
        self.assertEqual(four_thread_power, 18)
        self.assertEqual(hash_megabytes_for_power(single_power), 40.0)
        self.assertEqual(
            hash_megabytes_for_power(four_thread_power, partitions=4),
            40.0,
        )

    @unittest.skipUnless(LEGACY_LIBRARY.is_file(), "legacy V1 DLL is absent")
    def test_legacy_dll_layout_keeps_its_72_byte_budget(self):
        self.assertEqual(LEGACY_NATIVE_TT_ENTRY_BYTES, 72)
        self.assertEqual(native_tt_entry_bytes(LEGACY_LIBRARY), 72)
        power = hash_power_for_megabytes(
            64,
            partitions=4,
            entry_bytes=LEGACY_NATIVE_TT_ENTRY_BYTES,
        )
        self.assertEqual(power, 17)
        self.assertEqual(
            hash_megabytes_for_power(
                power,
                partitions=4,
                entry_bytes=LEGACY_NATIVE_TT_ENTRY_BYTES,
            ),
            36.0,
        )


@unittest.skipUnless(ABI4_LIBRARY.is_file(), "ABI-v4 candidate is absent")
class NativeWorkspaceTelemetryTests(unittest.TestCase):
    def test_persistent_search_reports_lazy_workspace_memory(self):
        tt_bytes = (1 << 16) * 72
        with NativeSearch(
            ABI4_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            self.assertEqual(native.abi_version, 4)
            self.assertIsNotNone(native.memory_bytes)
            self.assertGreater(native.memory_bytes, tt_bytes)
            self.assertLess(native.memory_bytes - tt_bytes, 8 * 1024 * 1024)
            result = native.search(
                initial_state(),
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertEqual(result.depth, 12)
            self.assertGreater(native.workspace_lists, 0)
            self.assertLess(native.workspace_lists, 96)
            native.clear()
            self.assertGreater(native.workspace_lists, 0)

    def test_one_shot_search_has_no_handle_telemetry(self):
        with NativeSearch(ABI4_LIBRARY, hash_power=16) as native:
            self.assertIsNone(native.memory_bytes)
            self.assertIsNone(native.workspace_lists)


@unittest.skipUnless(COMPACT_TT_LIBRARY.is_file(), "ABI-v5 candidate is absent")
class NativeCompactTTTests(unittest.TestCase):
    def test_c_and_python_agree_on_40_byte_tt_layout(self):
        self.assertEqual(native_tt_entry_bytes(COMPACT_TT_LIBRARY), 40)
        with NativeSearch(COMPACT_TT_LIBRARY, hash_power=16) as native:
            self.assertEqual(native.abi_version, 5)
            self.assertEqual(native.tt_entry_bytes, 40)
            self.assertEqual(native.allocated_hash_mb, 2.5)

    def test_compact_tt_reduces_persistent_allocation(self):
        with NativeSearch(
            COMPACT_TT_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            before = native.memory_bytes
            result = native.search(
                initial_state(),
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertEqual(result.depth, 12)
            self.assertLess(before, 3 * 1024 * 1024)
            self.assertGreater(native.workspace_lists, 0)


@unittest.skipUnless(
    PREORDER_LIBRARY.is_file() and PREORDER_CONTROL_LIBRARY.is_file(),
    "preorder candidate/control pair is absent",
)
class NativePrecomputedOrderingTests(unittest.TestCase):
    def test_precomputed_weights_preserve_fixed_depth_search(self):
        state = parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2")
        with NativeSearch(
            PREORDER_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate, NativeSearch(
            PREORDER_CONTROL_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as accepted:
            candidate_result = candidate.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            accepted_result = accepted.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertEqual(candidate_result.move, accepted_result.move)
            self.assertEqual(candidate_result.score, accepted_result.score)
            self.assertEqual(candidate_result.nodes, accepted_result.nodes)
            self.assertLessEqual(
                candidate.memory_bytes - accepted.memory_bytes,
                20 * 1024,
            )


@unittest.skipUnless(
    EARLY_TT_LIBRARY.is_file() and EARLY_TT_CONTROL_LIBRARY.is_file(),
    "early-TT candidate/control pair is absent",
)
class NativeEarlyTTCutoffTests(unittest.TestCase):
    def test_early_cutoff_preserves_fixed_depth_search(self):
        state = parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2")
        with NativeSearch(
            EARLY_TT_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate, NativeSearch(
            EARLY_TT_CONTROL_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as accepted:
            candidate_result = candidate.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            accepted_result = accepted.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertEqual(candidate_result.move, accepted_result.move)
            self.assertEqual(candidate_result.score, accepted_result.score)
            self.assertEqual(candidate_result.nodes, accepted_result.nodes)
            self.assertEqual(candidate.memory_bytes, accepted.memory_bytes)


@unittest.skipUnless(
    PACKED_PV_LIBRARY.is_file() and PRE_PACKED_PV_LIBRARY.is_file(),
    "packed-PV candidate/control pair is absent",
)
class NativePackedPVTests(unittest.TestCase):
    def test_packed_pv_preserves_search_and_reduces_context(self):
        state = parse_position("B:BM21,22,25,27:BK30:RM5,7,8,10:RK2")
        with NativeSearch(
            PACKED_PV_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate, NativeSearch(
            PRE_PACKED_PV_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as accepted:
            self.assertEqual(
                accepted.memory_bytes - candidate.memory_bytes,
                96 * 96 * (52 - 36),
            )
            candidate_result = candidate.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            accepted_result = accepted.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertEqual(candidate_result.move, accepted_result.move)
            self.assertEqual(candidate_result.score, accepted_result.score)
            self.assertEqual(candidate_result.nodes, accepted_result.nodes)
            self.assertEqual(candidate_result.pv, accepted_result.pv)


@unittest.skipUnless(TELEMETRY_LIBRARY.is_file(), "telemetry build is absent")
class NativeSearchTelemetryTests(unittest.TestCase):
    def test_persistent_search_reports_consistent_counters(self):
        state = initial_state()
        with NativeSearch(
            TELEMETRY_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            result = native.search(
                state,
                depth=10,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            telemetry = result.telemetry
            self.assertEqual(native.abi_version, 6)
            self.assertIsInstance(telemetry, NativeSearchTelemetry)
            self.assertEqual(telemetry, native.telemetry)
            self.assertLessEqual(telemetry.qnodes, result.nodes)
            self.assertGreater(telemetry.movegen_calls, 0)
            self.assertGreaterEqual(
                telemetry.moves_generated, telemetry.movegen_calls
            )
            self.assertLessEqual(telemetry.tt_hits, telemetry.tt_probes)
            self.assertLessEqual(telemetry.tt_cutoffs, telemetry.tt_hits)
            self.assertLessEqual(
                telemetry.beta_cutoff_first, telemetry.beta_cutoffs
            )
            self.assertLessEqual(
                telemetry.lmr_researches, telemetry.pvs_researches
            )
            native.clear()
            cleared = native.telemetry
            self.assertTrue(
                all(
                    getattr(cleared, name) == 0
                    for name in NativeSearchTelemetry.__dataclass_fields__
                )
            )

    def test_one_shot_search_has_no_handle_telemetry(self):
        with NativeSearch(TELEMETRY_LIBRARY, hash_power=16) as native:
            result = native.search(
                initial_state(),
                depth=4,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
        self.assertIsNone(result.telemetry)

    def test_parallel_search_aggregates_worker_counters(self):
        with ParallelNativeSearch(
            TELEMETRY_LIBRARY,
            threads=2,
            hash_mb=16,
        ) as native:
            result = native.search(
                initial_state(),
                depth=5,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
        self.assertIsInstance(result.telemetry, NativeSearchTelemetry)
        self.assertGreater(result.telemetry.movegen_calls, 0)
        self.assertGreater(result.telemetry.tt_probes, 0)


@unittest.skipUnless(IIR_CENSUS_LIBRARY.is_file(), "IIR census build is absent")
class NativeIirCensusTests(unittest.TestCase):
    def test_census_reports_consistent_eligibility_partitions(self):
        with NativeSearch(
            IIR_CENSUS_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            result = native.search(
                initial_state(),
                depth=9,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            census = native.iir_census
            self.assertGreater(result.nodes, 0)
            self.assertTrue(native.supports_iir_census)
            self.assertIsInstance(census, NativeIirCensusTelemetry)
            self.assertGreater(census.eligible_nodes, 0)
            self.assertGreaterEqual(census.post_tt_nodes, census.eligible_nodes)
            self.assertEqual(
                census.eligible_nodes,
                census.with_tt_move + census.without_tt_move,
            )
            self.assertEqual(
                census.eligible_nodes,
                census.full_window_nodes + census.null_window_nodes,
            )
            self.assertEqual(
                census.eligible_nodes,
                census.capture_nodes + census.quiet_nodes,
            )
            self.assertEqual(
                census.without_tt_move,
                census.missing_full_window + census.missing_null_window,
            )
            self.assertEqual(
                census.without_tt_move,
                census.missing_capture + census.missing_quiet,
            )
            self.assertEqual(
                census.without_tt_move,
                census.missing_depth4
                + census.missing_depth5
                + census.missing_depth6_plus,
            )
            self.assertGreaterEqual(
                census.missing_depth_sum,
                4 * census.without_tt_move,
            )
            native.clear()
            cleared = native.iir_census
            self.assertTrue(
                all(
                    getattr(cleared, name) == 0
                    for name in NativeIirCensusTelemetry.__dataclass_fields__
                )
            )


@unittest.skipUnless(
    REPETITION_CENSUS_LIBRARY.is_file(), "repetition census build is absent"
)
class NativeRepetitionCensusTests(unittest.TestCase):
    def test_census_reports_consistent_scan_partitions(self):
        state = initial_state()
        history = {(state.board, state.turn): 1}
        with NativeSearch(
            REPETITION_CENSUS_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            result = native.search(
                state,
                depth=9,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
                history=history,
            )
            census = native.repetition_census
            self.assertGreater(result.nodes, 0)
            self.assertTrue(native.supports_repetition_census)
            self.assertIsInstance(census, NativeRepetitionCensusTelemetry)
            self.assertGreater(census.calls, 0)
            self.assertGreater(census.normal_calls, 0)
            self.assertGreater(census.qsearch_calls, 0)
            self.assertEqual(
                census.calls,
                census.normal_calls + census.qsearch_calls,
            )
            self.assertEqual(
                census.calls,
                census.span_zero
                + census.span_1_4
                + census.span_5_16
                + census.span_17_plus,
            )
            self.assertEqual(census.initial_linear_calls, census.calls)
            self.assertEqual(census.initial_hash_calls, 0)
            self.assertGreaterEqual(census.initial_linear_entries, census.calls)
            self.assertGreaterEqual(census.line_entries, census.line_matches)
            native.clear()
            cleared = native.repetition_census
            self.assertTrue(
                all(
                    getattr(cleared, name) == 0
                    for name in NativeRepetitionCensusTelemetry.__dataclass_fields__
                )
            )


@unittest.skipUnless(
    SMALL_HISTORY_HASH_CONTROL_LIBRARY.is_file()
    and SMALL_HISTORY_HASH_CANDIDATE_LIBRARY.is_file(),
    "small-history hash candidate/control builds are absent",
)
class NativeSmallHistoryHashTests(unittest.TestCase):
    CONTROL_LIBRARY = SMALL_HISTORY_HASH_CONTROL_LIBRARY
    CANDIDATE_LIBRARY = SMALL_HISTORY_HASH_CANDIDATE_LIBRARY

    @staticmethod
    def _result_key(result):
        return (
            result.move,
            result.score,
            result.depth,
            result.nodes,
            result.pv,
        )

    def _compare_search(self, state, history, *, depth=8, no_progress_plies=80):
        results = []
        for library in (
            self.CONTROL_LIBRARY,
            self.CANDIDATE_LIBRARY,
        ):
            with NativeSearch(library, hash_power=16, persistent=True) as native:
                results.append(
                    native.search(
                        state,
                        depth=depth,
                        time_ms=None,
                        no_progress_plies=no_progress_plies,
                        repetition_limit=3,
                        history=history,
                    )
                )
        self.assertEqual(self._result_key(results[0]), self._result_key(results[1]))
        return results

    @staticmethod
    def _history_fixture(size):
        rng = random.Random(20260943 + size)
        state = initial_state()
        history = {}
        while len(history) < size:
            history.setdefault(state.position_key, 1)
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )
        root_key = next(reversed(history))
        board, turn = root_key
        return State(board, turn), history

    def test_one_two_thirty_one_and_thirty_two_entry_histories_match(self):
        for size in (1, 2, 31, 32):
            with self.subTest(size=size):
                state, history = self._history_fixture(size)
                self._compare_search(state, history)

    def test_root_and_in_line_threefold_cases_match(self):
        state = parse_position("B:BK1:RK32", reversible_plies=12)
        self._compare_search(state, {state.position_key: 3}, depth=10)
        self._compare_search(state, {state.position_key: 1}, depth=12)

    def test_reversible_clock_79_and_80_boundaries_match(self):
        state_79 = parse_position("B:BK1:RK32", reversible_plies=79)
        self._compare_search(state_79, {state_79.position_key: 1}, depth=8)
        state_80 = parse_position("B:BK1:RK32", reversible_plies=80)
        errors = []
        for library in (
            self.CONTROL_LIBRARY,
            self.CANDIDATE_LIBRARY,
        ):
            with NativeSearch(library, hash_power=16, persistent=True) as native:
                with self.assertRaises(RuntimeError) as caught:
                    native.search(
                        state_80,
                        depth=8,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                        history={state_80.position_key: 1},
                    )
                errors.append(str(caught.exception))
        self.assertEqual(errors[0], errors[1])

    def _raw_duplicate_search(self, library, counts):
        state = parse_position("B:BK1:RK32", reversible_plies=12)
        red, black, kings = _bitboards(state)
        entries = (_HistoryEntry * len(counts))(
            *(
                _HistoryEntry(
                    red,
                    black,
                    kings,
                    state.turn,
                    count,
                    (ctypes.c_uint8 * 2)(0, 0),
                )
                for count in counts
            )
        )
        raw = _SearchResult()
        with NativeSearch(library, hash_power=16, persistent=True) as native:
            status = native._library.makhos_search_run(
                native._require_handle(),
                red,
                black,
                kings,
                state.turn,
                state.reversible_plies,
                10,
                0,
                80,
                3,
                entries,
                len(counts),
                ctypes.byref(raw),
            )
        self.assertEqual(status, 0)
        return NativeSearch._decode_native_result(raw, None)

    def test_duplicate_history_keeps_first_entry_semantics(self):
        for counts in ((3, 1), (1, 3)):
            with self.subTest(counts=counts):
                control = self._raw_duplicate_search(
                    self.CONTROL_LIBRARY, counts
                )
                candidate = self._raw_duplicate_search(
                    self.CANDIDATE_LIBRARY, counts
                )
                self.assertEqual(
                    self._result_key(control), self._result_key(candidate)
                )


@unittest.skipUnless(
    CURRENT_LINE_SKIP_CONTROL_LIBRARY.is_file()
    and CURRENT_LINE_SKIP_CANDIDATE_LIBRARY.is_file(),
    "current-line skip candidate/control builds are absent",
)
class NativeCurrentLineSkipTests(NativeSmallHistoryHashTests):
    CONTROL_LIBRARY = CURRENT_LINE_SKIP_CONTROL_LIBRARY
    CANDIDATE_LIBRARY = CURRENT_LINE_SKIP_CANDIDATE_LIBRARY


class ParallelNativeConfigurationTests(unittest.TestCase):
    def test_rejects_threads_above_supported_max(self):
        with self.assertRaisesRegex(ValueError, r"2\.\.12"):
            ParallelNativeSearch(
                Path("unused-native-library.dll"),
                threads=13,
                hash_mb=16,
            )


@unittest.skipUnless(LIBRARY.is_file(), "native search library is not built")
class ParallelNativeSearchTests(unittest.TestCase):
    def test_two_threads_complete_every_root_move_at_one_common_depth(self):
        state = initial_state()
        with ParallelNativeSearch(
            LIBRARY,
            threads=2,
            hash_mb=16,
        ) as native:
            result = native.search(
                state,
                depth=6,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )

        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.depth, 6)
        self.assertEqual(result.pv[0], result.move)
        self.assertGreater(result.nodes, 0)
        self.assertEqual(
            {item.move for item in result.root_moves},
            set(legal_moves(state)),
        )
        self.assertTrue(all(item.depth == result.depth for item in result.root_moves))
        self.assertEqual(result.score, max(item.score for item in result.root_moves))
        self.assertEqual(result.common_depth, result.depth)
        self.assertFalse(result.selective_root)


@unittest.skipUnless(
    SELECTIVE_ROOT_LIBRARY.is_file(),
    "selective-root candidate library is absent",
)
class SelectiveRootSearchTests(unittest.TestCase):
    def test_fixed_search_matches_completed_iterative_depth(self):
        state = parse_position(
            "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17",
            reversible_plies=2,
        )
        with NativeSearch(
            SELECTIVE_ROOT_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as native:
            self.assertTrue(native.supports_fixed_search)
            iterative = native.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=None,
            )
            fixed = native.search_fixed(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=None,
            )

        self.assertEqual(fixed.move, iterative.move)
        self.assertEqual(fixed.score, iterative.score)
        self.assertEqual(fixed.depth, 12)
        self.assertEqual(fixed.common_depth, 12)
        self.assertEqual(fixed.pv[0], fixed.move)

    def test_selective_search_reports_common_and_deeper_candidate_depths(self):
        state = initial_state()
        with ParallelNativeSearch(
            SELECTIVE_ROOT_LIBRARY,
            threads=2,
            hash_mb=16,
            selective_root=True,
            selective_reserve=0.60,
            selective_candidates=2,
            selective_margin=1_000_000,
        ) as native:
            result = native.search(
                state,
                depth=40,
                time_ms=200,
                no_progress_plies=80,
                repetition_limit=3,
            )

        self.assertIn(result.move, legal_moves(state))
        self.assertTrue(result.selective_root)
        self.assertIsNotNone(result.common_depth)
        self.assertGreater(result.depth, result.common_depth)
        self.assertEqual(
            {item.move for item in result.root_moves},
            set(legal_moves(state)),
        )
        self.assertTrue(
            all(item.depth >= result.common_depth for item in result.root_moves)
        )
        self.assertEqual(
            max(item.depth for item in result.root_moves),
            result.depth,
        )

    def test_incomplete_selective_layer_falls_back_to_common_depth(self):
        state = initial_state()
        with ParallelNativeSearch(
            SELECTIVE_ROOT_LIBRARY,
            threads=2,
            hash_mb=16,
            selective_root=True,
            selective_reserve=0.60,
            selective_candidates=2,
            selective_margin=1_000_000,
        ) as native:
            patches = [
                mock.patch.object(
                    worker,
                    "search_fixed",
                    side_effect=TimeoutError("forced test timeout"),
                )
                for worker in native._workers
            ]
            for patch in patches:
                patch.start()
            try:
                result = native.search(
                    state,
                    depth=40,
                    time_ms=100,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
            finally:
                for patch in reversed(patches):
                    patch.stop()

        self.assertFalse(result.selective_root)
        self.assertEqual(result.depth, result.common_depth)
        self.assertTrue(
            all(item.depth == result.common_depth for item in result.root_moves)
        )


@unittest.skipUnless(
    SHARED_TT_LIBRARY.is_file() and SHARED_API_CONTROL_LIBRARY.is_file(),
    "shared-TT candidate libraries are absent",
)
class SharedTTSearchTests(unittest.TestCase):
    def test_single_context_shared_build_preserves_control_search(self):
        state = parse_position(
            "B:BM19,20,25,27,29,31:RM1,3,6,8,10,17",
            reversible_plies=2,
        )
        with NativeSearch(
            SHARED_TT_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate, NativeSearch(
            SHARED_API_CONTROL_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as control:
            self.assertTrue(candidate.supports_shared_tt)
            self.assertFalse(control.supports_shared_tt)
            candidate_result = candidate.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=None,
            )
            control_result = control.search(
                state,
                depth=12,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=None,
            )

        self.assertEqual(candidate_result.move, control_result.move)
        self.assertEqual(candidate_result.score, control_result.score)
        self.assertEqual(candidate_result.nodes, control_result.nodes)
        self.assertEqual(candidate_result.pv, control_result.pv)

    def test_parallel_workers_share_one_larger_tt_and_return_legal_search(self):
        state = initial_state()
        with ParallelNativeSearch(
            SHARED_TT_LIBRARY,
            threads=4,
            hash_mb=64,
            shared_tt=True,
        ) as shared, ParallelNativeSearch(
            SHARED_API_CONTROL_LIBRARY,
            threads=4,
            hash_mb=64,
        ) as partitioned:
            self.assertGreater(shared.hash_power, partitioned.hash_power)
            self.assertAlmostEqual(
                shared.allocated_hash_mb,
                partitioned.allocated_hash_mb,
            )
            result = shared.search(
                state,
                depth=7,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            self.assertIsNotNone(shared.memory_bytes)
            shared.clear()

        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.depth, 7)
        self.assertEqual(result.common_depth, 7)
        self.assertEqual(
            {item.move for item in result.root_moves},
            set(legal_moves(state)),
        )


@unittest.skipUnless(KING204_LIBRARY.is_file(), "king-value candidate is absent")
class NativeKingValueCandidateTests(unittest.TestCase):
    def test_native_candidate_matches_python_taper_on_random_play(self):
        rng = random.Random(20260911)
        state = initial_state()
        with NativeSearch(KING204_LIBRARY, hash_power=16) as native:
            for _ in range(1000):
                self.assertEqual(
                    native.evaluate(state),
                    evaluate_endgame_king_value(state, state.turn),
                )
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(
    KING204_EDGE31_LIBRARY.is_file(), "king-value/edge candidate is absent"
)
class NativeKingValueEdgeCandidateTests(unittest.TestCase):
    def test_native_candidate_matches_python_taper_on_random_play(self):
        rng = random.Random(20260918)
        state = initial_state()
        with NativeSearch(KING204_EDGE31_LIBRARY, hash_power=16) as native:
            for _ in range(1000):
                self.assertEqual(
                    native.evaluate(state),
                    evaluate_endgame_king_value(
                        state, state.turn, king_value=204, king_edge=31
                    ),
                )
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(ROOT_ALPHA_LIBRARY.is_file(), "root-alpha candidate is absent")
class NativeRootAlphaCandidateTests(unittest.TestCase):
    def test_full_window_is_deterministic_and_legal_on_random_play(self):
        rng = random.Random(20260920)
        state = initial_state()
        for _ in range(32):
            history = {state.position_key: 1}
            results = []
            for _repeat in range(2):
                with NativeSearch(
                    ROOT_ALPHA_LIBRARY, hash_power=16, persistent=True
                ) as window_search:
                    results.append(window_search.search_window(
                        state,
                        depth=7,
                        alpha=-2_000_000,
                        beta=2_000_000,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                        history=history,
                    ))
            self.assertEqual(results[0].move, results[1].move)
            self.assertEqual(results[0].score, results[1].score)
            self.assertEqual(results[0].depth, 7)
            self.assertIn(results[0].move, legal_moves(state))
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )

    def test_parallel_root_alpha_returns_one_complete_legal_layer(self):
        state = initial_state()
        with ParallelNativeSearch(
            ROOT_ALPHA_LIBRARY,
            threads=12,
            hash_mb=64,
            root_alpha=True,
            root_alpha_margin=32,
            root_alpha_min_depth=8,
        ) as native:
            result = native.search(
                state,
                depth=10,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
                history={state.position_key: 1},
            )
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.depth, 10)
        self.assertEqual(result.common_depth, 10)
        self.assertEqual(
            {item.move for item in result.root_moves},
            set(legal_moves(state)),
        )
        self.assertEqual({item.depth for item in result.root_moves}, {10})


@unittest.skipUnless(
    QSEARCH_CAPTURE_LIBRARY.is_file(), "qsearch capture candidate is absent"
)
class NativeQSearchCaptureCandidateTests(unittest.TestCase):
    def test_capture_only_qsearch_matches_accepted_fixed_depth(self):
        rng = random.Random(20260923)
        state = initial_state()
        for _ in range(16):
            with NativeSearch(
                QSEARCH_CAPTURE_LIBRARY, hash_power=16, persistent=True
            ) as candidate, NativeSearch(
                LIBRARY, hash_power=16, persistent=True
            ) as baseline:
                candidate_result = candidate.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history={state.position_key: 1},
                )
                baseline_result = baseline.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history={state.position_key: 1},
                )
            self.assertEqual(candidate_result.move, baseline_result.move)
            self.assertEqual(candidate_result.score, baseline_result.score)
            self.assertEqual(candidate_result.nodes, baseline_result.nodes)
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )


@unittest.skipUnless(
    QSEARCH_CAPTURE_QUIET_LIBRARY.is_file(),
    "qsearch capture quiet candidate is absent",
)
class NativeQSearchCaptureQuietCandidateTests(unittest.TestCase):
    def test_quiet_leaf_check_matches_accepted_fixed_depth(self):
        rng = random.Random(20260928)
        state = initial_state()
        for _ in range(16):
            with NativeSearch(
                QSEARCH_CAPTURE_QUIET_LIBRARY, hash_power=16, persistent=True
            ) as candidate, NativeSearch(
                LIBRARY, hash_power=16, persistent=True
            ) as baseline:
                candidate_result = candidate.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history={state.position_key: 1},
                )
                baseline_result = baseline.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history={state.position_key: 1},
                )
            self.assertEqual(candidate_result.move, baseline_result.move)
            self.assertEqual(candidate_result.score, baseline_result.score)
            self.assertEqual(candidate_result.nodes, baseline_result.nodes)
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )


@unittest.skipUnless(
    QSEARCH_CAPTURE_QUIET_ITERATIVE_LIBRARY.is_file(),
    "qsearch iterative candidate is absent",
)
class NativeQSearchCaptureQuietIterativeCandidateTests(unittest.TestCase):
    def test_iterative_api_matches_accepted_fixed_depth(self):
        rng = random.Random(20260929)
        state = initial_state()
        with NativeSearch(
            QSEARCH_CAPTURE_QUIET_ITERATIVE_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate:
            self.assertFalse(candidate.supports_fixed_search)
            self.assertFalse(candidate.supports_window_search)
            for _ in range(16):
                candidate.clear()
                with NativeSearch(
                    LIBRARY, hash_power=16, persistent=True
                ) as baseline:
                    candidate_result = candidate.search(
                        state,
                        depth=8,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                        history={state.position_key: 1},
                    )
                    baseline_result = baseline.search(
                        state,
                        depth=8,
                        time_ms=None,
                        no_progress_plies=80,
                        repetition_limit=3,
                        history={state.position_key: 1},
                    )
                self.assertEqual(candidate_result.move, baseline_result.move)
                self.assertEqual(candidate_result.score, baseline_result.score)
                self.assertEqual(candidate_result.nodes, baseline_result.nodes)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(
    QSEARCH_FAST_QUIET_LIBRARY.is_file(),
    "fast qsearch quiet-mobility candidate is absent",
)
class NativeQSearchFastQuietCandidateTests(unittest.TestCase):
    def test_precomputed_quiet_mobility_matches_iterative_candidate(self):
        rng = random.Random(20261002)
        state = initial_state()
        with NativeSearch(
            QSEARCH_FAST_QUIET_LIBRARY, hash_power=16, persistent=True
        ) as candidate, NativeSearch(
            QSEARCH_CAPTURE_QUIET_ITERATIVE_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as baseline:
            self.assertFalse(candidate.supports_fixed_search)
            self.assertFalse(candidate.supports_window_search)
            for _ in range(32):
                history = {state.position_key: 1}
                candidate.clear()
                baseline.clear()
                candidate_result = candidate.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                baseline_result = baseline.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                self.assertEqual(candidate_result.move, baseline_result.move)
                self.assertEqual(candidate_result.score, baseline_result.score)
                self.assertEqual(candidate_result.nodes, baseline_result.nodes)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(
    QSEARCH_FAST_CAPTURE_LIBRARY.is_file(),
    "fast qsearch capture-geometry candidate is absent",
)
class NativeQSearchFastCaptureCandidateTests(unittest.TestCase):
    def test_precomputed_man_capture_geometry_matches_fast_quiet_candidate(self):
        rng = random.Random(20261004)
        state = initial_state()
        with NativeSearch(
            QSEARCH_FAST_CAPTURE_LIBRARY, hash_power=16, persistent=True
        ) as candidate, NativeSearch(
            QSEARCH_FAST_QUIET_LIBRARY, hash_power=16, persistent=True
        ) as baseline:
            self.assertFalse(candidate.supports_fixed_search)
            self.assertFalse(candidate.supports_window_search)
            for _ in range(32):
                history = {state.position_key: 1}
                candidate.clear()
                baseline.clear()
                candidate_result = candidate.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                baseline_result = baseline.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                self.assertEqual(candidate_result.move, baseline_result.move)
                self.assertEqual(candidate_result.score, baseline_result.score)
                self.assertEqual(candidate_result.nodes, baseline_result.nodes)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(
    QSEARCH_FAST_CAPTURE_EXISTS_LIBRARY.is_file(),
    "qsearch capture-existence candidate is absent",
)
class NativeQSearchCaptureExistsCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = ctypes.CDLL(str(QSEARCH_FAST_CAPTURE_EXISTS_LIBRARY))
        cls.library.makhos_capture_exists.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        cls.library.makhos_capture_exists.restype = ctypes.c_int
        cls.library.makhos_qsearch_capture_moves.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_LegacyNativeMoveLayout),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        cls.library.makhos_qsearch_capture_moves.restype = ctypes.c_int

    @classmethod
    def capture_exists(cls, state):
        red, black, kings = _bitboards(state)
        exists = ctypes.c_int()
        status = cls.library.makhos_capture_exists(
            red,
            black,
            kings,
            state.turn,
            state.reversible_plies,
            ctypes.byref(exists),
        )
        if status != 0:
            raise AssertionError(f"native capture-existence status {status}")
        return bool(exists.value)

    @classmethod
    def qsearch_capture_moves(cls, state):
        storage = (_LegacyNativeMoveLayout * 4096)()
        count = ctypes.c_uint32()
        red, black, kings = _bitboards(state)
        status = cls.library.makhos_qsearch_capture_moves(
            red,
            black,
            kings,
            state.turn,
            state.reversible_plies,
            storage,
            len(storage),
            ctypes.byref(count),
        )
        if status != 0:
            raise AssertionError(f"native qsearch capture status {status}")
        return tuple(storage[index] for index in range(count.value))

    @staticmethod
    def _native_capture_key(move):
        path = tuple(move.path[index] for index in range(move.path_len))
        captured = tuple(
            move.captured[index] for index in range(move.capture_count)
        )
        return (
            path,
            captured,
            bool(move.promotes),
            move.next.red,
            move.next.black,
            move.next.kings,
            move.next.turn,
            move.next.reversible_plies,
        )

    @staticmethod
    def _python_capture_key(state, move):
        child = apply_move(state, move, validate=False)
        red, black, kings = _bitboards(child)
        return (
            move.path,
            move.captures,
            move.promotes,
            red,
            black,
            kings,
            child.turn,
            child.reversible_plies,
        )

    @staticmethod
    def _random_dense_state(rng):
        board = [EMPTY] * 32
        squares = rng.sample(range(32), rng.randint(4, 16))
        red_count = rng.randint(1, len(squares) - 1)
        for index, square in enumerate(squares):
            player = RED if index < red_count else BLACK
            must_be_king = (
                (player == RED and square >= 28)
                or (player == BLACK and square < 4)
            )
            king = must_be_king or rng.random() < 0.55
            if player == RED:
                board[square] = RED_KING if king else RED_MAN
            else:
                board[square] = BLACK_KING if king else BLACK_MAN
        return State(
            tuple(board),
            rng.choice((RED, BLACK)),
            reversible_plies=rng.randrange(80),
        )

    def test_capture_existence_matches_python_legal_moves(self):
        fixture_positions = [
            "B:BK1,4,7,10,14:RK18,21,25,28,31",
            "B:BM6,11,16:BK13,20,29:RM5,9,18:RK23,27",
            "B:BK3,8,15,19:RM4,12,26:RK22,30",
            "B:BM5,9,14:BK17,24:RM8,13:RK20,28,31",
            "B:BK6,10,18,27:RM2,14,21:RK25,30",
        ]
        states = [parse_position(value) for value in fixture_positions]
        rng = random.Random(20261008)
        state = initial_state()
        for _ in range(500):
            states.append(state)
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )

        for state in states:
            moves = legal_moves(state)
            expected = bool(moves and moves[0].captures)
            self.assertEqual(self.capture_exists(state), expected)

    def test_qsearch_capture_moves_match_python_moves_and_children(self):
        fixture_positions = [
            "B:BK1,4,7,10,14:RK18,21,25,28,31",
            "B:BM6,11,16:BK13,20,29:RM5,9,18:RK23,27",
            "B:BK3,8,15,19:RM4,12,26:RK22,30",
            "B:BM5,9,14:BK17,24:RM8,13:RK20,28,31",
            "B:BK6,10,18,27:RM2,14,21:RK25,30",
        ]
        states = [parse_position(value) for value in fixture_positions]
        rng = random.Random(20261010)
        states.extend(self._random_dense_state(rng) for _ in range(500))

        for state in states:
            expected = tuple(
                self._python_capture_key(state, move)
                for move in legal_moves(state)
                if move.captures
            )
            actual = tuple(
                self._native_capture_key(move)
                for move in self.qsearch_capture_moves(state)
            )
            self.assertEqual(sorted(actual), sorted(expected))

    def test_capture_existence_candidate_matches_fast_king_search(self):
        rng = random.Random(20261009)
        state = initial_state()
        with NativeSearch(
            QSEARCH_FAST_CAPTURE_EXISTS_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate, NativeSearch(
            QSEARCH_FAST_KING_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as baseline:
            for _ in range(32):
                if not legal_moves(state):
                    state = initial_state()
                history = {state.position_key: 1}
                candidate.clear()
                baseline.clear()
                candidate_result = candidate.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                baseline_result = baseline.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                self.assertEqual(candidate_result.move, baseline_result.move)
                self.assertEqual(candidate_result.score, baseline_result.score)
                self.assertEqual(candidate_result.nodes, baseline_result.nodes)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(
    QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY_LIBRARY.is_file(),
    "qsearch fast capture-existence man-geometry candidate is absent",
)
class NativeQSearchFastCaptureExistsManGeometryCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = ctypes.CDLL(
            str(QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY_LIBRARY)
        )
        cls.library.makhos_qsearch_fast_capture_exists.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        cls.library.makhos_qsearch_fast_capture_exists.restype = ctypes.c_int

    @classmethod
    def qsearch_fast_capture_exists(cls, state):
        red, black, kings = _bitboards(state)
        exists = ctypes.c_int()
        status = cls.library.makhos_qsearch_fast_capture_exists(
            red,
            black,
            kings,
            state.turn,
            state.reversible_plies,
            ctypes.byref(exists),
        )
        if status != 0:
            raise AssertionError(f"fast capture-existence status {status}")
        return bool(exists.value)

    def test_fast_man_capture_existence_matches_python(self):
        fixture_positions = [
            "B:BK1,4,7,10,14:RK18,21,25,28,31",
            "B:BM6,11,16:BK13,20,29:RM5,9,18:RK23,27",
            "B:BK3,8,15,19:RM4,12,26:RK22,30",
            "B:BM5,9,14:BK17,24:RM8,13:RK20,28,31",
            "B:BK6,10,18,27:RM2,14,21:RK25,30",
        ]
        states = [parse_position(value) for value in fixture_positions]
        rng = random.Random(20261014)
        state = initial_state()
        for _ in range(500):
            states.append(state)
            moves = legal_moves(state)
            state = (
                apply_move(state, rng.choice(moves), validate=False)
                if moves
                else initial_state()
            )
        states.extend(
            NativeQSearchCaptureExistsCandidateTests._random_dense_state(rng)
            for _ in range(500)
        )

        for state in states:
            moves = legal_moves(state)
            expected = bool(moves and moves[0].captures)
            self.assertEqual(self.qsearch_fast_capture_exists(state), expected)

    def test_fast_man_capture_existence_search_matches_control(self):
        rng = random.Random(20261015)
        state = initial_state()
        with NativeSearch(
            QSEARCH_FAST_CAPTURE_EXISTS_MAN_GEOMETRY_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as candidate, NativeSearch(
            QSEARCH_FAST_CAPTURE_EXISTS_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as control:
            for _ in range(32):
                if not legal_moves(state):
                    state = initial_state()
                history = {state.position_key: 1}
                candidate.clear()
                control.clear()
                candidate_result = candidate.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                control_result = control.search(
                    state,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                self.assertEqual(candidate_result.move, control_result.move)
                self.assertEqual(candidate_result.score, control_result.score)
                self.assertEqual(candidate_result.nodes, control_result.nodes)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )


@unittest.skipUnless(
    QSEARCH_FAST_KING_LIBRARY.is_file(),
    "fast qsearch king-capture candidate is absent",
)
class NativeQSearchFastKingCandidateTests(unittest.TestCase):
    def test_precomputed_king_capture_geometry_matches_fast_capture_candidate(self):
        fixture_positions = [
            "B:BK1,4,7,10,14:RK18,21,25,28,31",
            "B:BM6,11,16:BK13,20,29:RM5,9,18:RK23,27",
            "B:BK3,8,15,19:RM4,12,26:RK22,30",
            "B:BM5,9,14:BK17,24:RM8,13:RK20,28,31",
            "B:BK6,10,18,27:RM2,14,21:RK25,30",
        ]
        rng = random.Random(20261006)
        state = initial_state()
        with NativeSearch(
            QSEARCH_FAST_KING_LIBRARY, hash_power=16, persistent=True
        ) as candidate, NativeSearch(
            QSEARCH_FAST_CAPTURE_LIBRARY,
            hash_power=16,
            persistent=True,
        ) as baseline:
            self.assertFalse(candidate.supports_fixed_search)
            self.assertFalse(candidate.supports_window_search)
            def compare(position):
                history = {position.position_key: 1}
                candidate.clear()
                baseline.clear()
                candidate_result = candidate.search(
                    position,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                baseline_result = baseline.search(
                    position,
                    depth=8,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                    history=history,
                )
                self.assertEqual(candidate_result.move, baseline_result.move)
                self.assertEqual(candidate_result.score, baseline_result.score)
                self.assertEqual(candidate_result.nodes, baseline_result.nodes)

            for value in fixture_positions:
                compare(parse_position(value))
            for _ in range(32):
                compare(state)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state()
                )



if __name__ == "__main__":
    unittest.main()
