"""Shared helpers for VN broker journal parsers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Known HNX-listed tickers (incomplete; default fallback is HOSE)
_KNOWN_HNX_TICKERS = {
    "SHB", "PVS", "VND", "CEO", "MBS", "VCS", "VC3", "DGC",  # sample
}

_KNOWN_UPCOM_TICKERS = {
    "VEA", "BSR", "ACV", "VGT", "QNS", "MCH",  # sample
}

_BUY_TOKENS = frozenset({
    "buy", "b", "mua", "MUA", "Mua", "buy/long", "long", "B",
})
_SELL_TOKENS = frozenset({
    "sell", "s", "ban", "bán", "BÁN", "Bán", "sell/short", "short", "S",
})


def _qualify_vn_symbol(code: str, exchange_hint: str | None = None) -> str:
    """Map bare VN ticker to qualified form: VNM → VNM.HOSE, SHB → SHB.HNX, etc.

    If `code` already has a `.HOSE/.HNX/.UPCOM` suffix, return as-is (uppercased).
    If `exchange_hint` is provided (e.g. "HOSE"/"HNX"/"UPCOM") use that; otherwise
    consult known-ticker tables, defaulting to HOSE.
    """
    if not code:
        return code
    s = str(code).strip().upper()
    if s.endswith((".HOSE", ".HNX", ".UPCOM")):
        return s
    if exchange_hint:
        return f"{s}.{exchange_hint.upper()}"
    if s in _KNOWN_HNX_TICKERS:
        return f"{s}.HNX"
    if s in _KNOWN_UPCOM_TICKERS:
        return f"{s}.UPCOM"
    return f"{s}.HOSE"


def _normalize_vn_side(raw: Any) -> str:
    """Return 'buy' or 'sell'; raise ValueError on unknown."""
    if raw is None:
        raise ValueError("Empty side")
    s = str(raw).strip()
    if not s:
        raise ValueError("Empty side")
    # Direct match
    if s in _BUY_TOKENS:
        return "buy"
    if s in _SELL_TOKENS:
        return "sell"
    # Lowercase compare
    s_lower = s.lower()
    if s_lower in _BUY_TOKENS or s_lower in {"buy", "b", "mua", "long"}:
        return "buy"
    if s_lower in _SELL_TOKENS or s_lower in {"sell", "s", "ban", "bán", "short"}:
        return "sell"
    raise ValueError(f"Unknown side token: {raw!r}")


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y%m%d",
)


def _parse_vn_date(raw: Any) -> str:
    """Return ISO8601 string ('YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD')."""
    if raw is None:
        raise ValueError("Empty date")
    s = str(raw).strip()
    if not s:
        raise ValueError("Empty date")
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if "%H" in fmt:
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Last resort: pandas to_datetime
    try:
        import pandas as pd
        ts = pd.to_datetime(s, dayfirst=True, errors="raise")
        if ts.hour or ts.minute or ts.second:
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        return ts.strftime("%Y-%m-%d")
    except Exception:
        raise ValueError(f"Unparseable date: {raw!r}")


_VN_NUMBER_RE = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")  # 1.234.567,89
_US_NUMBER_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")  # 1,234,567.89


def _to_float_vn(val: Any, default: float = 0.0) -> float:
    """Parse numeric value; tolerate VN format (1.234,5), US format (1,234.5), bare numbers."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return default
    # Strip any trailing currency symbols
    s = s.replace("VND", "").replace("đ", "").strip()
    try:
        if _VN_NUMBER_RE.match(s):
            # Replace dots (thousands sep) with empty, comma with dot
            return float(s.replace(".", "").replace(",", "."))
        if _US_NUMBER_RE.match(s):
            return float(s.replace(",", ""))
        # Bare number maybe with dot or comma
        # If contains both, ambiguous — fall through
        if "," in s and "." not in s:
            # Could be VN decimal: "1234,5" → 1234.5
            return float(s.replace(",", "."))
        return float(s)
    except ValueError:
        return default


__all__ = [
    "_qualify_vn_symbol",
    "_normalize_vn_side",
    "_parse_vn_date",
    "_to_float_vn",
]
