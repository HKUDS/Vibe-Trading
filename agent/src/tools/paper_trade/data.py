"""Market-data supply layer for ``paper_trade_step`` (pt-v1.1 Step 2 / T2).

Public surface (the Step 3 engine consumes exactly these names):
:data:`MARKET_LOADER_KEYS` (resolve_loader wiring cn_a→a_share / hk→hk_equity
/ us→us_equity; the R5 ``MARKET_DATA_ORDER_US_EQUITY`` knob applies),
:data:`LOOKBACK_TRADING_DAYS` (K=120 FROZEN terminal value, VD-6/B3 —
delivery-note item; the window ``[from_date − K trading days, to_date]`` is
part of the data-snapshot definition), :func:`symbols_for_request` (universe =
positions ∪ orders, sorted — VD-10), :func:`fetch_market_data` (one batch
fetch per leg over the sorted list; served order = sorted order),
:func:`assess_readiness` (target-day readiness on the FEDERATED MERGED frame
— AM-9), :func:`day_bar_availability` (per-day facts for the AM-6 matrix in
calendar.py).

AM-9 (cn_a federation): the ClickHouse leg supplies T-1 history, the network
leg (first available non-clickhouse loader of the a_share chain, tencent in
production) supplies the current day; frames merge CH-priority.  Readiness is
judged on the MERGED frame, never the CH frame alone (CH is T-1 caliber —
judging on it would false-alarm NOT_READY every trading day).  The CH leg
bypasses ``clickhouse.DataLoader.fetch``: its internal federation calls
``resolve_loader("a_share")`` (clickhouse.py:296), which resolves back to
itself whenever CH is healthy and recurses until RecursionError degrades the
fetch to a CH-only frame (measured: ~490 wasted health checks, no current-day
bar).  The loader registry is never modified (import-only, VD-2).

Production prices must be raw: the existing registry's frame/source caliber
is checked before matching or merging. Adjusted and unknown network frames
are refused, including A-share qfq fallback frames; a matching timestamp does
not make them compatible with a raw-price cash ledger. Explicit injected
clients/loaders are trusted test or embedding inputs and must supply raw bars.
The ClickHouse adapter selects the raw OHLC columns explicitly.

Determinism (R1-1): NO clock is read — every date is injected, so the CH UTC
vs host CST 8h skew cannot leak into verdicts.  Zero side effects: no file
writes, network only to market-data sources; CH credentials come solely from
the existing ``CLICKHOUSE_*`` env config (zero-credential red line).

pt-v1.2 ``interval="5m"`` (T3/T4): the DAILY leg above is fetched unchanged
(K=120 lookback, valuation, price-limit bands, corporate actions) and exactly
ONE extra ranged 5m call covers the ORDER symbols — never one call per day and
never one call per position (T1: the provider allows 2 stk_mins calls/day, the
Tushare loader loops per code, and a refused call still burns the budget, so a
whole-universe request makes any two-symbol account unadvanceable).  The 5m
request end is ``to_date + 1 day`` because the provider's end
bound is exclusive at midnight.  Each symbol-day is split by the cn_a session
clock (:func:`calendar.classify_cn_a_session_label`): the 09:30 opening
auction print is dropped silently, an auction-window label is dropped and
reported as an ``auction_window`` event source, and the continuous bars are
assembled into ONE session bar (D1: open = first bar's open, high/low = extremes,
close = last bar's close, volume = sum).  Zero continuous bars on a
calendar-open day is a ``halted`` candidate; zero for the whole universe is
``PAPER_DATA_NOT_READY`` (D6).  A symbol with a daily bar but no 5m session
bar is a provider omission (``stk_mins`` quota or permission) ONLY when the
provider returned no row for it at all, and is reported as
``PAPER_DATA_NOT_READY`` naming it — a provider error must never be read as
a halt.  A symbol whose only 5m row is the 09:30 opening-auction print is a
halt candidate instead: the provider served the symbol, the exchange simply
had no continuous session (N3).  Unsupported instruments (ETFs, funds,
indices) are rejected by the tool before the fetch
(``data_5m.is_supported_five_minute_symbol``).
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Protocol

import numpy as np
import pandas as pd

from backtest.loaders.registry import frame_caliber, resolve_loader

from . import state_hash
from .data_5m import FiveMinuteFacts, SessionBar, fetch_five_minute
from .data_readiness import (
    NOT_READY_CODE,  # noqa: F401 — re-exported for callers that import it here
    ReadinessVerdict,
    _assess_five_minute_readiness,  # noqa: F401 — re-exported for existing callers
    _normalize_day,
    assess_readiness,
    day_bar_availability,
)
from .schema import DEFAULT_INTERVAL, INTERVALS, DataProvenance

if TYPE_CHECKING:
    from .schema import AccountState, Order

logger = logging.getLogger(__name__)

__all__ = [
    "LOOKBACK_CALENDAR_SPAN_DAYS",
    "LOOKBACK_TRADING_DAYS",
    "MARKET_LOADER_KEYS",
    "ClickHouseBarsClient",
    "CnABarsClient",
    "MarketDataResult",
    "ReadinessVerdict",
    "SessionBar",
    "SymbolData",
    "assess_readiness",
    "day_bar_availability",
    "default_ch_client",
    "fetch_market_data",
    "symbols_for_request",
]

MARKET_LOADER_KEYS: dict[str, str] = {
    "cn_a": "a_share",
    "hk": "hk_equity",
    "us": "us_equity",
}

#: K — frozen lookback in TRADING days (VD-6/B3 Step 2 terminal value).
LOOKBACK_TRADING_DAYS = 120

# Calendar span fetched to guarantee K trading bars before from_date even
# across holiday clusters: ceil(120×7/5)=168 + 32 slack.  _trim_window cuts
# back to exactly K, so the span never leaks into the served snapshot.
LOOKBACK_CALENDAR_SPAN_DAYS = 200

OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
_PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")

_CN_A_MARKET = "cn_a"
_CLICKHOUSE_LOADER_NAME = "clickhouse"

#: The only loader with a measured ``stk_mins`` leg.  The a_share daily chain
#: head (tencent) is wrapped as ``TencentRawLoader``, which refuses every
#: interval but ``1D`` — sharing that instance would make every 5m step a
#: permanent data-not-ready.  The 5m leg therefore resolves its own loader.
_FIVE_MINUTE_LOADER_NAME = "tushare"

# Sentinel distinguishing "not injected" from an explicit None.
_AUTO = object()


def _empty_frame() -> pd.DataFrame:
    columns = {column: pd.Series(dtype="float64") for column in OHLCV_COLUMNS}
    return pd.DataFrame(columns, index=pd.DatetimeIndex([], name="trade_date"))


def _canonical_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    # Canonical shape: tz-naive date DatetimeIndex (day-bar semantics: trading
    # day D stamped midnight), exactly OHLCV_COLUMNS (vol→volume, missing
    # NaN-filled), ascending, de-duplicated (keep last).
    if frame is None or len(frame) == 0:
        return _empty_frame()
    df = frame.copy()
    if "trade_date" in df.columns:
        df = df.set_index(pd.to_datetime(df["trade_date"]))
    index = pd.DatetimeIndex(df.index)
    df.index = (index.tz_localize(None) if index.tz is not None else index).normalize()
    df.index.name = "trade_date"
    if "vol" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"vol": "volume"})
    for column in OHLCV_COLUMNS:
        if column not in df.columns:
            df[column] = float("nan")
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df[list(OHLCV_COLUMNS)]
    return df[~df.index.duplicated(keep="last")].sort_index()


def _max_as_of(frames: Mapping[str, pd.DataFrame]) -> str | None:
    stamps = [
        pd.Timestamp(f.index.max()).strftime("%Y-%m-%d")
        for f in frames.values() if f is not None and not f.empty
    ]
    return max(stamps) if stamps else None


def _trim_window(frame: pd.DataFrame, from_date: str, to_date: str) -> pd.DataFrame:
    # Freeze the served window: the last K trading bars before from_date
    # (VD-6/B3) plus [from_date, to_date]; later bars never enter the snapshot.
    if frame.empty:
        return frame
    start = pd.Timestamp(from_date)
    end = pd.Timestamp(to_date)
    before = frame[frame.index < start]
    if len(before) > LOOKBACK_TRADING_DAYS:
        before = before.iloc[-LOOKBACK_TRADING_DAYS:]
    in_range = frame[(frame.index >= start) & (frame.index <= end)]
    if before.empty:
        return in_range
    if in_range.empty:
        return before
    return pd.concat([before, in_range]).sort_index()


def _untradable_dates(frame: pd.DataFrame) -> tuple[str, ...]:
    # R-V3 price sanity gate: non-positive/NaN OHLC bars must never reach
    # matching (cn_a additive-qfq old levels can go negative).  The Step 3
    # engine rejects that symbol's orders on these dates (frozen-vocabulary
    # mapping is the engine's call; this layer only flags, never crashes).
    if frame.empty:
        return ()
    prices = frame[list(_PRICE_COLUMNS)]
    bad = (~np.isfinite(prices)).any(axis=1) | (prices <= 0).any(axis=1)
    return tuple(day.strftime("%Y-%m-%d") for day in frame.index[bad])


def _valuation(frame: pd.DataFrame) -> tuple[float | None, str, bool]:
    # Carry-forward valuation = last usable positive close in the window (B3);
    # zero bars — or no positive close — falls back to avg_cost + warning.
    closes = frame["close"].dropna() if not frame.empty else pd.Series(dtype="float64")
    positives = closes[np.isfinite(closes) & (closes > 0)]
    if positives.empty:
        return None, "avg_cost", True
    return float(positives.iloc[-1]), "last_close", False


class CnABarsClient(Protocol):
    """Narrow injectable interface for the cn_a CH history leg."""

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Rows ``trade_date, open, high, low, close, vol`` (empty = no data)."""
        ...


