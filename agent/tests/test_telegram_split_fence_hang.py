"""Regression: telegram markdown split must not hang on long fenced bodies."""

from __future__ import annotations

import os

import pytest

import signal
import sys
import types


def _stub_telegram_deps() -> None:
    """Install minimal stubs so telegram.py imports without python-telegram-bot."""

    def _mod(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    tg = _mod("telegram")

    class _Accepting:
        def __init__(self, *args, **kwargs) -> None:
            pass

    for name in (
        "BotCommand",
        "InlineKeyboardButton",
        "InlineKeyboardMarkup",
        "ReactionTypeEmoji",
        "ReplyParameters",
        "Update",
    ):
        setattr(tg, name, _Accepting)

    err = _mod("telegram.error")
    for name in ("BadRequest", "NetworkError", "TimedOut"):
        setattr(err, name, type(name, (Exception,), {}))

    ext = _mod("telegram.ext")
    for name in (
        "Application",
        "CallbackQueryHandler",
        "ContextTypes",
        "MessageHandler",
        "filters",
    ):
        setattr(ext, name, _Accepting)

    _mod("telegram.request").HTTPXRequest = _Accepting


_stub_telegram_deps()

from src.channels.telegram import (  # noqa: E402
    TELEGRAM_MAX_MESSAGE_LEN,
    _split_telegram_markdown,
)


class _Hang(Exception):
    pass


def _alarm_handler(signum, frame) -> None:  # noqa: ANN001
    raise _Hang()


@pytest.mark.skipif(os.name == "nt", reason="SIGALRM hang-guard is POSIX-only")
def test_split_telegram_markdown_long_fence_body_no_hang() -> None:
    """Long fenced line with no breaks must finish under the production limit."""
    body = "a" * 5000
    content = f"```\n{body}"
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(2)
    try:
        chunks = _split_telegram_markdown(content, TELEGRAM_MAX_MESSAGE_LEN)
    finally:
        signal.alarm(0)

    assert chunks
    assert all(isinstance(c, str) and c for c in chunks)
    # Body must appear across chunks (close/reopen may repeat the fence marker).
    joined_body = "".join(c.replace("```", "").replace("\n", "") for c in chunks)
    assert body in joined_body or joined_body.count("a") >= len(body)


@pytest.mark.skipif(os.name == "nt", reason="SIGALRM hang-guard is POSIX-only")
def test_split_telegram_markdown_closed_long_fence_no_hang() -> None:
    content = "```\n" + "x" * 5000 + "\n```"
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(2)
    try:
        chunks = _split_telegram_markdown(content, TELEGRAM_MAX_MESSAGE_LEN)
    finally:
        signal.alarm(0)
    assert len(chunks) >= 2
    assert sum(c.count("x") for c in chunks) >= 5000


def test_split_telegram_markdown_nonpositive_max_len_returns_unsplit() -> None:
    content = "hello world"
    assert _split_telegram_markdown(content, 0) == [content]
    assert _split_telegram_markdown(content, -1) == [content]


@pytest.mark.skipif(os.name == "nt", reason="SIGALRM hang-guard is POSIX-only")
def test_split_telegram_markdown_short_fence_mid_limit_no_hang() -> None:
    """Fence at index 0 with mid-size max_len must not rebuild the same chunk."""
    content = '```\n om/yyyyyyyyyyyyyyyyyyyy)\n\na"'
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(2)
    try:
        chunks = _split_telegram_markdown(content, 32)
    finally:
        signal.alarm(0)
    assert chunks
    assert "".join(chunks).replace("```", "").count("y") >= content.count("y")
