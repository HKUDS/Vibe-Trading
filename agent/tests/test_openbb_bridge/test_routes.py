"""Integration tests for the OpenBB Workspace bridge HTTP endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("openbb_ai")

import api_server
from openbb_ai.helpers import message_chunk
from openbb_ai.models import LlmClientMessage, QueryRequest
from src.openbb_bridge import routes as bridge_routes
from src.openbb_bridge import ai_service_routes


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_agents_json_returns_manifest(client: TestClient):
    response = client.get("/agents.json")
    assert response.status_code == 200
    body = response.json()
    assert bridge_routes.AGENT_KEY in body
    agent = body[bridge_routes.AGENT_KEY]
    assert agent["name"]
    assert agent["endpoints"]["query"] == "/v1/query"
    assert agent["features"]["streaming"] is True


def test_query_streams_from_adapter(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeAdapter:
        async def handle_query(self, request):
            yield message_chunk(text="hello from vibe")

    monkeypatch.setattr(bridge_routes, "_get_adapter", lambda: _FakeAdapter())

    body = QueryRequest(
        messages=[LlmClientMessage(role="human", content="hi")]
    ).model_dump(mode="json")

    response = client.post("/v1/query", json=body)
    assert response.status_code == 200
    assert "hello from vibe" in response.text


def test_query_reports_when_runtime_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(bridge_routes, "_get_adapter", lambda: None)

    body = QueryRequest(
        messages=[LlmClientMessage(role="human", content="hi")]
    ).model_dump(mode="json")

    response = client.post("/v1/query", json=body)
    assert response.status_code == 200
    assert "not enabled" in response.text


def test_enhance_prompt_uses_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ai_service_routes, "_run_llm", lambda system, user: "an enhanced prompt"
    )
    response = client.post("/v1/enhance_prompt", json={"prompt": "stocks?"})
    assert response.status_code == 200
    assert response.json()["prompt"] == "an enhanced prompt"


def test_chat_title_falls_back_on_empty(client: TestClient):
    response = client.post("/v1/generate/chat/title", json={"messages": []})
    assert response.status_code == 200
    assert response.json()["title"] == "New chat"
