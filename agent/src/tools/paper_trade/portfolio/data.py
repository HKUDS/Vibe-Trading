"""Typed planning, execution and valuation inputs for portfolio buckets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal, TypeAlias

from .models import DecimalString, Market
from .sessions import BucketSession, PortfolioSessionError, PortfolioSessions

_SNAPSHOT_CALENDAR_MARKETS: Final = frozenset({"cn_a"})


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
class PreparedPortfolioData:
    """Prepared inputs with closed buckets excluded from matching."""

    buckets: tuple[PreparedBucketData, ...]

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
            execution: DataSnapshot | None = data.execution
            valuation: ValuationInput = TargetBarValuation(snapshot=data.valuation)
        else:
            execution = None
            valuation = PriorMarkValuation(marks=_closed_marks(session, data))
        prepared.append(
            PreparedBucketData(
                session=session,
                planning=data.planning,
                execution=execution,
                valuation=valuation,
            )
        )
    return PreparedPortfolioData(buckets=tuple(prepared))
