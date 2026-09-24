"""Connection-test contract for the Feishu/Lark channel.

Mirrors ``test_qq_connection_test.py``: Feishu implements the standalone
credential probe against the ``tenant_access_token`` endpoint and never
touches the lark SDK client (which only exists after ``start()``). The
contract codes the frontend dispatches on are ``ok | invalid_credentials |
network`` plus an ``sdk_available`` flag, and no credential or token value may
ever leak into the result or logs. Feishu-specific: the endpoint may answer
HTTP 200 with an error body (``{"code": 10014, ...}``) for bad credentials,
which the shared "200 but no token" branch classifies as
``invalid_credentials``, and ``domain="lark"`` switches the probe to the
Lark Suite host.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest

from src.channels.bus.queue import MessageBus
from src.channels.feishu import FEISHU_AVAILABLE, FeishuChannel

FEISHU_TOKEN_URL = (
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
)
LARK_TOKEN_URL = (
    "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
)
APP_ID = "cli_feishu_app_id_1234567890"
APP_SECRET = "feishu-app-secret-abcdefghij"
TENANT_TOKEN = "fresh-tenant-token-value-do-not-leak"

# Captured before any test monkeypatches the class, so repeated injections in a
# single test still wrap the real client instead of the previous factory.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _make_channel(
    app_id: str = APP_ID,
    app_secret: str = APP_SECRET,
    domain: str = "feishu",
) -> FeishuChannel:
    """Build a Feishu channel that has NOT been started (no lark client)."""
    return FeishuChannel(
        {"app_id": app_id, "app_secret": app_secret, "domain": domain},
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
# Feishu standalone probe — success
# --------------------------------------------------------------------------- #


def test_success_returns_ok_and_discards_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == FEISHU_TOKEN_URL
        assert request.method == "POST"
        assert json.loads(request.content.decode("utf-8")) == {
            "app_id": APP_ID,
            "app_secret": APP_SECRET,
        }
        return httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": TENANT_TOKEN, "expire": 7200},
        )

    requests = _inject_mock_transport(monkeypatch, handler)
    channel = _make_channel()

    result = _run(channel.test_connection())

    assert len(requests) == 1
    assert result["ok"] is True
    assert result["code"] == "ok"
    assert result["sdk_available"] is FEISHU_AVAILABLE
    # The probe is standalone: it must not have created the lark SDK client.
    assert channel._client is None
    # The token and secret are discarded, never returned.
    serialized = json.dumps(result)
    assert TENANT_TOKEN not in serialized
    assert APP_SECRET not in serialized


def test_success_uses_fresh_client_even_when_sdk_client_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A started channel's lark client must not be reused by the probe."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tenant_access_token": TENANT_TOKEN})

    requests = _inject_mock_transport(monkeypatch, handler)
    channel = _make_channel()
    sentinel = object()
    channel._client = sentinel  # pretend start() ran

    result = _run(channel.test_connection())

    assert result["ok"] is True
    assert len(requests) == 1
    assert channel._client is sentinel


# --------------------------------------------------------------------------- #
# Feishu standalone probe — domain routing
# --------------------------------------------------------------------------- #


def test_lark_domain_hits_larksuite_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == LARK_TOKEN_URL
        return httpx.Response(200, json={"tenant_access_token": TENANT_TOKEN})

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(domain="lark").test_connection())

    assert result["ok"] is True
    assert len(requests) == 1


def test_default_domain_hits_feishu_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == FEISHU_TOKEN_URL
        return httpx.Response(200, json={"tenant_access_token": TENANT_TOKEN})

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is True
    assert len(requests) == 1


# --------------------------------------------------------------------------- #
# Feishu standalone probe — invalid credentials
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", [400, 401, 403])
def test_http_client_error_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"msg": "invalid app_id/app_secret"})

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is FEISHU_AVAILABLE
    assert "detail" in result
    assert APP_SECRET not in json.dumps(result)
    assert TENANT_TOKEN not in json.dumps(result)


def test_http_200_error_body_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feishu answers bad credentials with HTTP 200 and an error body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10014, "msg": "app secret invalid"})

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is FEISHU_AVAILABLE
    assert APP_SECRET not in json.dumps(result)


@pytest.mark.parametrize("body", [b"null", b"[1, 2]", b'"oops"'])
def test_http_200_non_object_json_body_reports_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    """A 200 with valid non-object JSON must classify, never raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is FEISHU_AVAILABLE
    assert APP_SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    ("app_id", "app_secret"),
    [("", ""), (APP_ID, ""), ("", APP_SECRET)],
)
def test_missing_credentials_short_circuit_without_network(
    monkeypatch: pytest.MonkeyPatch,
    app_id: str,
    app_secret: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call may happen without credentials")

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(app_id, app_secret).test_connection())

    assert requests == []
    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"] == "missing credentials"
    # The short-circuit envelope is self-contained like every other branch.
    assert result["sdk_available"] is FEISHU_AVAILABLE


# --------------------------------------------------------------------------- #
# Feishu standalone probe — network
# --------------------------------------------------------------------------- #


def test_transport_error_reports_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"
    assert result["sdk_available"] is FEISHU_AVAILABLE
    assert APP_SECRET not in json.dumps(result)


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
        return httpx.Response(200, json={"tenant_access_token": TENANT_TOKEN})

    _inject_mock_transport(monkeypatch, ok_handler)
    with caplog.at_level(logging.DEBUG):
        success = _run(_make_channel().test_connection())

    def reject_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad secret {APP_SECRET}")

    _inject_mock_transport(monkeypatch, reject_handler)
    with caplog.at_level(logging.DEBUG):
        failure = _run(_make_channel().test_connection())

    assert success["code"] == "ok"
    assert failure["code"] == "invalid_credentials"
    assert APP_SECRET not in caplog.text
    assert TENANT_TOKEN not in caplog.text
    # And the rejection body's echoed secret is scrubbed from the detail too.
    assert APP_SECRET not in json.dumps(failure)


def test_rejection_detail_scrubs_echoed_secret_and_app_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, text=f"app_secret {APP_SECRET} is invalid for {APP_ID}"
        )

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel().test_connection())

    assert result["code"] == "invalid_credentials"
    assert APP_SECRET not in json.dumps(result)
    assert APP_ID not in json.dumps(result)
    assert "detail" in result
