"""Unit tests for the UCI/UGI protocol interface."""

import io
import sys
import unittest
from unittest.mock import patch

from makhos.cli import main


class UCITests(unittest.TestCase):

    def test_uci_handshake_and_quit(self) -> None:
        input_data = "uci\nisready\nquit\n"
        output_buffer = io.StringIO()

        with patch("sys.stdin", io.StringIO(input_data)), patch("sys.stdout", output_buffer):
            exit_code = main(["uci", "--depth", "1"])
            self.assertEqual(exit_code, 0)

        output = output_buffer.getvalue()
        self.assertIn("id name ThaiMakhos 2.0", output)
        self.assertIn("uciok", output)
        self.assertIn("readyok", output)

    def test_uci_position_and_go(self) -> None:
        input_data = "uci\nposition startpos moves 28-24 8-12\ngo depth 2\nquit\n"
        output_buffer = io.StringIO()

        with patch("sys.stdin", io.StringIO(input_data)), patch("sys.stdout", output_buffer):
            exit_code = main(["uci", "--depth", "2"])
            self.assertEqual(exit_code, 0)

        output = output_buffer.getvalue()
        self.assertIn("info depth", output)
        self.assertIn("bestmove", output)


if __name__ == "__main__":
    unittest.main()
