"""Read-only option-chain tool sharing the API/CLI data gateway.

Responses preserve source identity, acquisition time and stale/delayed status.
No live-execution capability is exposed by this tool.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from src.agent.tools import BaseTool

_MAX_CONTRACTS_PER_SIDE = 60


class OptionsChainTool(BaseTool):
    """Fetch observed US option snapshots through the shared data gateway."""

    name = "get_options_chain"
    # The agent scheduler resolves this argument before its normal identity gate.
    identity_argument = "ticker"
    description = (
        "Resolve a bare/ambiguous underlying with search_symbol first, in a separate turn; "
        "reuse a canonical user-provided or already resolved US identity. "
        "Fetch the US-listed options chain (calls and puts) for one expiration "
        "via the shared cached data gateway: per-contract strike, bid/ask, last price, volume, "
        "open interest, implied volatility, and in-the-money flag, plus the list "
        "of available expirations (epoch seconds). Read-only US options data. "
        "For a few near-price contracts, set near_spot_count to the requested number per side; "
        "use the included underlying_price without an extra stock-price read. "
        "last_trade_time is the last execution time, NEVER the bid/ask quote time. "
        "When quote_time_known is false, label the quote timestamp unavailable. "
        "Do not assign a timezone to unzoned provider timestamps; fetched_at is "
        "gateway retrieval time, not market quote time. "
        'Example after identity resolution: get_options_chain(ticker="AAPL.US").'
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": (
                    "Resolved US underlying, e.g. 'AAPL.US' (suffix stripped by provider). For bare 'AAPL', call search_symbol first and wait for its result. Required."
                ),
            },
            "near_spot_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_CONTRACTS_PER_SIDE,
                "description": "Nearest strikes per side (e.g. 2 for two calls and two puts). Defaults to 60. Do not combine with offset.",
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
        near_spot_count = kwargs.get("near_spot_count", _MAX_CONTRACTS_PER_SIDE)
        if isinstance(near_spot_count, bool) or not isinstance(near_spot_count, int) or not 1 <= near_spot_count <= _MAX_CONTRACTS_PER_SIDE:
            return _error(f"near_spot_count must be an integer from 1 to {_MAX_CONTRACTS_PER_SIDE}")
        if offset is not None and "near_spot_count" in kwargs:
            return _error("near_spot_count cannot be combined with offset")
        result = get_gateway().options_chain(
            ticker, normalized_expiration, **({"full": True} if offset is not None else {})
        )
        if result.get("ok"):
            data = result["data"]
            try:
                data["expiration_date"] = datetime.fromtimestamp(data["expiration"], timezone.utc).date().isoformat()
            except (ValueError, OverflowError, OSError, TypeError):
                data["expiration_date"] = None
            data["expiration_date_basis"] = "source_expiration_epoch_UTC_date"
            for side in ("calls", "puts"):
                if offset is None:
                    nearest = sorted(data[side], key=lambda row: abs(row["strike"] - data["underlying_price"]))
                    data[side] = sorted(nearest[:near_spot_count], key=lambda row: row["strike"])
                else:
                    data[side] = data[side][offset : offset + _MAX_CONTRACTS_PER_SIDE]
                for row in data[side]:
                    bid, ask = row.get("bid"), row.get("ask")
                    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and 0 <= bid <= ask:
                        b, a = Decimal(str(bid)), Decimal(str(ask))
                        row["mid_price"] = float((a + b) / 2)
                        row["bid_ask_spread"] = float(a - b)
                        row["quote_calculation_basis"] = "derived_from_returned_bid_ask; midpoint_not_execution_price"
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
