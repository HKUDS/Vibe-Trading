"""Extracted per-bar market hooks and symbol-classification helpers.

Both the original engines (CryptoEngine, ForexEngine) and CompositeEngine
call these same functions. Zero duplication — one source of truth.

Also hosts symbol -> market detection helpers shared by ``runner.py`` and
``composite.py``: ``_MARKET_PATTERNS``, ``_detect_market``,
``_is_china_futures``, ``_detect_submarket``. Keep regex tables here so the
truncated-duplicate routing bug (bare ``RB2410`` getting routed to
GlobalFutures because composite.py used a suffix-only check) cannot recur.
"""

from __future__ import annotations

import re
from typing import Dict, List

import pandas as pd

from backtest.models import Position


# ── Symbol -> market classification (shared by runner.py + composite.py) ──

_MARKET_PATTERNS = [
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "a_share"),
    (re.compile(r"^(51|15|56)\d{4}\.(SZ|SH)$", re.I), "a_share"),
    (re.compile(r"^[A-Z]+\.US$", re.I), "us_equity"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "hk_equity"),
    # India equities: NSE (RELIANCE.NS) / BSE (500325.BO); tickers may carry
    # '&' and '-' (e.g. M&M.NS, BAJAJ-AUTO.NS).
    (re.compile(r"^[A-Z0-9&.\-]+\.(NS|BO)$", re.I), "india_equity"),
    # Korea equities: KOSPI (005930.KS) / KOSDAQ (247540.KQ), 6-digit codes.
    (re.compile(r"^\d{6}\.(KS|KQ)$", re.I), "kr_equity"),
    # Canada equities: Toronto Stock Exchange (TD.TO) and TSX Venture
    # (PNG.V). Yahoo carries both suffixes verbatim.
    (re.compile(r"^[A-Z0-9&.\-]+\.(TO|V)$", re.I), "ca_equity"),
    # Vietnam equities: HOSE (VIC.VN). Tickers are three letters in practice;
    # the class stays broad to admit fund certificates and ETF codes.
    (re.compile(r"^[A-Z0-9]+\.VN$", re.I), "vietnam_equity"),
    (re.compile(r"^[A-Z]+-USDT$", re.I), "crypto"),
    (re.compile(r"^[A-Z]+/USDT$", re.I), "crypto"),
    # yfinance's native crypto spelling (BTC-USD, ETH-USD). Distinct from
    # USDT pairs only in the quote currency; both belong to CryptoEngine.
    (re.compile(r"^[A-Z]+-USD$", re.I), "crypto"),
    # China futures: product+delivery.exchange (e.g. IF2406.CFFEX, rb2410.SHFE)
    (re.compile(r"^[A-Za-z]{1,2}\d{3,4}\.(ZCE|DCE|SHFE|INE|CFFEX|GFEX)$", re.I), "futures"),
    # Global futures: product+month-code (e.g. ESZ4, CLF25, GCM2025)
    (re.compile(r"^[A-Z]{2,4}[FGHJKMNQUVXZ]\d{1,2}$", re.I), "futures"),
    # Global futures: product+YYMM (e.g. CL2412, ES2503)
    (re.compile(r"^[A-Z]{2,4}\d{4}$", re.I), "futures"),
    # Global futures: bare product code with exchange (e.g. ES.CME)
    (re.compile(r"^[A-Z]{2,4}\.(CME|CBOT|NYMEX|COMEX|ICE|EUREX)$", re.I), "futures"),
    # Forex pairs: XXX/YYY or XXXXXX.FX
    (re.compile(r"^[A-Z]{3}/[A-Z]{3}$"), "forex"),
    (re.compile(r"^[A-Z]{6}\.FX$"), "forex"),
    # Bare US tickers (AAPL, MSFT, SPY, T, ...). Must stay LAST so every
    # suffixed equity / futures / crypto / forex form above wins first.
    # ``{1,5}`` covers every standard US ticker length while 6-char bare
    # forex (EURUSD) and longer crypto codes (BTCUSDT) fall through to the
    # a_share default.
    (re.compile(r"^[A-Z]{1,5}$", re.I), "us_equity"),
]

_CHINA_EXCHANGES = {"CFFEX", "SHFE", "DCE", "ZCE", "INE", "GFEX"}

# Settlement currency per market. A composite backtest holds one shared capital
# pool, so a code set spanning two of these would add CNY to USD to KRW as if
# they were the same unit.
_MARKET_CURRENCY = {
    "a_share": "CNY",
    "us_equity": "USD",
    "hk_equity": "HKD",
    "india_equity": "INR",
    "kr_equity": "KRW",
    "ca_equity": "CAD",
    "vietnam_equity": "VND",
    # Every crypto pattern in _MARKET_PATTERNS is USDT-quoted, and USDT is
    # carried at its USD peg. This is the one approximation in the table: a
    # depeg would make a crypto+US book wrong by the depeg amount, which is
    # orders of magnitude below the CNY/USD-style unit error this guard exists
    # to catch.
    "crypto": "USD",
}

