"""An unauthorized DM sender under dm.policy="allowlist" must receive a
pairing code, not have their message silently forwarded (or dropped with
no feedback at all)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from tests.slack_stubs import install_slack_stubs

install_slack_stubs()

from slack_sdk.socket_mode.request import SocketModeRequest  # noqa: E402

from src.channels.bus.events import OutboundMessage  # noqa: E402
from src.channels.pairing import PAIRING_CODE_META_KEY  # noqa: E402
from src.channels.slack import SlackChannel, SlackConfig  # noqa: E402


def _channel() -> SlackChannel:
    config = SlackConfig(enabled=True, bot_token="xoxb-test", app_token="xapp-test")
    config.dm.policy = "allowlist"
    config.dm.allow_from = ["U_OWNER"]
    channel = object.__new__(SlackChannel)
    channel.config = config
    channel._bot_user_id = None
    channel.logger = __import__("logging").getLogger("test.slack")
    return channel


def test_unauthorized_dm_sender_gets_a_pairing_code() -> None:
    async def scenario() -> None:
        channel = _channel()
        channel.send = AsyncMock()

        client = AsyncMock()
        req = SocketModeRequest(
            type="events_api",
            envelope_id="env-1",
            payload={
                "event": {
                    "type": "message",
                    "user": "U_RANDOM",
                    "channel": "D123",
                    "channel_type": "im",
                    "text": "hello",
                }
            },
        )

        await channel._on_socket_request(client, req)

        channel.send.assert_awaited_once()
        sent: OutboundMessage = channel.send.await_args.args[0]
        assert sent.chat_id == "D123"
        assert PAIRING_CODE_META_KEY in sent.metadata

    asyncio.run(scenario())


def test_authorized_dm_sender_is_unaffected() -> None:
    async def scenario() -> None:
        channel = _channel()
        channel.send = AsyncMock()
        channel._handle_message = AsyncMock()
        channel._should_respond_in_channel = lambda *a, **k: True
        channel._strip_bot_mention = lambda text: text
        channel._with_thread_context = AsyncMock(return_value="hello")
        channel._web_client = None
        channel.config.reply_in_thread = False

        client = AsyncMock()
        req = SocketModeRequest(
            type="events_api",
            envelope_id="env-2",
            payload={
                "event": {
                    "type": "message",
                    "user": "U_OWNER",
                    "channel": "D123",
                    "channel_type": "im",
                    "text": "hello",
                    "ts": "1.1",
                }
            },
        )

        await channel._on_socket_request(client, req)

        channel.send.assert_not_awaited()
        channel._handle_message.assert_awaited_once()

    asyncio.run(scenario())
