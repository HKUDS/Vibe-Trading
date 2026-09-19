"""Tests for fund_nav_tool: availability gating, resolution, parsing, batching.

All MCP transport is mocked — no test reaches a live Gildata endpoint. The
tool imports ``_call_tool`` from the loader and ``resolve_vendor_code`` from
gildata_codes; both are patched on the ``fund_nav_tool`` module namespace,
except where the real resolver is exercised against a stubbed transport.
"""

from __future__ import annotations

import json
from typing import Any

from src.tools import fund_nav_tool as fnt
from src.tools.fund_nav_tool import GildataFundNavTool


def _mcp_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _tool_entry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The results[0] entry shape the loader's _call_tool returns."""
    return {"api_name": "基金净值", "columns": {}, "rows": rows}


_NAV_ROWS = [
    # Newest-first, exactly as the vendor sends them.
    {
        "enddate": "2024-01-11", "fundname": "易方达消费行业股票",
        "fundcode": "110022", "unitnv": 3.29, "accumulatedunitnv": 3.29,
        "unitnvrestored": 3.29, "nvdailygrowthrate": 0.6116,
    },
    {
        "enddate": "2024-01-10", "fundname": "易方达消费行业股票",
        "fundcode": "110022", "unitnv": 3.27, "accumulatedunitnv": 3.27,
        "unitnvrestored": 3.27, "nvdailygrowthrate": 0.3683,
    },
]


