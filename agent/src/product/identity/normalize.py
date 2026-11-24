"""Canonical symbols, exchange spellings and instrument classification."""
import re
from typing import Any
from src.market_data import canonical_fx_pair

# Bare tickers and ambiguous USD suffixes cannot seed a user identity.
_JOINED_CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "TUSD")


# Resolver parity is enforced by test_crypto_pair_tables_match_the_resolver.
_CRYPTO_QUOTE_ASSETS = frozenset({"USDT", "USDC", "BUSD", "TUSD", "FDUSD", "BTC", "ETH", "BNB"})


_CRYPTO_USD_BASES = frozenset(
    {
        "BTC",
        "ETH",
        "BNB",
        "SOL",
        "ADA",
        "XRP",
        "DOGE",
        "TRX",
        "DOT",
        "MATIC",
        "AVAX",
        "LINK",
        "LTC",
        "BCH",
        "ETC",
        "XLM",
        "ATOM",
        "FIL",
        "APT",
        "NEAR",
        "ALGO",
        "SAND",
        "MANA",
        "AXS",
        "XAUT",
        "PAXG",
    }
)


# Prevent platinum quoted in USD from matching the TUSD suffix.
_METAL_USD_PAIR_RE = re.compile(r"^(?:XAU|XAG|XPT|XPD)USD$", re.IGNORECASE)


_JOINED_CRYPTO_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


_CANONICAL_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"[A-Z0-9]{4}\.T|"
    r"\d{3,6}\.(?:SH|SZ|BJ|SS|HK|KS|KQ)|"
    # Try TWO first to preserve the complete TPEx suffix.
    r"\d{4,6}[A-Z]?\.(?:TWO|TW)|"
    # Accept the connector’s venue-prefixed listing spellings.
    r"(?:HK|SH|SZ|BJ|SS)\.\d{3,6}|"
    # Keep US prefixes case-sensitive so URLs such as us.reuters never seed a symbol.
    r"(?-i:US\.[A-Z][A-Z0-9&-]{0,19})|"
    # Keep routed suffixes in sync with test_market_identity_parity.
    r"[A-Z][A-Z0-9&.-]{0,19}\.(?:US|NS|BO|FX|TO|V|BA|SA|L|VN)|"
    r"[A-Z0-9]{2,15}(?:-|/)(?:USDT|USDC|USD|BTC|ETH)|"
    r"[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")|"
    r"\^[A-Z0-9&.\-]{1,20}|"
    r"[A-Z0-9]{2,15}=[FX]"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)



# Canonicalize provider aliases before comparing instrument identities.
_EXCHANGE_PREFIXED_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$")


_VENUE_PREFIXES = frozenset({"HK", "SH", "SZ", "BJ", "SS", "US"})


_US_TICKER_RE = re.compile(r"[A-Z][A-Z0-9&-]{0,19}")


def _normalize_symbol(value: Any) -> str:
    """Normalize a symbol onto one canonical identity for exact comparison."""
    # Recognize fiat pairs before rewriting slash-separated crypto symbols.
    raw = str(value or "").strip().upper()
    fx = canonical_fx_pair(raw)
    if fx is not None:
        return fx
    symbol = raw.replace("/", "-")
    if not symbol:
        return ""

    prefixed = _EXCHANGE_PREFIXED_RE.match(symbol)
    if prefixed:
        return f"{prefixed.group(2)}.{prefixed.group(1)}"
    base, dot, suffix = symbol.rpartition(".")
    if not dot:
        joined = _JOINED_CRYPTO_RE.fullmatch(symbol)
        if joined and not _METAL_USD_PAIR_RE.fullmatch(symbol):
            for quote in _JOINED_CRYPTO_QUOTE_SUFFIXES:
                if symbol.endswith(quote) and len(symbol) > len(quote):
                    base_part = symbol[: -len(quote)]
                    if base_part.isalpha():
                        return f"{base_part}-{quote}"
        return symbol
    if base in _VENUE_PREFIXES and suffix:
        venue = "SH" if base == "SS" else base
        if venue == "US":
            if _US_TICKER_RE.fullmatch(suffix):
                return f"{suffix}.US"
        elif suffix.isdigit():
            digits = suffix.zfill(5) if venue == "HK" else suffix
            return f"{digits}.{venue}"
    if suffix == "SS":
        suffix = "SH"
    if suffix == "HK" and base.isdigit():
        base = base.zfill(5)
    return f"{base}.{suffix}"


