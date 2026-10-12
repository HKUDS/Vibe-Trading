"""B3 COTAHIST: daily quotes of every instrument traded on B3.

B3 publishes the "Séries Históricas" as fixed-width text files (245 chars per
record, Latin-1) inside ZIPs:

* yearly  ``COTAHIST_A{YYYY}.ZIP`` (1986 onwards; the current year is updated
  every trading day)
* daily   ``COTAHIST_D{DDMMYYYY}.ZIP``

Record layout (type 01, 1-based positions from B3's published layout):
DATA 3-10, CODBDI 11-12, CODNEG 13-24, TPMERC 25-27, NOMRES 28-39,
ESPECI 40-49, PREABE 57-69, PREMAX 70-82, PREMIN 83-95, PREMED 96-108,
PREULT 109-121, PREOFC 122-134, PREOFV 135-147, TOTNEG 148-152,
QUATOT 153-170, VOLTOT 171-188, PREEXE 189-201, DATVEN 203-210,
FATCOT 211-217, CODISI 231-242. Prices carry two implied decimals and are
quoted per FATCOT units.

Prices are as traded (not adjusted for dividends or splits).
"""

from __future__ import annotations

import io
import logging
import sqlite3
import zipfile
from datetime import date, timedelta
from typing import Iterable, Iterator, Optional

from src.br_data._download import fetch_bytes
from src.br_data.store import is_done, mark_done

logger = logging.getLogger(__name__)

HOST_KEY = "b3_cotahist"
BASE_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
FIRST_YEAR = 1986

_COLUMNS = (
    "trade_date", "ticker", "bdi", "market_type", "short_name", "spec",
    "open", "high", "low", "avg", "close", "best_bid", "best_ask",
    "trades", "volume", "turnover", "strike", "expiry", "quote_factor", "isin",
)
_INSERT = (
    f"INSERT OR REPLACE INTO b3_quotes ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _COLUMNS)})"
)


def _num(field: str) -> int:
    field = field.strip()
    return int(field) if field.isdigit() else 0


def _iso(field: str) -> Optional[str]:
    field = field.strip()
    if len(field) != 8 or not field.isdigit() or field == "99991231":
        return None
    try:
        return date(int(field[:4]), int(field[4:6]), int(field[6:8])).isoformat()
    except ValueError:
        return None


def parse_record(line: str) -> Optional[tuple]:
    """Parse one COTAHIST line; ``None`` for header/trailer/malformed lines."""
    if len(line) < 245 or not line.startswith("01"):
        return None
    trade_date = _iso(line[2:10])
    if trade_date is None:
        return None
    # Earlier COTAHIST history contains pre-real currencies. Never stamp those
    # prices as BRL, nor fabricate missing quotation factors or OHLC values.
    if line[52:56].strip() != "R$":
        return None
    factor = _num(line[210:217])
    if factor <= 0 or any(not line[a:b].strip().isdigit()
                          for a, b in ((56, 69), (69, 82), (82, 95), (108, 121))):
        return None

    def price(start: int, end: int) -> float:
        return _num(line[start:end]) / 100.0 / factor

    return (
        trade_date,
        line[12:24].strip(),
        line[10:12].strip(),
        _num(line[24:27]),
        line[27:39].strip(),
        line[39:49].strip(),
        price(56, 69),
        price(69, 82),
        price(82, 95),
        price(95, 108),
        price(108, 121),
        price(121, 134),
        price(134, 147),
        _num(line[147:152]),
        float(_num(line[152:170])),
        _num(line[170:188]) / 100.0,
        _num(line[188:201]) / 100.0 / factor,
        _iso(line[202:210]),
        factor,
        line[230:242].strip(),
    )


def parse_text(text: str) -> Iterator[tuple]:
    """Yield parsed records from a whole COTAHIST text body."""
    for line in text.splitlines():
        record = parse_record(line)
        if record is not None:
            yield record


def ingest_zip(conn: sqlite3.Connection, payload: bytes) -> int:
    """Insert every record of a COTAHIST ZIP; return the row count.

    The yearly text is several hundred MB once unzipped, so it is streamed
    line by line instead of being decoded in one piece.
    """
    total = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            batch: list[tuple] = []
            with archive.open(info) as raw:
                for line in io.TextIOWrapper(raw, encoding="latin-1", newline=""):
                    record = parse_record(line.rstrip("\r\n"))
                    if record is None:
                        continue
                    batch.append(record)
                    if len(batch) >= 50_000:
                        conn.executemany(_INSERT, batch)
                        total += len(batch)
                        batch.clear()
            if batch:
                conn.executemany(_INSERT, batch)
                total += len(batch)
    return total


def _last_date(conn: sqlite3.Connection) -> Optional[date]:
    row = conn.execute("SELECT MAX(trade_date) FROM b3_quotes").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def _weekdays(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def sync(conn: sqlite3.Connection, start_year: int, today: date) -> int:
    """Download missing years in full, then the current year day by day.

    Past years are fetched once (tracked in ``sync_log``). The current year is
    fetched as one yearly file on first run, then topped up with the small
    daily files for every weekday after the last stored date (holidays answer
    404 and are skipped).
    """
    start_year = max(start_year, FIRST_YEAR)
    total = 0
    for year in range(start_year, today.year):
        item = f"A{year}"
        if is_done(conn, "cotahist", item):
            continue
        logger.info("cotahist: downloading %s", item)
        payload = fetch_bytes(f"{BASE_URL}/COTAHIST_A{year}.ZIP", HOST_KEY)
        if payload is None:
            logger.warning("cotahist: %s not published", item)
            continue
        rows = ingest_zip(conn, payload)
        mark_done(conn, "cotahist", item, rows)
        conn.commit()
        total += rows

    last = _last_date(conn)
    if last is None or last.year < today.year:
        logger.info("cotahist: downloading A%s (year to date)", today.year)
        payload = fetch_bytes(f"{BASE_URL}/COTAHIST_A{today.year}.ZIP", HOST_KEY)
        if payload is not None:
            total += ingest_zip(conn, payload)
            conn.commit()
        last = _last_date(conn)

    if last is not None and last.year == today.year:
        for day in _weekdays(last + timedelta(days=1), today):
            payload = fetch_bytes(f"{BASE_URL}/COTAHIST_D{day:%d%m%Y}.ZIP", HOST_KEY)
            if payload is None:
                continue
            total += ingest_zip(conn, payload)
            conn.commit()
    return total
