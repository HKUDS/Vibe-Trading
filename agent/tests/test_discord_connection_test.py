"""Connection-test contract for the Discord channel.

Mirrors ``test_slack_connection_test.py``: Discord implements the standalone
bot-token probe (``GET /api/v10/users/@me`` with an ``Authorization: Bot``
header) and never touches the ``discord.py`` client (which only exists after
``start()``). The contract codes the frontend dispatches on are ``ok |
invalid_credentials | network`` plus an ``sdk_available`` flag, and no token
value may ever leak into the result or logs. Discord-specific: a valid BOT
token answers 200 with ``"bot": true`` in the user object, while a pasted
OAuth *user* token answers 200 WITHOUT the flag — the shared "200 but
token_key missing/falsy" branch classifies that as ``invalid_credentials``,
catching the wrong token type at probe time. Unlike slack (constant True),
the adapter delegate passes the real ``DISCORD_AVAILABLE`` guard, so the
envelope echoes it in both states. The adapter itself imports without the
``discord`` SDK installed, which is the state of CI and this test env.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest

import src.channels.discord as discord_channel
from src.channels import discord_probe
from src.channels.bus.queue import MessageBus
from src.channels.discord import DISCORD_AVAILABLE, DiscordChannel, DiscordConfig

USERS_ME_URL = "https://discord.com/api/v10/users/@me"
BOT_TOKEN = "fake-bot-token-do-not-leak-1234567890"
BOT_USER_BODY = {"id": "123", "username": "probe", "bot": True}

# Captured before any test monkeypatches the class, so repeated injections in a
# single test still wrap the real client instead of the previous factory.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _make_channel(token: str = BOT_TOKEN, **overrides: Any) -> DiscordChannel:
    """Build a Discord channel that has NOT been started (no discord.py client)."""
    return DiscordChannel({"token": token, **overrides}, MessageBus())


def _inject_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: "Any",
) -> list[httpx.Request]:
    """Route the probe's fresh ``httpx.AsyncClient`` through a MockTransport.

    The probe owns its client, so the only seam is the client class itself. The
    real class is kept and a ``transport`` is supplied, so every other client
    behaviour (timeout argument, context-manager close) still runs for real.
    """
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording_handler)
    real_client_cls = _REAL_ASYNC_CLIENT

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return requests


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """Answer the leg the way Discord answers a valid bot token."""
    assert str(request.url) == USERS_ME_URL
    assert request.method == "GET"
    assert request.headers["authorization"] == f"Bot {BOT_TOKEN}"
    # A GET must carry no JSON body.
    assert request.content == b""
    return httpx.Response(200, json=BOT_USER_BODY)


# --------------------------------------------------------------------------- #
# Discord standalone probe — success
# --------------------------------------------------------------------------- #


def test_success_valid_bot_token_returns_ok_and_discards_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _inject_mock_transport(monkeypatch, _ok_handler)
    channel = _make_channel()

    result = _run(channel.test_connection())

    assert result["ok"] is True
    assert result["code"] == "ok"
    assert result["sdk_available"] is DISCORD_AVAILABLE
    assert len(requests) == 1
    # The probe is standalone: it must not have created the discord.py client.
    assert channel._client is None
    # The token and the success body (bot username/id) are discarded.
    serialized = json.dumps(result)
    assert BOT_TOKEN not in serialized
    assert "username" not in serialized
    assert set(result) == {"ok", "code", "sdk_available"}


def test_success_uses_fresh_client_even_when_sdk_client_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A started channel's discord.py client must not be reused by the probe."""
    requests = _inject_mock_transport(monkeypatch, _ok_handler)
    channel = _make_channel()
    sentinel = object()
    channel._client = sentinel  # pretend start() ran

    result = _run(channel.test_connection())

    assert result["ok"] is True
    assert len(requests) == 1
    assert channel._client is sentinel


# --------------------------------------------------------------------------- #
# Discord standalone probe — invalid credentials
# --------------------------------------------------------------------------- #


def test_user_token_200_without_bot_flag_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pasted OAuth *user* token answers 200 without ``"bot": true``.

    ``token_key="bot"`` routes that through the shared "200 but token_key
    missing/falsy" branch: a user token cannot open a bot gateway session,
    so the wrong token type must be caught at probe time, not at start().
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "456", "username": "human"})

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is DISCORD_AVAILABLE
    assert len(requests) == 1
    serialized = json.dumps(result)
    assert BOT_TOKEN not in serialized
    assert "human" not in serialized


def test_http_401_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "401: Unauthorized"})

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is DISCORD_AVAILABLE
    assert "detail" in result
    assert BOT_TOKEN not in json.dumps(result)


def test_missing_token_short_circuits_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``start()`` guard rejects an empty token, so the probe reports it
    before any HTTP call happens."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call may happen without a token")

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(token="").test_connection())

    assert requests == []
    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"] == "missing bot token"
    # The short-circuit envelope is self-contained like every other branch.
    assert result["sdk_available"] is DISCORD_AVAILABLE


# --------------------------------------------------------------------------- #
# Discord standalone probe — network
# --------------------------------------------------------------------------- #


def test_transport_error_reports_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"
    assert result["sdk_available"] is DISCORD_AVAILABLE
    assert BOT_TOKEN not in json.dumps(result)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_reports_network(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="upstream exploded")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"


# --------------------------------------------------------------------------- #
# sdk_available echo — both states, probe level and adapter level
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag", [True, False])
def test_probe_echoes_sdk_available_in_both_states(flag: bool) -> None:
    """The probe is stateless: whatever the caller passes is echoed back."""
    result = _run(
        discord_probe.test_connection(DiscordConfig(token=""), sdk_available=flag)
    )
    assert result["sdk_available"] is flag


@pytest.mark.parametrize("flag", [True, False])
def test_adapter_delegate_passes_the_real_availability_guard(
    monkeypatch: pytest.MonkeyPatch, flag: bool
) -> None:
    """Unlike slack's constant True, the delegate reads DISCORD_AVAILABLE at
    call time, so the envelope reports the SDK state honestly."""
    monkeypatch.setattr(discord_channel, "DISCORD_AVAILABLE", flag)
    result = _run(_make_channel(token="").test_connection())
    assert result["sdk_available"] is flag


# --------------------------------------------------------------------------- #
# Secret hygiene
# --------------------------------------------------------------------------- #


def test_rejection_detail_scrubs_echoed_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token is declared a secret, so an echoing rejection body reaches
    the detail masked."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad token {BOT_TOKEN}")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["code"] == "invalid_credentials"
    assert "***" in result["detail"]
    assert BOT_TOKEN not in json.dumps(result)


def test_probe_never_logs_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _inject_mock_transport(monkeypatch, _ok_handler)

    with caplog.at_level(logging.DEBUG):
        result = _run(_make_channel().test_connection())

    assert result["code"] == "ok"
    assert BOT_TOKEN not in caplog.text


# --------------------------------------------------------------------------- #
# Adapter wiring
# --------------------------------------------------------------------------- #


def test_adapter_imports_without_the_sdk_and_declares_support() -> None:
    """discord.py guards the SDK behind DISCORD_AVAILABLE, so the adapter and
    its probe delegate import in an SDK-less environment (CI, this test env)."""
    assert isinstance(DISCORD_AVAILABLE, bool)
    assert DiscordChannel.supports_connection_test is True
