"""Single source of truth for all Vibe-Trading environment variable defaults.

This module defines Pydantic models for every environment variable consumed by
the Vibe-Trading agent, grouped by functional category.  Each field carries the
correct type, default value, and env-var alias so that ``EnvConfig()`` with no
arguments reads from ``os.environ`` and applies the documented defaults.

The schema replaces the ~207 scattered ``os.getenv`` calls across 66 files with
a validated, typed, centrally-managed configuration layer.

Usage::

    from src.config.env_schema import EnvConfig

    cfg = EnvConfig()          # reads os.environ, applies defaults
    cfg.llm.timeout_seconds    # 120
    cfg.data.tushare_token     # ""
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

__all__ = [
    "EnvConfig",
    "LLMConfig",
    "DataConfig",
    "APIConfig",
    "SwarmConfig",
    "AgentTuningConfig",
    "PathConfig",
    "OcrConfig",
]


# ---------------------------------------------------------------------------
# Boolean coercion helper
# ---------------------------------------------------------------------------


def _parse_env_bool(v: Any) -> Any:
    """Coerce environment string values to ``bool``.

    Accepts ``"1"``, ``"true"``, ``"yes"``, ``"on"`` (case-insensitive) as
    ``True`` and ``"0"``, ``"false"``, ``"no"``, ``"off"``, ``""`` as ``False``.
    Non-string values pass through for Pydantic's built-in coercion.
    """
    if isinstance(v, str):
        low = v.strip().lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off", ""}:
            return False
    return v


EnvBool = Annotated[bool, BeforeValidator(_parse_env_bool)]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class _EnvBase(BaseModel):
    """Base for environment-variable-backed config sub-models.

    Each sub-model reads missing fields from ``os.environ`` using the field
    alias (the UPPER_SNAKE_CASE env-var name).  Explicit constructor arguments
    always take precedence over environment values.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _load_from_env(cls, data: Any) -> Any:
        """Populate missing fields from ``os.environ`` using field aliases.

        Invalid numeric env values are silently dropped so Pydantic applies
        the field default instead of raising a ``ValidationError``.
        """
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for field_name, field_info in cls.model_fields.items():
            alias = field_info.alias
            # Skip fields already provided (by Python name or alias).
            if field_name in result or (alias and alias in result):
                continue
            # Read from environment using the UPPER_SNAKE_CASE alias.
            if alias and alias in os.environ:
                env_val = os.environ[alias]
                # Safe coercion for numeric fields: drop unparseable values
                # so Pydantic falls back to the field default.
                annotation = field_info.annotation
                if annotation is int and isinstance(env_val, str):
                    try:
                        env_val = int(env_val)
                    except ValueError:
                        continue
                elif annotation is float and isinstance(env_val, str):
                    try:
                        env_val = float(env_val)
                    except ValueError:
                        continue
                result[alias] = env_val
        return result


# ---------------------------------------------------------------------------
# LLM Provider
# ---------------------------------------------------------------------------


class LLMConfig(_EnvBase):
    """LLM provider and generation parameters.

    Sources: ``src/providers/llm.py``, ``src/providers/chat.py``,
    ``src/providers/openai_codex.py``, ``src/preflight.py``.
    """

    langchain_provider: str = Field(alias="LANGCHAIN_PROVIDER", default="openai")
    langchain_model_name: str = Field(alias="LANGCHAIN_MODEL_NAME", default="")
    langchain_temperature: float = Field(alias="LANGCHAIN_TEMPERATURE", default=0.0)
    timeout_seconds: int = Field(alias="TIMEOUT_SECONDS", default=120)
    max_retries: int = Field(alias="MAX_RETRIES", default=2)
    langchain_reasoning_effort: str = Field(alias="LANGCHAIN_REASONING_EFFORT", default="")
    vibe_trading_deepseek_adapter: str = Field(alias="VIBE_TRADING_DEEPSEEK_ADAPTER", default="auto")
    moonshot_user_agent: str = Field(alias="MOONSHOT_USER_AGENT", default="")
    openai_codex_base_url: str = Field(
        alias="OPENAI_CODEX_BASE_URL",
        default="https://chatgpt.com/backend-api/codex/responses",
    )
    openai_model: str = Field(alias="OPENAI_MODEL", default="")


