"""Private strategy IPC using fresh pipes, never the MCP server's stdin.

The existing strategy sandbox still validates and executes the source. Pickle
is private IPC between these two processes, as with the previous Connection;
it is never accepted from a client or a persisted file.
"""

from __future__ import annotations

import pickle
import queue
import subprocess
import sys
import threading
from typing import Any


class StrategyConnection:
    """Connection-compatible messages with a bounded parent-side poll."""

    def __init__(self, reader, writer, *, background: bool = False):
        self.reader = reader
        self.writer = writer
        self.messages: queue.Queue = queue.Queue()
        self.pending = None
        self.thread = None
        if background:
            self.thread = threading.Thread(target=self._read, name="paper-strategy-ipc", daemon=True)
            self.thread.start()

    def _read(self) -> None:
        try:
            while True:
                self.messages.put((True, pickle.load(self.reader)))
        except Exception:
            self.messages.put((False, None))

    def send(self, message: Any) -> None:
        pickle.dump(message, self.writer, protocol=pickle.HIGHEST_PROTOCOL)
        self.writer.flush()

    def poll(self, timeout: float) -> bool:
        if self.pending is None:
            try:
                self.pending = self.messages.get(timeout=timeout)
            except queue.Empty:
                return False
        return True

    def recv(self) -> Any:
        if self.thread is None:
            return pickle.load(self.reader)
        success, message = self.pending if self.pending is not None else self.messages.get()
        self.pending = None
        if not success:
            raise EOFError("strategy process closed its protocol")
        return message

    def close(self) -> None:
        # Caller reaps the child first, releasing any blocked pipe read.
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        for stream in (self.writer, self.reader):
            try:
                stream.close()
            except OSError:
                pass


def start_strategy_process(payload: dict[str, Any]):
    """Start an isolated interpreter and deliver the validated source snapshot.

    Args:
        payload: Source, filename, days and universe already checked by caller.

    Returns:
        The child process and its private bidirectional message connection.
    """
    # Preserve import paths for editable installs and standalone MCP hosts.
    # -B keeps research execution from writing bytecode into a caller's cwd.
    bootstrap = (
        f"import sys; sys.path[:] = {sys.path!r}; "
        "from src.tools.paper_trade.strategy_process import worker_main; worker_main()"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-u", "-c", bootstrap],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    connection = StrategyConnection(process.stdout, process.stdin, background=True)
    try:
        connection.send(payload)
    except BaseException:
        process.kill()
        process.wait()
        connection.close()
        raise
    return process, connection


def worker_main() -> None:
    """Keep strategy/import prints out of the binary protocol stream."""
    connection = StrategyConnection(sys.stdin.buffer, sys.stdout.buffer)
    sys.stdout = sys.stderr
    payload = connection.recv()
    from .strategy_exec import _child_main

    _child_main(connection, payload)
