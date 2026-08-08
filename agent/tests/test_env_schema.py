"""Comprehensive tests for EnvConfig schema and accessor singleton.

Covers:
- Default values for every sub-model
- Type coercion (int, float, bool)
- Validation errors on bad input
- Environment variable override
- API key alias resolution
- Singleton caching and reset
- Thread safety
- _parse_bool utility
- get_env_or utility
- get_env_value utility
- _parse_env_bool (EnvBool BeforeValidator)
"""

from __future__ import annotations

import concurrent.futures

import pytest

from src.config.accessor import (
    _parse_bool,
    get_env_config,
    get_env_or,
    get_env_value,
    reset_env_config,
)
from src.config.env_schema import (
    APIConfig,
    AgentTuningConfig,
    DataConfig,
    EnvConfig,
    LLMConfig,
    PathConfig,
    SwarmConfig,
    _parse_env_bool,
)


# ---------------------------------------------------------------------------
# Fixture: reset singleton + clean env before each test
# ---------------------------------------------------------------------------

# All env-var aliases used by EnvConfig sub-models.
_ALL_ALIASES: list[str] = []
for _model in (LLMConfig, DataConfig, APIConfig, SwarmConfig, AgentTuningConfig, PathConfig):
    for _info in _model.model_fields.values():
        if _info.alias:
            _ALL_ALIASES.append(_info.alias)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all EnvConfig-related env vars and reset the singleton."""
    for alias in _ALL_ALIASES:
        monkeypatch.delenv(alias, raising=False)
    reset_env_config()
    yield  # type: ignore[misc]
    reset_env_config()


# ===================================================================
# TestEnvConfigDefaults — every sub-model's defaults
# ===================================================================


class TestEnvConfigDefaults:
    """Verify every field defaults correctly when no env vars are set."""

    def test_llm_defaults(self) -> None:
        c = EnvConfig()
        assert c.llm.langchain_provider == "openai"
        assert c.llm.langchain_model_name == ""
        assert c.llm.langchain_temperature == 0.0
        assert c.llm.timeout_seconds == 120
        assert c.llm.max_retries == 2
        assert c.llm.langchain_reasoning_effort == ""
        assert c.llm.vibe_trading_deepseek_adapter == "auto"
        assert c.llm.moonshot_user_agent == ""
        assert c.llm.openai_codex_base_url == "https://chatgpt.com/backend-api/codex/responses"

    def test_data_defaults(self) -> None:
        c = EnvConfig()
        assert c.data.tushare_token == ""
        assert c.data.ccxt_exchange == "binance"
        assert c.data.ccxt_timeout_ms == 15000
        assert c.data.ccxt_fetch_budget_s == 60.0
        assert c.data.futu_host == "127.0.0.1"
        assert c.data.futu_port == 11111
        assert c.data.finnhub_api_key == ""
        assert c.data.alphavantage_api_key == ""
        assert c.data.tiingo_api_key == ""
        assert c.data.fmp_api_key == ""
        assert c.data.fred_api_key == ""
        assert c.data.vibe_trading_iwencai_key == ""
        assert c.data.vibe_trading_sec_ua == ""
        assert c.data.vibe_trading_data_cache is False
        assert c.data.vibe_trading_data_cache_root == ""
        assert c.data.aliyun_iqs_api_key == ""
        assert c.data.longbridge_app_key == ""
        assert c.data.longbridge_app_secret == ""
        assert c.data.longbridge_access_token == ""

    def test_api_defaults(self) -> None:
        c = EnvConfig()
        assert c.api.api_auth_key == ""
        assert c.api.vibe_trading_api_key == ""
        assert c.api.cors_origins == ""
        assert c.api.api_allowed_hosts == ""
        assert c.api.enable_session_runtime is True
        assert c.api.vibe_trading_trust_docker_loopback is False
        assert c.api.vibe_trading_enable_shell_tools is False
        assert c.api.vibe_trading_allowed_file_roots == ""
        assert c.api.vibe_trading_allowed_write_roots == ""
        assert c.api.vibe_trading_allowed_run_roots == ""

    def test_swarm_defaults(self) -> None:
        c = EnvConfig()
        assert c.swarm.swarm_worker_timeout == 300
        assert c.swarm.swarm_worker_max_iter == 50
        assert c.swarm.swarm_max_workers == 4
        assert c.swarm.swarm_timeout == 1800
        assert c.swarm.swarm_heartbeat_interval_s == 3.0
        assert c.swarm.swarm_stream_retry_delay_s == 1.0
        assert c.swarm.swarm_grounding_max_symbols == 8

    def test_agent_tuning_defaults(self) -> None:
        c = EnvConfig()
        assert c.agent_tuning.token_threshold == 40000
        assert c.agent_tuning.vt_heartbeat_interval_s == 3.0
        assert c.agent_tuning.vt_reasoning_delta_min_interval_s == 1.0
        assert c.agent_tuning.vt_stream_retry_delay_s == 1.0
        assert c.agent_tuning.vibe_trading_tool_timeout_seconds == 1800.0
        assert c.agent_tuning.vibe_trading_goal_max_continuations == 3
        assert c.agent_tuning.vibe_trading_sse_timeout == 90
        assert c.agent_tuning.content_filter_warning_threshold == 0.05
        assert c.agent_tuning.vibe_trading_enable_advisory is False
        assert c.agent_tuning.vibe_trading_enable_scheduler is False
        assert c.agent_tuning.vibe_trading_scheduler_max_consecutive_failures == 3
        assert c.agent_tuning.vibe_trading_scheduler_retry_base_delay_ms == 60_000
        assert c.agent_tuning.vibe_trading_scheduler_retry_max_delay_ms == 3_600_000
        assert c.agent_tuning.vibe_trading_channels_auto_start is False
        assert c.agent_tuning.vibe_trading_disable_bottleneck is False
        assert c.agent_tuning.vibe_trading_bench_workers == 0
        assert c.agent_tuning.vibe_trading_search_backends == ""
        assert c.agent_tuning.vibe_trading_search_bing_fallback is True

    def test_path_defaults(self) -> None:
        c = EnvConfig()
        assert c.paths.vibe_trading_hypotheses_path == ""
        assert c.paths.vibe_trading_goal_db_path == ""
        assert c.paths.vibe_trading_swarm_agent_config == ""
        assert c.paths.allow_session_mcp_servers is False


# ===================================================================
# TestEnvConfigTypeCoercion
# ===================================================================


class TestEnvConfigTypeCoercion:
    """Verify env-var strings are coerced to the correct Python types."""

    def test_int_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TIMEOUT_SECONDS", "300")
        c = EnvConfig()
        assert c.llm.timeout_seconds == 300
        assert isinstance(c.llm.timeout_seconds, int)

    def test_float_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGCHAIN_TEMPERATURE", "0.5")
        c = EnvConfig()
        assert c.llm.langchain_temperature == 0.5
        assert isinstance(c.llm.langchain_temperature, float)

    def test_invalid_int_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TIMEOUT_SECONDS", "not_a_number")
        c = EnvConfig()
        assert c.llm.timeout_seconds == 120

    def test_invalid_token_threshold_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TOKEN_THRESHOLD", "abc")
        c = EnvConfig()
        assert c.agent_tuning.token_threshold == 40000

    def test_bool_coercion_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "true")
        c = EnvConfig()
        assert c.data.vibe_trading_data_cache is True

    def test_bool_false_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_SESSION_RUNTIME", "false")
        c = EnvConfig()
        assert c.api.enable_session_runtime is False

    def test_float_swarm_heartbeat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SWARM_HEARTBEAT_INTERVAL_S", "5.5")
        c = EnvConfig()
        assert c.swarm.swarm_heartbeat_interval_s == 5.5

    def test_scheduler_retry_int_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_SCHEDULER_MAX_CONSECUTIVE_FAILURES", "5")
        monkeypatch.setenv("VIBE_TRADING_SCHEDULER_RETRY_BASE_DELAY_MS", "2500")
        monkeypatch.setenv("VIBE_TRADING_SCHEDULER_RETRY_MAX_DELAY_MS", "10000")

        tuning = EnvConfig().agent_tuning

        assert tuning.vibe_trading_scheduler_max_consecutive_failures == 5
        assert tuning.vibe_trading_scheduler_retry_base_delay_ms == 2500
        assert tuning.vibe_trading_scheduler_retry_max_delay_ms == 10000


# ===================================================================
# TestEnvConfigOverride
# ===================================================================


class TestEnvConfigOverride:
    """Verify env vars override defaults and reset restores them."""

    def test_longbridge_credentials_read_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LONGBRIDGE_APP_KEY", "app-key")
        monkeypatch.setenv("LONGBRIDGE_APP_SECRET", "app-secret")
        monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", "access-token")

        data = EnvConfig().data

        assert data.longbridge_app_key == "app-key"
        assert data.longbridge_app_secret == "app-secret"
        assert data.longbridge_access_token == "access-token"

    def test_env_override_and_reset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGCHAIN_PROVIDER", "deepseek")
        monkeypatch.setenv("TIMEOUT_SECONDS", "60")
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token_123")

        c = EnvConfig()
        assert c.llm.langchain_provider == "deepseek"
        assert c.llm.timeout_seconds == 60
        assert c.data.tushare_token == "test_token_123"

        # Remove env vars and create a new config → defaults restored.
        monkeypatch.delenv("LANGCHAIN_PROVIDER")
        monkeypatch.delenv("TIMEOUT_SECONDS")
        monkeypatch.delenv("TUSHARE_TOKEN")

        c2 = EnvConfig()
        assert c2.llm.langchain_provider == "openai"
        assert c2.llm.timeout_seconds == 120
        assert c2.data.tushare_token == ""

    def test_multiple_overrides_simultaneously(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARM_MAX_WORKERS", "8")
        monkeypatch.setenv("CCXT_EXCHANGE", "okx")
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")

        c = EnvConfig()
        assert c.swarm.swarm_max_workers == 8
        assert c.data.ccxt_exchange == "okx"
        assert c.api.cors_origins == "http://localhost:3000"


# ===================================================================
# TestAPIKeyAlias
# ===================================================================


class TestAPIKeyAlias:
    """Verify VIBE_TRADING_API_KEY → api_auth_key alias resolution."""

    def test_vibe_trading_api_key_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_API_KEY", "secret")
        c = EnvConfig()
        assert c.api.api_auth_key == "secret"
        assert c.api.vibe_trading_api_key == "secret"

    def test_both_keys_explicit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_TRADING_API_KEY", "secret")
        monkeypatch.setenv("API_AUTH_KEY", "other")
        c = EnvConfig()
        assert c.api.api_auth_key == "other"

    def test_api_auth_key_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_KEY", "other")
        c = EnvConfig()
        assert c.api.api_auth_key == "other"

    def test_neither_key_set(self) -> None:
        c = EnvConfig()
        assert c.api.api_auth_key == ""
        assert c.api.vibe_trading_api_key == ""


# ===================================================================
# TestSingletonBehavior
# ===================================================================


class TestSingletonBehavior:
    """Verify get_env_config / reset_env_config singleton semantics."""

    def test_cached_instance(self) -> None:
        c1 = get_env_config()
        c2 = get_env_config()
        assert c1 is c2

    def test_reset_creates_new_instance(self) -> None:
        c1 = get_env_config()
        reset_env_config()
        c3 = get_env_config()
        assert c3 is not c1

    def test_reset_picks_up_new_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c1 = get_env_config()
        assert c1.llm.timeout_seconds == 120

        monkeypatch.setenv("TIMEOUT_SECONDS", "999")
        reset_env_config()

        c2 = get_env_config()
        assert c2.llm.timeout_seconds == 999
        assert c2 is not c1


# ===================================================================
# TestThreadSafety
# ===================================================================


class TestThreadSafety:
    """Verify concurrent access to get_env_config is safe."""

    def test_concurrent_access_returns_same_instance(self) -> None:
        results: list[EnvConfig] = []

        def _fetch() -> None:
            results.append(get_env_config())

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_fetch) for _ in range(10)]
            concurrent.futures.wait(futures)

        # All threads got an instance (no exception).
        assert len(results) == 10
        # All are the same object (singleton).
        assert all(r is results[0] for r in results)

    def test_concurrent_reset_and_read(self) -> None:
        """Interleaved reset + read must not raise."""
        errors: list[Exception] = []

        def _worker(i: int) -> None:
            try:
                if i % 3 == 0:
                    reset_env_config()
                else:
                    get_env_config()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_worker, i) for i in range(30)]
            concurrent.futures.wait(futures)

        assert errors == []


# ===================================================================
# TestParseBool — accessor._parse_bool
# ===================================================================


class TestParseBool:
    """Verify the unified boolean parser from accessor.py."""

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"],
    )
    def test_truthy(self, value: str) -> None:
        assert _parse_bool(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "0", "false", "False", "FALSE",
            "no", "No", "NO",
            "off", "Off", "OFF",
            "", "random", "2", "maybe",
        ],
    )
    def test_falsy(self, value: str) -> None:
        assert _parse_bool(value) is False

    def test_none_returns_false(self) -> None:
        assert _parse_bool(None) is False


# ===================================================================
# TestParseEnvBool — env_schema._parse_env_bool
# ===================================================================


class TestParseEnvBool:
    """Verify the Pydantic BeforeValidator for EnvBool fields."""

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"],
    )
    def test_truthy_strings(self, value: str) -> None:
        assert _parse_env_bool(value) is True

    @pytest.mark.parametrize(
        "value",
        ["0", "false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF", ""],
    )
    def test_falsy_strings(self, value: str) -> None:
        assert _parse_env_bool(value) is False

    def test_non_string_passthrough(self) -> None:
        """Non-string values pass through for Pydantic's built-in coercion."""
        assert _parse_env_bool(True) is True
        assert _parse_env_bool(False) is False
        assert _parse_env_bool(1) == 1
        assert _parse_env_bool(None) is None

    def test_unrecognized_string_passthrough(self) -> None:
        """Unrecognized strings pass through (Pydantic will reject them)."""
        result = _parse_env_bool("random")
        assert result == "random"


