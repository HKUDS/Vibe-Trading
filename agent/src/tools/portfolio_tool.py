"""Read-only, sanitized portfolio context for model-assisted analysis."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.portfolio.service import PortfolioService


class PortfolioSummaryTool(BaseTool):
    """Expose the latest local portfolio snapshot as sanitized analysis context."""

    name = "portfolio_summary"
    description = (
        "Read the latest sanitized snapshot of the user's locally configured "
        "read-only brokerage accounts. Returns deterministic totals, account "
        "allocation, combined holdings, weights, unrealized P/L, data-quality "
        "warnings, and risk_xray_args (symbols + weights) that can be passed "
        "straight to the portfolio_risk_xray tool. A source that failed to "
        "refresh is reported as an error and excluded from the totals, so a "
        "snapshot with complete=false is missing accounts. It never returns "
        "credentials, account numbers, order IDs, personal names, or local "
        "paths. The result carries snapshot_id and read_identity; pass that "
        "snapshot_id back to keep a multi-step analysis on the same stored "
        "observation after a later refresh. Use the Web Portfolio refresh button "
        "before requesting current data."
    )
    parameters = {
        "type": "object",
        "properties": {
            "snapshot_id": {
                "type": "string",
                "description": (
                    "Optional id of a stored snapshot. When given, read exactly that "
                    "immutable observation instead of the latest one."
                ),
            },
        },
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Return the sanitized portfolio context as a JSON envelope.

        Returns:
            A JSON string with ``status`` ``ok`` and the context, ``empty``
            with a hint when no usable snapshot exists, or ``error`` when a
            requested ``snapshot_id`` is unavailable.
        """
        raw_id = kwargs.get("snapshot_id")
        snapshot_id = None if raw_id is None else str(raw_id).strip()
        context = PortfolioService().analysis_context(snapshot_id=snapshot_id)
        if context is None:
            if snapshot_id is not None:
                return json.dumps(
                    {
                        "status": "error",
                        "error_code": "snapshot_not_found",
                        "snapshot_id": snapshot_id,
                        "message": "The requested portfolio snapshot is unavailable or incompatible.",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "status": "empty",
                    "message": "No portfolio snapshot exists. Refresh the Portfolio page first.",
                },
                ensure_ascii=False,
            )
        return json.dumps({"status": "ok", "context": context}, ensure_ascii=False)