class ClickHouseBarsClient:
    """CH bar-leg adapter over an INJECTED connector (limits_cn_a.py precedent).

    Narrow explicit SELECT (no ``SELECT *``); raw ``close`` (NOT ``close_hfq``)
    per the module-docstring caliber facts.
    """

    def __init__(self, connector: Any) -> None:
        self._connector = connector

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        sql = (
            "SELECT trade_date, open, high, low, close, vol FROM stk_factor_pro "
            "WHERE ts_code = {ts_code:String} AND trade_date >= {start_date:String} "
            "AND trade_date <= {end_date:String} ORDER BY trade_date"
        )
        params = {"param_ts_code": ts_code, "param_start_date": start_date, "param_end_date": end_date}
        return self._connector.query(sql, params=params)


def default_ch_client() -> CnABarsClient | None:
    """CH bar client from the existing ``CLICKHOUSE_*`` env config, or None
    when unreachable — the cn_a path then degrades to the network leg alone."""
    try:
        from src.clickhouse_connector import ClickHouseConnector
        from src.config.accessor import get_env_config

        cfg = get_env_config().data
        connector = ClickHouseConnector(
            host=cfg.clickhouse_host or None, port=cfg.clickhouse_port or None,
            user=cfg.clickhouse_user or None, password=cfg.clickhouse_password or None,
            database=cfg.clickhouse_database or None,
        )
        # Probe with an AUTHENTICATED SELECT 1, not connector.health_check():
        # health_check sends its probe with no credentials, so it 403s against
        # a password-protected server even when the configured credentials are
        # valid (observed live on the dev CH via SSH tunnel, 2026-10-19).
        connector.query("SELECT 1")
        return ClickHouseBarsClient(connector)
    except Exception as exc:  # noqa: BLE001 — unreachable CH degrades, never crashes
        logger.debug("paper_trade CH bar client unavailable: %s", exc)
        return None


