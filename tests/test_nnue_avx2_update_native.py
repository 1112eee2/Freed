import ctypes
import json
from pathlib import Path
import subprocess

from makhos.core import (
    BLACK,
    BLACK_MAN,
    RED_MAN,
    apply_move,
    initial_state,
    legal_moves,
    parse_position,
    state_from_pieces,
)
from makhos.nnue_features import (
    both_perspective_feature_deltas,
    perspective_active_features,
)
from scratch import nnue_quantized_export as exporter
from tests import test_nnue_avx2_native as avx2_tests


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "makhos_nnue_avx2_update.c"
LIBRARY = ROOT / "build" / "makhos_nnue_avx2_update_test.dll"
NO_AVX2_LIBRARY = ROOT / "build" / "makhos_nnue_avx2_update_forced_off_test.dll"
COMPILER = Path(r"C:\Program Files\LLVM\bin\clang.exe")
CONTRACT = avx2_tests.CONTRACT
MODEL = avx2_tests.MODEL


def configure_update(library):
    avx2_tests.configure_avx2(library)
    library.makhos_nnue_avx2_update.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
    ]
    library.makhos_nnue_avx2_update.restype = ctypes.c_int
    return library


class NativeAvx2UpdateTests(avx2_tests.NativeAvx2Tests):
    @classmethod
    def setUpClass(cls):
        common = [
            str(COMPILER),
            "-O3",
            "-march=x86-64",
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            str(SOURCE),
        ]
        for output, extra in (
            (LIBRARY, []),
            (NO_AVX2_LIBRARY, ["-DMAKHOS_NNUE_FORCE_NO_AVX2=1"]),
        ):
            result = subprocess.run(
                [*common, *extra, "-o", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise AssertionError(result.stderr)
        cls.library = configure_update(ctypes.CDLL(str(LIBRARY)))
        cls.no_avx2_library = configure_update(ctypes.CDLL(str(NO_AVX2_LIBRARY)))
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.quantized = exporter.parse_quantized_model(
            MODEL.read_bytes(), cls.contract
        )
        cls.expected_sha = (ctypes.c_uint8 * 32).from_buffer_copy(
            bytes.fromhex(cls.contract["source_model_sha256"])
        )

    def update(self, model, accumulator, delta, *, inverse=False):
        removed = delta.added if inverse else delta.removed
        added = delta.removed if inverse else delta.added
        status = self.library.makhos_nnue_avx2_update(
            model,
            accumulator,
            delta.perspective,
            self.encoded(removed),
            len(removed),
            self.encoded(added),
            len(added),
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())

    def explicit_parents(self):
        return (
            ("quiet_no_boundary", parse_position("B:BM25:RK1", reversible_plies=1)),
            ("quiet_boundary", parse_position("B:BM25:RK1", reversible_plies=9)),
            (
                "capture_reset",
                state_from_pieces(
                    {(4, 3): BLACK_MAN, (3, 2): RED_MAN, (5, 2): RED_MAN},
                    BLACK,
                    reversible_plies=37,
                ),
            ),
            (
                "multi_capture",
                state_from_pieces(
                    {(6, 1): BLACK_MAN, (5, 2): RED_MAN, (3, 4): RED_MAN},
                    BLACK,
                    reversible_plies=12,
                ),
            ),
            ("promotion", parse_position("R:RM25:BK5", reversible_plies=7)),
        )

    def test_scalar_and_avx2_updates_match_explicit_delta_shapes(self):
        model = self.load_model()
        scalar_accumulator = self.create_accumulator()
        avx2_accumulator = self.create_accumulator()
        observed = {}
        try:
            for name, parent in self.explicit_parents():
                moves = legal_moves(parent)
                move = (
                    next(item for item in moves if item.promotes)
                    if name == "promotion"
                    else moves[0]
                )
                child = apply_move(parent, move)
                deltas = both_perspective_feature_deltas(parent, child)
                observed[name] = tuple(
                    (len(delta.removed), len(delta.added)) for delta in deltas
                )
                self.refresh(model, scalar_accumulator, parent)
                self.refresh(model, avx2_accumulator, parent)
                for delta in deltas:
                    self.assertEqual(
                        self.library.makhos_nnue_incremental_update(
                            model,
                            scalar_accumulator,
                            delta.perspective,
                            self.encoded(delta.removed),
                            len(delta.removed),
                            self.encoded(delta.added),
                            len(delta.added),
                        ),
                        1,
                    )
                    self.update(model, avx2_accumulator, delta)
                scalar_value = ctypes.c_int32()
                self.assertEqual(
                    self.library.makhos_nnue_incremental_eval(
                        model,
                        scalar_accumulator,
                        child.turn,
                        ctypes.byref(scalar_value),
                    ),
                    1,
                )
                self.assertEqual(
                    self.evaluate(model, avx2_accumulator, child),
                    scalar_value.value,
                )
                for delta in reversed(deltas):
                    self.update(model, avx2_accumulator, delta, inverse=True)
                self.assert_state(model, avx2_accumulator, parent)
            self.assertEqual(observed["quiet_no_boundary"], ((1, 1), (1, 1)))
            self.assertEqual(observed["quiet_boundary"], ((2, 2), (2, 2)))
            self.assertEqual(observed["capture_reset"], ((3, 2), (3, 2)))
            self.assertEqual(observed["multi_capture"], ((4, 2), (4, 2)))
            self.assertEqual(observed["promotion"], ((2, 2), (2, 2)))
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(avx2_accumulator)
            self.library.makhos_nnue_incremental_free_accumulator(scalar_accumulator)
            self.library.makhos_nnue_incremental_free_model(model)

    def test_invalid_avx2_deltas_preserve_accumulator_state(self):
        model = self.load_model()
        accumulator = self.create_accumulator()
        state = initial_state()
        try:
            self.refresh(model, accumulator, state)
            before = self.evaluate(model, accumulator, state)
            red_active = set(perspective_active_features(state, 1))
            inactive = next(index for index in range(137) if index not in red_active)
            active = next(iter(red_active))
            cases = (
                (1, (inactive,), ()),
                (1, (active, active), ()),
                (1, (active,), (active,)),
                (1, (), (active,)),
                (1, (137,), ()),
                (3, (), ()),
                (1, (), tuple(range(18))),
            )
            for perspective, removed, added in cases:
                self.assertEqual(
                    self.library.makhos_nnue_avx2_update(
                        model,
                        accumulator,
                        perspective,
                        self.encoded(removed),
                        len(removed),
                        self.encoded(added),
                        len(added),
                    ),
                    0,
                )
                self.assertEqual(self.evaluate(model, accumulator, state), before)
        finally:
            self.library.makhos_nnue_incremental_free_accumulator(accumulator)
            self.library.makhos_nnue_incremental_free_model(model)

    def test_forced_unsupported_update_fails_closed(self):
        library = self.no_avx2_library
        model = library.makhos_nnue_incremental_load(
            str(MODEL).encode("utf-8"), self.expected_sha
        )
        accumulator = library.makhos_nnue_incremental_create_accumulator()
        state = initial_state()
        red = perspective_active_features(state, 1)
        black = perspective_active_features(state, 2)
        try:
            self.assertEqual(
                library.makhos_nnue_incremental_refresh(
                    model,
                    accumulator,
                    self.encoded(red),
                    len(red),
                    self.encoded(black),
                    len(black),
                ),
                1,
            )
            before = ctypes.c_int32()
            self.assertEqual(
                library.makhos_nnue_incremental_eval(
                    model, accumulator, state.turn, ctypes.byref(before)
                ),
                1,
            )
            move = legal_moves(state)[0]
            child = apply_move(state, move)
            delta = both_perspective_feature_deltas(state, child)[0]
            self.assertEqual(
                library.makhos_nnue_avx2_update(
                    model,
                    accumulator,
                    delta.perspective,
                    self.encoded(delta.removed),
                    len(delta.removed),
                    self.encoded(delta.added),
                    len(delta.added),
                ),
                0,
            )
            after = ctypes.c_int32()
            self.assertEqual(
                library.makhos_nnue_incremental_eval(
                    model, accumulator, state.turn, ctypes.byref(after)
                ),
                1,
            )
            self.assertEqual(after.value, before.value)
        finally:
            library.makhos_nnue_incremental_free_accumulator(accumulator)
            library.makhos_nnue_incremental_free_model(model)
