"""Connection-test contract for the QQ channel.

Mirrors ``test_dingtalk_connection_test.py``: QQ implements the standalone
credential probe against ``getAppAccessToken`` and never touches
``self._http`` (which only exists after ``start()``). The contract codes the
frontend dispatches on are ``ok | invalid_credentials | network`` plus an
``sdk_available`` flag, and no credential or token value may ever leak into
the result or logs. QQ-specific: the endpoint may answer HTTP 200 with an
error body (``{"code": 100007, ...}``) for bad credentials, which the shared
"200 but no token" branch classifies as ``invalid_credentials``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.channels.bus.queue import MessageBus
from src.channels.qq import QQ_AVAILABLE, QQChannel

TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
APP_ID = "qq-app-id-1234567890"
SECRET = "qq-client-secret-abcdefghij"
ACCESS_TOKEN = "fresh-access-token-value-do-not-leak"

# Captured before any test monkeypatches the class, so repeated injections in a
# single test still wrap the real client instead of the previous factory.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _make_channel(
    tmp_path: Path,
    app_id: str = APP_ID,
    secret: str = SECRET,
) -> QQChannel:
    """Build a QQ channel that has NOT been started (no ``self._http``).

    ``media_dir`` is pinned under ``tmp_path`` so any media-root creation
    (``_ensure_media_root``, downloads) stays inside the test sandbox.
    """
    return QQChannel(
        {
            "app_id": app_id,
            "secret": secret,
            "media_dir": str(tmp_path / "qq-media"),
        },
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
# QQ standalone probe — success
# --------------------------------------------------------------------------- #


def test_success_returns_ok_and_discards_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        assert request.method == "POST"
        assert json.loads(request.content.decode("utf-8")) == {
            "appId": APP_ID,
            "clientSecret": SECRET,
        }
        return httpx.Response(
            200,
            json={"access_token": ACCESS_TOKEN, "expires_in": "7200"},
        )

    requests = _inject_mock_transport(monkeypatch, handler)
    channel = _make_channel(tmp_path)

    result = _run(channel.test_connection())

    assert len(requests) == 1
    assert result["ok"] is True
    assert result["code"] == "ok"
    assert result["sdk_available"] is QQ_AVAILABLE
    # The probe is standalone: it must not have created the shared client.
    assert channel._http is None
    # The token and secret are discarded, never returned.
    serialized = json.dumps(result)
    assert ACCESS_TOKEN not in serialized
    assert SECRET not in serialized


def test_success_uses_fresh_client_even_when_shared_client_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A started channel's ``_http`` must not be reused by the probe."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": ACCESS_TOKEN})

    requests = _inject_mock_transport(monkeypatch, handler)
    channel = _make_channel(tmp_path)
    sentinel = object()
    channel._http = sentinel  # pretend start() ran

    result = _run(channel.test_connection())

    assert result["ok"] is True
    assert len(requests) == 1
    assert channel._http is sentinel


# --------------------------------------------------------------------------- #
# QQ standalone probe — invalid credentials
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", [400, 401, 403])
def test_http_client_error_reports_invalid_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "invalid appId/clientSecret"})

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path).test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is QQ_AVAILABLE
    assert "detail" in result
    assert SECRET not in json.dumps(result)
    assert ACCESS_TOKEN not in json.dumps(result)


def test_http_200_error_body_reports_invalid_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QQ answers bad credentials with HTTP 200 and an error body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 100007, "message": "appId or clientSecret is invalid"},
        )

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path).test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is QQ_AVAILABLE
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("body", [b"null", b"[1, 2]", b'"oops"'])
def test_http_200_non_object_json_body_reports_invalid_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    """A 200 with valid non-object JSON must classify, never raise.

    Middleboxes and proxied error pages produce exactly such bodies; without
    the isinstance guard in ``token_probe`` the ``.get`` raised
    ``AttributeError``, which the unguarded ``/test`` route turned into a
    bare 500.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path).test_connection())

    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["sdk_available"] is QQ_AVAILABLE
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    ("app_id", "secret"),
    [("", ""), (APP_ID, ""), ("", SECRET)],
)
def test_missing_credentials_short_circuit_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_id: str,
    secret: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call may happen without credentials")

    requests = _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path, app_id, secret).test_connection())

    assert requests == []
    assert result["ok"] is False
    assert result["code"] == "invalid_credentials"
    assert result["detail"] == "missing credentials"
    # The short-circuit envelope is self-contained like every other branch.
    assert result["sdk_available"] is QQ_AVAILABLE


# --------------------------------------------------------------------------- #
# QQ standalone probe — network
# --------------------------------------------------------------------------- #


def test_transport_error_reports_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path).test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"
    assert result["sdk_available"] is QQ_AVAILABLE
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_reports_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="upstream exploded")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path).test_connection())

    assert result["ok"] is False
    assert result["code"] == "network"


# --------------------------------------------------------------------------- #
# Construction side effects
# --------------------------------------------------------------------------- #


def test_construction_never_creates_the_media_directory(tmp_path: Path) -> None:
    """Ephemeral validation instances must not touch the filesystem.

    The web-config Test/Save routes construct the channel to validate a
    section before anything is persisted; a constructor that mkdir'd a
    user-controlled path created directories for configs that were then
    rejected. Creation belongs to ``start()`` via ``_ensure_media_root``.
    """
    media = tmp_path / "qq-media"

    channel = _make_channel(tmp_path)

    assert channel._media_root == media
    assert not media.exists()

    channel._ensure_media_root()
    assert media.is_dir()


# --------------------------------------------------------------------------- #
# Secret hygiene
# --------------------------------------------------------------------------- #


def test_probe_never_logs_secret_or_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": ACCESS_TOKEN})

    _inject_mock_transport(monkeypatch, ok_handler)
    with caplog.at_level(logging.DEBUG):
        # Construction happens INSIDE the capture block on purpose: the
        # constructor logs the media directory, so a loguru-style "{}" format
        # string (which stdlib logging cannot render) would make pytest's
        # caplog handler raise TypeError and fail this test.
        success = _run(_make_channel(tmp_path).test_connection())

    def reject_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad secret {SECRET}")

    _inject_mock_transport(monkeypatch, reject_handler)
    with caplog.at_level(logging.DEBUG):
        failure = _run(_make_channel(tmp_path).test_connection())

    assert success["code"] == "ok"
    assert failure["code"] == "invalid_credentials"
    assert "media directory:" in caplog.text
    assert SECRET not in caplog.text
    assert ACCESS_TOKEN not in caplog.text
    # And the rejection body's echoed secret is scrubbed from the detail too.
    assert SECRET not in json.dumps(failure)


def test_rejection_detail_scrubs_echoed_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"clientSecret {SECRET} is invalid")

    _inject_mock_transport(monkeypatch, handler)

    result = _run(_make_channel(tmp_path).test_connection())

    assert result["code"] == "invalid_credentials"
    assert SECRET not in json.dumps(result)
    assert "detail" in result
