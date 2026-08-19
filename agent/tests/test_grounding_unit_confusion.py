"""Tests for the four unit-confusion fixes in grounding.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger


class FakeRecord:
    """Minimal record stand-in for testing."""
    def __init__(self, symbol, value, field):
        self.symbol = symbol
        self.value = value
        self.field = field
        self.call_id = "test_call_1"
        self.currency = None
        self.source = "test"
        self.timestamp = None
        self.status = "observed"


def _extract_numbers(text: str) -> list[float]:
    """Helper: extract numbers from text using the grounding ledger logic."""
    ledger = GroundingLedger(run_dir=Path("/tmp/test_helpers"), user_message="test")
    return ledger._numbers_without_dates_or_percent(text)


# ===========================================================================
# Fix A: _is_explicit_derivation accepts `=` without keyword
# ===========================================================================

class TestFixA:
    def _make_ledger(self, user_message="test"):
        return GroundingLedger(run_dir=Path("/tmp/test_fix_a"), user_message=user_message)

    def test_equals_without_keyword_triggers_derivation(self):
        """market_val / qty = $111 with matching observed should pass."""
        ledger = self._make_ledger()
        records = [
            FakeRecord("AAPL", 444000.0, "market_val"),
            FakeRecord("AAPL", 4000.0, "qty"),
        ]
        assert ledger._is_explicit_derivation(
            "market_val 444000 / 4000 = $111", records, "AAPL"
        )

    def test_equals_with_keyword_still_works(self):
        """Existing keyword-based derivation still works."""
        ledger = self._make_ledger()
        records = [
            FakeRecord("AAPL", 122.5, "strike"),
            FakeRecord("AAPL", 1.3, "premium"),
        ]
        assert ledger._is_explicit_derivation(
            "based on 122.5 + 1.30 = 123.8", records, "AAPL"
        )

    def test_equals_without_matching_observed_fails(self):
        """Formula with = but inputs don't match observed should fail."""
        ledger = self._make_ledger()
        records = [FakeRecord("AAPL", 50.0, "price")]
        assert not ledger._is_explicit_derivation(
            "random 999 * 2 = 198", records, "AAPL"
        )

    def test_no_equals_no_keyword_fails(self):
        """Without = or keyword, derivation check fails."""
        ledger = self._make_ledger()
        records = [FakeRecord("AAPL", 115.0, "price")]
        assert not ledger._is_explicit_derivation(
            "price is 115", records, "AAPL"
        )


# ===========================================================================
# Fix B: _QUANTITY_WITH_UNIT_RE masks qty/premium/multiplier
# ===========================================================================

class TestFixB:
    def test_qty_unit_masked(self):
        assert _extract_numbers("4000 qty") == []

    def test_premium_unit_masked(self):
        assert _extract_numbers("1.30 premium") == []

    def test_multiplier_unit_masked(self):
        assert _extract_numbers("100 multiplier") == []

    def test_contracts_unit_masked(self):
        assert _extract_numbers("1 contract") == []
        assert _extract_numbers("100 contracts") == []

    def test_shares_unit_masked(self):
        assert _extract_numbers("4000 shares") == []

    def test_notional_unit_masked(self):
        assert _extract_numbers("444000 notional") == []

    def test_market_val_unit_masked(self):
        assert _extract_numbers("444000 market_val") == []
        assert _extract_numbers("444000 market value") == []

    def test_legitimate_price_not_masked(self):
        """Real prices should NOT be masked."""
        assert _extract_numbers("77.0 close") == [77.0]
        assert _extract_numbers("$111") == [111.0]
        assert _extract_numbers("115 HKD") == [115.0]

    def test_indicator_value_not_masked_by_this(self):
        """Indicator values are masked by _INDICATOR_VALUE_RE, not this."""
        assert _extract_numbers("RSI 67.3") == []


# ===========================================================================
# Fix C: _compare_price_claim skips comparison when scale differs >100x
# ===========================================================================

