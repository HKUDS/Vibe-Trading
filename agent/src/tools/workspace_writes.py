"""Record which tool windows covered observed changes to a node workspace."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path

from src.tools.bash_tool import _workspace_files


workspace_call_id: ContextVar[str] = ContextVar("workspace_call_id", default="")
_RECEIPT_NAME = "workspace-writes.json"


def workspace_write_receipt(thread: Path) -> Path:
    """Locate the host's write receipt outside the tool workspace.

    Args:
        thread: Canonical node thread path.

    Returns:
        Sibling path for the write receipt.
    """
    return thread.with_name(_RECEIPT_NAME)


class WorkspaceWrites:
    """Serialize scan boundaries for foreground calls and overlapping background tasks."""

    def __init__(
        self, workspace: Path, receipt: Path, *,
        legacy: dict[str, tuple[str | None, str | None]] | None = None,
        background_running: Callable[[str], bool] | None = None,
    ) -> None:
        self._workspace = workspace
        self._receipt = receipt
        self._lock = threading.Lock()
        self._sealed = False
        self._active: set[int] = set()
        self._carried: dict[int, str] = {}
        self._background_running = background_running
        self._snapshot: dict[str, tuple[int, int]] | None = None
        self._calls: list[dict] = []
        self._writers: dict[str, set[int]] = {}
        self._latest: dict[str, list[int]] = {}
        self._legacy = legacy or {}
        if receipt.is_file():
            saved = json.loads(receipt.read_text())
            self._calls = saved["calls"]
            for path, file in saved["files"].items():
                self._writers[path] = set(file["writers"])
                self._latest[path] = file["latest"]
            self._snapshot = {path: tuple(file["stat"]) for path, file in saved["files"].items()
                              if file["stat"] is not None}
            self._legacy = {path: tuple(writer) for path, writer in saved["legacy"].items()}
            if background_running is not None:
                self._carried = {
                    index: call["task_id"] for index, call in enumerate(self._calls)
                    if call["outcome"] == "running" and call["task_id"] and background_running(call["task_id"])
                }
                self._active.update(self._carried)
        self._first_new_call = len(self._calls)
        # A started attempt must never be mistaken for a legacy run if it fails to seal.
        self._save(sealed=False)

    def start(
        self, tool: str, call_id: str, *, may_write: bool, task_id: str | None = None,
    ) -> tuple[int | None, dict[str, tuple[int, int]]]:
        """Open a tool window and observe the preceding interval.

        Args:
            tool: Tool name.
            call_id: Provider tool call identifier.
            may_write: Whether this operation can change a handoff file.
            task_id: Background task identifier, for an asynchronous window.

        Returns:
            Window index (None if sealed) and its starting snapshot.
        """
        with self._lock:
            if self._sealed:
                return None, {}
            if may_write:
                self._scan()
            index = len(self._calls)
            self._calls.append({"tool": tool, "call_id": call_id, "task_id": task_id,
                                "start": time.monotonic_ns(), "end": None, "outcome": "running"})
            if may_write:
                self._active.add(index)
            return index, self._snapshot or {}

    def finish(
        self, index: int | None, *, success: bool, exit_code: int | None = None,
        exclusive_files: bool = False,
    ) -> dict[str, tuple[int, int]]:
        """Observe the window's final interval and record its result.

        Args:
            index: Window from start, or None if the attempt already sealed.
            success: Whether the tool or background process succeeded.
            exit_code: Subprocess exit code if available.
            exclusive_files: Return files only this call could have written in their last interval.

        Returns:
            Exclusive output stats when requested, otherwise an empty mapping.
        """
        ended = time.monotonic_ns()
        with self._lock:
            if self._sealed or index is None:
                return {}
            if index in self._active:
                self._scan()
                self._active.remove(index)
            call = self._calls[index]
            call.update(end=ended, outcome="ok" if success else "failed")
            if exit_code is not None:
                call["exit_code"] = exit_code
            if not exclusive_files:
                return {}
            snapshot = self._snapshot or {}
            return {path: snapshot[path] for path, latest in self._latest.items()
                    if latest == [index] and path in snapshot}

    def seal(self) -> None:
        """Freeze the attempt, treating every active window's outcome as unknown."""
        cutoff = time.monotonic_ns()
        with self._lock:
            self._sealed = True
            if self._active or self._snapshot is None:
                self._scan()
            for call in self._calls[self._first_new_call:]:
                if call["end"] is not None and call["end"] > cutoff:
                    call.update(end=None, outcome="running")
                    call.pop("exit_code", None)
            self._save(sealed=True)

    def _scan(self) -> None:
        current = _workspace_files(self._workspace, require_request=False) or {}
        if self._snapshot is not None:
            for path in self._snapshot.keys() | current.keys():
                if self._snapshot.get(path) == current.get(path):
                    continue
                self._legacy.pop(path, None)
                self._latest[path] = sorted(self._active)
                if self._active:
                    self._writers.setdefault(path, set()).update(self._active)
        self._snapshot = current
        if self._background_running is not None:
            for index, task in tuple(self._carried.items()):
                if not self._background_running(task):
                    self._active.remove(index)
                    del self._carried[index]

    def _save(self, *, sealed: bool) -> None:
        snapshot = self._snapshot or {}
        files = {path: {"stat": snapshot.get(path), "writers": sorted(self._writers.get(path, ())),
                        "latest": self._latest.get(path, [])}
                 for path in snapshot.keys() | self._writers.keys()}
        data = {"sealed": sealed, "calls": self._calls, "files": files, "legacy": self._legacy}
        self._receipt.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._receipt.parent,
                                         prefix=f".{self._receipt.name}.", delete=False) as output:
            pending = Path(output.name)
            try:
                json.dump(data, output, ensure_ascii=False)
                output.close()
                pending.replace(self._receipt)
            finally:
                pending.unlink(missing_ok=True)
