"""Tesouro Direto prices and yields (Tesouro Transparente open data).

One ``;``-separated CSV with the whole history, Brazilian number format:
``Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;
PU Compra Manha;PU Venda Manha;PU Base Manha``.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Iterator

from src.br_data._download import br_date, decode_text, fetch_bytes, to_float

HOST_KEY = "tesouro"
URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)


def parse(text: str) -> Iterator[tuple]:
    """Yield ``tesouro_prices`` tuples from the published CSV."""
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        row = {str(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        bond = row.get("tipo titulo", "")
        maturity = br_date(row.get("data vencimento"))
        base = br_date(row.get("data base"))
        if not bond or not maturity or not base:
            continue
        yield (
            bond,
            maturity,
            base,
            to_float(row.get("taxa compra manha")),
            to_float(row.get("taxa venda manha")),
            to_float(row.get("pu compra manha")),
            to_float(row.get("pu venda manha")),
            to_float(row.get("pu base manha")),
        )


def sync(conn: sqlite3.Connection) -> int:
    """Download the full history (a few MB) and upsert it."""
    payload = fetch_bytes(URL, HOST_KEY)
    if payload is None:
        return 0
    rows = list(parse(decode_text(payload)))
    conn.executemany("INSERT OR REPLACE INTO tesouro_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)
