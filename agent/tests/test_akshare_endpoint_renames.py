"""Keep adjusted/raw history and non-A-share readers working across renames."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from backtest.loaders.akshare_loader import DataLoader


@pytest.mark.parametrize("current,legacy,method,code,args", [
    ("stock_zh_a_hist_em", "stock_zh_a_hist", "_fetch_a_share", "601398.SH", ("1D",)),
    ("stock_us_hist_em", "stock_us_hist", "_fetch_us", "AAPL.US", ()),
    ("stock_hk_hist_em", "stock_hk_hist", "_fetch_hk", "0700.HK", ()),
    ("fx_hist_em", "forex_hist_em", "_fetch_forex", "EURUSD", ()),
])
@pytest.mark.parametrize("renamed", [True, False])
def test_renamed_and_legacy_endpoints_preserve_bars(current, legacy, method, code, args, renamed):
    frame = pd.DataFrame({
        "日期": ["2026-11-13"], "开盘": [10.0], "收盘": [11.0],
        "最高": [12.0], "最低": [9.0], "成交量": [1234.0],
    })
    if method == "_fetch_forex":
        frame = frame.rename(columns={"开盘": "今开", "收盘": "最新价"})
    endpoint = Mock(return_value=frame)
    module = SimpleNamespace(**{current if renamed else legacy: endpoint})
    if renamed:
        # A broken current endpoint must not silently retry a legacy API.
        setattr(module, legacy, Mock(side_effect=AssertionError("legacy endpoint used")))
    result = getattr(DataLoader(), method)(module, code, "2026-11-01", "2026-11-16", *args)
    assert result.iloc[0]["close"] == 11.0
    assert result.iloc[0]["open"] == 10.0
    assert result.iloc[0]["volume"] == (0 if method == "_fetch_forex" else 1234)
    assert result.index[0] == pd.Timestamp("2026-11-13")
    if method != "_fetch_forex":
        assert endpoint.call_args.kwargs["adjust"] == "qfq"
        assert endpoint.call_args.kwargs["start_date"] == "20261101"
        assert endpoint.call_args.kwargs["end_date"] == "20261116"
    else:
        assert endpoint.call_args.kwargs == {"symbol": "EURUSD"}


@pytest.mark.parametrize("renamed", [True, False])
def test_raw_companion_uses_same_endpoint_without_adjustment(monkeypatch, renamed):
    frame = pd.DataFrame({
        "日期": ["2026-11-13"], "开盘": [10.0], "收盘": [11.0],
        "最高": [12.0], "最低": [9.0], "成交量": [1234.0],
    })
    endpoint = Mock(return_value=frame)
    module = SimpleNamespace(**{"stock_zh_a_hist_em" if renamed else "stock_zh_a_hist": endpoint})
    monkeypatch.setitem(sys.modules, "akshare", module)
    loader = DataLoader()
    adjusted = loader._fetch_a_share(module, "601398.SH", "2026-11-01", "2026-11-16", "1D")
    raw = loader._fetch_a_share_raw("601398.SH", "2026-11-01", "2026-11-16", "1D")
    assert [call.kwargs["adjust"] for call in endpoint.call_args_list] == ["qfq", ""]
    pd.testing.assert_frame_equal(adjusted, raw)


def test_current_endpoint_failure_is_not_retried_through_old_name():
    current = Mock(side_effect=RuntimeError("upstream unavailable"))
    legacy = Mock()
    module = SimpleNamespace(stock_zh_a_hist_em=current, stock_zh_a_hist=legacy)
    with pytest.raises(RuntimeError, match="upstream unavailable"):
        DataLoader()._fetch_a_share(module, "601398.SH", "2026-11-01", "2026-11-16", "1D")
    legacy.assert_not_called()


@pytest.mark.parametrize("current,legacy,method,code,args", [
    ("stock_zh_a_hist_em", "stock_zh_a_hist", "_fetch_a_share", "601398.SH", ("1D",)),
    ("stock_us_hist_em", "stock_us_hist", "_fetch_us", "AAPL.US", ()),
    ("stock_hk_hist_em", "stock_hk_hist", "_fetch_hk", "0700.HK", ()),
    ("fx_hist_em", "forex_hist_em", "_fetch_forex", "EURUSD", ()),
])
def test_installed_sdk_parses_wire_columns_and_adjustment(
    monkeypatch, current, legacy, method, code, args,
):
    """Exercise the installed SDK parser; only its HTTP transport is replaced."""
    ak = pytest.importorskip("akshare")
    endpoint = getattr(ak, current, None) or getattr(ak, legacy)
    module = importlib.import_module(endpoint.__module__)
    transport = getattr(module, "http", None) or module.requests
    line = "2026-11-13,10,11,12,9,1234,10000,3,2,1,0.1"
    if method == "_fetch_forex":
        line += ",0,0,0"
    response = SimpleNamespace(json=lambda: {"data": {
        "klines": [line], "code": "EURUSD", "name": "EURUSD",
    }})
    wire = Mock(return_value=response)
    monkeypatch.setattr(transport, "get", wire)
    loader = DataLoader()
    frame = getattr(loader, method)(ak, code, "2026-11-01", "2026-11-16", *args)
    assert frame.iloc[0]["open"] == 10
    assert frame.iloc[0]["close"] == 11
    assert frame.iloc[0]["volume"] == (0 if method == "_fetch_forex" else 1234)
    if method != "_fetch_forex":
        assert wire.call_args.kwargs["params"]["fqt"] == "1"
    if method == "_fetch_a_share":
        raw = loader._fetch_a_share_raw(code, "2026-11-01", "2026-11-16", "1D")
        assert wire.call_args.kwargs["params"]["fqt"] == "0"
        pd.testing.assert_frame_equal(frame, raw)
