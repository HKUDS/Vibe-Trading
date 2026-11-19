"""Regression: a newly-subscribed Mochat session must drop only its first
watch response (the catch-up backlog), not the next real message too.

The long-poll fallback worker legitimately returns a response with no
"events" key at all on a timeout with nothing new. Clearing the cold flag
only when `events` happened to already be a list left the session stuck
"cold" across that eventless poll, so the very next response -- the one
carrying a real message -- was wrongly discarded as well.
"""

from __future__ import annotations

import asyncio

from src.channels.mochat import MochatChannel, MochatConfig


class _FakeBus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish_inbound(self, msg) -> None:
        self.published.append(msg)


def _make_channel() -> tuple[MochatChannel, _FakeBus]:
    config = MochatConfig(enabled=True, claw_token="tok", sessions=["sess1"], allow_from=["*"])
    bus = _FakeBus()
    channel = MochatChannel(config, bus)
    channel._cold_sessions.add("sess1")
    return channel, bus


class TestColdSessionBacklogDiscard:
    def test_eventless_timeout_response_clears_the_cold_flag(self) -> None:
        channel, _ = _make_channel()

        asyncio.run(channel._handle_watch_payload({"sessionId": "sess1", "cursor": 0}, "session"))

        assert "sess1" not in channel._cold_sessions

    def test_real_message_after_an_eventless_response_still_gets_dispatched(self) -> None:
        channel, bus = _make_channel()

        asyncio.run(channel._handle_watch_payload({"sessionId": "sess1", "cursor": 0}, "session"))
        payload = {
            "sessionId": "sess1",
            "cursor": 1,
            "events": [{
                "type": "message.add", "seq": 1,
                "payload": {"author": "user-123", "messageId": "m1", "content": "hello"},
            }],
        }
        asyncio.run(channel._handle_watch_payload(payload, "session"))

        assert len(bus.published) == 1
        assert bus.published[0].content == "hello"

    def test_first_response_with_real_events_is_still_discarded_as_backlog(self) -> None:
        channel, bus = _make_channel()
        payload = {
            "sessionId": "sess1",
            "cursor": 1,
            "events": [{
                "type": "message.add", "seq": 1,
                "payload": {"author": "user-123", "messageId": "m1", "content": "backlog message"},
            }],
        }

        asyncio.run(channel._handle_watch_payload(payload, "session"))

        assert "sess1" not in channel._cold_sessions
        assert bus.published == []
