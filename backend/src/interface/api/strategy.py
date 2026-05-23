"""Strategy REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def list_strategies() -> dict:
    """List published strategies."""
    return {"strategies": []}


@router.post("")
async def create_strategy() -> dict:
    """Create a new strategy from a template."""
    return {"id": "todo"}


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str) -> dict:
    """Get strategy details."""
    return {"id": strategy_id}


@router.post("/{strategy_id}/publish")
async def publish_strategy(strategy_id: str) -> dict:
    """Publish a strategy to the marketplace."""
    return {"id": strategy_id, "status": "published"}