# ---------------------------------------------------------------------------
# Data Sources
# ---------------------------------------------------------------------------


class DataConfig(_EnvBase):
    """Market-data source credentials and tuning.

    Sources: ``backtest/loaders/*.py``, ``src/tools/web_search_tool.py``,
    ``src/tools/iwencai_tool.py``, ``src/tools/fred_macro_tool.py``.
    """

    tushare_token: str = Field(alias="TUSHARE_TOKEN", default="")
    ccxt_exchange: str = Field(alias="CCXT_EXCHANGE", default="binance")
    ccxt_timeout_ms: int = Field(alias="CCXT_TIMEOUT_MS", default=15000)
    ccxt_fetch_budget_s: float = Field(alias="CCXT_FETCH_BUDGET_S", default=60.0)
    futu_host: str = Field(alias="FUTU_HOST", default="127.0.0.1")
    futu_port: int = Field(alias="FUTU_PORT", default=11111)
    finnhub_api_key: str = Field(alias="FINNHUB_API_KEY", default="")
    alphavantage_api_key: str = Field(alias="ALPHAVANTAGE_API_KEY", default="")
    tiingo_api_key: str = Field(alias="TIINGO_API_KEY", default="")
    fmp_api_key: str = Field(alias="FMP_API_KEY", default="")
    fred_api_key: str = Field(alias="FRED_API_KEY", default="")
    vibe_trading_iwencai_key: str = Field(alias="VIBE_TRADING_IWENCAI_KEY", default="")
    vibe_trading_sec_ua: str = Field(alias="VIBE_TRADING_SEC_UA", default="")
    vibe_trading_data_cache: EnvBool = Field(alias="VIBE_TRADING_DATA_CACHE", default=False)
    vibe_trading_data_cache_root: str = Field(alias="VIBE_TRADING_DATA_CACHE_ROOT", default="")
    aliyun_iqs_api_key: str = Field(alias="ALIYUN_IQS_API_KEY", default="")
    qveris_api_key: str = Field(alias="QVERIS_API_KEY", default="")
    qveris_base_url: str = Field(alias="QVERIS_BASE_URL", default="")
    rsshub_base_url: str = Field(alias="RSSHUB_BASE_URL", default="")
    dashscope_api_key: str = Field(alias="DASHSCOPE_API_KEY", default="")
    longbridge_app_key: str = Field(alias="LONGBRIDGE_APP_KEY", default="")
    longbridge_app_secret: str = Field(alias="LONGBRIDGE_APP_SECRET", default="")
    longbridge_access_token: str = Field(alias="LONGBRIDGE_ACCESS_TOKEN", default="")


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


class OcrConfig(_EnvBase):
    """OCR engine selection and model configuration.

    Sources: ``src/tools/ocr/engine.py``, ``src/tools/ocr/qwen_vision_ocr.py``.
    """

    vibe_trading_ocr_engine: str = Field(alias="VIBE_TRADING_OCR_ENGINE", default="auto")
    vibe_trading_ocr_qwen_model: str = Field(alias="VIBE_TRADING_OCR_QWEN_MODEL", default="")


# ---------------------------------------------------------------------------
# API Server
# ---------------------------------------------------------------------------