class TestAvailability:
    """check_available reflects only GILDATA_TOKEN."""

    def test_unavailable_without_token(self, monkeypatch):
        monkeypatch.delenv("GILDATA_TOKEN", raising=False)
        assert GildataFundNavTool.check_available() is False

    def test_available_with_token(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        assert GildataFundNavTool.check_available() is True

    def test_metadata(self):
        assert GildataFundNavTool.name == "get_fund_nav"
        assert GildataFundNavTool().is_readonly is True


class TestNormalizeFundCode:
    """Project codes map onto the vendor's NNNNNN.OF ref."""

    def test_bare_digits_get_of_suffix(self):
        assert fnt._normalize_fund_code("110022") == "110022.OF"

    def test_of_suffix_uppercased(self):
        assert fnt._normalize_fund_code("110022.of") == "110022.OF"

    def test_exchange_listed_rejected(self):
        # OHLCV instruments — served by get_market_data, not this tool.
        assert fnt._normalize_fund_code("510300.SH") is None
        assert fnt._normalize_fund_code("159915.SZ") is None

    def test_garbage_rejected(self):
        assert fnt._normalize_fund_code("AAPL") is None
        assert fnt._normalize_fund_code("") is None
        assert fnt._normalize_fund_code(12345) is None


class TestExecute:
    """End-to-end execute with the MCP transport mocked."""

    def _patch_transport(self, monkeypatch, side_effect):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        from backtest.loaders import gildata_codes
        gildata_codes.reset_code_cache()
        monkeypatch.setattr(fnt, "_call_tool", side_effect)
        monkeypatch.setattr(fnt, "_recall_candidates", side_effect)

    def test_missing_token_error(self, monkeypatch):
        monkeypatch.delenv("GILDATA_TOKEN", raising=False)
        out = json.loads(GildataFundNavTool().execute(funds=["110022"]))
        assert out["ok"] is False
        assert "GILDATA_TOKEN" in out["error"]

    def test_happy_path(self, monkeypatch):
        def transport(tool, args):
            if tool == "ParamCandidateRecall":
                return {"candidates": [
                    {"caption": "易方达消费行业股票", "code": "11363",
                     "ref_code": "110022.OF"},
                ]}
            assert tool == "NetFundUnitValueReport"
            assert args["fundObject"] == ["11363"]
            assert args["statisticalPeriod"] == 0
            assert args.get("beginDate") == "2024-01-01"
            return _tool_entry(_NAV_ROWS)

        self._patch_transport(monkeypatch, transport)
        out = json.loads(GildataFundNavTool().execute(
            funds=["110022"], start_date="2024-01-01"))
        assert out["ok"] is True and out["source"] == "gildata"
        fund = out["funds"]["110022.OF"]
        assert fund["ok"] is True
        assert fund["fund_name"] == "易方达消费行业股票"
        assert fund["count"] == 2
        # Ascending order; served field names mapped off the vendor's.
        assert [r["date"] for r in fund["rows"]] == ["2024-01-10", "2024-01-11"]
        row = fund["rows"][0]
        assert row["unit_nav"] == 3.27
        assert row["accumulated_nav"] == 3.27
        assert row["adjusted_nav"] == 3.27
        assert row["daily_growth_pct"] == 0.3683

    def test_unresolved_fund_reports_error_not_abort(self, monkeypatch):
        def transport(tool, args):
            if tool == "ParamCandidateRecall":
                return {"candidates": [
                    {"caption": "别的基金", "code": "1", "ref_code": "000001.OF"},
                ]}
            return _tool_entry(_NAV_ROWS)

        self._patch_transport(monkeypatch, transport)
        out = json.loads(GildataFundNavTool().execute(
            funds=["110022", "000198.OF"]))
        # 110022 resolves and serves; 000198 does not resolve and reports.
        assert out["ok"] is True
        assert out["funds"]["110022.OF"]["ok"] is True
        assert out["funds"]["000198.OF"]["ok"] is False

    def test_exchange_listed_code_reports_error(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda tool, args: _tool_entry([]))
        out = json.loads(GildataFundNavTool().execute(
            funds=["510300.SH", "110022"]))
        assert out["ok"] is True
        assert out["funds"]["510300.SH"]["ok"] is False

    def test_all_invalid_codes_rejected_upfront(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        out = json.loads(GildataFundNavTool().execute(funds=["AAPL", "00700.HK"]))
        assert out["ok"] is False

    def test_limit_keeps_most_recent_rows(self, monkeypatch):
        rows = [
            {"enddate": f"2024-01-{day:02d}", "fundname": "F",
             "unitnv": 1.0, "accumulatedunitnv": 1.0,
             "unitnvrestored": 1.0, "nvdailygrowthrate": 0.0}
            for day in range(1, 11)
        ]
        def transport(tool, args):
            if tool == "ParamCandidateRecall":
                return {"candidates": [
                    {"caption": "F", "code": "11363", "ref_code": "110022.OF"}]}
            return _tool_entry(rows)

        self._patch_transport(monkeypatch, transport)
        out = json.loads(GildataFundNavTool().execute(funds=["110022"], limit=3))
        fund = out["funds"]["110022.OF"]
        assert fund["count"] == 3
        assert fund["rows"][-1]["date"] == "2024-01-10"  # newest kept

    def test_empty_window_reports_error(self, monkeypatch):
        def transport(tool, args):
            if tool == "ParamCandidateRecall":
                return {"candidates": [
                    {"caption": "F", "code": "11363", "ref_code": "110022.OF"}]}
            return _tool_entry([])

        self._patch_transport(monkeypatch, transport)
        out = json.loads(GildataFundNavTool().execute(funds=["110022"]))
        assert out["funds"]["110022.OF"]["ok"] is False
        assert "no NAV rows" in out["funds"]["110022.OF"]["error"]


class TestGroundingEvidence:
    """NAV figures must register as price evidence (live-measured regression).

    A fund's NAV is its dated price observation; before the alias entries the
    verifier left every unit_nav value unmatched, the answer gate rejected the
    run twice, and the final answer shipped degraded with figures redacted.
    """

    def test_nav_leaves_map_to_price_fields(self):
        from src.agent.grounding.evidence import _price_field_for_path

        for leaf in ("unit_nav", "accumulated_nav", "adjusted_nav"):
            assert _price_field_for_path(f"funds.110022.OF.rows[0].{leaf}") == "price"

    def test_get_fund_nav_result_verifies_against_price_evidence(self, tmp_path):
        from src.agent.grounding.ledger import GroundingLedger

        ledger = GroundingLedger(
            run_dir=tmp_path,
            user_message="查易方达消费行业基金最新净值",
        )
        payload = {
            "ok": True, "source": "gildata",
            "funds": {"110022.OF": {"ok": True, "fund_name": "易方达消费行业股票",
                "rows": [{"date": "2026-09-17", "unit_nav": 1.4794,
                          "accumulated_nav": 1.4794, "adjusted_nav": 1.4794,
                          "daily_growth_pct": -0.6314}]}},
        }
        ledger._ingest_generic_numeric(
            "get_fund_nav", {"funds": ["110022"]}, payload, call_id="nav_call",
        )
        comparable = ledger._comparable_price_records()
        nav_values = [r.value for r in comparable if r.field == "price"]
        assert 1.4794 in nav_values


class TestIdentityGateBypass:
    """The funds argument must not enroll the tool in the identity gate."""

    def test_argument_key_outside_gate_regime(self):
        # _SYMBOL_ARGUMENT_KEYS (codes/symbols/tickers/...) marks a tool as
        # market-instrument-sensitive and demands a search_symbol lock the
        # resolver cannot obtain for off-exchange codes. `funds` must stay
        # outside that set, or the tool becomes uncallable in the agent loop
        # (measured live: identity_required / identity_conflict loop).
        from src.agent.grounding.identity import _SYMBOL_ARGUMENT_KEYS

        param_names = set(GildataFundNavTool.parameters["properties"])
        assert param_names & set(_SYMBOL_ARGUMENT_KEYS) == set()
        assert "funds" in param_names
