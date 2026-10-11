"""CVM investment funds: register and daily report (informe diário).

* Daily report — quota value, net assets, inflows/outflows and holders of
  every registered fund/class, one ZIP per month:
  ``FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{YYYYMM}.zip`` (older years as
  ``.../DADOS/HIST/inf_diario_fi_{YYYY}.zip``). Since CVM Resolution 175 the
  key columns are ``CNPJ_FUNDO_CLASSE``/``TP_FUNDO_CLASSE``/``ID_SUBCLASSE``;
  older files use ``CNPJ_FUNDO``/``TP_FUNDO``. Both are accepted.
* Register — legacy ``FI/CAD/DADOS/cad_fi.csv`` plus the post-175
  ``FI/CAD/DADOS/registro_fundo_classe.zip`` (fund and class registers).

Column lookups are case-insensitive and tolerate either naming, because CVM
renames columns between layouts.
"""

from __future__ import annotations

import csv
import io
import logging
import sqlite3
from datetime import date
from typing import Iterable, Iterator, Optional

from src.br_data._download import br_date, decode_text, digits, fetch_bytes, to_float, zip_members
from src.br_data.store import is_done, mark_done

logger = logging.getLogger(__name__)

HOST_KEY = "cvm"
BASE_URL = "https://dados.cvm.gov.br/dados/FI"

_INSERT_DAILY = (
    "INSERT OR REPLACE INTO cvm_fund_daily (cnpj, trade_date, fund_type, subclass, "
    "total_value, quota, net_assets, inflows, outflows, holders) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_UPSERT_FUND = (
    "INSERT INTO cvm_funds (cnpj, name, status, fund_class, fund_type, manager, admin, "
    "benchmark, start_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(cnpj) DO UPDATE SET "
    "name = COALESCE(excluded.name, name), status = COALESCE(excluded.status, status), "
    "fund_class = COALESCE(excluded.fund_class, fund_class), "
    "fund_type = COALESCE(excluded.fund_type, fund_type), "
    "manager = COALESCE(excluded.manager, manager), admin = COALESCE(excluded.admin, admin), "
    "benchmark = COALESCE(excluded.benchmark, benchmark), "
    "start_date = COALESCE(excluded.start_date, start_date)"
)


def _rows(text: str) -> Iterator[dict[str, str]]:
    """Iterate a ``;``-separated CVM CSV with upper-cased header keys."""
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        yield {str(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}


def _pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name.upper())
        if value:
            return value
    return ""


def _opt(value: str) -> Optional[str]:
    return value or None


def parse_daily(text: str) -> Iterator[tuple]:
    """Yield ``cvm_fund_daily`` tuples from one informe-diário CSV."""
    for row in _rows(text):
        cnpj = digits(_pick(row, "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"))
        trade_date = br_date(_pick(row, "DT_COMPTC"))
        if not cnpj or not trade_date:
            continue
        holders = to_float(_pick(row, "NR_COTST"))
        yield (
            cnpj,
            trade_date,
            _opt(_pick(row, "TP_FUNDO_CLASSE", "TP_FUNDO")),
            _pick(row, "ID_SUBCLASSE"),
            to_float(_pick(row, "VL_TOTAL")),
            to_float(_pick(row, "VL_QUOTA")),
            to_float(_pick(row, "VL_PATRIM_LIQ")),
            to_float(_pick(row, "CAPTC_DIA")),
            to_float(_pick(row, "RESG_DIA")),
            int(holders) if holders is not None else None,
        )


def ingest_daily_zip(conn: sqlite3.Connection, payload: bytes) -> int:
    """Insert every CSV inside an informe-diário ZIP; return the row count."""
    total = 0
    for name, raw in zip_members(payload).items():
        if not name.lower().endswith(".csv"):
            continue
        batch = list(parse_daily(decode_text(raw)))
        conn.executemany(_INSERT_DAILY, batch)
        total += len(batch)
    return total


def parse_register(text: str) -> Iterator[tuple]:
    """Yield ``cvm_funds`` tuples from cad_fi.csv or registro_*.csv."""
    for row in _rows(text):
        cnpj = digits(_pick(row, "CNPJ_FUNDO", "CNPJ_CLASSE", "CNPJ_FUNDO_CLASSE"))
        if not cnpj:
            continue
        yield (
            cnpj,
            _opt(_pick(row, "DENOM_SOCIAL", "DENOMINACAO_SOCIAL")),
            _opt(_pick(row, "SIT", "SITUACAO")),
            _opt(_pick(row, "CLASSE", "CLASSIFICACAO", "CLASSE_ANBIMA")),
            _opt(_pick(row, "TP_FUNDO", "TIPO_CLASSE", "TIPO_FUNDO")),
            _opt(_pick(row, "GESTOR")),
            _opt(_pick(row, "ADMIN", "ADMINISTRADOR")),
            _opt(_pick(row, "RENTAB_FUNDO", "INDICADOR_DESEMPENHO")),
            br_date(_pick(row, "DT_INI_ATIV", "DATA_INICIO", "DT_REG", "DATA_REGISTRO")),
        )


def _months(start: date, end: date) -> Iterable[tuple[int, int]]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        month += 1
        if month == 13:
            year, month = year + 1, 1


def sync_register(conn: sqlite3.Connection) -> int:
    """Refresh the fund register (both layouts, best effort each)."""
    total = 0
    legacy = fetch_bytes(f"{BASE_URL}/CAD/DADOS/cad_fi.csv", HOST_KEY)
    if legacy is not None:
        batch = list(parse_register(decode_text(legacy)))
        conn.executemany(_UPSERT_FUND, batch)
        total += len(batch)
    current = fetch_bytes(f"{BASE_URL}/CAD/DADOS/registro_fundo_classe.zip", HOST_KEY)
    if current is not None:
        for name, raw in zip_members(current).items():
            if name.lower().endswith(".csv") and "subclasse" not in name.lower():
                batch = list(parse_register(decode_text(raw)))
                conn.executemany(_UPSERT_FUND, batch)
                total += len(batch)
    conn.commit()
    return total


def sync_daily(conn: sqlite3.Connection, start_year: int, today: date) -> int:
    """Fetch monthly reports; the last two months are always refreshed.

    CVM revises recent months, so only months older than that are recorded as
    done. A month that 404s falls back to the yearly HIST archive once.
    """
    total = 0
    recent = {(today.year, today.month)}
    prev = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    recent.add(prev)
    hist_years_done: set[int] = set()
    for year, month in _months(date(start_year, 1, 1), today):
        item = f"{year}{month:02d}"
        if (year, month) not in recent and is_done(conn, "cvm_fund_daily", item):
            continue
        payload = fetch_bytes(f"{BASE_URL}/DOC/INF_DIARIO/DADOS/inf_diario_fi_{item}.zip", HOST_KEY)
        if payload is None:
            if year in hist_years_done or is_done(conn, "cvm_fund_daily", f"HIST{year}"):
                continue
            hist = fetch_bytes(f"{BASE_URL}/DOC/INF_DIARIO/DADOS/HIST/inf_diario_fi_{year}.zip", HOST_KEY)
            hist_years_done.add(year)
            if hist is not None:
                rows = ingest_daily_zip(conn, hist)
                mark_done(conn, "cvm_fund_daily", f"HIST{year}", rows)
                conn.commit()
                total += rows
            continue
        rows = ingest_daily_zip(conn, payload)
        if (year, month) not in recent:
            mark_done(conn, "cvm_fund_daily", item, rows)
        conn.commit()
        total += rows
    return total
