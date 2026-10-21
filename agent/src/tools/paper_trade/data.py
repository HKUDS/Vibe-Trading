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
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Protocol

import numpy as np
import pandas as pd

from backtest.loaders.registry import frame_caliber, resolve_loader

from .schema import DataProvenance

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

#: Frozen in-band envelope code (schema.ERROR_CODES member) for target-day
#: all-market zero bar (AM-5/AM-9).
NOT_READY_CODE = "PAPER_DATA_NOT_READY"

_CN_A_MARKET = "cn_a"
_CLICKHOUSE_LOADER_NAME = "clickhouse"

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


def _normalize_day(value: str) -> str:
    return dt.date.fromisoformat(str(value).strip()).isoformat()


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

    def has_bar(self, day: str) -> bool:
        return day in self.bar_dates


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


@dataclass(frozen=True, slots=True)
class ReadinessVerdict:
    """Target-day readiness (AM-9).  ``ready=False`` carries the frozen in-band
    envelope material (AM-5) — this layer never raises for data-not-ready."""

    ready: bool
    code: str | None = None
    message: str | None = None


def symbols_for_request(
    account_state: "AccountState", orders: "tuple[Order, ...] | None"
) -> tuple[str, ...]:
    """Fetch universe = positions ∪ orders, sorted (VD-10); the zero-order
    pure-valuation path yields the position symbols alone."""
    universe = {position.symbol for position in account_state.positions}
    for order in orders or ():
        universe.add(order.symbol)
    return tuple(sorted(universe))


def fetch_market_data(
    market: str,
    symbols: Any,
    from_date: str,
    to_date: str,
    *,
    loader: Any = _AUTO,
    ch_client: Any = _AUTO,
) -> MarketDataResult:
    """Fetch the frozen window for every symbol; assemble merged provenance.

    ``loader`` injects the network leg (cn_a: clickhouse-named loaders are
    refused — recursion guard; hk/us: the single leg); ``ch_client`` injects
    the cn_a CH leg (``None`` forces network-only).  ValueError for an unknown
    market, bad dates or a clickhouse injection → in-band INVALID_REQUEST (T6).
    """
    if market not in MARKET_LOADER_KEYS:
        raise ValueError(f"unknown market for paper data fetch: {market!r}")
    start = _normalize_day(from_date)
    end = _normalize_day(to_date)
    if start > end:
        raise ValueError(f"from_date ({start}) > to_date ({end})")
    ordered = tuple(sorted({str(symbol) for symbol in symbols}))
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
        data[symbol] = SymbolData(
            symbol=symbol, frame=frame,
            bar_dates=frozenset(day.strftime("%Y-%m-%d") for day in frame.index),
            untradable_dates=untradable, valuation_price=price, valuation_basis=basis,
        )
    return MarketDataResult(
        market=market, from_date=start, to_date=end, symbols=ordered,
        data=data, provenance=provenance, warnings=tuple(warnings),
    )


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


def assess_readiness(result: MarketDataResult, target_day: str) -> ReadinessVerdict:
    """Target-day readiness on the merged frame (AM-9), never on a leg alone.

    Ready when ANY served symbol carries the target-day bar (single-symbol
    absence is a suspended fact for the engine, AM-6③); all-market zero bar →
    the frozen PAPER_DATA_NOT_READY material (message follows the R1-4 example
    shape; deterministic English, no timestamps — VD-7).  An empty universe is
    vacuously ready.
    """
    day = _normalize_day(target_day)
    if result.symbols and not any(
        result.data[symbol].has_bar(day) for symbol in result.symbols
    ):
        ends = result.provenance.bars_as_of or "empty"
        message = f"target bar {day} not available from served sources ({result.provenance.source} frame ends {ends})"
        return ReadinessVerdict(ready=False, code=NOT_READY_CODE, message=message)
    return ReadinessVerdict(ready=True)


def day_bar_availability(result: MarketDataResult, dates: Any) -> dict[str, tuple[str, ...]]:
    # Per-day sorted tuple of symbols WITH a bar — the AM-6 matrix input
    # (dates: iterable of YYYY-MM-DD, e.g. hk_us_candidate_days output).
    availability: dict[str, tuple[str, ...]] = {}
    for raw in dates:
        day = _normalize_day(raw)
        availability[day] = tuple(s for s in result.symbols if result.data[s].has_bar(day))
    return availability
