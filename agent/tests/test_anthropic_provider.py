"""Regression coverage for Anthropic model-specific request parameters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.providers import llm


def _capture_anthropic_kwargs(monkeypatch, model: str, temperature: float) -> dict:
    captured: dict = {}

    def fake_chat_anthropic(**kwargs):
        captured.update(kwargs)
        return object()

    fake_module = SimpleNamespace(ChatAnthropic=fake_chat_anthropic)
    fake_config = SimpleNamespace(
        llm=SimpleNamespace(
            anthropic_max_tokens=None,
            timeout_seconds=120,
            max_retries=2,
        )
    )
    monkeypatch.setattr(llm, "import_module", lambda _name: fake_module)
    monkeypatch.setattr(llm, "get_env_config", lambda: fake_config)

    llm._build_anthropic(model=model, temperature=temperature)
    return captured


def test_opus_4_7_omits_deprecated_temperature(monkeypatch) -> None:
    """Claude Opus 4.7 rejects requests that include temperature."""
    kwargs = _capture_anthropic_kwargs(monkeypatch, "claude-opus-4-7", 0.3)

    assert "temperature" not in kwargs


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-7-20260725",
        "anthropic.claude-opus-4-7-v1:0",
    ],
)
def test_opus_4_7_model_variants_omit_deprecated_temperature(
    monkeypatch, model: str
) -> None:
    """Dated and provider-qualified Opus 4.7 IDs follow the same restriction."""
    kwargs = _capture_anthropic_kwargs(monkeypatch, model, 0.3)

    assert "temperature" not in kwargs


def test_older_anthropic_models_keep_configured_temperature(monkeypatch) -> None:
    """Existing Anthropic model behavior remains unchanged."""
    kwargs = _capture_anthropic_kwargs(monkeypatch, "claude-sonnet-4-6", 0.3)

    assert kwargs["temperature"] == 0.3


def test_older_opus_models_keep_configured_temperature(monkeypatch) -> None:
    """The restriction does not change older Opus request behavior."""
    kwargs = _capture_anthropic_kwargs(monkeypatch, "claude-opus-4-6", 0.3)

    assert kwargs["temperature"] == 0.3


def test_other_opus_versions_keep_configured_temperature(monkeypatch) -> None:
    """Do not infer the Opus 4.7 restriction for unreported model versions."""
    kwargs = _capture_anthropic_kwargs(monkeypatch, "claude-opus-4-8", 0.3)

    assert kwargs["temperature"] == 0.3