def _resolve_network_loader(chain_key: str, exclude: frozenset[str] = frozenset()) -> Any | None:
    # First raw-capable loader of the chain, skipping excluded names. The
    # registry's resolve_loader cannot exclude the chain head, and cn_a must
    # exclude clickhouse (recursion — module docstring).
    from backtest.loaders.base import NoAvailableSourceError
    from backtest.loaders.registry import FALLBACK_CHAINS, LOADER_REGISTRY, price_caliber

    try:
        head = resolve_loader(chain_key)
    except NoAvailableSourceError:
        return None
    if head.name == "tencent":
        from .raw_loader import TencentRawLoader
        return TencentRawLoader()
    if head.name not in exclude and price_caliber(head.name, chain_key) == "raw":
        return head
    for name in FALLBACK_CHAINS.get(chain_key, []):
        if name in exclude or name not in LOADER_REGISTRY:
            continue
        try:
            loader = LOADER_REGISTRY[name]()
            if (loader.name == "tencent" or price_caliber(loader.name, chain_key) == "raw") and loader.is_available():
                if loader.name == "tencent":
                    from .raw_loader import TencentRawLoader
                    return TencentRawLoader()
                return loader
        except Exception:  # noqa: BLE001 — unavailable candidates keep the walk going
            continue
    return None