class TestFixC:
    def _make_ledger(self, user_message="test"):
        return GroundingLedger(run_dir=Path("/tmp/test_fix_c"), user_message=user_message)

    def _compare(self, value, observed, claim="test claim"):
        ledger = self._make_ledger()
        records = [FakeRecord("AAPL", v, "close") for v in observed]
        return ledger._compare_price_claim(
            value=value, records=records, field_name=None,
            date_value=None, symbol="AAPL", claim=claim,
        )

    def test_extreme_scale_mismatch_skipped(self):
        """Claim $1.0 vs observed $100-200: ratio >100x, skip."""
        result = self._compare(1.0, [100.0, 200.0], "premium 1.0")
        assert result is None

    def test_market_val_vs_ohlc_skipped(self):
        """Claim 444000 vs observed [77, 96]: ratio >100x, skip."""
        result = self._compare(444000.0, [77.0, 96.45], "market_val 444000")
        assert result is None

    def test_qty_vs_ohlc_skipped(self):
        """Claim 40000 vs observed [77, 96]: ratio >100x, skip."""
        result = self._compare(40000.0, [77.0, 96.45], "qty 40000")
        assert result is None

    def test_within_tolerance_no_conflict(self):
        """Claim within 0.5% of an observed value returns None (no conflict)."""
        # 77.2 is within 0.5% of 77.0 (0.5% of 77 = 0.385)
        result = self._compare(77.2, [77.0, 96.45], "price 77.2")
        assert result is None

    def test_out_of_range_same_scale_conflict(self):
        """Claim $200 vs observed [77, 96]: same scale, out of range, conflict."""
        result = self._compare(200.0, [77.0, 96.45], "price 200")
        assert result is not None
        assert result["code"] == "numeric_claim_conflict"

    def test_barely_out_of_range_conflict(self):
        """Claim $50 vs observed [77, 96]: same scale, conflict."""
        result = self._compare(50.0, [77.0, 96.45], "price 50")
        assert result is not None
        assert result["code"] == "numeric_claim_conflict"

    def test_multiplier_vs_stock_skipped(self):
        """Claim 100000 (contract multiplier) vs stock $122: >100x, skip."""
        result = self._compare(100000.0, [122.5, 130.9], "100000 multiplier")
        assert result is None


# ===========================================================================
# Fix D: safe_fallback routes unit-conflict cases to "no tool evidence"
# ===========================================================================

class TestFixD:
    def test_unit_conflict_override_chinese(self):
        """When identity_required=True but all failures are numeric_claim_conflict,
        the Chinese message should be the "no tool evidence" variant."""
        ledger = GroundingLedger(run_dir=Path("/tmp/test_fix_d"), user_message="总结我的持仓")
        ledger._validations = [
            {"code": "numeric_claim_conflict", "value": 1.3, "observed_min": 77.0, "observed_max": 96.45}
        ]
        ledger._tool_failures = [{"tool": "get_market_data"}]
        msg = ledger.safe_fallback()
        assert "没有工具证据" in msg
        assert "无法安全确认标的身份" not in msg

    def test_unit_conflict_override_english(self):
        """Same test in English."""
        ledger = GroundingLedger(run_dir=Path("/tmp/test_fix_d_en"), user_message="summarize my holdings")
        ledger._identity_required = True
        ledger._validations = [
            {"code": "numeric_claim_conflict", "value": 1.3, "observed_min": 77.0, "observed_max": 96.45}
        ]
        ledger._tool_failures = [{"tool": "get_market_data"}]
        msg = ledger.safe_fallback()
        assert "without tool evidence" in msg
        assert "could not safely lock" not in msg

    def test_non_conflict_validations_preserve_identity_message(self):
        """When there are non-conflict validations, identity message is preserved."""
        ledger = GroundingLedger(run_dir=Path("/tmp/test_fix_d_preserve"), user_message="总结我的持仓")
        ledger._identity_required = True
        ledger._validations = [
            {"code": "numeric_claim_unavailable", "value": 100.0}
        ]
        ledger._tool_failures = [{"tool": "get_market_data"}]
        msg = ledger.safe_fallback()
        assert "无法安全确认标的身份" in msg

    def test_mixed_validations_preserve_identity_message(self):
        """When there are mixed validations (conflict + other), identity message."""
        ledger = GroundingLedger(run_dir=Path("/tmp/test_fix_d_mixed"), user_message="总结我的持仓")
        ledger._identity_required = True
        ledger._validations = [
            {"code": "numeric_claim_conflict", "value": 1.3},
            {"code": "numeric_claim_unavailable", "value": 100.0},
        ]
        ledger._tool_failures = [{"tool": "get_market_data"}]
        msg = ledger.safe_fallback()
        assert "无法安全确认标的身份" in msg

    def test_non_market_question_gets_new_message(self):
        """Non-market question (no identity) gets the "no tool evidence" message."""
        ledger = GroundingLedger(run_dir=Path("/tmp/test_fix_d_nonmarket"), user_message="how many alphas are there")
        assert not ledger._identity_required
        ledger._validations = [{"code": "numeric_claim_conflict", "value": 1.3}]
        ledger._tool_failures = [{"tool": "get_market_data"}]
        msg = ledger.safe_fallback()
        assert "without tool evidence" in msg


