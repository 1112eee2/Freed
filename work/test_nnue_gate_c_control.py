"""Backward-compatibility wrapper for test_nnue_gate_c_control.

Canonical test suite has moved to tests.tooling.test_nnue_gate_c_control.
"""
from tests.tooling.test_nnue_gate_c_control import *

if __name__ == "__main__":
    unittest.main(verbosity=2)
