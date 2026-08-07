"""Phase 2 decay-classification contract for ``src.strategy_discovery.models``.

Pure read-time decay (plan D1-D3): the verdict comes from the evidence row's
own ``date_ranges`` window end relative to an injected clock — never from
persisted state, never from the wall clock. Every assertion here injects a
fixed ``today``; ``date.today()`` never appears in this file.

Pinned semantics:

* Boundary rule — exact threshold belongs to the STRICTER side:
  ``age == DECAY_STALE_EVIDENCE_AGE_DAYS`` ⇒ stale,
  ``age == DECAY_AGING_EVIDENCE_AGE_DAYS`` ⇒ aging.
* Negative-age clamp — month-granular windows are end-anchored to month-end,
  so a window ending in the current month can postdate ``today``; the age is
  clamped to 0 (fresh), never negative.
* Fail-closed — unparseable/empty ``date_ranges`` classify as stale.
* ``staleness_days`` (from ``last_verified``) is report-only: malformed
  input yields ``None`` and never influences the verdict.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

try:
    from src.strategy_discovery import models as sd_models

    DECAY_AVAILABLE = True
except ImportError:
    sd_models = None
    DECAY_AVAILABLE = False

requires_decay = pytest.mark.skipif(
    not DECAY_AVAILABLE,
    reason="waiting on src.strategy_discovery.models decay helpers (issue #969 Phase 2)",
)

#: Fixed window used for boundary math; end-anchored to 2026-01-31.
JAN_2026 = ("2026-01 to 2026-01",)
WINDOW_END = date(2026, 1, 31)


@requires_decay
class TestDecayConstants:
    def test_vocabulary_exact(self) -> None:
        assert sd_models.DECAY_FRESH == "fresh"
        assert sd_models.DECAY_AGING == "aging"
        assert sd_models.DECAY_STALE == "stale"

    def test_thresholds_match_quarterly_cadence(self) -> None:
        assert sd_models.DECAY_AGING_EVIDENCE_AGE_DAYS == 90
        assert sd_models.DECAY_STALE_EVIDENCE_AGE_DAYS == 180


@requires_decay
class TestEvidenceWindowEnd:
    def test_single_range_is_month_end_anchored(self) -> None:
        assert sd_models.evidence_window_end(["2022-01 to 2022-12"]) == date(
            2022, 12, 31
        )
        assert sd_models.evidence_window_end(["2022-01 to 2022-02"]) == date(
            2022, 2, 28
        )

    def test_latest_end_wins_across_ranges(self) -> None:
        assert sd_models.evidence_window_end(
            ["2018-01 to 2018-12", "2022-01 to 2022-06", "2020-01 to 2020-03"]
        ) == date(2022, 6, 30)

    def test_malformed_entries_contribute_nothing(self) -> None:
        assert sd_models.evidence_window_end(
            ["garbage", "2022-01 to 2022-12", "2022-99 to nope", 123]
        ) == date(2022, 12, 31)

    def test_nothing_parseable_yields_none(self) -> None:
        assert sd_models.evidence_window_end([]) is None
        assert sd_models.evidence_window_end(["garbage"]) is None
        assert sd_models.evidence_window_end(["2022-01 to nope"]) is None
        assert sd_models.evidence_window_end([123, None]) is None


@requires_decay
class TestEvidenceAgeDays:
    def test_age_is_days_since_window_end(self) -> None:
        today = WINDOW_END + timedelta(days=10)
        assert sd_models.evidence_age_days(JAN_2026, today) == 10

    def test_negative_age_clamps_to_zero_for_current_month_window(self) -> None:
        # Window ends 2026-08-31 (month-end anchor) but today is 2026-08-06:
        # the raw difference is negative and must clamp to 0, not go below.
        assert (
            sd_models.evidence_age_days(("2026-08 to 2026-08",), date(2026, 8, 6)) == 0
        )

    def test_exact_threshold_ages(self) -> None:
        stale_edge = WINDOW_END + timedelta(
            days=sd_models.DECAY_STALE_EVIDENCE_AGE_DAYS
        )
        assert sd_models.evidence_age_days(JAN_2026, stale_edge) == 180
        aging_edge = WINDOW_END + timedelta(
            days=sd_models.DECAY_AGING_EVIDENCE_AGE_DAYS
        )
        assert sd_models.evidence_age_days(JAN_2026, aging_edge) == 90

    def test_unparseable_ranges_yield_none(self) -> None:
        assert sd_models.evidence_age_days((), date(2026, 8, 6)) is None
        assert sd_models.evidence_age_days(("garbage",), date(2026, 8, 6)) is None


@requires_decay
class TestStalenessDays:
    def test_days_since_last_verified(self) -> None:
        assert sd_models.staleness_days("2026-08-01", date(2026, 8, 6)) == 5

    def test_malformed_or_empty_yields_none(self) -> None:
        assert sd_models.staleness_days("", date(2026, 8, 6)) is None
        assert sd_models.staleness_days("not-a-date", date(2026, 8, 6)) is None
        assert sd_models.staleness_days("2026-13-45", date(2026, 8, 6)) is None
        assert sd_models.staleness_days(None, date(2026, 8, 6)) is None  # type: ignore[arg-type]

    def test_future_last_verified_clamps_to_zero(self) -> None:
        assert sd_models.staleness_days("2026-08-31", date(2026, 8, 6)) == 0


@requires_decay
class TestClassifyDecay:
    def test_exact_stale_threshold_is_stale(self) -> None:
        today = WINDOW_END + timedelta(days=180)
        assert sd_models.classify_decay(JAN_2026, today) == sd_models.DECAY_STALE

    def test_one_day_inside_stale_threshold_is_aging(self) -> None:
        today = WINDOW_END + timedelta(days=179)
        assert sd_models.classify_decay(JAN_2026, today) == sd_models.DECAY_AGING

    def test_exact_aging_threshold_is_aging(self) -> None:
        today = WINDOW_END + timedelta(days=90)
        assert sd_models.classify_decay(JAN_2026, today) == sd_models.DECAY_AGING

    def test_one_day_inside_aging_threshold_is_fresh(self) -> None:
        today = WINDOW_END + timedelta(days=89)
        assert sd_models.classify_decay(JAN_2026, today) == sd_models.DECAY_FRESH

    def test_future_window_is_fresh_via_clamp(self) -> None:
        assert (
            sd_models.classify_decay(("2026-08 to 2026-08",), date(2026, 8, 6))
            == sd_models.DECAY_FRESH
        )

    def test_unparseable_ranges_are_stale_fail_closed(self) -> None:
        today = date(2026, 8, 6)
        assert sd_models.classify_decay((), today) == sd_models.DECAY_STALE
        assert sd_models.classify_decay(("garbage",), today) == sd_models.DECAY_STALE
        assert (
            sd_models.classify_decay(("2026-01 to nope",), today)
            == sd_models.DECAY_STALE
        )

    def test_thresholds_overridable_per_call(self) -> None:
        ranges = ("2026-01 to 2026-01",)
        assert (
            sd_models.classify_decay(ranges, WINDOW_END + timedelta(days=15))
            == sd_models.DECAY_FRESH
        )
        assert (
            sd_models.classify_decay(
                ranges,
                WINDOW_END + timedelta(days=15),
                aging_days=10,
                stale_days=20,
            )
            == sd_models.DECAY_AGING
        )
        assert (
            sd_models.classify_decay(
                ranges,
                WINDOW_END + timedelta(days=25),
                aging_days=10,
                stale_days=20,
            )
            == sd_models.DECAY_STALE
        )


@requires_decay
class TestDecayWarning:
    def test_stale_warning_carries_prefix_and_day_count(self) -> None:
        warning = sd_models.decay_warning(sd_models.DECAY_STALE, 200)
        assert warning is not None
        assert warning.startswith("stale-evidence:")
        assert "200" in warning
        assert str(sd_models.DECAY_STALE_EVIDENCE_AGE_DAYS) in warning

    def test_aged_warning_carries_prefix_and_day_count(self) -> None:
        warning = sd_models.decay_warning(sd_models.DECAY_AGING, 120)
        assert warning is not None
        assert warning.startswith("aged-evidence:")
        assert "120" in warning
        assert str(sd_models.DECAY_AGING_EVIDENCE_AGE_DAYS) in warning

    def test_fresh_and_unknown_statuses_yield_none(self) -> None:
        assert sd_models.decay_warning(sd_models.DECAY_FRESH, 5) is None
        assert sd_models.decay_warning("bogus", 5) is None

    def test_stale_with_unknown_age_still_warns_fail_closed(self) -> None:
        warning = sd_models.decay_warning(sd_models.DECAY_STALE, None)
        assert warning is not None
        assert warning.startswith("stale-evidence:")
        assert "unparseable" in warning
