"""Pin the shared checker to the health lane and every registered source."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.loader_health import check_frame
from backtest.loaders.registry import VALID_SOURCES
from tests.loader_contract import loader_contract_errors


CONTRACT_SUITES = {
    "akshare": "test_akshare_loader.py",
    "alphavantage": "test_alphavantage_loader.py",
    "baostock": "test_baostock_loader.py",
    "binance": "test_binance_fallback.py",
    "ccxt": "test_ccxt_loader_bounded.py",
    "eastmoney": "test_eastmoney_loader.py",
    "finnhub": "test_finnhub_loader.py",
    "fmp": "test_fmp_loader.py",
    "futu": "test_futu_loader.py",
    "gildata": "test_gildata_loader.py",
    "india_broker": "test_india_broker_loader.py",
    "local": "test_local_loader.py",
    "longbridge": "test_longbridge_loader.py",
    "mootdx": "test_mootdx_loader.py",
    "mt5": "test_mt5_loader.py",
    "nobitex": "test_nobitex_loader.py",
    "okx": "test_okx_loader_bounded.py",
    "pykrx": "test_pykrx_loader.py",
    "qveris": "test_qveris_loader.py",
    "sina": "test_sina_loader.py",
    "stooq": "test_stooq_loader.py",
    "tencent": "test_tencent_loader.py",
    "tickerall": "test_tickerall_loader.py",
    "tiingo": "test_tiingo_loader.py",
    "tushare": "test_tushare_loader.py",
    "wallex": "test_wallex_loader.py",
    "yahoo": "test_yahoo_loader.py",
    "yfinance": "test_yfinance_crypto.py",
}


def test_every_loader_has_a_canonical_contract_assertion():
    assert CONTRACT_SUITES.keys() == VALID_SOURCES - {"auto"}
    root = Path(__file__).parent
    for source, filename in CONTRACT_SUITES.items():
        tree = ast.parse((root / filename).read_text())
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "assert_loader_contract"
            for function in tree.body
            if isinstance(function, (ast.FunctionDef, ast.ClassDef))
            for node in ast.walk(function)
        ), source


@pytest.mark.parametrize("fault", [None, "empty_frame", "schema", "datetime_index", "index_order", "numeric_columns", "nonfinite_values", "invalid_prices_or_volume", "ohlc_order"])
def test_offline_contract_agrees_with_health_lane(fault):
    frame = pd.DataFrame(
        {"open": [10., 11.], "high": [12., 13.], "low": [9., 10.], "close": [11., 12.], "volume": [0., 5.]},
        index=pd.date_range("2026-10-01", periods=2, tz="UTC"),
    )
    if fault == "empty_frame":
        frame = frame.iloc[:0]
    elif fault == "schema":
        frame = frame.drop(columns="volume")
    elif fault == "datetime_index":
        frame.index = [1, 2]
    elif fault == "index_order":
        frame = frame.iloc[::-1]
    elif fault == "numeric_columns":
        frame["open"] = ["10", "11"]
    elif fault == "nonfinite_values":
        frame.loc[frame.index[0], "close"] = np.nan
    elif fault == "invalid_prices_or_volume":
        frame.loc[frame.index[0], "volume"] = -1.
    elif fault == "ohlc_order":
        frame.loc[frame.index[0], "high"] = 1.
    errors = loader_contract_errors(frame)
    live = check_frame(frame, today=pd.Timestamp("2026-10-02").date())
    assert errors == ([] if fault is None else [fault])
    assert live.get("reason") == fault
