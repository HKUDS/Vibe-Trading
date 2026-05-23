"""Abstract repository interface for CopyTrade aggregate."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.copytrade.entities import CopyTrade
    from domain.shared.entity_id import EntityId


class CopyTradeRepository(ABC):
    """Repository for CopyTrade aggregate root."""

    @abstractmethod
    async def get(self, copy_trade_id: EntityId) -> CopyTrade | None:
        """Get copy trade by ID."""
        raise NotImplementedError

    @abstractmethod
    async def list_by_follower(self, follower_id: EntityId) -> list[CopyTrade]:
        """List all copy trades for a follower."""
        raise NotImplementedError

    @abstractmethod
    async def list_by_strategy(self, strategy_id: EntityId) -> list[CopyTrade]:
        """List all copy trades for a strategy."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, copy_trade: CopyTrade) -> CopyTrade:
        """Save or update a copy trade."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, copy_trade_id: EntityId) -> bool:
        """Delete a copy trade."""
        raise NotImplementedError
