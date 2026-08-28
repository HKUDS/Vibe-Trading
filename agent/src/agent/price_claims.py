"""Deterministic extraction of explicit observed-price claims.

The grounding gate must not treat every number in a market-related sentence as
a price.  This module therefore recognizes only positive syntax: a supported
observed-price field directly bound to one numeric value, or a numeric cell in
a table column that already declares such a field.  Dates, counts, index names,
security codes, formulas, targets and indicator readings require no exclusion
rules because none of them satisfy that contract.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MARK = r"[*_`]{0,3}"
_CURRENCY = (
    r"US\$|HK\$|C\$|A\$|S\$|\$|¥|￥|USD|CNY|CNH|RMB|HKD|CAD|AUD|SGD|"
    r"美元|美金|人民币|港元|港币|加元|澳元|新加坡元|元"
)
_POINT_UNIT = r"点|points?"

# Each branch names the canonical evidence field it represents.  Labels for
# plans (target/entry/support/resistance) are intentionally absent: those are
# proposed levels, not observations.
_PRICE_CLAIM_RE = re.compile(
    rf"(?:"
    rf"(?P<close>closing\s+price|close\s+price|closed\s+at|close|收盘价|收报|收于)"
    rf"|(?P<open>opening\s+price|open\s+price|opened\s+at|open|开盘价)"
    rf"|(?P<high>session\s+high|daily\s+high|high\s+price|high|最高价|最高)"
    rf"|(?P<low>session\s+low|daily\s+low|low\s+price|low|最低价|最低)"
    rf"|(?P<price>current\s+price|latest\s+price|last\s+price|market\s+price|quote|现价|最新价|报价)"
    rf")"
    rf"{_MARK}\s*(?:(?:约为|大约为|约|大约|around|about|为|是|报|在|at|was|is|of)\s*)?[:：=]?\s*{_MARK}"
    rf"(?P<currency_before>{_CURRENCY})?\s*{_MARK}"
    rf"(?P<value>{_NUMBER}){_MARK}\s*"
    rf"(?P<currency_after>{_CURRENCY})?\s*(?P<unit>{_POINT_UNIT})?"
    rf"(?=$|[\s,，;；。.!！?？)）\]】])",
    re.IGNORECASE,
)
_DATED_OHLC_RE = re.compile(
    rf"(?P<date>(?:(?:19|20)\d{{2}}\s*[-/]\s*)?"
    rf"(?:0?[1-9]|1[0-2])\s*[-/]\s*(?:0?[1-9]|[12]\d|3[01]))"
    rf"(?:\s*\([^)]{{1,4}}\))?\s*(?:盘中|当日|日内)?\s*"
    rf"(?P<label>开盘|开|最高|高|最低|低|收盘|收)\s*[:：=]?\s*{_MARK}"
    rf"(?P<currency_before>{_CURRENCY})?\s*{_MARK}"
    rf"(?P<value>{_NUMBER}){_MARK}\s*"
    rf"(?P<currency_after>{_CURRENCY})?\s*(?P<unit>{_POINT_UNIT})?"
    rf"(?=$|[\s,，;；。.!！?？)）\]】])",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(?<!\d)(?:(?:19|20)\d{2}\s*[-/]\s*)?"
    r"(?:0?[1-9]|1[0-2])\s*[-/]\s*(?:0?[1-9]|[12]\d|3[01])(?!\d)"
)
_CELL_RE = re.compile(
    rf"^\s*{_MARK}(?P<currency_before>{_CURRENCY})?\s*{_MARK}"
    rf"(?P<value>{_NUMBER}){_MARK}\s*"
    rf"(?P<currency_after>{_CURRENCY})?\s*(?P<unit>{_POINT_UNIT})?{_MARK}\s*$",
    re.IGNORECASE,
)

_CURRENCY_CODES = {
    "US$": "USD",
    "$": "USD",
    "USD": "USD",
    "美元": "USD",
    "美金": "USD",
    "CNY": "CNY",
    "CNH": "CNY",
    "RMB": "CNY",
    "¥": "CNY",
    "￥": "CNY",
    "人民币": "CNY",
    "元": "CNY",
    "HK$": "HKD",
    "HKD": "HKD",
    "港元": "HKD",
    "港币": "HKD",
    "C$": "CAD",
    "CAD": "CAD",
    "加元": "CAD",
    "A$": "AUD",
    "AUD": "AUD",
    "澳元": "AUD",
    "S$": "SGD",
    "SGD": "SGD",
    "新加坡元": "SGD",
}


@dataclass(frozen=True)
class NumericClaim:
    """One explicit observed-price assertion extracted from final prose."""

    value: float
    field: str
    text: str
    date: str | None = None
    currency: str | None = None
    unit: str | None = None
    temporal_scope: str = "latest"
    start: int = 0
    end: int = 0


def _finite_number(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _currency_code(raw: str | None) -> str | None:
    if not raw:
        return None
    return _CURRENCY_CODES.get(raw.upper(), _CURRENCY_CODES.get(raw))


def _field(match: re.Match[str]) -> str:
    for name in ("open", "high", "low", "close", "price"):
        if match.group(name) is not None:
            return name
    raise ValueError("price claim regex matched without a field")


def _nearby_date(prefix: str) -> str | None:
    matches = list(_DATE_RE.finditer(prefix))
    if not matches:
        return None
    match = matches[-1]
    if len(prefix) - match.end() > 24:
        return None
    return match.group(0).replace(" ", "")


def extract_prose_price_claims(content: str) -> list[NumericClaim]:
    """Extract only field-bound observed prices from non-table prose.

    Args:
        content: Candidate assistant answer.

    Returns:
        Claims in document order. Markdown table rows are left to the table
        parser, whose header already provides the field binding.
    """
    claims: list[NumericClaim] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if "|" not in body:
            line_claims: list[NumericClaim] = []
            for match in _PRICE_CLAIM_RE.finditer(body):
                value = _finite_number(match.group("value"))
                if value is None:
                    continue
                currency = _currency_code(
                    match.group("currency_before") or match.group("currency_after")
                )
                unit = "points" if match.group("unit") else None
                line_claims.append(
                    NumericClaim(
                        value=value,
                        field=_field(match),
                        text=body.strip(),
                        date=_nearby_date(body[: match.start()]),
                        currency=currency,
                        unit=unit,
                        start=offset + match.start(),
                        end=offset + match.end(),
                    )
                )
            dated_fields = {
                "开盘": "open",
                "开": "open",
                "最高": "high",
                "高": "high",
                "最低": "low",
                "低": "low",
                "收盘": "close",
                "收": "close",
            }
            for match in _DATED_OHLC_RE.finditer(body):
                value = _finite_number(match.group("value"))
                if value is None:
                    continue
                line_claims.append(
                    NumericClaim(
                        value=value,
                        field=dated_fields[match.group("label")],
                        text=body.strip(),
                        date=match.group("date").replace(" ", ""),
                        currency=_currency_code(
                            match.group("currency_before")
                            or match.group("currency_after")
                        ),
                        unit="points" if match.group("unit") else None,
                        temporal_scope="dated",
                        start=offset + match.start(),
                        end=offset + match.end(),
                    )
                )
            deduped: list[NumericClaim] = []
            for claim in sorted(line_claims, key=lambda item: (item.start, item.end)):
                overlap = next(
                    (
                        index
                        for index, existing in enumerate(deduped)
                        if existing.field == claim.field
                        and existing.value == claim.value
                        and claim.start < existing.end
                        and existing.start < claim.end
                    ),
                    None,
                )
                if overlap is None:
                    deduped.append(claim)
                elif claim.date and not deduped[overlap].date:
                    deduped[overlap] = claim
            claims.extend(deduped)
        offset += len(line)
    return claims


def parse_numeric_cell(value: str) -> tuple[float, str | None, str | None] | None:
    """Parse one table cell whose header already identifies a price field."""
    match = _CELL_RE.match(value or "")
    if match is None:
        return None
    number = _finite_number(match.group("value"))
    if number is None:
        return None
    currency = _currency_code(
        match.group("currency_before") or match.group("currency_after")
    )
    unit = "points" if match.group("unit") else None
    return (number, currency, unit)


__all__ = ["NumericClaim", "extract_prose_price_claims", "parse_numeric_cell"]
