"""Tests for get_northbound_flow: success + error envelopes, HTTP fully mocked.

All Eastmoney HTTP is mocked at ``src.tools.northbound_tool.get_json`` (the name
the tool imported), so no test touches a live Eastmoney endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import northbound_tool as nb


def _realtime_payload() -> dict:
    return {
        "data": {
            "hk2sh": {"netBuyAmt": 1200.5},
            "hk2sz": {"netBuyAmt": -300.0},
        }
    }


def _history_payload() -> dict:
    return {
        "data": {
            "klines": [
                "2024-01-02,100.0,50.0",
                "2024-01-03,-20.0,80.0",
                "2024-01-04,-,-",
            ]
        }
    }


def _fake_get_json(url: str, *, params: dict):
    if "kamt.kline" in url:
        return _history_payload()
    return _realtime_payload()


class TestSuccessEnvelope:
    def test_returns_realtime_and_history(self):
        with patch.object(nb, "get_json", side_effect=_fake_get_json):
            text = nb.NorthboundFlowTool().execute(lookback_days=10)

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["market"] == "China A"
        assert payload["source"] == "eastmoney"

        data = payload["data"]
        assert data["lookback_days"] == 10
        assert data["realtime"]["shanghai_connect"] == 1200.5
        assert data["realtime"]["shenzhen_connect"] == -300.0
        assert data["realtime"]["total"] == 900.5

        history = data["history"]
        assert len(history) == 3
        assert history[0] == {
            "trade_date": "2024-01-02",
            "shanghai_connect": 100.0,
            "shenzhen_connect": 50.0,
            "total": 150.0,
        }
        # A "-" sentinel row coerces to None without aborting the batch.
        assert history[-1]["shanghai_connect"] is None
        assert history[-1]["total"] is None

    def test_default_lookback_applied_when_absent(self):
        with patch.object(nb, "get_json", side_effect=_fake_get_json):
            text = nb.NorthboundFlowTool().execute()
        payload = json.loads(text)
        assert payload["data"]["lookback_days"] == nb._DEFAULT_LOOKBACK_DAYS

    def test_lookback_is_clamped_to_ceiling(self):
        with patch.object(nb, "get_json", side_effect=_fake_get_json):
            text = nb.NorthboundFlowTool().execute(lookback_days=99999)
        payload = json.loads(text)
        assert payload["data"]["lookback_days"] == nb._MAX_LOOKBACK_DAYS

    def test_history_trimmed_to_lookback(self):
        with patch.object(nb, "get_json", side_effect=_fake_get_json):
            text = nb.NorthboundFlowTool().execute(lookback_days=1)
        payload = json.loads(text)
        history = payload["data"]["history"]
        assert len(history) == 1
        assert history[0]["trade_date"] == "2024-01-04"


class TestErrorEnvelope:
    def test_http_failure_returns_error_envelope(self):
        with patch.object(nb, "get_json", side_effect=RuntimeError("HTTP 429")), patch.object(
            nb.tushare_fallbacks,
            "fetch_northbound_flow",
            side_effect=RuntimeError("no fallback"),
        ):
            text = nb.NorthboundFlowTool().execute(lookback_days=5)
        payload = json.loads(text)
        assert payload["ok"] is False
        assert "429" in payload["error"]

    def test_http_failure_uses_tushare_fallback_when_available(self):
        fallback = {
            "unit": "10k CNY",
            "lookback_days": 5,
            "realtime": {"total": 100.0},
            "history": [{"trade_date": "2024-01-03", "total": 100.0}],
        }
        with patch.object(nb, "get_json", side_effect=RuntimeError("HTTP 429")), patch.object(
            nb.tushare_fallbacks,
            "fetch_northbound_flow",
            return_value=fallback,
        ) as fallback_fetch:
            text = nb.NorthboundFlowTool().execute(lookback_days=5)

        fallback_fetch.assert_called_once_with(lookback_days=5)
        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "tushare"
        assert payload["data"]["history"][0]["trade_date"] == "2024-01-03"
        assert "used tushare fallback" in payload["warnings"][0]

    def test_missing_data_block_is_dead_feed_and_falls_through(self):
        """A structurally empty payload is the live post-reform state (#1481):
        it must fall through to tushare, not pass as an empty success."""
        fallback = {
            "unit": "CNY million",
            "lookback_days": 5,
            "note": "HKEX stopped publishing northbound net buy on 2024-08-30...",
            "realtime": {"total": 259865.83},
            "history": [{"trade_date": "2026-09-17", "total": 259865.83}],
        }
        with patch.object(nb, "get_json", return_value={"data": None}), patch.object(
            nb.tushare_fallbacks,
            "fetch_northbound_flow",
            return_value=fallback,
        ) as fallback_fetch:
            text = nb.NorthboundFlowTool().execute(lookback_days=5)

        fallback_fetch.assert_called_once_with(lookback_days=5)
        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "tushare"
        assert "used tushare fallback" in payload["warnings"][0]
        assert payload["data"]["unit"] == "CNY million"


class TestDeadFeedDetection:
    """Eastmoney's northbound net feed died at the 2024-08-30 disclosure reform.

    The HTTP calls still succeed with all-zero nets / a frozen cumulative (and
    the payload shape drifted so the parsers find nothing), which used to pass
    as an empty ok:true envelope and short-circuit the tushare fallback.
    """

    def test_all_zero_payload_falls_through_to_tushare(self):
        dead_realtime = {
            "data": {
                "hk2sh": {"netBuyAmt": 0.0},
                "hk2sz": {"netBuyAmt": 0.0},
            }
        }
        dead_history = {
            "data": {
                "klines": [
                    "2026-09-16,0.0,0.0",
                    "2026-09-17,0.0,0.0",
                ]
            }
        }

        def fake(url: str, *, params: dict):
            return dead_history if "kamt.kline" in url else dead_realtime

        fallback = {
            "unit": "CNY million",
            "lookback_days": 5,
            "note": "...2024-08-30...",
            "realtime": {"total": 4.5},
            "history": [{"trade_date": "2026-09-17", "total": 4.5}],
        }
        with patch.object(nb, "get_json", side_effect=fake), patch.object(
            nb.tushare_fallbacks,
            "fetch_northbound_flow",
            return_value=fallback,
        ):
            text = nb.NorthboundFlowTool().execute(lookback_days=5)

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "tushare"
        assert "2024-08-30" in payload["warnings"][0]

    def test_dead_feed_without_tushare_returns_honest_error(self):
        with patch.object(nb, "get_json", return_value={"data": None}), patch.object(
            nb.tushare_fallbacks,
            "fetch_northbound_flow",
            side_effect=RuntimeError("TUSHARE_TOKEN not set"),
        ):
            text = nb.NorthboundFlowTool().execute(lookback_days=5)

        payload = json.loads(text)
        assert payload["ok"] is False
        assert "2024-08-30" in payload["error"]
        assert "tushare fallback failed" in payload["error"]

    def test_healthy_payload_still_serves_eastmoney(self):
        """Guard: detection must not swallow a live non-zero feed."""
        with patch.object(nb, "get_json", side_effect=_fake_get_json):
            text = nb.NorthboundFlowTool().execute(lookback_days=10)
        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "eastmoney"

    def test_realtime_alive_history_dead_is_not_dead_feed(self):
        """Both sides must be dead: a trimmed all-None history window with a
        live realtime figure still serves the Eastmoney envelope."""
        live_realtime = {
            "data": {"hk2sh": {"netBuyAmt": 12.5}, "hk2sz": {"netBuyAmt": 0.0}}
        }

        def fake(url: str, *, params: dict):
            if "kamt.kline" in url:
                return {"data": {"klines": ["2026-09-17,0.0,0.0"]}}
            return live_realtime

        with patch.object(nb, "get_json", side_effect=fake):
            text = nb.NorthboundFlowTool().execute(lookback_days=5)
        payload = json.loads(text)
        assert payload["source"] == "eastmoney"
        assert payload["data"]["realtime"]["shanghai_connect"] == 12.5


class TestToolMetadata:
    def test_name_and_required_params(self):
        tool = nb.NorthboundFlowTool()
        assert tool.name == "get_northbound_flow"
        assert tool.is_readonly is True
        assert tool.parameters["required"] == []
        assert "lookback_days" in tool.parameters["properties"]


class TestRoutingDescription:
    """Description must scope to MARKET-WIDE Stock-Connect flow, not per-stock.

    Regression for B10-routing-desc: get_fund_flow and get_northbound_flow both
    used to open on a generic 'net capital flow' phrase, so a vague prompt could
    route to either. The northbound description must lead with the market-wide
    Stock-Connect scope and point per-stock intent at get_fund_flow.
    """

    def test_description_leads_with_market_wide_stock_connect(self):
        desc = nb.NorthboundFlowTool().description
        assert desc.startswith("MARKET-WIDE Northbound")
        assert "北向" in desc
        # Disambiguates against the per-stock tool.
        assert "get_fund_flow" in desc
        assert "NOT per-stock" in desc

    def test_description_keeps_a_concrete_example(self):
        assert "get_northbound_flow(lookback_days=10)" in nb.NorthboundFlowTool().description
