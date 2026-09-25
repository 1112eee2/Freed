import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from makhos.workload_isolation import (
    LOCK_SLOTS,
    BatchWorkLease,
    InteractiveSessionActive,
    InteractiveSessionLease,
    _RangeLock,
    interactive_session_active,
)


REPO_ROOT = Path(__file__).resolve().parents[1]

# Takes a batch slot and reports it.  The first stdin line releases the lease
# and the second ends the process, so a freed slot proves an explicit release.
HOLDER_PROGRAM = (
    "from pathlib import Path; import sys\n"
    "from makhos.workload_isolation import BatchWorkLease\n"
    "with BatchWorkLease(Path(sys.argv[1]), event_name=sys.argv[2]) as lease:\n"
    "    print('HOLD', lease._lock.offset, flush=True)\n"
    "    sys.stdin.readline()\n"
    "print('RELEASED', flush=True)\n"
    "sys.stdin.readline()\n"
)

# Reports whether each requested slot could be locked by this other process.
PROBE_PROGRAM = (
    "from pathlib import Path; import sys\n"
    "from makhos.workload_isolation import _RangeLock\n"
    "states = []\n"
    "for slot in map(int, sys.argv[2:]):\n"
    "    lock = _RangeLock(Path(sys.argv[1]))\n"
    "    states.append('FREE' if lock.try_lock(slot, 1) else 'HELD')\n"
    "    lock.close()\n"
    "print(' '.join(states))\n"
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


@unittest.skipIf(os.name == "nt", "POSIX byte-range locks; Windows uses msvcrt")
class PosixSlotLockTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.lock_path = self.root / "build" / "runtime" / "workload.lock"
        self.event_name = rf"Local\ThaiMakhosTest-{uuid.uuid4()}"

    def start_holder(self) -> tuple[subprocess.Popen, int]:
        child = subprocess.Popen(
            [sys.executable, "-c", HOLDER_PROGRAM]
            + [str(self.root), self.event_name],
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.stop_holder, child)
        line = child.stdout.readline()
        if not line.startswith("HOLD "):
            child.kill()
            _, stderr = child.communicate(timeout=10)
            self.fail(f"holder did not take a slot: {line!r}\n{stderr}")
        return child, int(line.split()[1])

    def release_holder(self, child: subprocess.Popen) -> None:
        child.stdin.write("\n")
        child.stdin.flush()
        self.assertEqual(child.stdout.readline().strip(), "RELEASED")

    def stop_holder(self, child: subprocess.Popen) -> None:
        try:
            child.communicate(timeout=10)  # EOF on stdin ends the holder
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=10)

    def slot_states(self, *slots: int) -> list[str]:
        completed = subprocess.run(
            [sys.executable, "-c", PROBE_PROGRAM, str(self.lock_path)]
            + [str(slot) for slot in slots],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.split()

    def test_separate_processes_hold_distinct_slots_until_released(self) -> None:
        first, first_slot = self.start_holder()
        second, second_slot = self.start_holder()
        self.assertEqual((first_slot, second_slot), (0, 1))
        # Each process's slot is refused to every other process.
        self.assertEqual(self.slot_states(0, 1, 2), ["HELD", "HELD", "FREE"])

        self.release_holder(first)
        self.assertIsNone(first.poll())  # released explicitly, still running
        self.assertEqual(self.slot_states(0, 1), ["FREE", "HELD"])
        _third, third_slot = self.start_holder()
        self.assertEqual(third_slot, 0)

        second.kill()  # the kernel frees a crashed holder's slot
        second.wait(timeout=10)
        self.assertEqual(self.slot_states(1), ["FREE"])

    def test_closing_one_lease_keeps_other_in_process_slots_held(self) -> None:
        with BatchWorkLease(self.root, event_name=self.event_name) as kept:
            with BatchWorkLease(self.root, event_name=self.event_name) as closed:
                self.assertEqual((kept._lock.offset, closed._lock.offset), (0, 1))
            # With fcntl.lockf, closing any descriptor of the file would have
            # dropped slot 0 as well.
            self.assertEqual(self.slot_states(0, 1), ["HELD", "FREE"])
        self.assertEqual(self.slot_states(0), ["FREE"])

    def test_full_range_owner_survives_refused_in_process_lease(self) -> None:
        # The full-suite attestation owns every slot while the tests it runs
        # in-process open their own BatchWorkLease on the same file.
        owner = _RangeLock(self.lock_path)
        self.addCleanup(owner.close)
        self.assertTrue(owner.try_lock(0, LOCK_SLOTS))
        with self.assertRaisesRegex(RuntimeError, "already occupied"):
            BatchWorkLease(self.root, event_name=self.event_name).__enter__()
        self.assertEqual(self.slot_states(0, LOCK_SLOTS - 1), ["HELD", "HELD"])
        owner.close()
        self.assertEqual(self.slot_states(0, LOCK_SLOTS - 1), ["FREE", "FREE"])

    def test_without_ofd_locks_one_whole_file_lease_is_admitted(self) -> None:
        # Simulates POSIX systems whose fcntl lacks F_OFD_SETLK (macOS, BSD).
        program = (
            "import fcntl; vars(fcntl).pop('F_OFD_SETLK', None)\n"
            "from pathlib import Path; import sys\n"
            "from makhos.workload_isolation import BatchWorkLease\n"
            "root, event = Path(sys.argv[1]), sys.argv[2]\n"
            "with BatchWorkLease(root, event_name=event):\n"
            "    try:\n"
            "        BatchWorkLease(root, event_name=event).__enter__()\n"
            "    except RuntimeError as error:\n"
            "        print('REFUSED', error)\n"
            "with BatchWorkLease(root, event_name=event) as lease:\n"
            "    print('ACQUIRED', lease._lock.offset)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program, str(self.root), self.event_name],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                "REFUSED all batch workload slots are already occupied",
                "ACQUIRED 0",
            ],
        )


if __name__ == "__main__":
    unittest.main()
