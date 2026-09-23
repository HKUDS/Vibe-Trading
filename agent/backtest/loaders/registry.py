"""Loader registry with market-level fallback chains.

Loaders self-register via the ``@register`` decorator when their module is
first imported.  The ``_ensure_registered()`` helper lazily imports every
known loader module so that callers of ``resolve_loader`` /
``get_loader_cls_with_fallback`` never see an empty registry — regardless
of import order.
"""

from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any, Type

from backtest.loaders.base import NoAvailableSourceError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global registry: source_name -> loader class
# ---------------------------------------------------------------------------

LOADER_REGISTRY: dict[str, Type[Any]] = {}

_registered = False
_registration_lock = Lock()

# Canonical set of accepted data-source names: every registered loader plus the
# ``"auto"`` cross-market selector. Single source of truth shared by the backtest
# config schema (``backtest.runner.BacktestConfigSchema``) and the agent-facing
# backtest tool (``src.tools.backtest_tool``) so the two can never drift apart.
# Keep in sync with ``_loader_modules`` below — the regression test
# ``test_valid_sources_covers_all_registered_loaders`` enforces full coverage.
VALID_SOURCES: set[str] = {
    "tushare",
    "okx",
    "nobitex",
    "wallex",
    "binance",
    "yfinance",
    "akshare",
    "baostock",
    "tencent",
    "mootdx",
    "ccxt",
    "futu",
    "eastmoney",
    "sina",
    "stooq",
    "yahoo",
    "finnhub",
    "alphavantage",
    "tiingo",
    "fmp",
    "gildata",
    "qveris",  # QVERIS-INTEGRATION
    "india_broker",
    "pykrx",
    "longbridge",
    "mt5",
    "tickerall",
    "local",
    "auto",
}


def register(cls: Type[Any]) -> Type[Any]:
    """Class decorator: register a loader into the global registry.

    The class must have a ``name`` class attribute.
    """
    LOADER_REGISTRY[cls.name] = cls
    return cls


def _ensure_registered() -> None:
    """Import every known loader module so ``@register`` decorators fire.

    Safe to call multiple times — only runs the imports once.
    Concurrent callers wait until the import pass finishes.
    Loaders whose dependencies are missing (e.g. ``akshare`` not installed)
    are silently skipped.
    """
    # Re-check env overrides even when already registered — a subprocess may
    # have loaded ~/.vibe-trading/.env (or synced os.environ) after this
    # module's import-time refresh ran. Must precede the early return.
    refresh_source_order_overrides()
    global _registered
    if _registered:
        return

    with _registration_lock:
        if _registered:
            return

        _loader_modules = [
            "backtest.loaders.tushare",
            "backtest.loaders.okx",
            "backtest.loaders.nobitex",
            "backtest.loaders.wallex",
            "backtest.loaders.binance_loader",
            "backtest.loaders.yfinance_loader",
            "backtest.loaders.akshare_loader",
            "backtest.loaders.baostock_loader",
            "backtest.loaders.tencent_loader",
            "backtest.loaders.mootdx_loader",
            "backtest.loaders.ccxt_loader",
            "backtest.loaders.futu",
            "backtest.loaders.eastmoney_loader",
            "backtest.loaders.sina_loader",
            "backtest.loaders.stooq_loader",
            "backtest.loaders.yahoo_loader",
            "backtest.loaders.finnhub_loader",
            "backtest.loaders.alphavantage_loader",
            "backtest.loaders.tiingo_loader",
            "backtest.loaders.fmp_loader",
            "backtest.loaders.gildata_loader",
            "backtest.loaders.qveris_loader",  # QVERIS-INTEGRATION
            "backtest.loaders.india_broker_loader",
            "backtest.loaders.pykrx_loader",
            "backtest.loaders.longbridge",
            "backtest.loaders.mt5_loader",
            "backtest.loaders.tickerall_loader",
            "backtest.loaders.local_loader",
        ]
        import importlib

        for mod in _loader_modules:
            try:
                importlib.import_module(mod)
            except Exception:
                pass
        _registered = True


