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
        "state and fills. Accepts two account_state shapes: the legacy "
        "{cash, positions} ledger and, for a pt-v2.0 portfolio document, its "
        "opening {buckets:[...]} portfolio_state object. A result declaring "
        "paper_trade_step + mode=portfolio + schema_version=pt-v2.0 is dispatched "
        "to the portfolio replay (buckets, conversions, plan order ids, fills, "
        "fees, cash, positions, NAV, exposures and attribution); every legacy "
        "document follows the original ledger-only checks. Returns field-level "
        "mismatches and names facts that cannot be verified without marks, FX "
        "snapshots or hashes. Research only; no market data, broker, order "
        "placement, or persistent write is used."
    )
    parameters = {
        "type": "object",
        "properties": {
            "account_state": {
                "type": "object",
                "description": (
                    "Initial ledger. Legacy single-market: {cash, positions:["
                    "{symbol, qty, avg_cost}]}. Portfolio (pt-v2.0): the opening "
                    "portfolio_state {buckets:[{bucket_id, market, currency, "
                    "cash, positions, fee_model?}]} supplied to the step."
                ),
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
