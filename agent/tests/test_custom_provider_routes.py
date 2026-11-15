"""Tests for the custom OpenAI-compatible provider manager."""

from __future__ import annotations
from src.providers import custom_profiles

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
    monkeypatch.setattr(custom_provider_routes, "CustomProviderStore", lambda: store)
    return store


@pytest.fixture()
def client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_custom_provider_base_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="without embedded credentials"):
        custom_provider_routes._validate_custom_base_url("https://user:pass@example.test/v1")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1/v1",
        "http://localhost/v1",
        "http://169.254.169.254/v1",
        "http://100.100.100.200/v1",
        "http://[::ffff:127.0.0.1]/v1",
        "http://[::ffff:100.100.100.200]/v1",
    ],
)
def test_custom_provider_base_url_rejects_local_targets(base_url: str) -> None:
    with pytest.raises(ValueError):
        custom_provider_routes._validate_custom_base_url(base_url)


def test_custom_provider_base_url_accepts_a_public_address() -> None:
    assert custom_provider_routes._validate_custom_base_url("https://8.8.8.8/v1") == "https://8.8.8.8/v1"


@pytest.mark.parametrize("resolved", ["100.100.100.200", "10.0.0.5", "::ffff:169.254.169.254"])
def test_custom_provider_dns_target_rejects_non_public_resolution(
    monkeypatch: pytest.MonkeyPatch, resolved: str
) -> None:
    monkeypatch.setattr(
        custom_profiles.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", (resolved, 0))],
    )
    with pytest.raises(ValueError, match="resolves to a local or private network address"):
        custom_profiles._reject_private_dns_targets("https://provider.example/v1")


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
    monkeypatch.setattr(custom_provider_routes, "activate_custom_provider", lambda profile, **kwargs: {"status": "ok"})

    response = client.post(
        "/settings/custom-providers/hilinkup/activate",
        json={"confirm": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Explicit confirmation is required to activate a provider"


def test_activate_constructs_a_model_with_one_vault_profile(
    client, custom_store, tmp_path, monkeypatch
):
    from src.providers import llm, settings as provider_settings
    from src.providers.settings import get_llm_credentials

    custom_store.save(profile_id="alpha", label="Alpha", base_url="https://alpha.example/v1", model="alpha-model", api_key="alpha-secret")
    monkeypatch.setattr(custom_profiles, "CustomProviderStore", lambda: custom_store)
    monkeypatch.setattr(api_server, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(api_server, "LEGACY_ENV_PATH", tmp_path / "absent-env")
    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://other.example/v1")
    # Track process values so pytest restores them after the route updates them.
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "other-model")
    monkeypatch.setattr(provider_settings, "_ensure_dotenv", lambda: None)
    response = client.post("/settings/custom-providers/alpha/activate", json={"confirm": True})
    assert response.status_code == 200
    assert "secret" not in response.text
    assert "secret" not in (tmp_path / ".env").read_text()
    creds = get_llm_credentials("custom", "stale-model")
    assert creds == {"provider": "custom", "model": "alpha-model", "base_url": "https://alpha.example/v1", "api_key": "alpha-secret"}
    model = llm.build_llm()
    assert model.model_name == "alpha-model"
    assert model.openai_api_base == "https://alpha.example/v1"
    assert model.openai_api_key.get_secret_value() == "alpha-secret"
    settings = client.get("/settings/llm").json()
    assert settings["provider"] == "custom"
    assert settings["model_name"] == "alpha-model"
    assert settings["base_url"] == "https://alpha.example/v1"
    assert custom_store.list_public()[0]["active"] is True
    with pytest.raises(ValueError, match="new id"):
        custom_store.save(profile_id="alpha", label="Changed", base_url="https://changed.example/v1", model="changed-model", api_key="changed-key")
    assert get_llm_credentials("custom", None)["api_key"] == "alpha-secret"


def test_missing_vault_profile_never_falls_back_to_an_ambient_key(custom_store, monkeypatch):
    from src.providers import custom_profiles
    from src.providers.settings import get_llm_credentials

    monkeypatch.setattr(custom_profiles, "CustomProviderStore", lambda: custom_store)
    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-secret")
    with pytest.raises(RuntimeError, match="No custom provider"):
        get_llm_credentials("custom", None)


def test_vault_namespace_does_not_overwrite_a_broker_connection(custom_store):
    custom_store.credentials.save("alpha", {"api_key": "broker-secret"})
    custom_store.save(profile_id="alpha", label="Alpha", base_url="https://alpha.example/v1", model="alpha", api_key="llm-secret")
    assert custom_store.credentials.load("alpha", ["api_key"]) == {"api_key": "broker-secret"}
    assert custom_store.get("alpha")["api_key"] == "llm-secret"


def test_parallel_saves_retain_every_profile(custom_store):
    from concurrent.futures import ThreadPoolExecutor

    def save(i):
        return custom_store.save(profile_id=f"p{i}", label=f"P{i}", base_url="https://example.test/v1", model="alpha", api_key="synthetic-key")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(12)))
    assert len(custom_store.list_public()) == 12