# Sources that must NEVER silently fall through to a network loader when the
# caller asked for them explicitly. ``local`` reads the user's own configured
# files (``~/.vibe-trading/data-bridge/config.yaml``); its ``markets`` set spans
# every market only so the cross-market auto-resolver can *reach* it, not so an
# unavailable ``local`` request can degrade into an unrelated network source.
# An explicit ``local`` request that is unavailable is a config problem the user
# must see, not something to paper over with a Yahoo/Tencent fetch.
# ``tickerall`` joins for the same reason (explicit-only, the user's own broker key).
# ``fmp`` joins because an explicit ``source="fmp"`` request must not silently
# return data from a different source when the Stable endpoint 403s — the
# caller asked for FMP provenance, not a Yahoo fallback (issue #1270).
# ``nobitex``/``wallex`` join for a stronger version of the same reason: they
# are the only sources quoting in Iranian Toman, and they declare
# ``markets = {"crypto"}`` purely to be reachable. Degrading an unavailable
# ``BTCIRT`` request into the crypto chain would hand a USDT-quoted series back
# as if it were Toman — a caliber error of about six orders of magnitude, not a
# missing-data error. An unreachable Iranian endpoint must be visible.
_NO_NETWORK_FALLBACK_SOURCES: frozenset[str] = frozenset(
    {"local", "qveris", "tickerall", "fmp", "nobitex", "wallex"}
)  # QVERIS-INTEGRATION


def is_no_network_fallback_source(source: str) -> bool:
    """Whether an explicit request for *source* must never silently degrade.

    The set itself stays module-private; callers outside the registry ask
    through this predicate instead of importing the underscore name.
    """
    return source in _NO_NETWORK_FALLBACK_SOURCES


# ---------------------------------------------------------------------------
# Fallback chains: market_type -> ordered list of source names
# ---------------------------------------------------------------------------

# Chains are ordered by IP-ban risk first (lighter, throttle-tolerant public
# endpoints lead; key-gated REST and rate-limit-prone sources trail), then by
# data quality. Eastmoney/Sina/Stooq/Yahoo are unauthenticated public sources
# that must be politely throttled; Finnhub/AlphaVantage/Tiingo/FMP are key-gated
# REST fallbacks placed deeper in the chain.
FALLBACK_CHAINS: dict[str, list[str]] = {
    "a_share": [
        "tencent",
        "mootdx",
        "eastmoney",
        "baostock",
        "akshare",
        "tushare",
        # Key-gated commercial vendor (恒生聚源): trails the free sources so
        # paid quota is only spent when the public endpoints cannot serve.
        "gildata",
        "local",
    ],
    "us_equity": [
        "yahoo",
        "stooq",
        "sina",
        "eastmoney",
        "yfinance",
        "tiingo",
        "fmp",
        "finnhub",
        "alphavantage",
        "longbridge",
        "akshare",
        "local",
    ],
    # HK: tencent leads (no observed IP ban); akshare (Eastmoney-backed)
    # precedes the Yahoo-SDK family, which is blocked from mainland IPs;
    # tushare hk_daily is key-gated.
    "hk_equity": [
        "tencent",
        "eastmoney",
        "yahoo",
        "futu",
        "akshare",
        "yfinance",
        "tushare",
        "longbridge",
        "local",
    ],
    "india_equity": ["yahoo", "yfinance", "india_broker", "local"],
    "kr_equity": ["pykrx", "yahoo", "yfinance", "local"],
    # TSX (.TO) / TSX Venture (.V): direct Yahoo first, SDK fallback second.
    "ca_equity": ["yahoo", "yfinance", "local"],
    # Argentina (BYMA .BA): Yahoo public chart first, yfinance fallback.
    "ar_equity": ["yahoo", "yfinance", "local"],
    # UK (LSE .L): direct Yahoo first, SDK fallback second.
    "uk_equity": ["yahoo", "yfinance", "local"],
    # Vietnam (.VN): Yahoo lists HOSE only — HNX and UPCOM are unsupported,
    # so those two are reachable only through the user's local files.
    "vietnam_equity": ["yahoo", "yfinance", "local"],
    # OKX first (native), then dedicated Binance, then generic CCXT / Yahoo.
    "crypto": ["okx", "binance", "ccxt", "yfinance", "local"],
    # tushare led this chain while implementing no futures endpoint at all
    # (#1395): ``resolve_loader`` walks FALLBACK_CHAINS and never consults a
    # loader's ``markets`` set, so trimming that set alone would have left
    # tushare first in line, returning empty frames before akshare was ever
    # asked. akshare serves Chinese contracts off the token-free Sina daily
    # endpoints; a global contract has no network source and reaches ``local``.
    "futures": ["akshare", "local"],
    "fund": ["tushare", "akshare", "local"],
    "macro": ["akshare", "tushare", "local"],
    # mt5 leads when a local MetaTrader 5 terminal is attached (Windows-only,
    # broker feed); otherwise it reports unavailable and the chain proceeds.
    "forex": ["mt5", "akshare", "yfinance", "local"],
    # Yahoo index symbols (^SPX, ^NDX, ^FTSE, ^VIX, ...): served verbatim by
    # the public chart endpoint, same as the =F/=X conventions.
    "index": ["yahoo", "yfinance", "local"],
}


