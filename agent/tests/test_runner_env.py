"""Regression tests for generated backtest subprocess environment handling."""

from __future__ import annotations

import os
from pathlib import Path

from src.core.runner import Runner


def test_backtest_runtime_env_keeps_market_data_configuration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    allowed_values = {
        "TUSHARE_TOKEN": "tushare-token",
        "FINNHUB_API_KEY": "finnhub-key",
        "ALPHAVANTAGE_API_KEY": "alpha-key",
        "TIINGO_API_KEY": "tiingo-key",
        "FMP_API_KEY": "fmp-key",
        "FRED_API_KEY": "fred-key",
        "VIBE_TRADING_IWENCAI_KEY": "iwencai-key",
        "VIBE_TRADING_SEC_UA": "Research Bot bot@example.com",
        "VIBE_TRADING_DATA_CACHE": "1",
        "VIBE_TRADING_ALLOWED_RUN_ROOTS": str(tmp_path),
        "VIBE_TRADING_FMP_MIN_INTERVAL": "0.5",
        "CCXT_EXCHANGE": "okx",
        "CCXT_TIMEOUT_MS": "12000",
        "OKX_TIMEOUT_S": "20",
        "OKX_FETCH_BUDGET_S": "90",
        "RSSHUB_BASE_URL": "https://rss.example.test",
        "RSSHUB_TIMEOUT_S": "12",
        "RSSHUB_FETCH_BUDGET_S": "45",
        "FUTU_HOST": "127.0.0.1",
        "FUTU_PORT": "11111",
        "HTTPS_PROXY": "http://proxy.example.test:8080",
        "REQUESTS_CA_BUNDLE": "/tmp/ca.pem",
        "LC_ALL": "C.UTF-8",
    }
    for key, value in allowed_values.items():
        monkeypatch.setenv(key, value)

    env = Runner(timeout=1)._build_runtime_env(tmp_path)

    for key, value in allowed_values.items():
        assert env[key] == value
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_backtest_runtime_env_scrubs_service_and_broker_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sensitive_keys = [
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "LANGCHAIN_PROVIDER",
        "LANGCHAIN_MODEL_NAME",
        "API_AUTH_KEY",
        "VIBE_TRADING_API_KEY",
        "VIBE_TRADING_ENABLE_SHELL_TOOLS",
        "VIBE_TRADING_ENABLE_ADVISORY",
        "INVINOVERITAS_API_KEY",
        "FUTU_TRADE_PWD_MD5",
        "BINANCE_API_SECRET",
        "ALPACA_API_KEY",
        "LONGPORT_APP_SECRET",
        "SHOONYA_PASSWORD",
    ]
    for key in sensitive_keys:
        monkeypatch.setenv(key, f"{key.lower()}-secret")

    env = Runner(timeout=1)._build_runtime_env(tmp_path)

    for key in sensitive_keys:
        assert key not in env


def test_backtest_runtime_env_prepends_runtime_pythonpath(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "existing-path")
    pythonpath_extra = tmp_path / "agent"

    env = Runner(timeout=1)._build_runtime_env(tmp_path, pythonpath_extra=pythonpath_extra)

    assert env["PYTHONPATH"] == f"{pythonpath_extra}{os.pathsep}existing-path"
