"""Tests for gildata_loader: auth gating, symbol mapping, parsing, batch resilience.

All HTTP is mocked at :func:`backtest.loaders._http.throttled_post_json` (imported
into the loader module), so no test touches a live Gildata endpoint.
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.loaders import gildata_loader as gl
from backtest.loaders.gildata_loader import (
    DataLoader,
    _gildata_symbol,
    _parse_daily_rows,
)

# Two raw StockDailyQuote rows exactly as the vendor sends them: descending
# dates, turnovervolume in 万股, and avgprice on a different (unadjusted)
# basis than the qfq OHLC — the parser must ignore it.
_MAOTAI_ROWS = [
    {
        "tradingday": "2024-01-04",
        "openprice": 1509.71, "highprice": 1525.45, "lowprice": 1501.33,
        "closeprice": 1511.55, "avgprice": 1666.34,
        "turnovervolume": 202.43, "turnovervalue": 337315.56,
    },
    {
        "tradingday": "2024-01-03",
        "openprice": 1491.24, "highprice": 1501.52, "lowprice": 1485.84,
        "closeprice": 1491.23, "avgprice": 1642.56,
        "turnovervolume": 244.12, "turnovervalue": 400982.65,
    },
]


def _envelope(rows, *, inner_code=0):
    """Build the full MCP JSON-RPC response around a StockDailyQuote result."""
    inner = {"code": inner_code, "results": [{"api_name": "股票日行情", "columns": {}, "rows": rows}]}
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(inner)}]}}


class TestRegistration:
    """Loader self-registers with the expected metadata."""

    def test_registered_in_registry(self):
        from backtest.loaders import registry

        registry._ensure_registered()
        assert registry.LOADER_REGISTRY.get("gildata") is DataLoader

    def test_metadata(self):
        assert DataLoader.name == "gildata"
        assert DataLoader.markets == {"a_share", "hk_equity"}
        assert DataLoader.requires_auth is True
        assert DataLoader.volume_units == {
            "a_share": "shares",
            "hk_equity": "shares",
        }


class TestIsAvailable:
    """Availability is gated purely on GILDATA_TOKEN presence."""

    def test_available_with_token(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        assert DataLoader().is_available() is True

    def test_unavailable_without_token(self, monkeypatch):
        monkeypatch.delenv("GILDATA_TOKEN", raising=False)
        assert DataLoader().is_available() is False

    def test_unavailable_with_blank_token(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "   ")
        assert DataLoader().is_available() is False

    def test_unavailable_with_placeholder_token(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "your-gildata-token")
        assert DataLoader().is_available() is False


class TestSymbolMapping:
    """Project symbols map onto Gildata's 代码.后缀 convention."""

    def test_suffixed_passthrough(self):
        assert _gildata_symbol("600519.SH") == "600519.SH"
        assert _gildata_symbol("000001.SZ") == "000001.SZ"
        assert _gildata_symbol("831010.BJ") == "831010.BJ"

    def test_ss_normalized_to_sh(self):
        assert _gildata_symbol("600519.SS") == "600519.SH"

    def test_lowercase_uppered(self):
        assert _gildata_symbol("600519.sh") == "600519.SH"

    def test_bare_code_exchange_inferred(self):
        assert _gildata_symbol("600519") == "600519.SH"
        assert _gildata_symbol("000001") == "000001.SZ"
        assert _gildata_symbol("300750") == "300750.SZ"
        assert _gildata_symbol("831010") == "831010.BJ"

    def test_non_a_share_returns_none(self):
        assert _gildata_symbol("00700.HK") is None
        assert _gildata_symbol("AAPL.US") is None
        assert _gildata_symbol("BTC-USDT") is None
        assert _gildata_symbol("") is None
        assert _gildata_symbol("12345") is None