# ---------------------------------------------------------------------------
# Price caliber: what the served prices actually mean, per source (#1301)
# ---------------------------------------------------------------------------

#: A value lands here only when it is measured against live payloads (the
#: #1301 chain table) or pinned by the loader's own endpoint/parameter
#: choice. Anything unverified resolves to "unknown" on purpose: origin-side
#: adjustment is invisible from loader code (yahoo serves split-adjusted
#: quotes with zero adjustment logic in this repo), so an unmeasured source
#: must say "unknown" rather than a guessed caliber.
PRICE_CALIBER_BY_SOURCE: dict[str, str] = {
    # Split- and dividend-adjusted.
    "yahoo": "split_dividend",  # quote series split-adjusted at origin, scaled to adjclose
    "yfinance": "split_dividend",  # auto_adjust=True
    "eastmoney": "split_dividend",  # fqt=1 (forward-adjusted) on every kline call
    # Tencent's qfq subtracts cash dividends from the price level instead of
    # scaling by a ratio: between corporate actions qfq = raw + c, and c steps by
    # the dividend at each ex-date (#1493, measured on 600519.SH where five
    # constant offsets cover 500 bars). The level is therefore not on the same
    # scale as the multiplicative sources above, so it gets its own caliber.
    "tencent": "split_dividend_additive",  # fqkline qfq, additive in dividends
    "akshare": "split_dividend",  # adjust="qfq", including the stock_us_hist path
    "baostock": "split_dividend",  # adjustflag="2"
    "tushare": "split_dividend",  # adj_factor applied via cn_adjust (A-share/fund)
    "tiingo": "split_dividend",  # prefers adjOpen/High/Low/Close, else adjClose/close
    "fmp": "split_dividend",  # Stable historical-price-eod/full, scaled by adjClose/close
    "gildata": "split_dividend",  # StockDailyQuote restorationStatus=1 (前复权), measured vs live payload
    # Split-adjusted only.
    "pykrx": "split",  # get_market_ohlcv_by_date(adjusted=True), Naver-backed
    # Unadjusted.
    "sina": "raw",
    "alphavantage": "raw",  # TIME_SERIES_DAILY, not the _ADJUSTED endpoint
    "longbridge": "raw",  # pins AdjustType.NoAdjust
}

