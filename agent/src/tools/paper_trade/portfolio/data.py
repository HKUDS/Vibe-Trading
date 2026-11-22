"""Bucket-scoped data types, raw loading and all-bucket execution preflight."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias

from ..data_readiness import assess_readiness
from .models import DecimalString, Market
from .sessions import BucketSession, PortfolioSessionError, PortfolioSessions

if TYPE_CHECKING:
    from ..calendar import TradeCalendarClient
    from ..corporate_actions import CorporateActionPlan
    from ..data import MarketDataResult
    from ..data_readiness import ReadinessVerdict
    from ..engine import DayPlan
    from ..schema import DataProvenance

_SNAPSHOT_CALENDAR_MARKETS: Final = frozenset({"cn_a"})
_PRICE_COLUMNS: Final = ("open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One symbol's close within a dated market-data snapshot."""

    symbol: str
    close: DecimalString


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    """A separately provenanced planning, execution or valuation snapshot."""

    price_date: date
    source: str
    as_of: datetime
    bars: tuple[PriceBar, ...] = ()


@dataclass(frozen=True, slots=True)
class PriorMark:
    """An explicit historical close used when a market is closed."""

    symbol: str
    price_date: date
    close: DecimalString
    source: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class CalendarCoverage:
    """The cn_a snapshot-calendar verdict for one price date."""

    price_date: date
    is_open: bool
    source: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class BucketMarketData:
    """All data descriptors supplied for one portfolio bucket."""

    bucket_id: str
    market: Market
    price_date: date
    planning: DataSnapshot
    execution: DataSnapshot
    valuation: DataSnapshot
    prior_marks: tuple[PriorMark, ...] = ()
    calendar: CalendarCoverage | None = None


@dataclass(frozen=True, slots=True)
class TargetBarValuation:
    """Valuation from target-date bars for an open bucket."""

    snapshot: DataSnapshot
    kind: Literal["target_bars"] = "target_bars"


@dataclass(frozen=True, slots=True)
class PriorMarkValuation:
    """Valuation from explicit dated marks for a closed bucket."""

    marks: tuple[PriorMark, ...]
    kind: Literal["prior_marks"] = "prior_marks"


ValuationInput: TypeAlias = TargetBarValuation | PriorMarkValuation


@dataclass(frozen=True, slots=True)
class PreparedBucketData:
    """Validated data and matching eligibility for one bucket."""

    session: BucketSession
    planning: DataSnapshot
    execution: DataSnapshot | None
    valuation: ValuationInput

    @property
    def bucket_id(self) -> str:
        return self.session.bucket_id


@dataclass(frozen=True, slots=True)
class BucketPreflight:
    """One bucket's raw load plus every pre-match gate verdict and provenance."""

    prepared: PreparedBucketData
    market_data: "MarketDataResult"
    day_plan: tuple["DayPlan", ...]
    readiness: "ReadinessVerdict"
    corporate_actions: "CorporateActionPlan"
    calendar: CalendarCoverage | None
    provenance: "DataProvenance"

    @property
    def bucket_id(self) -> str:
        return self.prepared.bucket_id

    @property
    def market(self) -> Market:
        return self.prepared.session.market


@dataclass(frozen=True, slots=True)
class PreparedPortfolioData:
    """Prepared inputs with closed buckets excluded from matching."""

    buckets: tuple[PreparedBucketData, ...]
    #: Additive preflight journal; empty for descriptors prepared by hand.
    preflight: tuple[BucketPreflight, ...] = ()

    @property
    def matchable(self) -> tuple[PreparedBucketData, ...]:
        return tuple(bucket for bucket in self.buckets if bucket.session.matchable)

    @property
    def closed(self) -> tuple[PreparedBucketData, ...]:
        return tuple(bucket for bucket in self.buckets if not bucket.session.matchable)


def _validate_identity(session: BucketSession, data: BucketMarketData) -> None:
    mismatches = (
        (data.market != session.market, "market"),
        (data.price_date != session.price_date, "price_date"),
        (data.execution.price_date != session.price_date, "execution.price_date"),
        (data.valuation.price_date != session.price_date, "valuation.price_date"),
    )
    for mismatch, field in mismatches:
        if mismatch:
            raise PortfolioSessionError(
                reason="session_data_disagreement",
                path=f"market_data.{session.bucket_id}.{field}",
                bucket_id=session.bucket_id,
            )


