"""Tests for the market-wide Southbound Stock-Connect tool."""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import southbound_tool as sb


def _full_history_payload() -> dict:
    # date, Shanghai NB, Shenzhen NB, North total, Shanghai SB, Shenzhen SB,
    # South total; values are in the tool's 10k CNY provider unit.
    return {
        "data": {
            "klines": [
                "2024-01-02,100,50,150,80,20,100",
                "2024-01-03,-20,80,60,40,-10,30",
            ]
        }
    }


def _fake_get_json(url: str, *, params: dict):
    if "kamt.kline" in url:
        assert params["fields2"] == "f51,f52,f53,f54,f55,f56,f57"
        return _full_history_payload()
    return {"data": None}


def test_eastmoney_parses_southbound_legs_and_uses_latest_daily_value() -> None:
    with patch.object(sb, "get_json", side_effect=_fake_get_json):
        payload = json.loads(sb.SouthboundFlowTool().execute(lookback_days=10))

    assert payload["ok"] is True
    assert payload["source"] == "eastmoney"
    assert payload["data"]["realtime"] == {
        "shanghai_connect": 40.0,
        "shenzhen_connect": -10.0,
        "total": 30.0,
    }
    assert payload["data"]["history"][0]["shanghai_connect"] == 80.0
    assert payload["data"]["history"][0]["shenzhen_connect"] == 20.0
    assert payload["warnings"]


def test_empty_eastmoney_payload_uses_tushare() -> None:
    fallback = {
        "unit": "10k CNY",
        "lookback_days": 5,
        "realtime": {"total": 12.0},
        "history": [{"trade_date": "2024-01-03", "total": 12.0}],
    }
    with patch.object(sb, "get_json", return_value={"data": None}), patch.object(
        sb.tushare_fallbacks,
        "fetch_southbound_flow",
        return_value=fallback,
    ) as fetch:
        payload = json.loads(sb.SouthboundFlowTool().execute(lookback_days=5))

    fetch.assert_called_once_with(lookback_days=5)
    assert payload["ok"] is True
    assert payload["source"] == "tushare"
    assert payload["data"] == fallback


def test_provider_failure_reports_missing_tushare_configuration() -> None:
    with patch.object(sb, "get_json", side_effect=RuntimeError("HTTP 503")), patch.object(
        sb.tushare_fallbacks,
        "fetch_southbound_flow",
        side_effect=RuntimeError("TUSHARE_TOKEN is not configured"),
    ):
        payload = json.loads(sb.SouthboundFlowTool().execute())

    assert payload["ok"] is False
    assert "HTTP 503" in payload["error"]
    assert "TUSHARE_TOKEN" in payload["error"]