#: Per-(source, market) exceptions to the per-source table.
PRICE_CALIBER_BY_SOURCE_MARKET: dict[tuple[str, str], str] = {
    # Tushare publishes no HK adjustment-factor series, so its HK path is raw.
    ("tushare", "hk_equity"): "raw",
    # Tencent serves no adjusted series for HK at all: its fqkline reply carries
    # only "day" (never "qfqday"/"hfqday") for HK symbols, so the loader's
    # ``qfqday or day`` fallback silently serves unadjusted bars and the `,qfq`
    # request parameter changes nothing. Checked on 00939.HK and 00700.HK against
    # eastmoney, whose adjusted HK series does differ from its raw one, so the
    # actions exist and are simply not served here (#1493).
    ("tencent", "hk_equity"): "raw",
    # Eastmoney's A-share fqt=1 is additive in the same way, with the same
    # offsets: 600519.SH fqt=1 - fqt=0 takes five values (-103.46 / -79.58 /
    # -51.98 / -28.02 / 0) over 500 bars against 367 distinct ratios, and
    # 601398.SH five against 253 (measured 2026-09-21). akshare's
    # stock_zh_a_hist(adjust="qfq") requests that endpoint with fqt=1. Their HK
    # and US series are not measured and keep the per-source label.
    ("eastmoney", "a_share"): "split_dividend_additive",
    ("akshare", "a_share"): "split_dividend_additive",
}

#: Markets with no corporate-action adjustment concept. Their sources stamp
#: "na" and stay out of mixed-caliber comparisons.
_NA_CALIBER_MARKETS = frozenset({"crypto", "forex", "futures", "macro"})

#: A price index has no corporate actions, so every source serves the one
#: unadjusted level, whatever it does to a stock: eastmoney fqt=1 equals fqt=0
#: on every bar of 000300.SH, 000001.SH, 000016.SH, 000905.SH, 399001.SZ,
#: 399006.SZ and 899050.BJ, Tencent's fqkline returns only "day" for the six
#: SSE/SZSE ones (nothing at all for 899050.BJ), and Yahoo's adjclose equals
#: close on ^GSPC, ^NDX and ^HSI (measured 2026-09-22).
#: The per-source table stamped them by what the source does to a stock, so an
#: A-share index read as additive and a Yahoo index as dividend-adjusted (#1541).
#: Indices stay comparable: a price index beside a dividend-adjusted stock is a
#: real caliber mix. A-share index codes are exchange-specific: 000001.SH is
#: the SSE Composite, 000001.SZ is Ping An Bank.
_INDEX_CALIBER_MARKETS = frozenset({"index"})
_A_SHARE_INDEX_CODE = re.compile(r"^(?:000\d{3}\.SH|399\d{3}\.SZ|899\d{3}\.BJ)$", re.I)

#: Calibers that participate in mixed-caliber comparison. "unknown" and "na"
#: never do: the first is unmeasured, the second has nothing to adjust for.
#: "split_dividend_additive" does participate — it is the whole point of the
#: caliber: an additive level and a multiplicative one are two different scales,
#: so a basket holding both must be warned about (#1493).
_COMPARABLE_CALIBERS = frozenset(
    {"raw", "split", "split_dividend", "split_dividend_additive"}
)

#: Calibers whose daily moves cannot be read as returns at all. Cash dividends
#: enter the price *level* as an offset rather than scaling the series, so a
#: window return is not a total return and an old level can even go negative.
#: Unlike a mixed basket, this is a defect of the series itself: it needs a
#: warning even when every symbol in the run came from the one source.
_ADDITIVE_CALIBERS = frozenset({"split_dividend_additive"})


def market_has_corporate_actions(market: str) -> bool:
    """Whether prices in ``market`` depend on a split/dividend adjustment.

    Args:
        market: A market name as ``_detect_market`` returns it.

    Returns:
        False for the markets stamped "na" and for price indices, True for
        every other market, so an unrecognized one is assumed to need it.
    """
    return market not in _NA_CALIBER_MARKETS and market not in _INDEX_CALIBER_MARKETS


