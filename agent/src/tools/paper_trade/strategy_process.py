"""Private strategy IPC using fresh pipes, never the MCP server's stdin.

The existing strategy sandbox still validates and executes the source. The two
directions use different encodings on purpose:

* parent -> child is pickle: the payload, account state and DataFrames come
  from the trusted parent, and the child is the one that unpickles them.
* child -> parent is one JSON array per line: the child runs LLM-generated
  strategy code, so nothing it writes may be unpickled (a crafted pickle would
  execute in the parent, which holds the full environment). Its messages are
  only ``["ready"]``, ``["day", day, orders]``, ``["error", day, name]`` and
  ``["done"]`` built from strings, finite floats and null.

The child also gets an allowlisted environment and an empty private working
directory, so strategy code can read neither the parent's secrets nor
relative files such as ``agent/.env``.
"""

from __future__ import annotations

import json
import pickle
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any

# Largest single child message; orders for one day are far below this.
_MAX_CHILD_MESSAGE_BYTES = 16 * 1024 * 1024


def decode_child_message(line: bytes) -> tuple[Any, ...]:
    """Parse one child->parent line, refusing anything but a tagged JSON array.

    Args:
        line: One newline-terminated line read from the child's stdout.

    Returns:
        The message as a tuple whose first element is its string tag.

    Raises:
        ValueError: If the line is truncated, oversized, or not a tagged array.
    """
    if not line.endswith(b"\n"):
        raise ValueError("strategy message truncated or larger than the limit")
    message = json.loads(line)
    if not (isinstance(message, list) and message and isinstance(message[0], str)):
        raise ValueError("strategy message must be a JSON array with a string tag")
    return tuple(message)


def encode_child_message(message: Any) -> bytes:
    """Serialize one child->parent message as a JSON line."""
    return json.dumps(list(message), ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


class StrategyConnection:
    """Connection-compatible messages with a bounded parent-side poll.

    ``parent=True`` reads JSON lines from the child and writes pickle to it;
    the child side does the reverse.
    """

    def __init__(self, reader, writer, *, parent: bool = False, workdir: str | None = None):
        self.reader = reader
        self.writer = writer
        self.parent = parent
        self.workdir = workdir
        self.messages: queue.Queue = queue.Queue()
        self.pending = None
        self.thread = None
        if parent:
            self.thread = threading.Thread(target=self._read, name="paper-strategy-ipc", daemon=True)
            self.thread.start()

    def _read(self) -> None:
        try:
            while True:
                line = self.reader.readline(_MAX_CHILD_MESSAGE_BYTES + 1)
                if not line:
                    raise EOFError
                self.messages.put((True, decode_child_message(line)))
        except Exception:
            self.messages.put((False, None))

    def send(self, message: Any) -> None:
        if self.parent:
            pickle.dump(message, self.writer, protocol=pickle.HIGHEST_PROTOCOL)
        else:
            self.writer.write(encode_child_message(message))
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
            return pickle.load(self.reader)  # child side: data from the trusted parent
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
        if self.workdir is not None:
            shutil.rmtree(self.workdir, ignore_errors=True)


def start_strategy_process(payload: dict[str, Any]):
    """Start an isolated interpreter and deliver the validated source snapshot.

    Args:
        payload: Source, filename, days and universe already checked by caller.

    Returns:
        The child process and its private bidirectional message connection.
    """
    from src.core.runner import _copy_runtime_env

    # Preserve import paths for editable installs and standalone MCP hosts.
    # -B keeps research execution from writing bytecode into a caller's cwd.
    bootstrap = (
        f"import sys; sys.path[:] = {sys.path!r}; "
        "from src.tools.paper_trade.strategy_process import worker_main; worker_main()"
    )
    workdir = tempfile.mkdtemp(prefix="vt-paper-strategy-")
    try:
        process = subprocess.Popen(
            [sys.executable, "-B", "-u", "-c", bootstrap],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, cwd=workdir, env=_copy_runtime_env(),
        )
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    connection = StrategyConnection(process.stdout, process.stdin, parent=True, workdir=workdir)
    try:
        connection.send(payload)
    except BaseException:
        process.kill()
        process.wait()
        connection.close()
        raise
    return process, connection


def worker_main() -> None:
    """Keep strategy/import prints out of the protocol stream."""
    connection = StrategyConnection(sys.stdin.buffer, sys.stdout.buffer)
    sys.stdout = sys.stderr
    payload = connection.recv()
    from .strategy_exec import _child_main

    _child_main(connection, payload)
