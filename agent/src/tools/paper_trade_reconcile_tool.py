"""Agent tool for independent paper-trade ledger reconciliation."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.tools.paper_trade.reconcile import reconcile_document


class PaperTradeReconcileTool(BaseTool):
    """Check a paper-trading result against its initial ledger and fills."""

    name = "paper_trade_reconcile"
    description = (
        "Independently replay a paper_trade_step result from the initial account "
        "state and fills. Checks per-fill fees, cash, position quantity and "
        "average cost, cn_a T+1 availability, end_state, and NAV arithmetic. "
        "Returns field-level mismatches and names facts that cannot be verified "
        "without bars or stable order ids. Research only; no market data, broker, "
        "order placement, or persistent write is used."
    )
    parameters = {
        "type": "object",
        "properties": {
            "account_state": {
                "type": "object",
                "description": "Initial ledger {cash, positions:[{symbol, qty, avg_cost}]}.",
            },
            "result": {
                "type": "object",
                "description": "Successful paper_trade_step result document to audit.",
            },
        },
        "required": ["account_state", "result"],
    }
    repeatable = True
    is_readonly = True
    deterministic = True

    def execute(self, **kwargs: Any) -> str:
        """Return a deterministic JSON reconciliation report."""
        try:
            payload = reconcile_document(
                kwargs.get("account_state"), kwargs.get("result")
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            payload = {
                "status": "error",
                "tool": self.name,
                "error": str(exc),
            }
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
