"""Regression tests for the overview market-data boundary."""

from __future__ import annotations

from types import SimpleNamespace

from src.api import market_routes
from src import a_share_data


def _payload(*, symbol: str, price: str, change_pct: str) -> bytes:
    values = ["200", symbol, symbol, price] + ["0"] * 29
    values[32] = change_pct
    return f'v_us{symbol}="{"~".join(values)}";'.encode("gbk")


def test_tencent_us_parser_handles_multiple_lines(monkeypatch) -> None:
    body = _payload(symbol="AAPL", price="305.93", change_pct="0.22")
    body += b"\n" + _payload(symbol="MSFT", price="495.40", change_pct="-0.30")
    monkeypatch.setattr(
        market_routes,
        "throttled_get",
        lambda *args, **kwargs: SimpleNamespace(content=body),
    )

    result = market_routes._fetch_tencent_us_snapshots(["AAPL.US", "MSFT.US"])

    assert result == {"AAPL.US": (305.93, 0.22), "MSFT.US": (495.4, -0.3)}


def test_tencent_symbol_search_supports_name_initials_and_code(monkeypatch) -> None:
    body = 'v_hint="sh~600519~\\u8d35\\u5dde\\u8305\\u53f0~gzmt~GP^us~aapl.oq~\\u82f9\\u679c~pg~GP";'.encode("utf-8")
    monkeypatch.setattr(
        market_routes,
        "throttled_get",
        lambda *args, **kwargs: SimpleNamespace(content=body),
    )

    assert market_routes._search_tencent_symbols("茅台", "a_share") == [
        {"symbol": "600519.SH", "name": "贵州茅台", "market": "a_share"}
    ]
    assert market_routes._search_tencent_symbols("aapl", "us") == [
        {"symbol": "AAPL.US", "name": "苹果", "market": "us"}
    ]


def test_us_snapshot_prefers_yfinance_and_falls_back_per_symbol(monkeypatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "_fetch_yfinance_snapshots",
        lambda symbols: {"AAPL.US": (305.93, 0.22)},
    )
    monkeypatch.setattr(
        market_routes,
        "_fetch_tencent_us_snapshots",
        lambda symbols: {"MSFT.US": (495.4, -0.3)},
    )

    result = market_routes._fetch_us_snapshots(["AAPL.US", "MSFT.US"])

    assert result["AAPL.US"] == (305.93, 0.22, "yfinance")
    assert result["MSFT.US"] == (495.4, -0.3, "tencent-fallback")


def test_industry_reports_use_qtype_one_without_stock_code(monkeypatch) -> None:
    captured: list[dict[str, str]] = []

    def fake_get(*args, **kwargs):
        captured.append(kwargs["params"])
        return SimpleNamespace(
            json=lambda: {
                "data": [{
                    "publishDate": "2026-08-15 00:00:00",
                    "orgSName": "测试机构",
                    "title": "人形机器人产业链行业报告",
                }],
                "TotalPage": 1,
            }
        )

    monkeypatch.setattr(a_share_data, "_em_get", fake_get)
    reports = a_share_data.eastmoney_industry_reports(days=90, limit=10, max_pages=1)

    assert reports[0]["title"] == "人形机器人产业链行业报告"
    assert captured[0]["qType"] == "1"
    assert captured[0]["industryCode"] == "*"
    assert "code" not in captured[0]


def test_robot_report_items_classify_and_normalize_fields() -> None:
    result = market_routes._robot_report_items(
        [{
            "publishDate": "2026-08-14 00:00:00",
            "orgSName": "测试机构",
            "title": "减速器与灵巧手产业链跟踪",
            "industryName": "机器人",
        }],
        20,
    )

    assert result == [{
        "date": "2026-08-14",
        "institution": "测试机构",
        "title": "减速器与灵巧手产业链跟踪",
        "segment": "机器人 / 减速器 / 灵巧手",
    }]


def test_hot_industries_combines_board_change_and_fund_flow(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        if kwargs["params"]["fid"] == "f3":
            return SimpleNamespace(json=lambda: {"data": {"diff": [
                {"f12": "BK001", "f14": "机器人", "f3": 5.0, "f104": 20, "f105": 5, "f140": "甲公司"},
                {"f12": "BK002", "f14": "银行", "f3": 1.0, "f104": 10, "f105": 15, "f140": "乙公司"},
            ]}})
        return SimpleNamespace(json=lambda: {"data": {"diff": [
            {"f12": "BK001", "f14": "机器人", "f3": 5.0, "f62": 100000000, "f184": 2.0, "f204": "甲公司", "f66": 60000000, "f72": 40000000, "f78": 0, "f84": -10000000},
            {"f12": "BK002", "f14": "银行", "f3": 1.0, "f62": -10000000, "f184": -0.2, "f204": "乙公司", "f66": -5000000, "f72": -5000000, "f78": 0, "f84": 0},
        ]}})

    monkeypatch.setattr(a_share_data, "_em_get", fake_get)
    result = a_share_data.eastmoney_hot_industries(limit=2)

    assert result["status"] == "ok"
    assert result["items"][0]["name"] == "机器人"
    assert result["items"][0]["rank"] == 1
    assert result["items"][0]["main_net"] == 100000000
