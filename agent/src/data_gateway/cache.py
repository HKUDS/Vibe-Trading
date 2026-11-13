"""Bounded JSON cache with atomic writes, expiry and cross-process eviction."""

from collections import OrderedDict
from contextlib import contextmanager
import json
import os
import threading
import time
from typing import Any

from .config import Config


class Cache:
    """Keep only bounded serialized entries in RAM; never retain parsed chains."""

    def __init__(self, config: Config):
        self.config = config
        self.memory: OrderedDict[str, bytes] = OrderedDict()
        self.memory_size = 0
        self.last_access: dict[str, float] = {}
        self.lock = threading.RLock()
        self.directory = config.cache_dir
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.prune()

    @contextmanager
    def disk_lock(self):
        """Serialize cache mutation across local CLI/API processes."""
        with (self.directory / ".lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _remember(self, key: str, raw: bytes):
        old = self.memory.pop(key, None)
        self.last_access.pop(key, None)
        self.memory_size -= len(old) if old else 0
        if len(raw) <= self.config.memory_bytes:
            self.memory[key] = raw
            self.last_access[key] = time.monotonic()
            self.memory_size += len(raw)
        while self.memory and (self.memory_size > self.config.memory_bytes or len(self.memory) > self.config.entries):
            removed, value = self.memory.popitem(last=False)
            self.last_access.pop(removed, None)
            self.memory_size -= len(value)

    def _prune(self, reserve: int = 0):
        now = time.time()
        files = []
        for path in self.directory.glob("*.json"):
            stat = path.stat()
            # Expiry is based on write time, never extended by a cache read.
            if now - stat.st_mtime > self.config.stale_ttl or stat.st_size > self.config.entry_bytes:
                path.unlink(missing_ok=True)
            else:
                files.append((stat.st_atime, path, stat.st_size))
        total = sum(row[2] for row in files)
        remaining = len(files)
        for _, path, size in sorted(files):
            if total + reserve <= self.config.disk_bytes and remaining <= self.config.entries - (1 if reserve else 0):
                break
            path.unlink(missing_ok=True)
            total -= size
            remaining -= 1
        # Temporary files are only written while this same process lock is held.
        for path in self.directory.glob("*.tmp"):
            path.unlink(missing_ok=True)
        self.prune_memory()

    def prune_memory(self):
        """Reclaim idle/expired RAM even when the disk cache is unavailable."""
        with self.lock:
            wall, monotonic = time.time(), time.monotonic()
            for key, raw in list(self.memory.items()):
                if (
                    monotonic - self.last_access[key] >= self.config.memory_idle
                    or wall - json.loads(raw)["stored_at"] > self.config.stale_ttl
                ):
                    del self.memory[key]
                    self.last_access.pop(key, None)
                    self.memory_size -= len(raw)

    def prune(self):
        """Reclaim expired entries and enforce disk and memory budgets."""
        self.prune_memory()
        with self.lock, self.disk_lock():
            self._prune()

    def get(self, key: str) -> dict[str, Any] | None:
        """Return an unshared parsed copy with its original acquisition time."""
        with self.lock:
            raw = self.memory.get(key)
            if raw is None:
                path = self.directory / (key + ".json")
                try:
                    with path.open("rb") as handle:
                        raw = handle.read(self.config.entry_bytes + 1)
                    if len(raw) > self.config.entry_bytes:
                        return None
                except OSError:
                    return None
            try:
                entry = json.loads(raw)
                if time.time() - entry["stored_at"] > self.config.stale_ttl:
                    return None
                self._remember(key, raw)
                return entry
            except (ValueError, KeyError, TypeError):
                return None

    def put(self, key: str, payload: dict[str, Any]):
        """Cache one successful result, evicting before the atomic disk write."""
        entry = {"stored_at": time.time(), "payload": payload}
        raw = json.dumps(entry, allow_nan=False, separators=(",", ":")).encode()
        if len(raw) > self.config.entry_bytes:
            return
        with self.lock, self.disk_lock():
            self._remember(key, raw)
            destination = self.directory / (key + ".json")
            destination.unlink(missing_ok=True)
            self._prune(len(raw))
            if len(raw) <= self.config.disk_bytes:
                temporary = self.directory / (key + ".tmp")
                with temporary.open("wb") as handle:
                    handle.write(raw)
                os.replace(temporary, destination)

    def stats(self):
        """Report actual disk and RAM occupancy without quote contents."""
        with self.lock, self.disk_lock():
            files = list(self.directory.glob("*.json"))
            return {
                "disk_bytes": sum(p.stat().st_size for p in files),
                "disk_entries": len(files),
                "memory_bytes": self.memory_size,
                "memory_entries": len(self.memory),
            }
