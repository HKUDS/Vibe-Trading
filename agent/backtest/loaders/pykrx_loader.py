"""pykrx loader: free, no-auth KRX (KOSPI/KOSDAQ) EOD OHLCV.

Fetches Korean equity **daily** bars through the `pykrx
<https://github.com/sharebook-kr/pykrx>`_ package. No API key.

Provenance caveat (be precise about what this data is): ``pykrx`` exposes both
a raw KRX path and an adjusted-price path, and
``stock.get_market_ohlcv_by_date`` defaults to ``adjusted=True``. The adjusted
path is served by Naver rather than by KRX's own endpoint (upstream discussion:
https://github.com/sharebook-kr/pykrx/issues/270). This loader passes
``adjusted=True`` **explicitly** — split/consolidation-adjusted bars are what a
backtest needs — so be clear that the series is *Naver-backed adjusted* data,
not a verbatim KRX print. Nothing here silently inherits that choice.

Symbol convention (Vibe-Trading -> pykrx):
  * ``005930.KS`` (KOSPI) / ``247540.KQ`` (KOSDAQ) -> bare 6-digit ticker
    ``005930``. The ``.KS``/``.KQ`` suffix follows the Yahoo convention already
    used for market inference elsewhere; pykrx itself takes the bare code and
    does not care which board it trades on.

pykrx returns a DataFrame indexed by date with Korean column names
(시가/고가/저가/종가/거래량), renamed here to the project's canonical
``open/high/low/close/volume``.

Politeness: pykrx's README asks callers to keep at least ~1 second between
bulk requests, so spacing defaults to 1.0s and runs through the shared,
lock-protected :class:`~backtest.loaders._http.HostThrottle` rather than a
module-global timestamp (which raced under concurrent fetches). Override with
``VIBE_TRADING_PYKRX_MIN_INTERVAL``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders._http import HostThrottle, resolve_min_interval
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_COLUMN_MAP = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
}
_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume"]

# Daily-only upstream API. Accepting anything else would cache day bars under an
# intraday key and run a 1m/1H/4H backtest on daily data.
_DAILY_INTERVALS = frozenset({"1d", "d", "day", "daily"})

# pykrx owns its own HTTP session, so requests cannot route through
# ``throttled_get``; the spacing gate is reused on its own.
_HOST_KEY = "pykrx"
_MIN_INTERVAL_ENV = "VIBE_TRADING_PYKRX_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 1.0
_THROTTLE = HostThrottle()


def map_symbol(symbol: str) -> str:
    """``005930.KS`` / ``247540.KQ`` -> pykrx's bare 6-digit ticker."""
    return symbol.strip().upper().removesuffix(".KS").removesuffix(".KQ")


def _min_interval() -> float:
    """Resolve the per-call minimum spacing, honoring the env override."""
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S)


@register
class DataLoader:
    """KRX (KOSPI/KOSDAQ) EOD OHLCV loader via pykrx (free, no auth)."""

    name = "pykrx"
    markets = {"kr_equity"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available when the optional ``pykrx`` package is importable."""
        try:
            import pykrx  # noqa: F401
        except ImportError:
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
        """Fetch daily OHLCV bars for ``codes`` over ``[start_date, end_date]``.

        Args:
            codes: Project-side symbols (e.g. ``["005930.KS", "247540.KQ"]``).
            start_date: Inclusive start date (``YYYY-MM-DD``).
            end_date: Inclusive end date (``YYYY-MM-DD``).
            interval: Only daily (``"1D"``) is supported. Any other value is
                rejected with an empty result so the runner's fallback chain can
                reach a source that actually serves that bar size.
            fields: Unused — pykrx always returns the full OHLCV set.

        Returns:
            Mapping ``{symbol: DataFrame}`` for symbols that returned data,
            each indexed by ``trade_date`` with float OHLCV columns ascending.
            A failing or empty symbol is omitted, never aborting the batch.
            Empty when ``interval`` is not daily.
        """
        validate_date_range(start_date, end_date)

        # Daily-only API; do not silently return day bars for runner ``1H``/``4H``.
        if str(interval).strip().lower() not in _DAILY_INTERVALS:
            logger.warning(
                "pykrx supports daily bars only; rejecting interval=%r",
                interval,
            )
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
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the batch
                logger.warning("pykrx failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch and normalize one symbol; ``None`` when KRX has no data.

        ``adjusted=True`` is passed explicitly: it is pykrx's own default, but
        stating it keeps the Naver-backed adjusted-price provenance (see the
        module docstring) visible at the call site instead of implied.
        """
        from pykrx import stock

        _THROTTLE.wait(_HOST_KEY, _min_interval())
        frame = stock.get_market_ohlcv_by_date(
            pd.Timestamp(start_date).strftime("%Y%m%d"),
            pd.Timestamp(end_date).strftime("%Y%m%d"),
            map_symbol(code),
            adjusted=True,
        )
        return _normalize(frame)


def _normalize(frame: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Convert a raw pykrx OHLCV frame into the project's canonical shape.

    Args:
        frame: pykrx output — date-indexed with Korean column names
            (시가/고가/저가/종가/거래량) — or ``None``/empty when KRX has no
            data for the symbol/window.

    Returns:
        A frame indexed by ``trade_date`` with float OHLCV columns sorted
        ascending, or ``None`` when the input carries no usable rows.
    """
    if frame is None or frame.empty:
        return None

    frame = frame.rename(columns=_COLUMN_MAP)
    if not all(col in frame.columns for col in _OUTPUT_COLUMNS):
        return None
    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "trade_date"
    frame = frame[_OUTPUT_COLUMNS].sort_index()
    for col in _OUTPUT_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    if frame.empty:
        return None
    return frame.astype(float)
