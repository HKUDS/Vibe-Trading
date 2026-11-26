"""Unadjusted (raw) A-share bars on request — owner decision 2026-11-26.

Asked for Kweichow Moutai's unadjusted September 2025 high/low, real-model
runs found every A-share source in the chain serving forward-adjusted bars
and either answered with them or spent 45 rounds writing a private fetcher.
``get_market_data(adjustment="raw")`` now asks the chain for unadjusted bars:
a source that can serve them is asked to (its request parameter pinned here),
a source that cannot refuses so the chain moves on, every served frame states
the adjustment actually applied, and the opt-in loader cache keeps raw and
adjusted series apart. Omitting the parameter is today's behaviour exactly.

All payloads are fixtures; no test opens a socket.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.loaders import (
    akshare_loader,
    baostock_loader,
    eastmoney_client,
    eastmoney_loader,
    tencent_loader,
    tushare as tushare_loader,
)

# Moutai, the first two September 2025 sessions, unadjusted (2025-09-01 and
# 2025-09-02 bars as Yahoo serves them unadjusted) and a forward-adjusted
# companion offset by an invented dividend so the two can never be confused.
_RAW_ROWS = [
    ["2025-09-01", "1480.00", "1475.01", "1488.00", "1470.00", "30000"],
    ["2025-09-02", "1475.01", "1478.50", "1484.00", "1466.66", "31000"],
]
_QFQ_ROWS = [[r[0], *(f"{float(v) - 25.0:.2f}" for v in r[1:5]), r[5]] for r in _RAW_ROWS]
_RAW_CLOSES = [1475.01, 1478.50]


class _FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _tencent_http(monkeypatch, urls: list[str]) -> None:
    """Answer fqkline with qfqday rows and kline/kline with raw day rows."""

    def fake_urlopen(req, timeout=None, **kwargs):  # noqa: ANN001
        urls.append(req.full_url)
        key = "qfqday" if "/fqkline/" in req.full_url else "day"
        rows = _QFQ_ROWS if key == "qfqday" else _RAW_ROWS
        return _FakeResponse(json.dumps({"code": 0, "data": {"sh600519": {key: rows}}}))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _passthrough_cache(monkeypatch, module, seen: list) -> None:
    def cached(**kwargs):
        seen.append(kwargs["fields"])
        return kwargs["fetch"]()

    monkeypatch.setattr(module, "cached_loader_fetch", cached)


def _enable_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "1")
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE_ROOT", str(tmp_path / "loader-cache"))


def _bars(closes, *, adjustment=None, start="2025-09-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(closes), freq="B", name="trade_date")
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 5 for c in closes],
            "low": [c - 5 for c in closes],
            "close": closes,
            "volume": [100.0] * len(closes),
        },
        index=index,
    )
    if adjustment is not None:
        frame.attrs["adjustment"] = adjustment
    return frame


# ---------------------------------------------------------------------------
# Tencent: raw reads kline/kline (no qfq suffix); default unchanged
# ---------------------------------------------------------------------------


def test_tencent_raw_request_reads_only_the_unadjusted_endpoint(monkeypatch):
    urls: list[str] = []
    fields: list = []
    _tencent_http(monkeypatch, urls)
    _passthrough_cache(monkeypatch, tencent_loader, fields)

    out = tencent_loader.DataLoader().fetch(
        ["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw"
    )

    frame = out["600519.SH"]
    assert len(urls) == 1
    assert "/kline/kline?" in urls[0] and ",qfq" not in urls[0]
    assert frame["close"].tolist() == _RAW_CLOSES
    assert frame.attrs["adjustment"] == "raw"
    assert fields == [["raw"]]


def test_tencent_default_request_is_unchanged(monkeypatch):
    urls: list[str] = []
    fields: list = []
    _tencent_http(monkeypatch, urls)
    _passthrough_cache(monkeypatch, tencent_loader, fields)

    out = tencent_loader.DataLoader().fetch(["600519.SH"], "2025-09-01", "2025-09-02")

    assert "/fqkline/get?" in urls[0] and urls[0].endswith(",qfq")
    assert "/kline/kline?" in urls[1]
    assert fields == [None, ["raw"]]
    assert out["600519.SH"].attrs.get("adjustment") != "raw"


# ---------------------------------------------------------------------------
# Eastmoney: raw sends fqt=0 only; default fqt=1 then the fqt=0 companion
# ---------------------------------------------------------------------------


def _eastmoney_rows(rows):
    return [
        {"trade_date": r[0], "open": float(r[1]), "close": float(r[2]), "high": float(r[3]),
         "low": float(r[4]), "volume": float(r[5]), "amount": 1.0}
        for r in rows
    ]


def _eastmoney_http(monkeypatch, fqts: list[int]) -> None:
    monkeypatch.setattr(eastmoney_client, "resolve_secid", lambda code: "1.600519")

    def fetch_kline(secid, *, klt, fqt=1, beg="0", end="20500101"):
        fqts.append(fqt)
        return _eastmoney_rows(_RAW_ROWS if fqt == 0 else _QFQ_ROWS)

    monkeypatch.setattr(eastmoney_client, "fetch_kline", fetch_kline)


def test_eastmoney_raw_request_sends_fqt_0_only(monkeypatch):
    fqts: list[int] = []
    fields: list = []
    _eastmoney_http(monkeypatch, fqts)
    _passthrough_cache(monkeypatch, eastmoney_loader, fields)

    out = eastmoney_loader.DataLoader().fetch(
        ["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw"
    )

    assert fqts == [0]
    assert fields == [["raw"]]
    assert out["600519.SH"]["close"].tolist() == _RAW_CLOSES
    assert out["600519.SH"].attrs["adjustment"] == "raw"


def test_eastmoney_default_request_is_unchanged(monkeypatch):
    fqts: list[int] = []
    fields: list = []
    _eastmoney_http(monkeypatch, fqts)
    _passthrough_cache(monkeypatch, eastmoney_loader, fields)

    eastmoney_loader.DataLoader().fetch(["600519.SH"], "2025-09-01", "2025-09-02")

    assert fqts == [1, 0]
    assert fields == [None, ["raw"]]


# ---------------------------------------------------------------------------
# BaoStock: raw sends adjustflag="3" (不复权); default "2" (前复权)
# ---------------------------------------------------------------------------


def _fake_baostock(monkeypatch, flags: list[str]) -> None:
    class _Result:
        error_code = "0"
        error_msg = ""

        def __init__(self, rows):
            self._rows = list(rows)

        def next(self):
            return bool(self._rows)

        def get_row_data(self):
            return self._rows.pop(0)

    def query(code, fields, *, start_date, end_date, frequency, adjustflag):
        flags.append(adjustflag)
        rows = _RAW_ROWS if adjustflag == "3" else _QFQ_ROWS
        # date,open,high,low,close,volume(shares),amount
        return _Result([[r[0], r[1], r[3], r[4], r[2], str(float(r[5]) * 100), "1"] for r in rows])

    fake = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        logout=lambda: None,
        query_history_k_data_plus=query,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr(
        baostock_loader, "_baostock_socket_guard", lambda timeout: contextlib.nullcontext(True)
    )


def test_baostock_raw_request_sends_adjustflag_3(monkeypatch):
    flags: list[str] = []
    _fake_baostock(monkeypatch, flags)

    out = baostock_loader.DataLoader().fetch(
        ["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw"
    )

    assert flags == ["3"]
    assert out["600519.SH"]["close"].tolist() == _RAW_CLOSES
    assert out["600519.SH"].attrs["adjustment"] == "raw"


def test_baostock_default_request_is_unchanged(monkeypatch):
    flags: list[str] = []
    _fake_baostock(monkeypatch, flags)

    out = baostock_loader.DataLoader().fetch(["600519.SH"], "2025-09-01", "2025-09-02")

    assert flags == ["2"]
    assert "adjustment" not in out["600519.SH"].attrs


def test_baostock_cache_keeps_raw_and_adjusted_apart(monkeypatch, tmp_path):
    _enable_cache(monkeypatch, tmp_path)
    flags: list[str] = []
    _fake_baostock(monkeypatch, flags)
    loader = baostock_loader.DataLoader()

    raw = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw")["600519.SH"]
    adjusted = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02")["600519.SH"]
    raw_again = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw")["600519.SH"]
    adjusted_again = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02")["600519.SH"]

    assert flags == ["3", "2"]  # one query per caliber, then cache hits
    assert raw_again["close"].tolist() == raw["close"].tolist() == _RAW_CLOSES
    assert adjusted_again["close"].tolist() == adjusted["close"].tolist() != _RAW_CLOSES
    assert raw_again.attrs["adjustment"] == "raw"
    assert len(list((tmp_path / "loader-cache" / "baostock").glob("*.parquet"))) == 2


# ---------------------------------------------------------------------------
# AKShare: raw sends adjust="" only; default "qfq" then the "" companion
# ---------------------------------------------------------------------------


def _fake_akshare(monkeypatch, adjusts: list[str]) -> SimpleNamespace:
    def history(*, symbol, period, start_date, end_date, adjust):
        adjusts.append(adjust)
        rows = _RAW_ROWS if adjust == "" else _QFQ_ROWS
        return pd.DataFrame(
            {"日期": [r[0] for r in rows], "开盘": [float(r[1]) for r in rows],
             "收盘": [float(r[2]) for r in rows], "最高": [float(r[3]) for r in rows],
             "最低": [float(r[4]) for r in rows], "成交量": [float(r[5]) for r in rows]}
        )

    fake = SimpleNamespace(stock_zh_a_hist_em=history, fund_etf_hist_sina=MagicMock())
    monkeypatch.setitem(sys.modules, "akshare", fake)
    return fake


def test_akshare_raw_request_sends_empty_adjust_only(monkeypatch):
    adjusts: list[str] = []
    fields: list = []
    _fake_akshare(monkeypatch, adjusts)
    _passthrough_cache(monkeypatch, akshare_loader, fields)

    out = akshare_loader.DataLoader().fetch(
        ["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw"
    )

    assert adjusts == [""]
    assert fields == [["raw"]]
    assert out["600519.SH"]["close"].tolist() == _RAW_CLOSES
    assert out["600519.SH"].attrs["adjustment"] == "raw"


def test_akshare_default_request_is_unchanged(monkeypatch):
    adjusts: list[str] = []
    fields: list = []
    _fake_akshare(monkeypatch, adjusts)
    _passthrough_cache(monkeypatch, akshare_loader, fields)

    akshare_loader.DataLoader().fetch(["600519.SH"], "2025-09-01", "2025-09-02")

    assert adjusts == ["qfq", ""]
    assert fields == [None, ["raw"]]


def test_akshare_refuses_a_raw_etf_it_cannot_serve(monkeypatch):
    """The Sina ETF endpoint's caliber is unmeasured: refuse, never guess."""
    adjusts: list[str] = []
    fake = _fake_akshare(monkeypatch, adjusts)
    loader = akshare_loader.DataLoader()

    out = loader.fetch(["510300.SH"], "2025-09-01", "2025-09-02", adjustment="raw")

    assert out == {}
    assert loader.fetch_errors == {"510300.SH": "adjustment_unsupported"}
    fake.fund_etf_hist_sina.assert_not_called()


