"""Tests for fund_flow_tool: envelope shape, parsing, per-symbol isolation.

All HTTP is mocked at the Eastmoney client functions the tool imports
(:func:`get_json` / :func:`resolve_secid`), so no test touches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools.fund_flow_tool import FundFlowTool

_DAILY_PAYLOAD = {
    "data": {
        "code": "600519",
        "klines": [
            "2024-01-02,100.0,-10.0,5.0,60.0,40.0,0,0,0,0,0,0,0,0,0",
            "2024-01-03,-50.0,20.0,-5.0,-30.0,-20.0,0,0,0,0,0,0,0,0,0",
        ],
    }
}


class TestSuccessEnvelope:
    """A resolvable symbol yields the ok envelope with labelled buckets."""

    def test_daily_flow_parses_into_buckets(self):
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="1.600519"
        ), patch(
            "src.tools.fund_flow_tool.get_json", return_value=_DAILY_PAYLOAD
        ):
            text = FundFlowTool().execute(codes=["600519.SH"], period="daily", days=30)

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["market"] == "stock"
        assert payload["source"] == "eastmoney"
        assert payload["period"] == "daily"
        assert payload["buckets"] == ["main", "small", "medium", "large", "super_large"]

        rows = payload["data"]["600519.SH"]["rows"]
        assert len(rows) == 2
        assert rows[0] == {
            "timestamp": "2024-01-02",
            "main": 100.0,
            "small": -10.0,
            "medium": 5.0,
            "large": 60.0,
            "super_large": 40.0,
        }

    def test_days_cap_keeps_most_recent_rows(self):
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="1.600519"
        ), patch(
            "src.tools.fund_flow_tool.get_json", return_value=_DAILY_PAYLOAD
        ):
            text = FundFlowTool().execute(codes=["600519.SH"], period="daily", days=1)

        rows = json.loads(text)["data"]["600519.SH"]["rows"]
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2024-01-03"

    def test_minute_period_uses_minute_url(self):
        minute_payload = {"data": {"klines": ["2024-01-02 09:31,1.0,2.0,3.0,4.0,5.0"]}}
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="1.600519"
        ), patch(
            "src.tools.fund_flow_tool.get_json", return_value=minute_payload
        ) as mock_get:
            text = FundFlowTool().execute(codes=["600519.SH"], period="min")

        url = mock_get.call_args[0][0]
        assert "fflow/kline/get" in url
        rows = json.loads(text)["data"]["600519.SH"]["rows"]
        assert rows[0]["timestamp"] == "2024-01-02 09:31"
        assert rows[0]["main"] == 1.0


class TestPerSymbolIsolation:
    """A single failing/unresolvable symbol never aborts the batch."""

    def test_unresolvable_symbol_is_reported_not_fatal(self):
        def fake_resolve(symbol):
            return None if symbol == "BAD" else "1.600519"

        with patch(
            "src.tools.fund_flow_tool.resolve_secid", side_effect=fake_resolve
        ), patch(
            "src.tools.fund_flow_tool.get_json", return_value=_DAILY_PAYLOAD
        ):
            text = FundFlowTool().execute(codes=["BAD", "600519.SH"])

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["data"]["BAD"]["error"] == "unresolvable symbol"
        assert len(payload["data"]["600519.SH"]["rows"]) == 2

    def test_http_failure_on_one_symbol_is_captured(self):
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="1.600519"
        ), patch(
            "src.tools.fund_flow_tool.get_json", side_effect=RuntimeError("HTTP 429")
        ), patch(
            "src.tools.fund_flow_tool._fetch_sina_daily_flow",
            side_effect=RuntimeError("Sina unavailable"),
        ), patch(
            "src.tools.fund_flow_tool.tushare_fallbacks.fetch_fund_flow",
            side_effect=RuntimeError("no fallback"),
        ):
            text = FundFlowTool().execute(codes=["600519.SH"])

        payload = json.loads(text)
        assert payload["ok"] is True
        assert "429" in payload["data"]["600519.SH"]["error"]

    def test_http_failure_uses_tushare_fallback_when_available(self):
        fallback = {
            "symbol": "600519.SH",
            "ts_code": "600519.SH",
            "source": "tushare",
            "rows": [{"timestamp": "2024-01-03", "main": 100.0}],
        }
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="1.600519"
        ), patch(
            "src.tools.fund_flow_tool.get_json", side_effect=RuntimeError("HTTP 429")
        ), patch(
            "src.tools.fund_flow_tool._fetch_sina_daily_flow",
            side_effect=RuntimeError("Sina unavailable"),
        ), patch(
            "src.tools.fund_flow_tool.tushare_fallbacks.fetch_fund_flow",
            return_value=fallback,
        ) as fallback_fetch:
            text = FundFlowTool().execute(codes=["600519.SH"], period="daily", days=5)

        fallback_fetch.assert_called_once_with("600519.SH", days=5)
        payload = json.loads(text)
        result = payload["data"]["600519.SH"]
        assert result["source"] == "tushare"
        assert result["rows"][0]["timestamp"] == "2024-01-03"
        assert "used tushare fallback" in result["warning"]

    def test_http_failure_uses_sina_before_tushare(self):
        fallback = {
            "symbol": "002407.SZ",
            "source": "sina",
            "rows": [{"timestamp": "2024-01-03", "main": 300.0}],
        }
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="0.002407"
        ), patch(
            "src.tools.fund_flow_tool.get_json", side_effect=RuntimeError("Eastmoney blocked")
        ), patch(
            "src.tools.fund_flow_tool._fetch_sina_daily_flow", return_value=fallback
        ) as sina_fetch, patch(
            "src.tools.fund_flow_tool.tushare_fallbacks.fetch_fund_flow"
        ) as tushare_fetch:
            text = FundFlowTool().execute(codes=["002407.SZ"], period="daily", days=5)

        sina_fetch.assert_called_once_with("002407.SZ", days=5)
        tushare_fetch.assert_not_called()
        result = json.loads(text)["data"]["002407.SZ"]
        assert result["source"] == "sina"
        assert "used sina fallback" in result["warning"]

    def test_sina_daily_rows_keep_cny_units_and_mark_missing_buckets(self, monkeypatch):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps([{
                    "opendate": "2024-01-03",
                    "netamount": "10.0",
                    "r0_net": "1.0",
                    "r1_net": "2.0",
                    "r2_net": "3.0",
                    "r3_net": "4.0",
                }]).encode()

        monkeypatch.setattr("src.tools.fund_flow_tool.urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())

        from src.tools.fund_flow_tool import _fetch_sina_daily_flow

        result = _fetch_sina_daily_flow("002407.SZ", days=5)

        assert result["source"] == "sina"
        assert result["rows"] == [{
            "timestamp": "2024-01-03",
            "main": 1.0,
            "small": 4.0,
            "medium": 3.0,
            "large": 2.0,
            "super_large": None,
        }]
        assert result["available_buckets"] == ["main", "small", "medium", "large"]

    def test_sina_actual_shape_uses_main_and_overall_without_inventing_buckets(self, monkeypatch):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps([{
                    "opendate": "2024-01-03",
                    "netamount": "-563868939.7000",
                    "r0_net": "-497955884.7400",
                }]).encode()

        monkeypatch.setattr("src.tools.fund_flow_tool.urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())

        from src.tools.fund_flow_tool import _fetch_sina_daily_flow

        result = _fetch_sina_daily_flow("002407.SZ", days=5)

        assert result["rows"] == [{
            "timestamp": "2024-01-03",
            "main": -497955884.74,
            "small": None,
            "medium": None,
            "large": None,
            "super_large": None,
        }]
        assert result["available_buckets"] == ["main"]

    def test_malformed_row_skipped(self):
        bad = {"data": {"klines": ["garbage", "2024-01-03,-50.0,20.0,-5.0,-30.0,-20.0"]}}
        with patch(
            "src.tools.fund_flow_tool.resolve_secid", return_value="1.600519"
        ), patch("src.tools.fund_flow_tool.get_json", return_value=bad):
            text = FundFlowTool().execute(codes=["600519.SH"])

        rows = json.loads(text)["data"]["600519.SH"]["rows"]
        assert len(rows) == 1


class TestErrorEnvelope:
    """Input validation returns the ok=false envelope before any HTTP."""

    def test_empty_codes_rejected(self):
        payload = json.loads(FundFlowTool().execute(codes=[]))
        assert payload["ok"] is False
        assert "codes" in payload["error"]

    def test_missing_codes_rejected(self):
        payload = json.loads(FundFlowTool().execute())
        assert payload["ok"] is False

    def test_non_string_code_rejected(self):
        payload = json.loads(FundFlowTool().execute(codes=[123]))
        assert payload["ok"] is False

    def test_invalid_period_rejected(self):
        payload = json.loads(
            FundFlowTool().execute(codes=["600519.SH"], period="hourly")
        )
        assert payload["ok"] is False
        assert "period" in payload["error"]

    def test_non_positive_days_rejected(self):
        payload = json.loads(
            FundFlowTool().execute(codes=["600519.SH"], days=0)
        )
        assert payload["ok"] is False
        assert "days" in payload["error"]

    def test_bool_days_rejected(self):
        payload = json.loads(
            FundFlowTool().execute(codes=["600519.SH"], days=True)
        )
        assert payload["ok"] is False


class TestRoutingDescription:
    """Description must scope to PER-STOCK flow so vague prompts don't misroute.

    Regression for B10-routing-desc: get_fund_flow and get_northbound_flow both
    used to open on a generic 'net capital flow' phrase, so a vague prompt could
    route to either. The fund-flow description must lead with the per-stock,
    order-level scope and point market-wide intent at get_northbound_flow.
    """

    def test_description_leads_with_per_stock_order_level(self):
        desc = FundFlowTool().description
        # Leads with the per-stock, order-level scope, not a generic phrase.
        assert desc.startswith("PER-STOCK order-level net inflow")
        assert "market-wide" not in desc.lower().split("not market-wide")[0]
        # Disambiguates against the market-wide tool.
        assert "get_northbound_flow" in desc

    def test_description_keeps_a_concrete_example(self):
        assert '{"codes": ["600519.SH"' in FundFlowTool().description
