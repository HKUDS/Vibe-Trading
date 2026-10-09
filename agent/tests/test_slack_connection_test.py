"""Connection-test contract for the Slack channel.

Mirrors ``test_qq_connection_test.py``: Slack implements the standalone
two-leg credential probe (``auth.test`` for the bot token, then
``apps.connections.open`` for the app token / Socket Mode enablement) and
never touches the ``slack_sdk`` clients (which only exist after
``start()``). The contract codes the frontend dispatches on are
``ok | invalid_credentials | network`` plus an ``sdk_available`` flag, and
no token value or ``wss://`` URL may ever leak into the result or logs.
Slack-specific: the API answers HTTP 200 with ``{"ok": false, "error":
"invalid_auth"}`` for bad tokens, which the shared "200 but no token"
branch classifies as ``invalid_credentials``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest

from src.channels.bus.queue import MessageBus
from src.channels.slack import SlackChannel

AUTH_TEST_URL = "https://slack.com/api/auth.test"
CONNECTIONS_OPEN_URL = "https://slack.com/api/apps.connections.open"
BOT_TOKEN = "xoxb-test-bot-token-1234567890"
APP_TOKEN = "xapp-test-app-token-abcdefghij"
WSS_URL = "wss://wss-primary.slack.com/link/?ticket=do-not-leak"

# Captured before any test monkeypatches the class, so repeated injections in a
# single test still wrap the real client instead of the previous factory.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _make_channel(
    bot_token: str = BOT_TOKEN,
    app_token: str = APP_TOKEN,
    **overrides: Any,
) -> SlackChannel:
    """Build a Slack channel that has NOT been started (no sdk clients)."""
    return SlackChannel(
        {"bot_token": bot_token, "app_token": app_token, **overrides},
        MessageBus(),
    )


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
    """Answer both legs the way Slack answers valid credentials."""
    if str(request.url) == AUTH_TEST_URL:
        return httpx.Response(200, json={"ok": True, "user_id": "U12345"})
    if str(request.url) == CONNECTIONS_OPEN_URL:
        return httpx.Response(200, json={"ok": True, "url": WSS_URL})
    raise AssertionError(f"unexpected URL {request.url}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# Slack standalone probe — success
# --------------------------------------------------------------------------- #


def test_success_both_legs_ok_and_discards_wss_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _inject_mock_transport(monkeypatch, _ok_handler)
    channel = _make_channel()

    result = _run(channel.test_connection())

    assert result["ok"] is True
    assert result["code"] == "ok"
    # The delegate passes a constant True: slack.py imports slack_sdk
    # unconditionally, so a missing SDK means the class never imports.
    assert result["sdk_available"] is True
    # Two legs, in order, each with its own Bearer header and an empty body.
    assert [str(r.url) for r in requests] == [AUTH_TEST_URL, CONNECTIONS_OPEN_URL]
    assert requests[0].headers["authorization"] == f"Bearer {BOT_TOKEN}"
    assert requests[1].headers["authorization"] == f"Bearer {APP_TOKEN}"
    assert json.loads(requests[0].content.decode("utf-8")) == {}
    # The probe is standalone: it must not have created the sdk clients.
    assert channel._web_client is None
    assert channel._socket_client is None
    # Tokens and the wss:// URL are discarded, never returned.
    serialized = json.dumps(result)
    assert BOT_TOKEN not in serialized
    assert APP_TOKEN not in serialized
    assert WSS_URL not in serialized
    assert "wss://" not in serialized


# --------------------------------------------------------------------------- #
# Slack standalone probe — invalid credentials
# --------------------------------------------------------------------------- #


def test_bad_bot_token_200_ok_false_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slack answers bad tokens with HTTP 200 and ``ok: false``."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == AUTH_TEST_URL
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"].startswith("bot token:")
    assert result["sdk_available"] is True
    # Leg 2 never runs after a leg 1 failure.
    assert len(requests) == 1
    serialized = json.dumps(result)
    assert BOT_TOKEN not in serialized
    assert APP_TOKEN not in serialized


def test_socket_mode_disabled_reports_invalid_credentials_on_leg_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apps.connections.open`` rejects when Socket Mode is not enabled."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_TEST_URL:
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": False, "error": "not_allowed"})

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"].startswith("app token:")
    assert len(requests) == 2
    assert BOT_TOKEN not in json.dumps(result)
    assert APP_TOKEN not in json.dumps(result)


@pytest.mark.parametrize(
    ("bot_token", "app_token", "detail"),
    [
        ("", "", "missing bot token"),
        ("", APP_TOKEN, "missing bot token"),
        (BOT_TOKEN, "", "missing app token"),
    ],
)
def test_missing_tokens_short_circuit_without_network(
    monkeypatch: pytest.MonkeyPatch,
    bot_token: str,
    app_token: str,
    detail: str,
) -> None:
    """Socket mode needs both tokens (the ``start()`` guard), so a missing
    one is reported before any HTTP call happens."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call may happen without tokens")

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(bot_token, app_token).test_connection())

    assert requests == []
    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"] == detail
    # The short-circuit envelope is self-contained like every other branch.
    assert result["sdk_available"] is True


# --------------------------------------------------------------------------- #
# Slack standalone probe — network
# --------------------------------------------------------------------------- #


def test_transport_error_reports_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"
    assert result["detail"].startswith("bot token:")
    assert result["sdk_available"] is True
    assert BOT_TOKEN not in json.dumps(result)


def test_leg_two_server_error_reports_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_TEST_URL:
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(503, text="upstream exploded")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"
    assert result["detail"].startswith("app token:")


# --------------------------------------------------------------------------- #
# Secret hygiene
# --------------------------------------------------------------------------- #


def test_rejection_detail_scrubs_echoed_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both token values are declared secrets, so an echoing rejection body
    reaches the detail masked whichever leg produced it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_TEST_URL:
            return httpx.Response(401, text=f"bad token {BOT_TOKEN}")
        return httpx.Response(500, text=f"exploded with {APP_TOKEN}")

    _inject_mock_transport(monkeypatch, handler)

    leg1 = _run(_make_channel().test_connection())
    assert leg1["code"] == "invalid_credentials"
    assert leg1["detail"].startswith("bot token:")
    assert "***" in leg1["detail"]
    assert BOT_TOKEN not in json.dumps(leg1)

    # Force leg 2 to be the echoing leg.
    def leg2_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == AUTH_TEST_URL:
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(500, text=f"exploded with {APP_TOKEN}")

    _inject_mock_transport(monkeypatch, leg2_handler)
    leg2 = _run(_make_channel().test_connection())
    assert leg2["code"] == "network"
    assert leg2["detail"].startswith("app token:")
    assert APP_TOKEN not in json.dumps(leg2)


def test_probe_never_logs_tokens_or_wss_url(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _inject_mock_transport(monkeypatch, _ok_handler)

    with caplog.at_level(logging.DEBUG):
        result = _run(_make_channel().test_connection())

    assert result["code"] == "ok"
    assert BOT_TOKEN not in caplog.text
    assert APP_TOKEN not in caplog.text
    assert WSS_URL not in caplog.text