# ---------------------------------------------------------------------------
# Tushare: raw skips apply_qfq (daily is unadjusted); default adjusts
# ---------------------------------------------------------------------------


def _tushare_loader() -> tushare_loader.DataLoader:
    loader = object.__new__(tushare_loader.DataLoader)
    loader.api = MagicMock()
    loader.api.daily.return_value = pd.DataFrame({
        "ts_code": ["600519.SH"] * 2,
        "trade_date": ["20250901", "20250902"],
        "open": [1480.0, 1475.01], "high": [1488.0, 1484.0], "low": [1470.0, 1466.66],
        "close": _RAW_CLOSES, "vol": [30000.0, 31000.0],
    })
    # A factor step on the last bar, so an adjusted frame differs from raw.
    loader.api.adj_factor.return_value = pd.DataFrame({
        "ts_code": ["600519.SH"] * 2, "trade_date": ["20250901", "20250902"], "adj_factor": [1.0, 2.0],
    })
    return loader


def test_tushare_raw_request_skips_the_adjustment_factor(monkeypatch):
    loader = _tushare_loader()

    out = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw")

    loader.api.adj_factor.assert_not_called()
    assert out["600519.SH"]["close"].tolist() == _RAW_CLOSES
    assert out["600519.SH"].attrs["adjustment"] == "raw"


