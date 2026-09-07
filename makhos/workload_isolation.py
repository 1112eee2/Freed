"""Crash-safe isolation between interactive play and CPU-heavy batch work.

The GUI owns the whole lock range while it is running.  Batch workers own one
byte each and periodically observe the interactive-priority event, allowing a
new GUI session to drain existing workers at a safe position boundary.  Windows
releases both file locks and named-event handles if a process crashes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time


INTERACTIVE_EVENT_NAME = r"Local\ThaiMakhosEngineInteractiveV1"
LOCK_SLOTS = 32
WAIT_OBJECT_0 = 0
ERROR_FILE_NOT_FOUND = 2
SYNCHRONIZE = 0x00100000


class InteractiveSessionActive(RuntimeError):
    """Raised when batch work must yield to an interactive GUI session."""


def _kernel32():
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = (
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def interactive_session_active(
    event_name: str = INTERACTIVE_EVENT_NAME,
) -> bool:
    """Return whether a live GUI process has asserted interactive priority."""

    kernel32 = _kernel32()
    if kernel32 is None:
        return False
    handle = kernel32.OpenEventW(SYNCHRONIZE, False, event_name)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            return False
        raise OSError(error, "could not inspect interactive workload event")
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def ensure_interactive_session_inactive(stage: str) -> None:
    if interactive_session_active():
        raise InteractiveSessionActive(
            f"PAUSED_FOR_INTERACTIVE_PLAY before {stage}"
        )


class _RangeLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None
        self.offset = 0
        self.length = 0

    def _open(self) -> None:
        if self.handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b", buffering=0)
        if self.path.stat().st_size < LOCK_SLOTS:
            self.handle.seek(LOCK_SLOTS - 1)
            self.handle.write(b"\0")
            self.handle.flush()

    def try_lock(self, offset: int, length: int) -> bool:
        self._open()
        assert self.handle is not None
        self.handle.seek(offset)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, length)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.offset = offset
        self.length = length
        return True

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            if self.length:
                self.handle.seek(self.offset)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(
                        self.handle.fileno(),
                        msvcrt.LK_UNLCK,
                        self.length,
                    )
                else:
                    import fcntl

                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.length = 0
            self.handle.close()
            self.handle = None


class BatchWorkLease:
    """Own one batch slot and yield when an interactive session starts."""

    def __init__(
        self,
        project_root: Path,
        *,
        event_name: str = INTERACTIVE_EVENT_NAME,
    ) -> None:
        self._lock = _RangeLock(project_root / "build" / "runtime" / "workload.lock")
        self.event_name = event_name

    def __enter__(self) -> "BatchWorkLease":
        if interactive_session_active(self.event_name):
            raise InteractiveSessionActive(
                "PAUSED_FOR_INTERACTIVE_PLAY before batch startup"
            )
        for slot in range(LOCK_SLOTS):
            if self._lock.try_lock(slot, 1):
                if interactive_session_active(self.event_name):
                    self._lock.close()
                    raise InteractiveSessionActive(
                        "PAUSED_FOR_INTERACTIVE_PLAY during batch startup"
                    )
                return self
        self._lock.close()
        raise RuntimeError("all batch workload slots are already occupied")

    def checkpoint(self, stage: str) -> None:
        if interactive_session_active(self.event_name):
            raise InteractiveSessionActive(
                f"PAUSED_FOR_INTERACTIVE_PLAY before {stage}"
            )

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._lock.close()


class InteractiveSessionLease:
    """Assert GUI priority and wait for instrumented batch workers to drain."""

    def __init__(
        self,
        project_root: Path,
        *,
        event_name: str = INTERACTIVE_EVENT_NAME,
    ) -> None:
        self.event_name = event_name
        self._lock = _RangeLock(project_root / "build" / "runtime" / "workload.lock")
        self._event_handle = None

    def acquire(self, *, timeout_sec: float = 15.0) -> None:
        kernel32 = _kernel32()
        if kernel32 is not None:
            handle = kernel32.CreateEventW(None, True, True, self.event_name)
            if not handle:
                error = ctypes.get_last_error()
                raise OSError(error, "could not assert interactive workload event")
            self._event_handle = handle
        deadline = time.monotonic() + timeout_sec
        while not self._lock.try_lock(0, LOCK_SLOTS):
            if time.monotonic() >= deadline:
                self.close()
                raise RuntimeError(
                    "batch work did not yield to interactive play within "
                    f"{timeout_sec:.1f} seconds"
                )
            time.sleep(0.05)

    def close(self) -> None:
        self._lock.close()
        if self._event_handle is not None:
            kernel32 = _kernel32()
            if kernel32 is not None:
                kernel32.CloseHandle(self._event_handle)
            self._event_handle = None

    def __enter__(self) -> "InteractiveSessionLease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
