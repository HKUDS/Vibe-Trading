"""Boundary regressions for the newly integrated vendor research surfaces."""
import json
import time

import pytest

from backtest.loaders import gildata_codes as codes
from backtest.loaders.gildata_loader import _is_cn_index, _response_results
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.fund_nav_tool import GildataFundNavTool
from src.tools.gildata_research_tools import _envelope
from src.tools.gildata_srv import _coerce_numeric_strings


@pytest.mark.parametrize("outer", [None, {}, {"result": []}, {"result": {"isError": True}}, {"result": {"content": [{"text": '{"code":false,"results":[]}'}]}}, {"result": {"content": [{"text": '{"code":0,"results":[null]}'}]}}, {"result": {"content": [{"text": '{"code":0,"results":[{"value":NaN}]}'}]}}])
def test_invalid_envelopes_are_never_successful_empty_reads(outer):
    with pytest.raises((ValueError, RuntimeError)):
        _response_results(outer)


def test_broker_error_does_not_echo_token():
    with pytest.raises(RuntimeError) as error:
        _response_results({"message": "credential secret-123"})
    assert "secret-123" not in str(error.value)


@pytest.mark.parametrize("symbol", ["000300.SH", "000300.SS", "399006.SZ", "899050.BJ"])
def test_every_shared_cn_index_shape_uses_index_quotes(symbol):
    assert _is_cn_index(symbol)
    assert not _is_cn_index("000001.SZ")


def test_conflicting_exact_recall_matches_do_not_pick_first(tmp_path, monkeypatch):
    monkeypatch.setattr(codes, "_cache_path", lambda: tmp_path / "codes.json")
    codes.reset_code_cache()
    response = {"candidates": [{"ref_code": "00700.HK", "code": value} for value in ["1", "2"]]}
    assert codes.resolve_vendor_code("hk_equity", "00700.HK", lambda *args: response) is None


@pytest.mark.parametrize("timestamp", ["bad", None, True, float("inf"), time.time() + 100000])
def test_corrupt_cache_age_triggers_fresh_recall(tmp_path, monkeypatch, timestamp):
    path = tmp_path / "codes.json"
    monkeypatch.setattr(codes, "_cache_path", lambda: path)
    codes.reset_code_cache()
    path.write_text(json.dumps({"00700.HK": {"kind": "hk_equity", "code": "wrong", "resolved_at": timestamp}}))
    assert codes.resolve_vendor_code("hk_equity", "00700.HK", lambda *args: {"candidates": [{"ref_code": "00700.HK", "code": "correct"}]}) == "correct"
    assert json.loads(path.read_text())["00700.HK"]["code"] == "correct"


def test_research_caps_whole_records_and_reports_omission():
    payload = {"api_names": ["Announcements"], "rows": [{"title": str(i), "excerpt": "x" * 1000} for i in range(200)]}
    text = _envelope("AnnouncementData", "Recent filings", payload, 200)
    assert len(text) <= TOOL_RESULT_LIMIT
    result = json.loads(text)
    assert result["truncated"] and result["count"] < 200
    assert all(len(row["excerpt"]) == 1000 for row in result["rows"])
    assert result["returned_by_vendor"] == 200
    payload["rows"] = [{"excerpt": "x" * 20000}]
    assert json.loads(_envelope("AnnouncementData", "filings", payload, 200))["ok"] is False


def test_nav_budget_keeps_complete_recent_records(monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_GILDATA_FEATURES", "fund_nav")
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    monkeypatch.setattr(GildataFundNavTool, "_fetch_one", lambda *args: {"ok": True, "fund_name": "Fund", "rows": [{"date": f"row-{i}", "unit_nav": 1.12, "adjusted_nav": 2.34} for i in range(2000)], "count": 2000, "returned_by_vendor": 2000})
    text = GildataFundNavTool().execute(funds=["110022"])
    assert len(text) <= TOOL_RESULT_LIMIT
    fund = json.loads(text)["funds"]["110022.OF"]
    assert fund["truncated"] and fund["count"] < 2000
    assert fund["rows"][-1]["date"] == "row-1999"


@pytest.mark.parametrize("window", [{"start_date": "yesterday"}, {"start_date": "2026-10-13", "end_date": "2026-10-12"}])
def test_invalid_nav_window_fails_before_vendor_call(monkeypatch, window):
    monkeypatch.setenv("VIBE_TRADING_GILDATA_FEATURES", "fund_nav")
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    monkeypatch.setattr(GildataFundNavTool, "_fetch_one", lambda *args: pytest.fail("invalid window reached vendor"))
    assert json.loads(GildataFundNavTool().execute(funds=["110022"], **window))["ok"] is False


def test_macro_observations_ground_with_explicit_refs_without_widening_price_gate(tmp_path):
    from evals.grounding.ledger import GroundingLedger

    rows = [{"value": "5.4", "indicatorcode": 10011, "unit": "%", "date": "2026-01-31"}]
    _coerce_numeric_strings(rows)
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Read the macro observation")
    ledger.ingest_tool_result(tool_name="get_cn_macro_series", arguments={"query": "GDP"}, result=json.dumps({"ok": True, "rows": rows}), call_id="macro_call", success=True)
    def check(value):
        return ledger.validate_final_answer(f"Observed growth: {value}%.\n```figures\n{value}% | observed | Growth | macro_call::rows[0].value\n```")
    assert check("5.4").valid
    assert not check("6.4").valid


def test_old_token_and_individual_opt_ins_across_agent_and_mcp(monkeypatch):
    import asyncio

    import mcp_server
    from src.config.accessor import reset_env_config
    from src.tools import build_registry, gildata_research_tools

    features = {
        "fund_nav": ("get_fund_nav", {"funds": ["110022"]}),
        "macro_series": ("get_cn_macro_series", {"query": "GDP"}),
        "announcements": ("get_cn_announcements", {"query": "dividend"}),
        "broker_reports": ("search_broker_reports", {"query": "earnings"}),
    }

    def unexpected(*args, **kwargs):
        pytest.fail("Disabled feature reached vendor lookup")

    monkeypatch.setattr(GildataFundNavTool, "_fetch_one", unexpected)
    monkeypatch.setattr(gildata_research_tools, "call_srv_tool", unexpected)
    monkeypatch.setenv("GILDATA_TOKEN", "existing-token")
    key = "VIBE_TRADING_GILDATA_FEATURES"
    monkeypatch.setenv(key, ",".join(features))
    reset_env_config()
    retained = build_registry()
    assert all(retained.get(name) for name, _ in features.values())
    monkeypatch.setattr(mcp_server, "_registry", retained)
    for selected in ["", *features]:
        monkeypatch.setenv(key, selected)
        reset_env_config()  # Settings PUT also refreshes the process config.
        fresh = build_registry()
        for feature, (name, params) in features.items():
            assert (fresh.get(name) is not None) == (feature == selected)
            if feature != selected:
                assert json.loads(retained.execute(name, params))["ok"] is False
                reply = asyncio.run(mcp_server.mcp.call_tool(name, params))
                assert json.loads(reply.content[0].text)["ok"] is False