def test_tushare_default_request_is_unchanged(monkeypatch):
    loader = _tushare_loader()

    out = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02")

    loader.api.adj_factor.assert_called_once()
    assert out["600519.SH"]["close"].tolist() == [1475.01 / 2, 1478.50]


def test_tushare_refuses_raw_minute_bars(monkeypatch):
    loader = _tushare_loader()

    out = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02", interval="5m", adjustment="raw")

    assert out == {}
    assert loader.fetch_errors == {"600519.SH": "adjustment_unsupported"}
    loader.api.stk_mins.assert_not_called()


def test_tushare_cache_keeps_raw_and_adjusted_apart(monkeypatch, tmp_path):
    _enable_cache(monkeypatch, tmp_path)
    loader = _tushare_loader()

    raw = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw")["600519.SH"]
    adjusted = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02")["600519.SH"]
    raw_again = loader.fetch(["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw")["600519.SH"]

    assert loader.api.daily.call_count == 2
    assert raw["close"].tolist() == raw_again["close"].tolist() == _RAW_CLOSES
    assert adjusted["close"].tolist() != _RAW_CLOSES
    assert raw_again.attrs["adjustment"] == "raw"


def test_tencent_raw_request_never_reads_the_adjusted_cache_entry(monkeypatch, tmp_path):
    from backtest.loaders.base import loader_cache_put

    _enable_cache(monkeypatch, tmp_path)
    for fields, closes in ((None, [1.0, 2.0]), (["raw"], _RAW_CLOSES)):
        loader_cache_put(source="tencent", symbol="600519.SH", timeframe="1D",
                         start_date="2025-09-01", end_date="2025-09-02", fields=fields,
                         frame=_bars(closes), source_revision=tencent_loader._CACHE_REVISION)
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=AssertionError("network")))

    out = tencent_loader.DataLoader().fetch(
        ["600519.SH"], "2025-09-01", "2025-09-02", adjustment="raw"
    )

    assert out["600519.SH"]["close"].tolist() == _RAW_CLOSES
    assert out["600519.SH"].attrs["adjustment"] == "raw"


