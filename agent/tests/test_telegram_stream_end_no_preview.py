"""Regression: a streaming reply must not be dropped when no preview was ever sent."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest


def _stub_telegram_deps() -> None:
    """Install minimal stubs so telegram.py imports without python-telegram-bot."""

    def _mod(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    tg = _mod("telegram")

    class _Accepting:
        def __init__(self, *args, **kwargs) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

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
    for name in ("BadRequest", "NetworkError", "TimedOut", "RetryAfter"):
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

from src.channels.telegram import TelegramChannel, _StreamBuf  # noqa: E402


@pytest.fixture(autouse=True)
def _ensure_retry_after_stub():
    """Sibling telegram test files stub telegram.error at import time too, and
    whichever file's stub runs last in a combined pytest session wins the
    shared sys.modules entry. None of them included RetryAfter before this
    file needed it (via _call_with_retry's real send path), so make sure it's
    present regardless of collection order.
    """
    telegram_error = sys.modules.get("telegram.error")
    if telegram_error is not None and not hasattr(telegram_error, "RetryAfter"):
        telegram_error.RetryAfter = type("RetryAfter", (Exception,), {})
    yield


class _FakeBot:
    def __init__(self, *, rich_ok: bool = False, rich_error: Exception | None = None) -> None:
        self.send_message_calls: list[dict] = []
        self.delete_message_calls: list[dict] = []
        self._rich_ok = rich_ok
        self._rich_error = rich_error

    async def send_message(self, **kwargs):
        self.send_message_calls.append(kwargs)

        class _Sent:
            message_id = 999

        return _Sent()

    async def delete_message(self, **kwargs):
        self.delete_message_calls.append(kwargs)

    async def do_api_request(self, *args, **kwargs):
        if not self._rich_ok:
            raise (self._rich_error or RuntimeError("rich send failed"))


def _make_channel(*, rich_messages: bool, bot: _FakeBot) -> TelegramChannel:
    channel = TelegramChannel({"token": "x", "rich_messages": rich_messages}, bus=None)

    class _App:
        pass

    app = _App()
    app.bot = bot
    channel._app = app
    return channel


class TestStreamEndWithoutPreview:
    """If the initial streaming preview send never succeeded (message_id is
    still None), the accumulated text must still reach the user through some
    channel call, never be silently dropped.
    """

    def test_rich_messages_disabled_falls_back_to_a_fresh_send(self) -> None:
        bot = _FakeBot()
        channel = _make_channel(rich_messages=False, bot=bot)
        channel._stream_bufs["42"] = _StreamBuf(text="Hello, world!", message_id=None)

        asyncio.run(channel.send_delta("42", "", {"_stream_end": True}))

        assert len(bot.send_message_calls) == 1
        assert "Hello, world!" in bot.send_message_calls[0]["text"]
        assert "42" not in channel._stream_bufs

    def test_rich_send_failure_falls_back_to_a_fresh_send(self) -> None:
        bot = _FakeBot(rich_ok=False)
        channel = _make_channel(rich_messages=True, bot=bot)
        channel._stream_bufs["42"] = _StreamBuf(text="Hello, world!", message_id=None)

        asyncio.run(channel.send_delta("42", "", {"_stream_end": True}))

        assert len(bot.send_message_calls) == 1
        assert "Hello, world!" in bot.send_message_calls[0]["text"]
        assert not bot.delete_message_calls

    def test_rich_send_success_does_not_try_to_delete_a_nonexistent_preview(self) -> None:
        bot = _FakeBot(rich_ok=True)
        channel = _make_channel(rich_messages=True, bot=bot)
        channel._stream_bufs["42"] = _StreamBuf(text="Hello, world!", message_id=None)

        asyncio.run(channel.send_delta("42", "", {"_stream_end": True}))

        assert not bot.send_message_calls
        assert not bot.delete_message_calls
        assert "42" not in channel._stream_bufs
