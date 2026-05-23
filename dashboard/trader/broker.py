"""Bybit testnet broker — ccxt wrapper for order execution.

Reads credentials from environment:
  BYBIT_API_KEY    — Bybit testnet API key
  BYBIT_API_SECRET — Bybit testnet API secret
"""

from __future__ import annotations

import os
from typing import Optional

import ccxt


def _make_exchange() -> ccxt.bybit:
    api_key = os.environ.get("BYBIT_API_KEY", "")
    api_secret = os.environ.get("BYBIT_API_SECRET", "")
    if not api_key or not api_secret:
        raise EnvironmentError("BYBIT_API_KEY and BYBIT_API_SECRET must be set")

    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
        }
    )
    exchange.set_sandbox_mode(True)  # Bybit testnet
    return exchange


class Broker:
    """Thin ccxt wrapper for Bybit testnet perpetual trading."""

    def __init__(self) -> None:
        self.exchange = _make_exchange()

    # ── Account ──────────────────────────────────────────────────────────────

    def get_equity(self) -> float:
        """Return total USDT equity in the unified trading account."""
        balance = self.exchange.fetch_balance({"type": "swap"})
        usdt = balance.get("USDT", {})
        return float(usdt.get("total", 0.0))

    # ── Position ─────────────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> Optional[dict]:
        """Return open position for *symbol*, or None if flat.

        Returns dict with keys: side ("long"/"short"), size (float), entry_price (float).
        """
        positions = self.exchange.fetch_positions([symbol])
        for pos in positions:
            contracts = float(pos.get("contracts") or 0)
            if contracts > 0:
                return {
                    "side": pos["side"],
                    "size": contracts,
                    "entry_price": float(pos.get("entryPrice") or 0),
                }
        return None

    # ── Orders ───────────────────────────────────────────────────────────────

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        """Place a market order.

        Args:
            symbol: e.g. "BTC/USDT:USDT"
            side: "buy" or "sell"
            qty: Quantity in base asset (contracts).

        Returns:
            ccxt order dict.
        """
        order = self.exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=qty,
        )
        return order

    def close_position(self, symbol: str) -> Optional[dict]:
        """Close the open position for *symbol*, if any.

        Returns the closing order dict, or None if already flat.
        """
        pos = self.get_position(symbol)
        if pos is None:
            return None
        # To close a long, sell; to close a short, buy.
        close_side = "sell" if pos["side"] == "long" else "buy"
        return self.place_market_order(symbol, close_side, pos["size"])

    def get_ticker(self, symbol: str) -> dict:
        """Return current ticker (bid/ask/last) for *symbol*."""
        return self.exchange.fetch_ticker(symbol)
