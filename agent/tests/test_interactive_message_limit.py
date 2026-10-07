"""Exercise the actual chat route's validation without invoking a model."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api.sessions_routes import MAX_MESSAGE_CHARS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("VIBE_TRADING_API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.mark.parametrize("content", ["x" * 5001, "研" * 100_000, "📈" * 100_000])
def test_long_prompt_passes_validation_and_reaches_session_lookup(client, content):
    response = client.post("/sessions/nosuch/messages", json={"content": content})
    assert response.status_code == 404


def test_oversized_prompt_returns_compact_actionable_error_without_input(client):
    content = "private_research_" + "x" * MAX_MESSAGE_CHARS
    response = client.post("/sessions/nosuch/messages", json={"content": content})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "message_too_long"
    assert response.json()["detail"]["max_length"] == MAX_MESSAGE_CHARS
    assert len(response.content) < 1000
    assert "private_research_" not in response.text


def test_empty_prompt_keeps_normal_validation(client):
    response = client.post("/sessions/nosuch/messages", json={"content": ""})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_short"


def test_frontend_message_bound_matches_the_server_schema():
    frontend = Path(__file__).resolve().parents[2] / "frontend/src/lib/chatPrompt.ts"
    constant = re.search(r"MAX_MESSAGE_CHARS = ([\d_]+)", frontend.read_text())
    assert constant is not None
    assert int(constant[1].replace("_", "")) == MAX_MESSAGE_CHARS
