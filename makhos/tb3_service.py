"""Background artifact readiness independent of the serialized search lock."""

from __future__ import annotations

from pathlib import Path
import threading
import time

from .compact_tb3 import CompactTablebase, DEFAULT_ARTIFACT


class TB3Service:
    def __init__(self, path: Path = DEFAULT_ARTIFACT, *, timeout_sec: float = 2.0):
        self.path = path
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()
        self._generation = 0
        self._state = "unloaded"
        self._error = None
        self._tablebase = None
        self._thread = None
        self._started = 0.0
        self._load_ms = None

    def _expire_locked(self):
        if self._state == "loading" and time.perf_counter() - self._started >= self.timeout_sec:
            self._state = "timeout"
            self._error = "TB3 startup load exceeded its deadline; check storage and restart server"
            self._generation += 1  # A late IO completion cannot publish readiness.

    def start(self) -> threading.Thread | None:
        with self._lock:
            self._expire_locked()
            if self._state != "unloaded":
                return self._thread if self._state == "loading" else None
            self._state = "loading"
            self._started = time.perf_counter()
            generation = self._generation
            thread = threading.Thread(target=self._load, args=(generation,),
                                      name="makhos-tb3-load", daemon=True)
            self._thread = thread
            thread.start()
            return thread

    def _load(self, generation):
        tablebase = None
        error = None
        try:
            tablebase = CompactTablebase(self.path)
        except (OSError, ValueError, RuntimeError) as caught:
            error = str(caught)
        with self._lock:
            self._expire_locked()
            if generation == self._generation and self._state == "loading":
                self._load_ms = (time.perf_counter() - self._started) * 1000
                self._state = "error" if error else "ready"
                self._error = error
                self._tablebase, tablebase = tablebase, None
                self._thread = None
        if tablebase is not None:
            tablebase.close()

    def ready(self) -> CompactTablebase | None:
        with self._lock:
            self._expire_locked()
            return self._tablebase if self._state == "ready" else None

    def status(self) -> dict:
        with self._lock:
            self._expire_locked()
            return {"state": self._state, "ready": self._state == "ready",
                    "error": self._error, "path": str(self.path), "load_ms": self._load_ms,
                    "timeout_ms": self.timeout_sec * 1000,
                    "sha256": self._tablebase.sha256 if self._tablebase else None}

    def close(self):
        with self._lock:
            self._generation += 1
            if self._tablebase is not None:
                self._tablebase.close()
            self._tablebase = self._thread = self._error = self._load_ms = None
            self._state = "unloaded"
