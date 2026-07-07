"""Tests for Phase 2 A-share market-rule warnings."""

from __future__ import annotations

from src.reliability.market_rules.ashare import audit_ashare_assumptions


def test_ashare_missing_t1_warning() -> None:
    warnings = audit_ashare_assumptions({"asset_class": "ashare"})

    codes = {warning.code for warning in warnings}

    assert "ASHARE_T1_ASSUMPTION_MISSING" in codes
    assert "ASHARE_COST_MODEL_MISSING" in codes


def test_ashare_complete_assumptions_do_not_warn() -> None:
    warnings = audit_ashare_assumptions(
        {
            "ashare_t1": True,
            "ashare_limit_up_down": True,
            "ashare_suspension": True,
            "ashare_lot_size": True,
            "cost_model": {"commission_bps": 2.5},
            "ashare_st_filter": True,
            "ashare_new_listing_filter": True,
            "historical_universe": True,
        }
    )

    assert warnings == []
