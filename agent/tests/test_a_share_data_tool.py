import json

import pytest

from src.a_share_data import canonical_a_share_code, normalize_a_share_code
from src.tools import a_share_data_tool, build_registry
from src.tools.a_share_data_tool import AShareDataTool


def test_a_share_code_normalization_is_strict():
    assert normalize_a_share_code("600519") == ("600519", "SH")
    assert normalize_a_share_code("SH600519") == ("600519", "SH")
    assert canonical_a_share_code("000001.SZ") == "000001.SZ"
    with pytest.raises(ValueError):
        normalize_a_share_code("SZ600519")
    with pytest.raises(ValueError):
        normalize_a_share_code("SH000001", stock_only=True)


def test_quote_dispatch_and_envelope(monkeypatch):
    monkeypatch.setattr(
        a_share_data_tool,
        "tencent_quote",
        lambda codes: {codes[0]: {"code": codes[0], "price": 1500.0}},
    )
    payload = json.loads(AShareDataTool().execute(operation="quote", code="600519.SH"))
    assert payload["ok"] is True
    assert payload["source"] == "a-stock-data"
    assert payload["data"]["quotes"]["600519.SH"]["price"] == 1500.0


def test_reports_keep_consensus_best_effort(monkeypatch):
    monkeypatch.setattr(a_share_data_tool, "eastmoney_reports", lambda code, limit: [{"title": "R"}])
    monkeypatch.setattr(a_share_data_tool, "ths_eps_forecast", lambda code: (_ for _ in ()).throw(RuntimeError("THS down")))
    payload = json.loads(AShareDataTool().execute(operation="reports", code="600519.SH", limit=3))
    assert payload["ok"] is True
    assert payload["data"]["reports"] == [{"title": "R"}]
    assert payload["data"]["consensus_eps"] == []
    assert "consensus_error" in payload["data"]


def test_profile_falls_back_to_tencent_quote(monkeypatch):
    monkeypatch.setattr(a_share_data_tool, "eastmoney_stock_info", lambda code: (_ for _ in ()).throw(RuntimeError("Eastmoney down")))
    monkeypatch.setattr(a_share_data_tool, "tencent_quote", lambda codes: {codes[0]: {"price": 1500.0}})
    payload = json.loads(AShareDataTool().execute(operation="fundamentals", code="600519.SH"))
    assert payload["ok"] is True
    assert payload["source"] == "a-stock-data:tencent-fallback"
    assert payload["data"]["profile"]["quote_fallback"]["price"] == 1500.0


def test_all_read_surfaces_dispatch(monkeypatch):
    monkeypatch.setattr(a_share_data_tool, "eastmoney_stock_news", lambda code, limit: [{"title": "N"}])
    monkeypatch.setattr(a_share_data_tool, "cls_telegraph", lambda limit: [{"title": "C"}])
    monkeypatch.setattr(a_share_data_tool, "eastmoney_global_news", lambda limit: [{"title": "G"}])
    monkeypatch.setattr(a_share_data_tool, "eastmoney_stock_info", lambda code: {"name": "K"})
    monkeypatch.setattr(a_share_data_tool, "sina_financial_report", lambda code, statement, limit: [{"statement": statement}])
    monkeypatch.setattr(a_share_data_tool, "cninfo_announcements", lambda code, limit: [{"title": "A"}])
    tool = AShareDataTool()
    assert json.loads(tool.execute(operation="news", code="600519.SH"))["ok"]
    assert json.loads(tool.execute(operation="news", scope="global"))["data"]["feeds"]["cls"] == [{"title": "C"}]
    assert json.loads(tool.execute(operation="fundamentals", code="600519.SH"))["data"]["profile"]["name"] == "K"
    assert json.loads(tool.execute(operation="announcements", code="600519.SH"))["data"]["items"] == [{"title": "A"}]


def test_registry_discovers_a_share_data_tool():
    registry = build_registry()
    assert "get_a_share_data" in registry.tool_names
    assert AShareDataTool.repeatable is True