# ===================================================================
# TestGetEnvOr
# ===================================================================


class TestGetEnvOr:
    """Verify the env-var fallback helper."""

    def test_primary_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRIMARY", "primary_val")
        monkeypatch.setenv("FALLBACK", "fallback_val")
        assert get_env_or("PRIMARY", "FALLBACK", "default") == "primary_val"

    def test_fallback_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRIMARY", raising=False)
        monkeypatch.setenv("FALLBACK", "fallback_val")
        assert get_env_or("PRIMARY", "FALLBACK", "default") == "fallback_val"

    def test_neither_set_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRIMARY", raising=False)
        monkeypatch.delenv("FALLBACK", raising=False)
        assert get_env_or("PRIMARY", "FALLBACK", "default") == "default"

    def test_empty_primary_falls_to_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRIMARY", "")
        monkeypatch.setenv("FALLBACK", "fb")
        assert get_env_or("PRIMARY", "FALLBACK", "default") == "fb"

    def test_empty_both_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRIMARY", "")
        monkeypatch.setenv("FALLBACK", "")
        assert get_env_or("PRIMARY", "FALLBACK", "default") == "default"


class TestGetEnvValue:
    """Verify dynamic registry keys still go through the config layer."""

    def test_reads_configured_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DYNAMIC_PROVIDER_API_KEY", "secret")
        assert get_env_value("DYNAMIC_PROVIDER_API_KEY") == "secret"

    def test_returns_default_for_missing_value(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DYNAMIC_PROVIDER_API_KEY", raising=False)
        assert get_env_value("DYNAMIC_PROVIDER_API_KEY", "fallback") == "fallback"


# ===================================================================
# TestSubModelDirectConstruction
# ===================================================================


class TestSubModelDirectConstruction:
    """Verify sub-models can be constructed directly with kwargs."""

    def test_llm_config_direct(self) -> None:
        cfg = LLMConfig(langchain_provider="anthropic", timeout_seconds=60)
        assert cfg.langchain_provider == "anthropic"
        assert cfg.timeout_seconds == 60

    def test_data_config_direct(self) -> None:
        cfg = DataConfig(tushare_token="my_token", ccxt_exchange="okx")
        assert cfg.tushare_token == "my_token"
        assert cfg.ccxt_exchange == "okx"

    def test_swarm_config_direct(self) -> None:
        cfg = SwarmConfig(swarm_max_workers=16)
        assert cfg.swarm_max_workers == 16

    def test_extra_fields_ignored(self) -> None:
        cfg = LLMConfig(unknown_field="ignored")
        assert not hasattr(cfg, "unknown_field")
