"""Regression tests for agent tools argument coercion and validation safety against None, empty, and non-finite values."""

import json
import math
import pytest

from tools.northbound_tool import _clamp_lookback
from tools.block_trades_tool import _clamp_days as block_trades_clamp_days
from tools.fred_macro_tool import _clamp_limit as fred_clamp_limit
from tools.iwencai_tool import _coerce_limit as iwencai_coerce_limit
from tools.lockup_expiry_tool import _clamp_horizon as lockup_clamp_horizon
from tools.margin_trading_tool import _clamp_days as margin_clamp_days
from tools.research_reports_tool import _clamp_limit as research_clamp_limit
from tools.sec_filings_tool import _clamp_limit as sec_clamp_limit
from tools.shareholder_count_tool import _clamp_periods as shareholder_clamp_periods
from tools.stock_news_tool import _clamp_limit as stock_news_clamp_limit
from tools.symbol_search_tool import _clamp_limit as symbol_clamp_limit
from tools.options_chain_tool import _coerce_expiration
from tools.alpha_zoo_tool import run_alpha_zoo
from tools.trading_connector_tool import _int_or_none, _num_or_none
from tools.options_pricing_tool import OptionsPricingTool
from tools.web_search_tool import WebSearchTool
from tools.session_search_tool import SessionSearchTool
from tools.qveris_tool import QVerisSearchTool, QVerisExecuteTool
from tools.report_audit_tool import ReportAuditTool
from tools.shadow_account_tool import ExtractShadowStrategyTool, ScanShadowSignalsTool


def test_clamp_funcs_overflow_safety():
    """Verify that integer clamp/coerce helpers handle infinity without OverflowError."""
    assert _clamp_lookback(float("inf")) == 30
    assert _clamp_lookback(float("-inf")) == 30
    assert block_trades_clamp_days(float("inf")) == 30
    assert fred_clamp_limit(float("inf")) == 2000
    assert iwencai_coerce_limit(float("inf")) == 20
    assert lockup_clamp_horizon(float("inf")) == 90
    assert margin_clamp_days(float("inf")) == 30
    assert research_clamp_limit(float("inf")) == 20
    assert sec_clamp_limit(float("inf")) == 20
    assert shareholder_clamp_periods(float("inf")) == 24
    assert stock_news_clamp_limit(float("inf")) == 20
    assert symbol_clamp_limit(float("inf")) == 10
    assert _coerce_expiration(float("inf")) is None
    assert _coerce_expiration(float("-inf")) is None


def test_trading_connector_helpers_robustness():
    """Verify _int_or_none and _num_or_none handle non-finite, bad types, and strings cleanly."""
    assert _int_or_none(float("inf")) is None
    assert _int_or_none(float("-inf")) is None
    assert _int_or_none(float("nan")) is None
    assert _int_or_none({}) is None
    assert _int_or_none([]) is None
    assert _int_or_none("invalid") is None
    assert _num_or_none({}) is None
    assert _num_or_none([]) is None
    assert _num_or_none("invalid") is None


def test_alpha_zoo_tool_limit_overflow():
    """Verify run_alpha_zoo handles float('inf') for limit without uncaught OverflowError."""
    res = run_alpha_zoo(action="list_alphas", limit=float("inf"))
    assert res["status"] == "error"
    assert "limit must be int" in res["error"]


def test_options_pricing_tool_bad_kwargs():
    """Verify OptionsPricingTool handles None, empty strings, dicts, lists, and missing args cleanly."""
    tool = OptionsPricingTool()
    for bad_spot in [None, "", {}, []]:
        res = json.loads(tool.execute(spot=bad_spot, strike=100, expiry_days=30, volatility=0.2, option_type="call"))
        assert res["status"] == "error"
        assert "invalid or missing input argument" in res["error"] or "error" in res


def test_web_search_tool_query_and_max_results():
    """Verify WebSearchTool handles invalid query and non-finite max_results cleanly."""
    tool = WebSearchTool()
    # Invalid query
    res = json.loads(tool.execute(query=None))
    assert res["status"] == "error"
    assert "query is mandatory" in res["error"]

    res2 = json.loads(tool.execute(query=""))
    assert res2["status"] == "error"

    # Non-finite or invalid max_results should not crash execute
    # Note: query may fail upstream network, but max_results parsing shouldn't raise OverflowError/TypeError/ValueError
    for bad_max in [None, "", float("nan"), float("inf"), {}, []]:
        res_max = tool.execute(query="test_query", max_results=bad_max)
        assert isinstance(res_max, str)


def test_session_search_tool_max_results():
    """Verify SessionSearchTool handles non-finite and bad max_results values."""
    tool = SessionSearchTool()
    for bad_max in [None, "", float("nan"), float("inf"), {}, []]:
        res = json.loads(tool.execute(query="test_session", max_results=bad_max))
        assert res["status"] in ("ok", "error")


def test_qveris_tool_limit_safety():
    """Verify QVerisSearchTool and QVerisExecuteTool handle bad limit and max_response_size."""
    search_tool = QVerisSearchTool()
    exec_tool = QVerisExecuteTool()

    # Search tool with non-finite limit
    res_search = search_tool.execute(query="test", limit=float("inf"))
    assert isinstance(res_search, str)

    # Execute tool with non-finite max_response_size
    res_exec = exec_tool.execute(tool_id="test_tool", parameters={}, max_response_size=float("inf"))
    assert isinstance(res_exec, str)


def test_report_audit_tool_ratio_and_seed():
    """Verify ReportAuditTool handles invalid ratio and seed parameters."""
    tool = ReportAuditTool()
    res1 = json.loads(tool.execute(command="extract", report_text="sample text", ratio="invalid"))
    assert res1["status"] == "error"
    assert "invalid ratio" in res1["error"]

    res2 = json.loads(tool.execute(command="extract", report_text="sample text", seed=float("inf")))
    assert res2["status"] == "error"
    assert "invalid seed" in res2["error"]


def test_shadow_account_tool_integer_arguments():
    """Verify ShadowAccountTool helpers handle non-finite integers without crashing."""
    extract_tool = ExtractShadowStrategyTool()
    res1 = json.loads(extract_tool.execute(journal_path="nonexistent.csv", min_support=float("inf")))
    assert res1["status"] == "error"

    scan_tool = ScanShadowSignalsTool()
    res2 = json.loads(scan_tool.execute(shadow_id="nonexistent_id", per_market=float("inf")))
    assert res2["status"] == "error"