# ===========================================================================
# Range check: values within observed [min, max] should not conflict
# ===========================================================================

class TestRangeCheck:
    """Tests for the range check fix: values within observed [min, max] are valid."""

    def _make_ledger(self, user_message="test"):
        return GroundingLedger(run_dir=Path("/tmp/test_range"), user_message=user_message)

    def _compare(self, value, observed, claim="test claim"):
        ledger = self._make_ledger()
        records = [FakeRecord("AAPL", v, "close") for v in observed]
        return ledger._compare_price_claim(
            value=value, records=records, field_name=None,
            date_value=None, symbol="AAPL", claim=claim,
        )

    def test_value_within_range_no_conflict(self):
        """85 within [77, 96.45] should NOT conflict."""
        result = self._compare(85.0, [77.0, 96.45], "average ~85")
        assert result is None

    def test_value_at_min_boundary_no_conflict(self):
        """77 (exact min) should NOT conflict."""
        result = self._compare(77.0, [77.0, 96.45], "low 77")
        assert result is None

    def test_value_at_max_boundary_no_conflict(self):
        """96.45 (exact max) should NOT conflict."""
        result = self._compare(96.45, [77.0, 96.45], "high 96.45")
        assert result is None

    def test_value_just_outside_range_conflict(self):
        """76.0 (below min 77, outside 0.5% tolerance) should conflict."""
        result = self._compare(76.0, [77.0, 96.45], "price 76.0")
        assert result is not None
        assert result["code"] == "numeric_claim_conflict"

    def test_value_far_outside_range_conflict(self):
        """200 (far above max 96.45) should conflict."""
        result = self._compare(200.0, [77.0, 96.45], "price 200")
        assert result is not None
        assert result["code"] == "numeric_claim_conflict"

    def test_average_calculation_no_conflict(self):
        """Average of 77 and 96.45 = 86.725 should NOT conflict."""
        result = self._compare(86.725, [77.0, 96.45], "average 86.7")
        assert result is None


# ===========================================================================
# Safe fallback: only trigger "price conflict" message when there are
# actual numeric_claim_conflict failures
# ===========================================================================

class TestSafeFallbackCategorization:
    """Tests for safe_fallback only triggering price conflict on actual conflicts."""

    def _make_ledger(self, user_message="总结我的持仓"):
        ledger = GroundingLedger(
            run_dir=Path("/tmp/test_sfb"),
            user_message=user_message,
        )
        ledger._identity_required = True
        return ledger

    def _add_validations(self, ledger, validations):
        """Add validation results via the proper record path."""
        for v in validations:
            ledger._validations.append(
                {
                    "attempt": len(ledger._validations) + 1,
                    "checked_at": "2024-01-01T00:00:00",
                    "content_sha256": "abc123",
                    "valid": False,
                    "issues": [v],
                }
            )

    def test_non_conflict_validation_does_not_trigger_price_message(self):
        """data_source_not_surfaced should NOT trigger the price conflict message."""
        ledger = self._make_ledger()
        ledger._evidence.append(FakeRecord("03690.HK", 85.0, "close"))
        self._add_validations(ledger, [
            {"code": "data_source_not_surfaced", "sources": ["tencent"]},
        ])
        msg = ledger.safe_fallback()
        # Should NOT be the price conflict message
        assert "价格证据冲突" not in msg
        assert "无法安全确认" in msg  # Falls through to identity message

    def test_conflict_validation_triggers_price_message(self):
        """numeric_claim_conflict SHOULD trigger the price conflict message."""
        ledger = self._make_ledger()
        ledger._evidence.append(FakeRecord("03690.HK", 77.0, "close"))
        ledger._evidence.append(FakeRecord("03690.HK", 96.45, "close"))
        self._add_validations(ledger, [
            {"code": "numeric_claim_conflict", "value": 85.0},
        ])
        msg = ledger.safe_fallback()
        # Price conflict message contains "避免...冲突" in Chinese
        assert "冲突" in msg and "价格" in msg

    def test_mixed_validations_with_conflict_triggers_price_message(self):
        """Mixed validations with at least one conflict trigger price message."""
        ledger = self._make_ledger()
        ledger._evidence.append(FakeRecord("03690.HK", 77.0, "close"))
        ledger._evidence.append(FakeRecord("03690.HK", 96.45, "close"))
        self._add_validations(ledger, [
            {"code": "numeric_claim_conflict", "value": 85.0},
            {"code": "data_source_not_surfaced", "sources": ["tencent"]},
        ])
        msg = ledger.safe_fallback()
        assert "冲突" in msg and "价格" in msg