# Non-US futures venues. The GlobalFuturesEngine is USD-denominated end to end
# — margin, commission and contract multipliers are all in USD and it carries
# no EUR or JPY product — so anything it handles settles in USD unless the
# symbol names a venue that does not.
_FUTURES_EXCHANGE_CURRENCY = {"EUREX": "EUR"}


def code_currency(code: str) -> str:
    """Return the currency a symbol settles in.

    Args:
        code: Ticker / symbol string.

    Returns:
        A currency code such as ``"CNY"``. A forex pair resolves to its quote
        currency and Chinese futures to ``"CNY"``. A symbol whose currency
        cannot be established returns a ``"UNKNOWN:<market>"`` marker rather
        than a guess, so a homogeneous set still compares equal while a mixed
        one cannot pass a same-currency check by accident.
    """
    market = _detect_market(code)
    if market in _MARKET_CURRENCY:
        return _MARKET_CURRENCY[market]
    if market == "forex":
        pair = code.upper().replace("/", "")
        if pair.endswith(".FX"):
            pair = pair[:-3]
        return pair[3:6] if len(pair) == 6 else "UNKNOWN:forex"
    if market == "futures":
        if _is_china_futures(code):
            return "CNY"
        exchange = code.upper().rpartition(".")[2]
        return _FUTURES_EXCHANGE_CURRENCY.get(exchange, "USD")
    return f"UNKNOWN:{market}"

# Known Chinese-futures product codes — used as a heuristic when a symbol
# lacks an exchange suffix (e.g. bare ``RB2410``, ``IF2406``). Without this
# table composite.py was misrouting such bare codes to GlobalFutures.
# Stored lowercase; ``_is_china_futures`` lowercases the extracted product
# before lookup so callers can pass any case (``RB2410`` and ``rb2410``
# both resolve correctly).
_CN_FUTURES_PRODUCTS = {
    "if", "ic", "ih", "im", "t", "tf", "ts", "tl",
    "au", "ag", "cu", "al", "zn", "pb", "ni", "sn", "ss",
    "rb", "hc", "i", "j", "jm",
    "sc", "fu", "lu", "bu", "nr",
    "c", "cs", "m", "y", "a", "p", "jd", "lh",
    "cf", "sr", "ta", "ma", "ap", "rm", "oi",
    "pp", "l", "v", "eg", "eb", "pf", "sa", "fg", "ur",
    "si", "lc",
}


def _detect_market(code: str) -> str:
    """Infer market type from symbol format.

    Args:
        code: Ticker / symbol string.

    Returns:
        Market type (a_share/us_equity/hk_equity/india_equity/kr_equity/
        ca_equity/crypto/futures/forex).
        Bare 1-5 letter alphabetic tickers resolve to ``us_equity``;
        any other unknown format defaults to ``a_share``.
    """
    for pattern, market in _MARKET_PATTERNS:
        if pattern.match(code):
            return market
    return "a_share"


def _is_china_futures(code: str) -> bool:
    """Check whether a futures code belongs to a Chinese exchange.

    Recognises two forms:
      1. ``<product><delivery>.<exchange>`` where exchange is one of
         CFFEX/SHFE/DCE/ZCE/INE/GFEX (e.g. ``IF2406.CFFEX``, ``rb2410.SHFE``).
      2. Bare ``<product><delivery>`` with no exchange suffix — matched
         against ``_CN_FUTURES_PRODUCTS`` (e.g. ``RB2410`` -> True).

    Args:
        code: Symbol string.

    Returns:
        True if it looks like a Chinese futures contract.
    """
    parts = code.upper().split(".")
    if len(parts) == 2:
        # Has an exchange suffix — trust it. CN exchange = True, anything
        # else = False. Without this guard the product-code heuristic below
        # would misclassify global futures whose product letters happen to
        # collide with a CN product (e.g. ``M2412.CBOT`` — US soybean meal).
        return parts[1] in _CHINA_EXCHANGES
    # Bare code (no exchange suffix): fall back to product-code heuristic.
    m = re.match(r"([A-Za-z]+)\d+", parts[0])
    if m:
        product = m.group(1).lower()
        if product in _CN_FUTURES_PRODUCTS:
            return True
    return False


def _detect_submarket(codes: List[str]) -> str:
    """Detect US, HK, or Canada from symbol suffixes.

    Args:
        codes: Instrument codes.

    Returns:
        ``"hk"`` for ``.HK``, ``"ca"`` for ``.TO``/``.V``, else ``"us"``.
    """
    for code in codes:
        upper = code.upper()
        if upper.endswith(".HK"):
            return "hk"
        if upper.endswith((".TO", ".V")):
            return "ca"
    return "us"

# ── Crypto: OKX tiered maintenance margin table (simplified) ──

_TIER_TABLE = [
    (100_000, 0.004),
    (500_000, 0.006),
    (1_000_000, 0.01),
    (5_000_000, 0.02),
    (10_000_000, 0.05),
    (float("inf"), 0.10),
]

FUNDING_HOURS = {0, 8, 16}


