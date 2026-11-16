"""Returned-series summaries reduce inspection turns without hiding gaps or sampling."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.data_gateway.bar_summary import summarize_bars
from src.agent.result_artifacts import persist_calculation_result
from src.config.limits import TOOL_RESULT_LIMIT


def payload():
    start = datetime(2026, 11, 13)
    return {"BTC-USDT": [{"trade_date": (start + timedelta(minutes=5*i)).isoformat(), "close": 100+i} for i in range(288)],
            "_provenance": {"BTC-USDT": {"source": "fixture", "timezone": "UTC"}}}


def test_full_series_summary_is_delivered_without_reading_parts(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    raw = payload()
    raw["_summary"] = summarize_bars(raw, "5m")
    response = json.loads(persist_calculation_result(json.dumps(raw), tmp_path))
    summary = response["_summary"]["BTC-USDT"]
    assert summary["source_rows"] == summary["returned_rows"] == 288
    assert summary["first_time"] == "2026-11-13T00:00:00"
    assert summary["last_time"] == "2026-11-13T23:55:00"
    assert summary["sequence"]["irregular_steps"] == 0
    assert summary["sequence"]["non_increasing_steps"] == 0
    assert summary["coverage"]["coverage_verified"] is False
    assert len(json.dumps(response, ensure_ascii=False)) <= TOOL_RESULT_LIMIT
    assert json.loads(Path(response["_result_file"]["path"]).read_text()) == raw


@pytest.mark.parametrize("fault", ["gap", "duplicate", "backward", "invalid"])
def test_sequence_defects_are_visible(fault):
    raw = payload()
    rows = raw["BTC-USDT"]
    if fault == "gap":
        rows.pop(5)
    elif fault == "duplicate":
        rows[5] = rows[4]
    elif fault == "backward":
        rows[5], rows[6] = rows[6], rows[5]
    else:
        rows[5]["trade_date"] = "not-a-date"
    sequence = summarize_bars(raw, "5m")["BTC-USDT"]["sequence"]
    if fault == "invalid":
        assert not sequence["timestamps_parsed"]
        assert sequence["irregular_steps"] is None
    else:
        assert sequence["irregular_steps"] > 0


def test_sampling_never_claims_consecutive_coverage():
    raw = payload()
    raw["BTC-USDT"] = {"rows": 288, "truncated": True, "data": raw["BTC-USDT"][::10]}
    result = summarize_bars(raw, "5m")["BTC-USDT"]
    assert result["sampled"] and result["source_rows"] == 288
    assert result["returned_rows"] == 29 and "sequence" not in result


def test_large_multisymbol_summary_still_respects_tool_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    raw = {"_summary": {str(i): {"text": "x"*200} for i in range(100)}}
    response = persist_calculation_result(json.dumps(raw), tmp_path)
    assert len(response) <= TOOL_RESULT_LIMIT
    assert "_summary_omitted" in json.loads(response)


def test_statistics_use_all_rows_and_preserve_missing_fields():
    raw = {"AAPL.US": [{"close": 10, "high": 12, "low": 8, "volume": 1},
                       {"close": 12, "high": 15, "low": 9, "volume": 2}]}
    stats = summarize_bars(raw, "1D")["AAPL.US"]["statistics"]
    assert stats["high"] == 15 and stats["low"] == 8 and stats["volume_sum"] == 3
    assert stats["first_to_last_close_change_pct"] == pytest.approx(20)
    del raw["AAPL.US"][0]["volume"]
    assert summarize_bars(raw, "1D")["AAPL.US"]["statistics"]["volume_sum"] is None


def test_overflow_in_optional_statistics_does_not_break_data_delivery():
    raw = {"AAPL.US": [{"close": 1e-308, "volume": 1e308}, {"close": 1e308, "volume": 1e308}]}
    stats = summarize_bars(raw, "1D")["AAPL.US"]["statistics"]
    assert stats["first_to_last_close_change_pct"] is None and stats["volume_sum"] is None


def test_summary_receipt_keeps_missing_symbol_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    raw = payload()
    raw["_unresolved"] = ["BHP.AX"]
    raw["_diagnostics"] = {"BHP.AX": [{"reason": "unsupported_market"}]}
    raw["_summary"] = summarize_bars(raw, "5m")
    response = json.loads(persist_calculation_result(json.dumps(raw), tmp_path))
    assert response["_unresolved"] == ["BHP.AX"]
    assert response["_diagnostics"] == raw["_diagnostics"]
