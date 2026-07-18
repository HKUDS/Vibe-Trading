"""Tests for qveris_loader: config gating, mocked HTTP fetches, and registry safety.

All QVeris calls are mocked by replacing ``requests.Session`` inside the loader
module. No test reaches the live QVeris API or a signed full-content URL.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from backtest.loaders import qveris_loader as qv
from backtest.loaders.base import NoAvailableSourceError
from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    get_loader_cls_with_fallback,
)


class _FakeResponse:
    """Small response stub for the loader's embedded HTTP client."""

    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """Queue-backed fake requests session."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        assert self.responses, f"unexpected HTTP call: {method} {url}"
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _isolated_qveris_config(monkeypatch, tmp_path):
    """Default every test to disabled QVeris with no cache or request sleep."""
    monkeypatch.setattr(qv, "_CONFIG_PATH", tmp_path / "qveris.json")
    monkeypatch.delenv("QVERIS_API_KEY", raising=False)
    monkeypatch.delenv("QVERIS_BASE_URL", raising=False)
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")
    monkeypatch.setenv("VIBE_TRADING_QVERIS_MIN_INTERVAL", "0")


def _write_config(
    path,
    *,
    enabled: bool = True,
    api_key: str = "sk_test",
    mode: str = "paid",
    budget: float = 50.0,
) -> None:
    path.write_text(
        json.dumps(
            {
                "enabled": enabled,
                "base_url": "https://qveris.test/api/v1",
                "api_key": api_key,
                "mode": mode,
                "budget_credits_per_session": budget,
            }
        ),
        encoding="utf-8",
    )


def _capability(
    tool_id: str = "tool_good",
    *,
    success_rate: float = 0.99,
    expected_cost: str = "1.0 credits",
) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "name": "Daily OHLCV candles",
        "description": "Historical open high low close volume by ticker symbol",
        "expected_cost": expected_cost,
        "stats": {"success_rate": success_rate},
        "params": [
            {"name": "symbol", "type": "string", "required": True},
            {"name": "start_date", "type": "string", "required": True},
            {"name": "end_date", "type": "string", "required": True},
            {"name": "interval", "type": "string", "enum": ["daily", "1D"]},
        ],
        "examples": {"sample_parameters": {"adjusted": True}},
    }


def _install_session(monkeypatch, responses: list[_FakeResponse]) -> _FakeSession:
    session = _FakeSession(responses)
    monkeypatch.setattr(qv.requests, "Session", lambda: session)
    return session


class TestAvailability:
    """Config and env override gating."""

    def test_missing_config_is_unavailable(self):
        assert qv.DataLoader().is_available() is False

    def test_disabled_config_stays_unavailable_even_with_env_key(self, monkeypatch):
        _write_config(qv._CONFIG_PATH, enabled=False, api_key="")
        monkeypatch.setenv("QVERIS_API_KEY", "sk_env")
        assert qv.DataLoader().is_available() is False

    def test_enabled_config_with_key_is_available(self):
        _write_config(qv._CONFIG_PATH, enabled=True, api_key="sk_file")
        assert qv.DataLoader().is_available() is True

    def test_env_key_overrides_empty_file_key(self, monkeypatch):
        _write_config(qv._CONFIG_PATH, enabled=True, api_key="")
        monkeypatch.setenv("QVERIS_API_KEY", "sk_env")
        assert qv.DataLoader().is_available() is True

    def test_metadata(self):
        assert qv.DataLoader.name == "qveris"
        assert qv.DataLoader.requires_auth is True


class TestFetch:
    """fetch() search-selects, executes, normalizes, and isolates empty symbols."""

    def test_returns_empty_without_availability_and_makes_no_http(self, monkeypatch):
        session = _install_session(monkeypatch, [])
        assert qv.DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-31") == {}
        assert session.calls == []

    def test_free_mode_keeps_qveris_loader_unavailable(self, monkeypatch):
        _write_config(qv._CONFIG_PATH, enabled=True, api_key="sk_test", mode="free")
        session = _install_session(monkeypatch, [])

        assert qv.DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-31") == {}
        assert session.calls == []

    def test_zero_budget_allows_search_but_blocks_paid_execute(self, monkeypatch):
        _write_config(qv._CONFIG_PATH, budget=0.0)
        session = _install_session(
            monkeypatch,
            [_FakeResponse({"search_id": "s_1", "results": [_capability()]})],
        )

        result = qv.DataLoader().fetch(
            ["AAPL.US"], "2024-01-01", "2024-01-31"
        )

        assert result == {}
        assert len(session.calls) == 1
        assert session.calls[0]["url"].endswith("/search")

    def test_budget_is_shared_across_symbols_in_one_fetch(self, monkeypatch):
        _write_config(qv._CONFIG_PATH, budget=1.0)
        rows = {
            "data": [
                {
                    "date": "2024-01-02",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume": 10,
                }
            ]
        }
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse({"search_id": "s_1", "results": [_capability()]}),
                _FakeResponse({"success": True, "cost": 1.0, "result": rows}),
                _FakeResponse({"search_id": "s_2", "results": [_capability()]}),
            ],
        )

        result = qv.DataLoader().fetch(
            ["AAPL.US", "MSFT.US"], "2024-01-01", "2024-01-31"
        )

        assert list(result) == ["AAPL.US"]
        execute_calls = [call for call in session.calls if "/tools/execute" in call["url"]]
        assert len(execute_calls) == 1

    def test_search_execute_happy_path_selects_best_capability(self, monkeypatch):
        _write_config(qv._CONFIG_PATH)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse(
                    {
                        "search_id": "s_123",
                        "results": [
                            _capability("expensive", success_rate=0.99, expected_cost="5 credits"),
                            _capability("cheap", success_rate=0.99, expected_cost="1 credits"),
                            _capability("weaker", success_rate=0.5, expected_cost="0.1 credits"),
                        ],
                    }
                ),
                _FakeResponse(
                    {
                        "success": True,
                        "result": {
                            "data": [
                                {
                                    "date": "2024-01-02",
                                    "open": "100",
                                    "high": "112",
                                    "low": "99",
                                    "close": "110",
                                    "volume": "1000",
                                }
                            ]
                        },
                    }
                ),
            ],
        )

        out = qv.DataLoader().fetch(["AAPL.US"], "2024-01-01", "2024-01-31")

        assert list(out) == ["AAPL.US"]
        df = out["AAPL.US"]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "trade_date"
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.dtype == "datetime64[ns]"
        assert df.loc["2024-01-02", "close"] == 110.0
        assert df.loc["2024-01-02", "volume"] == 1000.0

        assert session.calls[0]["url"] == "https://qveris.test/api/v1/search"
        assert session.calls[0]["kwargs"]["json"]["limit"] == 20
        assert session.calls[1]["url"].endswith("/tools/execute?tool_id=cheap")
        execute_body = session.calls[1]["kwargs"]["json"]
        assert execute_body["search_id"] == "s_123"
        assert execute_body["parameters"]["symbol"] == "AAPL"
        assert execute_body["parameters"]["start_date"] == "2024-01-01"
        assert execute_body["parameters"]["end_date"] == "2024-01-31"
        assert execute_body["parameters"]["adjusted"] is True

    def test_truncated_result_download_path(self, monkeypatch):
        _write_config(qv._CONFIG_PATH)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse({"search_id": "s_1", "results": [_capability()]}),
                _FakeResponse(
                    {
                        "success": True,
                        "result": {
                            "message": "too long",
                            "full_content_file_url": "https://oss.qveris.cn/full.json",
                            "truncated_content": "[]",
                        },
                    }
                ),
                _FakeResponse(
                    [
                        {
                            "date": "2024-01-02",
                            "open": 10,
                            "high": 12,
                            "low": 9,
                            "close": 11,
                        }
                    ]
                ),
            ],
        )

        out = qv.DataLoader().fetch(["MSFT"], "2024-01-01", "2024-01-31")

        assert list(out) == ["MSFT"]
        assert pd.isna(out["MSFT"].loc["2024-01-02", "volume"])
        assert session.calls[2]["method"] == "get"
        assert session.calls[2]["url"] == "https://oss.qveris.cn/full.json"
        assert "Authorization" not in session.calls[2]["kwargs"]["headers"]

    def test_search_no_ohlcv_result_omits_symbol(self, monkeypatch):
        _write_config(qv._CONFIG_PATH)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse(
                    {
                        "search_id": "s_1",
                        "results": [
                            {
                                "tool_id": "news",
                                "name": "Company news",
                                "description": "Headlines by ticker symbol",
                                "expected_cost": "1",
                                "stats": {"success_rate": 1},
                            }
                        ],
                    }
                )
            ],
        )

        assert qv.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31") == {}
        assert len(session.calls) == 1

    def test_date_filtering_and_ohlc_validation(self, monkeypatch):
        _write_config(qv._CONFIG_PATH)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse({"search_id": "s_1", "results": [_capability()]}),
                _FakeResponse(
                    {
                        "success": True,
                        "result": {
                            "historical": [
                                {"date": "2023-12-29", "open": 1, "high": 1, "low": 1, "close": 1},
                                {"date": "2024-01-02", "open": 2, "high": 3, "low": 1, "close": 2.5},
                                {"date": "2024-01-03", "open": 5, "high": 4, "low": 1, "close": 4},
                                {"date": "2024-02-01", "open": 6, "high": 6, "low": 6, "close": 6},
                            ]
                        },
                    }
                ),
            ],
        )

        df = qv.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31")["AAPL"]

        assert [d.strftime("%Y-%m-%d") for d in df.index] == ["2024-01-02"]
        assert df.loc["2024-01-02", "open"] == 2.0
        assert len(session.calls) == 2

    def test_invalid_date_range_raises(self):
        _write_config(qv._CONFIG_PATH)
        with pytest.raises(ValueError):
            qv.DataLoader().fetch(["AAPL"], "2024-02-01", "2024-01-01")


class TestHttpClient:
    """429 backoff is local and mockable."""

    def test_429_retries_after_header(self, monkeypatch):
        _write_config(qv._CONFIG_PATH)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse({}, status_code=429, headers={"Retry-After": "0"}),
                _FakeResponse({"search_id": "s_1", "results": []}),
            ],
        )

        payload = qv.QVerisClient(qv._load_config()).search("daily OHLCV AAPL")

        assert payload == {"search_id": "s_1", "results": []}
        assert len(session.calls) == 2


class TestCapabilitySelection:
    """Granularity filtering and multi-candidate fallback (live-e2e regressions)."""

    def test_daily_request_excludes_monthly_and_intraday_series(self, monkeypatch):
        """A monthly series with perfect stats must lose to a daily one."""
        _write_config(qv._CONFIG_PATH)
        monthly = _capability("alphavantage.time_series.monthly_adjusted.v1", success_rate=1.0)
        monthly["name"] = "Monthly Adjusted Time Series"
        intraday = _capability("alphavantage.time-series.intraday.v1", success_rate=1.0)
        intraday["description"] = "Intraday open high low close by ticker symbol"
        daily = _capability("tiingo.core.eod.v1", success_rate=0.5)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse(
                    {"search_id": "s_1", "results": [monthly, intraday, daily]}
                ),
                _FakeResponse(
                    {
                        "success": True,
                        "result": {
                            "data": [
                                {
                                    "date": "2024-01-02",
                                    "open": 1,
                                    "high": 2,
                                    "low": 0.5,
                                    "close": 1.5,
                                    "volume": 10,
                                }
                            ]
                        },
                    }
                ),
            ],
        )

        data = qv.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31")

        assert "AAPL" in data
        execute_url = session.calls[1]["url"]
        assert "tiingo.core.eod.v1" in execute_url

    def test_falls_back_to_second_candidate_when_first_result_unparseable(self, monkeypatch):
        """An unparseable paid result must not silently drop the symbol."""
        _write_config(qv._CONFIG_PATH)
        first = _capability("daily_bad", success_rate=0.99)
        second = _capability("daily_good", success_rate=0.90)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse({"search_id": "s_1", "results": [first, second]}),
                _FakeResponse({"success": True, "result": {"unexpected": "shape"}}),
                _FakeResponse(
                    {
                        "success": True,
                        "result": {
                            "data": [
                                {
                                    "date": "2024-01-02",
                                    "open": 1,
                                    "high": 2,
                                    "low": 0.5,
                                    "close": 1.5,
                                    "volume": 10,
                                }
                            ]
                        },
                    }
                ),
            ],
        )

        data = qv.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31")

        assert "AAPL" in data
        assert "daily_bad" in session.calls[1]["url"]
        assert "daily_good" in session.calls[2]["url"]

    def test_parses_provider_named_series_container(self, monkeypatch):
        """AlphaVantage-style '<X> Time Series' containers must parse."""
        _write_config(qv._CONFIG_PATH)
        session = _install_session(
            monkeypatch,
            [
                _FakeResponse({"search_id": "s_1", "results": [_capability()]}),
                _FakeResponse(
                    {
                        "success": True,
                        "result": {
                            "Meta Data": {"1. Information": "Daily Prices"},
                            "Time Series (Daily Adjusted)": {
                                "2024-01-02": {
                                    "1. open": "1.0",
                                    "2. high": "2.0",
                                    "3. low": "0.5",
                                    "4. close": "1.5",
                                    "5. volume": "10",
                                }
                            },
                        },
                    }
                ),
            ],
        )

        data = qv.DataLoader().fetch(["AAPL"], "2024-01-01", "2024-01-31")

        assert "AAPL" in data
        assert float(data["AAPL"]["close"].iloc[0]) == 1.5
        assert len(session.calls) == 2


def test_auto_fallback_chains_do_not_contain_qveris():
    """QVeris is explicit-only and must never be selected by source='auto'."""
    assert "qveris" in LOADER_REGISTRY
    assert all("qveris" not in chain for chain in FALLBACK_CHAINS.values())


def test_explicit_unavailable_qveris_does_not_fallback_to_network():
    """An unavailable explicit qveris source raises instead of falling back."""
    with pytest.raises(NoAvailableSourceError) as excinfo:
        get_loader_cls_with_fallback("qveris")
    assert "qveris" in str(excinfo.value).lower()
