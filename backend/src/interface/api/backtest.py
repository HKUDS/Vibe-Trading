"""Backtest REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def run_backtest() -> dict:
    """Run a backtest for a strategy."""
    return {"backtest_id": "todo"}


@router.get("/{backtest_id}")
async def get_backtest(backtest_id: str) -> dict:
    """Get backtest results."""
    return {"id": backtest_id}


@router.get("/{backtest_id}/progress")
async def backtest_progress(backtest_id: str) -> dict:
    """Stream backtest progress via SSE."""
    return {"id": backtest_id, "progress": 0}
