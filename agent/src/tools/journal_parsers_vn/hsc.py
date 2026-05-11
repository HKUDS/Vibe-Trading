"""HSC (Ho Chi Minh Securities) broker journal parser.

Primary schema: English. Vietnamese variant also supported.

Typical schema (English):
  Trade Date | Symbol | Stock Name | Side | Quantity | Matched Price | Net Amount | Fee | Tax

Vietnamese variant:
  Ngày giao dịch | Mã chứng khoán | Loại giao dịch | Khối lượng khớp | Giá khớp | Giá trị | Phí | Thuế

Disambiguation: SSI uses 'Match Volume' (English) — HSC uses 'Quantity'.
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


_EN_SIGNATURE = {"Trade Date", "Symbol", "Side", "Quantity", "Matched Price"}
_VN_SIGNATURE = {
    "Ngày giao dịch",
    "Mã chứng khoán",
    "Loại giao dịch",
    "Khối lượng khớp",
    "Giá khớp",
}


class HSCParser:
    name = "hsc"

    def detect(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return False
        cols = set(str(c).strip() for c in df.columns)
        en_match = len(_EN_SIGNATURE & cols) >= 4
        vn_match = len(_VN_SIGNATURE & cols) >= 4
        if not (en_match or vn_match):
            return False
        # Disambiguate from SSI (English) which uses 'Match Volume'/'Match Price'.
        # HSC uses 'Quantity' + 'Matched Price'.
        if en_match and "Match Volume" in cols:
            return False
        return True

    def parse(self, df: pd.DataFrame) -> list:
        records: list[TradeRecord] = []
        cols = set(str(c).strip() for c in df.columns)

        is_en = "Trade Date" in cols
        col_date = "Trade Date" if is_en else "Ngày giao dịch"
        col_sym = "Symbol" if is_en else "Mã chứng khoán"
        col_side = "Side" if is_en else "Loại giao dịch"
        col_qty = "Quantity" if is_en else "Khối lượng khớp"
        col_price = "Matched Price" if is_en else "Giá khớp"
        col_amt = next((c for c in ("Net Amount", "Giá trị") if c in cols), None)
        col_fee = next((c for c in ("Fee", "Phí") if c in cols), None)
        col_tax = next((c for c in ("Tax", "Thuế") if c in cols), None)
        col_name = next((c for c in ("Stock Name", "Tên") if c in cols), None)

        for _, row in df.iterrows():
            try:
                qty = _to_float_vn(row.get(col_qty), 0.0)
                if qty <= 0:
                    continue
                sym = str(row.get(col_sym, "")).strip()
                if not sym or sym.lower() == "nan":
                    continue
                side = _normalize_vn_side(row.get(col_side))
                price = _to_float_vn(row.get(col_price), 0.0)
                amt = _to_float_vn(row.get(col_amt), 0.0) if col_amt else qty * price
                fee = _to_float_vn(row.get(col_fee), 0.0) if col_fee else 0.0
                tax = _to_float_vn(row.get(col_tax), 0.0) if col_tax else 0.0
                records.append(TradeRecord(
                    datetime=_parse_vn_date(row.get(col_date)),
                    symbol=_qualify_vn_symbol(sym),
                    name=str(row.get(col_name, "")).strip() if col_name else "",
                    side=side,
                    quantity=qty,
                    price=price,
                    amount=amt,
                    fee=fee + tax,  # combine per TradeRecord schema
                    market="vn_equity",
                ))
            except (ValueError, KeyError):
                continue

        return records


register_vn_parser(HSCParser())