def _fetch_leg(
    loader: Any, symbols: tuple[str, ...], start_date: str, end_date: str, warnings: list[str],
    *, production_market: str | None = None,
) -> dict[str, pd.DataFrame]:
    # One batch fetch over the sorted symbol list (VD-10); failures degrade
    # to an empty leg with a structured warning, never a crash.
    if not symbols:
        return {}
    try:
        served = loader.fetch(list(symbols), start_date, end_date, interval="1D")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"network fetch ({loader.name}) failed: {type(exc).__name__}")
        return {}
    frames = {}
    for symbol in symbols:
        if production_market is not None:
            caliber = frame_caliber(served.get(symbol), loader.name, production_market, symbol)
            if caliber != "raw":
                warnings.append(
                    f"paper matching requires raw prices for {symbol}; "
                    f"{loader.name} supplied {caliber}; frame rejected"
                )
                continue
        frame = _canonical_frame(served.get(symbol))
        if not frame.empty:
            frames[symbol] = frame
    return frames


@dataclass(frozen=True, eq=False)
class SymbolData:
    """One symbol's served window (eq=False: DataFrame fields are not ==-safe)."""

    symbol: str
    frame: pd.DataFrame
    bar_dates: frozenset[str] = frozenset()
    untradable_dates: tuple[str, ...] = ()  # R-V3 flagged dates, ascending
    valuation_price: float | None = None  # None ⇒ value at avg_cost
    valuation_basis: str = "last_close"
    #: Day -> continuous 5m bars (empty for interval="1d"); for a single-day
    #: orders-mode step this is exactly the target day's continuous bars.
    bars_5m: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    #: Day -> assembled session bar (the D1 matched bar), interval="5m" only.
    session_bars: Mapping[str, SessionBar] = field(default_factory=dict)
    #: The TARGET day's session bar (``to_date``), or None when it has none.
    session_bar: SessionBar | None = None
    #: Day -> auction-window labels excluded from matching (T4 events).
    auction_labels: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Days with at least one 5m row of ANY kind, the 09:30 opening-auction
    #: print included.  Distinguishes a halt (rows, no continuous bar) from a
    #: provider omission (no row at all) — N3.
    five_minute_days: frozenset[str] = frozenset()

    def has_bar(self, day: str) -> bool:
        return day in self.bar_dates

    def has_session_bar(self, day: str) -> bool:
        return day in self.session_bars

    def has_five_minute_rows(self, day: str) -> bool:
        return day in self.five_minute_days


