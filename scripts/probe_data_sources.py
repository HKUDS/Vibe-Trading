#!/usr/bin/env python3
"""Probe free market-data sources and report which ones are reachable.

Runs anywhere (GitHub Actions runner, the isolated VM, a session sandbox) to
answer one question honestly: which data feeds can THIS environment pull?
Informational by design: exits 0 if at least one source works, 1 if none do.

Usage: python scripts/probe_data_sources.py
Deps:  pip install yfinance ccxt requests
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

TIMEOUT_S = 20


def _short(err: Exception) -> str:
    return f"{type(err).__name__}: {str(err)[:70]}"


def probe_yfinance(symbol: str):
    import yfinance as yf

    df = yf.Ticker(symbol).history(period="5d", interval="1d", timeout=TIMEOUT_S)
    if df.empty:
        raise RuntimeError("empty frame")
    return f"{len(df)} rows, last close {df['Close'].iloc[-1]:.2f}"


def probe_ccxt(exchange: str, symbol: str):
    import ccxt

    ex = getattr(ccxt, exchange)({"timeout": TIMEOUT_S * 1000})
    ticker = ex.fetch_ticker(symbol)
    return f"last {ticker['last']}"


def probe_stooq(symbol: str):
    import requests

    resp = requests.get(
        f"https://stooq.com/q/d/l/?s={symbol}&i=d", timeout=TIMEOUT_S
    )
    resp.raise_for_status()
    lines = resp.text.strip().splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"no data rows ({lines[:1]})")
    return f"{len(lines) - 1} rows, last: {lines[-1].split(',')[0]}"


PROBES = [
    ("yfinance BTC-USD", lambda: probe_yfinance("BTC-USD")),
    ("yfinance AAPL", lambda: probe_yfinance("AAPL")),
    ("ccxt binance BTC/USDT", lambda: probe_ccxt("binance", "BTC/USDT")),
    ("ccxt kraken BTC/USD", lambda: probe_ccxt("kraken", "BTC/USD")),
    ("ccxt okx BTC/USDT", lambda: probe_ccxt("okx", "BTC/USDT")),
    ("stooq AAPL.US daily", lambda: probe_stooq("aapl.us")),
]


def main() -> int:
    ok_count = 0
    print(f"{'source':26} status")
    print("-" * 60)
    for name, fn in PROBES:
        try:
            detail = fn()
            ok_count += 1
            print(f"{name:26} OK — {detail}")
        except Exception as err:  # noqa: BLE001 — report every failure kind
            print(f"{name:26} FAIL — {_short(err)}")
    print("-" * 60)
    print(f"summary: {ok_count}/{len(PROBES)} sources reachable")
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