def price_caliber(source: str, market: str | None = None, symbol: str | None = None) -> str:
    """Return the adjustment caliber of ``source``'s served prices.

    Args:
        source: Loader that served the prices.
        market: Market the symbol belongs to.
        symbol: The served symbol, needed to tell an A-share index from a stock.

    Returns:
        One of "raw", "split", "split_dividend", "split_dividend_additive"
        (dividend adjustment applied to the level rather than by a ratio),
        "na" (a market without corporate actions), or "unknown" (an
        unmeasured source).
    """
    if market in _NA_CALIBER_MARKETS:
        return "na"
    if market in _INDEX_CALIBER_MARKETS or (
        market == "a_share" and symbol is not None and _A_SHARE_INDEX_CODE.match(symbol)
    ):
        return "raw"
    return PRICE_CALIBER_BY_SOURCE_MARKET.get(
        (source, market), PRICE_CALIBER_BY_SOURCE.get(source, "unknown")
    )


def mixed_caliber_warning(stamps: dict[str, tuple[str, str]]) -> str | None:
    """Build the mixed-caliber warning for a served basket, or None.

    ``stamps`` maps each served symbol to the (source, caliber) pair that
    served it. Fires only when at least two distinct comparable calibers are
    present; "unknown" and "na" entries never trigger it.
    """
    by_caliber: dict[str, list[str]] = {}
    for symbol, (_source, caliber) in stamps.items():
        if caliber in _COMPARABLE_CALIBERS:
            by_caliber.setdefault(caliber, []).append(symbol)
    if len(by_caliber) < 2:
        return None
    parts = []
    for caliber, symbols in sorted(by_caliber.items()):
        shown = ", ".join(sorted(symbols)[:4])
        if len(symbols) > 4:
            shown += f", +{len(symbols) - 4} more"
        parts.append(f"{caliber} ({shown})")
    return (
        "mixed price calibers in this run: " + "; ".join(parts) + ". "
        "Prices are not on the same scale across calibers, so cross-symbol "
        "comparisons (momentum ranks, relative performance) are biased. "
        "See the adjustment field of each symbol's provenance entry."
    )


def additive_caliber_warning(stamps: dict[str, tuple[str, str]]) -> str | None:
    """Build the served-additive-caliber warning for a run, or None.

    ``stamps`` maps each served symbol to the (source, caliber) pair that
    served it. Unlike :func:`mixed_caliber_warning` this fires on a *single*
    additive source, because the problem is the series rather than the basket:
    a run that mixes nothing is still computing returns off levels that have
    dividends added back as a flat offset. That is the common A-share case,
    since ``tencent`` heads the chain (#1493).
    """
    additive = {
        symbol: source
        for symbol, (source, caliber) in stamps.items()
        if caliber in _ADDITIVE_CALIBERS
    }
    if not additive:
        return None
    shown = ", ".join(
        f"{symbol} ({source})" for symbol, source in sorted(additive.items())[:4]
    )
    if len(additive) > 4:
        shown += f", +{len(additive) - 4} more"
    return (
        "additive price adjustment in this run: " + shown + ". "
        "Cash dividends are added back as a flat offset rather than "
        "reinvested, so period returns and volatilities are not total "
        "returns and long-horizon backtests are distorted (old prices can "
        "go negative). Prefer a multiplicative source for return math."
    )


# ---------------------------------------------------------------------------
# Source-order overrides: per-market env-configurable chain priority
# ---------------------------------------------------------------------------

# Users can reprioritize a market's chain via one env var per market
# (persisted to ~/.vibe-trading/.env by the Settings page's "source
# priority" card):
#     MARKET_DATA_ORDER_A_SHARE=tushare,tencent,mootdx,...
# The value must be a permutation of the market's default chain —
# reordering is allowed, adding/dropping sources is not. Invalid values
# warn and keep the default chain, so a typo can never silently strip a
# market of its sources.
_SOURCE_ORDER_ENV_PREFIX = "MARKET_DATA_ORDER_"

# Snapshot of the chains as written above. refresh_source_order_overrides()
# restores from here; entries must never leak into FALLBACK_CHAINS by
# aliasing (always copy on restore), or a restore would mutate the snapshot.
_DEFAULT_CHAINS: dict[str, list[str]] = {
    market: chain[:] for market, chain in FALLBACK_CHAINS.items()
}

