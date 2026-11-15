"""Read-only option-chain tool sharing the API/CLI data gateway.

Responses preserve source identity, acquisition time and stale/delayed status.
No live-execution capability is exposed by this tool.
"""

from __future__ import annotations
import json
from typing import Any, Optional

from src.agent.tools import BaseTool

_MAX_CONTRACTS_PER_SIDE = 60


class OptionsChainTool(BaseTool):
    """Fetch observed US option snapshots through the shared data gateway."""

    name = "get_options_chain"
    description = (
        "Fetch the US-listed options chain (calls and puts) for one expiration "
        "via the shared cached data gateway: per-contract strike, bid/ask, last price, volume, "
        "open interest, implied volatility, and in-the-money flag, plus the list "
        "of available expirations (epoch seconds). Read-only US options data. "
        "last_trade_time is the last execution time, NEVER the bid/ask quote time. "
        "When quote_time_known is false, label the quote timestamp unavailable. "
        "Do not assign a timezone to unzoned provider timestamps; fetched_at is "
        "gateway retrieval time, not market quote time. "
        'Example: get_options_chain(ticker="AAPL").'
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": (
                    "US underlying symbol, e.g. 'AAPL' or 'AAPL.US' (the .US suffix is stripped). Required."
                ),
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Optional offset into the full source chain, in strike order, 60 rows per side. Omit for near-spot rows.",
            },
            "expiration": {
                "type": "integer",
                "description": (
                    "Optional expiration as Unix epoch seconds (one of the "
                    "values from the returned expirations list). Omit for the "
                    "nearest expiration."
                ),
            },
        },
        "required": ["ticker"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Return a JSON-string envelope with the calls/puts chain.

        Args:
            **kwargs: ``ticker`` (str, required) and optional ``expiration``
                (int epoch seconds).

        Returns:
            A JSON string. On success:
            ``{"ok": true, "market": "us", "source": str, "data": {...}}``
            where ``data`` carries ``ticker``, ``expirations``, ``expiration``,
            ``calls``, ``puts``, and per-side counts. On failure:
            ``{"ok": false, "error": str}``.
        """
        ticker = str(kwargs.get("ticker") or "").strip()
        if not ticker:
            return _error("ticker is required")

        expiration = kwargs.get("expiration")
        normalized_expiration = _coerce_expiration(expiration)
        if expiration is not None and normalized_expiration is None:
            return _error("expiration must be Unix epoch seconds (integer)")

        from src.data_gateway import get_gateway

        offset = kwargs.get("offset")
        if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0):
            return _error("offset must be a non-negative integer")
        result = get_gateway().options_chain(
            ticker, normalized_expiration, **({"full": True} if offset is not None else {})
        )
        if result.get("ok"):
            data = result["data"]
            for side in ("calls", "puts"):
                if offset is None:
                    nearest = sorted(data[side], key=lambda row: abs(row["strike"] - data["underlying_price"]))
                    data[side] = sorted(nearest[:_MAX_CONTRACTS_PER_SIDE], key=lambda row: row["strike"])
                else:
                    data[side] = data[side][offset : offset + _MAX_CONTRACTS_PER_SIDE]
                data[side + "_count"] = len(data[side])
            data["complete_expiration"] = all(
                len(data[s]) == data.get(s + "_total", len(data[s])) for s in ("calls", "puts")
            )
            if offset is not None:
                total = max(data.get(s + "_total", len(data[s])) for s in ("calls", "puts"))
                data["next_offset"] = (
                    offset + _MAX_CONTRACTS_PER_SIDE if offset + _MAX_CONTRACTS_PER_SIDE < total else None
                )
                data["offset"] = offset
                data["coverage"] = "page_of_source_expiration"
        return json.dumps(result, ensure_ascii=False, allow_nan=False)


def _coerce_expiration(value: Any) -> Optional[int]:
    """Coerce integer epoch seconds without silently truncating fractions."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
        if isinstance(value, float) and value != result:
            return None
        return result if result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _error(message: str) -> str:
    """Render a validation failure without starting gateway workers."""
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
