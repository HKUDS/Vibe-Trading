"""Zerodha Kite Connect tool classification (Tier 2 curated map).

Read tools stay ungated; order placement is pinned WRITE so the live gate fails
closed. Mirrors shoonya/classification.py. The connector itself is paper-only,
but the classification ladder is the registry's default-deny backstop.
"""

from __future__ import annotations

from src.live.classification import ToolClass

ZERODHA_TOOL_CLASS: dict[str, ToolClass] = {
    # read-only market data + account
    "kite.quote": ToolClass.READ,
    "kite.historical_data": ToolClass.READ,
    "kite.instruments": ToolClass.READ,
    "kite.positions": ToolClass.READ,
    "kite.holdings": ToolClass.READ,
    "kite.orders": ToolClass.READ,
    "kite.order_history": ToolClass.READ,
    "kite.margins": ToolClass.READ,
    # order mutation -> WRITE (fails closed under the live gate)
    "kite.place_order": ToolClass.WRITE,
    "kite.cancel_order": ToolClass.WRITE,
    "kite.modify_order": ToolClass.WRITE,
}
