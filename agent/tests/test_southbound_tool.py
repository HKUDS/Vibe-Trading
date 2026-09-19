"""Tests for get_southbound_flow: envelopes, source fallback, HTTP fully mocked.

Eastmoney datacenter calls are mocked at ``southbound_tool.eastmoney_client``
and HKEX report fetches at ``southbound_tool.requests.get``, so no test
touches a live endpoint. Fixture figures mirror the HKEX-cross-verified
2026-09-17 values (港股通沪 net 25.0239亿 == Buy 26,387.65M − Sell
23,885.26M HKD).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.tools import southbound_tool as sb


def _em_rows(channel_net: dict[str, float]) -> dict:
    """Build one datacenter payload for a channel's NET_DEAL_AMT map."""
    return {
        "result": {
            "data": [
                {
                    "TRADE_DATE": f"{date} 00:00:00",
                    "NET_DEAL_AMT": net,
                    "BUY_AMT": net + 10.0,
                    "SELL_AMT": 10.0,
                }
                for date, net in sorted(channel_net.items(), reverse=True)
            ]
        }
    }


def _fake_get_json(url: str, *, params: dict):
    assert url == sb._DATACENTER_URL
    if '"002"' in params["filter"]:
        return _em_rows({"2026-09-16": 26.6898, "2026-09-17": 25.0239})
    return _em_rows({"2026-09-16": 8.6076, "2026-09-17": 9.9861})


class TestEastmoneyEnvelope:
    def test_returns_merged_history_and_latest(self):
        with patch.object(sb.eastmoney_client, "get_json", side_effect=_fake_get_json):
            text = sb.SouthboundFlowTool().execute(lookback_days=10)

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["market"] == "HK"
        assert payload["source"] == "eastmoney"

        data = payload["data"]
        assert data["unit"] == "100M HKD"
        assert data["lookback_days"] == 10
        assert "cumulative" in data["note"]

        history = data["history"]
        assert [row["trade_date"] for row in history] == [
            "2026-09-16",
            "2026-09-17",
        ]
        assert history[-1]["shanghai_connect"] == 25.0239
        assert history[-1]["shenzhen_connect"] == 9.9861
        assert history[-1]["total"] == round(25.0239 + 9.9861, 4)
        assert data["realtime"] == history[-1]

    def test_history_trimmed_to_lookback(self):
        with patch.object(sb.eastmoney_client, "get_json", side_effect=_fake_get_json):
            text = sb.SouthboundFlowTool().execute(lookback_days=1)
        payload = json.loads(text)
        history = payload["data"]["history"]
        assert len(history) == 1
        assert history[0]["trade_date"] == "2026-09-17"

    def test_lookback_clamped_to_ceiling(self):
        with patch.object(sb.eastmoney_client, "get_json", side_effect=_fake_get_json):
            text = sb.SouthboundFlowTool().execute(lookback_days=99999)
        payload = json.loads(text)
        assert payload["data"]["lookback_days"] == sb._MAX_LOOKBACK_DAYS

    def test_one_channel_missing_leaves_none_and_partial_total(self):
        def fake(url: str, *, params: dict):
            if '"002"' in params["filter"]:
                return _em_rows({"2026-09-17": 25.0239})
            return {"result": {"data": []}}

        with patch.object(sb.eastmoney_client, "get_json", side_effect=fake):
            text = sb.SouthboundFlowTool().execute(lookback_days=5)
        row = json.loads(text)["data"]["history"][-1]
        assert row["shanghai_connect"] == 25.0239
        assert row["shenzhen_connect"] is None
        assert row["total"] == 25.0239