class TestParseDailyRows:
    """Pure parsing of vendor rows needs no network."""

    def test_sorts_ascending_and_typed(self):
        df = _parse_daily_rows(_MAOTAI_ROWS)
        assert list(df.index) == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "trade_date"
        for col in df.columns:
            assert df[col].dtype == float

    def test_volume_converted_from_wan_shares_to_shares(self):
        df = _parse_daily_rows(_MAOTAI_ROWS)
        # 244.12 万股 on 2024-01-03 -> 2_441_200 shares.
        assert df["volume"].iloc[0] == pytest.approx(2_441_200.0)

    def test_avgprice_ignored(self):
        df = _parse_daily_rows(_MAOTAI_ROWS)
        # avgprice (1666) is on a different adjustment basis and must never
        # leak into any served column.
        assert df["close"].max() < 1600.0

    def test_enddate_key_accepted(self):
        rows = [
            {"enddate": "2024-01-03", "openprice": 1.0, "highprice": 2.0,
             "lowprice": 0.5, "closeprice": 1.5, "turnovervolume": 100.0},
        ]
        df = _parse_daily_rows(rows)
        assert df is not None and len(df) == 1

    def test_integer_fields_cast_to_float(self):
        rows = [
            {"tradingday": "2024-01-03", "openprice": 1, "highprice": 2,
             "lowprice": 0, "closeprice": 1, "turnovervolume": 100},
        ]
        df = _parse_daily_rows(rows)
        for col in df.columns:
            assert df[col].dtype == float

    def test_missing_volume_becomes_zero(self):
        rows = [
            {"tradingday": "2024-01-03", "openprice": 1.0, "highprice": 2.0,
             "lowprice": 0.5, "closeprice": 1.5},
        ]
        df = _parse_daily_rows(rows)
        assert df["volume"].iloc[0] == 0.0

    def test_empty_rows_returns_none(self):
        assert _parse_daily_rows([]) is None

    def test_rows_with_incomplete_ohlc_dropped(self):
        rows = [
            {"tradingday": "2024-01-03", "openprice": None, "highprice": 2.0,
             "lowprice": 0.5, "closeprice": 1.5, "turnovervolume": 100.0},
        ]
        assert _parse_daily_rows(rows) is None


