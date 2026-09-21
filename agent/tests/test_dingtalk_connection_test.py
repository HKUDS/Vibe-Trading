"""Connection-test contract for IM channels.

Task 2 of the web IM channel-config plan: the base channel exposes a generic
``test_connection`` hook (default ``unsupported``), and DingTalk implements a
standalone credential probe that never touches ``self._http`` (which only exists
after ``start()``). The contract codes the frontend dispatches on are
``ok | invalid_credentials | network | unsupported`` plus an ``sdk_available``
flag, and no credential or token value may ever leak into the result or logs.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any

import httpx
import pytest

from src.channels.base import BaseChannel
from src.channels.bus.queue import MessageBus
from src.channels.dingtalk import DINGTALK_AVAILABLE, DingTalkChannel

TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
CLIENT_ID = "ding-client-id-1234567890"
CLIENT_SECRET = "ding-client-secret-abcdefghij"
ACCESS_TOKEN = "fresh-access-token-value-do-not-leak"

# Captured before any test monkeypatches the class, so repeated injections in a
# single test still wrap the real client instead of the previous factory.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

# Other adapters whose *default* ``test_connection`` must report ``unsupported``.
# Modules whose optional SDK is absent are skipped at runtime rather than
# removed from the parametrization, so coverage grows wherever deps are installed.
_DEFAULT_CHANNEL_CANDIDATES: list[tuple[str, str]] = [
    ("src.channels.discord", "DiscordChannel"),
    ("src.channels.telegram", "TelegramChannel"),
    ("src.channels.slack", "SlackChannel"),
    ("src.channels.feishu", "FeishuChannel"),
    ("src.channels.wecom", "WecomChannel"),
]


def _make_channel(
    client_id: str = CLIENT_ID,
    client_secret: str = CLIENT_SECRET,
) -> DingTalkChannel:
    """Build a DingTalk channel that has NOT been started (no ``self._http``)."""
    return DingTalkChannel(
        {"client_id": client_id, "client_secret": client_secret},
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


# --------------------------------------------------------------------------- #
# BaseChannel default hook
# --------------------------------------------------------------------------- #


def test_base_channel_declares_no_connection_test() -> None:
    assert BaseChannel.supports_connection_test is False


def test_base_channel_default_returns_unsupported() -> None:
    class _Probe(BaseChannel):
        async def start(self) -> None:  # pragma: no cover - abstract filler
            return None

        async def stop(self) -> None:  # pragma: no cover - abstract filler
            return None

        async def send(self, msg: Any) -> None:  # pragma: no cover - filler
            return None

    result = _run(_Probe({}, MessageBus()).test_connection())

    assert result == {"ok": False, "code": "unsupported"}


@pytest.mark.parametrize(("module_name", "class_name"), _DEFAULT_CHANNEL_CANDIDATES)
def test_other_adapters_default_to_unsupported(
    module_name: str,
    class_name: str,
) -> None:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:  # optional SDK not installed here
        pytest.skip(f"{module_name} dependency unavailable: {exc}")

    channel_cls = getattr(module, class_name)
    assert channel_cls.supports_connection_test is False

    channel = channel_cls({}, MessageBus())
    result = _run(channel.test_connection())

    assert result == {"ok": False, "code": "unsupported"}


# --------------------------------------------------------------------------- #
# DingTalk standalone probe — success
# --------------------------------------------------------------------------- #


def test_success_returns_ok_and_discards_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        assert request.method == "POST"
        assert json.loads(request.content.decode("utf-8")) == {
            "appKey": CLIENT_ID,
            "appSecret": CLIENT_SECRET,
        }
        return httpx.Response(
            200,
            json={"accessToken": ACCESS_TOKEN, "expireIn": 7200},
        )

    requests = _inject_mock_transport(monkeypatch, handler)
    channel = _make_channel()

    result = _run(channel.test_connection())

    assert len(requests) == 1
    assert result["ok"] is True
    assert result["code"] == "ok"
    assert result["sdk_available"] is DINGTALK_AVAILABLE
    # The probe is standalone: it must not have created the shared client.
    assert channel._http is None
    # The token and secret are discarded, never returned.
    serialized = json.dumps(result)
    assert ACCESS_TOKEN not in serialized
    assert CLIENT_SECRET not in serialized


def test_success_uses_fresh_client_even_when_shared_client_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A started channel's ``_http`` must not be reused by the probe."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accessToken": ACCESS_TOKEN})

    requests = _inject_mock_transport(monkeypatch, handler)
    channel = _make_channel()
    sentinel = object()
    channel._http = sentinel  # pretend start() ran

    result = _run(channel.test_connection())

    assert result["ok"] is True
    assert len(requests) == 1
    assert channel._http is sentinel


# --------------------------------------------------------------------------- #
# DingTalk standalone probe — invalid credentials
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", [400, 401, 403])
def test_http_client_error_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "invalid appKey/appSecret"})

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is DINGTALK_AVAILABLE
    assert "detail" in result
    assert CLIENT_SECRET not in json.dumps(result)
    assert ACCESS_TOKEN not in json.dumps(result)


def test_missing_token_in_ok_response_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "no token for you"})

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert CLIENT_SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    ("client_id", "client_secret"),
    [("", ""), (CLIENT_ID, ""), ("", CLIENT_SECRET)],
)
def test_missing_credentials_short_circuit_without_network(
    monkeypatch: pytest.MonkeyPatch,
    client_id: str,
    client_secret: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call may happen without credentials")

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(client_id, client_secret).test_connection())

    assert requests == []
    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"] == "missing credentials"


# --------------------------------------------------------------------------- #
# DingTalk standalone probe — network
# --------------------------------------------------------------------------- #


def test_transport_error_reports_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"
    assert result["sdk_available"] is DINGTALK_AVAILABLE
    assert CLIENT_SECRET not in json.dumps(result)


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
# Secret hygiene
# --------------------------------------------------------------------------- #


def test_probe_never_logs_secret_or_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accessToken": ACCESS_TOKEN})

    _inject_mock_transport(monkeypatch, ok_handler)
    with caplog.at_level(logging.DEBUG):
        success = _run(_make_channel().test_connection())

    def reject_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad secret {CLIENT_SECRET}")

    _inject_mock_transport(monkeypatch, reject_handler)
    with caplog.at_level(logging.DEBUG):
        failure = _run(_make_channel().test_connection())

    assert success["code"] == "ok"
    assert failure["code"] == "invalid_credentials"
    assert CLIENT_SECRET not in caplog.text
    assert ACCESS_TOKEN not in caplog.text
    # And the rejection body's echoed secret is scrubbed from the detail too.
    assert CLIENT_SECRET not in json.dumps(failure)


def test_rejection_detail_scrubs_echoed_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"appSecret {CLIENT_SECRET} is invalid")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["code"] == "invalid_credentials"
    assert CLIENT_SECRET not in json.dumps(result)
    assert "detail" in result