# ---------------------------------------------------------------------------
# Shared fetch path: honour, refuse, verify the served caliber
# ---------------------------------------------------------------------------


class _AdjustedOnly:
    """Yahoo-like: serves only adjusted A-share bars, knows no raw request."""

    name = "yahoo"
    volume_units = {}
    calls: list = []

    def is_available(self):
        return True

    def fetch(self, codes, start, end, interval="1D"):
        type(self).calls.append(list(codes))
        return {code: _bars([9.0, 9.5]) for code in codes}


class _RawCapable:
    """Tencent-like: declares raw A-share bars and honours the request."""

    name = "tencent"
    volume_units = {"a_share": "lots"}
    raw_markets = frozenset({"a_share"})
    requests: list = []
    stamp = "raw"

    def is_available(self):
        return True

    def fetch(self, codes, start, end, *, interval="1D", adjustment=None):
        type(self).requests.append(adjustment)
        stamp = type(self).stamp if adjustment == "raw" else "split_dividend"
        return {code: _bars(_RAW_CLOSES, adjustment=stamp) for code in codes}


@pytest.fixture
def chain(monkeypatch):
    from backtest.loaders import registry
    from src import market_data

    _AdjustedOnly.calls = []
    _RawCapable.requests = []
    _RawCapable.stamp = "raw"
    classes = {"yahoo": _AdjustedOnly, "tencent": _RawCapable}
    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "refresh_source_order_overrides", lambda: None)
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", dict(classes))
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["yahoo", "tencent"]})
    monkeypatch.setattr(market_data, "detect_source", lambda code: "yahoo")
    return classes


