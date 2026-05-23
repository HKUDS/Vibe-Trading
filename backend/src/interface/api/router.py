"""Main API router aggregating all module routes."""

from __future__ import annotations

from fastapi import APIRouter

from interface.api import backtest, copytrade, strategy

api_router = APIRouter()

api_router.include_router(
    strategy.router,
    prefix="/strategies",
    tags=["strategies"],
)

api_router.include_router(
    backtest.router,
    prefix="/backtests",
    tags=["backtests"],
)

api_router.include_router(
    copytrade.router,
    prefix="/copy-trades",
    tags=["copy-trades"],
)
