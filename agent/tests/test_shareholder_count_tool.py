"""Tests for get_shareholder_count: success + error envelopes, HTTP mocked.

The Eastmoney datacenter call is mocked at ``get_json`` (imported into the tool
module), so no test reaches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import shareholder_count_tool as sct
from src.tools.shareholder_count_tool import ShareholderCountTool

# The per-period detail report: one row per disclosure, no avg/market-cap
# columns (it never carries them).
_DETAIL_PAYLOAD = {
    "result": {
        "data": [
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2024-03-31 00:00:00",
                "HOLDER_NUM": 188000,
                "HOLDER_NUM_CHANGE": -2000,
                "HOLDER_NUM_RATIO": -1.05,
            },
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2023-12-31 00:00:00",
                "HOLDER_NUM": 190000,
                "HOLDER_NUM_CHANGE": 1500,
                "HOLDER_NUM_RATIO": 0.80,
            },
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2023-09-30 00:00:00",
                "HOLDER_NUM": 188500,
                "HOLDER_NUM_CHANGE": 500,
                "HOLDER_NUM_RATIO": 0.27,
            },
        ]
    }
}

# The latest-only report: one row, the only carrier of avg holding/market cap.
_LATEST_PAYLOAD = {
    "result": {
        "data": [
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2024-03-31 00:00:00",
                "PRE_END_DATE": "2023-12-31 00:00:00",
                "HOLDER_NUM": 188000,
                "HOLDER_NUM_CHANGE": -2000,
                "HOLDER_NUM_RATIO": -1.05,
                "AVG_HOLD_NUM": 6680.0,
                "AVG_MARKET_CAP": 12345678.0,
                "TOTAL_MARKET_CAP": 2.1e12,
            },
        ]
    }
}


def _route_by_report(url, params=None, **kwargs):
    """Serve the detail or latest payload by the request's reportName."""
    report = (params or {}).get("reportName")
    if report == sct._DETAIL_REPORT:
        return _DETAIL_PAYLOAD
    return _LATEST_PAYLOAD


def test_success_envelope_parses_periods_newest_first():
    with patch.object(sct, "get_json", side_effect=_route_by_report) as mock_get:
        out = ShareholderCountTool().execute(code="600519.SH")

    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["market"] == "CN"
    assert payload["source"] == "eastmoney"
    assert payload["data"]["code"] == "600519.SH"

    periods = payload["data"]["periods"]
    assert len(periods) == 3
    assert periods[0] == {
        "end_date": "2024-03-31",
        "holder_count": 188000.0,
        "holder_count_change": -2000.0,
        "holder_count_change_pct": -1.05,
        # the latest-only report's avg/market-cap fields join onto the newest row
        "avg_hold_shares": 6680.0,
        "avg_hold_amount": 12345678.0,
        "total_market_cap": 2.1e12,
        "prev_period_end": "2023-12-31",
    }
    # older rows carry no avg fields, and each states its own interval
    assert periods[1]["avg_hold_shares"] is None
    assert periods[1]["prev_period_end"] == "2023-09-30"
    assert periods[2]["prev_period_end"] is None

    # SECUCODE filter flows through to the datacenter request.
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["filter"] == '(SECUCODE="600519.SH")'
    # The retired AVG_HOLD_AMT spelling makes the datacenter reject the request.
    assert "AVG_MARKET_CAP" in kwargs["params"]["columns"]


def test_max_periods_caps_returned_rows():
    with patch.object(sct, "get_json", side_effect=_route_by_report) as mock_get:
        out = ShareholderCountTool().execute(code="600519.SH", max_periods=1)
    payload = json.loads(out)
    assert len(payload["data"]["periods"]) == 1
    # the cap flows to the detail report's pageSize — the latest-only report
    # used to return exactly one row whatever was asked (#1503) — plus one row,
    # so the oldest returned period still knows its previous period
    _, kwargs = mock_get.call_args_list[0]
    assert kwargs["params"]["reportName"] == sct._DETAIL_REPORT
    assert kwargs["params"]["pageSize"] == "2"
    assert payload["data"]["periods"][0]["prev_period_end"] == "2023-12-31"


def test_latest_only_fallback_when_detail_report_is_empty():
    """A symbol absent from the per-period report still answers its latest row."""
    def detail_empty(url, params=None, **kwargs):
        if (params or {}).get("reportName") == sct._DETAIL_REPORT:
            return {"result": {"data": []}}
        return _LATEST_PAYLOAD

    with patch.object(sct, "get_json", side_effect=detail_empty):
        out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is True
    periods = payload["data"]["periods"]
    assert len(periods) == 1
    assert periods[0]["end_date"] == "2024-03-31"
    assert periods[0]["avg_hold_shares"] == 6680.0
    # the latest report's own PRE_END_DATE states the interval for a single row
    assert periods[0]["prev_period_end"] == "2023-12-31"


