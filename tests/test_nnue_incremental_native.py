import ctypes
import json
from pathlib import Path
import random
import subprocess
import unittest

from makhos.core import (
    BLACK,
    RED,
    State,
    apply_move,
    initial_state,
    legal_moves,
    parse_position,
    state_from_pieces,
    BLACK_MAN,
    RED_MAN,
)
from makhos.nnue_features import (
    both_perspective_feature_deltas,
    perspective_active_features,
)
from scratch import nnue_quantized_export as exporter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "makhos_nnue_incremental.c"
LIBRARY = ROOT / "build" / "makhos_nnue_incremental_test.dll"
COMPILER = Path(r"C:\Program Files\LLVM\bin\clang.exe")
MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
CONTRACT = (
    ROOT / "build" / "nnue_phase1_evidence" / "quantization_contract_v2.json"
)
OUTPUT_DENOMINATOR = 127 * 192


def configure_library(library):
    library.makhos_nnue_scalar_last_error.argtypes = []
    library.makhos_nnue_scalar_last_error.restype = ctypes.c_char_p
    library.makhos_nnue_incremental_model_bytes.argtypes = []
    library.makhos_nnue_incremental_model_bytes.restype = ctypes.c_size_t
    library.makhos_nnue_incremental_accumulator_bytes.argtypes = []
    library.makhos_nnue_incremental_accumulator_bytes.restype = ctypes.c_size_t
    library.makhos_nnue_incremental_load.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint8),
    ]
    library.makhos_nnue_incremental_load.restype = ctypes.c_void_p
    library.makhos_nnue_incremental_free_model.argtypes = [ctypes.c_void_p]
    library.makhos_nnue_incremental_free_model.restype = None
    library.makhos_nnue_incremental_create_accumulator.argtypes = []
    library.makhos_nnue_incremental_create_accumulator.restype = ctypes.c_void_p
    library.makhos_nnue_incremental_free_accumulator.argtypes = [ctypes.c_void_p]
    library.makhos_nnue_incremental_free_accumulator.restype = None
    library.makhos_nnue_incremental_refresh.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
    ]
    library.makhos_nnue_incremental_refresh.restype = ctypes.c_int
    library.makhos_nnue_incremental_update.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
    ]
    library.makhos_nnue_incremental_update.restype = ctypes.c_int
    library.makhos_nnue_incremental_eval.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int32),
    ]
    library.makhos_nnue_incremental_eval.restype = ctypes.c_int
    library.makhos_nnue_incremental_eval_full.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int32),
    ]
    library.makhos_nnue_incremental_eval_full.restype = ctypes.c_int
    return library


class NativeIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [
                str(COMPILER),
                "-O3",
                "-march=native",
                "-std=c17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-shared",
                str(SOURCE),
                "-o",
                str(LIBRARY),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.library = configure_library(ctypes.CDLL(str(LIBRARY)))
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.quantized = exporter.parse_quantized_model(
            MODEL.read_bytes(), cls.contract
        )
        cls.expected_sha = (ctypes.c_uint8 * 32).from_buffer_copy(
            bytes.fromhex(cls.contract["source_model_sha256"])
        )

    @staticmethod
    def encoded(values):
        return (ctypes.c_uint16 * len(values))(*values)

    def load_model(self):
        handle = self.library.makhos_nnue_incremental_load(
            str(MODEL).encode("utf-8"), self.expected_sha
        )
        self.assertTrue(handle, self.library.makhos_nnue_scalar_last_error())
        return handle

    def create_accumulator(self):
        handle = self.library.makhos_nnue_incremental_create_accumulator()
        self.assertTrue(handle, self.library.makhos_nnue_scalar_last_error())
        return handle

    def refresh(self, model, accumulator, state):
        red = perspective_active_features(state, RED)
        black = perspective_active_features(state, BLACK)
        status = self.library.makhos_nnue_incremental_refresh(
            model,
            accumulator,
            self.encoded(red),
            len(red),
            self.encoded(black),
            len(black),
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())

    def update(self, model, accumulator, delta, *, inverse=False):
        removed = delta.added if inverse else delta.removed
        added = delta.removed if inverse else delta.added
        status = self.library.makhos_nnue_incremental_update(
            model,
            accumulator,
            delta.perspective,
            self.encoded(removed),
            len(removed),
            self.encoded(added),
            len(added),
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())

    def evaluate(self, model, accumulator, state):
        result = ctypes.c_int32()
        status = self.library.makhos_nnue_incremental_eval(
            model, accumulator, state.turn, ctypes.byref(result)
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())
        return result.value

    def evaluate_full(self, model, state):
        red = perspective_active_features(state, RED)
        black = perspective_active_features(state, BLACK)
        result = ctypes.c_int32()
        status = self.library.makhos_nnue_incremental_eval_full(
            model,
            self.encoded(red),
            len(red),
            self.encoded(black),
            len(black),
            state.turn,
            ctypes.byref(result),
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())
        return result.value

    def expected(self, state):
        first, second = exporter.ordered_feature_indices(state)
        return round(
            exporter.quantized_infer(self.quantized, first, second)
            * OUTPUT_DENOMINATOR
        )

    def assert_state(self, model, accumulator, state):
        expected = self.expected(state)
        self.assertEqual(self.evaluate_full(model, state), expected)
        self.assertEqual(self.evaluate(model, accumulator, state), expected)

    def test_full_refresh_matches_every_clock_turn_and_piece_band(self):
        self.assertEqual(self.library.makhos_nnue_incremental_model_bytes(), 43704)
        self.assertEqual(
            self.library.makhos_nnue_incremental_accumulator_bytes(), 584
        )
        model = self.load_model()
        accumulator = self.create_accumulator()
        positions = (
            "B:BM21,22,23,24,25,26,27,28:RM1,2,3,4,5,6,7,8",
            "B:BM21,22,25,27:BK30:RM5,7,8,10:RK2",
            "B:BM21,22:BK30:RM5,7:RK2",
            "B:BK30:RK2",
        )
        try:
            checked = 0
            for position in positions:
                base = parse_position(position)
                for turn in (RED, BLACK):
                    for clock in range(80):
                        state = State(base.board, turn, clock, ply=31)
                        self.refresh(model, accumulator, state)
                        self.assert_state(model, accumulator, state)
                        checked += 1
            self.assertEqual(checked, 640)
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(accumulator)
            self.library.makhos_nnue_incremental_free_model(model)

    def test_targeted_quiet_capture_promotion_and_multi_capture_undo(self):
        quiet = parse_position("B:BM25:RK1", reversible_plies=9)
        capture = state_from_pieces(
            {(4, 3): BLACK_MAN, (3, 2): RED_MAN, (5, 2): RED_MAN},
            BLACK,
            reversible_plies=37,
        )
        promotion = parse_position("R:RM25:BK5", reversible_plies=7)
        multi_capture = state_from_pieces(
            {(6, 1): BLACK_MAN, (5, 2): RED_MAN, (3, 4): RED_MAN},
            BLACK,
            reversible_plies=12,
        )
        parents = (quiet, capture, promotion, multi_capture)
        model = self.load_model()
        accumulator = self.create_accumulator()
        try:
            for parent in parents:
                moves = legal_moves(parent)
                move = (
                    next(item for item in moves if item.promotes)
                    if parent is promotion
                    else moves[0]
                )
                child = apply_move(parent, move)
                deltas = both_perspective_feature_deltas(parent, child)
                self.refresh(model, accumulator, parent)
                self.assert_state(model, accumulator, parent)
                for delta in deltas:
                    self.update(model, accumulator, delta)
                self.assert_state(model, accumulator, child)
                for delta in reversed(deltas):
                    self.update(model, accumulator, delta, inverse=True)
                self.assert_state(model, accumulator, parent)
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(accumulator)
            self.library.makhos_nnue_incremental_free_model(model)

    def test_every_clock_bucket_transition_and_reset_is_bit_exact(self):
        quiet_boundaries = (0, 9, 19, 29, 39, 49, 59, 69)
        reset_clocks = (0, 1, 10, 20, 30, 40, 50, 60, 70)
        model = self.load_model()
        accumulator = self.create_accumulator()
        try:
            for clock in quiet_boundaries:
                parent = parse_position(
                    "B:BM25:RK1", reversible_plies=clock
                )
                move = legal_moves(parent)[0]
                self.assertFalse(move.is_capture)
                child = apply_move(parent, move)
                self.assertEqual(child.reversible_plies, clock + 1)
                deltas = both_perspective_feature_deltas(parent, child)
                self.refresh(model, accumulator, parent)
                for delta in deltas:
                    self.update(model, accumulator, delta)
                self.assert_state(model, accumulator, child)
                for delta in reversed(deltas):
                    self.update(model, accumulator, delta, inverse=True)
                self.assert_state(model, accumulator, parent)

            for clock in reset_clocks:
                parent = state_from_pieces(
                    {(4, 3): BLACK_MAN, (3, 2): RED_MAN, (5, 2): RED_MAN},
                    BLACK,
                    reversible_plies=clock,
                )
                move = legal_moves(parent)[0]
                self.assertTrue(move.is_capture)
                child = apply_move(parent, move)
                self.assertEqual(child.reversible_plies, 0)
                deltas = both_perspective_feature_deltas(parent, child)
                self.refresh(model, accumulator, parent)
                for delta in deltas:
                    self.update(model, accumulator, delta)
                self.assert_state(model, accumulator, child)
                for delta in reversed(deltas):
                    self.update(model, accumulator, delta, inverse=True)
                self.assert_state(model, accumulator, parent)
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(accumulator)
            self.library.makhos_nnue_incremental_free_model(model)

    def test_random_parent_child_undo_and_deep_stack_are_bit_exact(self):
        model = self.load_model()
        accumulator = self.create_accumulator()
        rng = random.Random(20260831)
        state = initial_state()
        try:
            self.refresh(model, accumulator, state)
            transitions = 0
            while transitions < 300:
                moves = legal_moves(state)
                if not moves or state.reversible_plies >= 79:
                    state = initial_state(first_player=rng.choice((RED, BLACK)))
                    self.refresh(model, accumulator, state)
                    continue
                child = apply_move(state, rng.choice(moves), validate=False)
                deltas = both_perspective_feature_deltas(state, child)
                for delta in deltas:
                    self.update(model, accumulator, delta)
                self.assert_state(model, accumulator, child)
                for delta in reversed(deltas):
                    self.update(model, accumulator, delta, inverse=True)
                self.assert_state(model, accumulator, state)
                for delta in deltas:
                    self.update(model, accumulator, delta)
                state = child
                transitions += 1

            state = initial_state()
            self.refresh(model, accumulator, state)
            stack = []
            for _ in range(64):
                moves = legal_moves(state)
                if not moves or state.reversible_plies >= 79:
                    break
                child = apply_move(state, rng.choice(moves), validate=False)
                deltas = both_perspective_feature_deltas(state, child)
                for delta in deltas:
                    self.update(model, accumulator, delta)
                stack.append((state, child, deltas))
                state = child
                self.assert_state(model, accumulator, state)
            self.assertGreaterEqual(len(stack), 20)
            for parent, _child, deltas in reversed(stack):
                for delta in reversed(deltas):
                    self.update(model, accumulator, delta, inverse=True)
                state = parent
                self.assert_state(model, accumulator, state)
            self.assertEqual(state, initial_state())
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(accumulator)
            self.library.makhos_nnue_incremental_free_model(model)

    def test_invalid_state_and_model_reload_require_safe_refresh(self):
        first_model = self.load_model()
        second_model = self.load_model()
        accumulator = self.create_accumulator()
        state = initial_state()
        output = ctypes.c_int32()
        try:
            self.assertEqual(
                self.library.makhos_nnue_incremental_eval(
                    first_model, accumulator, state.turn, ctypes.byref(output)
                ),
                0,
            )
            self.refresh(first_model, accumulator, state)
            before = self.evaluate(first_model, accumulator, state)
            self.assertEqual(
                self.library.makhos_nnue_incremental_eval(
                    second_model, accumulator, state.turn, ctypes.byref(output)
                ),
                0,
            )
            self.refresh(second_model, accumulator, state)
            self.assertEqual(self.evaluate(second_model, accumulator, state), before)

            red = set(perspective_active_features(state, RED))
            inactive = next(index for index in range(137) if index not in red)
            removed = self.encoded((inactive,))
            empty = self.encoded(())
            self.assertEqual(
                self.library.makhos_nnue_incremental_update(
                    second_model,
                    accumulator,
                    RED,
                    removed,
                    1,
                    empty,
                    0,
                ),
                0,
            )
            self.assertEqual(self.evaluate(second_model, accumulator, state), before)
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(accumulator)
            self.library.makhos_nnue_incremental_free_model(second_model)
            self.library.makhos_nnue_incremental_free_model(first_model)


if __name__ == "__main__":
    unittest.main()