def test_full_completion_url_normalizes_to_the_runtime_api_root():
    assert custom_provider_routes._validate_custom_base_url("https://example.test/v1/chat/completions/") == "https://example.test/v1"
    with pytest.raises(ValueError):
        custom_provider_routes._validate_custom_base_url("https://example.test/v1?api_key=secret")


def test_failed_activation_keeps_previous_profile(custom_store, tmp_path, monkeypatch):
    from src.providers.settings import SettingsStore

    for name in ("first", "second"):
        custom_store.save(profile_id=name, label=name, base_url=f"https://{name}.test/v1", model=name, api_key=f"{name}-key")
    custom_store.activate("first")
    def fail_write(self, _, **kwargs):
        raise OSError("Unable to save settings")
    monkeypatch.setattr(SettingsStore, "persist", fail_write)
    with pytest.raises(OSError):
        custom_profiles.activate_custom_provider("second", store=custom_store)
    assert custom_store._read()["active_id"] == "first"


def test_real_completion_transport_redacts_key_and_sends_expected_request(monkeypatch):
    import asyncio
    import httpx

    actual_client = httpx.AsyncClient
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK synthetic-secret"}}]})
    monkeypatch.setattr(custom_profiles, "_reject_private_dns_targets", lambda _: None)
    monkeypatch.setattr(custom_profiles, "proxy_applies", lambda _: False)
    monkeypatch.setattr(custom_profiles, "public_only_async_client", lambda **kw: actual_client(transport=httpx.MockTransport(handle), **kw))
    result = asyncio.run(custom_provider_routes._perform_completion_test(base_url="https://example.test/v1", model="demo", api_key="synthetic-secret"))
    assert result["response_preview"] == "OK [redacted]"
    assert str(seen[0].url) == "https://example.test/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer synthetic-secret"
    assert json.loads(seen[0].content)["model"] == "demo"


def test_cli_custom_commands_are_registered():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "cli.main", "provider", "custom", "--help"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "activate" in result.stdout
    assert "add" in result.stdout


def test_activation_write_failure_is_actionable_and_rolls_back(client, custom_store, monkeypatch):
    from src.providers.settings import SettingsStore

    custom_store.save(profile_id='first', label='First', base_url='https://first.test/v1', model='first', api_key='key')
    custom_store.save(profile_id='second', label='Second', base_url='https://second.test/v1', model='second', api_key='key')
    custom_store.activate('first')

    def fail_write(self, updates, **kwargs):
        raise PermissionError('private filesystem path')

    monkeypatch.setattr(SettingsStore, 'persist', fail_write)
    response = client.post('/settings/custom-providers/second/activate', json={'confirm': True})
    assert response.status_code == 503
    assert 'check ownership and permissions' in response.json()['detail']
    assert 'private filesystem path' not in response.text
    assert custom_store._read()['active_id'] == 'first'