def _query_key(value: Any) -> str:
    """Normalize resolver queries into stable state-machine keys."""
    return " ".join(str(value or "").casefold().split())


def _scan_symbols(text: str) -> set[str]:
    """Return the canonical symbols written anywhere in a blob of text."""
    return {_normalize_symbol(match.group(0)) for match in _CANONICAL_SYMBOL_RE.finditer(text or "")}


# The HKEX counter-specific currency lookup takes precedence over this table.
_LISTING_MARKETS = {
    ".US": ("us", "USD"),
    ".SH": ("shanghai", "CNY"),
    ".SZ": ("shenzhen", "CNY"),
    ".BJ": ("beijing", "CNY"),
    ".HK": ("hong_kong", "HKD"),
    ".T": ("tokyo", "JPY"),
    ".KS": ("kospi", "KRW"),
    ".KQ": ("kosdaq", "KRW"),
    ".NS": ("nse", "INR"),
    ".BO": ("bse", "INR"),
    ".FX": ("forex", None),
    ".TO": ("toronto", "CAD"),
    ".V": ("tsx_venture", "CAD"),
    ".BA": ("buenos_aires", "ARS"),
    ".SA": ("b3", "BRL"),
    ".L": ("lse", "GBP"),
    ".VN": ("hose", "VND"),
    ".TW": ("twse", "TWD"),
    ".TWO": ("tpex", "TWD"),
}
_BARE_FX_RE = re.compile(r"^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$")
_YAHOO_FX_RE = re.compile(r"^[A-Z]{6}=X$")


def _pair_type(symbol: str) -> str | None:
    if _BARE_FX_RE.match(symbol) or _YAHOO_FX_RE.match(symbol):
        return "forex"
    separator = "-" if "-" in symbol else "/"
    base, separator, quote = symbol.partition(separator)
    if not separator:
        return None
    if quote in _CRYPTO_QUOTE_ASSETS or (quote == "USD" and base in _CRYPTO_USD_BASES):
        return "crypto"
    return "forex"


def _infer_venue(symbol: str) -> str | None:
    """Infer a coarse venue from a project symbol."""
    upper = _normalize_symbol(symbol)
    for suffix, (venue, _) in _LISTING_MARKETS.items():
        if upper.endswith(suffix):
            return venue
    if upper.endswith("=F"):
        return "futures"
    pair = _pair_type(upper)
    return "crypto_or_fx" if pair == "crypto" else pair


def _infer_currency(symbol: str) -> str | None:
    """Infer quote currency without performing an implicit conversion."""
    upper = _normalize_symbol(symbol)
    # HKEX currency depends on the counter code, including the RMB and USD ranges.
    from backtest.engines._market_hooks import hk_counter_currency

    hk_currency = hk_counter_currency(upper)
    if hk_currency is not None:
        return hk_currency
    for suffix, (_, currency) in _LISTING_MARKETS.items():
        if currency is not None and upper.endswith(suffix):
            return currency
    for separator in ("-", "/"):
        if separator in upper:
            quote = upper.rsplit(separator, 1)[-1]
            if 3 <= len(quote) <= 5:
                return quote
    if upper.endswith("=X"):
        pair = upper[:-2]
        if len(pair) == 6:
            return pair[3:6]
    return None


def _infer_instrument_type(symbol: str, candidate_type: Any = None) -> str:
    """Normalize provider types into the identity contract."""
    raw = str(candidate_type or "").strip().casefold()
    if raw == "cfd":
        return "cfd"
    if "fund" in raw or "etf" in raw or "trust" in raw:
        return "fund"
    if "crypto" in raw:
        return "crypto"
    if "future" in raw:
        return "future"
    if "option" in raw:
        return "option"
    if "forex" in raw or raw == "currency":
        return "forex"
    if "index" in raw:
        return "index"
    upper = _normalize_symbol(symbol)
    if upper.endswith("=F"):
        return "future"
    if upper.endswith(".FX"):
        return "forex"
    pair = _pair_type(upper)
    if pair is not None:
        return pair
    if upper.startswith("^"):
        return "index"
    return "listed_security"
