"""GHSA-7wgj regression: API auth must check the configured key BEFORE trusting a loopback peer.

The bug: ``_validate_api_auth`` / ``require_event_stream_auth`` returned early on
``_is_local_client(request)`` *before* reading the configured API key, so a
loopback (or same-host reverse-proxy) peer was admitted with no credential even
when ``API_AUTH_KEY`` was set. The fix inverts to key-first precedence: when a
key is configured every peer -- loopback included -- must present a valid
credential; only in keyless dev mode does loopback trust apply.

A default FastAPI ``TestClient`` reports its peer host as ``testclient``, which
``_is_local_client`` treats as loopback -- exactly the condition that reproduced
the bug.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api_server


def _loopback_client() -> TestClient:
    """TestClient whose peer host ('testclient') is treated as loopback."""
    return TestClient(api_server.app)


@pytest.fixture(autouse=True)
def clear_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from dev-mode auth (no configured key)."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.delenv("VIBE_TRADING_TRUST_DOCKER_LOOPBACK", raising=False)
    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")


def _set_key(monkeypatch: pytest.MonkeyPatch, key: str = "secret") -> None:
    monkeypatch.setenv("API_AUTH_KEY", key)
    monkeypatch.setattr(api_server, "_API_KEY", key)


# (a) Key configured + NO credential on a require_auth route -> rejected, even for a loopback peer.
def test_loopback_without_credential_rejected_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    response = _loopback_client().get("/runs")

    # The vulnerability would return 200 here; key-first precedence rejects it.
    assert response.status_code in {401, 403}
    assert response.status_code != 200


# (b) Key configured + valid bearer -> allowed.
def test_loopback_with_valid_bearer_allowed_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    response = _loopback_client().get("/runs", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200


# (b') Key configured + WRONG bearer -> rejected.
def test_loopback_with_invalid_bearer_rejected_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    response = _loopback_client().get("/runs", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


# (c) No key (dev mode) + loopback peer -> allowed. Default local UX is unchanged.
def test_loopback_allowed_in_dev_mode_without_key() -> None:
    response = _loopback_client().get("/runs")

    assert response.status_code == 200


# (d) Event-stream: valid single-use ticket still authenticates.
def test_event_stream_accepts_valid_ticket_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    ticket = api_server._mint_sse_ticket()
    response = _loopback_client().get(f"/sessions/missing/events?ticket={ticket}")

    # Auth passed; the 404/501 comes from the missing session / disabled runtime,
    # not from the auth layer (a 401/403 would mean auth rejected the ticket).
    assert response.status_code in {404, 501}


# (d) Event-stream: valid bearer still authenticates.
def test_event_stream_accepts_valid_bearer_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    response = _loopback_client().get("/sessions/missing/events", headers={"Authorization": "Bearer secret"})

    assert response.status_code in {404, 501}


# (d) Event-stream: missing credential on a loopback peer -> rejected when key configured.
def test_event_stream_without_credential_rejected_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    response = _loopback_client().get("/sessions/missing/events")

    assert response.status_code == 401


# (d) Event-stream: an expired/invalid ticket is not accepted.
def test_event_stream_rejects_invalid_ticket_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_key(monkeypatch)

    response = _loopback_client().get("/sessions/missing/events?ticket=not-a-real-ticket")

    assert response.status_code == 401


# Event-stream dev mode: loopback allowed without any credential (unchanged UX).
def test_event_stream_allowed_in_dev_mode_without_key() -> None:
    response = _loopback_client().get("/sessions/missing/events")

    assert response.status_code in {404, 501}
