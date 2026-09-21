"""Regression tests for DingTalk inbound routing and stream task shutdown.

Covers two production defects found during live QA:
- ``_on_message`` never forwarded ``is_dm``, so unapproved DMs logged
  "Access denied" instead of receiving a pairing code.
- ``stop()`` never terminated the SDK stream loop (which swallows the first
  ``CancelledError``), leaving a zombie WebSocket after disable/hot-swap.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.channels.bus.queue import MessageBus
from src.channels.dingtalk import DingTalkChannel


def _make_channel() -> DingTalkChannel:
    return DingTalkChannel({"client_id": "cid", "client_secret": "sec"}, MessageBus())


def _record_handle(channel: DingTalkChannel) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []

    async def fake_handle(**kwargs: Any) -> None:
        recorded.append(kwargs)

    channel._handle_message = fake_handle
    return recorded


def test_dm_message_is_flagged_as_dm() -> None:
    async def scenario() -> None:
        channel = _make_channel()
        recorded = _record_handle(channel)

        await channel._on_message("hello", "264099", "Alice", "1", None)

        assert recorded[0]["is_dm"] is True
        assert recorded[0]["chat_id"] == "264099"

    asyncio.run(scenario())


def test_group_message_is_not_dm_and_uses_group_chat_id() -> None:
    async def scenario() -> None:
        channel = _make_channel()
        recorded = _record_handle(channel)

        await channel._on_message("hello", "264099", "Alice", "2", "cidXYZ")

        assert recorded[0]["is_dm"] is False
        assert recorded[0]["chat_id"] == "group:cidXYZ"

    asyncio.run(scenario())


def test_stop_terminates_cancel_swallowing_stream_task() -> None:
    """The SDK start loop swallows one CancelledError; stop must still kill it."""

    async def scenario() -> None:
        channel = _make_channel()

        async def sdk_like_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    await asyncio.sleep(30)

        task = asyncio.create_task(sdk_like_loop())
        await asyncio.sleep(0)
        channel._stream_task = task

        await channel.stop()

        assert task.done()
        assert task.cancelled()

    asyncio.run(scenario())


def test_stop_without_stream_task_is_safe() -> None:
    async def scenario() -> None:
        channel = _make_channel()

        await channel.stop()

        assert channel._stream_task is None
        assert channel.is_running is False

    asyncio.run(scenario())


def test_force_ipv4_binds_transport_to_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    """DingTalk's send API enforces the app egress-IP whitelist; force_ipv4 pins it."""
    import httpx

    from src.channels import dingtalk as dingtalk_mod

    captured: list[dict[str, Any]] = []
    real_transport_cls = httpx.AsyncHTTPTransport

    def spy(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return real_transport_cls(**kwargs)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", spy)

    pinned = DingTalkChannel(
        {"client_id": "cid", "client_secret": "sec", "force_ipv4": True}, MessageBus()
    )
    transport = dingtalk_mod._build_http_transport(pinned.config)
    assert transport is not None
    assert captured == [{"local_address": "0.0.0.0"}]

    default = _make_channel()
    assert dingtalk_mod._build_http_transport(default.config) is None
    assert len(captured) == 1
