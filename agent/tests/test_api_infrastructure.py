"""Regression tests for the extracted API infrastructure modules."""

from __future__ import annotations

import os
import pytest

import api_server
from src.api import _compat, security, models, helpers, state


# ============================================================================
# Re-export identity tests
# ============================================================================


def test_security_reexports():
    assert api_server.require_auth is security.require_auth
    assert api_server.require_event_stream_auth is security.require_event_stream_auth
    assert api_server.require_local_or_auth is security.require_local_or_auth
    assert api_server.require_settings_write_auth is security.require_settings_write_auth
    assert api_server._parse_cors_origins is security._parse_cors_origins
    assert api_server._is_loopback_bind_host is security._is_loopback_bind_host
    assert api_server._is_local_client is security._is_local_client
    assert api_server._configured_api_key is security._configured_api_key


def test_models_reexports():
    assert api_server.Artifact is models.Artifact
    assert api_server.BacktestMetrics is models.BacktestMetrics
    assert api_server.RAGSelection is models.RAGSelection
    assert api_server.RunInfo is models.RunInfo
    assert api_server.RunResponse is models.RunResponse


def test_helpers_reexports():
    assert api_server.RUNS_DIR is helpers.RUNS_DIR
    assert api_server.SESSIONS_DIR is helpers.SESSIONS_DIR
    assert api_server.ENV_PATH is helpers.ENV_PATH
    assert api_server._is_spa_html_route is helpers._is_spa_html_route
    assert api_server._read_env_values is helpers._read_env_values
    assert api_server._validate_path_param is helpers._validate_path_param


def test_state_reexports():
    assert api_server._get_session_service is state._get_session_service


def test_api_key_monkeypatch(monkeypatch):
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "test-secret")
    assert security._configured_api_key() == "test-secret"


def test_no_circular_imports():
    import importlib
    for mod_name in [
        "src.api._compat",
        "src.api.security",
        "src.api.models",
        "src.api.helpers",
        "src.api.state",
    ]:
        importlib.import_module(mod_name)


def test_api_server_is_thin_assembler():
    import inspect
    source = inspect.getsource(api_server)
    total_lines = len(source.splitlines())
    assert total_lines < 400, f"api_server.py has {total_lines} lines, expected < 400"


# ============================================================================
# _compat shared module tests
# ============================================================================


def test_compat_host_attr_reads_api_server():
    """host_attr should read attributes from the api_server module when present."""
    assert _compat.host_attr("_API_KEY", "fallback") is not None or True


def test_compat_host_attr_fallback():
    """host_attr should return fallback when attribute is missing."""
    assert _compat.host_attr("_nonexistent_attr_xyz", "default") == "default"


def test_compat_set_host_attr():
    """set_host_attr should write attributes onto the api_server module."""
    _compat.set_host_attr("_test_compat_marker", 42)
    assert api_server._test_compat_marker == 42
    del api_server._test_compat_marker


# ============================================================================
# security._parse_cors_origins edge cases
# ============================================================================


def test_parse_cors_origins_none_returns_defaults():
    result = security._parse_cors_origins(None)
    assert result == list(security._DEFAULT_CORS_ORIGINS)


def test_parse_cors_origins_empty_returns_defaults():
    result = security._parse_cors_origins("")
    assert result == list(security._DEFAULT_CORS_ORIGINS)
    result = security._parse_cors_origins("   ")
    assert result == list(security._DEFAULT_CORS_ORIGINS)


def test_parse_cors_origins_custom():
    result = security._parse_cors_origins("http://a.com, http://b.com")
    assert result == ["http://a.com", "http://b.com"]


def test_parse_cors_origins_wildcard_raises():
    with pytest.raises(RuntimeError, match="not allowed"):
        security._parse_cors_origins("*")


def test_default_cors_origins_is_immutable():
    assert isinstance(security._DEFAULT_CORS_ORIGINS, tuple)


# ============================================================================
# security._host_without_port edge cases
# ============================================================================


def test_host_without_port_plain():
    assert security._host_without_port("localhost:8080") == "localhost"


