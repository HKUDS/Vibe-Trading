"""Screening preserves vendor ranking, periods and existing grounding contracts."""
import copy
import json
from unittest.mock import Mock, patch

import pytest

from src.agent.grounding import GroundingLedger
from src.tools import gildata_stock_selection_tool as ss
from src.tools import gildata_srv


@pytest.fixture
def vendor(monkeypatch):
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    call = Mock(return_value=[{
        "api_name": "智能选股",
        "columns": {"secucode": "证券代码", "secuabbr": "证券简称", "id": "证券编码",
                    "rev_a": "营业收入（亿元）<[报告期]:2022-12-31><[单位]:亿元>",
                    "rev_b": "营业收入（万元）<[报告期]:2025-12-31><[单位]:万元>",
                    "weight": "指数成分股权重（%）<[截止日期]:NewestTradingDay()>"},
        "rows": [{"secucode": "600000.SH", "secuabbr": "甲", "id": "000001", "innercode": 77,
                  "rev_a": 12.34, "rev_b": 567.89, "weight": 3.4},
                 {"secucode": "000001.SZ", "secuabbr": "乙", "id": "000002", "innercode": 88,
                  "rev_a": None, "rev_b": 432.1, "weight": 2.3}],
    }])
    monkeypatch.setattr(ss, "call_srv_tool_results", call)
    return call


def execute(**kwargs):
    return json.loads(ss.GildataStockSelectionTool().execute(**{"query": "完整筛选问题", **kwargs}))


@pytest.mark.parametrize("token", ["", " ", "your-gildata-token"])
def test_unconfigured_not_available_or_called(vendor, monkeypatch, token):
    monkeypatch.setenv("GILDATA_TOKEN", token)
    assert not ss.GildataStockSelectionTool.check_available()
    assert execute()["error_type"] == "not_configured"
    vendor.assert_not_called()


@pytest.mark.parametrize("query", [None, " ", 123, "x" * 4001])
def test_invalid_query_not_sent(vendor, query):
    assert execute(query=query)["error_type"] == "invalid_query"
    vendor.assert_not_called()


@pytest.mark.parametrize("topk", [0, -2, True, "10", 2.5])
def test_invalid_topk_not_sent(vendor, topk):
    assert execute(topk=topk)["error_type"] == "invalid_topk"
    vendor.assert_not_called()


@pytest.mark.parametrize("topk", [None, 7, -1])
def test_one_unsplit_question_and_optional_vendor_topk(vendor, topk):
    q = " 指数权重最高的股票及两个报告期的营收 "
    assert execute(query=q, topk=topk)["ok"]
    vendor.assert_called_once_with("SmartStockSelection", q.strip(), **({"topk": topk} if topk is not None else {}))


def test_periods_order_nulls_and_identifiers_preserved(vendor):
    original = copy.deepcopy(vendor.return_value)
    table = execute()["data"]["tables"][0]
    assert table["columns"] == original[0]["columns"]
    assert [r["secucode"] for r in table["rows"]] == ["600000.SH", "000001.SZ"]
    row = table["rows"][0]
    assert row["rev_a"]["amount"] == 1234000000
    assert row["rev_b"]["display"] == "567.89万元"
    assert row["weight"]["percent"] == 3.4
    assert row["id"] == "000001" and row["innercode"] == "77"
    assert table["rows"][1]["rev_a"] is None
    assert vendor.return_value == original


def test_real_ledger_checks_each_period_and_stock_path(vendor, tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="筛选股票及历史营业收入")
    ledger.ingest_tool_result(tool_name="gildata_stock_selection", arguments={"query": "完整筛选问题"},
                              result=json.dumps(execute()), call_id="screen1", success=True)
    def check(field):
        return ledger.validate_final_answer(
            "营业收入12.34亿元。\n```figures\n"
            f"12.34亿元 | observed | 营业收入 | screen1::data.tables[0].rows[0].{field}.amount\n```")
    assert check("rev_a").valid
    assert not check("rev_b").valid
    assert not any(r.field.endswith((".innercode", ".id")) for r in ledger._evidence)


def test_errors_empty_and_unsupported_responses(vendor):
    vendor.side_effect = RuntimeError("secret-token")
    result = execute()
    assert result["error_type"] == "service_error" and "secret-token" not in json.dumps(result)
    vendor.side_effect = None
    vendor.return_value = []
    assert execute()["has_data"] is False
    vendor.return_value = [{"api_name": "智能选股", "table_markdown": "unstructured"}]
    assert execute()["error_type"] == "unsupported_data"


def test_transport_includes_topk_only_when_supplied(vendor):
    raw = {"result": {"content": [{"type": "text", "text": json.dumps({"code": 0, "results": vendor.return_value})}]}}
    with patch.object(gildata_srv, "throttled_post_json", return_value=raw) as post:
        for kwargs in [{}, {"topk": 7}, {"topk": -1}]:
            gildata_srv.call_srv_tool_results("SmartStockSelection", "完整筛选问题", **kwargs)
            assert post.call_args.kwargs["json_body"]["params"]["arguments"] == {"query": "完整筛选问题", **kwargs}


def test_discovered_alongside_iwencai(monkeypatch):
    from src import tools
    from src.tools.iwencai_tool import IWenCaiSearchTool
    monkeypatch.setattr(tools, "_SUBCLASSES_CACHE", None)
    classes = tools._discover_subclasses()
    assert ss.GildataStockSelectionTool in classes and IWenCaiSearchTool in classes
