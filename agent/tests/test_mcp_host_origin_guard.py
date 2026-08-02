"""Tests for the network MCP transport DNS-rebinding guard (GHSA-p3c9).

The stdio transport is a private pipe and is not touched. The network
transports (``--transport sse`` / ``http``) bind a TCP port, so fastmcp 3.2.4
(which ships no host/origin protection) is wrapped with a Host + Origin
allow-list before the MCP session is reached. These tests cover:

1. ``_parse_allowed_hosts`` — loopback-only default + comma parsing.
2. ``_origin_allowed`` — the Origin allow-list helper (browser-only guard).
3. The fully wired ASGI app rejects an untrusted Host (400) and Origin (403).
4. A loopback Host/Origin (and a missing Origin) is accepted.
"""

from __future__ import annotations

import mcp_server
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# _parse_allowed_hosts
# ---------------------------------------------------------------------------


def test_parse_allowed_hosts_default_is_loopback_only():
    assert mcp_server._parse_allowed_hosts(None) == ["127.0.0.1", "::1", "localhost"]
    assert mcp_server._parse_allowed_hosts("") == ["127.0.0.1", "::1", "localhost"]
    assert mcp_server._parse_allowed_hosts("   ") == ["127.0.0.1", "::1", "localhost"]


def test_parse_allowed_hosts_parses_and_trims():
    assert mcp_server._parse_allowed_hosts("a.example.com, b.example.com") == [
        "a.example.com",
        "b.example.com",
    ]
    # Empty segments are dropped, whitespace stripped.
    assert mcp_server._parse_allowed_hosts("mcp.local, ,  ") == ["mcp.local"]


def test_parse_allowed_hosts_normalizes_entries():
    # Case-insensitive, IPv6 brackets stripped, wildcard forms pass through.
    assert mcp_server._parse_allowed_hosts("LOCALHOST, [::1], *.Example.COM, *") == [
        "localhost",
        "::1",
        "*.example.com",
        "*",
    ]


# ---------------------------------------------------------------------------
# _normalize_host
# ---------------------------------------------------------------------------


def test_normalize_host_strips_port_and_lowercases():
    assert mcp_server._normalize_host("LOCALHOST:8900") == "localhost"
    assert mcp_server._normalize_host("Example.COM") == "example.com"
    assert mcp_server._normalize_host("127.0.0.1:8900") == "127.0.0.1"


def test_normalize_host_handles_ipv6_forms():
    assert mcp_server._normalize_host("[::1]:8900") == "::1"
    assert mcp_server._normalize_host("[::1]") == "::1"
    # Bare IPv6 (no brackets) is kept whole, never split into a fake host:port.
    assert mcp_server._normalize_host("::1") == "::1"
    assert mcp_server._normalize_host("fe80::1%eth0") == "fe80::1%eth0"


# ---------------------------------------------------------------------------
# _origin_allowed
# ---------------------------------------------------------------------------


def test_origin_allowed_missing_origin_is_allowed():
    # Non-browser MCP clients (curl / Python SDK) never send Origin.
    hosts = ["127.0.0.1", "localhost"]
    assert mcp_server._origin_allowed(None, hosts) is True
    assert mcp_server._origin_allowed("", hosts) is True


def test_origin_allowed_matches_allow_list():
    hosts = ["127.0.0.1", "localhost"]
    assert mcp_server._origin_allowed("http://localhost:8900", hosts) is True
    assert mcp_server._origin_allowed("http://127.0.0.1", hosts) is True


def test_origin_allowed_rejects_foreign_and_unparseable():
    hosts = ["127.0.0.1", "localhost"]
    assert mcp_server._origin_allowed("http://evil.example.com", hosts) is False
    assert mcp_server._origin_allowed("https://attacker.test:443", hosts) is False
    # A present-but-hostless Origin is rejected (fail closed).
    assert mcp_server._origin_allowed("null", hosts) is False


def test_origin_allowed_supports_wildcard():
    hosts = ["*.example.com"]
    assert mcp_server._origin_allowed("http://api.example.com", hosts) is True
    assert mcp_server._origin_allowed("http://example.com", hosts) is True
    assert mcp_server._origin_allowed("http://example.org", hosts) is False
    assert mcp_server._origin_allowed("http://evil.test", ["*"]) is True


# ---------------------------------------------------------------------------
# Fully wired ASGI app (real FastMCP network transport)
# ---------------------------------------------------------------------------