def _direct(**kwargs):
    from backtest.loaders import registry
    from src.market_data import fetch_market_data

    return fetch_market_data(
        codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02",
        include_provenance=True, loader_resolver=lambda name: registry.LOADER_REGISTRY[name],
        **kwargs,
    )


def test_raw_request_skips_a_source_that_cannot_serve_raw(chain):
    out = _direct(adjustment="raw")

    assert _AdjustedOnly.calls == []
    assert _RawCapable.requests == ["raw"]
    assert [row["close"] for row in out["600519.SH"]] == _RAW_CLOSES
    assert out["_provenance"]["600519.SH"]["source"] == "tencent"
    assert out["_provenance"]["600519.SH"]["adjustment"] == "raw"


def test_raw_request_drops_a_frame_that_is_not_raw(chain):
    _RawCapable.stamp = "split_dividend"  # a loader that ignored the request

    out = _direct(adjustment="raw")

    assert "600519.SH" not in out
    assert out["_unresolved"] == ["600519.SH"]
    reasons = [a["reason"] for a in out["_diagnostics"]["600519.SH"]["attempts"]]
    assert reasons == ["adjustment_unsupported", "adjustment_unsupported"]


def test_raw_request_serves_a_source_whose_default_is_already_raw(chain):
    """A price index has no corporate actions: every source's level is raw."""
    from backtest.loaders import registry
    from src.market_data import fetch_market_data

    out = fetch_market_data(
        codes=["000300.SH"], start_date="2025-09-01", end_date="2025-09-02", adjustment="raw",
        include_provenance=True, loader_resolver=lambda name: registry.LOADER_REGISTRY[name],
    )

    assert _AdjustedOnly.calls == [["000300.SH"]]
    assert out["_provenance"]["000300.SH"]["adjustment"] == "raw"


def test_default_request_passes_no_adjustment_to_any_loader(chain):
    out = _direct()

    assert _AdjustedOnly.calls == [["600519.SH"]]
    assert _RawCapable.requests == []
    assert out["_provenance"]["600519.SH"]["source"] == "yahoo"
    assert out["_provenance"]["600519.SH"]["adjustment"] == "split_dividend"


def test_unknown_adjustment_is_refused(chain):
    with pytest.raises(ValueError, match="adjustment"):
        _direct(adjustment="qfq")


# Captured on the unmodified code (8a28fd0a0) for this exact request.
_DEFAULT_JSON_SHA256 = "44eac17a28fa5d5e6a013f8348a55329cdb3685fac6109b78161ea0b2720b7f9"
_DEFAULT_TOOL_SHA256 = "b4e923c48c863108110a920995fcef4e19224e9de09ff3b0d6519f9b854cb849"


def test_default_json_is_byte_identical_to_before(chain):
    from backtest.loaders import registry
    from src.market_data import fetch_market_data_json

    text = fetch_market_data_json(
        codes=["600519.SH", "000300.SH"], start_date="2025-09-01", end_date="2025-09-02",
        include_provenance=True, loader_resolver=lambda name: registry.LOADER_REGISTRY[name],
    )

    assert hashlib.sha256(text.encode()).hexdigest() == _DEFAULT_JSON_SHA256


