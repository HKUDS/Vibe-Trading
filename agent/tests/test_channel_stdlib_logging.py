"""Channel adapters log through stdlib ``logging``, not loguru (#1531, #1533).

``BaseChannel.logger`` is ``logging.getLogger(...)``. A loguru-style ``"{}"``
message with arguments makes stdlib raise inside handler formatting, so the
message is lost; a loguru-only ``.opt(exception=True)`` raises AttributeError
before anything is logged.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.channels.signal import SignalChannel

pytestmark = pytest.mark.unit


def test_signal_safe_handle_logs_and_swallows(caplog) -> None:
    """``_safe_handle`` promises to swallow; ``.opt()`` made it raise AttributeError."""
    host = SimpleNamespace(logger=logging.getLogger("tests.signal.safe_handle"))

    async def run() -> None:
        async with SignalChannel._safe_handle(host, "receive", {"envelope": "100%"}):
            raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="tests.signal.safe_handle"):
        asyncio.run(run())

    record = next(r for r in caplog.records if r.name == "tests.signal.safe_handle")
    assert "Error in receive: boom" in record.getMessage()
    assert "100%" in record.getMessage()
    assert record.exc_info is not None


_SRC = Path(__file__).resolve().parents[1] / "src"
_BRACE_PLACEHOLDER = re.compile(r"\{(?:![rs])?(?::[^{}]*)?\}")
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}


def _loguru_style_calls(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr == "opt":
            found.append(f"{path.name}:{node.lineno} .opt()")
        elif node.func.attr in _LOG_METHODS and len(node.args) > 1:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and _BRACE_PLACEHOLDER.search(first.value):
                found.append(f"{path.name}:{node.lineno} {first.value!r}")
    return found


def test_no_loguru_style_logging_anywhere_in_src() -> None:
    """The whole tree logs through stdlib (#1533, its napcat follow-up, #1529)."""
    offenders = [hit for path in sorted(_SRC.rglob("*.py")) for hit in _loguru_style_calls(path)]
    assert not offenders, offenders


def test_the_scan_sees_a_loguru_style_call(tmp_path: Path) -> None:
    """Guard the guard: an empty scan would pass vacuously."""
    probe = tmp_path / "probe.py"
    probe.write_text('logger.info("sent {} to {}", a, b)\nlogger.opt(exception=True).error("x")\n', encoding="utf-8")
    assert len(_loguru_style_calls(probe)) == 2
