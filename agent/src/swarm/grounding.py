"""Pre-fetch market data for symbols mentioned in a swarm's user_vars."""

from __future__ import annotations

import logging
import math
import re
from datetime import date, timedelta
from typing import Iterable

from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)


def _is_finite(value: float) -> bool:
    """Return True when *value* is a finite number (not NaN, not inf)."""
    return isinstance(value, (int, float)) and math.isfinite(value)


# Keep the recent price window small enough for worker prompts.
DEFAULT_WINDOW_DAYS = 30
DEFAULT_MAX_SYMBOLS = 8

# Limit displayed bars while using the full window for extrema.
PROMPT_TABLE_TAIL = 5

# Symbol patterns understood by the bundled loaders. Anchored on word
# boundaries so substrings of longer text don't trigger.
_SYMBOL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Z]{1,5}\.US\b"),
    re.compile(r"\b\d{3,5}\.HK\b"),
    re.compile(r"\b\d{6}\.(?:SZ|SH|BJ)\b"),
    re.compile(r"\b[A-Z0-9&.-]+\.(?:TO|V)\b"),
    re.compile(r"\b[A-Z]{2,6}-USDT\b"),
)

# Exclude single letters and dotted compounds to avoid promoting prose or partial tickers.
_BARE_US_TICKER_PATTERN = re.compile(r"(?<![\w.])[A-Z]{2,5}(?!\w)(?!\.\w)")

# Exclude finance abbreviations that could resolve to unrelated listings.
_BARE_TICKER_STOPWORDS = frozenset({
    # geography / venues / index & data providers
    "US", "USA", "UK", "EU", "HK", "CN", "JP", "NYSE", "AMEX", "SSE", "SZSE",
    "HKEX", "TSX", "TSXV", "SPX", "NDX", "DJI", "DJIA", "HSI", "CSI", "FTSE", "MSCI", "VIX",
    # instruments / structures
    "ETF", "ETN", "ADR", "IPO", "REIT", "BOND", "SWAP", "PERP",
    # macro / institutions
    "FED", "FOMC", "SEC", "IMF", "GDP", "CPI", "PPI", "PMI", "PCE", "OPEC",
    "YOY", "QOQ", "MOM", "YTD", "EOD",
    # metrics / indicators
    "PE", "PB", "PS", "EPS", "ROE", "ROA", "ROI", "EBIT", "EV", "DCF",
    "CAGR", "IRR", "NAV", "AUM", "ATH", "ATL", "RSI", "MACD", "EMA", "SMA",
    "KDJ", "BOLL", "OHLC", "ADV", "PNL",
    # currencies / crypto traded under other loaders
    "USD", "EUR", "JPY", "GBP", "CNY", "CNH", "RMB", "KRW", "INR", "AUD",
    "CAD", "CHF", "FX", "BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE",
    "USDT", "USDC", "DEFI", "NFT", "DAO",
    # trading verbs / order words
    "BUY", "SELL", "HOLD", "LONG", "SHORT", "CALL", "PUT", "STOP", "LIMIT",
    "TP", "SL", "DCA",
    # tech / prose acronyms
    "AI", "ML", "LLM", "API", "JSON", "CSV", "PDF", "URL", "HTML", "CEO",
    "CFO", "CTO", "COO", "CIO", "VP", "OK", "FAQ", "ASAP", "AM", "PM",
    "EST", "PST", "UTC", "GMT",
})


def extract_symbols_from_user_vars(user_vars: dict[str, str]) -> list[str]:
    """Return a deduplicated list of symbols mentioned in the user variable values.

    Args:
        user_vars: Mapping whose string values are scanned for symbols.

    Returns:
        Suffixed symbols in first-occurrence order, followed by eligible bare tickers promoted to
        .US.
    """
    explicit: dict[str, None] = {}  # ordered set
    promoted: dict[str, None] = {}
    for value in user_vars.values():
        if not isinstance(value, str):
            continue
        remainder = value
        for pattern in _SYMBOL_PATTERNS:
            for match in pattern.findall(remainder):
                explicit.setdefault(match, None)
            # Blank matched spans so the bare scan can't split a suffixed
            # symbol into bogus fragments (BTC-USDT -> BTC.US).
            remainder = pattern.sub(" ", remainder)
        for token in _BARE_US_TICKER_PATTERN.findall(remainder):
            if token not in _BARE_TICKER_STOPWORDS:
                promoted.setdefault(f"{token}.US", None)
    return list(explicit) + [s for s in promoted if s not in explicit]


