"""API regressions for research goal status and defaults."""

from __future__ import annotations
from tests.recording_helpers import seed_message

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import api_server
from src.session.models import Message


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VIBE_TRADING_GOAL_DB_PATH", str(tmp_path / "goals.db"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setattr(api_server, "_goal_store", None)
    monkeypatch.setattr(api_server, "_session_service", None)
    monkeypatch.setattr(api_server, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _session_id(client: TestClient, *, title: str = "goal api") -> str:
    response = client.post("/sessions", json={"title": title})
    assert response.status_code == 201
    return response.json()["session_id"]


def _add_user_message(session_id: str) -> None:
    service = api_server._get_session_service()
    seed_message(service.store, Message(session_id=session_id, role="user", content="Evaluate NVDA momentum."))


def test_api_goal_uses_full_default_research_checklist(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client)

    response = client.post(f"/sessions/{sid}/goal", json={"objective": "Evaluate NVDA momentum."})

    assert response.status_code == 201
    criteria = response.json()["criteria"]
    assert [item["text"] for item in criteria] == [
        "Define the research-only thesis and symbol universe",
        "Collect fresh market or benchmark evidence",
        "Record caveats, contradictions, and non-advice boundary",
    ]


def test_api_can_complete_goal_with_verified_evidence(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client)
    run_dir = tmp_path / "runs" / "goal-api-run"
    run_dir.mkdir(parents=True)
    goal_response = client.post(
        f"/sessions/{sid}/goal",
        json={"objective": "Evaluate NVDA momentum.", "criteria": ["Check price action"]},
    )
    goal_payload = goal_response.json()
    goal_id = goal_payload["goal"]["goal_id"]
    criterion_id = goal_payload["criteria"][0]["criterion_id"]
    evidence_response = client.post(
        f"/sessions/{sid}/goal/evidence",
        json={
            "goal_id": goal_id,
            "expected_goal_id": goal_id,
            "criterion_id": criterion_id,
            "text": "Backtest artifact supports the criterion.",
            "run_id": "goal-api-run",
        },
    )
    evidence_id = evidence_response.json()["evidence"]["evidence_id"]

    response = client.patch(
        f"/sessions/{sid}/goal/status",
        json={
            "goal_id": goal_id,
            "expected_goal_id": goal_id,
            "status": "complete",
            "audit": [
                {
                    "criterion_id": criterion_id,
                    "result": "satisfied",
                    "evidence_ids": [evidence_id],
                    "notes": "Verified by generated run artifact.",
                }
            ],
            "recap": "Research-only goal completed.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["goal"]["status"] == "complete"
    assert payload["goal"]["recap"] == "Research-only goal completed."
    assert payload["snapshot"]["criteria"][0]["status"] == "satisfied"


def test_api_can_cancel_current_goal(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client)
    goal_payload = client.post(
        f"/sessions/{sid}/goal",
        json={"objective": "Evaluate NVDA momentum."},
    ).json()
    goal_id = goal_payload["goal"]["goal_id"]

    response = client.patch(
        f"/sessions/{sid}/goal/status",
        json={
            "goal_id": goal_id,
            "expected_goal_id": goal_id,
            "status": "cancelled",
            "recap": "Cancelled from API.",
        },
    )

    assert response.status_code == 200
    assert response.json()["goal"]["status"] == "cancelled"
    assert client.get(f"/sessions/{sid}/goal").status_code == 404


def test_api_can_edit_current_goal_objective(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client)
    goal_payload = client.post(
        f"/sessions/{sid}/goal",
        json={"objective": "Evaluate NVDA momentum."},
    ).json()
    goal_id = goal_payload["goal"]["goal_id"]

    response = client.patch(
        f"/sessions/{sid}/goal",
        json={
            "goal_id": goal_id,
            "expected_goal_id": goal_id,
            "objective": "Evaluate NVDA versus QQQ momentum.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["goal"]["goal_id"] == goal_id
    assert payload["goal"]["objective"] == "Evaluate NVDA versus QQQ momentum."
    assert payload["snapshot"]["claims"][0]["text"] == "Evaluate NVDA versus QQQ momentum."


def test_auto_title_closes_chat_client(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client, title="")
    _add_user_message(sid)
    response = MagicMock(content="NVDA Momentum Review")

    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.return_value = response
        result = client.post(f"/sessions/{sid}/title/auto")

    assert result.status_code == 200
    assert result.json()["title"] == "NVDA Momentum Review"
    chat_cls.return_value.close.assert_called_once_with()


def test_auto_title_closes_chat_client_when_model_returns_empty(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client, title="")
    _add_user_message(sid)
    response = MagicMock(content="")

    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.return_value = response
        result = client.post(f"/sessions/{sid}/title/auto")

    assert result.status_code == 502
    assert result.json()["detail"] == "empty title from model"
    chat_cls.return_value.close.assert_called_once_with()


def test_auto_title_closes_chat_client_when_provider_fails(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = _session_id(client, title="")
    _add_user_message(sid)

    with patch("src.providers.chat.ChatLLM") as chat_cls:
        chat_cls.return_value.chat.side_effect = RuntimeError("provider unavailable")
        result = client.post(f"/sessions/{sid}/title/auto")

    assert result.status_code == 502
    chat_cls.return_value.close.assert_called_once_with()
