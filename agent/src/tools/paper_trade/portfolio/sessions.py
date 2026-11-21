"""Caller-declared market sessions and per-bucket matching eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Mapping, assert_never

from .models import (
    ExplicitOrdersPlan,
    Market,
    MarketSession,
    PortfolioRequest,
    TargetWeightsPlan,
)


@dataclass(frozen=True, slots=True)
class PortfolioSessionError(ValueError):
    """A stable session/data rejection scoped to one portfolio bucket."""

    reason: str
    path: str
    bucket_id: str
    code: Literal["INVALID_REQUEST", "PAPER_DATA_NOT_READY"] = "PAPER_DATA_NOT_READY"
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.code}:{self.reason}:{self.path}:{self.bucket_id}"


@dataclass(frozen=True, slots=True)
class BucketSession:
    """One bucket's explicit session provenance and routing decision."""

    bucket_id: str
    market: Market
    price_date: date
    required: bool
    position_symbols: tuple[str, ...]
    session: MarketSession

    @property
    def matchable(self) -> bool:
        """Only caller-declared open buckets may enter a matcher."""
        return self.session.status == "open"

    @property
    def has_holdings(self) -> bool:
        return bool(self.position_symbols)


@dataclass(frozen=True, slots=True)
class PortfolioSessions:
    """Immutable session routing for every portfolio bucket."""

    trade_date: date
    buckets: tuple[BucketSession, ...]

    @property
    def matchable(self) -> tuple[BucketSession, ...]:
        return tuple(bucket for bucket in self.buckets if bucket.matchable)

    @property
    def closed(self) -> tuple[BucketSession, ...]:
        return tuple(bucket for bucket in self.buckets if not bucket.matchable)


def _required_bucket_ids(request: PortfolioRequest) -> frozenset[str]:
    match request.plan:
        case ExplicitOrdersPlan(orders=orders):
            return frozenset(order.bucket_id for order in orders)
        case TargetWeightsPlan(target_weights=targets):
            return frozenset(
                target.bucket_id for target in targets if Decimal(target.weight) != 0
            )
        case unreachable:
            assert_never(unreachable)


def resolve_portfolio_sessions(
    request: PortfolioRequest,
    *,
    price_dates: Mapping[Market, date],
) -> PortfolioSessions:
    """Resolve required buckets and matchability without inferring holidays."""
    required = _required_bucket_ids(request)
    sessions = {session.market: session for session in request.sessions}
    buckets: list[BucketSession] = []
    for bucket in request.portfolio_state.buckets:
        price_date = price_dates.get(bucket.market)
        if price_date is None:
            raise PortfolioSessionError(
                code="INVALID_REQUEST",
                reason="missing_price_date",
                path=f"price_dates.{bucket.market}",
                bucket_id=bucket.bucket_id,
            )
        if price_date != request.trade_date:
            raise PortfolioSessionError(
                reason="session_data_disagreement",
                path=f"price_dates.{bucket.market}",
                bucket_id=bucket.bucket_id,
            )
        resolved = BucketSession(
            bucket_id=bucket.bucket_id,
            market=bucket.market,
            price_date=price_date,
            required=bucket.bucket_id in required,
            position_symbols=tuple(position.symbol for position in bucket.positions),
            session=sessions[bucket.market],
        )
        if resolved.required and not resolved.matchable:
            raise PortfolioSessionError(
                code="INVALID_REQUEST",
                reason="required_bucket_closed",
                path=f"sessions.{bucket.market}.status",
                bucket_id=bucket.bucket_id,
            )
        buckets.append(resolved)
    return PortfolioSessions(trade_date=request.trade_date, buckets=tuple(buckets))
