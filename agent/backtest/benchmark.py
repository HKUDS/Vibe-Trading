"""Benchmark ticker resolution and fetch for backtest comparison.

Provides a lightweight, zero-dependency way to fetch benchmark reference
data given a set of strategy codes and a data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from backtest.loaders.yfinance_loader import DataLoader as YfinanceLoader
from backtest.metrics import bar_returns, buy_and_hold_return


# -------------------------------------------------------------------
# Benchmark map: market type → default ticker
# -------------------------------------------------------------------

MARKET_BENCHMARKS: dict[str, Optional[str]] = {
    "us_equity":  "SPY",
    "hk_equity":  "HK.03100",   # Hang Seng China Enterprises ETF
    "ca_equity":  "XIC.TO",     # S&P/TSX Capped Composite ETF
    "a_share":    "000300.SH",  # CSI 300 (China A-share core index)
    "crypto":     "BTC-USDT",
    "futures":    "ES.CME",      # E-mini S&P 500 futures
    "forex":      None,         # no universal benchmark
}


@dataclass
class BenchmarkResult:
    ticker:     str
    ret_series: pd.Series       # per-bar returns, index = timestamps
    total_ret: float          # total return over the FETCHED period
    close:      pd.Series       # benchmark closes, index = timestamps

    def total_return_over(self, dates: pd.DatetimeIndex) -> Optional[float]:
        """Return the buy-and-hold return restricted to ``dates``.

        ``total_ret`` spans everything that was fetched, which is the requested
        ``start_date``..``end_date``. When the run declares a warm-up boundary
        the evaluated window is shorter than that, and grading a strategy over
        the short window against a benchmark measured over the long one is the
        mismatched-window error the warm-up boundary exists to prevent (#1240).

        Computed as a price relative rather than the compounded product of
        ``ret_series``, which is the only form that stays honest once a price
        series contains a non-positive prior close (#872).

        Args:
            dates: The evaluated bar index.

        Returns:
            The buy-and-hold return over the overlap, or ``None`` when fewer
            than two benchmark closes fall inside it.
        """
        window = self.close.reindex(dates).dropna()
        if len(window) < 2:
            return None
        return buy_and_hold_return(window)


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
        interval:       Bar interval (1m / 5m / 15m / 30m / 1H / 4H / 1D).
        explicit:       Override ticker (e.g. "SPY" passed via config).
        loader:         Loader of the configured data source. When given, the
                        benchmark is fetched through it first, falling back to
                        yfinance if it yields no data — except ``local``,
                        which fails closed to keep offline runs offline.

    Returns:
        BenchmarkResult with return series and total return, or None if no
        benchmark applies (forex, or fetch failure).
    """
    ticker = _resolve_ticker(strategy_codes, source, explicit)
    if ticker is None:
        return None

    offline = source == "local"
    if offline and getattr(loader, "name", None) != source:
        # The runtime fallback chain in fetch_data_map() may have swapped in a
        # network loader while config["source"] still says local — never fetch
        # the benchmark through it. Fail closed instead.
        loader = None

    try:
        bench_df = _fetch_benchmark(
            ticker, start_date, end_date, interval,
            loader=loader,
            allow_fallback=not offline,
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

    return BenchmarkResult(
        ticker=ticker, ret_series=ret_series, total_ret=total, close=close
    )


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def _resolve_ticker(
    codes:     list[str],
    source:    str,
    explicit:  Optional[str],
) -> Optional[str]:
    """Pick the benchmark ticker to use."""

    if explicit:
        return explicit

    # Infer market from source + first code pattern
    market = _infer_market(codes, source)
    ticker = MARKET_BENCHMARKS.get(market)

    # yfinance is the universal fallback for benchmark fetch
    # but it only works for global-equity market types
    if ticker and market not in {"us_equity", "hk_equity", "ca_equity"}:
        # Only use benchmark if we can actually fetch it
        pass

    return ticker


def _infer_market(codes: list[str], source: str) -> str:
    """Rough market inference from symbol patterns and source."""
    if not codes:
        return "us_equity"

    first = codes[0].upper()

    if first.endswith(".US"):
        return "us_equity"
    if first.endswith(".HK"):
        return "hk_equity"
    if first.endswith((".TO", ".V")):
        return "ca_equity"
    if first.endswith((".NS", ".BO")):
        return "india_equity"
    if first.endswith((".KS", ".KQ")):
        return "kr_equity"
    crypto_quotes = ("-USDT", "-USDC", "-USD", "-BTC", "-ETH")
    if source in ("okx", "ccxt", "binance") or "/" in first or first.endswith(crypto_quotes):
        return "crypto"
    if source in ("tushare", "akshare"):
        if first.isdigit() and len(first) == 6:
            return "a_share"
        if first.startswith(("IF", "IC", "IH", "IM", "T", "TF")):
            return "futures"
        return "a_share"

    return "us_equity"


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
    closed instead of making a network request).
    """
    if loader is not None:
        try:
            df = _extract_frame(
                loader.fetch([ticker], start_date, end_date, interval=interval),
                ticker,
            )
        except Exception:
            df = pd.DataFrame()
        if not df.empty:
            return df

    if not allow_fallback:
        return pd.DataFrame()

    result = YfinanceLoader().fetch([ticker], start_date, end_date, interval=interval)
    return _extract_frame(result, ticker)


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