def test_network_app_rejects_untrusted_host():
    # Build the real hardened streamable-http app. TrustedHostMiddleware
    # short-circuits an untrusted Host before the MCP session handler runs, so
    # no lifespan/session-manager startup is needed to observe the rejection.
    app = mcp_server._build_network_app("streamable-http", ["127.0.0.1", "localhost"])
    client = TestClient(app)
    resp = client.post("/mcp", headers={"host": "evil.example.com"})
    assert resp.status_code == 400  # TrustedHostMiddleware "Invalid host header"


def test_network_app_rejects_untrusted_origin():
    app = mcp_server._build_network_app("streamable-http", ["127.0.0.1", "localhost"])
    client = TestClient(app)
    resp = client.post(
        "/mcp",
        headers={"host": "127.0.0.1:8900", "origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403  # _OriginGuardMiddleware rejection


# ---------------------------------------------------------------------------
# Accepted path — exercises the exact middleware objects on a light app so a
# valid loopback request is NOT rejected by either guard (no MCP session churn).
# ---------------------------------------------------------------------------


def _guarded_probe_app(allowed_hosts):
    async def _ok(_request):
        return PlainTextResponse("ok")

    return Starlette(
        routes=[Route("/mcp", _ok, methods=["POST"])],
        middleware=mcp_server._security_middleware(allowed_hosts),
    )


def test_loopback_host_and_origin_accepted():
    client = TestClient(_guarded_probe_app(["127.0.0.1", "localhost"]))
    # Good host, matching origin.
    resp = client.post("/mcp", headers={"host": "127.0.0.1:8900", "origin": "http://127.0.0.1:8900"})
    assert resp.status_code == 200
    assert resp.text == "ok"
    # Good host, no origin header (non-browser client).
    resp = client.post("/mcp", headers={"host": "localhost:8900"})
    assert resp.status_code == 200


def test_env_override_extends_allow_list():
    hosts = mcp_server._parse_allowed_hosts("mcp.internal.test")
    client = TestClient(_guarded_probe_app(hosts))
    resp = client.post(
        "/mcp",
        headers={"host": "mcp.internal.test", "origin": "http://mcp.internal.test"},
    )
    assert resp.status_code == 200
    # Loopback is no longer implicitly trusted once an explicit list is set.
    resp = client.post("/mcp", headers={"host": "127.0.0.1:8900"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# IPv6 / case handling in the wired host guard
# ---------------------------------------------------------------------------


def test_ipv6_loopback_accepted_by_default_list():
    """`--host ::1` deployments must not 400 every request (Starlette did)."""
    client = TestClient(_guarded_probe_app(mcp_server._parse_allowed_hosts(None)))
    resp = client.post("/mcp", headers={"host": "[::1]:8900"})
    assert resp.status_code == 200
    resp = client.post("/mcp", headers={"host": "::1"})
    assert resp.status_code == 200


def test_ipv6_env_entry_accepts_bracketed_host():
    """An env entry of `[::1]` or `::1` must actually match (no `*` needed)."""
    for entry in ("[::1]", "::1"):
        hosts = mcp_server._parse_allowed_hosts(entry)
        client = TestClient(_guarded_probe_app(hosts))
        resp = client.post("/mcp", headers={"host": "[::1]:8900"})
        assert resp.status_code == 200, entry


def test_host_matching_is_case_insensitive():
    client = TestClient(_guarded_probe_app(["127.0.0.1", "localhost"]))
    resp = client.post("/mcp", headers={"host": "LOCALHOST:8900"})
    assert resp.status_code == 200


def test_host_guard_still_rejects_untrusted():
    client = TestClient(_guarded_probe_app(mcp_server._parse_allowed_hosts(None)))
    resp = client.post("/mcp", headers={"host": "evil.example.com"})
    assert resp.status_code == 400
    # A missing Host header fails closed.
    resp = client.post("/mcp", headers={"host": ""})
    assert resp.status_code == 400


def test_host_guard_wildcard_semantics_unchanged():
    client = TestClient(_guarded_probe_app(["*.example.com"]))
    assert client.post("/mcp", headers={"host": "api.example.com"}).status_code == 200
    assert client.post("/mcp", headers={"host": "example.com"}).status_code == 200
    assert client.post("/mcp", headers={"host": "example.org"}).status_code == 400
    client = TestClient(_guarded_probe_app(["*"]))
    assert client.post("/mcp", headers={"host": "anything.example.org"}).status_code == 200
