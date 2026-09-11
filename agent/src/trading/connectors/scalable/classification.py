"""Curated read/write classification map for Scalable Capital's Agentic MCP.

Tier 2 of the classification ladder (:mod:`src.live.classification`): an
explicit, version-controlled map keyed by the broker's remote tool name. Map
entries are authoritative and override Tier-1 ``annotations`` when they
disagree (a deceptive ``readOnlyHint=True`` on ``submit_buy_order`` cannot
demote a curated WRITE). A tool absent from this map and not annotated
read-only is UNKNOWN and treated as WRITE (fail-closed).

Provenance: Scalable publishes the tool *names* and one-line descriptions in
their own help docs, indexed in issue #1367. The tracker post headlined "26
tools across 6 categories" and then enumerated 29 names; this map pins the
NAMES AS LISTED, because a name is what the classification ladder keys on.
Their argument schemas are not published — see :mod:`mcp` for the (small,
flagged) wire assumptions that follow from that.

READ is pinned for the 18 published read tools. WRITE is pinned for the 11
order-path ones — including ``preview_buy_order`` / ``preview_sell_order``:
a preview mutates nothing, but it sits on the order path and its confirmation
feeds ``submit_*``, so treating it as READ would hand out an order-path tool
on the plain read path. Any tool Scalable adds later that is not in this map
and not annotated read-only resolves UNKNOWN → WRITE (fail-closed).
"""

from __future__ import annotations

from src.live.classification import ToolClass

#: Frozen canonical Scalable Capital read/write catalog.
SCALABLE_TOOL_CLASS: dict[str, ToolClass] = {
    # READ — account & portfolio (9)
    "get_account_profile": ToolClass.READ,
    "list_accessible_portfolios": ToolClass.READ,
    "get_portfolio_overview": ToolClass.READ,
    "get_portfolio_holdings": ToolClass.READ,
    "get_portfolio_cash_breakdown": ToolClass.READ,
    "get_portfolio_performance": ToolClass.READ,
    "list_portfolio_transactions": ToolClass.READ,
    "get_transaction_details": ToolClass.READ,
    "get_overnight_summary": ToolClass.READ,
    # READ — market data (5)
    "search_securities": ToolClass.READ,
    "search_derivatives": ToolClass.READ,
    "get_security_quote": ToolClass.READ,
    "get_security_chart": ToolClass.READ,
    "get_security_news": ToolClass.READ,
    # READ — watchlist / alerts / savings-plan state (4)
    "list_watchlist_items": ToolClass.READ,
    "list_price_alerts": ToolClass.READ,
    "list_savings_plans": ToolClass.READ,
    "get_savings_plan_config": ToolClass.READ,
    # WRITE — watchlist / alerts / savings plans (6)
    "add_watchlist_item": ToolClass.WRITE,
    "remove_watchlist_item": ToolClass.WRITE,
    "create_price_alert": ToolClass.WRITE,
    "remove_price_alert": ToolClass.WRITE,
    "upsert_savings_plan": ToolClass.WRITE,
    "remove_savings_plan": ToolClass.WRITE,
    # WRITE — order path (5). preview_* is pinned WRITE on purpose: see module
    # docstring. No built-in profile enables any of these.
    "preview_buy_order": ToolClass.WRITE,
    "submit_buy_order": ToolClass.WRITE,
    "preview_sell_order": ToolClass.WRITE,
    "submit_sell_order": ToolClass.WRITE,
    "cancel_order": ToolClass.WRITE,
}
