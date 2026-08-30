"""Tests for the custom OpenAI-compatible provider manager."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import custom_provider_routes
from src.providers.custom_profiles import CustomProviderStore


class _MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


@pytest.fixture()
def custom_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CustomProviderStore:
    store = CustomProviderStore(tmp_path / "custom-providers.json", _MemoryCredentials())
    monkeypatch.setattr(custom_provider_routes, "_build_store", lambda: store)
    return store


@pytest.fixture()
def client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_custom_provider_base_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="without embedded credentials"):
        custom_provider_routes._validate_custom_base_url("https://user:pass@example.test/v1")


@pytest.mark.parametrize("base_url", ["http://127.0.0.1/v1", "http://localhost/v1", "http://169.254.169.254/v1"])
def test_custom_provider_base_url_rejects_local_targets(base_url: str) -> None:
    with pytest.raises(ValueError):
        custom_provider_routes._validate_custom_base_url(base_url)


def test_store_never_serializes_api_key(tmp_path: Path) -> None:
    backend = _MemoryCredentials()
    store = CustomProviderStore(tmp_path / "custom-providers.json", backend)

    store.save(
        profile_id="hilinkup",
        label="Hilinkup",
        base_url="https://api.example.test/v1",
        model="glm-5.3-flash",
        api_key="secret-key",
    )

    payload = json.loads((tmp_path / "custom-providers.json").read_text(encoding="utf-8"))
    assert "secret-key" not in json.dumps(payload)
    assert backend.values
    assert store.list_public()[0]["api_key_configured"] is True


def test_save_requires_a_successful_test(client: TestClient, custom_store: CustomProviderStore) -> None:
    response = client.post(
        "/settings/custom-providers",
        json={
            "id": "hilinkup",
            "label": "Hilinkup",
            "base_url": "https://api.example.test/v1",
            "model": "glm-5.3-flash",
            "api_key": "temporary-key",
            "test_id": "missing-test",
        },
    )

    assert response.status_code == 409
    assert custom_store.list_public() == []
    assert "temporary-key" not in response.text


def test_test_endpoint_returns_no_secret_and_save_then_requires_confirmation(
    client: TestClient,
    custom_store: CustomProviderStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_completion(**_: Any) -> dict[str, Any]:
        return {"response_preview": "CUSTOM_PROVIDER_TEST_OK", "latency_ms": 12}

    monkeypatch.setattr(custom_provider_routes, "_perform_completion_test", fake_completion)
    test_response = client.post(
        "/settings/custom-providers/test",
        json={
            "base_url": "https://api.example.test/v1",
            "model": "glm-5.3-flash",
            "api_key": "temporary-key",
        },
    )

    assert test_response.status_code == 200
    test_body = test_response.json()
    assert test_body["status"] == "ok"
    assert test_body["response_preview"] == "CUSTOM_PROVIDER_TEST_OK"
    assert "temporary-key" not in test_response.text

    save_payload = {
        "id": "hilinkup",
        "label": "Hilinkup",
        "base_url": "https://api.example.test/v1",
        "model": "glm-5.3-flash",
        "api_key": "temporary-key",
        "test_id": test_body["test_id"],
    }
    save_response = client.post("/settings/custom-providers", json=save_payload)
    assert save_response.status_code == 200
    assert "temporary-key" not in save_response.text

    activation = client.post("/settings/custom-providers/hilinkup/activate", json={"confirm": False})
    assert activation.status_code == 400


def test_activation_requires_explicit_confirmation(
    client: TestClient,
    custom_store: CustomProviderStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom_store.save(
        profile_id="hilinkup",
        label="Hilinkup",
        base_url="https://api.example.test/v1",
        model="glm-5.3-flash",
        api_key="secret-key",
    )
    monkeypatch.setattr(custom_provider_routes, "_activate_profile", lambda profile: {"status": "ok"})

    response = client.post(
        "/settings/custom-providers/hilinkup/activate",
        json={"confirm": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Explicit confirmation is required to activate a provider"
