"""CopyTrade REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def follow_strategy() -> dict:
    """Start copying a strategy."""
    return {"copy_trade_id": "todo"}


@router.get("/me")
async def my_copy_trades() -> dict:
    """Get current user's copy trades."""
    return {"copy_trades": []}


@router.delete("/{copy_trade_id}")
async def unfollow_strategy(copy_trade_id: str) -> dict:
    """Stop copying a strategy."""
    return {"id": copy_trade_id, "status": "stopped"}
