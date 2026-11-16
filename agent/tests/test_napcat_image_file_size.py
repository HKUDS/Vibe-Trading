"""Regression: a malformed `file_size` on an inbound Napcat image must not
drop the whole message. `file_size` comes straight from the OneBot segment
and is "sometimes a string" per the code's own comment; a non-numeric string
raised an uncaught ValueError out of `_on_message`, silently losing the
accompanying text too.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

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
    @pytest.mark.parametrize("file_size", ["", "not-a-number", float("inf")])
    def test_non_numeric_string_file_size_does_not_raise(self, monkeypatch: pytest.MonkeyPatch, file_size) -> None:
        channel, received = _make_channel(monkeypatch)

        asyncio.run(channel._on_message(_event(file_size)))

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


@pytest.mark.parametrize("declared,chunks,expected,requests", [
    ("unknown", [b"ab", b"cd"], b"abcd", 1),
    (None, [b"ab", b"cd"], b"abcd", 1),
    ("unknown", [b"abcd", b"e"], None, 1),
    ("1000", [b"ab"], None, 0),
])
def test_download_keeps_actual_byte_limit_with_unusable_metadata(
    monkeypatch, tmp_path, declared, chunks, expected, requests,
):
    channel, received = _make_channel(monkeypatch)
    channel.config.max_image_bytes = 4
    channel._media_root = tmp_path
    calls = []

    async def stream(size):
        for chunk in chunks:
            yield chunk

    class Response:
        status = 200
        content = SimpleNamespace(iter_chunked=stream)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    channel._http = SimpleNamespace(get=get)
    asyncio.run(channel._on_message(_event(declared)))
    assert len(received) == 1
    assert received[0]["content"] == "hello with a pic"
    assert len(calls) == requests
    if expected is None:
        assert received[0]["media"] is None
        assert list(tmp_path.iterdir()) == []
    else:
        assert Path(received[0]["media"][0]).read_bytes() == expected
        assert calls[0][1] == {"allow_redirects": False}
