"""vnstock loader: free, no-auth data for Vietnamese equities/indices/futures.

vnstock (https://github.com/thinh-vu/vnstock) aggregates Vietnamese market
data from multiple upstream brokers — VCI, TCBS, MSN. We try the sources in
that order per symbol and fall back on failure.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    "1D": "1D",
    "1W": "1W",
    "1M": "1M",
}

_VN_SOURCES = ["VCI", "TCBS", "MSN"]
_VN_FUTURES_SOURCES = ["VCI", "TCBS"]  # MSN does not support derivatives

_VN_EXCHANGE_RE = re.compile(r"\.(HOSE|HNX|UPCOM)$", re.I)
_VN30F_RE = re.compile(r"^VN30F[12][MQ](\.HNX)?$", re.I)


def _strip_exchange(code: str) -> str:
    """Strip the .HOSE / .HNX / .UPCOM suffix to get the bare ticker."""
    return _VN_EXCHANGE_RE.sub("", code).upper()


def _is_vn30f(symbol: str) -> bool:
    """Return True if *symbol* is a VN30 futures contract (e.g. VN30F1M)."""
    return bool(_VN30F_RE.match(symbol or ""))


def _classify_vn_exchange(code: str) -> str:
    """Return the exchange code (HOSE/HNX/UPCOM) implied by *code*.

    Defaults to ``HOSE`` (the largest exchange) when no suffix is present.
    """
    match = _VN_EXCHANGE_RE.search(code)
    if match:
        return match.group(1).upper()
    return "HOSE"


@register
class VNStockLoader:
    """vnstock universal Vietnamese OHLCV loader (free, no auth)."""

    name = "vnstock"
    markets = {"vn_equity", "vn_index", "vn_futures"}
    requires_auth = False

    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:
        """Available if vnstock is installed and VCI source responds."""
        try:
            import vnstock  # noqa: F401
        except ImportError:
            return False

        # 2-second health probe of VCI source via single bar of VNM.
        try:
            from vnstock import Quote
            q = Quote(symbol="VNM", source="VCI")
            df = q.history(start="2024-01-02", end="2024-01-03", interval="1D")
            if df is None or df.empty:
                return False
        except Exception as exc:
            logger.debug("vnstock health probe failed: %s", exc)
            return False
        return True

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV data via vnstock.

        Args:
            codes: Symbol list (``VNM``, ``VNM.HOSE``, ``VNM.HNX``, ``VNM.UPCOM``).
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: Bar size (``1D``, ``1W``, ``1M``).
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.  Symbols that fail every source
            are simply skipped (a warning is logged); they do not raise.
        """
        validate_date_range(start_date, end_date)

        vn_interval = _INTERVAL_MAP.get(interval, "1D")
        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            df = self._fetch_one(code, start_date, end_date, vn_interval)
            if df is not None and not df.empty:
                result[code] = df
        return result

    def _fetch_one(
        self,
        code: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single symbol, walking the VCI -> TCBS -> MSN fallback chain.

        For VN30F derivatives the chain narrows to VCI -> TCBS (MSN skipped —
        it does not serve derivatives data).
        """
        symbol = _strip_exchange(code)
        is_futures = _is_vn30f(symbol)
        sources = _VN_FUTURES_SOURCES if is_futures else _VN_SOURCES
        if is_futures:
            logger.info("Fetching VN30F symbol %s via %s (derivatives chain)", code, sources[0])
        last_exc: Optional[Exception] = None
        for idx, source in enumerate(sources):
            try:
                df = self._fetch_from_source(symbol, source, start_date, end_date, interval)
            except Exception as exc:
                last_exc = exc
                if idx + 1 < len(sources):
                    logger.info(
                        "vnstock source %s failed for %s (%s); falling back to %s",
                        source, code, exc, sources[idx + 1],
                    )
                continue
            if df is not None and not df.empty:
                if idx > 0:
                    logger.info("vnstock recovered %s via fallback source %s", code, source)
                return df
        if is_futures:
            logger.warning(
                "VN30F symbol %s not available via vnstock — derivatives data may "
                "require TCBS direct API integration (last error: %s)",
                code, last_exc,
            )
        else:
            logger.warning(
                "vnstock failed for %s across all sources %s: %s",
                code, sources, last_exc,
            )
        return None

    @staticmethod
    def _fetch_from_source(
        symbol: str,
        source: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch ``symbol`` from a single vnstock upstream and normalize."""
        from vnstock import Quote

        q = Quote(symbol=symbol, source=source)
        df = q.history(start=start_date, end=end_date, interval=interval)
        if df is None or df.empty:
            return None
        return VNStockLoader._normalize(df)

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize vnstock DataFrame to canonical OHLCV schema.

        vnstock returns columns ``time, open, high, low, close, volume``.
        We rename ``time`` -> ``trade_date``, coerce dtypes, and index by date.
        """
        if "time" in df.columns:
            df = df.rename(columns={"time": "trade_date"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").sort_index()

        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        ohlcv_cols = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        df = df[ohlcv_cols].dropna(subset=["open", "high", "low", "close"])
        if "volume" not in df.columns:
            df["volume"] = 0.0
        return df
