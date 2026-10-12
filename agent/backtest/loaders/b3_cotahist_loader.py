"""B3 COTAHIST loader: official daily bars for every B3 instrument.

Reads the local SQLite store filled by ``python -m src.br_data sync`` (see
:mod:`src.br_data.cotahist`); it never touches the network, so it is the
offline fallback of the ``br_equity`` chain after Yahoo/yfinance.

Symbol convention: ``PETR4.SA`` -> COTAHIST ``CODNEG`` ``PETR4``. Round-lot
rows (TPMERC 010) are served; ``PETR4F.SA`` reads the odd-lot market (020).
Prices are as traded (caliber ``raw``): no dividend/split adjustment.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import normalize_declared_quote_currency, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OUTPUT_COLUMNS = ["open", "high", "low", "close", "volume"]
_CASH_MARKET = 10
_ODD_LOT_MARKET = 20


def map_symbol(code: str) -> tuple[str, int]:
    """``PETR4.SA`` -> (``PETR4``, 10); ``PETR4F.SA`` -> (``PETR4F``, 20)."""
    ticker = code.strip().upper()
    if ticker.endswith(".SA"):
        ticker = ticker[:-3]
    market = _ODD_LOT_MARKET if ticker.endswith("F") and ticker[-2:-1].isdigit() else _CASH_MARKET
    return ticker, market


@register
class DataLoader:
    """Offline B3 daily bars from the official COTAHIST files."""

    name = "b3_cotahist"
    markets = {"br_equity"}
    # QUATOT is the number of securities traded.
    volume_units = {"br_equity": "shares"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available once a sync has created the store."""
        from src.br_data.store import db_path

        return db_path().exists()

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Return ``{code: OHLCV frame}`` for codes present in the store."""
        validate_date_range(start_date, end_date)
        if str(interval).strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning("b3_cotahist serves daily bars only; rejecting interval=%r", interval)
            return {}
        from src.br_data.store import connect

        result: Dict[str, pd.DataFrame] = {}
        try:
            with connect() as conn:
                for code in codes:
                    ticker, market = map_symbol(code)
                    rows = conn.execute(
                        "SELECT trade_date, open, high, low, close, volume FROM b3_quotes "
                        "WHERE ticker = ? AND market_type = ? AND trade_date BETWEEN ? AND ? "
                        "ORDER BY trade_date",
                        (ticker, market, start_date[:10], end_date[:10]),
                    ).fetchall()
                    if not rows:
                        continue
                    frame = pd.DataFrame([tuple(r) for r in rows], columns=["trade_date", *_OUTPUT_COLUMNS])
                    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
                    frame = frame.set_index("trade_date").astype(float)
                    # The importer admits only explicit R$ records, excluding older currencies.
                    result[code] = normalize_declared_quote_currency(frame, code, "BRL")
        except FileNotFoundError as exc:
            logger.warning("b3_cotahist: %s", exc)
        return result
