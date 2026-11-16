"""Gateway contracts and real SDK/HTTP integration through saved settings."""

from __future__ import annotations

from contextlib import closing

from tests.provider_helpers import provider_server as provider_server
from tests.provider_helpers import assert_stream_tool_roundtrip

from src.providers.registry import provider_catalog as catalog
from src.providers.settings import resolve_config
from src.providers.registry import get_provider_capabilities


def test_model_inference_does_not_change_explicit_adapter_family(monkeypatch):
    route = resolve_config(environment={"LANGCHAIN_PROVIDER": "openrouter", "LANGCHAIN_MODEL_NAME": "anthropic/claude-test"})
    assert route.backend == "openai_compatible"
    assert get_provider_capabilities(route.provider, route.model).name == "openrouter"
    route = resolve_config(environment={"LANGCHAIN_PROVIDER": "openai", "LANGCHAIN_MODEL_NAME": "deepseek-test"})
    assert route.backend == "openai_compatible"
    assert get_provider_capabilities(route.provider, route.model).name == "deepseek"
    from src.providers import llm as llm_module

    monkeypatch.setattr(llm_module, "resolve_config", lambda: route)
    monkeypatch.setattr(llm_module, "_package_version", lambda _: "installed")
    assert llm_module.provider_diagnostics()["adapter"]["type"] == "openai-compatible"
    assert resolve_config(environment={"LANGCHAIN_PROVIDER": "openai_codex", "LANGCHAIN_MODEL_NAME": "test"}).backend == "openai_codex"
    assert resolve_config(environment={"LANGCHAIN_PROVIDER": "github-copilot", "LANGCHAIN_MODEL_NAME": "test"}).backend == "copilot"
    assert resolve_config(environment={"LANGCHAIN_PROVIDER": "unknown-legacy-relay", "LANGCHAIN_MODEL_NAME": "test"}).backend == "openai_compatible"


def test_catalog_callers_cannot_mutate_gateway_configuration():
    rows = catalog()
    rows[0]["default_model"] = "changed"
    rows[0].setdefault("model_options", []).append("changed")
    assert catalog()[0]["default_model"] != "changed"
    assert "changed" not in catalog()[0].get("model_options", [])


def test_settings_to_real_sdk_stream_and_tool_followup(tmp_path, monkeypatch, provider_server):
    """Saved settings -> real SDK -> HTTP SSE -> fragmented tool call -> follow-up."""
    from fastapi.testclient import TestClient
    import api_server
    from src.providers.chat import ChatLLM

    base_url, received = provider_server
    for name in ("ENV_PATH", "ENV_EXAMPLE_PATH", "LEGACY_ENV_PATH"):
        monkeypatch.setattr(api_server, name, tmp_path / name, raising=False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setenv("VIBE_TRADING_DISABLE_HTTP_PROXY", "1")
    monkeypatch.setenv("LANGCHAIN_USE_RESPONSES_API", "false")
    with TestClient(api_server.app, client=("127.0.0.1", 50000)) as client:
        response = client.put("/settings/llm", json={
            "provider": "ollama", "model_name": "gateway-test", "base_url": base_url,
            "temperature": 0, "timeout_seconds": 10, "max_retries": 0,
        })
        assert response.status_code == 200, response.text
        provider = next(p for p in response.json()["providers"] if p["name"] == "ollama")
        assert provider["backend"] == "openai_compatible"
        with closing(ChatLLM()) as llm:
            assert_stream_tool_roundtrip(llm, "gateway-test")
    assert len(received) == 2
    assert all(path == "/v1/chat/completions" for path, _, _ in received)
    assert received[1][2]["messages"][-1]["tool_call_id"] == "call_quote"


def test_catalog_only_provider_reaches_settings_and_real_sdk(tmp_path, provider_server):
    """Cold-start CLI setup -> API update -> frozen clients -> actual HTTP requests."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    from textwrap import dedent
    from src.providers.registry import CATALOG_PATH

    base_url, received = provider_server
    row = {
        "name": "catalog-test", "label": "Catalog Test", "api_key_env": "CATALOG_TEST_KEY",
        "base_url_env": "CATALOG_TEST_URL", "default_model": "catalog-model",
        "default_base_url": base_url, "api_key_required": True,
        "setup": {"order": 100}, "onboarding": {"order": 100},
    }
    path = tmp_path / "providers.json"
    path.write_text(json.dumps([*json.loads(CATALOG_PATH.read_text()), row]))
    script = dedent("""
        import os, sys
        from pathlib import Path
        from contextlib import closing
        from unittest.mock import patch
        from src.providers import registry
        registry.CATALOG_PATH = Path(sys.argv[1])
        from cli import _legacy, onboard
        from src.providers.chat import ChatLLM
        from src.providers.settings import SettingsStore, secret_names
        assert onboard.PROVIDERS[-1].key == "catalog-test"
        with patch.object(_legacy.IntPrompt, "ask", return_value=len(_legacy._PROVIDER_CHOICES)), \
             patch.object(_legacy.Prompt, "ask", side_effect=["cli-secret", sys.argv[2], "cli-model", ""]):
            assert _legacy.cmd_init() == 0
        with closing(ChatLLM()) as old:
            import api_server
            from fastapi.testclient import TestClient
            with TestClient(api_server.app, client=("127.0.0.1", 50000)) as api:
                current = api.get("/settings/llm").json()
                assert current["provider"] == "catalog-test" and current["api_key_configured"]
                assert current["providers"][-1]["api_key_env"] == "CATALOG_TEST_KEY"
                response = api.put("/settings/llm", json={
                    "provider": "catalog-test", "model_name": "api-model", "api_key": "api-secret",
                })
                assert response.status_code == 200, response.text
                assert "api-secret" not in response.text and "cli-secret" not in response.text
                with closing(ChatLLM()) as new:
                    assert new.chat([{"role": "user", "content": "hello"}]).content == "api-model"
                assert old.chat([{"role": "user", "content": "hello"}]).content == "cli-model"
                os.environ["VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS"] = "1"
                assert "CATALOG_TEST_KEY" in secret_names()
                assert api.put("/settings/llm", json={"provider": "catalog-test", "model_name": "api-model"}).status_code == 200
                assert SettingsStore().read()["CATALOG_TEST_KEY"] == "api-secret"
                assert "api-secret" not in SettingsStore().path.read_text()
        """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), base_url],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=90,
        env={**{k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ},
             "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "VIBE_TRADING_HOME": str(tmp_path),
             "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "OPENAI_API_KEY": "wrong-secret",
             "LANGCHAIN_USE_RESPONSES_API": "false", "VIBE_TRADING_DISABLE_HTTP_PROXY": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert [(body["model"], headers["Authorization"]) for _, headers, body in received] == [
        ("api-model", "Bearer api-secret"), ("cli-model", "Bearer cli-secret"),
    ]