def _validate_calendar(session: BucketSession, data: BucketMarketData) -> None:
    if session.market not in _SNAPSHOT_CALENDAR_MARKETS:
        return
    coverage = data.calendar
    if coverage is None:
        raise PortfolioSessionError(
            reason="missing_calendar_coverage",
            path=f"market_data.{session.bucket_id}.calendar",
            bucket_id=session.bucket_id,
        )
    if coverage.price_date != session.price_date or coverage.is_open != session.matchable:
        raise PortfolioSessionError(
            reason="session_data_disagreement",
            path=f"market_data.{session.bucket_id}.calendar",
            bucket_id=session.bucket_id,
        )


def _closed_marks(session: BucketSession, data: BucketMarketData) -> tuple[PriorMark, ...]:
    supplied: dict[str, PriorMark] = {}
    for mark in data.prior_marks:
        if mark.symbol in supplied:
            raise PortfolioSessionError(
                code="INVALID_REQUEST",
                reason="duplicate_prior_mark",
                path=f"market_data.{session.bucket_id}.prior_marks.{mark.symbol}",
                bucket_id=session.bucket_id,
            )
        supplied[mark.symbol] = mark
    marks: list[PriorMark] = []
    for symbol in session.position_symbols:
        mark = supplied.get(symbol)
        path = f"market_data.{session.bucket_id}.prior_marks.{symbol}"
        if mark is None:
            raise PortfolioSessionError(
                reason="missing_prior_mark", path=path, bucket_id=session.bucket_id
            )
        if mark.price_date >= session.price_date:
            raise PortfolioSessionError(
                reason="stale_prior_mark", path=path, bucket_id=session.bucket_id
            )
        marks.append(mark)
    return tuple(marks)


def _prepare_bucket(session: BucketSession, data: BucketMarketData) -> PreparedBucketData:
    _validate_identity(session, data)
    _validate_calendar(session, data)
    if session.matchable:
        if not data.execution.bars:
            raise PortfolioSessionError(
                reason="open_bucket_zero_target_bars",
                path=f"market_data.{session.bucket_id}.execution.bars",
                bucket_id=session.bucket_id,
            )
        if not data.valuation.bars:
            raise PortfolioSessionError(
                reason="open_bucket_zero_target_bars",
                path=f"market_data.{session.bucket_id}.valuation.bars",
                bucket_id=session.bucket_id,
            )
        return PreparedBucketData(
            session=session,
            planning=data.planning,
            execution=data.execution,
            valuation=TargetBarValuation(snapshot=data.valuation),
        )
    return PreparedBucketData(
        session=session,
        planning=data.planning,
        execution=None,
        valuation=PriorMarkValuation(marks=_closed_marks(session, data)),
    )


def prepare_portfolio_data(
    sessions: PortfolioSessions,
    market_data: tuple[BucketMarketData, ...],
) -> PreparedPortfolioData:
    """Attach open target bars or closed prior marks to session routing."""
    expected = {session.bucket_id for session in sessions.buckets}
    supplied: dict[str, BucketMarketData] = {}
    for data in market_data:
        if data.bucket_id not in expected:
            raise PortfolioSessionError(
                code="INVALID_REQUEST",
                reason="unknown_bucket_data",
                path=f"market_data.{data.bucket_id}.bucket_id",
                bucket_id=data.bucket_id,
            )
        if data.bucket_id in supplied:
            raise PortfolioSessionError(
                code="INVALID_REQUEST",
                reason="duplicate_bucket_data",
                path=f"market_data.{data.bucket_id}.bucket_id",
                bucket_id=data.bucket_id,
            )
        supplied[data.bucket_id] = data

    prepared: list[PreparedBucketData] = []
    for session in sessions.buckets:
        data = supplied.get(session.bucket_id)
        if data is None:
            raise PortfolioSessionError(
                code="INVALID_REQUEST",
                reason="missing_bucket_data",
                path=f"market_data.{session.bucket_id}",
                bucket_id=session.bucket_id,
            )
        prepared.append(_prepare_bucket(session, data))
    return PreparedPortfolioData(buckets=tuple(prepared))


class _InvalidPriceBar(ValueError):
    def __init__(self, symbol: str, field: str) -> None:
        self.symbol = symbol
        self.field = field
        super().__init__(f"{symbol}.{field}")


