"""SQLite store for the Brazilian official datasets."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.config.accessor import get_env_config

DEFAULT_DB_PATH = Path.home() / ".vibe-trading" / "br-data" / "br_data.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS b3_quotes (
    trade_date   TEXT NOT NULL,      -- YYYY-MM-DD
    ticker       TEXT NOT NULL,      -- CODNEG, e.g. PETR4, PETR4F, PETRJ300
    bdi          TEXT,               -- CODBDI
    market_type  INTEGER,            -- TPMERC: 10 cash, 20 odd lot, 70/80 options ...
    short_name   TEXT,               -- NOMRES
    spec         TEXT,               -- ESPECI (ON, PN, CI, DRN ...)
    open         REAL,
    high         REAL,
    low          REAL,
    avg          REAL,
    close        REAL,
    best_bid     REAL,
    best_ask     REAL,
    trades       INTEGER,
    volume       REAL,               -- QUATOT, number of securities traded
    turnover     REAL,               -- VOLTOT, BRL
    strike       REAL,
    expiry       TEXT,
    quote_factor INTEGER,
    isin         TEXT,
    PRIMARY KEY (ticker, trade_date, market_type)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_b3_quotes_date ON b3_quotes(trade_date);

CREATE TABLE IF NOT EXISTS cvm_fund_daily (
    cnpj        TEXT NOT NULL,       -- digits only
    trade_date  TEXT NOT NULL,
    fund_type   TEXT,
    subclass    TEXT NOT NULL DEFAULT '',
    total_value REAL,
    quota       REAL,
    net_assets  REAL,
    inflows     REAL,
    outflows    REAL,
    holders     INTEGER,
    PRIMARY KEY (cnpj, subclass, trade_date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS cvm_funds (
    cnpj       TEXT PRIMARY KEY,
    name       TEXT,
    status     TEXT,
    fund_class TEXT,
    fund_type  TEXT,
    manager    TEXT,
    admin      TEXT,
    benchmark  TEXT,
    start_date TEXT
);

CREATE TABLE IF NOT EXISTS cvm_companies (
    cnpj        TEXT PRIMARY KEY,
    cvm_code    TEXT,
    name        TEXT,
    trade_name  TEXT,
    status      TEXT,
    sector      TEXT
);

CREATE TABLE IF NOT EXISTS cvm_company_tickers (
    ticker TEXT PRIMARY KEY,
    cnpj   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cvm_statements (
    cnpj        TEXT NOT NULL,
    doc         TEXT NOT NULL,        -- DFP (annual) or ITR (quarterly)
    statement   TEXT NOT NULL,        -- BPA, BPP, DRE, DFC_MD, DFC_MI, DVA, DRA, DMPL
    period_end  TEXT NOT NULL,
    period_start TEXT NOT NULL DEFAULT '',
    account     TEXT NOT NULL,        -- CD_CONTA, e.g. 3.01
    description TEXT,
    value       REAL,                 -- in BRL units (ESCALA_MOEDA applied)
    version     INTEGER,
    PRIMARY KEY (cnpj, doc, statement, period_end, period_start, account)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bcb_series (
    code       INTEGER NOT NULL,
    obs_date   TEXT NOT NULL,
    value      REAL,
    PRIMARY KEY (code, obs_date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS tesouro_prices (
    bond        TEXT NOT NULL,        -- e.g. "Tesouro IPCA+"
    maturity    TEXT NOT NULL,
    base_date   TEXT NOT NULL,
    buy_rate    REAL,
    sell_rate   REAL,
    buy_price   REAL,
    sell_price  REAL,
    base_price  REAL,
    PRIMARY KEY (bond, maturity, base_date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sync_log (
    source  TEXT NOT NULL,
    item    TEXT NOT NULL,
    done_at TEXT NOT NULL,
    rows    INTEGER,
    PRIMARY KEY (source, item)
);
"""


def db_path() -> Path:
    """Return the configured SQLite path (``VIBE_BR_DATA_DB`` or the default)."""
    configured = get_env_config().data.vibe_br_data_db.strip()
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def init_db(path: Path | None = None) -> Path:
    """Create the database file and tables when missing; return its path."""
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
    return target


@contextmanager
def connect(path: Path | None = None, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the store. Read-only connections never create the file.

    Raises:
        FileNotFoundError: On a read-only open when no sync has run yet.
    """
    target = path or db_path()
    if write:
        init_db(target)
        conn = sqlite3.connect(target, timeout=60)
    else:
        if not target.exists():
            raise FileNotFoundError(
                f"Brazilian data store not found at {target}; run "
                "`python -m src.br_data sync` first"
            )
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if write:
            conn.commit()
    finally:
        conn.close()


def mark_done(conn: sqlite3.Connection, source: str, item: str, rows: int) -> None:
    """Record that ``source/item`` was fully ingested."""
    from datetime import datetime, timezone

    conn.execute(
        "INSERT OR REPLACE INTO sync_log(source, item, done_at, rows) VALUES (?, ?, ?, ?)",
        (source, item, datetime.now(timezone.utc).isoformat(timespec="seconds"), rows),
    )


def is_done(conn: sqlite3.Connection, source: str, item: str) -> bool:
    """Whether ``source/item`` was already ingested."""
    row = conn.execute(
        "SELECT 1 FROM sync_log WHERE source = ? AND item = ?", (source, item)
    ).fetchone()
    return row is not None
