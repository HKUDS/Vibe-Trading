"""Cross-asset correlation matrix computation.

Computes pairwise Pearson or Spearman correlation of daily returns
over a configurable lookback window. Used by the /correlation API endpoint.
"""

from __future__ import annotations

import logging
import re
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
       ``.SZ``/``.BJ``, ``.TO``/``.V``, ``.US``). Bare HK and A-share codes
       are both purely numeric, so the suffix is the only reliable
       disambiguator.
    3. Bare numeric codes by digit length: A-share codes are exactly 6 digits
       (600000, 000001, 300750, 688981, 830799); HK codes are at most 5
       (700, 0700, 9988, 3690). Prefix alone cannot tell them apart — both
       markets use leading 0 and 3.
    4. Anything else (alphabetic tickers) is a US equity.
    """
    from src.market_data import canonical_fx_pair
    from backtest.engines._market_hooks import _detect_market

    code_upper = code.strip().upper()
    if canonical_fx_pair(code_upper):
        return "forex"
    # The shared classifier distinguishes known crypto/USD pairs from metals
    # and FX. Resolve those before the permissive crypto spelling fallback.
    detected = _detect_market(code_upper)
    if detected != "a_share":
        return detected
    crypto_suffixes = ("USDT", "BTC", "ETH", "BNB", "SOL", "ADA", "DOGE")
    if (
        "/" in code_upper
        or any(
            code_upper.endswith("-" + quote)
            for quote in (*crypto_suffixes, "USD", "USDC")
        )
        or re.fullmatch(
            r"(?:[A-Z0-9]{2,}(?:USDT|USDC|BTC|ETH|BNB|SOL|ADA|DOGE)|(?:BTC|ETH|BNB|SOL|ADA|DOGE)USD)",
            code_upper,
        )
    ):
        return "crypto"
    if code_upper.endswith(".HK"):
        return "hk_equity"
    if code_upper.endswith((".SH", ".SZ", ".BJ")):
        return "a_share"
    if code_upper.endswith((".KS", ".KQ")):
        return "kr_equity"
    if code_upper.endswith((".TO", ".V")):
        return "ca_equity"
    if code_upper.endswith(".US"):
        return "us_equity"
    # Yahoo's continuous-front-month futures notation (``GC=F``, ``CL=F``,
    # ``SI=F``, ``HG=F``, ``MGC=F``). Mirrors the same pattern in
    # ``backtest.engines._market_hooks._MARKET_PATTERNS`` so this offline
    # classifier stays consistent with the engine-side classifier.
    if re.match(r"^[A-Z]{2,5}=F$", code_upper):
        return "futures"
    # Yahoo's forex notation (``XAUUSD=X``, ``EURUSD=X``).
    if re.match(r"^[A-Z]{6}=X$", code_upper):
        return "forex"
    # Bare 6-character precious-metal / FX symbols. Whitelist-restricted to
    # a small set of base codes (ISO 4217 metals + G10 currencies) so a
    # length-only pattern never re-routes a legitimate 6-letter US ticker.
    if re.match(
        r"^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$",
        code_upper,
    ):
        return "forex"
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
    (``BTC-USDT``) are already canonical; a code that already carries a ``.``
    suffix passes through, except HK codes, which are zero-padded to four digits
    so one instrument keeps one key.

    Args:
        code: The raw code as typed by the user (e.g. ``AAPL``, ``600000``).
        market: The market key from :func:`infer_market`.

    Returns:
        The canonical symbol the market's loaders expect.
    """
    from src.market_data import canonical_fx_pair

    cleaned = code.strip().upper()
    fx = canonical_fx_pair(cleaned)
    if fx:
        return fx
    # Crypto pairs and anything already exchange-qualified pass through as-is.
    if market == "crypto":
        if cleaned.endswith("/USDT"):
            return cleaned.replace("/", "-")
        if re.fullmatch(r"[A-Z]{2,}USDT", cleaned):
            return f"{cleaned[:-4]}-USDT"
        return cleaned
    if market == "hk_equity":
        hk = re.fullmatch(r"(\d{1,5})(?:\.HK)?", cleaned)
        if hk:
            # HKEX's five-digit display and four-digit Yahoo spelling can
            # name the same counter. Only discard redundant leading zeroes;
            # genuine five-digit counters (e.g. 80700) remain distinct.
            return f"{int(hk.group(1)):04d}.HK"
    if re.search(r"\.(US|HK|SH|SZ|BJ|KS|KQ|NS|BO|TO|V|BA|L|VN|FX)$", cleaned):
        return cleaned
    upper = cleaned.upper()
    if market == "us_equity":
        return f"{upper}.US"
    if market == "hk_equity":
        return f"{upper.zfill(4)}.HK"
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
        ts.index = ts.index.tz_localize(None).normalize()
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
    diagnostics: dict | None = None,
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
        attempts = []
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
        chain = registry.get_source_order_override(market)
        if chain is None:
            chain = list(registry.FALLBACK_CHAINS.get(market, []))
        # Yahoo's native index/future/FX identifiers are not Chinese contracts.
        if symbol.startswith("^") or symbol.endswith(("=F", "=X")):
            chain = list(dict.fromkeys(["yahoo", *chain]))
        for name in chain:
            loader_cls = registry.LOADER_REGISTRY.get(name)
            if loader_cls is None:
                attempts.append({"source": name, "reason": "source_unavailable"})
                continue
            try:
                loader = loader_cls()
                if not loader.is_available():
                    attempts.append({"source": name, "reason": "source_unavailable"})
                    continue
            except Exception as exc:
                attempts.append({"source": name, "reason": "source_unavailable"})
                logger.debug("correlation: loader %s failed to construct: %s", name, exc)
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
                attempts.append({"source": name, "reason": "fetch_failed"})
                logger.warning("correlation: %s fetch via %s failed: %s", symbol, name, exc)
                continue
            if result and symbol in result and result[symbol] is not None and not result[symbol].empty and "close" in result[symbol].columns:
                price_series[code] = result[symbol]
                break
            attempts.append({"source": name, "reason": "no_data"})
            logger.warning("correlation: %s returned no data via %s", symbol, name)
        else:
            logger.warning(
                "correlation: no loader in the %s chain returned data for %s "
                "(normalized from %r)", market, symbol, code,
            )
        if diagnostics is not None:
            diagnostics[code] = {"symbol": symbol, "market": market, "attempts": attempts, "source": name if code in price_series else None}

    return price_series