def test_latest_join_failure_keeps_the_history():
    """The avg-field enrichment is best-effort: history survives it failing."""
    def latest_down(url, params=None, **kwargs):
        if (params or {}).get("reportName") == sct._DETAIL_REPORT:
            return _DETAIL_PAYLOAD
        raise RuntimeError("HTTP 502")

    with patch.object(sct, "get_json", side_effect=latest_down):
        out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is True
    assert len(payload["data"]["periods"]) == 3
    assert payload["data"]["periods"][0]["avg_hold_shares"] is None
    # ...but it says why the average fields are empty
    assert any("HTTP 502" in w for w in payload["data"]["warnings"])


def test_latest_join_rejection_is_a_warning_not_silence():
    """A retired latest-only column (the #1489 failure) must not read as null data."""
    def latest_rejected(url, params=None, **kwargs):
        if (params or {}).get("reportName") == sct._DETAIL_REPORT:
            return _DETAIL_PAYLOAD
        return {"success": False, "result": None, "code": 9501, "message": "AVG_HOLD_AMT返回字段不存在"}

    with patch.object(sct, "get_json", side_effect=latest_rejected):
        payload = json.loads(ShareholderCountTool().execute(code="600519.SH"))
    assert payload["ok"] is True
    assert any("AVG_HOLD_AMT" in w for w in payload["data"]["warnings"])


def test_latest_only_fallback_rejection_is_an_error_not_no_disclosure():
    def both(url, params=None, **kwargs):
        if (params or {}).get("reportName") == sct._DETAIL_REPORT:
            return {"result": {"data": []}}
        return {"success": False, "result": None, "code": 9501, "message": "AVG_HOLD_AMT返回字段不存在"}

    with patch.object(sct, "get_json", side_effect=both):
        payload = json.loads(ShareholderCountTool().execute(code="600519.SH"))
    assert payload["ok"] is False
    assert "AVG_HOLD_AMT" in payload["error"]
    assert "no shareholder-count disclosure" not in payload["error"]


def test_a_clean_join_carries_no_warnings():
    with patch.object(sct, "get_json", side_effect=_route_by_report):
        payload = json.loads(ShareholderCountTool().execute(code="600519.SH"))
    assert "warnings" not in payload["data"]


def test_non_a_share_returns_error_envelope():
    out = ShareholderCountTool().execute(code="AAPL.US")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "A-share" in payload["error"]


def test_missing_code_returns_error_envelope():
    out = ShareholderCountTool().execute()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "required" in payload["error"]


def test_empty_disclosure_returns_error_envelope():
    with patch.object(sct, "get_json", return_value={"result": {"data": []}}):
        out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "no shareholder-count" in payload["error"]


def test_upstream_rejection_is_surfaced_not_reported_as_missing_data():
    """A stale request must not be reported as a symbol without a disclosure.

    The datacenter answers HTTP 200 with ``success: false`` and a message naming an
    unknown column when the requested column list drifts; the envelope has to carry
    that message rather than the empty-disclosure error.
    """
    drift = {
        "success": False,
        "message": "AVG_HOLD_AMT参数不存在",
        "result": None,
    }
    with patch.object(sct, "get_json", return_value=drift):
        out = ShareholderCountTool().execute(code="600519.SH")

    payload = json.loads(out)
    assert payload["ok"] is False
    assert "AVG_HOLD_AMT参数不存在" in payload["error"]
    assert "no shareholder-count" not in payload["error"]


def test_empty_result_message_is_reported_as_no_disclosure():
    """The datacenter's no-rows answer is not a rejection of the request.

    An empty match arrives with the same ``success: false`` flags as a schema
    complaint, so it has to stay on the empty-disclosure path.
    """
    empty = {"success": False, "message": "返回数据为空", "result": None}
    with patch.object(sct, "get_json", return_value=empty):
        out = ShareholderCountTool().execute(code="999999.SH")

    payload = json.loads(out)
    assert payload["ok"] is False
    assert "no shareholder-count" in payload["error"]
    assert "rejected" not in payload["error"]


def test_request_failure_is_caught_as_error_envelope():
    with patch.object(sct, "get_json", side_effect=RuntimeError("HTTP 429")):
        out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "429" in payload["error"]
