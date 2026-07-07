"""A-share market-rule audit warnings."""

from __future__ import annotations

from typing import Any, Mapping

from src.reliability.data.contracts import StructuredWarning

_ASHARE_REQUIRED_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("ashare_t1", "ASHARE_T1_ASSUMPTION_MISSING", "A-share T+1 handling is not declared"),
    (
        "ashare_limit_up_down",
        "ASHARE_LIMIT_UP_DOWN_ASSUMPTION_MISSING",
        "A-share limit-up/down handling is not declared",
    ),
    ("ashare_suspension", "ASHARE_SUSPENSION_ASSUMPTION_MISSING", "A-share suspension handling is not declared"),
    ("ashare_lot_size", "ASHARE_LOT_SIZE_ASSUMPTION_MISSING", "A-share 100-share lot handling is not declared"),
    ("ashare_st_filter", "ASHARE_ST_FILTER_MISSING", "A-share ST filter is not declared"),
    ("ashare_new_listing_filter", "ASHARE_NEW_LISTING_FILTER_MISSING", "A-share new-listing filter is not declared"),
    (
        "historical_universe",
        "ASHARE_HISTORICAL_UNIVERSE_MISSING",
        "A-share historical universe membership is not declared",
    ),
)


def audit_ashare_assumptions(config: Mapping[str, Any]) -> list[StructuredWarning]:
    """Return stable warnings for missing A-share assumptions."""
    warnings: list[StructuredWarning] = []
    for key, code, message in _ASHARE_REQUIRED_FLAGS:
        if not config.get(key):
            warnings.append(StructuredWarning(code=code, severity="warning", message=message))
    if not config.get("cost_model") and not _has_inline_cost_model(config):
        warnings.append(
            StructuredWarning(
                code="ASHARE_COST_MODEL_MISSING",
                severity="warning",
                message="A-share cost model is not declared",
            )
        )
    return warnings


def _has_inline_cost_model(config: Mapping[str, Any]) -> bool:
    return any(key in config for key in ("commission_rate", "stamp_tax", "transfer_fee", "slippage"))
