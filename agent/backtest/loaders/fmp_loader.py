"""Financial Modeling Prep (FMP) loader: key-gated US-equity OHLCV via HTTP.

FMP exposes a daily historical-price endpoint that, like other free quote
providers, rate-limits by source IP and must be throttled. Every request here
routes through :mod:`backtest.loaders._http` so calls share one process-wide
minimum-spacing gate and a reused session.

API format (public, documented):
  https://financialmodelingprep.com/stable/historical-price-eod/full
    ?symbol=SYMBOL&from=YYYY-MM-DD&to=YYYY-MM-DD&apikey=KEY

The JSON body is a top-level array ``[{date, open, high, low, close,
adjClose, volume}, ...]`` (legacy ``{"symbol": "AAPL", "historical": [...]}``
shape is still accepted for compatibility); an unknown symbol or empty window
yields an empty array. The parser sorts by date, so the order the endpoint
happens to return is not relied on.

Auth: set ``FMP_API_KEY`` in the environment. Covers US equities only.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_get_json
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_API_KEY_ENV = "FMP_API_KEY"
_BASE_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"

# Shared throttle/session bucket for every FMP request in this process.
_HOST_KEY = "fmp"
_MIN_INTERVAL_ENV = "VIBE_TRADING_FMP_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 0.3

# FMP daily bars carry these numeric fields; emitted in this column order.
_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")


def _api_key() -> str:
    """Return the FMP API key from the environment, stripped (``""`` if unset)."""
    from src.config.accessor import get_env_config

    return get_env_config().data.fmp_api_key.strip()


def _min_interval() -> float:
    """Resolve the per-call minimum spacing, honoring the env override."""
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S)


def _fmp_symbol(code: str) -> str:
    """Translate a project symbol into FMP's bare-ticker convention.

    FMP carries US tickers bare, so a trailing ``.US`` suffix (the project's
    US-equity marker) is dropped; everything else is upper-cased and passed
    through unchanged.

    Args:
        code: Project-side symbol, e.g. ``AAPL`` or ``AAPL.US``.

    Returns:
        The FMP ticker (suffix stripped, upper-cased).
    """
    cleaned = code.strip().upper()
    if cleaned.endswith(".US"):
        cleaned = cleaned[: -len(".US")]
    return cleaned


@register
class DataLoader:
    """Financial Modeling Prep US-equity OHLCV loader (key-gated, HTTP)."""

    name = "fmp"
    markets = {"us_equity"}
    requires_auth = True

    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:
        """Available when ``FMP_API_KEY`` is set to a non-empty value."""
        return bool(_api_key())

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch daily OHLCV bars from FMP, one symbol at a time.

        A single failing symbol is logged and skipped so it never aborts the
        rest of the batch.

        Args:
            codes: Project symbols (e.g. ``["AAPL", "MSFT.US"]``).
            start_date: Inclusive start date, ``YYYY-MM-DD``.
            end_date: Inclusive end date, ``YYYY-MM-DD``.
            interval: Bar size; only ``"1D"`` is supported (others skipped).
            fields: Ignored — FMP returns a fixed OHLCV schema.

        Returns:
            Mapping ``{symbol: DataFrame(trade_date, open, high, low, close,
            volume)}`` for every symbol that returned non-empty data.

        Raises:
            ValueError: If ``start_date`` > ``end_date`` (via
                :func:`validate_date_range`).
        """
        validate_date_range(start_date, end_date)

        if str(interval).strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning("fmp only supports 1D bars; got interval=%r", interval)
            return {}

        if not self.is_available():
            logger.warning("fmp fetch skipped: %s not set", _API_KEY_ENV)
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(code, start_date, end_date),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("fmp failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self,
        code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch and parse one symbol's daily bars; ``None`` on no data.

        Args:
            code: Project symbol to fetch.
            start_date: Inclusive start date, ``YYYY-MM-DD``.
            end_date: Inclusive end date, ``YYYY-MM-DD``.

        Returns:
            An ascending OHLCV DataFrame indexed by ``trade_date``, or ``None``
            when FMP reports no bars for the symbol/window.

        Raises:
            RuntimeError: If the API key is missing at call time.
            requests.RequestException: Propagated from the HTTP layer.
        """
        api_key = _api_key()
        if not api_key:
            raise RuntimeError(f"{_API_KEY_ENV} is not set")

        symbol = _fmp_symbol(code)
        if not symbol:
            return None

        payload = throttled_get_json(
            _BASE_URL,
            host_key=_HOST_KEY,
            min_interval=_min_interval(),
            params={
                "symbol": symbol,
                "from": start_date,
                "to": end_date,
                "apikey": api_key,
            },
        )
        return _parse_historical(payload)


def _adjusted_bar(bar: dict) -> Optional[tuple[float, float, float, float]]:
    """The adjusted ``(open, high, low, close)`` one FMP bar yields, or ``None``.

    FMP carries only ``adjClose``, so the rest of a bar is its raw OHLC scaled
    by the ``adjClose/close`` factor. ``None`` means the bar cannot be part of
    an adjusted series — a price that is missing, non-numeric, non-finite or
    non-positive, or a factor outside the sane 0.01-100x window — so it may
    neither supply the series' basis nor, once another bar supplies it, be
    replaced with raw prices.
    """
    try:
        o, h, lo, c = (
            float(bar[field]) for field in ("open", "high", "low", "close")
        )
        adj_close = float(bar["adjClose"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(
        math.isfinite(value) and value > 0 for value in (o, h, lo, c, adj_close)
    ):
        return None
    ratio = adj_close / c
    if not 0.01 <= ratio <= 100:
        return None
    return o * ratio, h * ratio, lo * ratio, adj_close


def _parse_historical(payload: Any) -> Optional[pd.DataFrame]:
    """Convert an FMP historical-price body into an ascending OHLCV frame.

    Stable API returns a top-level array; legacy ``{"historical": [...]}``
    shape is accepted for compatibility.

    The endpoint carries dividend- and split-adjusted closes in ``adjClose``.
    OHLC is scaled by ``adjClose/close`` when present so backtests see
    total-return prices rather than raw gaps — the same split_dividend caliber
    eastmoney/tencent/yahoo/yfinance serve, and what this source is registered
    as in ``PRICE_CALIBER_BY_SOURCE``. Volume is never scaled.

    A bar that cannot yield a complete, finite, positive adjusted bar is
    dropped whenever any other bar can, so one series never mixes the two
    price bases; a response in which no bar can stays consistently raw.

    Args:
        payload: Decoded JSON body from the historical-price endpoint.
            Accepts both the legacy ``{"historical": [...]}`` dict and the
            Stable top-level ``[...]`` array.

    Returns:
        DataFrame indexed by ``trade_date`` with float ``open/high/low/close/
        volume`` columns (adjusted), or ``None`` when no usable rows are present.
    """
    if isinstance(payload, list):
        historical = payload
    elif isinstance(payload, dict):
        h = payload.get("historical")
        historical = h if isinstance(h, list) else None
    else:
        historical = None
    if not historical:
        return None

    dated = [bar for bar in historical if isinstance(bar, dict)
             and isinstance(bar.get("date"), str)
             and pd.notna(pd.to_datetime(bar["date"], errors="coerce"))]
    if len(dated) != len(historical):
        logger.warning("FMP: dropped %d bars with missing/invalid dates", len(historical) - len(dated))
    has_adjusted_data = any(_adjusted_bar(bar) is not None for bar in dated)
    rows = []
    dropped = 0
    for bar in dated:
        basis = _adjusted_bar(bar)
        if basis is not None:
            o, h, lo, c = basis
        elif has_adjusted_data:
            # Preserve a single price basis: a bar whose adjustment is missing
            # or unusable cannot be replaced with raw OHLC when others are
            # adjusted. A response with no usable adjustment at all stays raw,
            # consistently.
            dropped += 1
            continue
        else:
            # Nothing to adjust against: the whole series stays on the raw
            # basis rather than the response being discarded.
            o, h, lo, c = (
                bar.get("open"),
                bar.get("high"),
                bar.get("low"),
                bar.get("close"),
            )
        rows.append(
            {
                "trade_date": bar["date"],
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": bar.get("volume"),
            }
        )

    if dropped:
        # Say so rather than truncate in silence: a long-history symbol whose
        # older bars fall outside the 0.01-100x factor window loses them, and
        # the backtest then runs a shorter window than it asked for.
        logger.warning(
            "FMP: dropped %d of %d bars that carry no usable adjustment while "
            "the rest do; the series keeps one price basis instead of mixing "
            "raw and adjusted prices",
            dropped,
            len(historical),
        )

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df = df.dropna(subset=["trade_date"])
    for field in _OHLCV_FIELDS:
        # Cast to float (not just to_numeric) so integer volume from the API
        # does not leave the column int64 and break the float-OHLCV contract.
        df[field] = pd.to_numeric(df[field], errors="coerce").astype(float)

    df = df.set_index("trade_date").sort_index()
    df = df[list(_OHLCV_FIELDS)].dropna(subset=["open", "high", "low", "close"])
    prices = df[["open", "high", "low", "close"]]
    df = df.loc[((prices > 0) & (prices < float("inf"))).all(axis=1)]
    if df.empty:
        return None
    df.attrs["adjustment"] = "split_dividend" if has_adjusted_data else "raw"
    return df
