"""Signal DM pairing under dm.policy="allowlist".

An owner approves a stranger's pairing code; that sender's DMs must then
reach the agent with their text. A sender who is not approved gets a
pairing code and nothing is published to the agent bus.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.channels import pairing
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.pairing import PAIRING_CODE_META_KEY
from src.channels.pairing import store as pairing_store
from src.channels.signal import SignalChannel, SignalConfig

OWNER = "+19990000000"
FRIEND = "+15550001111"
FRIEND_UUID = "6f1c2d3e-0000-4000-8000-1234567890ab"


@pytest.fixture(autouse=True)
def _isolated_pairing_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pairing_store, "_store_path", lambda: tmp_path / "pairing.json")


def _channel() -> tuple[SignalChannel, MessageBus, list[OutboundMessage]]:
    config = SignalConfig(enabled=True, phone_number="+10000000000")
    config.dm.enabled = True
    config.dm.policy = "allowlist"
    config.dm.allow_from = [OWNER]
    bus = MessageBus()
    channel = SignalChannel(config, bus)
    sent: list[OutboundMessage] = []

    async def fake_send(msg: OutboundMessage) -> None:
        sent.append(msg)

    async def no_typing(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    channel.send = fake_send  # type: ignore[method-assign]
    channel._start_typing = no_typing  # type: ignore[method-assign]
    return channel, bus, sent


def _dm(*, number: str, uuid: str | None = None, text: str) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "sourceNumber": number,
        "sourceName": "Friend",
        "dataMessage": {"message": text, "timestamp": 1},
    }
    if uuid is not None:
        envelope["sourceUuid"] = uuid
    return {"envelope": envelope}


def _published(bus: MessageBus) -> list[str]:
    contents = []
    while not bus.inbound.empty():
        contents.append(bus.inbound.get_nowait().content)
    return contents


def test_approved_sender_dm_reaches_the_agent_with_its_text() -> None:
    async def scenario() -> None:
        channel, bus, sent = _channel()
        pairing.approve_code(pairing.generate_code("signal", FRIEND))

        await channel._handle_receive_notification(
            _dm(number=FRIEND, text="What is AAPL's RSI?")
        )

        assert sent == []
        assert len(published := _published(bus)) == 1
        assert "What is AAPL's RSI?" in published[0]

    asyncio.run(scenario())


def test_code_approved_for_a_phone_and_uuid_sender_admits_that_sender() -> None:
    """signal-cli envelopes carry both sourceNumber and sourceUuid; the code is
    issued for the pipe-joined composite, so approval must match it."""

    async def scenario() -> None:
        channel, bus, sent = _channel()

        await channel._handle_receive_notification(
            _dm(number=FRIEND, uuid=FRIEND_UUID, text="hi")
        )
        assert len(sent) == 1
        code = sent[0].metadata[PAIRING_CODE_META_KEY]
        assert pairing.approve_code(code) == ("signal", f"{FRIEND}|{FRIEND_UUID}")
        sent.clear()

        await channel._handle_receive_notification(
            _dm(number=FRIEND, uuid=FRIEND_UUID, text="What is AAPL's RSI?")
        )

        assert sent == []
        assert len(published := _published(bus)) == 1
        assert "What is AAPL's RSI?" in published[0]

    asyncio.run(scenario())


def test_unknown_sender_gets_a_pairing_code_and_nothing_reaches_the_agent() -> None:
    async def scenario() -> None:
        channel, bus, sent = _channel()

        await channel._handle_receive_notification(_dm(number=FRIEND, text="hello"))

        assert len(sent) == 1
        assert sent[0].metadata.get(PAIRING_CODE_META_KEY)
        assert _published(bus) == []

    asyncio.run(scenario())


def test_allowlisted_owner_dm_is_unchanged() -> None:
    async def scenario() -> None:
        channel, bus, sent = _channel()

        await channel._handle_receive_notification(_dm(number=OWNER, text="status?"))

        assert sent == []
        assert len(published := _published(bus)) == 1
        assert "status?" in published[0]

    asyncio.run(scenario())


def test_dm_denied_by_dm_policy_never_reaches_the_agent_as_an_empty_message() -> None:
    """A sender allowed in groups (so the aggregate allow_from admits them) but
    not in dm.allow_from must get a pairing code for a DM, not have an empty
    prompt forwarded to the agent."""

    async def scenario() -> None:
        channel, bus, sent = _channel()
        channel.config.group.allow_from = [FRIEND]

        await channel._handle_receive_notification(_dm(number=FRIEND, text="hello"))

        assert _published(bus) == []
        assert len(sent) == 1
        assert sent[0].metadata.get(PAIRING_CODE_META_KEY)

    asyncio.run(scenario())


def test_disabled_dm_stays_disabled_after_pairing_approval() -> None:
    async def scenario() -> None:
        channel, bus, sent = _channel()
        pairing.approve_code(pairing.generate_code("signal", FRIEND))
        channel.config.dm.enabled = False
        await channel._handle_receive_notification(_dm(number=FRIEND, text="hello"))
        assert _published(bus) == []
        assert sent == []

    asyncio.run(scenario())


def test_open_dm_policy_still_admits_an_unpaired_sender() -> None:
    async def scenario() -> None:
        channel, bus, sent = _channel()
        channel.config.dm.policy = "open"
        await channel._handle_receive_notification(_dm(number=FRIEND, text="hello"))
        assert _published(bus) == ["hello"]
        assert sent == []

    asyncio.run(scenario())


def test_pairing_does_not_bypass_group_allowlist() -> None:
    async def scenario() -> None:
        channel, bus, sent = _channel()
        pairing.approve_code(pairing.generate_code("signal", FRIEND))
        channel.config.group.enabled = True
        channel.config.group.policy = "allowlist"
        channel.config.group.allow_from = ["another-group"]
        event = _dm(number=FRIEND, text="hello")
        event["envelope"]["dataMessage"]["groupInfo"] = {"groupId": "denied-group"}
        await channel._handle_receive_notification(event)
        assert _published(bus) == []
        assert sent == []

    asyncio.run(scenario())
