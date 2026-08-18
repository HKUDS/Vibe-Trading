"""Regression tests for local settings API endpoints."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import settings_routes
from tests.module_os_helpers import patch_module_os


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    env_example = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    env_example.write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=openrouter",
                "LANGCHAIN_MODEL_NAME=deepseek/deepseek-v4-pro",
                "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1",
                "OPENROUTER_API_KEY=sk-or-v1-your-key-here",
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
    monkeypatch.setattr(api_server, "LEGACY_ENV_PATH", tmp_path / "legacy" / ".env", raising=False)
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(api_server, "_baostock_supported", lambda: False)
    monkeypatch.setattr(api_server, "_baostock_installed", lambda: False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_get_llm_settings_is_side_effect_free_and_hides_placeholders(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.get("/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openrouter"
    assert body["model_name"] == "deepseek/deepseek-v4-pro"
    assert body["api_key_configured"] is False
    assert body["api_key_hint"] is None
    assert not Path(body["env_path"]).is_absolute()
    assert body["env_path"].endswith(".env")
    assert body["reasoning_effort"] == "max"
    assert not (tmp_path / ".env").exists()


def test_extract_model_ids_normalizes_openai_compatible_payloads() -> None:
    assert settings_routes._extract_model_ids(
        {"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-a"}]}
    ) == ["model-a", "model-b"]
    assert settings_routes._extract_model_ids(
        {"models": [{"name": "models/gemini-test"}, "custom-model"]}
    ) == ["custom-model", "models/gemini-test"]


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (
            {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
            "api_key_required",
        ),
        (
            {
                "provider": "openai-codex",
                "base_url": "https://chatgpt.com/backend-api/codex/responses",
            },
            "oauth_discovery_unsupported",
        ),
    ],
)
def test_model_discovery_returns_stable_warning_codes_not_english_prose(
    client: TestClient,
    payload: dict[str, str],
    expected_code: str,
) -> None:
    response = client.post("/settings/llm/models", json=payload)

    assert response.status_code == 200
    assert response.json()["warning_code"] == expected_code
    assert "warning" not in response.json()


def test_list_llm_models_uses_unsaved_form_values(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    async def fake_list(provider, *, base_url: str, api_key: str):
        observed.update(provider=provider.name, base_url=base_url, api_key=api_key)
        return settings_routes.LLMModelsResponse(
            provider=provider.name,
            models=[provider.default_model, "deepseek-v4-flash"],
            source="provider",
        )

    monkeypatch.setattr(settings_routes, "_list_provider_models", fake_list)
    response = client.post(
        "/settings/llm/models",
        json={
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "temporary-form-key",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert observed == {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "temporary-form-key",
    }


def test_list_llm_models_does_not_send_saved_key_to_unsaved_endpoint(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=deepseek",
                "LANGCHAIN_MODEL_NAME=deepseek-v4-pro",
                "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1",
                "DEEPSEEK_API_KEY=stored-secret-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    observed: list[tuple[str, str]] = []

    async def fake_list(provider, *, base_url: str, api_key: str):
        del provider
        observed.append((base_url, api_key))
        return settings_routes.LLMModelsResponse(
            provider="deepseek",
            models=["deepseek-v4-pro"],
            source="provider",
        )

    monkeypatch.setattr(settings_routes, "_list_provider_models", fake_list)

    trusted = client.post(
        "/settings/llm/models",
        json={"provider": "deepseek", "base_url": "https://api.deepseek.com/v1"},
    )
    untrusted = client.post(
        "/settings/llm/models",
        json={"provider": "deepseek", "base_url": "https://models.example.test/v1"},
    )

    assert trusted.status_code == 200
    assert untrusted.status_code == 200
    assert observed == [
        ("https://api.deepseek.com/v1", "stored-secret-key"),
        ("https://models.example.test/v1", ""),
    ]


@pytest.mark.parametrize("placeholder", ["sk-xxx", "xxx", "gsk_xxx"])
def test_llm_settings_treat_documented_key_placeholders_as_unconfigured(
    client: TestClient, tmp_path: Path, placeholder: str,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=deepseek",
                "LANGCHAIN_MODEL_NAME=deepseek-v4-pro",
                f"DEEPSEEK_API_KEY={placeholder}",
                "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get("/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["api_key_configured"] is False
    assert body["api_key_hint"] is None
    assert placeholder not in response.text


def test_update_llm_settings_persists_project_env(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.put(
        "/settings/llm",
        json={
            "provider": "openrouter",
            "model_name": "deepseek/deepseek-v4-pro",
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
    assert body["api_key_hint"] is None
    assert "or-secret-value" not in response.text
    assert "or-s...alue" not in response.text

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LANGCHAIN_PROVIDER=openrouter" in env_text
    assert "OPENROUTER_API_KEY=or-secret-value" in env_text
    assert "LANGCHAIN_REASONING_EFFORT=max" in env_text
    assert "sk-or-v1-your-key-here" not in env_text


def test_update_deepseek_settings_uses_exact_reported_payload(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.put(
        "/settings/llm",
        json={
            "provider": "deepseek",
            "model_name": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-deepseek-test",
            "temperature": 0.0,
            "timeout_seconds": 120,
            "max_retries": 2,
            "reasoning_effort": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "deepseek"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-deepseek-test" in env_text
    assert "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1" in env_text


def test_desktop_secure_mode_never_persists_injected_llm_key(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dpapi-decrypted-key")

    response = client.put(
        "/settings/llm",
        json={
            "provider": "deepseek",
            "model_name": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    )

    assert response.status_code == 200
    assert response.json()["api_key_configured"] is True
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "dpapi-decrypted-key" not in env_text
    assert "DEEPSEEK_API_KEY=" in env_text


@pytest.mark.parametrize(
    ("provider", "api_key_env", "base_url_env", "base_url"),
    [
        (
            "siliconflow-cn",
            "SILICONFLOW_API_KEY",
            "SILICONFLOW_BASE_URL",
            "https://api.siliconflow.cn/v1",
        ),
        (
            "siliconflow-global",
            "SILICONFLOW_GLOBAL_API_KEY",
            "SILICONFLOW_GLOBAL_BASE_URL",
            "https://api.siliconflow.com/v1",
        ),
    ],
)
def test_update_siliconflow_settings_uses_provider_namespace(
    client: TestClient,
    tmp_path: Path,
    provider: str,
    api_key_env: str,
    base_url_env: str,
    base_url: str,
) -> None:
    response = client.put(
        "/settings/llm",
        json={
            "provider": provider,
            "model_name": "deepseek-ai/DeepSeek-V3.1-Terminus",
            "base_url": base_url,
            "api_key": "sk-siliconflow-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == provider
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"{api_key_env}=sk-siliconflow-test" in env_text
    assert f"{base_url_env}={base_url}" in env_text


def test_settings_write_migrates_legacy_env_to_canonical_path(
    client: TestClient, tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy" / ".env"
    legacy_path.parent.mkdir()
    legacy_path.write_text(
        "LANGCHAIN_PROVIDER=openrouter\nTUSHARE_TOKEN=legacy-token\n",
        encoding="utf-8",
    )

    response = client.put(
        "/settings/llm",
        json={
            "provider": "deepseek",
            "model_name": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-deepseek-test",
        },
    )

    assert response.status_code == 200
    canonical_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LANGCHAIN_PROVIDER=deepseek" in canonical_text
    assert "TUSHARE_TOKEN=legacy-token" in canonical_text
    assert legacy_path.read_text(encoding="utf-8").startswith("LANGCHAIN_PROVIDER=openrouter")


def test_settings_write_permission_error_is_actionable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_server,
        "_write_env_values",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    response = client.put(
        "/settings/llm",
        json={
            "provider": "deepseek",
            "model_name": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-deepseek-test",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Unable to save settings; check ownership and permissions for "
        "~/.vibe-trading/.env"
    )


def test_update_nvidia_settings_persists_provider_namespace(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.put(
        "/settings/llm",
        json={
            "provider": "nvidia",
            "model_name": "nvidia/nemotron-3-ultra-550b-a55b",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "api_key": "nvapi-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "nvidia"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "NVIDIA_API_KEY=nvapi-test" in env_text
    assert "NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1" in env_text


def test_get_data_source_settings_treats_placeholder_as_unconfigured(
    client: TestClient, tmp_path: Path,
) -> None:
    response = client.get("/settings/data-sources")

    assert response.status_code == 200
    body = response.json()
    assert body["tushare_token_configured"] is False
    assert body["tushare_token_hint"] is None
    assert body["baostock_supported"] is False
    assert body["baostock_installed"] is False
    assert not Path(body["env_path"]).is_absolute()
    assert body["env_path"].endswith(".env")
    assert not (tmp_path / ".env").exists()


def test_settings_response_never_exposes_configured_secret_hints(
    client: TestClient, tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=openrouter",
                "OPENROUTER_API_KEY=or-secret-private-value",
                "TUSHARE_TOKEN=ts-secret-private-token",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    llm_response = client.get("/settings/llm")
    data_response = client.get("/settings/data-sources")

    assert llm_response.status_code == 200
    assert data_response.status_code == 200
    llm_body = llm_response.json()
    data_body = data_response.json()
    assert llm_body["api_key_configured"] is True
    assert llm_body["api_key_hint"] is None
    assert data_body["tushare_token_configured"] is True
    assert data_body["tushare_token_hint"] is None
    assert "or-secret-private-value" not in llm_response.text
    assert "or-s...alue" not in llm_response.text
    assert "ts-secret-private-token" not in data_response.text
    assert "ts-s...oken" not in data_response.text


def test_settings_reads_reject_remote_dev_mode_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    env_path.write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=openrouter",
                "OPENROUTER_API_KEY=or-secret-value",
                "TUSHARE_TOKEN=ts-secret-token",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env_example.write_text("LANGCHAIN_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setattr(api_server, "ENV_PATH", env_path)
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    remote_client = TestClient(api_server.app, client=("203.0.113.10", 50000))

    llm_response = remote_client.get("/settings/llm")
    data_source_response = remote_client.get("/settings/data-sources")

    assert llm_response.status_code == 403
    assert data_source_response.status_code == 403
    assert "or-s...alue" not in llm_response.text
    assert "ts-s...oken" not in data_source_response.text


def test_settings_reads_require_bearer_on_loopback_when_api_auth_key_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    env_path.write_text(
        "\n".join(
            [
                "LANGCHAIN_PROVIDER=openrouter",
                "OPENROUTER_API_KEY=or-secret-value",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env_example.write_text("LANGCHAIN_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setattr(api_server, "ENV_PATH", env_path)
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setenv("API_AUTH_KEY", "settings-secret")
    local_client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    unauthenticated_response = local_client.get("/settings/llm")
    authenticated_response = local_client.get(
        "/settings/llm",
        headers={"Authorization": "Bearer settings-secret"},
    )

    # GHSA-7wgj: a configured key gates settings reads even on loopback (the
    # bundled frontend sends the bearer once the key is stored in Settings).
    assert unauthenticated_response.status_code == 401
    assert authenticated_response.status_code == 200
    assert authenticated_response.json()["api_key_configured"] is True
    assert authenticated_response.json()["api_key_hint"] is None
    assert "or-secret-value" not in authenticated_response.text
    assert "or-s...alue" not in authenticated_response.text


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
    assert body["tushare_token_hint"] is None
    assert "ts-secret-token" not in response.text
    assert "ts-s...oken" not in response.text

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TUSHARE_TOKEN=ts-secret-token" in env_text


def test_desktop_secure_mode_never_persists_injected_tushare_token(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS", "1")
    monkeypatch.setenv("TUSHARE_TOKEN", "dpapi-tushare-token")

    response = client.put("/settings/data-sources", json={})

    assert response.status_code == 200
    assert response.json()["tushare_token_configured"] is True
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "dpapi-tushare-token" not in env_text
    assert "TUSHARE_TOKEN=" in env_text


def test_settings_writes_reject_remote_dev_mode_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_example = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    env_example.write_text("LANGCHAIN_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setattr(api_server, "ENV_PATH", env_path)
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    remote_client = TestClient(api_server.app, client=("203.0.113.10", 50000))

    response = remote_client.put(
        "/settings/data-sources",
        json={"tushare_token": "ts-secret-token"},
    )

    assert response.status_code == 403
    assert not env_path.exists()


def test_update_settings_writes_env_file_with_0600_mode(
    client: TestClient, tmp_path: Path,
) -> None:
    """A Web-UI settings write must leave agent/.env owner-read/write only."""
    response = client.put(
        "/settings/data-sources",
        json={"tushare_token": "ts-secret-token"},
    )

    assert response.status_code == 200
    mode = (tmp_path / ".env").stat().st_mode & 0o777
    if os.name != "nt":
        assert mode == 0o600


def test_atomic_write_secret_is_crash_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash during the replace must not corrupt or truncate the secret file,
    nor leave a stray temp file holding the secret behind."""
    from src.api import helpers

    target = tmp_path / ".env"
    target.write_text("OLD=1\n", encoding="utf-8")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash before commit")

    patch_module_os(monkeypatch, helpers, replace=_boom)

    with pytest.raises(OSError):
        helpers._atomic_write_secret(target, "NEW=2\n")

    # Original content is intact — the swap never happened.
    assert target.read_text(encoding="utf-8") == "OLD=1\n"
    # No half-written temp secret left in the directory.
    assert list(tmp_path.glob(".env.*")) == []


def test_atomic_write_secret_creates_0600_file(tmp_path: Path) -> None:
    """Fresh secret files are created owner-only via the atomic path."""
    from src.api import helpers

    target = tmp_path / ".env"
    helpers._atomic_write_secret(target, "KEY=value\n")

    assert target.read_text(encoding="utf-8") == "KEY=value\n"
    if os.name != "nt":
        assert (target.stat().st_mode & 0o777) == 0o600


def test_atomic_write_secret_supports_platforms_without_fchmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows must be able to persist Web UI settings without ``os.fchmod``."""
    from src.api import helpers

    monkeypatch.delattr(helpers.os, "fchmod", raising=False)
    target = tmp_path / ".env"

    helpers._atomic_write_secret(target, "KEY=value\n")

    assert target.read_text(encoding="utf-8") == "KEY=value\n"
