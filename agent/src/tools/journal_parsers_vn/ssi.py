"""SSI Securities (iBoard) broker journal parser.

Detects Vietnamese (Ngày GD/Mã CK/Loại GD) and English (Trade Date/Symbol/Side)
SSI iBoard exports. Both CSV and XLSX accepted via parent loader.

Typical schema:
  Ngày GD | Mã CK | Loại GD | KL khớp | Giá khớp | Giá trị | Phí GD | Thuế
  EN:     | Trade Date | Symbol | Side | Match Volume | Match Price | Value | Fee | Tax
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


_VN_REQUIRED = {"Ngày GD", "Mã CK", "Loại GD"}
_EN_REQUIRED = {"Trade Date", "Symbol", "Side"}
_VN_QTY_HINT = {"KL khớp", "Match Volume", "Khối lượng khớp"}
_VN_PRICE_HINT = {"Giá khớp", "Match Price"}


class SSIParser:
    name = "ssi"

    def detect(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return False
        cols = set(str(c).strip() for c in df.columns)
        # Need >=3 of the required + at least one qty hint
        vn_match = len(_VN_REQUIRED & cols) >= 3 and bool(_VN_QTY_HINT & cols)
        en_match = len(_EN_REQUIRED & cols) >= 3 and bool({"Match Volume", "Quantity"} & cols)
        return vn_match or en_match

    def parse(self, df: pd.DataFrame) -> list:
        records: list[TradeRecord] = []
        cols = set(str(c).strip() for c in df.columns)

        # Pick correct column names based on language
        is_vn = "Ngày GD" in cols
        col_date = "Ngày GD" if is_vn else "Trade Date"
        col_symbol = "Mã CK" if is_vn else "Symbol"
        col_side = "Loại GD" if is_vn else "Side"
        col_qty = next((c for c in ("KL khớp", "Match Volume", "Khối lượng khớp", "Quantity") if c in cols), None)
        col_price = next((c for c in ("Giá khớp", "Match Price") if c in cols), None)
        col_amount = next((c for c in ("Giá trị", "Value") if c in cols), None)
        col_fee = next((c for c in ("Phí GD", "Fee") if c in cols), None)
        col_tax = next((c for c in ("Thuế", "Tax") if c in cols), None)
        col_name = next((c for c in ("Tên", "Name") if c in cols), None)

        if not col_qty or not col_price:
            return records

        for _, row in df.iterrows():
            try:
                qty = _to_float_vn(row.get(col_qty), 0.0)
                if qty <= 0:
                    continue
                symbol_raw = str(row.get(col_symbol, "")).strip()
                if not symbol_raw or symbol_raw.lower() == "nan":
                    continue
                side = _normalize_vn_side(row.get(col_side))
                price = _to_float_vn(row.get(col_price), 0.0)
                amount = _to_float_vn(row.get(col_amount), 0.0) if col_amount else qty * price
                fee = _to_float_vn(row.get(col_fee), 0.0) if col_fee else 0.0
                tax = _to_float_vn(row.get(col_tax), 0.0) if col_tax else 0.0
                records.append(TradeRecord(
                    datetime=_parse_vn_date(row.get(col_date)),
                    symbol=_qualify_vn_symbol(symbol_raw),
                    name=str(row.get(col_name, "")).strip() if col_name else "",
                    side=side,
                    quantity=qty,
                    price=price,
                    amount=amount,
                    fee=fee + tax,  # combine per TradeRecord schema
                    market="vn_equity",
                ))
            except (ValueError, KeyError):
                continue

        return records


register_vn_parser(SSIParser())
