"""Regression tests for local settings API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    env_example = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    env_example.write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=deepseek",
                "LANGCHAIN_MODEL_NAME=deepseek-chat",
                "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1",
                "DEEPSEEK_API_KEY=sk-test-secret",
                "LANGCHAIN_TEMPERATURE=0.2",
                "TIMEOUT_SECONDS=90",
                "MAX_RETRIES=3",
                "LANGCHAIN_REASONING_EFFORT=max",
                "TUSHARE_TOKEN=your-tushare-token",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_server, "ENV_PATH", env_path)
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(api_server, "_baostock_supported", lambda: False)
    monkeypatch.setattr(api_server, "_baostock_installed", lambda: False)
    return TestClient(api_server.app)


def test_get_llm_settings_masks_configured_secret(client: TestClient) -> None:
    response = client.get("/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deepseek"
    assert body["model_name"] == "deepseek-chat"
    assert body["api_key_configured"] is True
    assert body["api_key_hint"] == "sk-t...cret"
    assert "sk-test-secret" not in response.text
    assert body["reasoning_effort"] == "max"


def test_update_llm_settings_persists_project_env(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.put(
        "/settings/llm",
        json={
            "provider": "openrouter",
            "model_name": "deepseek/deepseek-v3.2",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "or-secret-value",
            "temperature": 0.1,
            "timeout_seconds": 45,
            "max_retries": 1,
            "reasoning_effort": "max",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openrouter"
    assert body["api_key_configured"] is True
    assert body["api_key_hint"] == "or-s...alue"

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LANGCHAIN_PROVIDER=openrouter" in env_text
    assert "OPENROUTER_API_KEY=or-secret-value" in env_text
    assert "LANGCHAIN_REASONING_EFFORT=max" in env_text


def test_get_data_source_settings_treats_placeholder_as_unconfigured(
    client: TestClient,
) -> None:
    response = client.get("/settings/data-sources")

    assert response.status_code == 200
    body = response.json()
    assert body["tushare_token_configured"] is False
    assert body["tushare_token_hint"] is None
    assert body["baostock_supported"] is False
    assert body["baostock_installed"] is False


def test_update_data_source_settings_persists_tushare_token(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.put(
        "/settings/data-sources",
        json={"tushare_token": "ts-secret-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tushare_token_configured"] is True
    assert body["tushare_token_hint"] == "ts-s...oken"

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TUSHARE_TOKEN=ts-secret-token" in env_text
