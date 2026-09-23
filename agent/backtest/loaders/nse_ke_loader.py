"""NSE Kenya loader: the Nairobi Securities Exchange's own daily price list.

The exchange publishes a free Daily Equity Price List for every session as a
PDF, linked from https://www.nse.co.ke/market-statistics/ and stored at::

    https://www.nse.co.ke/wp-content/uploads/{DD}-{MON}-{YY}.pdf
    e.g. https://www.nse.co.ke/wp-content/uploads/27-FEB-26.pdf

No API key or login is needed. Every row carries, in this order::

    52WK HIGH  52WK LOW  <security name>  ISIN  HIGH  LOW  VWAP  PREVIOUS  VOLUME
    440.00     240.00    Kakuzi Plc Ord.5.00  KE0000000281  436.00  405.00  433.00  436.50  443

The ISIN anchors the parse: it is the one fixed-shape token on the line, so the
security name before it may contain digits and par values ("Ord 1.25 SME")
without confusing the columns.

Bar semantics (read before trusting a fill price):
  * ``close`` is the session **VWAP**. That is the NSE's official closing price
    (Equity Trading Rules 7.6.1 / 7.6.4) and the reference its ±10% band is
    measured from, so :class:`~backtest.engines.kenya_equity.KenyaEquityEngine`
    reproduces the exchange band exactly on this source.
  * The list prints no opening price. ``open`` is set to the VWAP too, so a
    next-bar fill executes at the next session's average price — a fair
    reading of what a patient order achieves on a thin book, and one that never
    borrows information from later in the day than the VWAP itself.
  * ``pre_close`` is the list's PREVIOUS column, the prior session's VWAP.
  * Prices are unadjusted for splits, bonus issues and dividends.
  * A counter that did not trade in a session gets no bar for it.

Symbols: ``SCOM.NR`` (Reuters-style ``.NR`` suffix) or the ISIN itself,
``KE1000001402.NR``. Trading codes are resolved to rows by name through
:mod:`backtest.loaders.nse_ke_symbols`; an ISIN is matched exactly.

History is built one session at a time — one PDF per trading day — so a long
window costs one request per session. Requests are throttled per host, the
per-symbol result goes through the opt-in loader cache, and
``VIBE_TRADING_NSE_KE_MAX_SESSIONS`` (default 300) caps the sessions a single
call will walk. For multi-year research, seed a ``local:`` CSV and let this
loader extend it.

Some price lists are published as scanned images with no text layer. Those
sessions are skipped and counted, never guessed; OCR is out of scope.

Requires the optional ``pdfplumber`` dependency (``pip install
'vibe-trading-ai[nse-ke]'``). Without it the loader reports itself unavailable
and the fallback chain moves on to ``local``.
"""

from __future__ import annotations

