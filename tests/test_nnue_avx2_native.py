import ctypes
import json
from pathlib import Path
import subprocess

from makhos.core import initial_state
from makhos.nnue_features import perspective_active_features
from scratch import nnue_quantized_export as exporter
from tests import test_nnue_incremental_native as incremental_tests


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "makhos_nnue_avx2.c"
LIBRARY = ROOT / "build" / "makhos_nnue_avx2_test.dll"
NO_AVX2_LIBRARY = ROOT / "build" / "makhos_nnue_avx2_forced_off_test.dll"
COMPILER = Path(r"C:\Program Files\LLVM\bin\clang.exe")
CONTRACT = incremental_tests.CONTRACT
MODEL = incremental_tests.MODEL


def configure_avx2(library):
    incremental_tests.configure_library(library)
    library.makhos_nnue_avx2_supported.argtypes = []
    library.makhos_nnue_avx2_supported.restype = ctypes.c_int
    library.makhos_nnue_avx2_eval.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int32),
    ]
    library.makhos_nnue_avx2_eval.restype = ctypes.c_int
    return library


class NativeAvx2Tests(incremental_tests.NativeIncrementalTests):
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
        cls.library = configure_avx2(ctypes.CDLL(str(LIBRARY)))
        cls.no_avx2_library = configure_avx2(ctypes.CDLL(str(NO_AVX2_LIBRARY)))
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.quantized = exporter.parse_quantized_model(
            MODEL.read_bytes(), cls.contract
        )
        cls.expected_sha = (ctypes.c_uint8 * 32).from_buffer_copy(
            bytes.fromhex(cls.contract["source_model_sha256"])
        )

    def evaluate(self, model, accumulator, state):
        result = ctypes.c_int32()
        status = self.library.makhos_nnue_avx2_eval(
            model, accumulator, state.turn, ctypes.byref(result)
        )
        self.assertEqual(status, 1, self.library.makhos_nnue_scalar_last_error())
        return result.value

    def test_host_capability_gate_reports_avx2(self):
        self.assertEqual(self.library.makhos_nnue_avx2_supported(), 1)

    def test_forced_unsupported_host_fails_closed(self):
        library = self.no_avx2_library
        self.assertEqual(library.makhos_nnue_avx2_supported(), 0)
        model = library.makhos_nnue_incremental_load(
            str(MODEL).encode("utf-8"), self.expected_sha
        )
        accumulator = library.makhos_nnue_incremental_create_accumulator()
        self.assertTrue(model)
        self.assertTrue(accumulator)
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
            output = ctypes.c_int32(1234567)
            self.assertEqual(
                library.makhos_nnue_avx2_eval(
                    model, accumulator, state.turn, ctypes.byref(output)
                ),
                0,
            )
            self.assertEqual(output.value, 1234567)
            self.assertIn(
                b"unavailable", library.makhos_nnue_scalar_last_error()
            )
        finally:
            library.makhos_nnue_incremental_free_accumulator(accumulator)
            library.makhos_nnue_incremental_free_model(model)
