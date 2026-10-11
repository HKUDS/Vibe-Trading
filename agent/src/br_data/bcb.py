"""Banco Central do Brasil — SGS time series (Selic, CDI, IPCA, PTAX ...).

API: ``https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados``
``?formato=json&dataInicial=dd/mm/yyyy&dataFinal=dd/mm/yyyy`` returns
``[{"data": "dd/mm/yyyy", "valor": "1.23"}, ...]``. Daily series are served in
windows of at most 10 years, so requests are chunked.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from backtest.loaders._http import throttled_get
from src.br_data._download import br_date, to_float

logger = logging.getLogger(__name__)

HOST_KEY = "bcb_sgs"
BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
_WINDOW_DAYS = 365 * 5

# Series synced by default (code -> description).
SERIES: dict[int, str] = {
    11: "Selic diária (% a.d.)",
    432: "Meta Selic (% a.a.)",
    12: "CDI diário (% a.d.)",
    4389: "CDI anualizado base 252 (% a.a.)",
    433: "IPCA mensal (%)",
    13522: "IPCA acumulado 12 meses (%)",
    189: "IGP-M mensal (%)",
    188: "INPC mensal (%)",
    1: "Dólar comercial venda - PTAX (R$/US$)",
    21619: "Euro venda - PTAX (R$/€)",
    4380: "PIB mensal - valores correntes (R$ milhões)",
    24369: "Taxa de desocupação - PNAD (%)",
}


def fetch_series(code: int, start: date, end: date) -> list[tuple[str, Optional[float]]]:
    """Download ``code`` between ``start`` and ``end`` (inclusive)."""
    out: list[tuple[str, Optional[float]]] = []
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=_WINDOW_DAYS), end)
        response = throttled_get(
            BASE_URL.format(code=code),
            host_key=HOST_KEY,
            min_interval=0.5,
            params={
                "formato": "json",
                "dataInicial": f"{window_start:%d/%m/%Y}",
                "dataFinal": f"{window_end:%d/%m/%Y}",
            },
            timeout=60,
        )
        # SGS answers 404 for a window with no observations (e.g. a monthly
        # series queried over a few days); that is "no data", not an error.
        if response.status_code == 404:
            window_start = window_end + timedelta(days=1)
            continue
        response.raise_for_status()
        for item in response.json() or []:
            obs = br_date(item.get("data"))
            if obs:
                out.append((obs, to_float(item.get("valor"))))
        window_start = window_end + timedelta(days=1)
    return out


def store_series(conn: sqlite3.Connection, code: int, rows: list[tuple[str, Optional[float]]]) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO bcb_series (code, obs_date, value) VALUES (?, ?, ?)",
        [(code, obs, value) for obs, value in rows],
    )
    return len(rows)


def sync(conn: sqlite3.Connection, start_year: int, today: date, codes: Optional[list[int]] = None) -> int:
    """Top up each series from its last stored observation (or ``start_year``)."""
    total = 0
    failures: list[str] = []
    codes = codes or list(SERIES)
    for code in codes:
        row = conn.execute("SELECT MAX(obs_date) FROM bcb_series WHERE code = ?", (code,)).fetchone()
        start = date.fromisoformat(row[0]) - timedelta(days=45) if row and row[0] else date(start_year, 1, 1)
        try:
            total += store_series(conn, code, fetch_series(code, start, today))
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - one series must not stop the rest
            logger.warning("bcb: series %s failed: %s", code, exc)
            failures.append(f"{code}: {type(exc).__name__}")
    if failures and len(failures) == len(codes):
        raise RuntimeError(f"every BCB series failed ({'; '.join(failures)})")
    return total
