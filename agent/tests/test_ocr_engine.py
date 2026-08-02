"""Tests for the pluggable OCR engine factory.

Cloud OCR uploads document pages to a third party, so cloud engines
must only ever be reachable through an explicit VIBE_TRADING_OCR_ENGINE
choice — never via "auto" fallback.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.config.accessor import reset_env_config
from src.tools.ocr import engine as ocr_engine


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the cached EnvConfig and plugin cache around each test."""
    reset_env_config()
    ocr_engine._reset_plugin_cache()
    yield
    reset_env_config()
    ocr_engine._reset_plugin_cache()


# ---------------------------------------------------------------------------
# Engine selection and privacy
# ---------------------------------------------------------------------------


class TestEngineSelection:
    """Test get_ocr_engine() selection logic and privacy guarantees."""

    def test_none_disables_ocr(self, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "none")
        reset_env_config()
        assert ocr_engine.get_ocr_engine() is None

    def test_auto_never_selects_cloud_engine(self, monkeypatch):
        """auto must not select any engine with is_cloud=True."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "auto")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        reset_env_config()

        engine = ocr_engine.get_ocr_engine()
        if engine is not None:
            assert engine.is_cloud is False, f"auto mode selected cloud engine '{engine.name}'"

    def test_unknown_choice_falls_back_to_local(self, monkeypatch):
        """An unknown engine name degrades to auto, which stays local."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "bogus-engine")
        reset_env_config()

        engine = ocr_engine.get_ocr_engine()
        if engine is not None:
            assert engine.is_cloud is False

    def test_llm_vision_explicit_not_auto_selected(self, monkeypatch):
        """llm-vision is available via explicit choice but not via auto."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "auto")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        reset_env_config()

        # auto should NOT return the cloud llm-vision engine
        engine = ocr_engine.get_ocr_engine()
        if engine is not None:
            assert engine.name != "llm-vision"

    def test_llm_vision_available_with_api_key(self, monkeypatch):
        """llm-vision is_available returns True when API key is set.

        Vision capability is NOT gated — the call is attempted regardless
        and a failed API call gives clearer feedback than silent refusal.
        """
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        reset_env_config()

        engine = ocr_engine.get_ocr_engine()
        assert engine is not None
        assert engine.name == "llm-vision"
        assert engine.is_cloud is True

    def test_llm_vision_unavailable_without_api_key(self, monkeypatch):
        """llm-vision is_available returns False when no API key is set.

        When the cloud engine is unavailable, get_ocr_engine falls back
        to auto (local engines). The returned engine must NOT be llm-vision.
        """
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        reset_env_config()

        engine = ocr_engine.get_ocr_engine()
        # Either no engine (no local OCR installed) or a local engine
        if engine is not None:
            assert engine.name != "llm-vision"
            assert engine.is_cloud is False

    def test_llm_vision_available_even_for_unknown_model(self, monkeypatch):
        """llm-vision is available even if model name is unknown.

        The vision model check is advisory (warning only), not a gate.
        A text-only model name should still let the engine be available
        — the API call will fail with a clear error if the model truly
        lacks vision support.
        """
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "deepseek")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "deepseek-chat")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        reset_env_config()

        engine = ocr_engine.get_ocr_engine()
        assert engine is not None
        assert engine.name == "llm-vision"


# ---------------------------------------------------------------------------
# Deprecated aliases
# ---------------------------------------------------------------------------


class TestRegistry:
    """Test the built-in registry and plugin discovery."""

    def test_builtin_engines_registered(self):
        """rapid and llm-vision should be in the built-in registry."""
        engines = ocr_engine._all_engines()
        assert "rapid" in engines
        assert "llm-vision" in engines

    def test_rapid_engine_is_local(self):
        """rapid engine should have is_cloud=False."""
        engines = ocr_engine._all_engines()
        rapid_cls = engines["rapid"]
        engine = rapid_cls()
        assert engine.is_cloud is False
        assert engine.name == "rapid"

    def test_llm_vision_engine_is_cloud(self):
        """llm-vision engine should have is_cloud=True."""
        engines = ocr_engine._all_engines()
        llm_cls = engines["llm-vision"]
        engine = llm_cls()
        assert engine.is_cloud is True
        assert engine.name == "llm-vision"

    def test_reset_plugin_cache_clears_cache(self):
        """_reset_plugin_cache should clear the lru_cache."""
        # Call _discover_plugins to populate cache
        ocr_engine._discover_plugins()
        cache_info = ocr_engine._discover_plugins.cache_info()
        assert cache_info.currsize >= 0

        # Reset should clear
        ocr_engine._reset_plugin_cache()
        cache_info = ocr_engine._discover_plugins.cache_info()
        assert cache_info.currsize == 0

    def test_plugin_overrides_builtin(self, monkeypatch):
        """A plugin with the same name as a builtin should override it."""

        class FakePluginEngine:
            name = "rapid"
            is_cloud = False
            install_hint = "fake plugin"

            def is_available(self):
                return True

            def recognize(self, image):
                return "fake"

        # Mock _discover_plugins to return our fake plugin
        monkeypatch.setattr(
            ocr_engine,
            "_discover_plugins",
            lambda: {"rapid": FakePluginEngine},
        )

        engines = ocr_engine._all_engines()
        rapid_cls = engines["rapid"]
        engine = rapid_cls()
        assert engine.install_hint == "fake plugin"


# ---------------------------------------------------------------------------
# Install hints
# ---------------------------------------------------------------------------


class TestInstallHints:
    """Test get_ocr_install_hint() dynamic generation."""

    def test_hint_empty_when_engine_available(self):
        """No hint needed when an engine object is passed (working)."""
        hint = ocr_engine.get_ocr_install_hint(object())
        assert hint == ""

    def test_hint_generated_when_engine_none(self, monkeypatch):
        """Hint should be generated when engine is None and OCR is needed."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "auto")
        reset_env_config()
        engine = ocr_engine.get_ocr_engine()
        hint = ocr_engine.get_ocr_install_hint(engine)
        if engine is None:
            assert "pip install" in hint
            assert "rapidocr_onnxruntime" in hint

    def test_hint_does_not_reference_deleted_plugin(self, monkeypatch):
        """Install hint must not reference the removed vibe-ocr-llm package."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "auto")
        reset_env_config()
        engine = ocr_engine.get_ocr_engine()
        hint = ocr_engine.get_ocr_install_hint(engine)
        assert "vibe-ocr-llm" not in hint


# ---------------------------------------------------------------------------
# Provider config resolution
# ---------------------------------------------------------------------------


class TestProviderConfigResolution:
    """Test _resolve_provider_config() fallback paths."""

    def test_normal_path_with_provider_env(self, monkeypatch):
        """When provider-specific env vars are set, they take priority."""
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "deepseek")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "deepseek-vl2")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["provider"] == "deepseek"
        assert config["api_key"] == "sk-test-123"
        assert config["model"] == "deepseek-vl2"

    def test_fallback_to_openai_api_key(self, monkeypatch):
        """When provider env is unset, fall back to OPENAI_API_KEY."""
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "unknown-provider")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_API_BASE", raising=False)
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["api_key"] == "sk-openai-test"

    def test_ollama_fallback_when_no_key(self, monkeypatch):
        """When no API key is set at all, fall back to 'ollama'."""
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "ollama")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "llava-1.5-7b")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["api_key"] == "ollama"

    def test_model_override_priority(self, monkeypatch):
        """VIBE_TRADING_OCR_LLM_MODEL overrides LANGCHAIN_MODEL_NAME."""
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o-mini")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("VIBE_TRADING_OCR_LLM_MODEL", "gpt-4o")
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["model"] == "gpt-4o"

    def test_base_url_fallback_chain(self, monkeypatch):
        """base_url should fall back through provider env → OPENAI_BASE_URL → OPENAI_API_BASE."""
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "ollama")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "llava-1.5-7b")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["base_url"] == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# recognize() should never emit advisory warnings
# ---------------------------------------------------------------------------


class TestRecognizeNoAdvisory:
    """Explicit engine choice (llm-vision) is the strongest multimodality
    signal — recognize() must not second-guess the user by emitting
    heuristic 'may not support vision' warnings.  If the model truly
    lacks vision support, the provider-side API call fails with a clear
    error — better UX than heuristic warnings.
    """

    def test_no_warning_with_text_only_model_name(self, monkeypatch, caplog):
        """deepseek-chat is a text-only model name, but explicit llm-vision
        engine choice should suppress any advisory warning — the user has
        already committed to that engine.
        """
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "deepseek")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "deepseek-chat")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import LlmVisionOcrEngine

        engine = LlmVisionOcrEngine()
        monkeypatch.setattr(
            engine,
            "_get_client",
            lambda config: _FakeNoOpClient(),
        )

        with caplog.at_level("WARNING", logger="src.tools.ocr.llm_vision_ocr"):
            engine.recognize(np.zeros((10, 10, 3), dtype=np.uint8))

        assert not any("may not support vision" in rec.message for rec in caplog.records)


class _FakeNoOpClient:
    """Stub: chat.completions.create returns an empty message for recognize()."""

    def __init__(self):
        class _Chat:
            class _Completions:
                def create(self, **kwargs):
                    return type(
                        "Resp",
                        (),
                        {
                            "choices": [
                                type(
                                    "Ch",
                                    (),
                                    {
                                        "message": type("Msg", (), {"content": ""}),
                                    },
                                )
                            ],
                        },
                    )()

            completions = _Completions()

        self.chat = _Chat()


# ---------------------------------------------------------------------------
# Backward compatibility aliases (Issue #547)
# ---------------------------------------------------------------------------


class TestBackwardCompatAliases:
    """Backward compatibility for deprecated engine names and env vars."""

    def test_qwen_vl_alias_maps_to_llm_vision(self, monkeypatch, caplog):
        """VIBE_TRADING_OCR_ENGINE=qwen-vl should alias to llm-vision with a deprecation warning."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "qwen-vl")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        reset_env_config()

        with caplog.at_level("WARNING", logger="src.tools.ocr.engine"):
            engine = ocr_engine.get_ocr_engine()

        # Should be aliased to llm-vision (cloud engine)
        assert engine is not None
        assert engine.name == "llm-vision"

        # Should emit deprecation warning
        assert any("deprecated" in rec.message and "qwen-vl" in rec.message for rec in caplog.records)

    def test_qwen_vl_alias_not_in_engines_dict(self):
        """Confirm 'qwen-vl' is not a registered engine name (only an alias)."""
        engines = ocr_engine._all_engines()
        assert "qwen-vl" not in engines
        assert "llm-vision" in engines

    def test_legacy_env_var_alias(self, monkeypatch, caplog):
        """VIBE_TRADING_OCR_QWEN_MODEL should alias to VIBE_TRADING_OCR_LLM_MODEL with deprecation warning."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # Legacy env var
        monkeypatch.setenv("VIBE_TRADING_OCR_QWEN_MODEL", "qwen-vl-plus-legacy")
        # New env var NOT set
        monkeypatch.delenv("VIBE_TRADING_OCR_LLM_MODEL", raising=False)
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        with caplog.at_level("WARNING"):
            config = _resolve_provider_config()

        # Should pick up the legacy env var as the model override
        assert config["model"] == "qwen-vl-plus-legacy"

    def test_new_env_var_takes_precedence_over_legacy(self, monkeypatch):
        """When both old and new env vars are set, the new one wins without warning."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("VIBE_TRADING_OCR_QWEN_MODEL", "qwen-old")
        monkeypatch.setenv("VIBE_TRADING_OCR_LLM_MODEL", "gpt-4o-new")
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["model"] == "gpt-4o-new"

    def test_unknown_provider_no_ollama_fallback(self, monkeypatch):
        """Unknown provider without API key should NOT fall back to 'ollama' literal."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "unknown-provider-xyz")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "some-model")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        # Should be empty string, NOT "ollama"
        assert config["api_key"] != "ollama"
        # is_available() should return False because empty api_key
        from src.tools.ocr.llm_vision_ocr import LlmVisionOcrEngine

        engine = LlmVisionOcrEngine()
        assert engine.is_available() is False

    def test_ollama_provider_keeps_placeholder_key(self, monkeypatch):
        """Ollama provider should still use 'ollama' placeholder when no OPENAI_API_KEY set."""
        monkeypatch.setenv("VIBE_TRADING_OCR_ENGINE", "llm-vision")
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "ollama")
        monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "llava-1.5-7b")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        reset_env_config()

        from src.tools.ocr.llm_vision_ocr import _resolve_provider_config

        config = _resolve_provider_config()
        assert config["api_key"] == "ollama"
