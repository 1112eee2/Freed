import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from makhos.core import (
    BLACK,
    RED,
    State,
    apply_move,
    initial_state,
    legal_moves,
    parse_position,
)
from scratch import nnue_quantized_export as exporter
from tests.test_nnue_quantized_export import contract, synthetic_model


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "makhos_nnue_scalar.c"
LIBRARY = ROOT / "build" / "makhos_nnue_scalar_test.dll"
COMPILER = Path(r"C:\Program Files\LLVM\bin\clang.exe")
OUTPUT_DENOMINATOR = 127 * 192
REAL_CONTRACT = ROOT / "build" / "nnue_phase1_evidence" / "quantization_contract_v2.json"
REAL_MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
REAL_MODEL_SHA256 = "07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C"


class NativeScalarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [
                str(COMPILER),
                "-O3",
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
        cls.library = ctypes.CDLL(str(LIBRARY))
        cls.library.makhos_nnue_scalar_load.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint8),
        ]
        cls.library.makhos_nnue_scalar_load.restype = ctypes.c_void_p
        cls.library.makhos_nnue_scalar_free.argtypes = [ctypes.c_void_p]
        cls.library.makhos_nnue_scalar_free.restype = None
        cls.library.makhos_nnue_scalar_eval.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_int32),
        ]
        cls.library.makhos_nnue_scalar_eval.restype = ctypes.c_int
        cls.library.makhos_nnue_scalar_last_error.argtypes = []
        cls.library.makhos_nnue_scalar_last_error.restype = ctypes.c_char_p
        cls.library.makhos_nnue_scalar_model_bytes.argtypes = []
        cls.library.makhos_nnue_scalar_model_bytes.restype = ctypes.c_size_t

    def fixture(self, root: Path):
        frozen = contract()
        quantized = exporter.quantize_model(synthetic_model(), frozen)
        encoded = exporter.serialize_quantized_model(quantized, frozen)
        path = root / "model.mknnue"
        path.write_bytes(encoded)
        expected_sha = (ctypes.c_uint8 * 32).from_buffer_copy(
            bytes.fromhex(frozen["source_model_sha256"])
        )
        return frozen, quantized, path, expected_sha

    def load(self, path: Path, expected_sha):
        return self.library.makhos_nnue_scalar_load(
            str(path).encode("utf-8"),
            expected_sha,
        )

    def evaluate(self, handle, first, second):
        first_values = (ctypes.c_uint16 * len(first))(*first)
        second_values = (ctypes.c_uint16 * len(second))(*second)
        result = ctypes.c_int32()
        status = self.library.makhos_nnue_scalar_eval(
            handle,
            first_values,
            len(first),
            second_values,
            len(second),
            ctypes.byref(result),
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())
        return result.value

    def assert_parity(self, handle, quantized, state):
        first, second = exporter.ordered_feature_indices(state)
        expected = round(
            exporter.quantized_infer(quantized, first, second)
            * OUTPUT_DENOMINATOR
        )
        self.assertEqual(self.evaluate(handle, first, second), expected)

    def real_fixture(self):
        frozen = json.loads(REAL_CONTRACT.read_text(encoding="utf-8"))
        encoded = REAL_MODEL.read_bytes()
        self.assertEqual(hashlib.sha256(encoded).hexdigest().upper(), REAL_MODEL_SHA256)
        quantized = exporter.parse_quantized_model(encoded, frozen)
        expected_sha = (ctypes.c_uint8 * 32).from_buffer_copy(
            bytes.fromhex(frozen["source_model_sha256"])
        )
        return frozen, quantized, expected_sha

    @staticmethod
    def copied_model(model):
        return exporter.QuantizedModel(
            feature_weights=model.feature_weights.copy(),
            feature_bias=model.feature_bias.copy(),
            hidden_weight=model.hidden_weight.copy(),
            hidden_bias=model.hidden_bias.copy(),
            output_weight=model.output_weight.copy(),
            output_bias=model.output_bias.copy(),
        )

    def test_native_scalar_is_bit_exact_across_phase_turn_and_clock_buckets(self):
        self.assertEqual(self.library.makhos_nnue_scalar_model_bytes(), 43684)
        positions = [
            "B:BM21,22,23,24,25,26,27,28:RM1,2,3,4,5,6,7,8",
            "B:BM21,22,25,27:BK30:RM5,7,8,10:RK2",
            "B:BM21,22:BK30:RM5,7:RK2",
        ]
        clocks = (0, 1, 10, 20, 30, 40, 50, 60, 70)
        with tempfile.TemporaryDirectory() as directory:
            frozen, quantized, path, expected_sha = self.fixture(Path(directory))
            handle = self.load(path, expected_sha)
            self.assertTrue(handle, self.library.makhos_nnue_scalar_last_error())
            try:
                checked = 0
                for position in positions:
                    for turn in ("B", "R"):
                        position_for_turn = turn + position[1:]
                        for clock in clocks:
                            state = parse_position(
                                position_for_turn,
                                reversible_plies=clock,
                                ply=4,
                            )
                            self.assert_parity(handle, quantized, state)
                            checked += 1
                self.assertEqual(checked, 54)
            finally:
                self.library.makhos_nnue_scalar_free(handle)

    def test_real_keep_model_is_bit_exact_for_every_clock_and_both_turns(self):
        _frozen, quantized, expected_sha = self.real_fixture()
        handle = self.load(REAL_MODEL, expected_sha)
        self.assertTrue(handle, self.library.makhos_nnue_scalar_last_error())
        positions = (
            "B:BM21,22,23,24,25,26,27,28:RM1,2,3,4,5,6,7,8",
            "B:BM21,22,25,27:BK30:RM5,7,8,10:RK2",
            "B:BM21,22:BK30:RM5,7:RK2",
            "B:BK30:RK2",
        )
        try:
            checked = 0
            piece_counts = set()
            turns = set()
            clocks = set()
            for position in positions:
                base = parse_position(position)
                piece_counts.add(sum(piece != 0 for piece in base.board))
                for turn in (BLACK, RED):
                    for clock in range(80):
                        state = State(base.board, turn, clock, ply=17)
                        self.assert_parity(handle, quantized, state)
                        turns.add(turn)
                        clocks.add(clock)
                        checked += 1
            self.assertEqual(checked, 640)
            self.assertEqual(piece_counts, {2, 6, 10, 16})
            self.assertEqual(turns, {BLACK, RED})
            self.assertEqual(clocks, set(range(80)))
        finally:
            self.library.makhos_nnue_scalar_free(handle)

    def test_real_keep_model_matches_random_legal_positions(self):
        _frozen, quantized, expected_sha = self.real_fixture()
        handle = self.load(REAL_MODEL, expected_sha)
        self.assertTrue(handle, self.library.makhos_nnue_scalar_last_error())
        rng = random.Random(20260830)
        state = initial_state()
        try:
            turns = set()
            clocks = set()
            for index in range(512):
                clock = index % 80
                observed = State(state.board, state.turn, clock, state.ply)
                self.assert_parity(handle, quantized, observed)
                turns.add(observed.turn)
                clocks.add(clock)
                moves = legal_moves(state)
                state = (
                    apply_move(state, rng.choice(moves), validate=False)
                    if moves
                    else initial_state(first_player=rng.choice((BLACK, RED)))
                )
            self.assertEqual(turns, {BLACK, RED})
            self.assertEqual(clocks, set(range(80)))
        finally:
            self.library.makhos_nnue_scalar_free(handle)

    def test_corrupt_truncated_and_incompatible_models_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _frozen, _quantized, path, expected_sha = self.fixture(root)
            original = path.read_bytes()
            variants = {
                "truncated": original[:-1],
                "corrupt": original[:-1] + bytes([original[-1] ^ 1]),
                "incompatible": original[:52]
                + bytes([original[52] ^ 1])
                + original[53:],
            }
            for name, encoded in variants.items():
                candidate = root / f"{name}.mknnue"
                candidate.write_bytes(encoded)
                self.assertFalse(self.load(candidate, expected_sha), name)
                self.assertTrue(self.library.makhos_nnue_scalar_last_error())

    def test_wrong_source_model_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            _frozen, _quantized, path, _expected_sha = self.fixture(Path(directory))
            wrong = (ctypes.c_uint8 * 32)(*([0xEE] * 32))
            self.assertFalse(self.load(path, wrong))
            self.assertIn(
                b"source model",
                self.library.makhos_nnue_scalar_last_error().lower(),
            )

    def test_checksum_valid_but_unsafe_integer_bounds_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen, quantized, _path, expected_sha = self.fixture(root)
            variants = {}

            feature_unsafe = self.copied_model(quantized)
            feature_unsafe.feature_weights[:, 0] = 32767
            feature_unsafe.feature_bias[0] = 32767
            variants["feature"] = feature_unsafe

            hidden_unsafe = self.copied_model(quantized)
            hidden_unsafe.hidden_bias[0] = 2147483647
            hidden_unsafe.hidden_weight[0, 0] = 127
            variants["hidden"] = hidden_unsafe

            output_unsafe = self.copied_model(quantized)
            output_unsafe.output_bias[0] = 2147483647
            output_unsafe.output_weight[0, 0] = 127
            variants["output"] = output_unsafe

            for name, model in variants.items():
                path = root / f"unsafe-{name}.mknnue"
                path.write_bytes(exporter.serialize_quantized_model(model, frozen))
                self.assertFalse(self.load(path, expected_sha), name)
                self.assertIn(
                    b"unsafe",
                    self.library.makhos_nnue_scalar_last_error().lower(),
                )

    def test_invalid_loader_and_feature_arguments_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            _frozen, _quantized, path, expected_sha = self.fixture(Path(directory))
            self.assertFalse(self.library.makhos_nnue_scalar_load(None, expected_sha))
            self.assertFalse(self.load(path, None))
            handle = self.load(path, expected_sha)
            self.assertTrue(handle, self.library.makhos_nnue_scalar_last_error())
            try:
                valid = (ctypes.c_uint16 * 2)(0, 128)
                duplicate = (ctypes.c_uint16 * 2)(5, 5)
                out_of_range = (ctypes.c_uint16 * 2)(5, 137)
                too_many = (ctypes.c_uint16 * 18)(*range(18))
                output = ctypes.c_int32()
                invalid_calls = (
                    (valid, 0, valid, 2, ctypes.byref(output)),
                    (duplicate, 2, valid, 2, ctypes.byref(output)),
                    (out_of_range, 2, valid, 2, ctypes.byref(output)),
                    (too_many, 18, valid, 2, ctypes.byref(output)),
                    (valid, 2, valid, 2, None),
                )
                for arguments in invalid_calls:
                    self.assertEqual(
                        self.library.makhos_nnue_scalar_eval(handle, *arguments),
                        0,
                    )
                    self.assertTrue(self.library.makhos_nnue_scalar_last_error())
                self.assertEqual(
                    self.library.makhos_nnue_scalar_eval(
                        None,
                        valid,
                        2,
                        valid,
                        2,
                        ctypes.byref(output),
                    ),
                    0,
                )
            finally:
                self.library.makhos_nnue_scalar_free(handle)


if __name__ == "__main__":
    unittest.main()
