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
        "benchmark_return",
        "cash",
        "cash_base",
        "cash_fx_effect_base",
        "conversion_effect_base",
        "conversion_rounding_base",
        "converted_amount",
        "deviation",
        "ending_cash",
        "ending_local_value",
        "ending_value_base",
        "exact_benchmark_return",
        "exact_converted",
        "exact_deviation",
        "exact_nav_base",
        "exact_notional_local",
        "exact_portfolio_return",
        "exact_value_base",
        "expected_rounding_residual",
        "fee",
        "fee_effect_base",
        "fee_local",
        "hhi",
        "limit",
        "lot_gap",
        "lot_gap_total",
        "market_contribution_base",
        "nav_base",
        "nav_change_exact",
        "nav_change_reported",
        "notional_local",
        "opening_cash",
        "opening_local_value",
        "opening_value_base",
        "planned_at_end_value_base",
        "planned_at_end_weight",
        "planned_cash_weight",
        "planned_value_base",
        "planned_weight",
        "planned_weight_total",
        "portfolio_end_exact_nav_base",
        "portfolio_end_nav_base",
        "portfolio_return",
        "portfolio_start_exact_nav_base",
        "portfolio_start_nav_base",
        "portfolio_start_rounding_residual",
        "position_contribution_base",
        "position_value",
        "position_value_base",
        "price",
        "price_gap",
        "price_gap_total",
        "rate",
        "realized_cash_weight",
        "realized_value_base",
        "realized_weight",
        "realized_weight_total",
        "rebalance_band",
        "reject_gap",
        "reject_gap_total",
        "rounding_effect_base",
        "rounding_local",
        "rounding_loss_base",
        "rounding_residual",
        "rounding_residual_base",
        "rounding_residual_local",
        "source_amount",
        "source_effect_base",
        "start_exact_nav_base",
        "start_nav_base",
        "start_rounding_residual",
        "target_cash_weight",
        "target_gap",
        "target_weight",
        "target_weight_total",
        "target_effect_base",
        "top_1",
        "top_5",
        "total_contribution_base",
        "trade_cash_base",
        "valuation_rounding",
        "valuation_rounding_weight",
        "value",
        "value_base",
        "weight",
        "weight_of_positions",
        "weight_rounding_residual",
        "weight_rounding_tolerance",
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
_OPTIONAL_SUCCESS_KEYS: Final = ("analytics",)
_SUCCESS_KEYS: Final = frozenset((*_REQUIRED_SUCCESS_KEYS, *_OPTIONAL_SUCCESS_KEYS))
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
