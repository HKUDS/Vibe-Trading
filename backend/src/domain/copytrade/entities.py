"""CopyTrade domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Self

from domain.shared.entity_id import EntityId
from domain.shared.result import Err, Ok, type Result


class CopyTradeStatus(Enum):
    """Status of a copy trade relationship."""

    ACTIVE = auto()
    PAUSED = auto()
    STOPPED = auto()


@dataclass
class CopyTrade:
    """A user's subscription to copy a strategy."""

    id: EntityId = field(default_factory=EntityId.generate)
    strategy_id: EntityId
    follower_id: EntityId
    allocation: float  # Capital allocated (e.g., 500.0 USD)
    status: CopyTradeStatus = CopyTradeStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    stopped_at: datetime | None = None
    total_pnl: float = 0.0  # Accumulated profit/loss

    def pause(self) -> Result[Self, str]:
        """Pause copying signals."""
        if self.status != CopyTradeStatus.ACTIVE:
            return Err("Only active copy trades can be paused")
        self.status = CopyTradeStatus.PAUSED
        return Ok(self)

    def resume(self) -> Result[Self, str]:
        """Resume copying signals."""
        if self.status != CopyTradeStatus.PAUSED:
            return Err("Only paused copy trades can be resumed")
        self.status = CopyTradeStatus.ACTIVE
        return Ok(self)

    def stop(self) -> Result[Self, str]:
        """Stop copying permanently."""
        if self.status == CopyTradeStatus.STOPPED:
            return Err("Copy trade is already stopped")
        self.status = CopyTradeStatus.STOPPED
        self.stopped_at = datetime.utcnow()
        return Ok(self)