def compute_correlation_analysis(codes: list[str], days: int = 90, method: str = "pearson", include_regime: bool = False) -> dict:
    """Compute independent analysis outputs from one observed price snapshot.

    Args:
        codes: User symbols; duplicates are rejected after normalization.
        days: Trailing observation count requested by the user.
        method: Correlation estimator for the static matrix.
        include_regime: Also compute the Pearson-based regime timeline.

    Returns:
        Matrix, optional regime, coverage and independent errors.
    """
    from datetime import datetime, timedelta
    from backtest.regime import _aligned_returns, compute_regime_timeline

    normalized = [_normalize_symbol(code, infer_market(code)) for code in codes]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Use distinct assets; two spellings of the same symbol are not a comparison.")
    end = datetime.now().strftime("%Y-%m-%d")
    buffer = 150 if include_regime else 60
    start = (datetime.now() - timedelta(days=days + buffer)).strftime("%Y-%m-%d")
    diagnostics: dict = {}
    frames = _fetch_price_series(codes, start, end, diagnostics)
    missing = [code for code in codes if code not in frames]
    output = {"correlation": None, "regime": None, "errors": {}, "coverage": {
        "requested": codes, "missing": missing, "diagnostics": diagnostics,
        "observations": 0, "first_date": None, "last_date": None,
    }}
    if len(frames) < 2:
        output["errors"]["correlation"] = "Fewer than two assets returned prices. Check the symbols, source configuration and date range."
        return output
    try:
        aligned = _aligned_returns(frames).iloc[-days:]
        labels, matrix = _rolling_correlation_matrix(frames, days, method)
        output["correlation"] = {"labels": labels, "matrix": matrix, "window": days, "method": method}
        output["coverage"].update({"observations": len(aligned), "first_date": aligned.index[0].strftime("%Y-%m-%d"), "last_date": aligned.index[-1].strftime("%Y-%m-%d")})
    except ValueError as exc:
        output["errors"]["correlation"] = str(exc)
    if include_regime:
        try:
            output["regime"] = compute_regime_timeline(codes, days, price_series=frames)
        except ValueError as exc:
            output["errors"]["regime"] = str(exc)
    return output


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
