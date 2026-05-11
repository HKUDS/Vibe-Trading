"""Security regression tests for API authentication boundaries."""

from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_server


def _remote_client() -> TestClient:
    """Return a TestClient that simulates a non-loopback caller."""
    return TestClient(api_server.app, client=("203.0.113.10", 50000))


def _local_client() -> TestClient:
    """Return a TestClient that simulates a loopback caller."""
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def clear_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every auth test from dev-mode auth."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.delenv("VIBE_TRADING_TRUST_DOCKER_LOOPBACK", raising=False)
    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")


def test_remote_write_requires_api_key_when_key_unset() -> None:
    response = _remote_client().post("/sessions", json={})

    assert response.status_code == 403
    assert "API_AUTH_KEY" in response.json()["detail"]


def test_local_dev_write_allowed_when_key_unset() -> None:
    response = _local_client().post("/sessions", json={})

    assert response.status_code in {201, 501}


def test_docker_gateway_dev_write_allowed_only_with_compose_trust_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SimpleNamespace(client=SimpleNamespace(host="172.18.0.1"))
    monkeypatch.setattr(
        api_server,
        "_default_gateway_ips",
        lambda: {ipaddress.IPv4Address("172.18.0.1")},
    )

    assert not api_server._is_local_client(request)

    monkeypatch.setenv("VIBE_TRADING_TRUST_DOCKER_LOOPBACK", "1")

    assert api_server._is_local_client(request)


def test_docker_network_peer_is_not_local_even_with_compose_trust_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SimpleNamespace(client=SimpleNamespace(host="172.18.0.42"))
    monkeypatch.setenv("VIBE_TRADING_TRUST_DOCKER_LOOPBACK", "1")
    monkeypatch.setattr(
        api_server,
        "_default_gateway_ips",
        lambda: {ipaddress.IPv4Address("172.18.0.1")},
    )

    assert not api_server._is_local_client(request)


def test_configured_api_key_required_for_sensitive_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")
    client = _remote_client()

    for path in [
        "/runs",
        "/sessions",
        "/swarm/runs",
    ]:
        response = client.get(path)
        assert response.status_code == 401, path


def test_configured_api_key_accepts_bearer_for_sensitive_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    response = _remote_client().get(
        "/runs",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200


def test_configured_api_key_required_for_session_event_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    response = _remote_client().get("/sessions/missing/events")

    assert response.status_code == 401


def test_session_event_stream_accepts_query_token_for_browser_eventsource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    response = _remote_client().get("/sessions/missing/events?api_key=secret")

    assert response.status_code in {404, 501}


def test_shell_tools_allowed_for_loopback_api_request() -> None:
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    assert api_server._shell_tools_enabled_for_request(request)


def test_shell_tools_disabled_for_remote_api_request_by_default() -> None:
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.10"))

    assert not api_server._shell_tools_enabled_for_request(request)


def test_shell_tools_remote_api_request_accepts_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.10"))
    monkeypatch.setenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", "1")

    assert api_server._shell_tools_enabled_for_request(request)


def test_default_cors_origins_are_loopback_only() -> None:
    origins = api_server._parse_cors_origins(None)

    assert origins
    assert "*" not in origins
    assert all(
        origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:")
        for origin in origins
    )


def test_cors_origins_reject_credentialed_wildcard() -> None:
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        api_server._parse_cors_origins("https://app.example.com,*")


def test_cors_origins_accept_explicit_remote_origins() -> None:
    origins = api_server._parse_cors_origins(" https://app.example.com,https://admin.example.com ")

    assert origins == ["https://app.example.com", "https://admin.example.com"]


# ============================================================================
# Path-parameter validation (run_id / session_id)
# ============================================================================


@pytest.mark.parametrize(
    "value",
    [
        # Real formats produced by the codebase.
        "20260105_120342_12_a1b2c3",            # state.create_run_dir
        "swarm-20260105_120342-a1b2c3",         # swarm presets.run_id
        "abcdef012345",                         # session_id (uuid.uuid4().hex[:12])
        "run-1",
        "A" * 128,
    ],
)
def test_validate_path_param_accepts_known_good_values(value: str) -> None:
    api_server._validate_path_param(value, "run_id")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "..",
        "../etc",
        "foo/bar",
        "foo\\bar",
        "foo bar",
        "foo.bar",             # dot is not in the safe class
        "foo\n",
        "foo\r",
        "foo\t",
        "foo\x00bar",
        "A" * 129,
    ],
)
def test_validate_path_param_rejects_traversal_inputs(value: str) -> None:
    with pytest.raises(api_server.HTTPException) as excinfo:
        api_server._validate_path_param(value, "run_id")

    assert excinfo.value.status_code == 400
    assert "run_id" in excinfo.value.detail


def test_get_run_code_rejects_dot_run_id() -> None:
    response = _local_client().get("/runs/../code")

    # Either rejected at routing (404) or by the validator (400). Both are safe;
    # what we forbid is reading code from outside RUNS_DIR.
    assert response.status_code in {400, 404}


def test_get_run_pine_rejects_traversal_run_id() -> None:
    response = _local_client().get("/runs/foo.bar/pine")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid run_id"


def test_get_run_pine_rejects_url_encoded_newline_run_id() -> None:
    response = _local_client().get("/runs/foo%0A/pine")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid run_id"


def test_get_run_result_rejects_traversal_run_id() -> None:
    response = _local_client().get("/runs/foo.bar")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid run_id"


def test_session_endpoints_reject_traversal_session_id() -> None:
    client = _local_client()

    cases = [
        ("get", "/sessions/foo.bar", None),
        ("delete", "/sessions/foo.bar", None),
        ("patch", "/sessions/foo.bar", {"title": "x"}),
        ("post", "/sessions/foo.bar/messages", {"content": "x"}),
        ("get", "/sessions/foo.bar/messages", None),
        ("post", "/sessions/foo.bar/cancel", None),
    ]
    for method, path, body in cases:
        kwargs = {"json": body} if body is not None else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 400, f"{method.upper()} {path} should be rejected"
        assert response.json()["detail"] == "invalid session_id"


def test_session_event_stream_rejects_traversal_session_id() -> None:
    response = _local_client().get("/sessions/foo.bar/events")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid session_id"


def test_swarm_run_endpoints_reject_traversal_run_id() -> None:
    client = _local_client()

    for method, path in (
        ("get", "/swarm/runs/foo.bar"),
        ("get", "/swarm/runs/foo.bar/events"),
        ("post", "/swarm/runs/foo.bar/cancel"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 400, f"{method.upper()} {path} should be rejected"
        assert response.json()["detail"] == "invalid run_id"
