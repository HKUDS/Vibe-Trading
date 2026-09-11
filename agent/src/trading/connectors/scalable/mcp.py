"""Scalable Capital Agentic MCP mapping for generic read-only operations.

What is verified: the read tool NAMES, from the tool list Scalable publishes in
their own help docs (indexed in issue #1367). What is not: the argument
schemas, which need a live ``tools/list`` against an authenticated MCP session.
So the mapping is deliberately the smallest one that can work, and each wire
key it emits is an assumption flagged below — the upgrade path is one live
``tools/list`` replacing the two constants, not a rewrite.

* ``account`` / ``positions`` take one portfolio selector. Their holdings and
  overview tools are scoped to a portfolio the caller picked from
  ``list_accessible_portfolios``; the generic layer hands that over as
  ``account_number`` (or ``account``), and the wire key is ASSUMED to be
  ``portfolio_id``. When the caller named no portfolio, nothing is sent, so a
  wrong guess fails on the broker side instead of silently reading the wrong
  portfolio.
* ``quote`` is ASSUMED to take ``symbols`` (the Robinhood shape), because
  ``get_security_quote`` is the only published quote tool and the generic layer
  already passes ``symbols``.
* ``orders`` is intentionally unmapped: Scalable publishes no open-order read
  tool for it to point at.

None of these three assumptions is load-bearing for safety. They only decide
whether a read succeeds; a wrong key surfaces as a broker-side error.
"""

from __future__ import annotations

from typing import Any

_REMOTE_TOOL_NAMES = {
    "account": "get_portfolio_overview",
    "positions": "get_portfolio_holdings",
    "quote": "get_security_quote",
}

#: Generic keys that name the portfolio a read is scoped to. ASSUMED to be sent
#: on the wire as ``portfolio_id`` (see module docstring).
_PORTFOLIO_KEYS = ("portfolio_id", "account_number", "account")


def remote_tool_name(operation: str) -> str | None:
    """Return the Scalable remote tool name for a generic read operation."""
    return _REMOTE_TOOL_NAMES.get(operation)


def remote_arguments(operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize generic arguments for a Scalable remote MCP operation."""
    if operation in ("account", "positions"):
        for key in _PORTFOLIO_KEYS:
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return {"portfolio_id": value.strip()}
        return {}
    if operation == "quote":
        symbols = arguments.get("symbols")
        if isinstance(symbols, list) and symbols:
            return {"symbols": symbols}
        symbol = arguments.get("symbol")
        return {"symbols": [symbol]} if symbol else {}
    return {}
