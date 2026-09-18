"""Tests for the gildata srv-tool research wrappers.

All MCP transport is mocked at ``gildata_research_tools.call_srv_tool`` —
no test reaches the live vendor.
"""

from __future__ import annotations

import json



from src.tools import gildata_research_tools as grt
from src.tools.gildata_research_tools import (
    GetCnAnnouncementsTool,
    GetCnMacroSeriesTool,
    SearchBrokerReportsTool,
)

TOOLS = [GetCnMacroSeriesTool, GetCnAnnouncementsTool, SearchBrokerReportsTool]


class TestAvailabilityAndMetadata:
    """All three wrappers gate on GILDATA_TOKEN and share plumbing."""

    def test_unavailable_without_token(self, monkeypatch):
        monkeypatch.delenv("GILDATA_TOKEN", raising=False)
        for cls in TOOLS:
            assert cls.check_available() is False

    def test_available_with_token(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        for cls in TOOLS:
            assert cls.check_available() is True

    def test_metadata(self):
        by_name = {cls.name: cls for cls in TOOLS}
        assert by_name["get_cn_macro_series"].vendor_tool == "MacroIndustryData"
        assert by_name["get_cn_announcements"].vendor_tool == "AnnouncementData"
        assert by_name["search_broker_reports"].vendor_tool == "FinancialResearchReport"
        for cls in TOOLS:
            assert cls().is_readonly is True


class TestExecute:
    """Envelope shape, api_names echo, limit, and error paths."""

    def _patch(self, monkeypatch, payload):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        monkeypatch.setattr(grt, "call_srv_tool", lambda tool, query: payload)

    def test_macro_happy_path(self, monkeypatch):
        self._patch(monkeypatch, {
            "api_names": ["EDB取数"],
            "rows": [
                {"indicatorname": "中国:GDP:当期同比", "date": "2024-12-31",
                 "value": "5.4", "unit": "%", "frequency": "季"},
            ],
        })
        out = json.loads(GetCnMacroSeriesTool().execute(
            query="2024年中国GDP同比"))
        assert out["ok"] is True
        assert out["source"] == "gildata"
        assert out["vendor_tool"] == "MacroIndustryData"
        assert out["api_names"] == ["EDB取数"]
        assert out["rows"][0]["value"] == "5.4"
        assert out["count"] == 1

    def test_announcements_rows_and_multiple_api_names(self, monkeypatch):
        self._patch(monkeypatch, {
            "api_names": ["公告库", "公告库"],
            "rows": [
                {"title": "分红公告", "pubtime": "2025-04-03", "highlight": "每10股276.24元"},
                {"title": "年报", "pubtime": "2025-04-02", "highlight": "..."},
            ],
        })
        out = json.loads(GetCnAnnouncementsTool().execute(
            query="贵州茅台2024年年度分红公告"))
        assert out["api_names"] == ["公告库", "公告库"]
        assert out["count"] == 2
        assert out["rows"][0]["highlight"].startswith("每10股")

    def test_limit_caps_rows(self, monkeypatch):
        self._patch(monkeypatch, {
            "api_names": ["研报库"],
            "rows": [{"title": f"r{i}"} for i in range(80)],
        })
        out = json.loads(SearchBrokerReportsTool().execute(
            query="白酒研报", limit=10))
        assert out["count"] == 10 and len(out["rows"]) == 10

    def test_limit_clamped_to_max(self, monkeypatch):
        self._patch(monkeypatch, {"api_names": [], "rows": []})
        out = json.loads(GetCnMacroSeriesTool().execute(
            query="GDP", limit=99999))
        assert out["ok"] is True  # clamped, not rejected

    def test_vendor_error_becomes_ok_false(self, monkeypatch):
        def boom(tool, query):
            raise RuntimeError("gildata srv-tool MacroIndustryData returned error: quota")
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        monkeypatch.setattr(grt, "call_srv_tool", boom)
        out = json.loads(GetCnMacroSeriesTool().execute(query="GDP"))
        assert out["ok"] is False
        assert "quota" in out["error"]

    def test_missing_query_rejected(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        out = json.loads(SearchBrokerReportsTool().execute(query="  "))
        assert out["ok"] is False and "'query'" in out["error"]

    def test_missing_token_rejected(self, monkeypatch):
        monkeypatch.delenv("GILDATA_TOKEN", raising=False)
        out = json.loads(GetCnAnnouncementsTool().execute(query="分红"))
        assert out["ok"] is False and "GILDATA_TOKEN" in out["error"]

    def test_empty_rows_still_ok(self, monkeypatch):
        self._patch(monkeypatch, {"api_names": [], "rows": []})
        out = json.loads(GetCnAnnouncementsTool().execute(query="不存在的东西"))
        assert out["ok"] is True and out["rows"] == []


class TestNumericCoercion:
    """EDB value strings must land in the numeric evidence pool."""

    def test_value_strings_coerced(self):
        from src.tools.gildata_srv import _coerce_numeric_strings

        rows = [{"indicatorname": "GDP同比", "value": "5.4", "unit": "%"},
                {"indicatorname": "CPI同比", "value": "0.2"},
                {"indicatorname": "缺口", "value": "."}]
        _coerce_numeric_strings(rows)
        assert rows[0]["value"] == 5.4
        assert rows[1]["value"] == 0.2
        assert rows[2]["value"] == "."  # non-numeric stays untouched

    def test_coerced_values_land_in_generic_evidence(self, tmp_path):
        from src.agent.grounding.ledger import GroundingLedger

        ledger = GroundingLedger(run_dir=tmp_path, user_message="2024年GDP增速")
        payload = {
            "api_names": ["EDB取数"],
            "rows": [{"indicatorcode": 110252269, "indicatorname": "GDP当季同比",
                      "value": 5.4, "unit": "%", "date": "2024-12-31"}],
        }
        ledger._ingest_generic_numeric(
            "get_cn_macro_series", {"query": "GDP"}, payload, call_id="edb",
        )
        leaves = {r.field: r.value for r in ledger._evidence}
        # The measurement is a numeric leaf now (string "5.4" never indexed).
        assert leaves.get("rows[0].value") == 5.4
        # NOTE: whether percent claims VERIFY against these leaves is an
        # upstream grounding question (the metric pool admits analysis
        # metrics only) — tracked as an upstream issue, not asserted here.
