"""Contracts for the IM channel runtime wiring."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest

from src.channels.bus.events import InboundMessage, OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.manager import ChannelManager
from src.channels.registry import discover_channel_names, inspect_channels
from src.channelsui.cli_apps_api import normalize_cli_app_mentions
from src.channelsui.gateway_services import build_gateway_services
from src.channelsui.mcp_presets_api import normalize_mcp_preset_mentions
from src.channelsui.transcription_ws import webui_transcription_event
from src.session.goal_state import goal_state_ws_blob
from src.session.models import Message, Session
from src.session.webui_turns import (
    clear_websocket_turn_started,
    mark_websocket_turn_started,
    websocket_turn_wall_started_at,
)
from src.utils.media_decode import FileSizeExceeded, save_base64_data_url


class FakeSessionService:
    """Small SessionService stand-in for channel runtime tests."""

    def __init__(self) -> None:
        self.created: list[Session] = []
        self.sent: list[tuple[str, str]] = []
        self.messages: dict[str, list[Message]] = {}

    def create_session(self, title: str = "", config: dict[str, Any] | None = None) -> Session:
        session = Session(session_id=f"session-{len(self.created) + 1}", title=title, config=config or {})
        self.created.append(session)
        self.messages[session.session_id] = []
        return session

    def get_session(self, session_id: str) -> Session | None:
        return next((session for session in self.created if session.session_id == session_id), None)

    async def send_message(
        self,
        session_id: str,
        content: str,
        *,
        include_shell_tools: bool = False,
        parent_attempt_id: str | None = None,
    ) -> dict[str, str]:
        del include_shell_tools, parent_attempt_id
        self.sent.append((session_id, content))
        attempt_id = f"attempt-{len(self.sent)}"
        self.messages[session_id].append(
            Message(
                session_id=session_id,
                role="assistant",
                content=f"agent reply: {content}",
                linked_attempt_id=attempt_id,
            )
        )
        return {"message_id": "msg-1", "attempt_id": attempt_id}

    def get_messages(self, session_id: str, limit: int = 100) -> list[Message]:
        del limit
        return list(self.messages.get(session_id, []))


def test_channel_manager_can_construct_websocket_with_default_gateway() -> None:
    bus = MessageBus()
    manager = ChannelManager(
        {"websocket": {"enabled": True, "host": "127.0.0.1", "port": 0, "allow_from": ["*"]}},
        bus,
    )

    assert "websocket" in manager.channels
    assert manager.channels["websocket"].name == "websocket"


def test_registry_reports_all_built_in_channels_with_dependency_recovery() -> None:
    expected = {
        "dingtalk",
        "discord",
        "email",
        "feishu",
        "matrix",
        "mochat",
        "msteams",
        "napcat",
        "qq",
        "signal",
        "slack",
        "telegram",
        "websocket",
        "wecom",
        "weixin",
        "whatsapp",
    }

    assert expected.issubset(set(discover_channel_names()))
    assert {"config", "runtime"}.isdisjoint(set(discover_channel_names()))

    statuses = inspect_channels({"telegram": {"enabled": True}, "slack": {"enabled": True}})

    for name in expected:
        assert name in statuses
        assert statuses[name]["name"] == name
        assert "install_hint" in statuses[name]
        assert "available" in statuses[name]

    missing = [item for item in statuses.values() if not item["available"]]
    assert all(item["install_hint"].startswith("pip install") for item in missing)


def test_channel_manager_status_includes_every_configured_adapter() -> None:
    bus = MessageBus()
    manager = ChannelManager(
        {
            "send_max_retries": 1,
            "websocket": {"enabled": True, "host": "127.0.0.1", "port": 0, "allow_from": ["*"]},
            "telegram": {"enabled": False},
            "slack": {"enabled": True},
        },
        bus,
    )

    status = manager.get_status()

    assert status["websocket"]["loaded"] is True
    assert status["websocket"]["enabled"] is True
    assert status["telegram"]["configured"] is True
    assert status["telegram"]["enabled"] is False
    assert status["slack"]["configured"] is True
    assert status["slack"]["enabled"] is True
    assert "available" in status["slack"]
    if not status["slack"]["loaded"]:
        assert status["slack"]["error"]
        assert status["slack"]["install_hint"].startswith("pip install")


def test_registry_marks_lazy_sdk_adapter_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.channels.discord as discord_channel

    from src.channels.registry import inspect_channel

    monkeypatch.setattr(discord_channel, "DISCORD_AVAILABLE", False)

    status = inspect_channel("discord").to_dict()

    assert status["available"] is False
    assert status["install_hint"] == "pip install 'vibe-trading-ai[discord]'"


def test_channel_manager_skips_enabled_adapter_when_lazy_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.channels.discord as discord_channel

    monkeypatch.setattr(discord_channel, "DISCORD_AVAILABLE", False)

    manager = ChannelManager({"discord": {"enabled": True, "token": "x"}}, MessageBus())
    status = manager.get_status()["discord"]

    assert "discord" not in manager.channels
    assert status["enabled"] is True
    assert status["available"] is False
    assert status["loaded"] is False
    assert status["install_hint"] == "pip install 'vibe-trading-ai[discord]'"


def test_websocket_turn_wall_accepts_optional_chat_id() -> None:
    assert websocket_turn_wall_started_at("chat-1") is None
    mark_websocket_turn_started("chat-1", 123.0)
    assert websocket_turn_wall_started_at("chat-1") == 123.0
    clear_websocket_turn_started("chat-1")
    assert websocket_turn_wall_started_at("chat-1") is None


def test_websocket_compatibility_helpers_have_structured_behavior() -> None:
    assert goal_state_ws_blob({"active_goal": {"goal_id": "g1"}}) == {
        "active": True,
        "active_goals": [{"goal_id": "g1"}],
        "completed_goals": [],
    }
    assert normalize_cli_app_mentions("@codex, terminal") == ["codex", "terminal"]
    assert normalize_mcp_preset_mentions(["@research", "market"]) == ["research", "market"]


def test_gateway_services_adapt_session_service_for_hydration() -> None:
    service = FakeSessionService()
    session = service.create_session(title="chat", config={"metadata": {"active_goal": {"goal_id": "g1"}}})
    gateway = build_gateway_services(session_manager=service)

    row = gateway.session_manager.read_session_file(session.session_id)

    assert row["metadata"] == {"active_goal": {"goal_id": "g1"}}


def test_transcription_event_returns_structured_error() -> None:
    async def scenario() -> None:
        event, payload = await webui_transcription_event({"type": "transcribe_audio"})
        assert event == "error"
        assert "not configured" in payload["detail"]

    asyncio.run(scenario())


def test_save_base64_data_url_decodes_and_limits_size(tmp_path: Path) -> None:
    payload = base64.b64encode(b"hello").decode("ascii")

    saved = save_base64_data_url(f"data:text/plain;base64,{payload}", tmp_path, max_bytes=10)

    assert saved.read_text(encoding="utf-8") == "hello"
    assert saved.suffix == ".txt"

    with pytest.raises(FileSizeExceeded):
        save_base64_data_url(f"data:text/plain;base64,{payload}", tmp_path, max_bytes=4)

    with pytest.raises(ValueError):
        save_base64_data_url("not-a-data-url", tmp_path, max_bytes=10)


def test_channel_runtime_routes_inbound_to_session_and_outbound(tmp_path: Path) -> None:
    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=tmp_path / "channel_sessions.json",
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            await bus.publish_inbound(
                InboundMessage(
                    channel="websocket",
                    sender_id="user-1",
                    chat_id="chat-1",
                    content="hello from IM",
                )
            )

            outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        finally:
            await runtime.stop()

        assert service.sent == [("session-1", "hello from IM")]
        assert outbound == OutboundMessage(
            channel="websocket",
            chat_id="chat-1",
            content="agent reply: hello from IM",
            metadata={
                "_channel_runtime": True,
                "attempt_id": "attempt-1",
                "session_id": "session-1",
            },
        )

    asyncio.run(scenario())


def test_channel_runtime_handles_pairing_commands_without_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        monkeypatch.setenv("VIBE_TRADING_DATA_DIR", str(tmp_path / "data"))
        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=tmp_path / "channel_sessions.json",
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            await bus.publish_inbound(
                InboundMessage(
                    channel="telegram",
                    sender_id="owner",
                    chat_id="chat-1",
                    content="/PAIRING LIST",
                )
            )
            outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        finally:
            await runtime.stop()

        assert service.sent == []
        assert outbound.channel == "telegram"
        assert outbound.chat_id == "chat-1"
        assert "No pending pairing requests" in outbound.content
        assert outbound.metadata["_pairing_command"] is True

    asyncio.run(scenario())


def test_channel_runtime_new_command_resets_session_and_creates_fresh_one(tmp_path: Path) -> None:
    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=tmp_path / "channel_sessions.json",
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            await bus.publish_inbound(
                InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="hello")
            )
            reply1 = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
            assert reply1.metadata["session_id"] == "session-1"

            await bus.publish_inbound(
                InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="/new")
            )
            reset_reply = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
            assert "Session reset" in reset_reply.content
            assert reset_reply.metadata.get("session_reset") is True

            await bus.publish_inbound(
                InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="after reset")
            )
            reply2 = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
            assert reply2.metadata["session_id"] == "session-2"
        finally:
            await runtime.stop()

        assert service.sent == [("session-1", "hello"), ("session-2", "after reset")]

    asyncio.run(scenario())


def test_channel_runtime_new_command_with_no_existing_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=tmp_path / "channel_sessions.json",
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            await bus.publish_inbound(
                InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/new")
            )
            reply = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        finally:
            await runtime.stop()

        assert "No active session to reset" in reply.content
        assert reply.metadata.get("session_reset") is True
        assert service.sent == []
        assert len(service.created) == 0

    asyncio.run(scenario())


def test_channel_runtime_reset_and_newsession_aliases_work(tmp_path: Path) -> None:
    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=tmp_path / "channel_sessions.json",
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            await bus.publish_inbound(
                InboundMessage(channel="discord", sender_id="u1", chat_id="c1", content="hi")
            )
            await asyncio.wait_for(bus.consume_outbound(), timeout=1)

            await bus.publish_inbound(
                InboundMessage(channel="discord", sender_id="u1", chat_id="c1", content="/reset")
            )
            reply = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
            assert "Session reset" in reply.content

            await bus.publish_inbound(
                InboundMessage(channel="discord", sender_id="u1", chat_id="c1", content="hi again")
            )
            await asyncio.wait_for(bus.consume_outbound(), timeout=1)

            await bus.publish_inbound(
                InboundMessage(channel="discord", sender_id="u1", chat_id="c1", content="/newsession")
            )
            reply2 = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
            assert "Session reset" in reply2.content
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_channel_runtime_regular_messages_not_intercepted_as_new_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=tmp_path / "channel_sessions.json",
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            for text in ["hello /new world", "/new stuff", "/NEW YORK", "type /new to reset"]:
                await bus.publish_inbound(
                    InboundMessage(channel="slack", sender_id="u1", chat_id="c1", content=text)
                )
                reply = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
                assert reply.metadata.get("session_reset") is not True
                assert "agent reply:" in reply.content
        finally:
            await runtime.stop()

        assert len(service.sent) == 4

    asyncio.run(scenario())


def test_channel_runtime_session_map_persisted_after_reset(tmp_path: Path) -> None:
    import json

    async def scenario() -> None:
        from src.channels.runtime import ChannelRuntime

        map_path = tmp_path / "channel_sessions.json"
        bus = MessageBus()
        service = FakeSessionService()
        runtime = ChannelRuntime(
            bus=bus,
            session_service=service,
            manager=None,
            session_map_path=map_path,
            reply_timeout_s=1,
            poll_interval_s=0.01,
        )
        await runtime.start(start_manager=False)
        try:
            await bus.publish_inbound(
                InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="hi")
            )
            await asyncio.wait_for(bus.consume_outbound(), timeout=1)

            data = json.loads(map_path.read_text(encoding="utf-8"))
            assert data["feishu:c1"] == "session-1"

            await bus.publish_inbound(
                InboundMessage(channel="feishu", sender_id="u1", chat_id="c1", content="/new")
            )
            await asyncio.wait_for(bus.consume_outbound(), timeout=1)

            data = json.loads(map_path.read_text(encoding="utf-8"))
            assert "feishu:c1" not in data
        finally:
            await runtime.stop()

    asyncio.run(scenario())
