from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from makhos.workload_isolation import (
    BatchWorkLease,
    InteractiveSessionActive,
    InteractiveSessionLease,
    interactive_session_active,
)


class WorkloadIsolationTests(unittest.TestCase):
    def test_interactive_event_is_live_only_while_lease_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            event_name = rf"Local\ThaiMakhosTest-{uuid.uuid4()}"
            lease = InteractiveSessionLease(Path(directory), event_name=event_name)
            lease.acquire(timeout_sec=0.2)
            try:
                self.assertTrue(interactive_session_active(event_name))
            finally:
                lease.close()
            self.assertFalse(interactive_session_active(event_name))

    def test_batch_slots_allow_parallel_workers_and_release_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_name = rf"Local\ThaiMakhosTest-{uuid.uuid4()}"
            first = BatchWorkLease(root, event_name=event_name)
            second = BatchWorkLease(root, event_name=event_name)
            with first, second:
                self.assertNotEqual(first._lock.offset, second._lock.offset)

    def test_live_default_interactive_session_rejects_batch_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interactive = InteractiveSessionLease(root)
            interactive.acquire(timeout_sec=0.2)
            try:
                with self.assertRaises(InteractiveSessionActive):
                    BatchWorkLease(root).__enter__()
            finally:
                interactive.close()

    def test_interactive_priority_drains_a_live_batch_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_name = rf"Local\ThaiMakhosTest-{uuid.uuid4()}"
            program = (
                "from pathlib import Path; import sys,time; "
                "from makhos.workload_isolation import BatchWorkLease,"
                "InteractiveSessionActive; "
                "lease=BatchWorkLease(Path(sys.argv[1]),event_name=sys.argv[2]); "
                "lease.__enter__(); print('READY',flush=True); "
                "\ntry:\n"
                "  while True:\n"
                "    lease.checkpoint('child-test'); time.sleep(0.01)\n"
                "except InteractiveSessionActive:\n"
                "  pass\n"
                "finally:\n"
                "  lease.__exit__(None,None,None)\n"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", program, str(root), event_name],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "READY")
                interactive = InteractiveSessionLease(root, event_name=event_name)
                started = time.perf_counter()
                interactive.acquire(timeout_sec=2.0)
                try:
                    child.wait(timeout=2)
                    self.assertEqual(child.returncode, 0, child.stderr.read())
                    self.assertLess(time.perf_counter() - started, 2.0)
                finally:
                    interactive.close()
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=2)


if __name__ == "__main__":
    unittest.main()
