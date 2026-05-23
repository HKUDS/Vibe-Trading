"""Adapter for Vibe-Trading backtest engine (Anti-Corruption Layer)."""

from __future__ import annotations

import httpx
from structlog import get_logger

from config import settings

logger = get_logger()


class BacktestEngineAdapter:
    """Wrap Vibe-Trading agent API for backtesting.

    This is the Anti-Corruption Layer — our domain talks to this adapter,
    not directly to Vibe-Trading's internal APIs.
    """

    def __init__(self, base_url: str = settings.vibe_trading_api_url) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))

    async def run_backtest(self, config: dict) -> dict:
        """Run a backtest via Vibe-Trading agent.

        Args:
            config: Compiled backtest configuration

        Returns:
            Raw backtest result from Vibe-Trading
        """
        url = f"{self.base_url}/api/v1/backtest"
        logger.info("backtest_request", url=url, symbol=config.get("symbol"))

        response = await self.client.post(url, json=config)
        response.raise_for_status()

        result = response.json()
        logger.info("backtest_response", status=response.status_code)
        return result

    async def get_backtest_status(self, run_id: str) -> dict:
        """Get backtest run status."""
        url = f"{self.base_url}/api/v1/backtest/{run_id}/status"
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
