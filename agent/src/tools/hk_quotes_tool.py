"""Read-only Hong Kong quote snapshots, separate from historical OHLCV."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.hk_data.service import fetch_quotes


class HKQuotesTool(BaseTool):
    name = "get_hk_quotes"
    description = (
        "Fetch current Hong Kong quote snapshots with source timestamp, currency, "
        "age and delay metadata. Defaults to Tencent's faster r_hk endpoint. "
        "Yahoo HK is 15 minutes delayed. Unknown delay never means verified realtime. "
        "Use get_market_data for historical OHLCV. Futu is explicit-only via local OpenD."
    )
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 100,
                "description": "HK tickers, e.g. 0700.HK, 0005.HK.",
            },
            "source": {
                "type": "string",
                "enum": ["auto", "yahoo", "tencent", "futu"],
                "default": "tencent",
            },
            "max_age_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 60,
            },
        },
        "required": ["symbols"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            result = fetch_quotes(
                kwargs.get("symbols"),
                kwargs.get("source", "tencent"),
                kwargs.get("max_age_seconds", 60),
            )
        except (ValueError, TypeError) as exc:
            result = {"ok": False, "status": "error", "error": str(exc)}
        return json.dumps(result, ensure_ascii=False, allow_nan=False)
