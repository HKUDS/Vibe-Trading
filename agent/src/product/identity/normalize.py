"""Canonical symbols, exchange spellings and instrument classification."""
import re
from typing import Any
from src.market_data import canonical_fx_pair

# Project-style canonical symbols. A bare model-generated ticker is still
# checked when it appears under a symbol argument key, but it is not accepted
# as user-provided identity because it lacks venue information.
#
# A joined crypto pair (``BTCUSDT``, ``ETHUSDT`` …) is recognized alongside
# the dashed/slashed form so a user message like ``Get BTCUSDT spot price``
# seeds an asserted identity and the asserted-symbol conflict check at
# ``_ingest_resolution`` runs against it. The base is restricted to alpha
# so a numeric prefix cannot masquerade as a joined pair, and the suffix
# list is the unambiguous stablecoin set (``USDT`` / ``USDC`` / ``BUSD`` /
# ``TUSD``) — ``USD`` is excluded because too many non-crypto strings end
# in those three letters and over-matching would lock the wrong identity.
_JOINED_CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "TUSD")


# A dashed / slashed pair is crypto when its quote leg is unambiguously a
# crypto quote asset, or when a USD quote sits on one of these bases. Both
# sets MUST agree with ``_CRYPTO_QUOTE_ASSETS`` / ``_CRYPTO_USD_BASES`` in
# ``src.tools.symbol_search_tool`` — that module is the resolver, and a venue
# inferred here that disagrees with the identity it locks is a contradictory
# identity, which outranks every later lock and blocks all market tools. The
# tool imports this module, so the sets are duplicated rather than imported;
# ``test_crypto_pair_tables_match_the_resolver`` fails if they drift. ``USD``
# is the one quote the resolver accepts that is NOT unambiguous, so it is
# excluded here and decided by the base whitelist below instead.
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


# Spot precious metals quoted in USD collide with the TUSD suffix: XPTUSD is
# XPT + USD (platinum), but stripping "TUSD" leaves the alpha base "XP" and
# folds it to XP-TUSD — a crypto pair that does not exist, and the same class
# of misresolution the USD exclusion above exists to prevent. XAU/XAG/XPD do
# not collide today; they are listed together because they are the same kind
# of symbol and a future suffix would collide with them the same way.
_METAL_USD_PAIR_RE = re.compile(r"^(?:XAU|XAG|XPT|XPD)USD$", re.IGNORECASE)


_JOINED_CRYPTO_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


_CANONICAL_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"[A-Z0-9]{4}\.T|"
    r"\d{3,6}\.(?:SH|SZ|BJ|SS|HK|KS|KQ)|"
    # Taiwan (TWSE .TW / TPEx .TWO): numeric codes, and an ETF code can end in
    # a letter (00400A.TW). TWO is listed first so 6488.TWO is not read as
    # 6488.TW with a stray "O".
    r"\d{4,6}[A-Z]?\.(?:TWO|TW)|"
    # Futu writes the venue as a PREFIX (HK.00700 / SH.600519 / US.AAPL). The
    # suffix branch above cannot see it, so a user who pasted a connector code
    # got no identity lock at all and every market tool answered
    # identity_required. Handled for the whole prefix set, not just HK: the
    # connector emits all four, and one venue's fix leaves the same hole open
    # in the next.
    r"(?:HK|SH|SZ|BJ|SS)\.\d{3,6}|"
    # Case-SENSITIVE (the connector writes it uppercase): a case-folded
    # match turns any "…/us.reuters/…" host inside a source URL into the
    # symbol REUTERS.US and fails the answer for an unsourced figure.
    r"(?-i:US\.[A-Z][A-Z0-9&-]{0,19})|"
    # Every equity suffix the market-data layer routes (backtest.engines.
    # _market_hooks._MARKET_PATTERNS); test_market_identity_parity keeps the
    # two in step, because .L / .VN / .BA each landed there without landing here.
    r"[A-Z][A-Z0-9&.-]{0,19}\.(?:US|NS|BO|FX|TO|V|BA|SA|L|VN)|"
    r"[A-Z0-9]{2,15}(?:-|/)(?:USDT|USDC|USD|BTC|ETH)|"
    r"[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")|"
    r"\^[A-Z0-9&.\-]{1,20}|"
    r"[A-Z0-9]{2,15}=[FX]"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)