class APIConfig(_EnvBase):
    """API server authentication, CORS, and security toggles.

    Sources: ``src/api/security.py``, ``src/api/state.py``,
    ``mcp_server.py``, ``src/tools/path_utils.py``.
    """

    api_auth_key: str = Field(alias="API_AUTH_KEY", default="")
    vibe_trading_api_key: str = Field(alias="VIBE_TRADING_API_KEY", default="")
    cors_origins: str = Field(alias="CORS_ORIGINS", default="")
    api_allowed_hosts: str = Field(alias="API_ALLOWED_HOSTS", default="")
    enable_session_runtime: EnvBool = Field(alias="ENABLE_SESSION_RUNTIME", default=True)
    vibe_trading_trust_docker_loopback: EnvBool = Field(
        alias="VIBE_TRADING_TRUST_DOCKER_LOOPBACK", default=False,
    )
    vibe_trading_enable_shell_tools: EnvBool = Field(
        alias="VIBE_TRADING_ENABLE_SHELL_TOOLS", default=False,
    )
    vibe_trading_allowed_file_roots: str = Field(
        alias="VIBE_TRADING_ALLOWED_FILE_ROOTS", default="",
    )
    vibe_trading_allowed_write_roots: str = Field(
        alias="VIBE_TRADING_ALLOWED_WRITE_ROOTS", default="",
    )
    vibe_trading_allowed_run_roots: str = Field(
        alias="VIBE_TRADING_ALLOWED_RUN_ROOTS", default="",
    )
    vibe_trading_api_url: str = Field(
        alias="VIBE_TRADING_API_URL", default="http://127.0.0.1:8000",
    )
    futu_trade_pwd_md5: str = Field(alias="FUTU_TRADE_PWD_MD5", default="")


# ---------------------------------------------------------------------------
# Swarm
# ---------------------------------------------------------------------------


class SwarmConfig(_EnvBase):
    """Multi-agent swarm execution parameters.

    Sources: ``src/swarm/worker.py``, ``src/tools/swarm_tool.py``,
    ``src/swarm/runtime.py``, ``src/swarm/grounding.py``.
    """

    swarm_worker_timeout: int = Field(alias="SWARM_WORKER_TIMEOUT", default=300)
    swarm_worker_max_iter: int = Field(alias="SWARM_WORKER_MAX_ITER", default=50)
    swarm_max_workers: int = Field(alias="SWARM_MAX_WORKERS", default=4)
    swarm_timeout: int = Field(alias="SWARM_TIMEOUT", default=1800)
    swarm_heartbeat_interval_s: float = Field(alias="SWARM_HEARTBEAT_INTERVAL_S", default=3.0)
    swarm_stream_retry_delay_s: float = Field(alias="SWARM_STREAM_RETRY_DELAY_S", default=1.0)
    swarm_grounding_max_symbols: int = Field(alias="SWARM_GROUNDING_MAX_SYMBOLS", default=8)


# ---------------------------------------------------------------------------
# Agent Tuning
# ---------------------------------------------------------------------------


