"""CVM listed companies: register, ticker map and financial statements.

* ``CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv`` — company register.
* ``CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{YYYY}.zip`` — the
  ``valor_mobiliario`` file maps B3 tickers (``Codigo_Negociacao``) to CNPJ.
* ``CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{YYYY}.zip`` (annual) and
  ``.../ITR/DADOS/itr_cia_aberta_{YYYY}.zip`` (quarterly) — one CSV per
  statement, e.g. ``dfp_cia_aberta_DRE_con_2025.csv``.

Only the current-period column (``ORDEM_EXERC = ÚLTIMO``) is kept and the
highest ``VERSAO`` wins. Consolidated statements are stored as ``DRE``,
``BPA`` ...; individual (parent-only) ones as ``DRE_ind`` ...
``ESCALA_MOEDA = MIL`` values are multiplied by 1000 so every value is BRL.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
from datetime import date
from typing import Iterator, Optional

from src.br_data._download import br_date, decode_text, digits, fetch_bytes, to_float, zip_members
from src.br_data.store import is_done, mark_done

logger = logging.getLogger(__name__)

HOST_KEY = "cvm"
BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA"

_STATEMENT_FILE = re.compile(
    r"(?:dfp|itr)_cia_aberta_(?P<stmt>[A-Z_]+?)_(?P<scope>con|ind)_\d{4}\.csv$", re.I
)
_UPSERT_STATEMENT = (
    "INSERT INTO cvm_statements (cnpj, doc, statement, period_end, period_start, account, "
    "description, value, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(cnpj, doc, statement, period_end, period_start, account) DO UPDATE SET "
    "description = excluded.description, value = excluded.value, version = excluded.version "
    "WHERE excluded.version >= cvm_statements.version"
)


def _rows(text: str) -> Iterator[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        yield {str(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}


def _opt(value: Optional[str]) -> Optional[str]:
    return value or None


def parse_register(text: str) -> Iterator[tuple]:
    """Yield ``cvm_companies`` tuples from cad_cia_aberta.csv."""
    for row in _rows(text):
        cnpj = digits(row.get("CNPJ_CIA"))
        if not cnpj:
            continue
        yield (
            cnpj,
            _opt(row.get("CD_CVM")),
            _opt(row.get("DENOM_SOCIAL")),
            _opt(row.get("DENOM_COMERC")),
            _opt(row.get("SIT")),
            _opt(row.get("SETOR_ATIV")),
        )


def parse_tickers(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(ticker, cnpj)`` from an FCA valor_mobiliario CSV."""
    for row in _rows(text):
        ticker = (row.get("CODIGO_NEGOCIACAO") or "").upper()
        cnpj = digits(row.get("CNPJ_COMPANHIA") or row.get("CNPJ_CIA"))
        if ticker and cnpj and re.fullmatch(r"[A-Z0-9]{4,12}", ticker):
            yield ticker, cnpj


def parse_statement(text: str, doc: str, statement: str) -> Iterator[tuple]:
    """Yield ``cvm_statements`` tuples from one DFP/ITR statement CSV."""
    for row in _rows(text):
        order = row.get("ORDEM_EXERC", "").upper()
        if order and not order.startswith(("ÚLTIMO", "ULTIMO")):
            continue
        cnpj = digits(row.get("CNPJ_CIA"))
        period_end = br_date(row.get("DT_FIM_EXERC") or row.get("DT_REFER"))
        account = row.get("CD_CONTA", "")
        if not cnpj or not period_end or not account:
            continue
        currency = row.get("MOEDA", "").upper()
        if currency and currency not in {"REAL", "REAIS", "BRL", "R$"}:
            raise ValueError(f"Unsupported CVM statement currency: {currency}")
        value = to_float(row.get("VL_CONTA"))
        if value is not None and row.get("ESCALA_MOEDA", "").upper() == "MIL":
            value *= 1000.0
        version = to_float(row.get("VERSAO"))
        yield (
            cnpj,
            doc,
            statement,
            period_end,
            br_date(row.get("DT_INI_EXERC")) or "",
            account,
            _opt(row.get("DS_CONTA")),
            value,
            int(version) if version is not None else 0,
        )


def ingest_statements_zip(conn: sqlite3.Connection, payload: bytes, doc: str) -> int:
    """Insert every statement CSV of a DFP/ITR ZIP; return the row count."""
    total = 0
    for name, raw in zip_members(payload).items():
        match = _STATEMENT_FILE.search(name.rsplit("/", 1)[-1])
        if not match:
            continue
        statement = match.group("stmt").upper()
        if match.group("scope").lower() == "ind":
            statement += "_ind"
        batch = list(parse_statement(decode_text(raw), doc, statement))
        conn.executemany(_UPSERT_STATEMENT, batch)
        total += len(batch)
    return total


def sync(conn: sqlite3.Connection, start_year: int, today: date) -> int:
    """Refresh register + tickers, then DFP/ITR from ``start_year``.

    The current and previous year are always refreshed (filings and
    restatements keep arriving); older years are fetched once.
    """
    total = 0
    register = fetch_bytes(f"{BASE_URL}/CAD/DADOS/cad_cia_aberta.csv", HOST_KEY)
    if register is not None:
        batch = list(parse_register(decode_text(register)))
        conn.executemany("INSERT OR REPLACE INTO cvm_companies VALUES (?, ?, ?, ?, ?, ?)", batch)
        total += len(batch)
        conn.commit()

    for year in (today.year, today.year - 1):
        fca = fetch_bytes(f"{BASE_URL}/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip", HOST_KEY)
        if fca is None:
            continue
        for name, raw in zip_members(fca).items():
            if "valor_mobiliario" in name.lower():
                pairs = list(parse_tickers(decode_text(raw)))
                conn.executemany("INSERT OR REPLACE INTO cvm_company_tickers VALUES (?, ?)", pairs)
                total += len(pairs)
        conn.commit()
        break

    for doc in ("DFP", "ITR"):
        for year in range(start_year, today.year + 1):
            item = f"{doc}{year}"
            recent = year >= today.year - 1
            if not recent and is_done(conn, "cvm_statements", item):
                continue
            url = f"{BASE_URL}/DOC/{doc}/DADOS/{doc.lower()}_cia_aberta_{year}.zip"
            payload = fetch_bytes(url, HOST_KEY)
            if payload is None:
                continue
            rows = ingest_statements_zip(conn, payload, doc)
            if not recent:
                mark_done(conn, "cvm_statements", item, rows)
            conn.commit()
            total += rows
    return total
