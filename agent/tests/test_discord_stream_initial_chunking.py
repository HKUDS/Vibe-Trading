"""Regression: the first send of a Discord streaming reply must respect the
2000-char message cap, same as the periodic edit and finalize paths below it.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("discord")

from src.channels.discord import DiscordChannel, DiscordConfig, MAX_MESSAGE_LEN


class _FakeClient:
    def is_ready(self) -> bool:
        return True


class _FakeTarget:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str | None = None, **kwargs) -> "_FakeTarget":
        if content is not None and len(content) > MAX_MESSAGE_LEN:
            raise ValueError(f"content length {len(content)} exceeds {MAX_MESSAGE_LEN}")
        self.sent.append(content)
        return self


def _make_channel() -> tuple[DiscordChannel, _FakeTarget]:
    channel = DiscordChannel(DiscordConfig(enabled=True, token="x"), bus=None)
    channel._client = _FakeClient()
    target = _FakeTarget()

    async def fake_resolve_channel(chat_id: str):
        return target

    channel._resolve_channel = fake_resolve_channel
    return channel, target


class TestInitialStreamSendChunking:
    def test_oversized_first_delta_is_split_across_sends(self) -> None:
        channel, target = _make_channel()
        oversized = "x" * (MAX_MESSAGE_LEN + 500)

        asyncio.run(channel.send_delta("12345", oversized, {"_stream_id": "s1"}))

        assert len(target.sent) == 2
        assert len(target.sent[0]) == MAX_MESSAGE_LEN
        assert len(target.sent[1]) == 500
        assert target.sent[0] + target.sent[1] == oversized

    def test_normal_sized_first_delta_is_sent_as_one_message(self) -> None:
        channel, target = _make_channel()

        asyncio.run(channel.send_delta("12345", "hello world", {"_stream_id": "s1"}))

        assert target.sent == ["hello world"]
