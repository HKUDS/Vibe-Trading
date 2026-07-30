"""Cross-asset correlation matrix computation.

Computes pairwise Pearson or Spearman correlation of daily returns
over a configurable lookback window. Used by the /correlation API endpoint.
"""

from __future__ import annotations

import logging
from typing import Dict, Literal

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


def infer_market(code: str) -> str:
    """Infer market key from a ticker symbol.

    Resolution order:

    1. Crypto pair spellings (``BTC-USDT``, ``ETH/USD`` …).
    2. Explicit exchange suffix — always authoritative (``.HK``, ``.SH``/
       ``.SZ``/``.BJ``, ``.US``). Bare HK and A-share codes are both purely
       numeric, so the suffix is the only reliable disambiguator.
    3. Bare numeric codes by digit length: A-share codes are exactly 6 digits
       (600000, 000001, 300750, 688981, 830799); HK codes are at most 5
       (700, 0700, 9988, 3690). Prefix alone cannot tell them apart — both
       markets use leading 0 and 3.
    4. Anything else (alphabetic tickers) is a US equity.
    """
    code_upper = code.strip().upper()
    crypto_suffixes = ("USDT", "BTC", "ETH", "BNB", "SOL", "ADA", "DOGE")
    if any(code_upper.endswith(s) for s in crypto_suffixes) or "/" in code:
        return "crypto"
    if code_upper.endswith(".HK"):
        return "hk_equity"
    if code_upper.endswith((".SH", ".SZ", ".BJ")):
        return "a_share"
    if code_upper.endswith((".KS", ".KQ")):
        return "kr_equity"
    if code_upper.endswith(".US"):
        return "us_equity"
    if code_upper.isdigit():
        if len(code_upper) == 6:
            return "a_share"
        if len(code_upper) <= 5:
            return "hk_equity"
    return "us_equity"


def _normalize_symbol(code: str, market: str) -> str:
    """Convert a user-supplied code to the project's canonical loader symbol.

    The data loaders key US/HK/A-share instruments by an exchange-suffixed
    symbol (``AAPL.US``, ``0700.HK``, ``600000.SH``); a bare ticker such as
    ``AAPL`` or ``600000`` matches no loader and fetches nothing. Crypto pairs
    (``BTC-USDT``) are already canonical, and any code that already carries a
    ``.`` suffix is left untouched.

    Args:
        code: The raw code as typed by the user (e.g. ``AAPL``, ``600000``).
        market: The market key from :func:`infer_market`.

    Returns:
        The canonical symbol the market's loaders expect.
    """
    cleaned = code.strip()
    # Crypto pairs and anything already exchange-qualified pass through as-is.
    if market == "crypto" or "." in cleaned:
        return cleaned
    upper = cleaned.upper()
    if market == "us_equity":
        return f"{upper}.US"
    if market == "hk_equity":
        return f"{upper}.HK"
    if market == "a_share":
        # 6xxxxx -> Shanghai; 4xxxxx / 8xxxxx -> Beijing; else (0/3) Shenzhen.
        if upper[:1] == "6":
            return f"{upper}.SH"
        if upper[:1] in ("4", "8"):
            return f"{upper}.BJ"
        return f"{upper}.SZ"
    return cleaned


def _close_series(code: str, df: pd.DataFrame) -> pd.Series:
    """Extract the close-price series from a loader frame, date-indexed and sorted.

    Supports ``trade_date`` as the index name, as a column, or a plain
    DatetimeIndex — the shapes real loaders return.
    """
    if df.empty:
        raise ValueError(f"Price series for '{code}' is empty")
    if "close" not in df.columns and "close" not in df.index.names:
        raise ValueError(f"No 'close' column in price series for '{code}'")
    # Support trade_date as index name, column, or a plain DatetimeIndex.
    if "trade_date" in df.columns:
        ts = df.set_index("trade_date")["close"]
    elif "close" in df.columns and (
        "trade_date" in df.index.names
        or isinstance(df.index, pd.DatetimeIndex)
    ):
        ts = df["close"]
    else:
        raise ValueError(
            f"No trade_date index/column for price series '{code}'"
        )
    return ts.sort_index()