class TestHkexFallback:
    _HKEX_JS = (
        "tabData = ["
        '{"id":0,"date":"2026-09-17","market":"SSE Southbound","content":['
        '{"table":{"schema":[["Total Turnover","Buy Turnover","Sell Turnover"]],'
        '"tr":[{"td":[["50,272.91"]]},{"td":[["26,387.65"]]},'
        '{"td":[["23,885.26"]]}]}},'
        # Decoy: the top-10 stocks table also carries Buy/Sell Turnover
        # columns, one multi-cell row per stock — the parser must skip it
        # (regression for the live-payload bug where it overwrote the net
        # with (rank4 − rank5)/100 = −0.01).
        '{"table":{"schema":[["Rank","Stock Code","Stock Name",'
        '"Buy Turnover","Sell Turnover","Total Turnover"]],'
        '"tr":[{"td":[["1","02513","Z.AI","2,057,313,700",'
        '"1,369,978,206","3,427,291,906"]]},'
        '{"td":[["2","06869","YOFC","1,150,696,524",'
        '"1,290,739,110","2,441,435,634"]]}]}}]},'
        '{"id":1,"date":"2026-09-17","market":"SZSE Southbound","content":['
        '{"table":{"schema":[["Total Turnover","Buy Turnover","Sell Turnover"]],'
        '"tr":[{"td":[["27,737.22"]]},{"td":[["14,298.99"]]},'
        '{"td":[["13,438.23"]]}]}}]}'
        "];"
    )

    def _mock_response(self, status: int = 200, text: str = "") -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.text = text
        return response

    def test_eastmoney_failure_falls_back_to_hkex_snapshot(self):
        with (
            patch.object(
                sb.eastmoney_client, "get_json", side_effect=RuntimeError("HTTP 429")
            ),
            patch.object(
                sb.requests, "get", return_value=self._mock_response(200, self._HKEX_JS)
            ),
        ):
            text = sb.SouthboundFlowTool().execute(lookback_days=5)

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "hkex"
        assert "HKEX official daily statistics" in payload["warnings"][0]
        assert "HTTP 429" in payload["warnings"][0]

        snapshot = payload["data"]["realtime"]
        assert snapshot["trade_date"] == "2026-09-17"
        # (26,387.65 − 23,885.26) / 100 = 25.0239 亿 HKD
        assert snapshot["shanghai_connect"] == round(2502.39 / 100, 4)
        assert snapshot["shenzhen_connect"] == round(860.76 / 100, 4)
        assert payload["data"]["history"] == [snapshot]

    def test_eastmoney_empty_rows_also_falls_back(self):
        empty = {"result": {"data": []}}
        with (
            patch.object(sb.eastmoney_client, "get_json", return_value=empty),
            patch.object(
                sb.requests, "get", return_value=self._mock_response(200, self._HKEX_JS)
            ),
        ):
            text = sb.SouthboundFlowTool().execute(lookback_days=5)
        payload = json.loads(text)
        assert payload["source"] == "hkex"
        assert "returned no rows" in payload["warnings"][0]

    def test_hkex_walks_back_past_404(self):
        responses = [
            self._mock_response(404),
            self._mock_response(200, self._HKEX_JS),
        ]
        with (
            patch.object(
                sb.eastmoney_client, "get_json", side_effect=RuntimeError("down")
            ),
            patch.object(sb.requests, "get", side_effect=responses) as get,
        ):
            text = sb.SouthboundFlowTool().execute(lookback_days=5)
        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "hkex"
        assert get.call_count == 2

    def test_both_sources_down_returns_error_envelope(self):
        with (
            patch.object(
                sb.eastmoney_client, "get_json", side_effect=RuntimeError("HTTP 500")
            ),
            patch.object(
                sb.requests, "get", side_effect=sb.requests.RequestException("dns")
            ),
        ):
            text = sb.SouthboundFlowTool().execute(lookback_days=5)
        payload = json.loads(text)
        assert payload["ok"] is False
        assert "eastmoney datacenter" in payload["error"]
        assert "HKEX" in payload["error"]


class TestHkexParser:
    def test_missing_southbound_sections_returns_none(self):
        js = (
            "tabData = ["
            '{"date":"2026-09-17","market":"SSE Northbound","content":['
            '{"table":{"schema":[["Total Turnover"]],"tr":[{"td":[["1.0"]]}]}}]}'
            "];"
        )
        assert sb._parse_hkex_report(js) is None

    def test_garbage_body_returns_none(self):
        assert sb._parse_hkex_report("<html>not js</html>") is None


class TestToolMetadata:
    def test_name_and_params(self):
        tool = sb.SouthboundFlowTool()
        assert tool.name == "get_southbound_flow"
        assert tool.is_readonly is True
        assert tool.parameters["required"] == []
        assert "lookback_days" in tool.parameters["properties"]

    def test_description_scopes_to_market_wide_southbound(self):
        desc = sb.SouthboundFlowTool().description
        assert desc.startswith("MARKET-WIDE Southbound")
        assert "南向" in desc
        # Disambiguates against the per-stock tool and the northbound one.
        assert "get_fund_flow" in desc
        assert "NOT per-stock" in desc
        assert "get_northbound_flow" in desc
        assert "get_southbound_flow(lookback_days=10)" in desc
