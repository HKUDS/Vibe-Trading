"""DNSE (DNSE LightSpeed) broker journal parser.

Modern English-only export from DNSE's LightSpeed mobile app. Distinguished
from HSC by short column names: Volume/Price/Net Value vs HSC's
Quantity/Matched Price/Net Amount.

Typical schema:
  Trade Date | Symbol | Side | Volume | Price | Net Value | Fee

Note: DNSE often nets sell-side tax into Net Value rather than reporting it
as a separate column. Parser tolerates absence of Tax column.
"""

from __future__ import annotations

import pandas as pd

from src.tools.trade_journal_parsers import TradeRecord
from src.tools.journal_parsers_vn import register_vn_parser
from src.tools.journal_parsers_vn._common import (
    _qualify_vn_symbol,
    _normalize_vn_side,
    _parse_vn_date,
    _to_float_vn,
)

_REQUIRED = {"Trade Date", "Symbol", "Side", "Volume", "Price"}


class DNSEParser:
    name = "dnse"

    def detect(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return False
        cols = set(str(c).strip() for c in df.columns)
        if len(_REQUIRED & cols) < 4:
            return False
        # Disambiguate from HSC (Quantity / Matched Price / Net Amount)
        if "Quantity" in cols or "Matched Price" in cols or "Net Amount" in cols:
            return False
        # Disambiguate from any SSI-EN variant (Match Volume / Match Price)
        if "Match Volume" in cols or "Match Price" in cols:
            return False
        return True

    def parse(self, df: pd.DataFrame) -> list:
        records: list = []
        cols = set(str(c).strip() for c in df.columns)
        col_amt = "Net Value" if "Net Value" in cols else None
        col_fee = "Fee" if "Fee" in cols else None
        col_tax = "Tax" if "Tax" in cols else None  # rarely present
        col_name = next((c for c in ("Stock Name", "Name") if c in cols), None)
        for _, row in df.iterrows():
            try:
                qty = _to_float_vn(row.get("Volume"), 0.0)
                if qty <= 0:
                    continue
                sym = str(row.get("Symbol", "")).strip()
                if not sym:
                    continue
                side = _normalize_vn_side(row.get("Side"))
                price = _to_float_vn(row.get("Price"), 0.0)
                amt = _to_float_vn(row.get(col_amt), 0.0) if col_amt else qty * price
                fee = _to_float_vn(row.get(col_fee), 0.0) if col_fee else 0.0
                tax = _to_float_vn(row.get(col_tax), 0.0) if col_tax else 0.0
                records.append(TradeRecord(
                    datetime=_parse_vn_date(row.get("Trade Date")),
                    symbol=_qualify_vn_symbol(sym),
                    name=str(row.get(col_name, "")).strip() if col_name else "",
                    side=side,
                    quantity=qty,
                    price=price,
                    amount=amt,
                    fee=fee + tax,
                    market="vn_equity",
                ))
            except (ValueError, KeyError):
                continue
        return records


register_vn_parser(DNSEParser())
