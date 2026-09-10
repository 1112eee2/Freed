"""C1 native TB3 gate. Build with tools/build_endgame_c1.ps1 first."""
import ctypes as C
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import random
import unittest

from makhos.compact_tb3 import CompactTablebase, BOARD_COUNT
from makhos.core import State, parse_position
from makhos.native_endgame import DEFAULT_LIBRARY, NativeEndgameTablebase, Position, Probe


@unittest.skipUnless(DEFAULT_LIBRARY.is_file(), "isolated C1 DLL not built")
class NativeEndgameTBTests(unittest.TestCase):
    def setUp(self):
        self.reference = CompactTablebase()
        self.addCleanup(self.reference.close)
        self.native = NativeEndgameTablebase(self.reference)
        self.addCleanup(self.native.close)

    def test_48600_reference_probes(self):
        rng = random.Random(20260909)
        count = 0
        for sample in range(300):
            board = [0] * 32
            for square in rng.sample(range(32), 1 + sample % 3):
                piece = rng.randrange(1, 5)
                # No unpromoted men on their final rank.
                if (piece == 2 and square < 4) or (piece == 1 and square >= 28):
                    piece += 2
                board[square] = piece
            for turn in (1, 2):
                for clock in range(81):
                    state = State(tuple(board), turn, clock)
                    self.assertEqual(self.native.probe(state), self.reference.probe(state))
                    count += 1
        self.assertEqual(count, 48600)

    def test_source_close_does_not_invalidate_native_copy(self):
        state = parse_position("B:BK6,15:RK28")
        expected = self.reference.probe(state)
        self.reference.close()
        self.assertEqual(self.native.probe(state), expected)
        with self.assertRaises(RuntimeError):
            self.reference.export_native_image()

    def test_close_is_idempotent(self):
        self.native.close()
        self.native.close()
        with self.assertRaises(RuntimeError):
            self.native.probe(parse_position("B:BK1:RK32"))

    def test_invalid_inputs_and_abi(self):
        dll = self.native._dll
        good = Position(1, 2, 3, 1, 0)
        for position in (Position(1, 1, 1, 1, 0), Position(1, 2, 4, 1, 0),
                         Position(1, 2, 3, 0, 0), Position(1, 2, 3, 1, 81)):
            result = Probe(C.sizeof(Probe), 1)
            self.assertEqual(dll.makhos_tb_set_probe(self.native._handle, C.byref(position), C.byref(result)), 3)
        for size, version in ((0, 1), (C.sizeof(Probe), 2)):
            result = Probe(size, version)
            self.assertEqual(dll.makhos_tb_set_probe(self.native._handle, C.byref(good), C.byref(result)), 3)
        for clock in (-1, 81, 2**32):
            with self.assertRaises(ValueError):
                self.native.probe(replace(parse_position("B:BK1:RK32"), reversible_plies=clock))

    def test_create_rejects_layout_and_corrupt_reference(self):
        image, clock, vectors = self.reference.export_native_image()
        dll = self.native._dll
        for size, horizon, count in ((len(image)-1, clock, vectors), (2**64-1, clock, vectors),
                                     (len(image), 0, vectors), (len(image), clock, 0)):
            handle = C.c_void_p(123)
            self.assertEqual(dll.makhos_tb3_create(image, size, horizon, count, C.byref(handle)), 3)
            self.assertFalse(handle)
        corrupt = b'\xff' * 4 + image[4:]
        handle = C.c_void_p()
        self.assertEqual(dll.makhos_tb3_create(corrupt, len(corrupt), clock, vectors, C.byref(handle)), 4)
        self.assertFalse(handle)

    def test_raw_native_concurrent_readers_retain_lifetime(self):
        dll, handle = self.native._dll, self.native._handle
        dll.makhos_tb_set_retain(handle)
        try:
            self.native.close()
            def worker(_):
                position = Position(1 << 27, (1 << 5) | (1 << 14),
                                    (1 << 27) | (1 << 5) | (1 << 14), 2, 0)
                for _ in range(1000):
                    output = Probe(C.sizeof(Probe), 1)
                    self.assertEqual(dll.makhos_tb_set_probe(handle, C.byref(position), C.byref(output)), 0)
                    self.assertEqual(output.outcome, 1)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(worker, range(2)))
        finally:
            dll.makhos_tb_set_release(handle)

    def test_miss_and_corruption_are_not_draws(self):
        dll = self.native._dll
        for position in (Position(0, 0, 0, 1, 0), Position(3, 12, 15, 1, 0)):
            output = Probe(C.sizeof(Probe), 1, 99, 99)
            status = dll.makhos_tb_set_probe(self.native._handle, C.byref(position), C.byref(output))
            self.assertEqual(status, 1)
            self.assertEqual(output.outcome, 99)
        # A well-sized image with an invalid encoded value must fail closed.
        image = bytes(BOARD_COUNT * 4) + b'\xff\xff' * 2
        handle = C.c_void_p()
        self.assertEqual(dll.makhos_tb3_create(image, len(image), 1, 1, C.byref(handle)), 0)
        try:
            output = Probe(C.sizeof(Probe), 1, 99, 99)
            position = Position(1, 2, 3, 1, 0)
            self.assertEqual(dll.makhos_tb_set_probe(handle, C.byref(position), C.byref(output)), 4)
            self.assertEqual(output.outcome, 99)
        finally:
            dll.makhos_tb_set_release(handle)


if __name__ == "__main__":
    unittest.main()