# market -> override currently in effect. Populated only by
# refresh_source_order_overrides(); absent key = default chain in effect.
_ACTIVE_SOURCE_ORDER_OVERRIDES: dict[str, list[str]] = {}

# Env values refresh_source_order_overrides() last saw. When unchanged the
# refresh is a no-op — override-free environments never touch FALLBACK_CHAINS,
# so tests that patch.dict the chains directly stay unaffected.
_LAST_ORDER_ENV_SNAPSHOT: dict[str, str] | None = None


def source_order_env_var(market: str) -> str:
    """Return the env var name overriding ``market``'s source order.

    ``"a_share"`` -> ``"MARKET_DATA_ORDER_A_SHARE"``.
    """
    return _SOURCE_ORDER_ENV_PREFIX + market.upper()


def parse_source_order(raw: str) -> list[str]:
    """Parse a comma-separated source order string.

    Tokens are stripped, lowercased, and empty ones dropped, so
    ``" TUSHARE, tencent ,, "`` parses to ``["tushare", "tencent"]``.
    Validating against the market's default chain is a separate step
    (:func:`is_valid_source_order`).
    """
    return [token.strip().lower() for token in raw.split(",") if token.strip()]


def is_valid_source_order(market: str, order: list[str]) -> bool:
    """True when ``order`` is a permutation of ``market``'s default chain.

    Multiset equality — every default member exactly once, nothing extra —
    so reordering passes while adding, dropping, or duplicating a source
    fails. Unknown markets are never valid.
    """
    default = _DEFAULT_CHAINS.get(market)
    if default is None:
        return False
    return sorted(order) == sorted(default)


def get_default_source_order(market: str) -> list[str]:
    """Return a copy of ``market``'s default chain (empty if unknown)."""
    return _DEFAULT_CHAINS.get(market, [])[:]


def get_source_order_override(market: str) -> list[str] | None:
    """Return the active env-configured order for ``market``, or ``None``."""
    override = _ACTIVE_SOURCE_ORDER_OVERRIDES.get(market)
    return override[:] if override is not None else None


def refresh_source_order_overrides() -> None:
    """Apply ``MARKET_DATA_ORDER_*`` env values onto :data:`FALLBACK_CHAINS`.

    Snapshot-gated: when the relevant env vars are unchanged since the last
    call, return immediately — an environment with no overrides costs
    nothing and never reassigns chains. On change, each market's chain is
    reassigned **in place** (``FALLBACK_CHAINS[market] = ...``): the dict
    keeps its identity, so both ``from ... import FALLBACK_CHAINS`` and
    attribute-access consumers see the new order. An empty/cleared var
    restores the default chain.
    """
    global _LAST_ORDER_ENV_SNAPSHOT
    # Config-layer read (ci_env_var_gate: no raw os.getenv outside src/config/).
    # get_env_value passes through to os.getenv un-cached, so hot-apply still
    # only needs the os.environ sync the Settings PUT performs. Imported here,
    # not at module top, matching the other loaders' accessor usage.
    from src.config.accessor import get_env_value

    snapshot = {
        source_order_env_var(market): get_env_value(source_order_env_var(market), "")
        for market in _DEFAULT_CHAINS
    }
    if snapshot == _LAST_ORDER_ENV_SNAPSHOT:
        return
    _LAST_ORDER_ENV_SNAPSHOT = snapshot

    for market, default in _DEFAULT_CHAINS.items():
        raw = snapshot[source_order_env_var(market)]
        order = parse_source_order(raw) if raw else []
        if order and is_valid_source_order(market, order):
            FALLBACK_CHAINS[market] = order[:]
            _ACTIVE_SOURCE_ORDER_OVERRIDES[market] = order[:]
            continue
        if order:  # non-empty but invalid — warn, keep default order
            logger.warning(
                "Ignoring invalid %s=%r: value must be a permutation of the"
                " default chain %s; keeping default order",
                source_order_env_var(market),
                raw,
                default,
            )
        FALLBACK_CHAINS[market] = default[:]
        _ACTIVE_SOURCE_ORDER_OVERRIDES.pop(market, None)


