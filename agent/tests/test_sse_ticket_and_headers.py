"""VT-003 / VT-006 regression tests: SSE tickets, security headers, log redaction."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import security


def _remote_client() -> TestClient:
    """Return a TestClient that simulates a non-loopback caller."""
    return TestClient(api_server.app, client=("203.0.113.10", 50000))


def _local_client() -> TestClient:
    """Return a TestClient that simulates a loopback caller."""
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test from dev-mode auth with an empty ticket store."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.delenv("VIBE_TRADING_TRUST_DOCKER_LOOPBACK", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    with security._sse_tickets_lock:
        security._sse_tickets.clear()


# ---------------------------------------------------------------------------
# SSE ticket store (unit)
# ---------------------------------------------------------------------------


def test_minted_ticket_is_unguessable_and_urlsafe() -> None:
    ticket = security._mint_sse_ticket()
    assert isinstance(ticket, str)
    assert len(ticket) >= 32
    # token_urlsafe alphabet only
    assert all(c.isalnum() or c in "-_" for c in ticket)


def test_ticket_is_single_use() -> None:
    ticket = security._mint_sse_ticket()
    assert security._consume_sse_ticket(ticket) is True
    # Second use is rejected — the ticket was invalidated on first use.
    assert security._consume_sse_ticket(ticket) is False


def test_unknown_ticket_is_rejected() -> None:
    assert security._consume_sse_ticket("never-minted") is False
    assert security._consume_sse_ticket("") is False


def test_expired_ticket_is_rejected() -> None:
    import time

    ticket = security._mint_sse_ticket()
    # Force the stored expiry into the past without waiting the full TTL.
    with security._sse_tickets_lock:
        security._sse_tickets[ticket] = time.monotonic() - 1.0
    assert security._consume_sse_ticket(ticket) is False


# ---------------------------------------------------------------------------
# POST /auth/sse-ticket endpoint
# ---------------------------------------------------------------------------


def test_sse_ticket_endpoint_mints_in_loopback_dev_mode() -> None:
    response = _local_client().post("/auth/sse-ticket")

    assert response.status_code == 200
    assert isinstance(response.json().get("ticket"), str)
    assert response.json()["ticket"]


def test_sse_ticket_endpoint_requires_bearer_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    # Remote caller without the header is rejected — minting requires the key
    # in an Authorization header (never a URL).
    assert _remote_client().post("/auth/sse-ticket").status_code == 401

    ok = _remote_client().post("/auth/sse-ticket", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    assert ok.json()["ticket"]


# ---------------------------------------------------------------------------
# require_event_stream_auth (integration via /sessions/{id}/events)
# ---------------------------------------------------------------------------


def test_event_stream_accepts_ticket_once_then_rejects_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    ticket = api_server._mint_sse_ticket()
    client = _remote_client()

    first = client.get(f"/sessions/missing/events?ticket={ticket}")
    # Auth passed: the 404/501 comes from the missing session / disabled runtime.
    assert first.status_code in {404, 501}

    # The same ticket cannot be replayed.
    second = client.get(f"/sessions/missing/events?ticket={ticket}")
    assert second.status_code == 401


def test_event_stream_still_accepts_bearer_header_for_non_browser_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    response = _remote_client().get(
        "/sessions/missing/events",
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code in {404, 501}


# ---------------------------------------------------------------------------
# VT-006: security headers
# ---------------------------------------------------------------------------


def test_security_headers_present_on_response() -> None:
    response = _local_client().get("/health")

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in response.headers.get("Permissions-Policy", "")

    # Enforcing by default -- Report-Only provides no protection.
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self';" in csp
    assert response.headers.get("Content-Security-Policy-Report-Only") is None

    # No HSTS from the app — that belongs at the TLS-terminating proxy.
    assert response.headers.get("Strict-Transport-Security") is None


def test_csp_report_only_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """``VIBE_TRADING_CSP_REPORT_ONLY=1`` is the documented rollback switch."""
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("VIBE_TRADING_CSP_REPORT_ONLY", "1")
    reset_env_config()
    try:
        response = _local_client().get("/health")
        assert "default-src 'self'" in response.headers.get(
            "Content-Security-Policy-Report-Only", ""
        )
        assert response.headers.get("Content-Security-Policy") is None
    finally:
        monkeypatch.delenv("VIBE_TRADING_CSP_REPORT_ONLY", raising=False)
        reset_env_config()


def test_docs_csp_allows_bundle_host_but_app_pages_do_not() -> None:
    """The Swagger/ReDoc CDN exception must not leak into the SPA's policy."""
    client = _local_client()

    docs_csp = client.get("/docs").headers.get("Content-Security-Policy", "")
    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "frame-ancestors 'none'" in docs_csp

    app_csp = client.get("/health").headers.get("Content-Security-Policy", "")
    assert "cdn.jsdelivr.net" not in app_csp
    assert "'unsafe-inline'" not in app_csp.split("style-src")[0]


def test_docs_pages_reference_no_host_outside_their_csp() -> None:
    """Every remote asset the docs pages load must be covered by the policy.

    Guards against a FastAPI bump reintroducing an asset host the exception
    does not allow (ReDoc's Google Fonts stylesheet was one such case), which
    would silently render a blocked page under the enforcing policy.
    """
    import re

    client = _local_client()
    for path in ("/docs", "/redoc"):
        html = client.get(path).text
        hosts = set(re.findall(r"https?://([a-zA-Z0-9.\-]+)", html))
        assert hosts <= {"cdn.jsdelivr.net"}, f"{path} references {hosts}"


def test_security_headers_present_on_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headers must wrap error responses from inner middleware too."""
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    response = _local_client().get("/runs", headers={"Host": "attacker.example:8899"})

    assert response.status_code == 403  # rebound-host guard short-circuits
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


# ---------------------------------------------------------------------------
# VT-003: access-log secret redaction
# ---------------------------------------------------------------------------


def test_redact_query_secrets_masks_ticket_and_api_key_values() -> None:
    line = 'GET /sessions/x/events?ticket=abc123&foo=bar HTTP/1.1'
    red = security._redact_query_secrets(line)
    assert "abc123" not in red
    assert "ticket=***REDACTED***" in red
    assert "foo=bar" in red

    line2 = "/alpha/bench/1/stream?api_key=SUPERSECRET"
    red2 = security._redact_query_secrets(line2)
    assert "SUPERSECRET" not in red2
    assert "api_key=***REDACTED***" in red2


def test_access_log_filter_redacts_record_args() -> None:
    filt = security._AccessLogRedactionFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:5000", "GET", "/sessions/x/events?ticket=LEAKME", "1.1", 404),
        exc_info=None,
    )

    assert filt.filter(record) is True
    formatted = record.getMessage()
    assert "LEAKME" not in formatted
    assert "ticket=***REDACTED***" in formatted


def test_install_access_log_redaction_filter_is_idempotent() -> None:
    access = logging.getLogger("uvicorn.access")
    before = [f for f in access.filters if isinstance(f, security._AccessLogRedactionFilter)]
    for f in list(before):
        access.removeFilter(f)

    security.install_access_log_redaction_filter()
    security.install_access_log_redaction_filter()

    installed = [f for f in access.filters if isinstance(f, security._AccessLogRedactionFilter)]
    assert len(installed) == 1

    # Restore prior state (leave exactly what was there before this test).
    for f in installed:
        access.removeFilter(f)
    for f in before:
        access.addFilter(f)