@dataclass(frozen=True, eq=False)
class MarketDataResult:
    """Frozen-order fetch result (VD-10): ``symbols`` sorted, ``data`` keyed in
    the same order; ``provenance`` is the AM-9 merged-frame record."""

    market: str
    from_date: str
    to_date: str
    symbols: tuple[str, ...]
    data: Mapping[str, SymbolData] = field(default_factory=dict)
    provenance: DataProvenance = field(default_factory=lambda: DataProvenance(source=""))
    warnings: tuple[str, ...] = ()
    #: "1d" (frozen pt-v1.1 path) or "5m" (pt-v1.2 cn_a session path).
    interval: str = DEFAULT_INTERVAL
    #: D3 bar fingerprint over the bars actually served: the continuous 5m
    #: bars when a 5m step orders symbols, the day bars otherwise (a
    #: pure-valuation 5m step issues no 5m request and is valued on them).
    bar_fingerprint: str = ""
    #: Day -> symbols whose daily bar and 5m session bar disagree on whether
    #: the symbol traded (a provider fault, never a halt: D6 fail-closed).
    five_minute_contradiction: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Symbols the 5m leg covers — the ORDER symbols in orders mode (the daily
    #: leg values positions), the declared universe in strategy mode.  Empty
    #: for a pure-valuation step, which issues no 5m request at all.
    five_minute_symbols: tuple[str, ...] = ()
    #: Why the 5m leg produced no data when the cause is the LOADER (none
    #: available, or the fetch raised), never when the provider simply omitted
    #: a halted day.  Readiness surfaces this verbatim instead of blaming the
    #: provider's quota for a source that cannot serve 5m at all.
    five_minute_error: str = ""
    #: Loader that served the 5m leg (empty when no 5m request was made).  It
    #: stays OFF the wire — the account-layer step.json records it, so the
    #: audit trail names the 5m source without changing the frozen response.
    five_minute_source: str = ""


def symbols_for_request(
    account_state: "AccountState", orders: "tuple[Order, ...] | None"
) -> tuple[str, ...]:
    """Fetch universe = positions ∪ orders, sorted (VD-10); the zero-order
    pure-valuation path yields the position symbols alone."""
    universe = {position.symbol for position in account_state.positions}
    for order in orders or ():
        universe.add(order.symbol)
    return tuple(sorted(universe))


def _resolve_five_minute_loader(loader: Any) -> Any | None:
    """Return the loader that serves ``interval="5m"``, or ``None`` when none can.

    An injected loader is honoured verbatim — tests and embedders own their
    source, and substituting another one would hide the failure.  Only the
    ``_AUTO`` sentinel resolves the Tushare ``stk_mins`` loader; the daily
    chain is deliberately never consulted for 5m.
    """
    if loader is not _AUTO:
        return loader
    try:
        from backtest.loaders.tushare import DataLoader

        candidate = DataLoader()
        return candidate if candidate.is_available() else None
    except Exception:  # noqa: BLE001 — an unavailable 5m source is data-not-ready
        return None


def fetch_market_data(
    market: str,
    symbols: Any,
    from_date: str,
    to_date: str,
    *,
    loader: Any = _AUTO,
    ch_client: Any = _AUTO,
    interval: str = DEFAULT_INTERVAL,
    five_minute_symbols: Iterable[str] | None = None,
) -> MarketDataResult:
    """Fetch the frozen window for every symbol; assemble merged provenance.

    ``loader`` injects the network leg (cn_a: clickhouse-named loaders are
    refused — recursion guard; hk/us: the single leg); ``ch_client`` injects
    the cn_a CH leg (``None`` forces network-only).  ``interval="1d"`` is the
    frozen pt-v1.1 path and never issues a 5m request; ``interval="5m"`` keeps
    the daily leg (K=120 lookback, valuation, limits, corporate actions) and
    adds exactly ONE ranged 5m fetch (T1 quota: the provider allows 2 calls/day,
    so a per-day loop is forbidden, and the Tushare loader loops per symbol —
    a whole-universe request would burn the budget on the first account with
    two names).  ``five_minute_symbols`` therefore narrows that ONE request to
    the symbols whose session bar is actually matched (orders mode: the order
    symbols); ``None`` keeps the legacy whole-universe request.  ValueError
    for an unknown market, bad dates, an unknown interval, a non-cn_a 5m
    request or a clickhouse injection → in-band INVALID_REQUEST (T6).
    """
    if market not in MARKET_LOADER_KEYS:
        raise ValueError(f"unknown market for paper data fetch: {market!r}")
    if interval not in INTERVALS:
        raise ValueError(f"unknown interval for paper data fetch: {interval!r}")
    if interval == "5m" and market != _CN_A_MARKET:
        raise ValueError("interval '5m' is cn_a-only in pt-v1.2")
    start = _normalize_day(from_date)
    end = _normalize_day(to_date)
    if start > end:
        raise ValueError(f"from_date ({start}) > to_date ({end})")
    ordered = tuple(sorted({str(symbol) for symbol in symbols}))
    ordered_five = (
        ordered
        if five_minute_symbols is None
        else tuple(dict.fromkeys(str(symbol) for symbol in five_minute_symbols))
    )
    window_start = (
        dt.date.fromisoformat(start) - dt.timedelta(days=LOOKBACK_CALENDAR_SPAN_DAYS)
    ).isoformat()

    warnings: list[str] = []
    if market == _CN_A_MARKET:
        frames, provenance = _fetch_cn_a(
            ordered, window_start, end, loader=loader, ch_client=ch_client, warnings=warnings
        )
    else:
        frames, provenance = _fetch_single_leg(
            market, ordered, window_start, end, loader=loader, warnings=warnings
        )

    five = FiveMinuteFacts()
    five_minute_error = ""
    five_minute_source = ""
    if interval == "5m" and ordered_five:
        five_loader = _resolve_five_minute_loader(loader)
        if five_loader is None:
            five_minute_error = (
                "5m data: no available 5m loader; interval 5m requires the Tushare "
                "stk_mins source (daily sources such as tencent serve 1D only)")
            warnings.append(five_minute_error)
            five = FiveMinuteFacts(
                bar_fingerprint=state_hash.state_hash([]), fetch_failed=True,
                missing_symbols=ordered_five)
        else:
            five = fetch_five_minute(
                ordered_five, start, end, loader=five_loader, warnings=warnings)
            five_minute_source = str(getattr(five_loader, "name", ""))
            if five.fetch_failed:
                five_minute_error = five.failure_reason or (
                    "5m data: the 5m fetch through "
                    f"{getattr(five_loader, 'name', 'the loader')!r} failed; "
                    "the step is data-not-ready, retry later")

    data: dict[str, SymbolData] = {}
    for symbol in ordered:
        frame = _trim_window(frames.get(symbol, _empty_frame()), start, end)
        untradable = _untradable_dates(frame)
        price, basis, needs_warning = _valuation(frame)
        if untradable:
            warnings.append(
                f"price sanity: {symbol} has {len(untradable)} invalid price bar(s) in the fetch "
                f"window ({untradable[0]}..{untradable[-1]}); orders on those days are rejected"
            )
        if needs_warning:
            warnings.append(f"valuation: {symbol} has no usable positive close in the fetch window; positions value at avg_cost")
        bars_5m, session_bars = five.for_symbol(symbol)
        data[symbol] = SymbolData(
            symbol=symbol, frame=frame,
            bar_dates=frozenset(day.strftime("%Y-%m-%d") for day in frame.index),
            untradable_dates=untradable, valuation_price=price, valuation_basis=basis,
            bars_5m=bars_5m, session_bars=session_bars,
            session_bar=session_bars.get(end),
            auction_labels=five.auction_by_symbol.get(symbol, {}),
            five_minute_days=frozenset(five.observed_days_by_symbol.get(symbol, ())),
        )

    omitted_5m = tuple(
        symbol for symbol in five.missing_symbols
        if symbol in data and data[symbol].has_bar(end)
    )
    if omitted_5m:
        warnings.append(
            f"5m data: provider omitted the 5m leg for {', '.join(omitted_5m)} even though the "
            "daily bar exists; stk_mins quota or permission likely; retry after the quota window")

    # D3 covers the bars that actually produced this step's output.  With 5m
    # order symbols that is the continuous 5m leg; a pure-valuation 5m step
    # issues no 5m request at all, so its NAV comes from the daily leg and the
    # daily digest is the honest one (otherwise every such step shares the
    # empty-tape hash and the fingerprint cannot tell two days apart).
    bar_fingerprint = (
        five.bar_fingerprint if interval == "5m" and ordered_five
        else _daily_bar_fingerprint(data, ordered, start, end)
    )
    return MarketDataResult(
        market=market, from_date=start, to_date=end, symbols=ordered,
        data=data, provenance=provenance, warnings=tuple(warnings),
        interval=interval, bar_fingerprint=bar_fingerprint,
        five_minute_contradiction=_five_minute_contradictions(
            data, ordered_five, start, end, interval, five),
        five_minute_symbols=ordered_five,
        five_minute_error=five_minute_error,
        five_minute_source=five_minute_source,
    )


def _days_in_range(from_date: str, to_date: str) -> tuple[str, ...]:
    start = dt.date.fromisoformat(from_date)
    end = dt.date.fromisoformat(to_date)
    return tuple(
        (start + dt.timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    )


def _finite_float(value: Any) -> float:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else 0.0


def _daily_bar_fingerprint(
    data: Mapping[str, SymbolData],
    symbols: tuple[str, ...],
    from_date: str,
    to_date: str,
) -> str:
    # D3 for interval="1d": the day bars actually served in [from, to], sorted
    # by (symbol, date) so input order cannot change the digest.  Rows are
    # [symbol, "YYYY-MM-DD", open, high, low, close, volume] with finite
    # floats (a non-finite cell, e.g. a missing volume, canonicalizes as 0.0
    # instead of raising inside the JCS serializer).
    start = pd.Timestamp(from_date)
    end = pd.Timestamp(to_date)
    payload: list[list[Any]] = []
    for symbol in sorted(symbols):
        sym_data = data.get(symbol)
        if sym_data is None or sym_data.frame.empty:
            continue
        window = sym_data.frame[(sym_data.frame.index >= start) & (sym_data.frame.index <= end)]
        for timestamp, row in window.iterrows():
            payload.append([
                symbol, timestamp.strftime("%Y-%m-%d"),
                _finite_float(row["open"]), _finite_float(row["high"]),
                _finite_float(row["low"]), _finite_float(row["close"]),
                _finite_float(row["volume"]),
            ])
    return state_hash.state_hash(payload)


def _five_minute_leg_mismatch(sym_data: SymbolData, day: str) -> bool:
    """True when the daily and 5m legs disagree in a way a halt cannot explain.

    A daily bar with no continuous 5m bar is a provider omission only when the
    symbol produced NO 5m row that day.  A symbol the provider DID serve (even
    just the 09:30 opening-auction print) is a halt candidate: the exchange had
    no continuous session, the provider did not fail (N3).  A session bar with
    no daily bar is a mismatch in both directions.
    """
    has_daily = sym_data.has_bar(day)
    has_session = sym_data.has_session_bar(day)
    if has_daily == has_session:
        return False
    return has_session or not sym_data.has_five_minute_rows(day)


def _five_minute_contradictions(
    data: Mapping[str, SymbolData],
    symbols: tuple[str, ...],
    from_date: str,
    to_date: str,
    interval: str,
    five: FiveMinuteFacts,
) -> dict[str, tuple[str, ...]]:
    # A daily bar with no 5m session bar (or the reverse) cannot be a halt when
    # the provider served no 5m row at all for that symbol: Tushare omits
    # suspended days from BOTH endpoints.  It is a provider / federation fault,
    # so the day fails closed as data-not-ready rather than reading a provider
    # error as "halted" (D6).
    if interval != "5m" or five.fetch_failed or not symbols:
        return {}
    contradictions: dict[str, tuple[str, ...]] = {}
    for day in _days_in_range(from_date, to_date):
        mismatched = tuple(sorted(
            symbol for symbol in symbols
            if symbol in data and _five_minute_leg_mismatch(data[symbol], day)
        ))
        if mismatched:
            contradictions[day] = mismatched
    return contradictions


def _fetch_cn_a(
    symbols: tuple[str, ...],
    window_start: str,
    to_date: str,
    *,
    loader: Any,
    ch_client: Any,
    warnings: list[str],
) -> tuple[dict[str, pd.DataFrame], DataProvenance]:
    # Explicit two-leg federation (AM-9): CH history + network current day,
    # merged CH-priority.  Legs are fetched sequentially over sorted symbols
    # (deterministic; no ordering hazard to freeze).
    if loader is not _AUTO and getattr(loader, "name", "") == _CLICKHOUSE_LOADER_NAME:
        raise ValueError(
            "paper data fetch refuses a clickhouse-named loader injection: its internal federation "
            "leg recurses into resolve_loader (clickhouse.py:296); federate via ch_client instead"
        )
    client: CnABarsClient | None = default_ch_client() if ch_client is _AUTO else ch_client
    ch_frames: dict[str, pd.DataFrame] = {}
    if client is not None:
        for symbol in symbols:
            try:
                frame = _canonical_frame(client.get_bars(symbol, window_start, to_date))
            except Exception as exc:  # noqa: BLE001 — leg failure degrades, never crashes
                warnings.append(f"clickhouse leg failed for {symbol}: {type(exc).__name__}")
                continue
            if not frame.empty:
                ch_frames[symbol] = frame

    net_loader = (
        loader
        if loader is not _AUTO
        else _resolve_network_loader(
            MARKET_LOADER_KEYS[_CN_A_MARKET], exclude=frozenset({_CLICKHOUSE_LOADER_NAME})
        )
    )
    net_frames = (
        _fetch_leg(net_loader, symbols, window_start, to_date, warnings,
                   production_market=MARKET_LOADER_KEYS[_CN_A_MARKET] if loader is _AUTO else None)
        if net_loader is not None
        else {}
    )
    if client is None and net_loader is None:
        warnings.append("no available data source for market 'cn_a'; frames are empty")

    merged: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        ch_frame = ch_frames.get(symbol)
        net_frame = net_frames.get(symbol)
        if ch_frame is not None and net_frame is not None:
            merged[symbol] = ch_frame.combine_first(net_frame)  # CH priority (AM-9)
        elif ch_frame is not None:
            merged[symbol] = ch_frame
        elif net_frame is not None:
            merged[symbol] = net_frame

    ch_as_of = _max_as_of(ch_frames)
    network_as_of = _max_as_of(net_frames)
    net_name = str(getattr(net_loader, "name", "network"))
    if ch_as_of is not None and network_as_of is not None:
        source = f"clickhouse+{net_name}(merged)"
    elif ch_as_of is not None:
        source = "clickhouse"
    else:
        source = net_name if network_as_of is not None else "unavailable"
    provenance = DataProvenance(
        source=source, bars_as_of=_max_as_of(merged), ch_as_of=ch_as_of, network_as_of=network_as_of
    )
    return merged, provenance


def _fetch_single_leg(
    market: str,
    symbols: tuple[str, ...],
    window_start: str,
    to_date: str,
    *,
    loader: Any,
    warnings: list[str],
) -> tuple[dict[str, pd.DataFrame], DataProvenance]:
    # hk/us single leg through the registry chain (resolve_loader wiring).
    net_loader = (
        loader if loader is not _AUTO else _resolve_network_loader(MARKET_LOADER_KEYS[market])
    )
    if net_loader is None:
        warnings.append(f"no available data source for market {market!r}; frames are empty")
        return {}, DataProvenance(source="unavailable")
    frames = _fetch_leg(net_loader, symbols, window_start, to_date, warnings,
                        production_market=MARKET_LOADER_KEYS[market] if loader is _AUTO else None)
    as_of = _max_as_of(frames)
    provenance = DataProvenance(
        source=str(getattr(net_loader, "name", "network")) if frames else "unavailable",
        bars_as_of=as_of,
        network_as_of=as_of,
    )
    return frames, provenance
