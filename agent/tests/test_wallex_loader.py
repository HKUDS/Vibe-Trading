"""Tests for wallex loader: contract, symbol mapping, intervals, chunking.

All HTTP is mocked - no test reaches the live Wallex endpoint. The loader
talks to the API through ``requests.Session.get``, so tests monkeypatch that
method on ``wallex.requests.Session``.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import pytest
import requests

from backtest.loaders import wallex


def _udf_payload(
    times: List[int],
    o: List[Any],
    h: List[Any],
    l: List[Any],
    c: List[Any],
    v: List[Any],
    status: str = "ok",
) -> Dict[str, Any]:
    return {"s": status, "t": times, "o": o, "h": h, "l": l, "c": c, "v": v}


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _CallRecorder:
    """Plain callable: when set as a class attribute it receives no self."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        payload = self.handler(dict(params or {}))
        if isinstance(payload, dict):
            return _FakeResponse(payload)
        return payload


def _patch(monkeypatch: pytest.MonkeyPatch, handler) -> _CallRecorder:
    recorder = _CallRecorder(handler)
    monkeypatch.setattr(wallex.requests.Session, "get", recorder)
    return recorder


class TestLoaderContract:
    def test_attributes(self):
        loader = wallex.DataLoader()
        assert loader.name == "wallex"
        assert loader.markets == {"crypto"}
        assert loader.requires_auth is False


class TestMapSymbol:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("USDT-TMN", "USDTTMN"),
            ("USDTTMN", "USDTTMN"),
            ("usdttmn", "USDTTMN"),
            ("BTC/TMN", "BTCTMN"),
            (" btc-tmn ", "BTCTMN"),
        ],
    )
    def test_normalizes_aliases(self, raw: str, expected: str):
        assert wallex.map_symbol(raw) == expected


class TestIntervalMap:
    def test_only_true_buckets_are_mapped(self):
        assert wallex._INTERVAL_MAP == {"1m": "1", "1h": "60", "1H": "60", "1d": "1D", "1D": "1D"}

    def test_silently_degrading_intervals_reject_without_http(self, monkeypatch):
        def _fail(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("HTTP must not be called for degrading intervals")

        monkeypatch.setattr(wallex.requests.Session, "get", _fail)
        loader = wallex.DataLoader()
        for interval in ("15m", "4h", "4H", "720", "1W"):
            assert loader.fetch(["USDT-TMN"], "2024-01-01", "2024-02-01", interval=interval) == {}


class TestFetch:
    def test_parses_string_ohlcv_into_sorted_floats(self, monkeypatch):
        def handler(params: Dict[str, Any]):
            return _udf_payload(
                [1704067200, 1704153600],
                ["198216.0", "198148.0"],
                ["199125.0", "199000.0"],
                ["198148.0", "197827.0"],
                ["198174.0", "199000.0"],
                ["128980.98", "183954.04"],
            )

        recorder = _patch(monkeypatch, handler)
        out = wallex.DataLoader().fetch(["USDT-TMN"], "2024-01-01", "2024-01-03")
        assert list(out) == ["USDT-TMN"]
        df = out["USDT-TMN"]
        assert df.index.name == "trade_date"
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.is_monotonic_increasing
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert df["close"].tolist() == [198174.0, 199000.0]
        assert df["volume"].dtype.kind == "f"
        assert recorder.calls[0]["params"]["symbol"] == "USDTTMN"
        assert recorder.calls[0]["params"]["resolution"] == "1D"

    def test_error_body_skips_symbol(self, monkeypatch):
        recorder = _patch(
            monkeypatch,
            lambda params: {"errmsg": "Invalid resolution!", "s": "error"},
        )
        out = wallex.DataLoader().fetch(["USDT-TMN"], "2024-01-01", "2024-01-03")
        assert out == {}
        assert recorder.calls, "handler should have been invoked"

    def test_one_bad_symbol_does_not_abort_batch(self, monkeypatch):
        good = _udf_payload(
            [1704067200], ["1"], ["2"], ["0.5"], ["1.5"], ["10"]
        )

        def handler(params: Dict[str, Any]):
            if params.get("symbol") == "BADTMN":
                return {"errmsg": "Invalid symbol", "s": "error"}
            return good

        _patch(monkeypatch, handler)
        out = wallex.DataLoader().fetch(
            ["USDT-TMN", "BAD-TMN"], "2024-01-01", "2024-01-03"
        )
        assert list(out) == ["USDT-TMN"]

    def test_forward_chunking_merges_windows(self, monkeypatch):
        calls: List[Dict[str, Any]] = []

        def handler(params: Dict[str, Any]):
            calls.append(dict(params))
            start = int(params["from"])
            step = 60
            span = int(params["to"]) - start
            count = min(span // step, 500)
            times = [start + i * step for i in range(count)]
            return _udf_payload(
                times,
                ["1"] * count,
                ["2"] * count,
                ["0.5"] * count,
                ["1.5"] * count,
                ["10"] * count,
            )

        _patch(monkeypatch, handler)
        # 74 days of 1m data spans 4 windows of 20 days.
        out = wallex.DataLoader().fetch(["USDT-TMN"], "2024-01-01", "2024-03-15", interval="1m")
        df = out["USDT-TMN"]
        assert df.index.is_monotonic_increasing
        assert not df.index.duplicated().any()
        assert len(calls) >= 2
        froms = [c["from"] for c in calls]
        assert froms == sorted(froms), "windows must walk forward"

    def test_invalid_date_range_raises(self):
        with pytest.raises(ValueError):
            wallex.DataLoader().fetch(["USDT-TMN"], "2024-02-01", "2024-01-01")


class TestRoutingPattern:
    def test_source_pattern_matches_tmn_pairs_only(self):
        from src.market_data import detect_source

        assert detect_source("USDTTMN") == "wallex"
        assert detect_source("USDT-TMN") == "wallex"
        assert detect_source("btc-tmn") == "wallex"
        assert detect_source("BTCIRT") == "nobitex"
        assert detect_source("BTC-USDT") == "okx"
