"""Frozen pt-v2.0 portfolio wire constants and the internal plan-line shape.

Every pattern, key set and header constant the wire validators enforce lives
here so the focused wire modules share one contract vocabulary without
importing each other's behavior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

WIRE_TOOL: Final = "paper_trade_step"
WIRE_SCHEMA_VERSION: Final = "pt-v2.0"
WIRE_MODE: Final = "portfolio"
INPUT_HASH_MARKER: Final = "input_sha256"
PUBLIC_ERROR_CODES: Final[tuple[str, ...]] = (
    "INVALID_REQUEST",
    "PAPER_DATA_NOT_READY",
)

_DECIMAL_PATTERN: Final = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_HASH_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_KEYS: Final = frozenset(
    {
        "amount",
        "avg_cost",
        "cash",
        "fee",
        "limit",
        "nav_base",
        "position_value",
        "price",
        "rebalance_band",
        "value",
        "weight",
    }
)
_REQUIRED_SUCCESS_KEYS: Final = (
    "status",
    "tool",
    "schema_version",
    "mode",
    "account_id",
    "base_currency",
    "trade_date",
    "planning_at",
    "valuation_at",
    "opening_portfolio",
    "post_conversion_portfolio",
    "end_portfolio",
    "sessions",
    "conversions",
    "plan",
    "bucket_results",
    "fills",
    "rejected_orders",
    "canceled_orders",
    "warnings",
    "errors",
    "complete",
    "hashes",
)
_SUCCESS_KEYS: Final = frozenset(_REQUIRED_SUCCESS_KEYS)
_CURRENCY_VALUES: Final = frozenset({"CNY", "HKD", "USD"})
_INPUT_HASH_SUFFIX: Final = re.compile(r"(?:^|;\s*)input_sha256=[0-9a-f]{64}\s*$")
_BUCKET_REQUIRED_KEYS: Final = ("bucket_id", "market", "currency", "cash", "positions")
_PLAN_LINE_FIELDS: Final = ("symbol", "currency", "side", "qty")


@dataclass(frozen=True, slots=True)
class _PlanLine:
    bucket_id: str
    symbol: str
    currency: str
    side: str
    qty: int