# Import-time refresh: picks up overrides present in the process env before
# any caller touches the chains (subprocess/CLI entry paths).
refresh_source_order_overrides()


def resolve_loader(market: str) -> Any:
    """Return the first *available* loader instance for *market*.

    Walks the fallback chain and returns the first loader whose
    ``is_available()`` returns ``True``.

    Args:
        market: Market type key (e.g. ``"a_share"``, ``"crypto"``).

    Returns:
        A loader instance.

    Raises:
        NoAvailableSourceError: If every candidate is unavailable.
    """
    _ensure_registered()
    chain = FALLBACK_CHAINS.get(market, [])
    tried: list[str] = []
    for name in chain:
        if name not in LOADER_REGISTRY:
            continue
        tried.append(name)
        # Issue #50 — some loaders (e.g. Tushare) call into the SDK during
        # __init__ and raise on missing credentials. Treat that the same as
        # is_available()=False so the fallback chain keeps walking.
        try:
            loader = LOADER_REGISTRY[name]()
        except Exception as exc:
            logger.debug("loader %s failed to construct: %s", name, exc)
            continue
        if loader.is_available():
            return loader
    raise NoAvailableSourceError(
        f"No available data source for market '{market}'. "
        f"Tried: {tried or chain}. Check network and API token config."
    )


def get_loader_cls_with_fallback(source: str) -> Type[Any]:
    """Return a loader *class* for *source*, falling back if unavailable.

    Args:
        source: Requested data source name.

    Returns:
        A DataLoader class (not instance).

    Raises:
        NoAvailableSourceError: If the source and all fallbacks are unavailable.
    """
    _ensure_registered()
    if source not in LOADER_REGISTRY:
        raise NoAvailableSourceError(f"Unknown data source: {source}")

    loader_cls = LOADER_REGISTRY[source]
    try:
        instance = loader_cls()
    except Exception as exc:
        logger.debug("loader %s failed to construct: %s", source, exc)
        instance = None
    if instance is not None and instance.is_available():
        return loader_cls

    # Some sources must never silently degrade to an unrelated network loader
    # when explicitly requested. ``local`` is the canonical case: its broad
    # ``markets`` set exists only to make it reachable from the cross-market
    # auto-resolver, so falling back through it would fetch network data the
    # user never asked for and mask a Data Bridge config problem. Fail loudly.
    if source in _NO_NETWORK_FALLBACK_SOURCES:
        hint = {
            "local": "Check your Data Bridge config "
            "(~/.vibe-trading/data-bridge/config.yaml) — it must exist and "
            "list at least one source.",
            "tickerall": "Set TICKERALL_API_KEY and TICKERALL_ACCOUNT_ID.",
            "fmp": "Set FMP_API_KEY.",
            "nobitex": "Nobitex's public endpoint was unreachable. It quotes in "
            "Toman (IRT) and has no substitute — check network access "
            "to apiv2.nobitex.ir.",
            "wallex": "Wallex's public endpoint was unreachable. It quotes in "
            "Toman (TMN) and has no substitute — check network access "
            "to api.wallex.ir.",
        }.get(source, "")
        raise NoAvailableSourceError(
            f"Data source '{source}' is unavailable and does not fall back to a "
            f"network source. {hint}".rstrip()
        )

    # Source unavailable — try same-market fallback
    for market in loader_cls.markets:
        try:
            fallback = resolve_loader(market)
            logger.warning(
                "%s is unavailable, falling back to %s for market %s",
                source,
                fallback.name,
                market,
            )
            return type(fallback)
        except NoAvailableSourceError:
            continue

    raise NoAvailableSourceError(
        f"Data source '{source}' is unavailable and no fallback found."
    )
