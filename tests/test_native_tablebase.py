import ctypes
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from makhos.core import parse_position
from makhos.exact import Outcome
from makhos.native_tablebase import NativeTablebase


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TB4_EXECUTABLE = _PROJECT_ROOT / "build" / "makhos_tb4.exe"
_TB4_NP1 = _PROJECT_ROOT / "build" / "tb4_np1.bin"


class _FakeFunction:
    def __init__(self, implementation):
        self.implementation = implementation
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.implementation(*args)


class _FakeLibrary:
    def __init__(self):
        self.makhos_tb3_init = _FakeFunction(lambda _clock, _power: 0)
        self.makhos_tb3_shutdown = _FakeFunction(lambda: None)
        self.makhos_tb3_state_count = _FakeFunction(lambda: 123)
        self.makhos_tb3_root_count = _FakeFunction(lambda: 45)

        def probe(
            _red,
            _black,
            _kings,
            _turn,
            _clock,
            outcome,
            distance,
        ):
            ctypes.cast(outcome, ctypes.POINTER(ctypes.c_int))[0] = Outcome.DRAW
            ctypes.cast(distance, ctypes.POINTER(ctypes.c_int))[0] = -1
            return 0

        self.makhos_tb3_probe = _FakeFunction(probe)


class NativeTablebaseLifetimeTests(unittest.TestCase):
    def test_compatible_instances_share_lifetime_and_close_independently(self):
        fake = _FakeLibrary()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "makhos_native.dll"
            path.write_bytes(b"fixture")
            with patch(
                "makhos.native_tablebase.ctypes.CDLL", return_value=fake
            ) as load_library:
                first = NativeTablebase(
                    path, no_progress_plies=80, hash_power=16
                )
                second = NativeTablebase(
                    path, no_progress_plies=80, hash_power=16
                )
                self.assertEqual(load_library.call_count, 1)
                self.assertEqual(len(fake.makhos_tb3_init.calls), 1)

                first.close()
                first.close()
                self.assertEqual(len(fake.makhos_tb3_shutdown.calls), 0)
                with self.assertRaisesRegex(RuntimeError, "closed"):
                    first.probe(parse_position("B:BK1:RK32"))

                result = second.probe(parse_position("B:BK1:RK32"))
                self.assertEqual(result.outcome, Outcome.DRAW)
                self.assertEqual(second.state_count, 123)
                self.assertEqual(second.root_count, 45)
                second.close()
                second.close()
                self.assertEqual(len(fake.makhos_tb3_shutdown.calls), 1)

    def test_incompatible_live_configuration_is_rejected_without_reinit(self):
        fake = _FakeLibrary()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "makhos_native.dll"
            path.write_bytes(b"fixture")
            with patch(
                "makhos.native_tablebase.ctypes.CDLL", return_value=fake
            ):
                first = NativeTablebase(
                    path, no_progress_plies=80, hash_power=16
                )
                try:
                    with self.assertRaisesRegex(ValueError, "incompatible"):
                        NativeTablebase(
                            path, no_progress_plies=40, hash_power=16
                        )
                    with self.assertRaisesRegex(ValueError, "incompatible"):
                        NativeTablebase(
                            path, no_progress_plies=80, hash_power=17
                        )
                    self.assertEqual(len(fake.makhos_tb3_init.calls), 1)
                    self.assertEqual(len(fake.makhos_tb3_shutdown.calls), 0)
                    self.assertEqual(
                        first.probe(parse_position("B:BK1:RK32")).outcome,
                        Outcome.DRAW,
                    )
                finally:
                    first.close()
                self.assertEqual(len(fake.makhos_tb3_shutdown.calls), 1)


@unittest.skipUnless(
    _TB4_EXECUTABLE.is_file() and _TB4_NP1.is_file(),
    "native four-piece CLI fixture is not available",
)
class NativeTablebaseCliRegressionTests(unittest.TestCase):
    @staticmethod
    def _probe(position: str, clock: int) -> dict[str, str]:
        completed = subprocess.run(
            [
                str(_TB4_EXECUTABLE),
                "probe",
                str(_TB4_NP1),
                position,
                str(clock),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            key.strip(): value.strip()
            for line in completed.stdout.splitlines()
            if ":" in line
            for key, value in (line.split(":", 1),)
        }

    def test_no_progress_draw_precedes_native_blocked_loss(self):
        position = "B:BM5,6:RM1,2"
        self.assertEqual(self._probe(position, 0)["outcome"], "LOSS")
        self.assertEqual(self._probe(position, 1)["outcome"], "DRAW")

    def test_native_four_king_rank_boundaries(self):
        self.assertEqual(
            self._probe("B:BK29,30:RK31,32", 0)["rank"],
            "0",
        )
        self.assertEqual(
            self._probe("B:BK3,4:RK1,2", 0)["rank"],
            "215759",
        )


if __name__ == "__main__":
    unittest.main()
