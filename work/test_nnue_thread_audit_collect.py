"""Backward-compatibility wrapper for test_nnue_thread_audit_collect.

Canonical test suite has moved to tests.tooling.test_nnue_thread_audit_collect.
"""
from tests.tooling.test_nnue_thread_audit_collect import *

if __name__ == "__main__":
    unittest.main()
