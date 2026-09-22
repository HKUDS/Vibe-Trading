"""The datacenter's rejected-query and empty-result answers look alike (#1489, #1501, #1502).

Both are HTTP 200 with ``success: false``. A rejection (a retired report or
column, code 9501) read as an empty result tells the caller "this stock has no
data" when the query is stale. Every datacenter caller shares one rule, pinned
here from both sides, and the three tools that used to swallow a rejection are
checked against it.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backtest.loaders import eastmoney_client
from backtest.loaders.eastmoney_client import datacenter_rejection
from src.tools import block_trades_tool
from src.tools.financial_statements_tool import FinancialStatementsTool
from src.tools.margin_trading_tool import MarginTradingTool

REJECTED = {"success": False, "code": 9501, "message": "RPT_OLD报表配置不存在", "result": None}
EMPTY = {"success": False, "code": 9201, "message": "返回数据为空", "result": None}


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True, "result": {"data": [{"a": 1}]}},
        EMPTY,
        {"success": False, "message": "返回数据为空", "result": None},  # no code at all
        {"result": {"data": []}},  # no success flag
        None,
    ],
)
def test_accepted_and_empty_answers_are_not_rejections(payload):
    assert datacenter_rejection(payload) is None


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        (REJECTED, "code=9501 message=RPT_OLD报表配置不存在"),
        ({"success": False, "code": 9501, "message": "返回数据为空"}, "code=9501"),
        ({"success": False, "code": 9201, "message": "COL返回字段不存在"}, "COL返回字段不存在"),
        ({"success": False, "code": 9501, "message": ""}, "request rejected without a message"),
        ({"success": False, "message": "参数错误"}, "参数错误"),
    ],
)
def test_rejections_are_named(payload, fragment):
    rejection = datacenter_rejection(payload)
    assert rejection is not None and fragment in rejection


def test_block_trades_reports_a_rejection_instead_of_zero_deals():
    with patch.object(block_trades_tool, "get_json", return_value=REJECTED):
        out = json.loads(block_trades_tool.BlockTradesTool().execute(code="600519.SH"))
    assert out["ok"] is False
    assert "9501" in out["error"]


def test_block_trades_still_reads_an_empty_window_as_zero_deals():
    with patch.object(block_trades_tool, "get_json", return_value=EMPTY):
        out = json.loads(block_trades_tool.BlockTradesTool().execute(code="600519.SH"))
    assert out["ok"] is True
    assert out["data"]["count"] == 0


def test_margin_trading_names_the_rejection_when_it_falls_back():
    fallback = {"code": "600519", "ts_code": "600519.SH", "rows": [{"trade_date": "2024-01-03"}]}
    with patch.object(eastmoney_client, "get_json", return_value=REJECTED), patch(
        "src.tools.margin_trading_tool.tushare_fallbacks.fetch_margin_trading", return_value=fallback
    ):
        out = json.loads(MarginTradingTool().execute(code="600519.SH", days=5))
    assert out["source"] == "tushare"
    assert "rejected" in out["warnings"][0] and "9501" in out["warnings"][0]
    assert "no rows" not in out["warnings"][0]


def test_margin_trading_error_names_the_rejection_when_the_fallback_fails():
    with patch.object(eastmoney_client, "get_json", return_value=REJECTED), patch(
        "src.tools.margin_trading_tool.tushare_fallbacks.fetch_margin_trading",
        side_effect=RuntimeError("no tushare token"),
    ):
        out = json.loads(MarginTradingTool().execute(code="600519.SH", days=5))
    assert out["ok"] is False
    assert "9501" in out["error"]


def test_financial_statements_report_a_rejection_instead_of_no_periods():
    with patch("src.tools.financial_statements_tool.resolve_secid", return_value="1.600519"), patch(
        "src.tools.financial_statements_tool.get_json", return_value=REJECTED
    ):
        out = json.loads(
            FinancialStatementsTool().execute(code="600519.SH", statement="balance", period="annual")
        )
    assert "9501" in json.dumps(out, ensure_ascii=False)
    assert out.get("data", {}).get("600519.SH", {}).get("periods") in (None, [])
