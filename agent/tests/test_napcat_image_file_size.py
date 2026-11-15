"""Regression: a malformed `file_size` on an inbound Napcat image must not
drop the whole message. `file_size` comes straight from the OneBot segment
and is "sometimes a string" per the code's own comment; a non-numeric string
raised an uncaught ValueError out of `_on_message`, silently losing the
accompanying text too.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("websockets")

from src.channels.napcat import NapcatChannel, NapcatConfig


def _make_channel(monkeypatch: pytest.MonkeyPatch) -> tuple[NapcatChannel, list[dict]]:
    import src.channels.napcat as napcat_mod

    monkeypatch.setattr(napcat_mod, "validate_url_target", lambda url, **kwargs: (True, ""))

    channel = NapcatChannel(NapcatConfig(enabled=True), bus=None)
    channel._http = object()  # non-None; download itself fails gracefully and is irrelevant here

    received: list[dict] = []

    async def fake_handle_message(**kwargs):
        received.append(kwargs)

    channel._handle_message = fake_handle_message
    return channel, received


def _event(file_size) -> dict:
    return {
        "message_id": 1,
        "message_type": "private",
        "user_id": 12345,
        "message": [
            {"type": "text", "data": {"text": "hello with a pic"}},
            {"type": "image", "data": {"url": "http://example.com/x.png", "file_size": file_size}},
        ],
        "sender": {"nickname": "tester"},
    }


class TestMalformedFileSizeDoesNotDropMessage:
    def test_non_numeric_string_file_size_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        channel, received = _make_channel(monkeypatch)

        asyncio.run(channel._on_message(_event("")))

        assert len(received) == 1
        assert received[0]["content"] == "hello with a pic"

    def test_missing_file_size_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        channel, received = _make_channel(monkeypatch)
        event = _event(None)
        del event["message"][1]["data"]["file_size"]

        asyncio.run(channel._on_message(event))

        assert len(received) == 1

    def test_oversized_numeric_file_size_still_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        channel, received = _make_channel(monkeypatch)
        channel.config.max_image_bytes = 10

        asyncio.run(channel._on_message(_event("1000000")))

        assert len(received) == 1
        assert received[0]["media"] is None
