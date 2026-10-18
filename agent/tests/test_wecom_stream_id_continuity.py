"""Regression: WeCom must reuse one stream_id across one logical reply."""

from __future__ import annotations

import asyncio
import itertools

from src.channels.bus.events import OutboundMessage
from src.channels.wecom import WecomChannel


def _make_channel() -> WecomChannel:
    channel = WecomChannel({"enabled": True, "bot_id": "x", "secret": "y"}, bus=None)
    channel._chat_frames["user123"] = {"headers": {"req_id": "abc"}}
    counter = itertools.count()
    channel._generate_req_id = lambda prefix: f"{prefix}_{next(counter)}"
    return channel


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    async def reply_stream(self, frame, stream_id, content, finish):  # noqa: ANN001
        self.calls.append((stream_id, content, finish))


class TestWecomStreamIdContinuity:
    """Progress chunks and the final answer of one turn must share a stream_id,
    otherwise WeCom treats each chunk as an unrelated message instead of one
    progressively updating reply.
    """

    def test_progress_and_final_share_the_injected_stream_id(self) -> None:
        channel = _make_channel()
        client = _FakeClient()
        channel._client = client
        attempt_id = "attempt-42"

        async def run() -> None:
            await channel.send(
                OutboundMessage(
                    channel="wecom", chat_id="user123", content="Thinking",
                    metadata={"_progress": True, "_stream_id": attempt_id},
                )
            )
            await channel.send(
                OutboundMessage(
                    channel="wecom", chat_id="user123", content="Still thinking",
                    metadata={"_progress": True, "_stream_id": attempt_id},
                )
            )
            await channel.send(
                OutboundMessage(
                    channel="wecom", chat_id="user123", content="Final answer",
                    metadata={"_stream_id": attempt_id},
                )
            )

        asyncio.run(run())

        stream_ids = [c[0] for c in client.calls]
        assert stream_ids == [attempt_id, attempt_id, attempt_id]
        assert [c[2] for c in client.calls] == [False, False, True]
        assert channel._stream_ids == {}

    def test_falls_back_to_a_stable_per_chat_id_when_no_stream_id_injected(self) -> None:
        channel = _make_channel()
        client = _FakeClient()
        channel._client = client

        async def run() -> None:
            await channel.send(
                OutboundMessage(
                    channel="wecom", chat_id="user123", content="Thinking",
                    metadata={"_progress": True},
                )
            )
            await channel.send(
                OutboundMessage(
                    channel="wecom", chat_id="user123", content="Final answer",
                    metadata={},
                )
            )

        asyncio.run(run())

        stream_ids = [c[0] for c in client.calls]
        assert stream_ids[0] == stream_ids[1]
        assert channel._stream_ids == {}

    def test_separate_chats_never_share_a_stream_id(self) -> None:
        channel = _make_channel()
        channel._chat_frames["user456"] = {"headers": {"req_id": "def"}}
        client = _FakeClient()
        channel._client = client

        async def run() -> None:
            await channel.send(
                OutboundMessage(channel="wecom", chat_id="user123", content="A", metadata={"_progress": True})
            )
            await channel.send(
                OutboundMessage(channel="wecom", chat_id="user456", content="B", metadata={"_progress": True})
            )

        asyncio.run(run())

        stream_ids = [c[0] for c in client.calls]
        assert stream_ids[0] != stream_ids[1]
