"""Benchmark ticker resolution and fetch for backtest comparison.

Provides a lightweight, zero-dependency way to fetch benchmark reference
data given a set of strategy codes and a data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from backtest.engines._market_hooks import matched_market, strip_local_prefix
from backtest.loaders.base import resample_bars, source_interval
from backtest.loaders.registry import is_no_network_fallback_source
from backtest.loaders.yfinance_loader import DataLoader as YfinanceLoader
from backtest.metrics import bar_returns, buy_and_hold_return, entry_returns


# -------------------------------------------------------------------
# Benchmark map: market type → default ticker
# -------------------------------------------------------------------

MARKET_BENCHMARKS: dict[str, Optional[str]] = {
    "us_equity":  "SPY",
    "hk_equity":  "2828.HK",    # Hang Seng China Enterprises Index ETF
    "ca_equity":  "XIC.TO",     # S&P/TSX Capped Composite ETF
    "br_equity":  "BOVA11.SA",  # iShares Ibovespa ETF
    "a_share":    "000300.SH",  # CSI 300 (China A-share core index)
    "uk_equity": "^FTSE",
    "india_equity": "^NSEI",
    "kr_equity": "^KS11",
    "ar_equity": "^MERV",
    "crypto":     "BTC-USDT",
    "futures":    None,         # no common reference across contracts and venues
    "forex":      None,         # no universal benchmark
}


@dataclass
class BenchmarkResult:
    ticker:     str
    ret_series: pd.Series       # per-bar returns, index = timestamps
    total_ret: float          # total return over the FETCHED period
    close:      pd.Series       # benchmark closes, index = timestamps
    open:       Optional[pd.Series] = None  # benchmark opens, same index

    def total_return_over(self, dates: pd.DatetimeIndex) -> Optional[float]:
        """Return the buy-and-hold return restricted to ``dates``.

        ``total_ret`` spans everything that was fetched, which is the requested
        ``start_date``..``end_date``. When the run declares a warm-up boundary
        the evaluated window is shorter than that, and grading a strategy over
        the short window against a benchmark measured over the long one is the
        mismatched-window error the warm-up boundary exists to prevent (#1240).

        The position is bought at the open of the first benchmark bar inside
        the window, the price the engine fills the strategy at (see
        ``metrics.entry_returns``), or at that bar's close when it has no
        usable open. Computed as a price relative rather than the compounded
        product of ``ret_series``, which is the only form that stays honest
        once a price series contains a non-positive prior close (#872).

        Args:
            dates: The evaluated bar index.

        Returns:
            The buy-and-hold return over the overlap, or ``None`` when fewer
            than two benchmark closes fall inside it.
        """
        window = self.close.reindex(dates).dropna()
        if len(window) < 2:
            return None
        entry = self._entry_open(window.index[0])
        if entry is None:
            return buy_and_hold_return(window)
        last = float(window.iloc[-1])
        return last / entry - 1.0 if np.isfinite(last) else None

    def returns_over(self, dates: pd.DatetimeIndex) -> pd.Series:
        """Per-bar returns of the same position on the evaluated bar index.

        Args:
            dates: The evaluated bar index.

        Returns:
            Returns on ``dates`` whose compounded total equals
            :meth:`total_return_over` while prices are positive.
        """
        close = self.close.reindex(dates)
        opens = self.open.reindex(dates) if self.open is not None else None
        return entry_returns(close, opens, label=f"benchmark {self.ticker}")

    def _entry_open(self, timestamp: Any) -> Optional[float]:
        if self.open is None or timestamp not in self.open.index:
            return None
        value = float(self.open.loc[timestamp])
        return value if np.isfinite(value) and value > 0 else None


def resolve_benchmark(
    strategy_codes: list[str],
    source:       str,
    start_date:   str,
    end_date:     str,
    interval:     str = "1D",
    explicit:     Optional[str] = None,
    loader:       Optional[Any] = None,
) -> Optional[BenchmarkResult]:
    """Resolve the appropriate benchmark ticker and fetch its return series.

    Args:
        strategy_codes: Instruments being backtested (used for market inference).
        source:         Data source name (tushare / yfinance / okx / akshare / ccxt).
        start_date:     Backtest start date.
        end_date:       Backtest end date.
        interval:       Bar interval (1m / 5m / 15m / 30m / 1H / 4H / 1D / 1W / 1M).
        explicit:       Override ticker (e.g. "SPY" passed via config).
        loader:         Loader of the configured data source. When given, the
                        benchmark is fetched through it first, falling back to
                        yfinance if it yields no data, except sources whose
                        contract prohibits a fallback to a different source.

    Returns:
        BenchmarkResult with return series and total return, or None if no
        benchmark applies (forex, or fetch failure).
    """
    ticker = explicit or default_benchmark(strategy_codes, source)
    if ticker is None:
        return None

    source_bound = is_no_network_fallback_source(source)
    if source_bound and getattr(loader, "name", None) != source:
        # Do not let a swapped loader bypass the configured source's boundary:
        # local must stay offline, and source-specific quote currencies and
        # explicit provider choices must not silently change for a benchmark.
        loader = None

    try:
        bench_df = _fetch_benchmark(
            ticker, start_date, end_date, interval,
            loader=loader,
            allow_fallback=not source_bound,
        )
    except Exception:
        return None

    if bench_df.empty or "close" not in bench_df.columns:
        return None

    close = bench_df["close"].dropna()
    if len(close) < 2:
        return None

    ret_series = bar_returns(close, label=f"benchmark {ticker}")
    # Price relative, not the compounded product: identical while prices are
    # positive, and it is the only one of the two that stays honest once they
    # are not (#872).
    total = buy_and_hold_return(close)
    if total is None:
        return None

    opens = bench_df["open"].reindex(close.index) if "open" in bench_df.columns else None
    return BenchmarkResult(
        ticker=ticker, ret_series=ret_series, total_ret=total, close=close, open=opens
    )


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def default_benchmark(codes: list[str], source: str) -> str | None:
    """Select a default only when all evaluated instruments identify one market."""
    market = _infer_market(codes, source)
    return MARKET_BENCHMARKS.get(market) if market else None


def _infer_market(codes: list[str], source: str) -> str | None:
    """Use the engine's market rules without its default for unknown instruments."""
    markets = set()
    for code in codes:
        symbol = strip_local_prefix(code).strip().upper()
        # Yahoo uses .SS for Shanghai. Bare six-digit codes are unambiguous
        # on the Chinese stock sources, but not on a generic loader.
        if symbol.endswith(".SS") and symbol[:-3].isdigit():
            symbol = symbol[:-3] + ".SH"
        elif source in {"akshare", "tushare", "baostock"} and len(symbol) == 6 and symbol.isdigit():
            markets.add("a_share")
            continue
        markets.add(matched_market(symbol))
    return markets.pop() if len(markets) == 1 else None


def _fetch_benchmark(
    ticker:    str,
    start_date: str,
    end_date:   str,
    interval:   str,
    loader:    Optional[Any] = None,
    allow_fallback: bool = True,
) -> pd.DataFrame:
    """Fetch benchmark OHLCV data.

    Tries the configured source's loader first (when given). Falls back to
    yfinance (single symbol, no auth) when no loader is given or it yields
    no data — unless ``allow_fallback`` is False (offline sources fail
    closed instead of making a network request). Weekly and monthly bars are
    built from daily ones the way the strategy's are (#1479).
    """
    fetch_as = source_interval(interval)
    if loader is not None:
        try:
            df = _extract_frame(
                loader.fetch([ticker], start_date, end_date, interval=fetch_as),
                ticker,
            )
        except Exception:
            df = pd.DataFrame()
        if not df.empty:
            return resample_bars(df, interval)

    if not allow_fallback:
        return pd.DataFrame()

    result = YfinanceLoader().fetch([ticker], start_date, end_date, interval=fetch_as)
    return resample_bars(_extract_frame(result, ticker), interval)


def _extract_frame(result: Any, ticker: str) -> pd.DataFrame:
    """Normalise a loader fetch result to a single DataFrame."""
    if isinstance(result, dict):
        df = result.get(ticker)
    elif isinstance(result, pd.DataFrame):
        df = result
    else:
        return pd.DataFrame()

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return pd.DataFrame()

    return df
