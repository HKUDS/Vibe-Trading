"""Regression tests for the stock detail aggregation route."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import market_routes
from src.api.security import require_auth
from src.session.models import AuthMethod, Principal


@pytest.fixture(autouse=True)
def disable_iwencai_skill_calls(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "iwencai_stock_reports",
        lambda *args, **kwargs: (_ for _ in ()).throw(market_routes.IwencaiSkillError("test fallback")),
    )
    monkeypatch.setattr(
        market_routes,
        "iwencai_stock_news",
        lambda *args, **kwargs: (_ for _ in ()).throw(market_routes.IwencaiSkillError("test fallback")),
    )


def test_a_share_detail_route_aggregates_profile_bars_reports_and_news(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        market_routes,
        "_get_stock_detail_store",
        lambda: market_routes.StockDetailStore(tmp_path / "details.db"),
    )
    monkeypatch.setattr(
        market_routes,
        "tencent_quote",
        lambda codes: {codes[0]: {"name": "贵州茅台", "price": 1500.0, "pe_ttm": 20.0}},
    )
    monkeypatch.setattr(
        market_routes,
        "eastmoney_stock_info",
        lambda code: {"industry": "白酒", "mcap": 1000.0},
    )
    monkeypatch.setattr(market_routes, "eastmoney_stock_boards", lambda code: [{"board_code": "BK0001", "board_name": "White Liquor", "change_pct": 1.2, "price": 1000.0}])
    requested_periods = []

    def fake_bars(code, start, end, period="1d"):
        requested_periods.append(period)
        return [{"trade_date": "2026-08-14", "open": 1490, "high": 1510, "low": 1480, "close": 1500, "volume": 100}]

    monkeypatch.setattr(market_routes, "tencent_bars", fake_bars)
    monkeypatch.setattr(
        market_routes,
        "ths_bars",
        lambda code, start, end, period="30m": [{
            "trade_date": "2026-08-14 10:30",
            "open": 1490,
            "high": 1510,
            "low": 1480,
            "close": 1500,
            "volume": 100,
        }],
    )
    monkeypatch.setattr(market_routes, "eastmoney_reports", lambda code, limit: [{"title": "研报"}])
    monkeypatch.setattr(market_routes, "eastmoney_stock_news", lambda code, limit: [{"title": "新闻"}])
    monkeypatch.setattr(market_routes, "sina_financial_report", lambda code, statement, limit: [])

    app = FastAPI()
    market_routes.register_market_routes(app)
    app.dependency_overrides[require_auth] = lambda: Principal(
        subject="shared-key-holder", auth_method=AuthMethod.SHARED_KEY
    )

    response = TestClient(app).get("/market/stocks/600519.SH")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "600519.SH"
    assert payload["profile"]["industry"] == "白酒"
    assert payload["bars"] == [{
        "time": "2026-08-14",
        "open": 1490.0,
        "high": 1510.0,
        "low": 1480.0,
        "close": 1500.0,
        "volume": 100.0,
    }]
    assert payload["reports"] == [{"title": "研报"}]
    assert payload["news"] == [{"title": "新闻"}]
    assert payload["financials"]["eps"] is None
    assert requested_periods == ["1d"]

    response = TestClient(app).get("/market/stocks/600519.SH?period=15m")
    assert response.status_code == 200
    assert response.json()["period"] == "15m"
    # Historical intraday periods use the asynchronous THS/Eastmoney refresh
    # path instead of the live-only Tencent minute endpoint.
    assert requested_periods == ["1d"]

    response = TestClient(app).get(
        "/market/stocks/002407.SZ?period=1d",
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["symbol"] == "002407.SZ"


def test_stock_news_route_supports_newest_first_pagination(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "eastmoney_stock_news",
        lambda code, limit, page: [
            {"title": f"page-{page}-new", "time": "2026-08-17 10:00:00"},
            {"title": f"page-{page}-old", "time": "2026-08-17 09:00:00"},
        ][:limit],
    )
    app = FastAPI()
    market_routes.register_market_routes(app)
    app.dependency_overrides[require_auth] = lambda: Principal(
        subject="shared-key-holder", auth_method=AuthMethod.SHARED_KEY
    )

    response = TestClient(app).get("/market/stocks/600519.SH/news?page=2&page_size=2")

    assert response.status_code == 200
    assert response.json()["page"] == 2
    assert response.json()["items"][0]["title"] == "page-2-new"
    assert response.json()["has_more"] is True


def test_a_share_detail_can_skip_slow_news_for_fast_initial_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: market_routes.StockDetailStore(tmp_path / "details.db"))
    monkeypatch.setattr(market_routes, "tencent_quote", lambda codes: {codes[0]: {"name": "测试", "price": 10.0}})
    monkeypatch.setattr(market_routes, "eastmoney_stock_info", lambda code: {})
    monkeypatch.setattr(market_routes, "_a_share_financials", lambda code: {})
    monkeypatch.setattr(market_routes, "eastmoney_reports", lambda code, limit: [])
    monkeypatch.setattr(market_routes, "eastmoney_stock_boards", lambda code: [])
    monkeypatch.setattr(market_routes, "tencent_bars", lambda code, start, end, period="1d": [])
    monkeypatch.setattr(market_routes, "eastmoney_stock_news", lambda code, limit: (_ for _ in ()).throw(AssertionError("news must be deferred")))

    payload = market_routes._stock_detail_a_share("600519.SH", "1m", include_news=False)

    assert payload["news"] == []


def test_a_share_industry_section_only_returns_industry_and_boards(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        market_routes,
        "_get_stock_detail_store",
        lambda: market_routes.StockDetailStore(tmp_path / "details.db"),
    )
    monkeypatch.setattr(market_routes, "eastmoney_stock_info", lambda code: {"industry": "白酒"})
    monkeypatch.setattr(market_routes, "eastmoney_stock_boards", lambda code: [])

    market_routes._refresh_stock_industry_a_share("600519.SH")
    payload = market_routes._stock_industry_a_share("600519.SH")

    assert payload["boards"] == []
    assert "industry_news" not in payload
    assert payload["industry"] == "白酒"


def test_stock_reports_fall_back_to_live_source_when_cache_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "_get_stock_detail_store",
        lambda: (_ for _ in ()).throw(OSError("cache unavailable")),
    )
    monkeypatch.setattr(
        market_routes,
        "eastmoney_reports",
        lambda code, limit: [{"title": "Live report", "publishDate": "2026-08-17 00:00:00"}],
    )

    payload = market_routes._stock_reports_a_share("600519.SH")

    assert payload["reports"] == [{"title": "Live report", "publishDate": "2026-08-17 00:00:00"}]


def test_stock_news_falls_back_to_live_source_when_cache_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "_get_stock_detail_store",
        lambda: (_ for _ in ()).throw(OSError("cache unavailable")),
    )
    monkeypatch.setattr(
        market_routes,
        "eastmoney_stock_news",
        lambda code, limit, page: [{"title": "Live news", "time": "2026-08-17 10:00:00"}],
    )

    payload = market_routes._stock_news_cached("600519.SH", 1, 20)

    assert payload["items"] == [{"title": "Live news", "time": "2026-08-17 10:00:00"}]


def test_a_share_bars_endpoint_normalizes_provider_trade_date(monkeypatch, tmp_path) -> None:
    today = market_routes.StockDetailStore.today()
    monkeypatch.setattr(
        market_routes,
        "_get_stock_detail_store",
        lambda: market_routes.StockDetailStore(tmp_path / "details.db"),
    )
    monkeypatch.setattr(
        market_routes,
        "tencent_bars",
        lambda code, start, end, period="1m": [
            {"trade_date": f"{today} 09:31", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 10}
        ],
    )
    market_routes._refresh_stock_bars_a_share("600519.SH", "1m")

    payload = market_routes._stock_bars_a_share("600519.SH", "1m")

    assert payload["bars"] == [{
        "time": f"{today} 09:31",
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
            "close": 100.0,
            "volume": 10.0,
            "amount": 995.0,
    }]
    cached = market_routes.StockDetailStore(tmp_path / "details.db").get_bars("600519.SH", "1m")
    assert cached is not None


def test_us_detail_sections_read_cached_info_and_bars_without_provider_call(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    store.save_static("AAPL.US", {
        "profile": {"code": "AAPL", "name": "Apple"},
        "quote": {"price": 200.0, "change_pct": 1.5, "source": "test"},
        "financials": {},
        "reports": [],
        "industry": "Technology",
        "boards": [],
    })
    store.save_bars("AAPL.US", "1d", [{
        "trade_date": "2026-08-17",
        "open": 199,
        "high": 201,
        "low": 198,
        "close": 200,
        "volume": 1000,
    }])
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_fetch_us_snapshots", lambda symbols: (_ for _ in ()).throw(AssertionError("provider must not run")))
    monkeypatch.setattr(market_routes, "YFinanceLoader", lambda: (_ for _ in ()).throw(AssertionError("provider must not run")))

    info = market_routes._stock_info_us("AAPL.US")
    bars = market_routes._stock_bars_us("AAPL.US", "1d")

    assert info["profile"]["price"] == 200.0
    assert info["cache_status"] == "cached"
    assert bars["bars"][0]["time"] == "2026-08-17"
    assert bars["cache_status"] == "cached"


def test_us_daily_bars_compute_chan_once_and_reuse_snapshot(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    calls = {"bars": 0}

    def fake_bars(symbol, period):
        calls["bars"] += 1
        return [{
            "trade_date": "2026-08-17",
            "open": 199,
            "high": 201,
            "low": 198,
            "close": 200,
            "volume": 1000,
        }]

    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_fetch_stock_bars_us", fake_bars)

    first = market_routes._stock_bars_us("AAPL.US", "1d")
    second = market_routes._stock_bars_us("AAPL.US", "1d")

    assert calls["bars"] == 1
    assert first["chan_analysis"]["version"] == "chan-structure-v2"
    assert second["chan_analysis"]["version"] == "chan-structure-v2"
    assert second["from_cache"] is True


def test_us_incomplete_intraday_cache_refreshes_when_market_is_closed(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    calls = {"bars": 0}
    store.save_bars("AAPL.US", "1m", [{
        "trade_date": f"{store.today()} 21:30",
        "open": 199,
        "high": 201,
        "low": 198,
        "close": 200,
        "volume": 1000,
    }])
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: False)
    monkeypatch.setattr(
        market_routes,
        "_fetch_stock_bars_us",
        lambda *args: calls.__setitem__("bars", calls["bars"] + 1) or [{
            "trade_date": f"{store.today()} 21:30",
            "open": 199,
            "high": 201,
            "low": 198,
            "close": 200,
            "volume": 1000,
        }],
    )

    payload = market_routes._stock_bars_us("AAPL.US", "1m")

    assert calls["bars"] == 1
    assert payload["cache_status"] == "cached"


def test_us_complete_cross_midnight_session_is_reused_when_market_is_closed(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    session_start = datetime(2026, 8, 17, 21, 30)
    store.save_bars("AAPL.US", "1m", [
        {
            "trade_date": (session_start + timedelta(minutes=index)).strftime("%Y-%m-%d %H:%M"),
            "open": 199,
            "high": 201,
            "low": 198,
            "close": 200,
            "volume": 1000,
        }
        for index in range(390)
    ])
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: False)
    monkeypatch.setattr(
        market_routes,
        "_fetch_stock_bars_us",
        lambda *args: (_ for _ in ()).throw(AssertionError("complete US session must not fetch")),
    )

    payload = market_routes._stock_bars_us("AAPL.US", "1m")

    assert payload["cache_status"] == "cached"
    assert len(payload["bars"]) == 390


def test_us_intraday_bars_are_filtered_to_latest_session_and_converted_to_shanghai(monkeypatch, tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "open": [99.0, 100.0, 101.0],
            "high": [100.0, 101.0, 102.0],
            "low": [98.0, 99.0, 100.0],
            "close": [99.5, 100.5, 101.5],
            "volume": [10.0, 20.0, 30.0],
        },
        index=pd.to_datetime(["2026-08-14 09:30", "2026-08-17 09:30", "2026-08-17 10:30"]),
    )

    class FakeLoader:
        def fetch(self, symbols, start, end, interval):
            return {"AAPL.US": frame}

    class FakeNews:
        def execute(self, **kwargs):
            return json.dumps({"ok": True, "data": {"articles": []}})

    monkeypatch.setattr(market_routes, "YFinanceLoader", FakeLoader)
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_fetch_us_snapshots", lambda symbols: {"AAPL.US": (100.0, 1.0, "yfinance")})
    monkeypatch.setattr(market_routes, "StockNewsTool", FakeNews)

    market_routes._refresh_stock_bars_us("AAPL.US", "1m")
    payload = market_routes._stock_detail_us("AAPL.US", "1m")

    assert [bar["time"] for bar in payload["bars"]] == ["2026-08-17 21:30", "2026-08-17 22:30"]


def test_us_120_minute_bars_are_aggregated_and_persisted(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    frame = pd.DataFrame(
        {
            "open": [99.0, 100.0, 101.0, 102.0],
            "high": [100.0, 103.0, 102.0, 104.0],
            "low": [98.0, 99.0, 100.0, 101.0],
            "close": [100.0, 102.0, 101.0, 103.0],
            "volume": [10.0, 20.0, 30.0, 40.0],
        },
        index=pd.to_datetime([
            "2026-08-17 09:30",
            "2026-08-17 10:30",
            "2026-08-17 11:30",
            "2026-08-17 12:30",
        ]),
    )

    class FakeLoader:
        def fetch(self, symbols, start, end, interval):
            assert interval == "1H"
            return {"AAPL.US": frame}

    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "YFinanceLoader", FakeLoader)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: True)

    market_routes._refresh_stock_bars_us("AAPL.US", "120m")
    payload = market_routes._stock_bars_us("AAPL.US", "120m")

    assert payload["cache_status"] == "cached"
    assert payload["bars"] == [
            {
                "time": "2026-08-17 21:30",
            "open": 99.0,
            "high": 103.0,
            "low": 98.0,
                "close": 102.0,
                "volume": 30.0,
                "amount": 3015.0,
        },
        {
            "time": "2026-08-17 23:30",
            "open": 101.0,
            "high": 104.0,
            "low": 100.0,
                "close": 103.0,
                "volume": 70.0,
                "amount": 7140.0,
        },
    ]


def test_a_share_historical_intraday_periods_are_not_limited_to_today(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(
        market_routes,
        "ths_bars",
        lambda code, start, end, period="30m": [
            {"trade_date": "2026-08-14 14:30", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 10},
            {"trade_date": "2026-08-17 10:30", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 20},
        ],
    )
    monkeypatch.setattr(
        market_routes,
        "tencent_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("historical intraday must not use Tencent rolling data")),
    )

    market_routes._refresh_stock_bars_a_share("600519.SH", "30m")
    payload = market_routes._stock_bars_a_share("600519.SH", "30m")

    assert [bar["time"] for bar in payload["bars"]] == ["2026-08-14 14:30", "2026-08-17 10:30"]


def test_a_share_120_minute_bars_are_aggregated_from_historical_60_minute_bars(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(
        market_routes,
        "ths_bars",
        lambda code, start, end, period="60m": [
            {"trade_date": "2026-08-17 10:30", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 10},
            {"trade_date": "2026-08-17 11:30", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 20},
        ],
    )

    market_routes._refresh_stock_bars_a_share("600519.SH", "120m")
    payload = market_routes._stock_bars_a_share("600519.SH", "120m")

    assert payload["bars"] == [{
        "time": "2026-08-17 10:30",
        "open": 99.0,
        "high": 103.0,
        "low": 98.0,
            "close": 102.0,
            "volume": 30.0,
            "amount": 3015.0,
    }]


def test_a_share_intraday_cache_is_reused_when_market_is_closed(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    store.save_bars("600519.SH", "1m", [
        {
            "trade_date": f"2026-08-17 09:{index:02d}",
            "open": 99,
            "high": 101,
            "low": 98,
            "close": 100,
            "volume": 10,
            "source": "tencent",
        }
        for index in range(240)
    ])
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: False)
    monkeypatch.setattr(
        market_routes,
        "_refresh_stock_bars_a_share",
        lambda *args: (_ for _ in ()).throw(AssertionError("fresh intraday cache must be reused")),
    )

    payload = market_routes._stock_bars_a_share("600519.SH", "1m")

    assert payload["cache_status"] == "cached"
    # A cached previous-session line must not be rendered as today's live line
    # before the next A-share session opens.
    assert payload["bars"] == []


def test_incomplete_intraday_cache_refreshes_when_market_is_closed(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    today = store.today()
    calls = {"bars": 0}
    store.save_bars("600519.SH", "1m", [{
        "trade_date": f"{today} 09:31",
        "open": 99,
        "high": 101,
        "low": 98,
        "close": 100,
        "volume": 10,
        "source": "tencent",
    }])
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: False)
    monkeypatch.setattr(
        market_routes,
        "_fetch_stock_bars_a_share",
        lambda *args: calls.__setitem__("bars", calls["bars"] + 1) or [{
            "trade_date": f"{today} 09:31",
            "open": 99,
            "high": 101,
            "low": 98,
            "close": 100,
            "volume": 10,
        }],
    )

    payload = market_routes._stock_bars_a_share("600519.SH", "1m")

    assert calls["bars"] == 1
    assert payload["cache_status"] == "cached"


def test_empty_intraday_cache_refreshes_when_market_is_closed(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    calls = {"bars": 0}
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: False)
    monkeypatch.setattr(
        market_routes,
        "_fetch_stock_bars_a_share",
        lambda *args: calls.__setitem__("bars", calls["bars"] + 1) or [{
            "trade_date": f"{store.today()} 09:31",
            "open": 99,
            "high": 101,
            "low": 98,
            "close": 100,
            "volume": 10,
        }],
    )

    payload = market_routes._stock_bars_a_share("600519.SH", "1m")

    assert payload["cache_status"] == "cached"
    assert payload["bars"]
    assert calls["bars"] == 1


def test_a_share_historical_intraday_first_request_loads_data_when_market_is_closed(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    calls: list[str] = []
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "_stock_market_is_open", lambda market: False)

    def fake_fetch(code, period):
        calls.append(period)
        return [{
            "trade_date": "2026-08-17 10:30",
            "open": 99,
            "high": 101,
            "low": 98,
            "close": 100,
            "volume": 10,
            "source": "ths",
        }]

    monkeypatch.setattr(market_routes, "_fetch_stock_bars_a_share", fake_fetch)

    payload = market_routes._stock_bars_a_share("600519.SH", "15m")

    assert calls == ["15m"]
    assert payload["cache_status"] == "cached"
    assert payload["bars"][0]["time"] == "2026-08-17 10:30"


def test_a_share_30_minute_bars_merge_two_15_minute_bars(monkeypatch) -> None:
    calls: list[str] = []

    def fake_ths(code, start, end, period="30m"):
        calls.append(period)
        if period == "15m":
            return [
                {"trade_date": "2026-08-17 09:30", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 10, "source": "tencent"},
                {"trade_date": "2026-08-17 09:45", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 20, "source": "tencent"},
                {"trade_date": "2026-08-17 13:00", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 15, "source": "tencent"},
                {"trade_date": "2026-08-17 13:15", "open": 103, "high": 105, "low": 102, "close": 104, "volume": 25, "source": "tencent"},
            ]
        return []

    monkeypatch.setattr(market_routes, "ths_bars", fake_ths)
    monkeypatch.setattr(market_routes, "_eastmoney_historical_a_share_bars", lambda *args: [])

    rows = market_routes._fetch_stock_bars_a_share("600519.SH", "30m")

    assert calls == ["30m", "15m"]
    assert rows == [
        {"trade_date": "2026-08-17 09:30", "open": 99, "high": 103, "low": 98, "close": 102, "volume": 30, "source": "tencent", "_session": "2026-08-17"},
        {"trade_date": "2026-08-17 13:00", "open": 102, "high": 105, "low": 101, "close": 104, "volume": 40, "source": "tencent", "_session": "2026-08-17"},
    ]


def test_a_share_15_minute_bars_fall_back_to_eastmoney_history(monkeypatch, tmp_path) -> None:
    store = market_routes.StockDetailStore(tmp_path / "details.db")
    monkeypatch.setattr(market_routes, "_get_stock_detail_store", lambda: store)
    monkeypatch.setattr(market_routes, "ths_bars", lambda *args, **kwargs: [])

    class FakeLoader:
        def fetch(self, symbols, start_date, end_date, interval):
            frame = pd.DataFrame(
                [{"open": 99, "high": 101, "low": 98, "close": 100, "volume": 10}],
                index=pd.to_datetime(["2026-08-17 10:15"]),
            )
            return {symbols[0]: frame}

    monkeypatch.setattr(market_routes, "EastmoneyBarsLoader", FakeLoader)

    market_routes._refresh_stock_bars_a_share("600519.SH", "15m")
    payload = market_routes._stock_bars_a_share("600519.SH", "15m")

    assert payload["bars"][0]["time"] == "2026-08-17 10:15"
