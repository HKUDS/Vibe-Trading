"""Strategy domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Self

from domain.shared.entity_id import EntityId
from domain.shared.result import Err, Ok, type Result


class StrategyStatus(Enum):
    """Lifecycle status of a strategy."""

    DRAFT = auto()
    PUBLISHED = auto()
    ARCHIVED = auto()


class SignalType(Enum):
    """Type of trading signal."""

    BUY = auto()
    SELL = auto()
    HOLD = auto()


@dataclass(frozen=True, slots=True)
class Signal:
    """A buy/sell/hold instruction at a specific time."""

    type: SignalType
    symbol: str
    timestamp: datetime
    price: float
    confidence: float = 1.0  # 0.0 ~ 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("Confidence must be between 0.0 and 1.0")
        if self.price <= 0:
            raise ValueError("Price must be positive")


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Historical simulation result."""

    cumulative_return: float  # e.g., 0.47 = +47%
    max_drawdown: float  # e.g., -0.12 = -12%
    sharpe_ratio: float
    win_rate: float  # 0.0 ~ 1.0
    total_trades: int
    start_date: datetime
    end_date: datetime


@dataclass
class Strategy:
    """A complete trading strategy."""

    id: EntityId = field(default_factory=EntityId.generate)
    creator_id: EntityId
    name: str
    template_key: str  # e.g., "moving_average_cross"
    params: dict[str, object]  # Template-specific parameters
    status: StrategyStatus = StrategyStatus.DRAFT
    backtest_result: BacktestResult | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    published_at: datetime | None = None

    def publish(self) -> Result[Self, str]:
        """Publish the strategy to the marketplace."""
        if self.status != StrategyStatus.DRAFT:
            return Err("Strategy must be in DRAFT status to publish")
        if self.backtest_result is None:
            return Err("Strategy must have a backtest result before publishing")
        self.status = StrategyStatus.PUBLISHED
        self.published_at = datetime.utcnow()
        return Ok(self)

    def archive(self) -> Result[Self, str]:
        """Archive the strategy."""
        if self.status != StrategyStatus.PUBLISHED:
            return Err("Only published strategies can be archived")
        self.status = StrategyStatus.ARCHIVED
        return Ok(self)