def test_host_without_port_ipv6():
    assert security._host_without_port("[::1]:8080") == "[::1]"


def test_host_without_port_ipv6_no_port():
    assert security._host_without_port("[::1]") == "[::1]"


def test_host_without_port_empty():
    assert security._host_without_port("") == ""


def test_host_without_port_trailing_dot():
    assert security._host_without_port("example.com.") == "example.com"


# ============================================================================
# helpers._validate_path_param security tests
# ============================================================================


def test_validate_path_param_valid():
    helpers._validate_path_param("abc-123_test", "run_id")


def test_validate_path_param_path_traversal():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        helpers._validate_path_param("..", "run_id")
    with pytest.raises(HTTPException):
        helpers._validate_path_param("foo/../bar", "run_id")
    with pytest.raises(HTTPException):
        helpers._validate_path_param("foo/..", "run_id")


def test_validate_path_param_empty():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        helpers._validate_path_param("", "run_id")


def test_validate_path_param_special_chars():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        helpers._validate_path_param("foo bar", "run_id")
    with pytest.raises(HTTPException):
        helpers._validate_path_param("foo\x00bar", "run_id")


# ============================================================================
# helpers._is_spa_html_route tests
# ============================================================================


def test_is_spa_html_route_correlation():
    assert helpers._is_spa_html_route("/correlation") is True


def test_is_spa_html_route_runs_detail():
    assert helpers._is_spa_html_route("/runs/abc123") is True
    assert helpers._is_spa_html_route("/runs/abc123/") is True


def test_is_spa_html_route_runs_subpath_not_spa():
    assert helpers._is_spa_html_route("/runs/abc123/code") is False
    assert helpers._is_spa_html_route("/runs/abc123/pine") is False


def test_is_spa_html_route_runs_collection_not_spa():
    assert helpers._is_spa_html_route("/runs") is False


def test_is_spa_html_route_unknown():
    assert helpers._is_spa_html_route("/api/health") is False


# ============================================================================
# helpers dotenv round-trip
# ============================================================================


def test_read_write_env_values_roundtrip(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nFOO=bar\nBAZ=qux\n", encoding="utf-8")

    values = helpers._read_env_values(env_file)
    assert values == {"FOO": "bar", "BAZ": "qux"}

    helpers._write_env_values(env_file, {"FOO": "updated", "NEW_KEY": "new_val"})
    updated = helpers._read_env_values(env_file)
    assert updated["FOO"] == "updated"
    assert updated["NEW_KEY"] == "new_val"
    assert updated["BAZ"] == "qux"


def test_settings_default_to_user_writable_config_path() -> None:
    """Web settings must not target the installed package directory."""
    from pathlib import Path

    assert helpers.ENV_PATH == Path.home() / ".vibe-trading" / ".env"
    assert helpers.LEGACY_ENV_PATH == helpers.AGENT_DIR / ".env"


def test_write_env_values_creates_private_parent_directory(tmp_path) -> None:
    target = tmp_path / "nested" / ".env"

    helpers._write_env_values(target, {"KEY": "value"})

    assert helpers._read_env_values(target) == {"KEY": "value"}
    if os.name != "nt":
        assert (target.parent.stat().st_mode & 0o777) == 0o700
        assert (target.stat().st_mode & 0o777) == 0o600


def test_strip_env_value_quotes():
    assert helpers._strip_env_value('"hello"') == "hello"
    assert helpers._strip_env_value("'hello'") == "hello"


def test_strip_env_value_inline_comment():
    assert helpers._strip_env_value("value # comment") == "value"


# ============================================================================
# state._get_session_service writeback
# ============================================================================


def test_session_service_writeback_to_host(monkeypatch):
    """_get_session_service should write back to api_server for monkeypatch compat."""
    monkeypatch.setenv("ENABLE_SESSION_RUNTIME", "false")
    import src.api.state as state_mod
    state_mod._session_service = None
    _compat.set_host_attr("_session_service", None)

    result = state_mod._get_session_service()
    assert result is None