# Provider spellings that denote one instrument. Shanghai is quoted as ``.SH``
# by Eastmoney and ``.SS`` by Yahoo, A-share tools also accept an exchange
# prefix (``sh600519``), Hong Kong codes are zero-padded to five digits, and
# ccxt writes a crypto pair with a slash. Every one of these is a spelling, not
# an identity: ``_infer_venue`` and ``_infer_currency`` below already map ``.SS``
# and ``.SH`` to the same venue and the same currency. Treating them as
# different identities made ``search_symbol("600519")`` return two candidates
# for one listing, which no tie-break could resolve, so every Shanghai listing
# resolved ``ambiguous`` and no market tool could run for the rest of the run.
_EXCHANGE_PREFIXED_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$")


# The dotted form of the same idea, as the Futu connector spells it
# (``HK.00700`` / ``US.AAPL``). ``SS`` is Yahoo's Shanghai alias and folds
# onto ``SH`` exactly as the suffix spelling does.
_VENUE_PREFIXES = frozenset({"HK", "SH", "SZ", "BJ", "SS", "US"})


_US_TICKER_RE = re.compile(r"[A-Z][A-Z0-9&-]{0,19}")


def _normalize_symbol(value: Any) -> str:
    """Normalize a symbol onto one canonical identity for exact comparison.

    Args:
        value: Any provider- or model-supplied symbol spelling.

    Returns:
        The canonical spelling — uppercased, with Shanghai's ``.SS`` alias
        folded onto ``.SH``, an exchange prefix rewritten as a suffix, a Hong
        Kong code zero-padded, and a crypto pair hyphenated. A joined crypto
        pair with no separator (``BTCUSDT``) is rewritten as the dashed form
        (``BTC-USDT``) so every downstream check sees one identity. Text that
        is not a symbol is returned uppercased and otherwise untouched.
    """
    # A fiat/fiat pair is one FX instrument regardless of spelling: ``GBP/USD``
    # and ``GBPUSD`` are both ``GBPUSD=X``. Checked BEFORE the slash is
    # rewritten ("GBP/USD" -> "GBP-USD", the crypto-pair spelling), which
    # disagreed with the resolver's ``GBPUSD=X`` answer — a contradictory
    # identity that outranked every later lock and blocked all further tools.
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
        # No separator at all: rewrite a joined crypto pair (``BTCUSDT``)
        # as the dashed form so the dash/slash branch and the canonical
        # regex both match. The base must be all-alpha so a numeric prefix
        # cannot collide with another numeric-code branch downstream.
        joined = _JOINED_CRYPTO_RE.fullmatch(symbol)
        if joined and not _METAL_USD_PAIR_RE.fullmatch(symbol):
            for quote in _JOINED_CRYPTO_QUOTE_SUFFIXES:
                if symbol.endswith(quote) and len(symbol) > len(quote):
                    base_part = symbol[: -len(quote)]
                    if base_part.isalpha():
                        return f"{base_part}-{quote}"
        return symbol
    # Venue-prefixed listing (Futu connector format: HK.06693 / SH.600519 /
    # SZ.000001 / US.AAPL): rewrite to the canonical suffix spelling so
    # identity matching agrees with the market-data chain (06693.HK) that
    # get_market_data uses. Shanghai's .SS alias is folded onto .SH here too,
    # the same way the suffix branch below does it.
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


