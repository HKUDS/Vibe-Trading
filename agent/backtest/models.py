"""Shared data models for backtest engines.

Immutable dataclasses for positions, trades, and equity snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


ORDER_STATUSES = {"open", "partially_filled", "filled", "cancelled"}


@dataclass
class OrderRecord:
    """Mutable order lifecycle supporting one or more execution fills."""

    order_id: str
    symbol: str
    side: str
    event_type: str
    direction: int
    requested_quantity: float
    created_time: pd.Timestamp
    decision_price: float
    reason: str
    filled_quantity: float = 0.0
    remaining_quantity: float | None = None
    cancelled_quantity: float = 0.0
    status: str = "open"
    updated_time: pd.Timestamp | None = None
    signal_time: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        self.requested_quantity = max(float(self.requested_quantity), 0.0)
        self.filled_quantity = max(float(self.filled_quantity), 0.0)
        if self.remaining_quantity is None:
            self.remaining_quantity = max(
                self.requested_quantity - self.filled_quantity,
                0.0,
            )
        else:
            self.remaining_quantity = max(float(self.remaining_quantity), 0.0)
        self.cancelled_quantity = max(float(self.cancelled_quantity), 0.0)
        if self.status not in ORDER_STATUSES:
            raise ValueError(f"unsupported order status: {self.status!r}")
        if self.filled_quantity - self.requested_quantity > 1e-9:
            raise ValueError("filled quantity cannot exceed requested quantity")

    def record_fill(self, quantity: float, timestamp: pd.Timestamp) -> None:
        """Apply an executed quantity and advance the order status."""
        if self.status not in {"open", "partially_filled"}:
            raise ValueError(f"cannot fill order in status {self.status!r}")
        executed = float(quantity)
        if executed <= 0.0:
            raise ValueError("fill quantity must be positive")
        remaining = float(self.remaining_quantity or 0.0)
        if executed - remaining > 1e-9:
            raise ValueError("fill quantity exceeds remaining quantity")
        self.filled_quantity += executed
        self.remaining_quantity = max(remaining - executed, 0.0)
        self.updated_time = pd.Timestamp(timestamp)
        self.status = (
            "filled" if self.remaining_quantity <= 1e-9 else "partially_filled"
        )

    def cancel(self, timestamp: pd.Timestamp) -> None:
        """Cancel only the unfilled residual quantity."""
        if self.status in {"filled", "cancelled"}:
            return
        self.cancelled_quantity += float(self.remaining_quantity or 0.0)
        self.remaining_quantity = 0.0
        self.updated_time = pd.Timestamp(timestamp)
        self.status = "cancelled"


@dataclass(frozen=True)
class Position:
    """An open position in a single instrument.

    Args:
        symbol: Instrument identifier.
        direction: 1 for long, -1 for short.
        entry_price: Execution price at entry.
        entry_time: Timestamp when position was opened.
        size: Number of shares / coins.
        leverage: Effective leverage (1 for spot/stocks).
        entry_bar_idx: Index in the dates array at entry (for holding_bars).
        entry_commission: Commission paid at entry.
    """

    symbol: str
    direction: int
    entry_price: float
    entry_time: pd.Timestamp
    size: float
    leverage: float = 1.0
    entry_bar_idx: int = 0
    entry_commission: float = 0.0
    entry_decision_price: float | None = None
    entry_slippage_cost: float = 0.0
    signal_time: pd.Timestamp | None = None


@dataclass(frozen=True)
class TradeRecord:
    """A completed round-trip trade.

    Args:
        symbol: Instrument identifier.
        direction: 1 for long, -1 for short.
        entry_price: Entry execution price.
        exit_price: Exit execution price.
        entry_time: Entry timestamp.
        exit_time: Exit timestamp.
        size: Number of shares / coins traded.
        leverage: Effective leverage.
        pnl: Realised profit/loss in cash terms.
        pnl_pct: Realised P&L as percentage of margin.
        exit_reason: Why closed (signal / liquidation / end_of_backtest).
        holding_bars: Number of bars held.
        commission: Total commission (entry + exit).
    """

    symbol: str
    direction: int
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    size: float
    leverage: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_bars: int
    commission: float
    signal_time: pd.Timestamp | None = None
    entry_decision_price: float | None = None
    exit_decision_price: float | None = None
    gross_pnl: float | None = None
    slippage_cost: float = 0.0
    net_pnl: float | None = None
    holding_days: int | None = None


@dataclass(frozen=True)
class FillRecord:
    """A single executed entry or exit fill captured at execution time.

    ``direction`` is the position direction (``1`` long, ``-1`` short), while
    ``side`` describes the actual order side (``buy`` or ``sell``).  Notional
    intentionally follows the shared ledger convention of absolute quantity
    times fill price.
    """

    timestamp: pd.Timestamp
    symbol: str
    side: str
    event_type: str
    direction: int
    quantity: float
    decision_price: float
    fill_price: float
    notional: float
    commission: float
    slippage_cost: float
    reason: str
    order_id: str = ""
    requested_quantity: float | None = None
    remaining_quantity: float | None = None
    fill_status: str = "filled"


@dataclass(frozen=True)
class EquitySnapshot:
    """Portfolio state at a single point in time.

    Args:
        timestamp: Bar timestamp.
        capital: Free cash.
        unrealized: Total unrealised P&L across all positions.
        equity: capital + margin_in_use + unrealized.
        positions: Number of open positions.
    """

    timestamp: pd.Timestamp
    capital: float
    unrealized: float
    equity: float
    positions: int
