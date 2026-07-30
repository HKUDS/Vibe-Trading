"""Integration tests for the OpenBB Workspace bridge HTTP endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("openbb_ai")

import api_server
from openbb_ai.helpers import message_chunk
from openbb_ai.models import LlmClientMessage, QueryRequest
from src.openbb_bridge import routes as bridge_routes


def _local_client() -> TestClient:
    """Return a TestClient that simulates a loopback caller."""
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _remote_client() -> TestClient:
    """Return a TestClient that simulates a non-loopback caller."""
    return TestClient(api_server.app, client=("203.0.113.10", 50000))


def _query_body() -> dict:
    return QueryRequest(
        messages=[LlmClientMessage(role="human", content="hi")]
    ).model_dump(mode="json")


@pytest.fixture(autouse=True)
def clear_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every bridge test from dev-mode (keyless loopback) auth."""
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")


@pytest.fixture
def client() -> TestClient:
    return _local_client()


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real adapter so no agent loop is started."""

    class _FakeAdapter:
        async def handle_query(self, request):
            yield message_chunk(text="hello from vibe")

    monkeypatch.setattr(bridge_routes, "_get_adapter", lambda: _FakeAdapter())


def test_agents_json_returns_manifest(client: TestClient):
    response = client.get("/agents.json")

    assert response.status_code == 200
    body = response.json()
    assert bridge_routes.AGENT_KEY in body
    agent = body[bridge_routes.AGENT_KEY]
    assert agent["name"]
    assert agent["features"]["streaming"] is True


def test_agents_json_advertises_an_absolute_query_url(client: TestClient):
    """Workspace stores endpoints.query verbatim, so it must be absolute."""
    response = client.get("/agents.json")

    query_url = response.json()[bridge_routes.AGENT_KEY]["endpoints"]["query"]
    assert query_url.startswith("http://")
    assert query_url.endswith(bridge_routes.QUERY_PATH)


def test_manifest_only_advertises_implemented_features(client: TestClient):
    """widget-dashboard-search needs the get_widget_data round trip we lack."""
    features = client.get("/agents.json").json()[bridge_routes.AGENT_KEY]["features"]

    assert features["widget-dashboard-search"] is False


def test_query_streams_from_adapter(client: TestClient, fake_adapter: None):
    response = client.post("/v1/query", json=_query_body())

    assert response.status_code == 200
    assert "hello from vibe" in response.text


def test_query_reports_when_runtime_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(bridge_routes, "_get_adapter", lambda: None)

    response = client.post("/v1/query", json=_query_body())

    assert response.status_code == 200
    assert "not enabled" in response.text


def test_remote_query_requires_api_key_when_key_unset(fake_adapter: None):
    """Keyless dev mode must not expose the agent registry to the network."""
    response = _remote_client().post("/v1/query", json=_query_body())

    assert response.status_code == 403
    assert "API_AUTH_KEY" in response.json()["detail"]


def test_query_rejects_missing_or_wrong_bearer_when_key_configured(
    monkeypatch: pytest.MonkeyPatch, fake_adapter: None
):
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    for client in (_local_client(), _remote_client()):
        assert client.post("/v1/query", json=_query_body()).status_code == 401
        wrong = client.post(
            "/v1/query",
            json=_query_body(),
            headers={"Authorization": "Bearer nope"},
        )
        assert wrong.status_code == 401


def test_query_accepts_valid_bearer_when_key_configured(
    monkeypatch: pytest.MonkeyPatch, fake_adapter: None
):
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    response = _remote_client().post(
        "/v1/query",
        json=_query_body(),
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert "hello from vibe" in response.text


def test_query_rejects_cross_site_browser_post(fake_adapter: None):
    """A loopback peer is not enough when the POST comes from another origin."""
    response = _local_client().post(
        "/v1/query",
        json=_query_body(),
        headers={
            "Origin": "https://pro.openbb.co",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert response.status_code == 403


def test_unadvertised_ai_service_routes_are_not_mounted(client: TestClient):
    """chat-title / dashboard-title / enhance-prompt were removed, not just hidden."""
    for path in (
        "/v1/generate/chat/title",
        "/v1/generate/dashboard/title",
        "/v1/enhance_prompt",
    ):
        assert client.post(path, json={}).status_code == 404, path