def max_grounding_symbols() -> int:
    """Return the configured cap for symbols fetched into worker prompts.

    Returns:
        Configured symbol cap, clamped to at least one.
    """
    value = get_env_config().swarm.swarm_grounding_max_symbols
    return max(1, value)


def fetch_grounding_data(
    symbols: Iterable[str],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    today: date | None = None,
) -> dict[str, list[dict]]:
    """Fetch daily OHLCV bars for the supplied symbols.

    Args:
        symbols: Iterable of suffixed symbols such as NVDA.US.
        window_days: Calendar-day lookback from the end date.
        today: End date for the fetch. Defaults to the current local date.

    Returns:
        Mapping from original symbols to lists of bars with trade_date, open, high, low, close, and
        volume. Symbols with missing or failed fetches are omitted.
    """
    symbols_list = list(symbols)
    if not symbols_list:
        return {}

    end = today or date.today()
    start = end - timedelta(days=window_days)
    start_str = start.isoformat()
    end_str = end.isoformat()

    # Defer loader imports and reuse standard market routing for extracted symbols.
    from backtest.loaders.registry import resolve_loader
    from backtest.runner import _detect_market

    out: dict[str, list[dict]] = {}
    for code in symbols_list:
        try:
            market = _detect_market(code)
            loader = resolve_loader(market)  # already a ready-to-use instance
            df_map = loader.fetch([code], start_str, end_str, interval="1D")
        except Exception as exc:  # pragma: no cover — depends on network
            logger.warning(
                "grounding: failed to fetch %s — %s", code, exc, exc_info=False
            )
            continue
        df = df_map.get(code)
        if df is None or df.empty:
            logger.info("grounding: no data returned for %s", code)
            continue
        rows: list[dict] = []
        for ts, row in df.iterrows():
            rows.append({
                "trade_date": getattr(ts, "isoformat", lambda: str(ts))(),
                "open": float(row.get("open", 0.0)),
                "high": float(row.get("high", 0.0)),
                "low": float(row.get("low", 0.0)),
                "close": float(row.get("close", 0.0)),
                "volume": float(row.get("volume", 0.0)),
            })
        if rows:
            out[code] = rows
    return out


def format_grounding_block(grounding: dict[str, list[dict]]) -> str:
    """Render a dated market snapshot for a worker prompt.

    Args:
        grounding: Mapping from symbol to dated OHLCV rows in chronological order.

    Returns:
        Markdown with recent rows and finite-close statistics, or an empty string if no symbol has a
        finite close.
    """
    if not grounding:
        return ""

    sections: list[str] = []
    for code, rows in grounding.items():
        if not rows:
            continue
        first_date = rows[0]["trade_date"][:10]
        last_date = rows[-1]["trade_date"][:10]
        closes = [row["close"] for row in rows if _is_finite(row["close"])]
        if not closes:
            continue
        window_low = min(closes)
        window_high = max(closes)
        last_close = closes[-1]
        # Pair the latest finite close with its own date because the final bar can lack a close.
        last_finite_row = next(
            (r for r in reversed(rows) if _is_finite(r["close"])), rows[-1]
        )
        last_close_date = last_finite_row["trade_date"][:10]

        lines = [
            f"### {code}  (window {first_date} → {last_date})",
            "",
            "| Date | Close | Volume |",
            "| --- | ---: | ---: |",
        ]
        for row in rows[-PROMPT_TABLE_TAIL:]:
            vol = row["volume"]
            vol_str = f"{int(vol):,}" if _is_finite(vol) else "—"
            close_str = f"{row['close']:.2f}" if _is_finite(row["close"]) else "—"
            lines.append(f"| {row['trade_date'][:10]} | {close_str} | {vol_str} |")
        lines.append("")
        lines.append(
            f"**Latest close:** {last_close:.2f} ({last_close_date})  "
            f"**Window range:** {window_low:.2f} – {window_high:.2f}"
        )
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        "## Initial Market Snapshot — Dated Reference\n\n"
        "These observations were fetched when the run began and may be older than "
        "later tool results, especially after continuation. Use the observation dates "
        "and price adjustment basis to choose comparable inputs. Newer verified "
        "data can supersede this snapshot; do not call an old snapshot current. "
        "When the entry price or other assumptions change, recompute dependent "
        "returns and hedge bounds rather than carrying over old percentages. "
        "Fetch missing data with get_market_data instead of recalling prices from training."
    )
    return header + "\n\n" + "\n\n".join(sections)
