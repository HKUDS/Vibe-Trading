"""Pure MT5 symbol normalization + mandate classification (no SDK import).

Broker symbol resolution (suffix discovery against a live terminal) lives in
``_client``; this module is the terminal-free half the order gate uses, so it
must stay importable and correct on any platform.
"""

from __future__ import annotations

from src.live.mandate.model import AssetClass, InstrumentType

#: ISO-4217 codes accepted as halves of a spot forex pair. Deliberately
#: EXCLUDES metals (XAU/XAG/XPT/XPD): metal symbols classify as CFD so the
#: mandate admits them only via an explicit ``"cfd"`` instrument allowance.
_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "AUD",
        "NZD",
        "CAD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "TRY",
        "ZAR",
        "MXN",
        "SGD",
        "HKD",
        "CNH",
        "CNY",
        "THB",
        "ILS",
        "RON",
        "INR",
        "IDR",
        "KRW",
        "BRL",
        "CLP",
        "COP",
        "AED",
        "SAR",
    }
)

#: Longest broker account-type suffix still treated as a suffix ("m", "z",
#: "c", "raw", ".r", "micro" is NOT — 5 chars means a different instrument).
_MAX_SUFFIX_LEN = 4


def normalize_base(symbol: str) -> str:
    """Collapse ``EUR/USD`` / ``eur-usd`` / ``EURUSD.FX`` to ``EURUSD``.

    Uppercases and strips separators plus the project's ``.FX`` market tag.
    Broker suffixes are preserved (``EURUSDm`` → ``EURUSDM``); stripping them
    is :func:`split_suffix`'s job.
    """
    token = symbol.strip().upper()
    if token.endswith(".FX"):
        token = token[: -len(".FX")]
    for separator in ("/", "-", "_", " "):
        token = token.replace(separator, "")
    return token


def split_suffix(token: str) -> tuple[str, str]:
    """Split a broker account-type suffix off a normalized token.

    ``EURUSDM`` → ``("EURUSD", "M")`` when the first six characters form a
    currency pair and the remainder is short enough to be a suffix; anything
    else returns ``(token, "")`` unchanged.
    """
    if len(token) <= 6 or len(token) > 6 + _MAX_SUFFIX_LEN:
        return token, ""
    base, tail = token[:6], token[6:]
    if base[:3] in _CURRENCIES and base[3:] in _CURRENCIES:
        return base, tail
    return token, ""


def is_forex_pair(token: str) -> bool:
    """True when ``token`` (optionally broker-suffixed) is a currency pair."""
    base, _ = split_suffix(token)
    return len(base) == 6 and base[:3] in _CURRENCIES and base[3:] in _CURRENCIES


def classify_mt5_symbol(symbol: str) -> tuple[InstrumentType, AssetClass | None]:
    """Map an MT5 symbol to its mandate ``(InstrumentType, AssetClass)``.

    Currency pairs (including Exness-style suffixed forms) classify as
    ``(FOREX, FOREX)``. Everything else — metals, index/energy/crypto CFDs,
    stock CFDs, unrecognized strings — classifies as ``(CFD, None)``:
    fail-safe, because CFD has no asset-class bucket and is admitted only when
    the mandate explicitly lists ``"cfd"`` in ``allowed_instruments``.
    """
    if is_forex_pair(normalize_base(symbol)):
        return InstrumentType.FOREX, AssetClass.FOREX
    return InstrumentType.CFD, None