def _rolling_correlation_matrix(
    price_series: Dict[str, pd.DataFrame],
    window: int,
    method: Literal["pearson", "spearman"],
) -> tuple[list[str], list[list[float]]]:
    """Compute correlation matrix for multiple price series.

    Args:
        price_series: Mapping of asset code -> DataFrame with a ``close`` column.
        window: Rolling window size in days.
        method: "pearson" or "spearman".

    Returns:
        (labels, matrix) where labels is the sorted list of codes and matrix
        is a symmetric NxN matrix of correlation coefficients.
    """
    if not price_series:
        return [], []

    codes = sorted(price_series.keys())

    # Build a aligned returns DataFrame (row index = date)
    returns_frames = []
    closes = {}
    for code, df in price_series.items():
        closes[code] = _close_series(code, df)

    for code in codes:
        ts = closes[code]
        # Normalize to date-only (midnight) so that cross-market assets
        # (e.g. crypto via OKX/CCXT at UTC midnight vs US equity via
        # yfinance at EDT midnight = 04:00 UTC) align correctly.
        ts.index = ts.index.normalize()
        # ``fill_method=None`` is explicit because under the project's
        # pandas>=2,<3 pin the ``pct_change`` default forward-fills missing
        # prices, silently manufacturing 0% returns on halted sessions.
        rets = ts.pct_change(fill_method=None).dropna()
        rets.name = code
        returns_frames.append(rets)

    # Align all series to a common index (inner join)
    aligned = pd.concat(returns_frames, axis=1).dropna()
    if aligned.empty:
        ranges = {
            code: f"{closes[code].index.min()} .. {closes[code].index.max()}"
            for code in codes
            if len(closes[code]) > 0
        }
        raise ValueError(
            f"No overlapping return data between assets. "
            f"Date ranges: {ranges}"
        )

    # Apply the trailing window — only use the last `window` rows of aligned data
    if len(aligned) > window:
        aligned = aligned.iloc[-window:]

    n = len(aligned)
    if n < 2:
        raise ValueError("Not enough data points to compute correlation")

    labels = codes
    n_assets = len(labels)
    matrix = [[1.0] * n_assets for _ in range(n_assets)]

    for i in range(n_assets):
        for j in range(i + 1, n_assets):
            xi = aligned.iloc[:, i].values
            xj = aligned.iloc[:, j].values
            if method == "spearman":
                corr, _ = spearmanr(xi, xj)
            else:
                corr = np.corrcoef(xi, xj)[0, 1]
            if np.isnan(corr):
                corr = 0.0
            matrix[i][j] = round(corr, 4)
            matrix[j][i] = round(corr, 4)

    return labels, matrix


def _fetch_price_series(
    codes: list[str],
    start_date: str,
    end_date: str,
) -> Dict[str, pd.DataFrame]:
    """Fetch daily price frames for each code via the loader fallback chains.

    Args:
        codes: Asset codes as supplied by the caller (used as result keys).
        start_date: Fetch range start, ``YYYY-MM-DD``.
        end_date: Fetch range end, ``YYYY-MM-DD``.

    Returns:
        Mapping of original code -> OHLCV DataFrame; codes no loader could
        serve are omitted (with a warning logged).
    """
    # Import here to avoid circular
    from backtest.loaders import registry

    registry._ensure_registered()
    price_series: Dict[str, pd.DataFrame] = {}

    for code in codes:
        market = infer_market(code)
        # Loaders key instruments by the canonical exchange-suffixed symbol
        # (AAPL.US / 600000.SH); a bare ticker fetches nothing. Fetch under the
        # normalized symbol but keep the user's original code as the label.
        symbol = _normalize_symbol(code, market)

        # Walk the market's full fallback chain until a loader actually
        # returns data. A loader can be "available" yet still serve nothing
        # (network error, unsupported symbol), so stopping at the first
        # available loader — as resolve_loader does — would silently drop
        # the asset even when a later loader could serve it.
        for name in registry.FALLBACK_CHAINS.get(market, []):
            loader_cls = registry.LOADER_REGISTRY.get(name)
            if loader_cls is None:
                continue
            try:
                loader = loader_cls()
            except Exception as exc:
                logger.debug("correlation: loader %s failed to construct: %s", name, exc)
                continue
            if not loader.is_available():
                continue
            try:
                result = loader.fetch(
                    codes=[symbol],
                    start_date=start_date,
                    end_date=end_date,
                    interval="1D",
                    fields=["trade_date", "open", "high", "low", "close", "volume"],
                )
            except Exception as exc:
                logger.warning("correlation: %s fetch via %s failed: %s", symbol, name, exc)
                continue
            if symbol in result and not result[symbol].empty:
                price_series[code] = result[symbol]
                break
            logger.warning("correlation: %s returned no data via %s", symbol, name)
        else:
            logger.warning(
                "correlation: no loader in the %s chain returned data for %s "
                "(normalized from %r)", market, symbol, code,
            )

    return price_series


def compute_correlation_matrix(
    codes: list[str],
    days: int = 90,
    method: Literal["pearson", "spearman"] = "pearson",
) -> Dict[str, object]:
    """Fetch price data and compute correlation matrix for a list of assets.

    Args:
        codes: List of asset codes (e.g. ["BTC-USDT", "ETH-USDT", "SPY"]).
        days: Lookback window in days (default 90).
        method: Correlation method.

    Returns:
        Dict with keys: labels, matrix, window, method.
    """
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days + 60)).strftime("%Y-%m-%d")

    price_series = _fetch_price_series(codes, start_date, end_date)

    if len(price_series) < 2:
        raise ValueError(
            f"Could not fetch price data for at least 2 assets. "
            f"Fetched: {list(price_series.keys())}"
        )

    labels, matrix = _rolling_correlation_matrix(price_series, days, method)
    return {
        "labels": labels,
        "matrix": matrix,
        "window": days,
        "method": method,
    }