def test_default_tool_output_is_byte_identical_to_before(chain):
    from backtest.loaders import registry

    text = _tool().execute(
        codes=["600519.SH", "000300.SH"], start_date="2025-09-01", end_date="2025-09-02",
        loader_resolver=lambda name: registry.LOADER_REGISTRY[name],
    )

    assert hashlib.sha256(text.encode()).hexdigest() == _DEFAULT_TOOL_SHA256


# ---------------------------------------------------------------------------
# Tool, gateway and MCP surfaces
# ---------------------------------------------------------------------------


def _tool():
    from src.config.accessor import get_env_config
    from src.tools.market_data_tool import MarketDataTool
    from src.tools.path_utils import FileRoots

    return MarketDataTool(roots=FileRoots.from_config(get_env_config().api))


def test_tool_schema_offers_raw_adjustment():
    from src.tools.market_data_tool import MarketDataTool

    schema = MarketDataTool.parameters["properties"]["adjustment"]
    assert schema["enum"] == ["raw"]
    assert "adjustment" not in MarketDataTool.parameters["required"]


def test_tool_rejects_an_unknown_adjustment():
    out = json.loads(_tool().execute(
        codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02", adjustment="qfq",
    ))
    assert out["ok"] is False and "adjustment" in out["error"]


def test_tool_names_the_raw_refusal_when_no_source_can_serve(chain):
    from backtest.loaders import registry

    registry.FALLBACK_CHAINS["a_share"] = ["yahoo"]
    out = json.loads(_tool().execute(
        codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02", adjustment="raw",
        loader_resolver=lambda name: registry.LOADER_REGISTRY[name],
    ))

    assert out["status"] == "error" and out["error_code"] == "no_market_data"
    assert "adjustment='raw'" in out["error"]
    assert "600519.SH" not in out
    assert _AdjustedOnly.calls == []


def test_gateway_keys_and_serves_raw_separately(chain, tmp_path):
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway

    gateway = MarketDataGateway(Config(tmp_path))
    try:
        raw = gateway.bars(codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02",
                           adjustment="raw")
        default = gateway.bars(codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02")
    finally:
        gateway.close()

    assert raw["data"]["_provenance"]["600519.SH"]["adjustment"] == "raw"
    assert raw["data"]["_provenance"]["600519.SH"]["source"] == "tencent"
    # The default request is a separate gateway entry: it reaches a loader
    # again, without the raw request, and is served adjusted. (Which source
    # serves it is the router's health order: tencent just succeeded.)
    assert default["data"]["_provenance"]["600519.SH"]["adjustment"] == "split_dividend"
    assert _RawCapable.requests[0] == "raw"
    assert "raw" not in _RawCapable.requests[1:]
    assert len(_RawCapable.requests) + len(_AdjustedOnly.calls) == 2


def test_gateway_reports_the_raw_refusal_reason(chain, tmp_path):
    from backtest.loaders import registry
    from src.data_gateway.config import Config
    from src.data_gateway.service import MarketDataGateway

    registry.FALLBACK_CHAINS["a_share"] = ["yahoo"]
    gateway = MarketDataGateway(Config(tmp_path))
    try:
        out = gateway.bars(codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02",
                           adjustment="raw")
    finally:
        gateway.close()

    assert out["data"]["_unresolved"] == ["600519.SH"]
    assert {a["reason"] for a in out["data"]["_diagnostics"]["600519.SH"]} == {"adjustment_unsupported"}


def test_mcp_get_market_data_forwards_adjustment(monkeypatch):
    import mcp_server

    gmd = getattr(mcp_server.get_market_data, "fn", None) or mcp_server.get_market_data
    monkeypatch.setattr(mcp_server, "_get_loader", lambda src: _RawCapable)
    _RawCapable.requests = []

    out = json.loads(gmd(codes=["600519.SH"], start_date="2025-09-01", end_date="2025-09-02",
                         source="tencent", adjustment="raw"))

    assert _RawCapable.requests == ["raw"]
    assert out["_provenance"]["600519.SH"]["adjustment"] == "raw"
