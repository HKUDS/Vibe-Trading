"""FinQuery's output must work with the existing grounding and delivery contracts."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.result_artifacts import deliver_tool_result
from src.agent.tools import ToolRegistry
from src.tools import gildata_fin_query_tool as fq
from src.tools import gildata_srv
from src.tools.read_file_tool import ReadFileTool


@pytest.fixture
def tables():
    return [{"api_name": "财务", "columns": {"gilcode": "聚源代码", "financevalue": "财务科目数额",
             "unit": "展示单位", "date": "时间", "reportdate": "报告期", "ratio": "研发占比(%)"},
             "rows": [{"gilcode": "600000.SH", "financevalue": 12.34, "unit": "亿元",
                       "date": "2025-03-28", "reportdate": "2024-12-31", "ratio": "23.01%"}]}]


@pytest.fixture
def vendor(monkeypatch, tables):
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    with patch.object(fq, "call_srv_tool_results", return_value=tables) as call:
        yield call


def execute(**kwargs):
    return json.loads(fq.GildataFinQueryTool().execute(query="mixed metrics", **kwargs))


@pytest.mark.parametrize("token", ["", " ", "your-gildata-token"])
def test_no_token_means_unavailable(monkeypatch, token):
    monkeypatch.setenv("GILDATA_TOKEN", token)
    with patch.object(fq, "call_srv_tool_results") as call:
        assert not fq.GildataFinQueryTool.check_available()
        assert not execute()["ok"]
        call.assert_not_called()


@pytest.mark.parametrize("args", [{}, {"query": " "}, {"query": 123}, {"query": "x" * 4001}])
def test_invalid_arguments_do_not_call_service(vendor, args):
    assert not json.loads(fq.GildataFinQueryTool().execute(**args))["ok"]
    vendor.assert_not_called()


def test_one_query_one_numeric_representation_and_no_mutation(vendor, tables):
    original = copy.deepcopy(tables)
    out = execute()
    vendor.assert_called_once_with("FinQuery", "mixed metrics")
    assert out["ok"] and out["has_data"]
    assert "figure_rows" not in out and "evidence" not in out
    row = out["data"]["tables"][0]["rows"][0]
    assert row["financevalue"] == {"amount": 1234000000, "unit": "元", "source_unit": "亿元", "display": "12.34亿元",
                                   "citation": "12.34亿元 | observed | 600000.SH 财务科目数额 | data.tables[0].rows[0].financevalue.amount"}
    assert row["ratio"] == {"percent": 23.01, "unit": "%", "citation": "23.01% | observed | 600000.SH 研发占比(%) | data.tables[0].rows[0].ratio.percent"}
    assert row["date"] == "2025-03-28" and row["reportdate"] == "2024-12-31"
    assert tables == original


@pytest.mark.parametrize("unit,value,base", [("元", 1234.5, 1234.5), ("万元", "1234.5", 12345000),
                                             ("亿元", 12.34, 1234000000), ("亿元", 0, 0),
                                             ("万元", -12.3, -123000)])
def test_explicit_amount_units(vendor, tables, unit, value, base):
    tables[0]["rows"][0].update(unit=unit, financevalue=value)
    assert execute()["data"]["tables"][0]["rows"][0]["financevalue"]["amount"] == base


def test_unknown_unit_and_null_are_not_invented(vendor, tables):
    tables[0]["rows"][0].update(unit="吨", financevalue=12.34, missing=None)
    row = execute()["data"]["tables"][0]["rows"][0]
    assert row["financevalue"] == 12.34 and row["missing"] is None


def test_quotes_counts_and_arbitrary_metrics_remain_distinct(vendor):
    vendor.return_value = [{"columns": {"px": "收盘价(元)", "day": "交易日", "staff": "人员数量(人)",
                            "product": "新产品数量", "id": "证券内码"},
                            "rows": [{"px": 100.5, "day": "2024-12-31", "staff": 4321,
                                      "product": 37, "id": 12345, "adjustment": "不复权"}]}]
    row = execute()["data"]["tables"][0]["rows"][0]
    assert row == {"close": 100.5, "trade_date": "2024-12-31", "staff": 4321,
                   "product": 37, "id": "12345", "adjustment": "不复权"}


@pytest.mark.parametrize("value", [23.01, "23.01%", "23.01％"])
def test_percent_points_not_fraction(vendor, tables, value):
    tables[0]["rows"][0]["ratio"] = value
    assert execute()["data"]["tables"][0]["rows"][0]["ratio"]["percent"] == 23.01


def test_explicit_foreign_currency_is_retained(vendor, tables):
    tables[0]["rows"][0]["currency"] = "USD"
    assert execute()["data"]["tables"][0]["rows"][0]["financevalue"]["currency"] == "USD"


@pytest.mark.parametrize("response", [[], [{"columns": {}, "rows": []}]])
def test_empty_data_is_explicit(vendor, response):
    vendor.return_value = response
    assert execute()["has_data"] is False


@pytest.mark.parametrize("response", [[{"columns": {}, "rows": "bad"}],
                                      [{"columns": {"x": "收盘价", "close": "其他"}, "rows": []}]])
def test_unsupported_data_has_no_evidence(vendor, response):
    vendor.return_value = response
    assert execute()["ok"] is False


def test_service_error_does_not_leak_or_fallback(vendor):
    vendor.side_effect = RuntimeError("secret-token")
    out = execute()
    assert out["error_type"] == "service_error" and "secret-token" not in json.dumps(out)
    vendor.assert_called_once()


@pytest.mark.parametrize("prose,value,field,valid", [
    ("营业收入12.34 亿元", "12.34亿元", "financevalue.amount", True),
    ("营业收入13.34亿元", "13.34亿元", "financevalue.amount", False),
    ("占比23.01%", "23.01%", "ratio.percent", True),
    ("营业收入12.34亿元", "12.34亿元", "ratio.percent", False),
])
def test_existing_grounding_accepts_correct_paths_and_rejects_wrong_values(vendor, tmp_path, prose, value, field, valid):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600000.SH 财务")
    out = execute()
    ledger.ingest_tool_result(tool_name="gildata_fin_query", arguments={"query": "mixed metrics"},
                              result=json.dumps(out), call_id="fq1", success=True)
    result = ledger.validate_final_answer(f"600000.SH {prose}。\n```figures\n"
                                          f"{value} | observed | 指标 | fq1::data.tables[0].rows[0].{field}\n```")
    assert result.valid is valid, result.issues


def test_repeated_calls_need_the_right_call_id(vendor, tables, tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600000.SH 财务")
    for call_id, value in [("first", 12.34), ("second", 56.78)]:
        tables[0]["rows"][0]["financevalue"] = value
        ledger.ingest_tool_result(tool_name="gildata_fin_query", arguments={"query": "mixed metrics"},
                                  result=json.dumps(execute()), call_id=call_id, success=True)
    def check(ref):
        return ledger.validate_final_answer("600000.SH 营业收入56.78亿元。\n```figures\n"
            f"56.78亿元 | observed | 收入 | {ref}::data.tables[0].rows[0].financevalue.amount\n```")
    assert check("second").valid
    assert not check("first").valid
    assert not check("gildata_fin_query").valid


def test_large_result_uses_original_delivery_without_loss(vendor, tables, tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    tables[0]["rows"] *= 150
    raw = json.dumps(execute(), ensure_ascii=False)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry))
    saved = json.loads(Path(receipt["_result_file"]["path"]).read_text(encoding="utf-8"))
    assert saved == json.loads(raw)


def test_optional_tool_is_discovered(monkeypatch):
    from src.tools import _discover_subclasses
    import src.tools as tools
    monkeypatch.setattr(tools, "_SUBCLASSES_CACHE", None)
    assert fq.GildataFinQueryTool in _discover_subclasses()


def test_shared_transport_preserves_results_and_old_flattening(monkeypatch, tables):
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    raw = {"result": {"content": [{"type": "text", "text": json.dumps({"code": 0, "results": tables})}]}}
    with patch.object(gildata_srv, "throttled_post_json", return_value=raw) as post:
        preserved = gildata_srv.call_srv_tool_results("FinQuery", "mixed")
        flattened = gildata_srv.call_srv_tool("MacroIndustryData", "macro")
    assert preserved == tables
    assert flattened == {"api_names": [t["api_name"] for t in tables],
                         "rows": [r for t in tables for r in t["rows"]]}
    url = post.call_args.args[0]
    assert "format=json" in url and "test-token" not in url
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"




def test_returned_display_and_ref_can_be_cited_without_extra_calculation(vendor, tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600000.SH 财务")
    out = execute()
    ledger.ingest_tool_result(tool_name="gildata_fin_query", arguments={"query": "mixed metrics"},
                              result=json.dumps(out), call_id="fq1", success=True)
    cell = out["data"]["tables"][0]["rows"][0]["financevalue"]
    result = ledger.validate_final_answer(f"600000.SH 营业收入{cell['citation'].split(' | ')[0]}。\n```figures\n"
                                          f"{cell['citation']}\n```")
    assert result.valid, result.issues


@pytest.mark.parametrize("unit,amount,display", [
    ("亿元", 21.44, "21.44亿元"),
    ("万元", "567.89", "567.89万元"),
    ("元", -0.2, "-0.2元"),
    ("亿元", 0, "0元"),
])
def test_display_keeps_units_and_sign_and_uses_existing_evidence(vendor, tables, tmp_path, unit, amount, display):
    tables[0]["rows"][0].update(unit=unit, financevalue=amount)
    out = execute()
    cell = out["data"]["tables"][0]["rows"][0]["financevalue"]
    assert cell["display"] == display
    assert cell["citation"].split(" | ")[0] == display
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600000.SH 财务")
    ledger.ingest_tool_result(tool_name="gildata_fin_query", arguments={"query": "mixed metrics"},
                              result=json.dumps(out), call_id="fq1", success=True)
    records = [r for r in ledger._evidence if "financevalue" in r.field]
    assert len(records) == 1 and records[0].field.endswith(".amount")
    def check(value):
        return ledger.validate_final_answer(
            f"600000.SH 金额{value}。\n```figures\n"
            f"{value} | observed | 金额 | fq1::data.tables[0].rows[0].financevalue.amount\n```")
    result = check(cell["display"])
    assert result.valid, result.issues
    assert not check("0.2元" if amount == -0.2 else "99.99亿元").valid


@pytest.mark.parametrize("date_label", ["交易日", "交易日期"])
def test_quote_date_aliases_keep_actual_date(vendor, tmp_path, date_label):
    vendor.return_value = [{"columns": {"enddate": date_label, "prev": "前收盘价(元)", "last": "收盘价(元)"},
                            "rows": [{"enddate": "2024-12-31", "prev": 110, "last": 100}]}]
    out = execute()
    row = out["data"]["tables"][0]["rows"][0]
    assert row == {"trade_date": "2024-12-31", "prev_close": 110, "close": 100}
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600000.SH quote")
    ledger.ingest_tool_result(tool_name="gildata_fin_query", arguments={"query": "mixed metrics"},
                              result=json.dumps(out), call_id="fq1", success=True)
    assert any(r.timestamp == "2024-12-31" and r.symbol is None and r.value == 100
               for r in ledger._comparable_price_records())


def test_financial_metric_with_explicit_percent_unit(vendor, tables):
    tables[0]["rows"][0].update(unit="%", financevalue=12.34)
    assert execute()["data"]["tables"][0]["rows"][0]["financevalue"]["percent"] == 12.34


def test_query_without_code_calls_finquery_directly(vendor):
    query = "查询某公司的年末收盘价、全年营收和归母净利润"
    out = json.loads(fq.GildataFinQueryTool().execute(query=query))
    vendor.assert_called_once_with("FinQuery", query)
    assert out["ok"]
    cell = out["data"]["tables"][0]["rows"][0]["financevalue"]
    assert "600000.SH" in cell["citation"]
    assert fq.GildataFinQueryTool.parameters["required"] == ["query"]
    assert set(fq.GildataFinQueryTool.parameters["properties"]) == {"query"}
    assert "code" not in out


def test_no_code_uses_existing_authorization_without_resolution(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="查询某公司财务")
    decision = ledger.authorize_tool_call(tool_name="gildata_fin_query", arguments={"query": "公司财务"},
                                         batch_authorized_symbols=[], batch_identity_status="invalidated", call_id="q1")
    assert decision.allowed
