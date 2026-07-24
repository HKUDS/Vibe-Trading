"""Fail-closed Taiwan symbol parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass


class SymbolParseError(ValueError):
    """Raised when a Taiwan symbol is empty, invalid, or ambiguous."""


_SYMBOL_RE = re.compile(r"^(?P<local>\d{4,6})(?:\.(?P<suffix>[A-Za-z]+))?$")
_MARKET_ALIASES = {
    "TW": "TWSE",
    "TWSE": "TWSE",
    "TWO": "TPEX",
    "TPEX": "TPEX",
}


@dataclass(frozen=True)
class CanonicalSymbol:
    """Canonical Taiwan instrument identity used by Phase 01."""

    local_code: str
    market: str
    canonical: str
    vendor_symbols: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_to: str | None = None


def _market_hint(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    if normalized in {"TAIWAN", "TAIWAN_EQUITY"}:
        return None
    return _MARKET_ALIASES.get(normalized)


def parse_symbol(symbol: str, market_hint: str | None = None) -> CanonicalSymbol:
    """Parse ``2330.TW``/``6488.TWO`` without guessing ambiguous codes.

    Bare numeric codes are accepted only with an explicit ``TWSE``/``TPEX``
    hint. Provider-specific vendor mappings are deliberately not inferred.
    """
    raw = str(symbol).strip()
    if not raw:
        raise SymbolParseError("Taiwan symbol must not be empty")
    match = _SYMBOL_RE.fullmatch(raw)
    if not match:
        raise SymbolParseError(f"invalid Taiwan symbol: {symbol!r}")

    local_code = match.group("local")
    suffix = match.group("suffix")
    hinted_market = _market_hint(market_hint)
    if suffix:
        market = _MARKET_ALIASES.get(suffix.upper())
        if market is None:
            raise SymbolParseError(f"unknown Taiwan market suffix: {suffix!r}")
        if hinted_market is not None and hinted_market != market:
            raise SymbolParseError(
                f"symbol suffix {suffix!r} conflicts with market hint {market_hint!r}"
            )
    else:
        if hinted_market is None:
            raise SymbolParseError(
                f"bare Taiwan code {raw!r} is ambiguous; provide TWSE/TPEX hint"
            )
        market = hinted_market

    canonical_suffix = "TW" if market == "TWSE" else "TWO"
    return CanonicalSymbol(
        local_code=local_code,
        market=market,
        canonical=f"{local_code}.{canonical_suffix}",
    )


def is_taiwan_symbol(symbol: str, market_hint: str | None = None) -> bool:
    """Return whether *symbol* is a valid, unambiguous Taiwan symbol."""
    try:
        parsed = parse_symbol(symbol, market_hint=market_hint)
    except SymbolParseError:
        return False
    return parsed.market in {"TWSE", "TPEX"}

