"""Tests for nobitex loader: contract, symbol mapping, intervals, parsing.

All HTTP is mocked - no test reaches the live Nobitex endpoint. The loader
talks to the API through ``requests.Session.get``, so tests monkeypatch that
method on ``nobitex.requests.Session``.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import pytest
import requests

from backtest.loaders import nobitex


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
    def __init__(self, pages: Dict[int, Dict[str, Any]]):
        self.pages = pages
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        page = int((params or {}).get("page", 1))
        payload = self.pages.get(page)
        if payload is None:
            return _FakeResponse({"s": "no_data"})
        return _FakeResponse(payload)


def _patch(monkeypatch: pytest.MonkeyPatch, pages: Dict[int, Dict[str, Any]]) -> _CallRecorder:
    recorder = _CallRecorder(pages)
    monkeypatch.setattr(nobitex.requests.Session, "get", recorder)
    return recorder


class TestLoaderContract:
    def test_attributes(self):
        loader = nobitex.DataLoader()
        assert loader.name == "nobitex"
        assert loader.markets == {"crypto"}
        assert loader.requires_auth is False


class TestMapSymbol:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("BTC-IRT", "BTCIRT"),
            ("BTCIRT", "BTCIRT"),
            ("btcirt", "BTCIRT"),
            ("USDT/IRT", "USDTIRT"),
            (" usdt-irt ", "USDTIRT"),
        ],
    )
    def test_normalizes_aliases(self, raw: str, expected: str):
        assert nobitex.map_symbol(raw) == expected


class TestIntervalMap:
    def test_resolutions(self):
        assert nobitex._INTERVAL_MAP["1h"] == "60"
        assert nobitex._INTERVAL_MAP["1H"] == "60"
        assert nobitex._INTERVAL_MAP["4h"] == "240"
        assert nobitex._INTERVAL_MAP["4H"] == "240"
        assert nobitex._INTERVAL_MAP["1d"] == "D"
        assert nobitex._INTERVAL_MAP["1D"] == "D"
        assert nobitex._INTERVAL_MAP["12H"] == "720"

    def test_unsupported_interval_returns_empty_without_http(self, monkeypatch):
        def _fail(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("HTTP must not be called for unsupported intervals")

        monkeypatch.setattr(nobitex.requests.Session, "get", _fail)
        out = nobitex.DataLoader().fetch(
            ["BTC-IRT"], "2024-01-01", "2024-02-01", interval="1W"
        )
        assert out == {}


class TestFetch:
    def test_parses_udf_into_sorted_ohlcv(self, monkeypatch):
        recorder = _patch(
            monkeypatch,
            {
                1: _udf_payload(
                    [1704067200, 1704153600],
                    ["1", "2"],
                    ["2", "3"],
                    ["0.5", "1"],
                    ["1.5", "2.5"],
                    ["10", "20"],
                )
            },
        )
        out = nobitex.DataLoader().fetch(["BTC-IRT"], "2024-01-01", "2024-01-03")
        assert list(out) == ["BTC-IRT"]
        df = out["BTC-IRT"]
        assert df.index.name == "trade_date"
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.is_monotonic_increasing
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert df["close"].tolist() == [1.5, 2.5]
        assert df["volume"].dtype.kind == "f"
        assert recorder.calls[0]["params"]["symbol"] == "BTCIRT"
        assert recorder.calls[0]["params"]["resolution"] == "D"
        assert recorder.calls[0]["params"]["page"] == 1

    def test_no_data_yields_empty_result(self, monkeypatch):
        _patch(monkeypatch, {1: {"s": "no_data"}})
        out = nobitex.DataLoader().fetch(["BTC-IRT"], "2024-01-01", "2024-01-03")
        assert out == {}

    def test_error_status_skips_symbol(self, monkeypatch):
        _patch(monkeypatch, {1: {"s": "error", "errmsg": "InvalidSymbol"}})
        out = nobitex.DataLoader().fetch(["BTC-IRT"], "2024-01-01", "2024-01-03")
        assert out == {}

    def test_one_bad_symbol_does_not_abort_batch(self, monkeypatch):
        good = _udf_payload([1704067200], ["1"], ["2"], ["0.5"], ["1.5"], ["10"])
        calls: List[Dict[str, Any]] = []

        def fake_get(session_self, url, params=None, timeout=None):
            symbol = (params or {}).get("symbol")
            if symbol == "BADIRT":
                return _FakeResponse({"s": "error", "errmsg": "InvalidSymbol"})
            calls.append({"params": dict(params or {})})
            return _FakeResponse(good)

        monkeypatch.setattr(nobitex.requests.Session, "get", fake_get)
        out = nobitex.DataLoader().fetch(
            ["BTC-IRT", "BAD-IRT"], "2024-01-01", "2024-01-03"
        )
        assert list(out) == ["BTC-IRT"]
        assert len(calls) >= 1

    def test_paginates_older_pages_and_dedupes(self, monkeypatch):
        base = 1700000000
        t1 = [base + i * 3600 for i in range(nobitex._MAX_PER_PAGE)]
        t2 = [base - (300 - i) * 3600 for i in range(300)]

        def payload_for(times: List[int]) -> Dict[str, Any]:
            return _udf_payload(
                times,
                ["1"] * len(times),
                ["2"] * len(times),
                ["0.5"] * len(times),
                ["1.5"] * len(times),
                ["10"] * len(times),
            )

        recorder = _patch(monkeypatch, {1: payload_for(t1), 2: payload_for(t2)})
        out = nobitex.DataLoader().fetch(["BTC-IRT"], "2023-11-01", "2024-03-01")
        assert len(out["BTC-IRT"]) == 800
        assert [c["params"]["page"] for c in recorder.calls] == [1, 2]

    def test_invalid_date_range_raises(self):
        with pytest.raises(ValueError):
            nobitex.DataLoader().fetch(["BTC-IRT"], "2024-02-01", "2024-01-01")


class TestRoutingPattern:
    def test_source_pattern_matches_irt_pairs_only(self):
        from src.market_data import detect_source

        assert detect_source("BTCIRT") == "nobitex"
        assert detect_source("BTC-IRT") == "nobitex"
        assert detect_source("usdtirt") == "nobitex"
        assert detect_source("BTC-USDT") == "okx"
        assert detect_source("AAPL.US") == "yahoo"
