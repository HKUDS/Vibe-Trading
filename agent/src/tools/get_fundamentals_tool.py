"""Read-only fundamental panel facade backed by the loader layer."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import pandas as pd

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

_VALID_FREQS = ("annual", "quarterly", "ttm")
_VALID_SOURCES = ("auto", "sec", "eastmoney", "tushare")


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A strict JSON ``{"ok": false, "error": ...}`` string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    """Convert provider/scalar values to strict-JSON-safe values."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _frame_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Serialize a wide fundamental panel DataFrame as JSON-safe records.

    Args:
        df: Wide DataFrame indexed by date with symbols as columns.

    Returns:
        Row records matching the existing market-data JSON style.
    """
    frame = df.copy()
    frame.index.name = frame.index.name or "date"
    records = frame.reset_index().to_dict(orient="records")
    for row in records:
        for key, value in row.items():
            row[key] = _json_safe(value)
    return records


class GetFundamentalsTool(BaseTool):
    """Fetch PIT-aligned fundamental fields as daily wide panels."""

    name = "get_fundamentals"
    description = (
        "Fetch PIT-safe fundamental fields as daily wide panels aligned by filed "
        "date. Returns {field: date x symbol records}. Fields use the unified "
        "fundamental schema, e.g. roe, gross_profitability, net_income, "
        "shares_diluted. Default freq is ttm and PIT mode is on."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'Symbols such as ["AAPL.US", "600519.SH", "00700.HK"].',
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'Unified schema fields, e.g. ["roe", "net_income"].',
            },
            "start": {
                "type": "string",
                "description": "Start date in YYYY-MM-DD format.",
            },
            "end": {
                "type": "string",
                "description": "End date in YYYY-MM-DD format.",
            },
            "freq": {
                "type": "string",
                "enum": list(_VALID_FREQS),
                "description": "Reporting cadence: annual, quarterly, or ttm.",
                "default": "ttm",
            },
            "pit": {
                "type": "boolean",
                "description": "Use point-in-time filed-date alignment.",
                "default": True,
            },
            "source": {
                "type": "string",
                "enum": list(_VALID_SOURCES),
                "description": "Fundamental source router.",
                "default": "auto",
            },
            "index": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional trading-date index to align to.",
            },
        },
        "required": ["symbols", "fields", "start", "end"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Validate inputs, call the loader, and return a JSON envelope.

        Args:
            **kwargs: ``symbols``, ``fields``, ``start``, ``end``, optional
                ``freq``, ``pit``, ``source``, and ``index``.

        Returns:
            Strict JSON envelope with serialized field panels or an error.
        """
        symbols = kwargs.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            return _error("symbols must be a non-empty list of strings")
        if any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols):
            return _error("every symbol must be a non-empty string")
        symbols = [symbol.strip() for symbol in symbols]

        fields = kwargs.get("fields")
        if not isinstance(fields, list) or not fields:
            return _error("fields must be a non-empty list of strings")
        if any(not isinstance(field, str) or not field.strip() for field in fields):
            return _error("every field must be a non-empty string")
        fields = [field.strip() for field in fields]

        start = kwargs.get("start")
        end = kwargs.get("end")
        if not isinstance(start, str) or not start.strip():
            return _error("start must be a non-empty YYYY-MM-DD string")
        if not isinstance(end, str) or not end.strip():
            return _error("end must be a non-empty YYYY-MM-DD string")

        freq = kwargs.get("freq", "ttm")
        if freq not in _VALID_FREQS:
            return _error(f"freq must be one of {list(_VALID_FREQS)}")

        pit = kwargs.get("pit", True)
        if not isinstance(pit, bool):
            return _error("pit must be a boolean")

        source = kwargs.get("source", "auto")
        if source not in _VALID_SOURCES:
            return _error(f"source must be one of {list(_VALID_SOURCES)}")

        index_arg = kwargs.get("index")
        if index_arg is None or isinstance(index_arg, pd.DatetimeIndex):
            index = index_arg
        elif isinstance(index_arg, list):
            index = pd.DatetimeIndex(index_arg)
        else:
            return _error("index must be a list of date strings or a DatetimeIndex")

        try:
            from backtest.loaders.fundamentals_loader import load_fundamental_panel

            panel = load_fundamental_panel(
                symbols=symbols,
                fields=fields,
                start=start.strip(),
                end=end.strip(),
                freq=freq,
                pit=pit,
                source=source,
                index=index,
            )
            data: dict[str, list[dict[str, Any]]] = {}
            for field, frame in panel.items():
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(
                        f"loader returned {type(frame).__name__} for field {field!r}, expected DataFrame"
                    )
                data[str(field)] = _frame_records(frame)
        except Exception as exc:  # noqa: BLE001 - tool facade must envelope failures
            logger.warning("get_fundamentals failed: %s", exc)
            return _error(str(exc))

        envelope = {
            "ok": True,
            "source": source,
            "freq": freq,
            "pit": pit,
            "symbols": symbols,
            "fields": fields,
            "data": data,
        }
        return json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False)