class AgentTuningConfig(_EnvBase):
    """Agent loop tuning, content-filter, scheduler, and feature flags.

    Sources: ``src/agent/loop.py``, ``src/providers/content_filter.py``,
    ``src/scheduled_research/executor.py``, ``src/live/order_guard.py``,
    ``src/factors/_backend.py``, ``src/factors/bench_runner.py``,
    ``src/tools/web_search_tool.py``, ``api_server.py``.
    """

    token_threshold: int = Field(alias="TOKEN_THRESHOLD", default=40000)
    vt_heartbeat_interval_s: float = Field(alias="VT_HEARTBEAT_INTERVAL_S", default=3.0)
    vt_reasoning_delta_min_interval_s: float = Field(
        alias="VT_REASONING_DELTA_MIN_INTERVAL_S", default=1.0,
    )
    vt_stream_retry_delay_s: float = Field(alias="VT_STREAM_RETRY_DELAY_S", default=1.0)
    vibe_trading_tool_timeout_seconds: float = Field(
        alias="VIBE_TRADING_TOOL_TIMEOUT_SECONDS", default=1800.0,
    )
    vibe_trading_goal_max_continuations: int = Field(
        alias="VIBE_TRADING_GOAL_MAX_CONTINUATIONS", default=3,
    )
    vibe_trading_sse_timeout: int = Field(alias="VIBE_TRADING_SSE_TIMEOUT", default=90)
    content_filter_warning_threshold: float = Field(
        alias="CONTENT_FILTER_WARNING_THRESHOLD", default=0.05,
    )
    vibe_trading_enable_advisory: EnvBool = Field(
        alias="VIBE_TRADING_ENABLE_ADVISORY", default=False,
    )
    vibe_trading_enable_scheduler: EnvBool = Field(
        alias="VIBE_TRADING_ENABLE_SCHEDULER", default=False,
    )
    vibe_trading_channels_auto_start: EnvBool = Field(
        alias="VIBE_TRADING_CHANNELS_AUTO_START", default=False,
    )
    vibe_trading_disable_bottleneck: EnvBool = Field(
        alias="VIBE_TRADING_DISABLE_BOTTLENECK", default=False,
    )
    vibe_trading_bench_workers: int = Field(alias="VIBE_TRADING_BENCH_WORKERS", default=0)
    vibe_trading_search_backends: str = Field(alias="VIBE_TRADING_SEARCH_BACKENDS", default="")
    vibe_trading_search_bing_fallback: EnvBool = Field(
        alias="VIBE_TRADING_SEARCH_BING_FALLBACK", default=True,
    )
    vibe_live_authorize_timeout_s: int = Field(
        alias="VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS", default=300,
    )


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


class PathConfig(_EnvBase):
    """File-system path overrides and session-level MCP trust.

    Sources: ``src/hypotheses/registry.py``, ``src/goal/store.py``,
    ``src/config/loader.py``.
    """

    vibe_trading_hypotheses_path: str = Field(alias="VIBE_TRADING_HYPOTHESES_PATH", default="")
    vibe_trading_goal_db_path: str = Field(alias="VIBE_TRADING_GOAL_DB_PATH", default="")
    vibe_trading_swarm_agent_config: str = Field(
        alias="VIBE_TRADING_SWARM_AGENT_CONFIG", default="",
    )
    allow_session_mcp_servers: EnvBool = Field(alias="ALLOW_SESSION_MCP_SERVERS", default=False)
    vibe_trading_theme: str = Field(alias="VIBE_TRADING_THEME", default="")
    vibe_goal_session_id: str = Field(alias="VIBE_GOAL_SESSION_ID", default="")
    vibe_trading_strategy_store_db_path: str = Field(
        alias="VIBE_TRADING_STRATEGY_STORE_DB_PATH", default="",
    )


# ---------------------------------------------------------------------------
# Top-level composition
# ---------------------------------------------------------------------------


class EnvConfig(_EnvBase):
    """Root configuration model composing all environment variable groups.

    Instantiating with no arguments reads every recognised env var from
    ``os.environ`` and applies the documented defaults for missing values::

        cfg = EnvConfig()
        cfg.llm.timeout_seconds   # 120
        cfg.swarm.swarm_timeout   # 1800
    """

    llm: LLMConfig = Field(default_factory=LLMConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    swarm: SwarmConfig = Field(default_factory=SwarmConfig)
    agent_tuning: AgentTuningConfig = Field(default_factory=AgentTuningConfig)
    paths: PathConfig = Field(default_factory=PathConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)

    @model_validator(mode="after")
    def _resolve_api_key_alias(self) -> "EnvConfig":
        """Copy ``VIBE_TRADING_API_KEY`` to ``api_auth_key`` when only the alias is set.

        The CLI historically reads ``VIBE_TRADING_API_KEY`` first and falls back to
        ``API_AUTH_KEY`` (``cli/_legacy.py:2834``).  The API server only reads
        ``API_AUTH_KEY`` (``src/api/security.py:126``).  This validator closes
        the semantic gap so both surfaces agree.
        """
        if self.api.vibe_trading_api_key and not self.api.api_auth_key:
            self.api.api_auth_key = self.api.vibe_trading_api_key
        return self