import io
import logging
import os
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_get
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.nse_ke_symbols import (
    SECURITIES,
    code_for_name,
    is_isin,
    strip_suffix,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

PRICE_LIST_URL = "https://www.nse.co.ke/wp-content/uploads/{dd}-{mon}-{yy}.pdf"
MARKET_STATS_URL = "https://www.nse.co.ke/market-statistics/"
HOST_KEY = "nse_ke"

_MIN_INTERVAL_ENV = "VIBE_TRADING_NSE_KE_MIN_INTERVAL"
_DEFAULT_MIN_INTERVAL_S = 1.0
_MAX_SESSIONS_ENV = "VIBE_TRADING_NSE_KE_MAX_SESSIONS"
_DEFAULT_MAX_SESSIONS = 300

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

_NUM = r"(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?"
_CELL = rf"(?:{_NUM}|-)"
#: One price-list row. The ISIN is the anchor; the 52-week columns are optional
#: because a newly listed counter can be printed without them.
_ROW_RE = re.compile(
    rf"^(?:(?P<hi52>{_CELL})\s+(?P<lo52>{_CELL})\s+)?"
    rf"(?P<name>\S.*?)\s+"
    rf"(?P<isin>KE[0-9A-Z]{{10}})\s+"
    rf"(?P<high>{_CELL})\s+(?P<low>{_CELL})\s+(?P<vwap>{_CELL})\s+"
    rf"(?P<prev>{_CELL})\s+(?P<volume>{_CELL})\s*$"
)
#: The market-statistics page's link to the latest equity list.
_LIST_LINK_RE = re.compile(
    r"https?://www\.nse\.co\.ke/wp-content/uploads/(\d{2})-([A-Z]{3})-(\d{2})\.pdf",
    re.I,
)

PRICE_LIST_COLUMNS = [
    "code", "name", "isin", "sector",
    "hi52", "lo52", "high", "low", "vwap", "prev", "volume",
]
#: A sector heading: an upper-case line with no digits, e.g. "BANKING",
#: "ENERGY & PETROLEUM". Column headers and titles are excluded by name.
_SECTOR_RE = re.compile(r"^[A-Z][A-Z &,/\-]{2,60}$")
_NOT_SECTORS = ("DAILY PRICE LIST", "NAIROBI SECURITIES EXCHANGE", "SECURITY", "ISIN", "VWAP", "PREVIOUS")
_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume", "pre_close"]

# Per-process memo of parsed price lists, keyed by session date. A multi-symbol
# fetch reads each session's PDF once, not once per symbol. ``None`` records a
# session with no usable list (holiday, 404, scanned image) so it is not
# re-requested within the process.
_PRICE_LIST_MEMO: dict[date, Optional[pd.DataFrame]] = {}
_scanned_warned = False


def _min_interval() -> float:
    return resolve_min_interval(_MIN_INTERVAL_ENV, _DEFAULT_MIN_INTERVAL_S)


def _max_sessions() -> int:
    raw = os.environ.get(_MAX_SESSIONS_ENV, "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MAX_SESSIONS
    except ValueError:
        value = _DEFAULT_MAX_SESSIONS
    return max(1, value)


def price_list_url(day: date) -> str:
    """Return the NSE daily equity price list URL for *day*."""
    return PRICE_LIST_URL.format(
        dd=f"{day.day:02d}", mon=_MONTHS[day.month - 1], yy=f"{day.year % 100:02d}",
    )


def _to_float(cell: Optional[str]) -> Optional[float]:
    if cell is None:
        return None
    cell = cell.strip()
    if not cell or cell == "-":
        return None
    try:
        return float(cell.replace(",", ""))
    except ValueError:
        return None


def parse_price_list_text(text: str) -> pd.DataFrame:
    """Parse the text layer of an NSE daily price list into one row per security.

    Lines that are not security rows — titles, sector headings, column headers,
    footnotes — simply fail the ISIN-anchored pattern and are ignored.

    Args:
        text: Extracted text of the whole PDF.

    Returns:
        A frame with :data:`PRICE_LIST_COLUMNS`. ``code`` is the resolved NSE
        trading code, or ``None`` when the name matches no known entry (the row
        is kept, so an ISIN lookup still finds it). Empty when nothing parsed.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    sector: Optional[str] = None
    for raw_line in (text or "").splitlines():
        line = " ".join(raw_line.split())
        match = _ROW_RE.match(line)
        if not match:
            if _SECTOR_RE.match(line) and not any(word in line for word in _NOT_SECTORS):
                sector = line.title()
            continue
        isin = match["isin"].upper()
        if isin in seen:  # a repeated header row on a page break, etc.
            continue
        seen.add(isin)
        name = match["name"].strip()
        rows.append({
            "code": code_for_name(name),
            "name": name,
            "isin": isin,
            "sector": sector,
            "hi52": _to_float(match["hi52"]),
            "lo52": _to_float(match["lo52"]),
            "high": _to_float(match["high"]),
            "low": _to_float(match["low"]),
            "vwap": _to_float(match["vwap"]),
            "prev": _to_float(match["prev"]),
            "volume": _to_float(match["volume"]),
        })
    return pd.DataFrame(rows, columns=PRICE_LIST_COLUMNS)


def _pdf_text(content: bytes) -> Optional[str]:
    """Extract the text layer of a PDF, or ``None`` when it has none."""
    import pdfplumber  # optional dependency; guarded by is_available()

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages)
    return text if text.strip() else None


def fetch_price_list(day: date) -> Optional[pd.DataFrame]:
    """Download and parse the NSE daily price list for *day*.

    Args:
        day: Session date.

    Returns:
        The parsed list, or ``None`` when no list exists for that date
        (weekend, holiday, not yet published) or it carries no text layer.
    """
    global _scanned_warned
    if day in _PRICE_LIST_MEMO:
        return _PRICE_LIST_MEMO[day]

    result: Optional[pd.DataFrame] = None
    url = price_list_url(day)
    try:
        resp = throttled_get(url, host_key=HOST_KEY, min_interval=_min_interval(), timeout=30)
    except Exception as exc:  # network failure: skip this session, keep going
        logger.warning("nse_ke: %s request failed: %s", url, exc)
        return None  # not memoised — a transient failure may succeed later

    if resp.status_code == 404:
        _PRICE_LIST_MEMO[day] = None
        return None
    if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
        logger.warning("nse_ke: %s returned HTTP %s without a PDF", url, resp.status_code)
        return None

    text = _pdf_text(resp.content)
    if text is None:
        if not _scanned_warned:
            _scanned_warned = True
            logger.warning(
                "nse_ke: %s is a scanned image with no text layer; sessions "
                "published this way are skipped (OCR is not attempted)",
                url,
            )
    else:
        parsed = parse_price_list_text(text)
        result = parsed if not parsed.empty else None

    _PRICE_LIST_MEMO[day] = result
    return result


def latest_price_list_date(today: Optional[date] = None) -> Optional[date]:
    """Return the session date of the newest price list the NSE links to.

    Reads the market-statistics page, which links the latest Daily Equity Price
    List. The link — not a guess from the calendar — is what makes this robust
    to holidays and late publication.

    Args:
        today: Reference date, for tests. Defaults to today.

    Returns:
        The linked session date, or ``None`` when the page cannot be read.
    """
    try:
        resp = throttled_get(MARKET_STATS_URL, host_key=HOST_KEY, min_interval=_min_interval(), timeout=30)
    except Exception as exc:
        logger.warning("nse_ke: market-statistics page unavailable: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    dates = []
    for dd, mon, yy in _LIST_LINK_RE.findall(resp.text or ""):
        try:
            dates.append(date(2000 + int(yy), _MONTHS.index(mon.upper()) + 1, int(dd)))
        except ValueError:
            continue
    limit = today or date.today()
    dates = [d for d in dates if d <= limit]
    return max(dates) if dates else None


def latest_price_list(today: Optional[date] = None, lookback_days: int = 10) -> tuple[Optional[date], Optional[pd.DataFrame]]:
    """Return ``(session_date, price_list)`` for the most recent readable list.

    Tries the date the market-statistics page links first, then walks back
    weekday by weekday for up to *lookback_days* calendar days — covering a
    scanned or not-yet-published list.
    """
    start = today or date.today()
    candidates: list[date] = []
    linked = latest_price_list_date(start)
    if linked is not None:
        candidates.append(linked)
    for back in range(lookback_days + 1):
        day = start - timedelta(days=back)
        if day.weekday() < 5 and day not in candidates:
            candidates.append(day)
    for day in candidates:
        frame = fetch_price_list(day)
        if frame is not None:
            return day, frame
    return None, None


def _row_for(frame: pd.DataFrame, key: str) -> Optional[pd.Series]:
    """Find the row for a trading code or ISIN in one parsed price list."""
    column = "isin" if is_isin(key) else "code"
    hits = frame[frame[column] == key]
    if len(hits) != 1:
        return None
    return hits.iloc[0]


def _bar_from_row(row: pd.Series) -> Optional[dict]:
    """Turn one price-list row into an OHLCV bar, or ``None`` if it did not trade."""
    vwap, high, low = row["vwap"], row["high"], row["low"]
    volume = row["volume"]
    if vwap is None or pd.isna(vwap) or vwap <= 0:
        return None
    if volume is None or pd.isna(volume) or volume <= 0:
        return None
    high = vwap if high is None or pd.isna(high) else max(float(high), vwap)
    low = vwap if low is None or pd.isna(low) else min(float(low), vwap)
    prev = row["prev"]
    return {
        "open": float(vwap),
        "high": float(high),
        "low": float(low),
        "close": float(vwap),
        "volume": float(volume),
        "pre_close": float(prev) if prev is not None and pd.notna(prev) and prev > 0 else float("nan"),
    }


def _sessions(start_date: str, end_date: str) -> list[date]:
    """Weekdays in [start, end], newest last — candidate sessions to request."""
    days = pd.bdate_range(start=start_date, end=end_date)
    return [d.date() for d in days]


@register
class DataLoader:
    """NSE Kenya daily bars from the exchange's own daily price list."""

    name = "nse_ke"
    markets = {"kenya_equity"}
    volume_units = {"kenya_equity": "shares"}
    requires_auth = False

    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:
        """True when the optional ``pdfplumber`` dependency is installed."""
        try:
            import pdfplumber  # noqa: F401
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
        """Fetch daily bars for NSE symbols.

        Args:
            codes: Symbols such as ``["SCOM.NR", "KE0000000281.NR"]``.
            start_date: Inclusive start, ``YYYY-MM-DD``.
            end_date: Inclusive end, ``YYYY-MM-DD``.
            interval: Only daily (``1D``) is served; anything else returns ``{}``
                so the fallback chain moves on.
            fields: Unused (the list has a fixed shape).

        Returns:
            ``{symbol: DataFrame}`` indexed by ``trade_date`` with
            ``open, high, low, close, volume, pre_close``. Symbols with no
            traded session in the window are omitted.
        """
        validate_date_range(start_date, end_date)
        if str(interval).strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning("nse_ke serves daily bars only; interval %r is not supported", interval)
            return {}

        out: Dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                frame = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe="1D",
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(code, start_date, end_date),
                )
            except Exception as exc:  # one bad symbol never aborts the batch
                logger.warning("nse_ke: %s failed: %s", code, exc)
                continue
            if frame is not None and not frame.empty:
                out[code] = frame
        return out

    def _fetch_one(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        key = strip_suffix(code)
        if not is_isin(key) and key not in SECURITIES:
            logger.warning(
                "nse_ke: %s is neither a known NSE trading code nor an ISIN; "
                "pass the ISIN (e.g. KE0000000281.NR) for a security not in the table",
                code,
            )
            return None

        sessions = _sessions(start_date, end_date)
        cap = _max_sessions()
        if len(sessions) > cap:
            logger.warning(
                "nse_ke: %s spans %d sessions; reading the latest %d (raise %s to extend, "
                "or seed older history through a local: CSV)",
                code, len(sessions), cap, _MAX_SESSIONS_ENV,
            )
            sessions = sessions[-cap:]

        records: list[dict] = []
        index: list[pd.Timestamp] = []
        for day in sessions:
            listing = fetch_price_list(day)
            if listing is None:
                continue
            row = _row_for(listing, key)
            if row is None:
                continue
            bar = _bar_from_row(row)
            if bar is None:
                continue
            records.append(bar)
            index.append(pd.Timestamp(day))

        if not records:
            return None
        frame = pd.DataFrame(records, index=pd.DatetimeIndex(index, name="trade_date"))
        frame = frame[_OUTPUT_COLUMNS].sort_index()
        return frame.astype(float)


def clear_memo() -> None:
    """Forget every parsed price list held in this process (tests, long sessions)."""
    global _scanned_warned
    _PRICE_LIST_MEMO.clear()
    _scanned_warned = False


__all__ = [
    "DataLoader",
    "PRICE_LIST_COLUMNS",
    "clear_memo",
    "fetch_price_list",
    "latest_price_list",
    "latest_price_list_date",
    "parse_price_list_text",
    "price_list_url",
]

