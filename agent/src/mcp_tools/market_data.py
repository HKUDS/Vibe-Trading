"""MCP market-data tool (get_market_data) with row-capping helpers."""

from __future__ import annotations

from fastmcp import FastMCP

from src.market_data import (
    DEFAULT_MAX_ROWS,
    cap_rows,
    detect_source,
    fetch_market_data_json,
    get_loader,
)


def _detect_source(code: str) -> str:
    return detect_source(code)


def _get_loader(source: str):
    """Get loader class via registry with fallback support."""
    return get_loader(source)


def _cap_rows(records: list, max_rows: int) -> list | dict[str, object]:
    """Bound a per-symbol row list to keep the MCP payload within budget.

    max_rows==0 disables the cap (full list, unchanged shape). A negative
    max_rows is invalid and enforces the default cap (never unbounded).
    Otherwise an oversized symbol is *evenly strided* — every step-th bar,
    with the last bar pinned — so the returned series spans the full range
    (no head+tail gap, no synthetic ``_gap`` sentinel). Symbols within the
    cap are returned unchanged (plain list) — small queries are
    byte-identical.
    """
    return cap_rows(records, max_rows)


def get_market_data(
    codes: list[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    interval: str = "1D",
    max_rows: int = DEFAULT_MAX_ROWS,
) -> str:
    """Fetch OHLCV market data for stocks, crypto, or mixed symbols.

    Supported sources:
    - "yfinance": HK/US equities (free, e.g. AAPL.US, 700.HK)
    - "okx": cryptocurrency (free, e.g. BTC-USDT, ETH-USDT)
    - "tushare": China A-shares (requires TUSHARE_TOKEN, e.g. 000001.SZ)
    - "baostock": China A-shares via TCP protocol, bypasses HTTP CDN blocks (e.g. 000001.SZ, 601595.SH)
    - "tencent": China A-shares via Tencent Finance API (e.g. 000001.SZ, 601595.SH)
    - "akshare": A-shares, US, HK, futures, forex (free, e.g. 000001.SZ, AAPL.US)
    - "ccxt": crypto from 100+ exchanges (free, e.g. BTC/USDT)
    - "mt5": forex/metals from a local MetaTrader 5 terminal (Windows; e.g. EUR/USD, XAUUSD.FX)
    - "auto": auto-detect based on symbol format (with fallback)

    Args:
        codes: List of symbols (e.g. ["AAPL.US", "BTC-USDT", "000001.SZ"]).
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        source: Data source ("auto", "yfinance", "okx", "tushare", "baostock", "tencent", "akshare", "ccxt").
        interval: Bar size (1m/5m/15m/30m/1H/4H/1D, default "1D").
        max_rows: Per-symbol row cap (default 250) so the response stays
            within the MCP token budget. A symbol exceeding it returns an
            even-stride downsample (every step-th bar, last bar pinned)
            plus truncation metadata. Set max_rows=0 for all rows
            (unbounded, legacy behavior).
    """
    return fetch_market_data_json(
        codes=codes,
        start_date=start_date,
        end_date=end_date,
        source=source,
        interval=interval,
        max_rows=max_rows,
        loader_resolver=_get_loader,
    )


def register(mcp: FastMCP) -> None:
    """Register the market-data tool with the FastMCP instance."""
    mcp.tool()(get_market_data)