def _maintenance_rate(notional_usd: float) -> float:
    """Look up tiered maintenance margin rate."""
    for tier_max, rate in _TIER_TABLE:
        if notional_usd <= tier_max:
            return rate
    return _TIER_TABLE[-1][1]


def calc_crypto_funding_fee(
    symbol: str,
    bar: pd.Series,
    timestamp: pd.Timestamp,
    positions: Dict[str, Position],
    funding_rate: float,
    applied_set: set,
    daily_done_set: set,
) -> float:
    """Calculate crypto funding fee for one symbol.

    Args:
        symbol: Instrument code.
        bar: Current bar data.
        timestamp: Bar timestamp.
        positions: Shared positions dict.
        funding_rate: Fallback fixed rate per settlement, used when the bar
            carries no historical ``funding_rate`` column.
        applied_set: (symbol, date, hour) dedup set — mutated.
        daily_done_set: (symbol, date) dedup set — mutated.

    Returns:
        Fee amount (positive = longs pay, negative = longs receive).
    """
    if not hasattr(timestamp, "date"):
        return 0.0

    current_date = timestamp.date()
    hour = timestamp.hour if hasattr(timestamp, "hour") else 0

    if hour in FUNDING_HOURS:
        key = (symbol, current_date, hour)
        if key in applied_set:
            return 0.0
        applied_set.add(key)
    else:
        day_key = (symbol, current_date)
        if day_key in daily_done_set:
            return 0.0
        daily_done_set.add(day_key)

    pos = positions.get(symbol)
    if pos is None:
        return 0.0

    mark_price = float(bar.get("close", pos.entry_price))
    notional = pos.size * mark_price
    # Prefer the bar's historical funding rate when the loader supplied one
    # (USD-M perpetual data via BASE-USDT-PERP); fall back to the fixed
    # config rate otherwise so spot-proxy runs keep their behaviour.
    hist = bar.get("funding_rate")
    if hist is not None and pd.notna(hist):
        funding_rate = float(hist)
    return notional * funding_rate * pos.direction


def check_crypto_liquidation(
    symbol: str,
    bar: pd.Series,
    positions: Dict[str, Position],
) -> bool:
    """Check if a crypto position should be liquidated.

    Args:
        symbol: Instrument code.
        bar: Current bar data.
        positions: Shared positions dict.

    Returns:
        True if liquidation should be triggered.
        Does NOT execute the liquidation -- caller handles that.
    """
    pos = positions.get(symbol)
    if pos is None or pos.leverage <= 1.0:
        return False

    mark_price = float(bar.get("close", pos.entry_price))
    margin = pos.size * pos.entry_price / pos.leverage
    unrealized = pos.direction * pos.size * (mark_price - pos.entry_price)

    notional = pos.size * mark_price
    maint_rate = _maintenance_rate(notional)
    maint_margin = notional * maint_rate

    return (margin + unrealized) <= maint_margin


# ── Forex: swap tables ──

_SWAP_LONG: dict[str, float] = {
    "EUR/USD": -6.5, "GBP/USD": -3.0, "USD/JPY": 8.0, "USD/CHF": 4.0,
    "AUD/USD": -2.0, "USD/CAD": 2.0, "NZD/USD": -1.5,
}
_SWAP_SHORT: dict[str, float] = {
    "EUR/USD": 3.5, "GBP/USD": -1.0, "USD/JPY": -12.0, "USD/CHF": -8.0,
    "AUD/USD": -1.0, "USD/CAD": -5.0, "NZD/USD": -2.0,
}


def _normalize_symbol(symbol: str) -> str:
    """Normalize forex symbol to 'XXX/YYY' format."""
    s = symbol.replace(".FX", "").replace(".", "").strip()
    if "/" in s:
        return s.upper()
    if len(s) == 6:
        return f"{s[:3]}/{s[3:]}".upper()
    return s.upper()


def calc_forex_swap(
    symbol: str,
    timestamp: pd.Timestamp,
    positions: Dict[str, Position],
    lot_size: float,
    last_swap_dates: dict,
) -> float:
    """Calculate forex swap for one symbol.

    Args:
        symbol: Forex pair.
        timestamp: Bar timestamp.
        positions: Shared positions dict.
        lot_size: Standard lot size (e.g. 100_000).
        last_swap_dates: Per-symbol date tracking dict -- mutated.

    Returns:
        Swap amount (positive = credit, negative = debit).
    """
    if not hasattr(timestamp, "date"):
        return 0.0

    current_date = timestamp.date()
    if last_swap_dates.get(symbol) == current_date:
        return 0.0
    last_swap_dates[symbol] = current_date

    pos = positions.get(symbol)
    if pos is None:
        return 0.0

    pair = _normalize_symbol(symbol)
    lots = pos.size / lot_size

    if pos.direction == 1:
        swap_per_lot = _SWAP_LONG.get(pair, -1.0)
    else:
        swap_per_lot = _SWAP_SHORT.get(pair, -1.0)

    # Wednesday = triple swap (covers Sat+Sun)
    multiplier = 3.0 if timestamp.weekday() == 2 else 1.0
    return lots * swap_per_lot * multiplier
