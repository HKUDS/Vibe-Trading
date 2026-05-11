"""TCBS (Techcom Securities) broker journal parser.

Distinguishing column signature: full Vietnamese 'Ngày giao dịch' (vs SSI's
short 'Ngày GD'), 'Khối lượng' without 'khớp' modifier (vs SSI's 'KL khớp'),
and 'Giá trị giao dịch' (full form, vs SSI's 'Giá trị').

Typical schema:
  Ngày giao dịch | Mã CK | Tên | Loại GD | Khối lượng | Giá khớp
                | Giá trị giao dịch | Phí | Thuế
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

_REQUIRED = {"Ngày giao dịch", "Mã CK", "Loại GD", "Khối lượng", "Giá khớp"}


class TCBSParser:
    name = "tcbs"

    def detect(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return False
        cols = set(str(c).strip() for c in df.columns)
        if len(_REQUIRED & cols) < 4:
            return False
        # Disambiguate from SSI (which uses 'Ngày GD' short form and 'KL khớp')
        if "Ngày GD" in cols or "KL khớp" in cols:
            return False
        # Disambiguate from VNDirect (which uses 'Loại lệnh' instead of 'Loại GD')
        if "Loại lệnh" in cols:
            return False
        return True

    def parse(self, df: pd.DataFrame) -> list:
        records: list = []
        cols = set(str(c).strip() for c in df.columns)
        col_amt = (
            "Giá trị giao dịch" if "Giá trị giao dịch" in cols
            else ("Giá trị" if "Giá trị" in cols else None)
        )
        col_fee = "Phí" if "Phí" in cols else None
        col_tax = "Thuế" if "Thuế" in cols else None
        col_name = "Tên" if "Tên" in cols else None
        for _, row in df.iterrows():
            try:
                qty = _to_float_vn(row.get("Khối lượng"), 0.0)
                if qty <= 0:
                    continue
                sym = str(row.get("Mã CK", "")).strip()
                if not sym:
                    continue
                side = _normalize_vn_side(row.get("Loại GD"))
                price = _to_float_vn(row.get("Giá khớp"), 0.0)
                amt = _to_float_vn(row.get(col_amt), 0.0) if col_amt else qty * price
                fee = _to_float_vn(row.get(col_fee), 0.0) if col_fee else 0.0
                tax = _to_float_vn(row.get(col_tax), 0.0) if col_tax else 0.0
                records.append(TradeRecord(
                    datetime=_parse_vn_date(row.get("Ngày giao dịch")),
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


register_vn_parser(TCBSParser())