class TestFetch:
    """End-to-end fetch with the HTTP layer mocked."""

    def test_fetch_one_symbol(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with patch.object(gl, "throttled_post_json", return_value=_envelope(_MAOTAI_ROWS)) as mock_post:
            out = DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-31")
        assert set(out) == {"600519.SH"}
        assert len(out["600519.SH"]) == 2
        # The token rides the Authorization header — never the URL, whose
        # full form request exceptions embed in their messages (review of
        # #1474: a query-string token would leak into error logs).
        url = mock_post.call_args[0][0]
        assert "token=" not in url
        assert "format=json" in url
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret"
        # MCP streamable-HTTP requires the dual Accept header (measured:
        # the endpoint answers 400 without it).
        assert headers["Accept"] == "application/json, text/event-stream"
        # The JSON-RPC body routes to StockDailyQuote with qfq adjustment.
        body = mock_post.call_args.kwargs["json_body"]
        assert body["method"] == "tools/call"
        params = body["params"]
        assert params["name"] == "StockDailyQuote"
        assert params["arguments"] == {
            "stockObject": ["600519.SH"],
            "beginDate": "2024-01-01",
            "endDate": "2024-01-31",
            "restorationStatus": "1",
        }

    def test_ss_suffix_normalized_on_wire(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with patch.object(gl, "throttled_post_json", return_value=_envelope(_MAOTAI_ROWS)) as mock_post:
            DataLoader().fetch(["600519.SS"], "2024-01-01", "2024-01-31")
        args = mock_post.call_args.kwargs["json_body"]["params"]["arguments"]
        assert args["stockObject"] == ["600519.SH"]

    def test_unsupported_symbols_skipped(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with patch.object(gl, "throttled_post_json") as mock_post:
            out = DataLoader().fetch(["AAPL.US", "BTC-USDT"], "2024-01-01", "2024-01-31")
        assert out == {}
        mock_post.assert_not_called()

    def test_one_failing_symbol_does_not_abort_batch(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")

        def _side(url, **kwargs):
            symbol = kwargs["json_body"]["params"]["arguments"]["stockObject"][0]
            if symbol == "BAD.SZ":
                raise RuntimeError("boom")
            return _envelope(_MAOTAI_ROWS)

        with patch.object(gl, "throttled_post_json", side_effect=_side):
            out = DataLoader().fetch(["BAD.SZ", "600519.SH"], "2024-01-01", "2024-01-31")
        assert set(out) == {"600519.SH"}

    def test_empty_result_symbol_omitted(self, monkeypatch):
        # An unresolvable symbol answers rows: [] (never an error) and must
        # drop out so the fallback chain can serve it from another source.
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with patch.object(gl, "throttled_post_json", return_value=_envelope([])):
            out = DataLoader().fetch(["ZZZZ99.SZ"], "2024-01-01", "2024-01-31")
        assert out == {}

    def test_vendor_error_code_raises_for_that_symbol(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with patch.object(gl, "throttled_post_json", return_value=_envelope([], inner_code=1001)):
            out = DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-31")
        # The symbol fails (logged) but fetch itself must not raise.
        assert out == {}

    def test_auth_error_shape_raises_for_that_symbol(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "bad-token")
        body = {"success": False, "code": 1001, "message": "认证凭证缺失或有误", "data": None}
        with patch.object(gl, "throttled_post_json", return_value=body):
            out = DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-31")
        assert out == {}

    def test_non_daily_interval_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with patch.object(gl, "throttled_post_json") as mock_post:
            out = DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-31", interval="5m")
        assert out == {}
        mock_post.assert_not_called()

    def test_invalid_date_range_raises(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        with pytest.raises(ValueError):
            DataLoader().fetch(["600519.SH"], "2024-02-01", "2024-01-01")

    def test_missing_token_at_fetch_time_skips_symbol(self, monkeypatch):
        monkeypatch.delenv("GILDATA_TOKEN", raising=False)
        with patch.object(gl, "throttled_post_json") as mock_post:
            out = DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-31")
        assert out == {}
        mock_post.assert_not_called()

    def test_base_url_override_applied(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        monkeypatch.setenv("GILDATA_BASE_URL", "https://proxy.example/mcp")
        with patch.object(gl, "throttled_post_json", return_value=_envelope(_MAOTAI_ROWS)) as mock_post:
            DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-31")
        url = mock_post.call_args[0][0]
        assert url.startswith("https://proxy.example/mcp?")



def _recall_envelope(ref_code, code):
    inner = {
        "code": 0,
        "results": [
            {
                "api_name": "ParamCandidateRecall",
                "candidates": [
                    {"caption": "wrong", "code": "999", "ref_code": "99999.HK"},
                    {"caption": "right", "code": code, "ref_code": ref_code},
                ],
            }
        ],
    }
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [
        {"type": "text", "text": json.dumps(inner)}
    ]}}


# HK rows exactly as HKStockDailyQuotes sends them: bare OHLC keys, volume
# already in shares, befadj/aftadj closes as separate (ignored) fields.
_HK_ROWS = [
    {"tradingday": "2024-05-14", "open": 371.0, "high": 380.0, "low": 369.0,
     "close": 378.2, "volume": 20558084,
     "befadjcloseprice": 367.4352, "aftadjcloseprice": 2103.93},
    {"tradingday": "2024-05-13", "open": 368.6, "high": 380.0, "low": 368.0,
     "close": 378.2, "volume": 16718452, "befadjcloseprice": 367.4352},
]

# Index rows use the openprice-style keys with turnovervolume in 万股.
_INDEX_ROWS = [
    {"tradingday": "2024-01-03", "openprice": 3380.0, "highprice": 3390.0,
     "lowprice": 3360.0, "closeprice": 3380.5, "turnovervolume": 1100000.0},
    {"tradingday": "2024-01-02", "openprice": 3426.27, "highprice": 3426.27,
     "lowprice": 3386.35, "closeprice": 3386.35, "turnovervolume": 1161807.26},
]


class TestHkFetch:
    """:HK symbols route to the HK tool with a resolved internal code."""

    def test_fetch_hk_symbol(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        from backtest.loaders.gildata_codes import reset_code_cache
        reset_code_cache()

        def _side(url, **kwargs):
            body = kwargs["json_body"]["params"]
            if body["name"] == "ParamCandidateRecall":
                return _recall_envelope("00700.HK", "1000546")
            assert body["name"] == "HKStockDailyQuotes"
            assert body["arguments"] == {
                "stockObject": ["1000546"],
                "beginDate": "2024-05-01",
                "endDate": "2024-05-31",
            }
            return _envelope(_HK_ROWS)

        with patch.object(gl, "throttled_post_json", side_effect=_side):
            out = DataLoader().fetch(["00700.HK"], "2024-05-01", "2024-05-31")
        assert set(out) == {"00700.HK"}
        df = out["00700.HK"]
        assert len(df) == 2
        # Ascending: first row is 2024-05-13. Volume already in shares: no
        # 万股 scaling.
        assert df["volume"].iloc[0] == pytest.approx(16718452.0)
        # Raw traded prices pass through untouched.
        assert df["close"].iloc[0] == pytest.approx(378.2)
        # befadj/aftadj closes never leak into any served column.
        assert df["close"].max() < 400.0
        reset_code_cache()

    def test_unresolved_recall_omits_symbol(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        from backtest.loaders.gildata_codes import reset_code_cache
        reset_code_cache()

        def _side(url, **kwargs):
            # Recall answers candidates that do not include 00700.HK.
            return _recall_envelope("09999.HK", "424242")

        with patch.object(gl, "throttled_post_json", side_effect=_side) as mock_post:
            out = DataLoader().fetch(["00700.HK"], "2024-05-01", "2024-05-31")
        assert out == {}
        # Exactly one wire call: the recall — never the quote tool.
        assert mock_post.call_count == 1
        reset_code_cache()


class TestIndexFetch:
    """CN index codes route to the index tool with a resolved internal code."""

    def test_fetch_cn_index(self, monkeypatch):
        monkeypatch.setenv("GILDATA_TOKEN", "secret")
        from backtest.loaders.gildata_codes import reset_code_cache
        reset_code_cache()

        def _side(url, **kwargs):
            body = kwargs["json_body"]["params"]
            if body["name"] == "ParamCandidateRecall":
                return _recall_envelope("000300.SH", "3145")
            assert body["name"] == "IndexDailyQuote"
            assert body["arguments"] == {
                "indexObject": ["3145"],
                "beginDate": "2024-01-01",
                "endDate": "2024-01-31",
            }
            return _envelope(_INDEX_ROWS)

        with patch.object(gl, "throttled_post_json", side_effect=_side):
            out = DataLoader().fetch(["000300.SH"], "2024-01-01", "2024-01-31")
        assert set(out) == {"000300.SH"}
        df = out["000300.SH"]
        # Ascending: first row is 2024-01-02. Index volume is 万股 and scales
        # to shares like the A-share tool.
        assert df["volume"].iloc[0] == pytest.approx(1_161_807.26 * 10_000)
        assert df["close"].iloc[0] == pytest.approx(3386.35)
        reset_code_cache()

    def test_index_detection_exchange_specific(self):
        # 000001.SZ is Ping An Bank (an A-share), 000001.SH is the SSE index.
        assert gl._is_cn_index("000001.SH") is True
        assert gl._is_cn_index("000001.SZ") is False
