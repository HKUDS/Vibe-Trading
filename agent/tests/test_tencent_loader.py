"""Tests for Tencent's daily-only market-data contract."""

from __future__ import annotations

import json
import urllib.request

import pandas as pd

from backtest.loaders import tencent_loader


class _FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _hk_kline_payload(tencent_code: str) -> str:
    return json.dumps(
        {
            "code": 0,
            "data": {
                tencent_code: {
                    "day": [
                        ["2026-01-05", "466.4", "471.8", "475.0", "462.8", "31791979"],
                        ["2026-01-06", "470.0", "475.2", "479.8", "462.0", "31100240"],
                    ]
                }
            },
        }
    )


def _patch_http(monkeypatch, urls: list[str], payload: str) -> None:
    def fake_urlopen(req, timeout=None):  # noqa: ANN001, ANN002
        urls.append(req.full_url)
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        tencent_loader,
        "cached_loader_fetch",
        lambda **kwargs: kwargs["fetch"](),
    )


def test_intraday_request_does_not_return_daily_bars(monkeypatch) -> None:
    calls: list[str] = []
    daily = pd.DataFrame(
        {
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-05")]),
    )
    loader = tencent_loader.DataLoader()
    monkeypatch.setattr(
        tencent_loader,
        "cached_loader_fetch",
        lambda **kwargs: kwargs["fetch"](),
    )
    monkeypatch.setattr(
        loader,
        "_fetch_one",
        lambda code, start, end: calls.append(code) or daily,
    )

    result = loader.fetch(
        ["600519.SH"],
        "2026-01-01",
        "2026-01-31",
        interval="1m",
    )

    assert result == {}
    assert calls == []


def test_hk_equity_maps_to_hk_prefix_and_parses(monkeypatch) -> None:
    urls: list[str] = []
    _patch_http(monkeypatch, urls, _hk_kline_payload("hk00700"))

    result = tencent_loader.DataLoader().fetch(
        ["00700.HK"], "2026-01-01", "2026-01-31",
    )

    assert len(urls) == 1
    assert "param=hk00700,day," in urls[0]
    df = result["00700.HK"]
    assert len(df) == 2
    # Tencent kline rows are [date, open, close, high, low, volume].
    assert df.iloc[0]["open"] == 466.4
    assert df.iloc[0]["close"] == 471.8
    assert df.iloc[0]["high"] == 475.0
    assert df.iloc[0]["low"] == 462.8


def test_short_hk_code_is_zero_padded(monkeypatch) -> None:
    urls: list[str] = []
    _patch_http(monkeypatch, urls, _hk_kline_payload("hk00700"))

    result = tencent_loader.DataLoader().fetch(
        ["700.HK"], "2026-01-01", "2026-01-31",
    )

    assert "param=hk00700,day," in urls[0]
    assert "700.HK" in result
