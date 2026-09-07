from collections import Counter
import unittest

from makhos.native_verify import _parse_native_move_states


class NativeMoveStateParserTests(unittest.TestCase):
    def test_parses_deterministic_child_state_records(self):
        output = (
            "18x8x25\tred=00000000\tblack=01000000\t"
            "kings=01000000\tturn=1\tclock=0\n"
            "1-6\tred=00000020\tblack=80000000\t"
            "kings=80000000\tturn=2\tclock=80\n"
        )
        self.assertEqual(
            _parse_native_move_states(output),
            Counter({
                ("18x8x25", 0, 0x01000000, 0x01000000, 1, 0): 1,
                ("1-6", 0x20, 0x80000000, 0x80000000, 2, 80): 1,
            }),
        )

    def test_rejects_malformed_or_impossible_child_states(self):
        invalid_outputs = (
            "1-6\tred=00000020\tblack=80000000\tkings=00000000\tturn=2\n",
            "1-6\tblack=00000020\tred=80000000\tkings=00000000\tturn=2\tclock=1\n",
            "1-6\tred=1\tblack=80000000\tkings=00000000\tturn=2\tclock=1\n",
            "1-6\tred=00000001\tblack=00000001\tkings=00000000\tturn=2\tclock=1\n",
            "1-6\tred=00000001\tblack=00000000\tkings=00000002\tturn=2\tclock=1\n",
            "1-6\tred=00000001\tblack=00000000\tkings=00000000\tturn=3\tclock=1\n",
            "1-6\tred=00000001\tblack=00000000\tkings=00000000\tturn=2\tclock=256\n",
        )
        for output in invalid_outputs:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    _parse_native_move_states(output)


if __name__ == "__main__":
    unittest.main()