def _infer_venue(symbol: str) -> str | None:
    """Infer a coarse venue from a project symbol."""
    upper = _normalize_symbol(symbol)
    suffixes = {
        ".US": "us",
        ".SH": "shanghai",
        ".SZ": "shenzhen",
        ".BJ": "beijing",
        ".HK": "hong_kong",
        ".T": "tokyo",
        ".KS": "kospi",
        ".KQ": "kosdaq",
        ".NS": "nse",
        ".BO": "bse",
        ".FX": "forex",
        ".TO": "toronto",
        ".V": "tsx_venture",
        ".BA": "buenos_aires",
        ".SA": "b3",
        ".L": "lse",
        ".VN": "hose",
        ".TW": "twse",
        ".TWO": "tpex",
    }
    for suffix, venue in suffixes.items():
        if upper.endswith(suffix):
            return venue
    # Yahoo's continuous-front-month futures notation (GC=F, CL=F, SI=F, ...).
    # The exchange category is the venue class. The engine and the
    # correlation helper mirror this pattern; this is the third copy.
    if upper.endswith("=F"):
        return "futures"
    # Yahoo's forex notation (XAUUSD=X, EURUSD=X) is FX.
    if re.match(r"^[A-Z]{6}=X$", upper):
        return "forex"
    # Bare 6-character precious-metal / FX symbols. The whitelist is
    # ISO 4217 metals + G10 currencies; it intentionally does NOT include
    # any US-equity prefix. Mirroring the engine ``_MARKET_PATTERNS``.
    if re.match(
        r"^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$",
        upper,
    ):
        return "forex"
    # Dashed / slashed symbols are NOT categorically crypto: a USD quote is
    # crypto only on a whitelisted base (``_CRYPTO_USD_BASES``), so
    # ``XAU-USD`` / ``EUR-USD`` / ``GBP-USD`` are forex. Without this guard a
    # spot-gold pair surfaced as a crypto-or-fx hybrid in the runtime
    # registry, contradicting the engine classifier that already routes it to
    # ``forex`` (#1280).
    if "-" in upper or "/" in upper:
        base, _, quote = upper.partition("-") if "-" in upper else upper.partition("/")
        if quote in _CRYPTO_QUOTE_ASSETS:
            return "crypto_or_fx"
        if quote == "USD" and base in _CRYPTO_USD_BASES:
            return "crypto_or_fx"
        # Any other dashed / slashed pair is forex-shaped (e.g. ``XAU-USD``,
        # ``EUR-USD``, ``GBP-USD``); the per-pair engine classifier decides
        # ``forex`` vs ``crypto`` vs ``futures`` downstream.
        return "forex"
    return None


def _infer_currency(symbol: str) -> str | None:
    """Infer quote currency without performing an implicit conversion."""
    upper = _normalize_symbol(symbol)
    # HKEX assigns the currency by code range (RMB counters 80000-89999, a few
    # USD ranges), so 80700.HK is a CNY line beside 00700.HK in HKD. One table,
    # shared with the backtest's currency guard.
    from backtest.engines._market_hooks import hk_counter_currency

    hk_currency = hk_counter_currency(upper)
    if hk_currency is not None:
        return hk_currency
    suffixes = {
        ".US": "USD",
        ".SH": "CNY",
        ".SZ": "CNY",
        ".BJ": "CNY",
        ".HK": "HKD",
        ".T": "JPY",
        ".KS": "KRW",
        ".KQ": "KRW",
        ".NS": "INR",
        ".BO": "INR",
        ".TO": "CAD",
        ".V": "CAD",
        ".BA": "ARS",
        ".SA": "BRL",
        # The UK loaders admit only a declared GBP / GBp quote and hand back
        # GBP, the same contract as the backtest's _MARKET_CURRENCY.
        ".L": "GBP",
        ".VN": "VND",
        ".TW": "TWD",
        ".TWO": "TWD",
    }
    for suffix, currency in suffixes.items():
        if upper.endswith(suffix):
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
    # Yahoo's continuous-front-month futures notation (GC=F, CL=F, ...).
    # Mirrors the engine ``_MARKET_PATTERNS`` and the correlation helper.
    if re.match(r"^[A-Z]{2,5}=F$", upper):
        return "future"
    # Yahoo's forex notation (XAUUSD=X, EURUSD=X).
    if re.match(r"^[A-Z]{6}=X$", upper):
        return "forex"
    # Bare 6-character precious-metal / FX symbols (whitelist).
    if re.match(
        r"^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$",
        upper,
    ):
        return "forex"
    # Dashed / slashed symbols: crypto only when the quote leg is a
    # stablecoin OR the base is in the USD-whitelist. The whitelist
    # mirrors ``_canonical_crypto_pair`` in
    # ``src.tools.symbol_search_tool``. ``XAU-USD`` / ``EUR-USD`` /
    # ``GBP-USD`` are NOT crypto and resolve as ``forex`` (the per-pair
    # engine classifier decides the final market downstream).
    if "-" in upper or "/" in upper:
        base, _, quote = upper.partition("-") if "-" in upper else upper.partition("/")
        if quote in _CRYPTO_QUOTE_ASSETS:
            return "crypto"
        if quote == "USD" and base in _CRYPTO_USD_BASES:
            return "crypto"
        return "forex"
    if upper.startswith("^"):
        return "index"
    return "listed_security"
