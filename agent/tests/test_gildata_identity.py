"""Optional recall must preserve resolver identity and other sources."""
import json
from unittest.mock import Mock

import pytest

from src.agent.grounding import GroundingLedger
from src.tools import gildata_identity as gi
from src.tools import symbol_search_tool as ss


@pytest.fixture
def recall(monkeypatch):
    monkeypatch.setenv("GILDATA_TOKEN", "test-token")
    fn = Mock(return_value=[
        {"api_name": "StockDailyQuote", "candidates": [
            {"caption": "测试公司", "ref_code": "600000.SH", "code": "internal"},
            {"caption": "其他公司", "ref_code": "600001.SH"},
            {"caption": "未上市", "ref_code": "X12345.SH"}]},
        {"api_name": "HKStockDailyQuotes", "candidates": [
            {"caption": "测试公司", "ref_code": "700.HK", "code": "hk-internal"}]},
    ])
    monkeypatch.setattr(gi, "_call_tool_results", fn)
    monkeypatch.setattr(ss, "_search_selected_connector", lambda *a: ([], None, None))
    monkeypatch.setattr(ss, "_search_eastmoney", lambda *a: ([], "ok"))
    monkeypatch.setattr(ss, "_search_yahoo", lambda *a: ([], "unavailable"))
    monkeypatch.setattr(ss, "_enrich_us_cik", lambda x: (x, ss._NO_US))
    return fn


@pytest.mark.parametrize("token", ["", "your-gildata-token"])
def test_no_token_does_not_change_sources(recall, monkeypatch, token):
    monkeypatch.setenv("GILDATA_TOKEN", token)
    out = json.loads(ss.SymbolSearchTool().execute(query="测试公司"))
    assert "gildata" not in out["data"]["sources"]
    recall.assert_not_called()


def test_all_exact_venues_survive_and_remain_ambiguous(recall, tmp_path):
    raw = ss.SymbolSearchTool().execute(query="测试公司")
    data = json.loads(raw)["data"]
    assert [c["symbol"] for c in data["candidates"]] == ["600000.SH", "00700.HK"]
    assert data["candidates"][0]["vendor_code"] == "internal"
    ledger = GroundingLedger(run_dir=tmp_path, user_message="测试公司")
    ledger.ingest_tool_result(tool_name="search_symbol", arguments={"query": "测试公司"},
                              call_id="search1", result=raw, success=True)
    assert ledger.identity_status == "ambiguous"


def test_unique_name_locks_with_original_gate(recall, tmp_path):
    recall.return_value = recall.return_value[:1]
    raw = ss.SymbolSearchTool().execute(query="测试公司")
    ledger = GroundingLedger(run_dir=tmp_path, user_message="测试公司")
    ledger.ingest_tool_result(tool_name="search_symbol", arguments={"query": "测试公司"},
                              call_id="search1", result=raw, success=True)
    assert ledger.identity_status == "locked"
    assert ledger.authorized_symbols == {"600000.SH"}


def test_failure_keeps_original_source_candidates(recall, monkeypatch):
    recall.side_effect = RuntimeError("secret-token")
    monkeypatch.setattr(ss, "_search_eastmoney", lambda *a: ([
        {"symbol": "600001.SH", "name": "其他公司", "source": "eastmoney"}], "ok"))
    raw = ss.SymbolSearchTool().execute(query="其他公司")
    out = json.loads(raw)["data"]
    assert out["candidates"][0]["symbol"] == "600001.SH"
    assert out["sources"]["eastmoney"] == "ok"
    assert "failed" in out["sources"]["gildata"] and "secret-token" not in raw


def test_deduplicates_without_replacing_public_provider(recall, monkeypatch):
    monkeypatch.setattr(ss, "_search_eastmoney", lambda *a: ([
        {"symbol": "600000.SH", "name": "测试公司", "source": "eastmoney"}], "ok"))
    out = json.loads(ss.SymbolSearchTool().execute(query="测试公司"))["data"]
    hits = [c for c in out["candidates"] if c["symbol"] == "600000.SH"]
    assert len(hits) == 1 and hits[0]["source"] == "eastmoney"
    assert "gildata" in hits[0]["also_from"]


def test_us_vendor_suffix_is_not_project_suffix(recall):
    recall.return_value = [{"api_name": "USStockDailyQuotes", "candidates": [
        {"caption": "Apple", "ref_code": "AAPL.N", "code": "us-internal"}]}]
    hits, status = gi.search_candidates("AAPL.US", 5)
    assert status == "ok" and hits[0]["symbol"] == "AAPL.US"
    assert hits[0]["vendor_ref_code"] == "AAPL.N"
    assert recall.call_args.args[1]["recall_list"][0]["keyword"] == "AAPL"