@dataclass(frozen=True, slots=True)
class _DetectorPosition:
    symbol: str
    qty: int = 0


def _price_text(value: Any, symbol: str, field: str) -> DecimalString:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise _InvalidPriceBar(symbol, field) from exc
    if not math.isfinite(numeric) or numeric <= 0:
        raise _InvalidPriceBar(symbol, field)
    text = format(Decimal(str(numeric)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _snapshot_as_of(bars_as_of: str | None, fallback: date) -> datetime:
    try:
        day = date.fromisoformat(str(bars_as_of)[:10]) if bars_as_of else fallback
    except ValueError:
        day = fallback
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _reject_adjusted_frames(
    session: BucketSession,
    result: "MarketDataResult",
) -> None:
    for symbol in result.symbols:
        item = result.data.get(symbol)
        if item is None:
            continue
        attrs = getattr(item.frame, "attrs", None)
        adjustment = attrs.get("adjustment") if isinstance(attrs, Mapping) else None
        if isinstance(adjustment, str) and adjustment not in ("", "raw", "na"):
            raise PortfolioSessionError(
                reason="adjusted_prices_rejected",
                path=f"market_data.{session.bucket_id}.frames.{symbol}",
                bucket_id=session.bucket_id,
                detail=f"{symbol} declares caliber {adjustment!r}; raw prices required",
            )


def _planning_bars(
    session: BucketSession,
    result: "MarketDataResult",
) -> tuple[tuple[PriceBar, ...], date]:
    target = session.price_date.isoformat()
    bars: list[PriceBar] = []
    dates: list[str] = []
    for symbol in result.symbols:
        item = result.data.get(symbol)
        if item is None or item.frame.empty:
            continue
        prior = item.frame[item.frame.index < target]
        if prior.empty:
            continue
        row = prior.iloc[-1]
        try:
            close = _price_text(row["close"], symbol, "close")
        except _InvalidPriceBar as exc:
            raise PortfolioSessionError(
                reason="nonfinite_price_bar",
                path=f"market_data.{session.bucket_id}.planning.{symbol}.{exc.field}",
                bucket_id=session.bucket_id,
            ) from exc
        bars.append(PriceBar(symbol=symbol, close=close))
        dates.append(prior.index[-1].strftime("%Y-%m-%d"))
    if result.symbols and not bars:
        raise PortfolioSessionError(
            reason="missing_planning_bars",
            path=f"market_data.{session.bucket_id}.planning",
            bucket_id=session.bucket_id,
        )
    return tuple(bars), date.fromisoformat(max(dates)) if dates else session.price_date


def _target_bars(
    session: BucketSession,
    result: "MarketDataResult",
) -> tuple[PriceBar, ...]:
    target = session.price_date.isoformat()
    bars: list[PriceBar] = []
    for symbol in result.symbols:
        item = result.data.get(symbol)
        if item is None or target not in item.bar_dates:
            continue
        row = item.frame.loc[[target]].iloc[0]
        for field in _PRICE_COLUMNS:
            try:
                _price_text(row[field], symbol, field)
            except _InvalidPriceBar as exc:
                raise PortfolioSessionError(
                    reason="nonfinite_price_bar",
                    path=f"market_data.{session.bucket_id}.target.{symbol}.{field}",
                    bucket_id=session.bucket_id,
                ) from exc
        bars.append(PriceBar(symbol=symbol, close=_price_text(row["close"], symbol, "close")))
    return tuple(bars)


def _prior_marks(
    session: BucketSession,
    result: "MarketDataResult",
    as_of: datetime,
) -> tuple[PriorMark, ...]:
    target = session.price_date.isoformat()
    marks: list[PriorMark] = []
    for symbol in session.position_symbols:
        item = result.data.get(symbol)
        prior = (
            item.frame[item.frame.index < target]
            if item is not None and not item.frame.empty
            else None
        )
        if prior is None or prior.empty:
            raise PortfolioSessionError(
                reason="missing_prior_mark",
                path=f"market_data.{session.bucket_id}.prior_marks.{symbol}",
                bucket_id=session.bucket_id,
            )
        row = prior.iloc[-1]
        try:
            close = _price_text(row["close"], symbol, "close")
        except _InvalidPriceBar as exc:
            raise PortfolioSessionError(
                reason="nonfinite_price_bar",
                path=f"market_data.{session.bucket_id}.prior_marks.{symbol}.{exc.field}",
                bucket_id=session.bucket_id,
            ) from exc
        marks.append(
            PriorMark(
                symbol=symbol,
                price_date=date.fromisoformat(prior.index[-1].strftime("%Y-%m-%d")),
                close=close,
                source=f"{result.provenance.source}:prior_mark",
                as_of=as_of,
            )
        )
    return tuple(marks)


def _calendar_coverage(
    session: BucketSession,
    calendar_client: "TradeCalendarClient | None",
) -> tuple[CalendarCoverage | None, Any]:
    if session.market not in _SNAPSHOT_CALENDAR_MARKETS:
        return None, None
    if calendar_client is None:
        raise PortfolioSessionError(
            reason="missing_calendar_coverage",
            path=f"market_data.{session.bucket_id}.calendar",
            bucket_id=session.bucket_id,
        )
    from ..calendar import CalendarUnavailableError, snapshot_calendar

    day = session.price_date.isoformat()
    try:
        snapshot = snapshot_calendar(calendar_client, day, day)
    except CalendarUnavailableError as exc:
        raise PortfolioSessionError(
            reason="calendar_unavailable",
            path=f"market_data.{session.bucket_id}.calendar",
            bucket_id=session.bucket_id,
            detail=str(exc),
        ) from exc
    is_open: bool | None = None
    for row in snapshot.frame.to_dict("records"):
        if str(row.get("cal_date"))[:10] == day:
            is_open = bool(int(row["is_open"]))
            break
    if is_open is None:
        raise PortfolioSessionError(
            reason="calendar_unavailable",
            path=f"market_data.{session.bucket_id}.calendar",
            bucket_id=session.bucket_id,
        )
    coverage = CalendarCoverage(
        price_date=session.price_date,
        is_open=is_open,
        source="snapshot_calendar",
        as_of=_snapshot_as_of(None, session.price_date),
    )
    return coverage, snapshot


def _fetch_bucket(
    session: BucketSession,
    symbols: tuple[str, ...],
    *,
    loaders: Mapping[Market, Any] | None,
    ch_clients: Mapping[Market, Any] | None,
) -> tuple["MarketDataResult", Any]:
    from ..data import fetch_market_data

    kwargs: dict[str, Any] = {}
    loader = None
    if loaders is not None:
        if session.market not in loaders:
            raise PortfolioSessionError(
                reason="missing_loader",
                path=f"loaders.{session.market}",
                bucket_id=session.bucket_id,
            )
        loader = loaders[session.market]
        kwargs["loader"] = loader
    if ch_clients is not None:
        kwargs["ch_client"] = ch_clients.get(session.market)
    day = session.price_date.isoformat()
    try:
        result = fetch_market_data(session.market, symbols, day, day, **kwargs)
    except ValueError as exc:
        raise PortfolioSessionError(
            code="INVALID_REQUEST",
            reason="market_data_request",
            path=f"market_data.{session.bucket_id}",
            bucket_id=session.bucket_id,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — provider faults are retryable data facts
        raise PortfolioSessionError(
            reason="market_data_fetch_failed",
            path=f"market_data.{session.bucket_id}",
            bucket_id=session.bucket_id,
            detail=type(exc).__name__,
        ) from exc
    _reject_adjusted_frames(session, result)
    return result, loader


def _day_plan(
    session: BucketSession,
    result: "MarketDataResult",
    calendar_snapshot: Any,
) -> tuple["DayPlan", ...]:
    from ..engine import build_day_plan

    day = session.price_date.isoformat()
    return tuple(build_day_plan(session.market, day, day, result, calendar_snapshot))


def _corporate_actions(
    session: BucketSession,
    result: "MarketDataResult",
    day_plan: tuple["DayPlan", ...],
    positions: Sequence[Any] | None,
) -> "CorporateActionPlan":
    from ..corporate_actions import build_plan

    matching_days = (
        tuple(entry.date for entry in day_plan if entry.skip_reason is None)
        if session.matchable else ()
    )
    detector_positions = (
        tuple(positions)
        if positions is not None
        else tuple(_DetectorPosition(symbol) for symbol in session.position_symbols)
    )
    plan = build_plan(result, matching_days, detector_positions)
    event_days = sorted(set(plan.clean_by_day) | set(plan.unresolved_by_day))
    if not event_days:
        return plan
    day = event_days[0]
    symbols = sorted(
        {event.symbol for event in plan.clean_by_day.get(day, ())}
        | set(plan.unresolved_by_day.get(day, ()))
    )
    raise PortfolioSessionError(
        reason="corporate_action_unresolved",
        path=f"market_data.{session.bucket_id}.corporate_actions.{day}",
        bucket_id=session.bucket_id,
        detail=f"unverified corporate action on {day} for {', '.join(symbols)}",
    )


def preflight_portfolio_data(
    sessions: PortfolioSessions,
    *,
    symbols_by_bucket: Mapping[str, Iterable[str]] | None = None,
    positions_by_bucket: Mapping[str, Sequence[Any]] | None = None,
    loaders: Mapping[Market, Any] | None = None,
    ch_clients: Mapping[Market, Any] | None = None,
    calendar_client: "TradeCalendarClient | None" = None,
) -> PreparedPortfolioData:
    """Load each bucket's raw lookback/target bars and preflight it in order.

    Every gate (calendar, raw caliber, descriptor, readiness, day plan,
    corporate actions) completes for one bucket before the next bucket issues a
    provider call, so no later market can run ahead of an earlier failure.
    """
    prepared: list[PreparedBucketData] = []
    preflight: list[BucketPreflight] = []
    for session in sessions.buckets:
        if session.price_date != sessions.trade_date:
            raise PortfolioSessionError(
                reason="session_data_disagreement",
                path=f"sessions.{session.market}.price_date",
                bucket_id=session.bucket_id,
            )
        extra = symbols_by_bucket.get(session.bucket_id, ()) if symbols_by_bucket else ()
        symbols = tuple(sorted(set(session.position_symbols) | {str(symbol) for symbol in extra}))
        coverage, calendar_snapshot = _calendar_coverage(session, calendar_client)
        if coverage is not None and coverage.is_open != session.matchable:
            raise PortfolioSessionError(
                reason="session_data_disagreement",
                path=f"market_data.{session.bucket_id}.calendar",
                bucket_id=session.bucket_id,
            )
        result, _loader = _fetch_bucket(
            session, symbols, loaders=loaders, ch_clients=ch_clients)
        planning_bars, planning_date = _planning_bars(session, result)
        target_bars = _target_bars(session, result) if session.matchable else ()
        provenance = result.provenance
        as_of = _snapshot_as_of(provenance.bars_as_of, session.price_date)
        planning = DataSnapshot(
            price_date=planning_date,
            source=f"{provenance.source}:planning",
            as_of=as_of,
            bars=planning_bars,
        )
        execution = DataSnapshot(
            price_date=session.price_date,
            source=f"{provenance.source}:execution",
            as_of=as_of,
            bars=target_bars,
        )
        valuation = DataSnapshot(
            price_date=session.price_date,
            source=f"{provenance.source}:valuation",
            as_of=as_of,
            bars=target_bars,
        )
        prior_marks = () if session.matchable else _prior_marks(session, result, as_of)
        descriptor = BucketMarketData(
            bucket_id=session.bucket_id,
            market=session.market,
            price_date=session.price_date,
            planning=planning,
            execution=execution,
            valuation=valuation,
            prior_marks=prior_marks,
            calendar=coverage,
        )
        bucket = _prepare_bucket(session, descriptor)
        day_plan = _day_plan(session, result, calendar_snapshot)
        readiness = assess_readiness(result, session.price_date.isoformat())
        if session.matchable and not readiness.ready:
            raise PortfolioSessionError(
                reason="target_bar_not_ready",
                path=f"market_data.{session.bucket_id}.readiness",
                bucket_id=session.bucket_id,
                detail=readiness.message or "",
            )
        corporate_actions = _corporate_actions(
            session,
            result,
            day_plan,
            positions_by_bucket.get(session.bucket_id) if positions_by_bucket else None,
        )
        prepared.append(bucket)
        preflight.append(
            BucketPreflight(
                prepared=bucket,
                market_data=result,
                day_plan=day_plan,
                readiness=readiness,
                corporate_actions=corporate_actions,
                calendar=coverage,
                provenance=provenance,
            )
        )
    return PreparedPortfolioData(buckets=tuple(prepared), preflight=tuple(preflight))
