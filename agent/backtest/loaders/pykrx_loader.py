"""pykrx loader: free, no-auth KRX (KOSPI/KOSDAQ) EOD OHLCV.

Fetches Korean equity daily bars from KRX public data via the `pykrx
<https://github.com/sharebook-kr/pykrx>`_ package. No API key; pykrx scrapes
KRX's public endpoints, so calls are throttled per host bucket like the other
free sources.

Symbol convention (Vibe-Trading -> pykrx):
  * ``005930.KS`` (KOSPI) / ``247540.KQ`` (KOSDAQ) -> bare 6-digit ticker
    ``005930``. The ``.KS``/``.KQ`` suffix follows the Yahoo convention already
    used for market inference elsewhere; pykrx itself takes the bare code and
    does not care which board it trades on.

pykrx returns a DataFrame indexed by date with Korean column names
(시가/고가/저가/종가/거래량), renamed here to the project's canonical
``open/high/low/close/volume``.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pandas as pd

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

# ponytail: fixed spacing instead of the _http host-bucket throttle — pykrx
# owns its own HTTP session, so we can't route it through throttled_get.
_MIN_INTERVAL_S = 0.5
_last_call = 0.0


def map_symbol(symbol: str) -> str:
    """``005930.KS`` / ``247540.KQ`` -> pykrx's bare 6-digit ticker."""
    return symbol.strip().upper().removesuffix(".KS").removesuffix(".KQ")


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


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
            interval: Only daily (``"1D"``) is supported; other values are
                fetched as daily.
            fields: Unused — pykrx always returns the full OHLCV set.

        Returns:
            Mapping ``{symbol: DataFrame}`` for symbols that returned data,
            each indexed by ``trade_date`` with float OHLCV columns ascending.
            A failing or empty symbol is omitted, never aborting the batch.
        """
        validate_date_range(start_date, end_date)

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
        """Fetch and normalize one symbol; ``None`` when KRX has no data."""
        from pykrx import stock

        _throttle()
        frame = stock.get_market_ohlcv_by_date(
            pd.Timestamp(start_date).strftime("%Y%m%d"),
            pd.Timestamp(end_date).strftime("%Y%m%d"),
            map_symbol(code),
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
