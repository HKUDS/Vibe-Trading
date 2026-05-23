"""Abstract repository interface for Strategy aggregate."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.shared.entity_id import EntityId
    from domain.strategy.entities import Strategy


class StrategyRepository(ABC):
    """Repository for Strategy aggregate root."""

    @abstractmethod
    async def get(self, strategy_id: EntityId) -> Strategy | None:
        """Get strategy by ID."""
        raise NotImplementedError

    @abstractmethod
    async def list_published(self, *, limit: int = 20, offset: int = 0) -> list[Strategy]:
        """List published strategies."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, strategy: Strategy) -> Strategy:
        """Save or update a strategy."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, strategy_id: EntityId) -> bool:
        """Delete a strategy."""
        raise NotImplementedError
