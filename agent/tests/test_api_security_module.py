"""Regression tests for the extracted API security helpers."""

from __future__ import annotations

import api_server
from src.api import security as api_security


def test_api_server_reexports_security_dependencies() -> None:
    """Keep the public ``api_server.*`` compatibility surface stable."""
    assert api_server.require_auth is api_security.require_auth
    assert api_server.require_event_stream_auth is api_security.require_event_stream_auth
    assert api_server.require_local_or_auth is api_security.require_local_or_auth
    assert api_server.require_settings_write_auth is api_security.require_settings_write_auth
    assert api_server._parse_cors_origins is api_security._parse_cors_origins
    assert api_server._is_loopback_bind_host is api_security._is_loopback_bind_host


def test_security_module_honors_api_server_api_key_reexport(monkeypatch) -> None:
    """Existing tests and consumers monkeypatch ``api_server._API_KEY``."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "fallback-secret")

    assert api_security._configured_api_key() == "fallback-secret"
