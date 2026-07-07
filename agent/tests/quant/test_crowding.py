from __future__ import annotations

from src.reliability.quant.crowding import build_crowding_report


def test_crowding_high_without_stress_caps_conclusion() -> None:
    report = build_crowding_report(
        crowding_tier="academic_public",
        years_public=6,
        in_public_library=True,
        stress_periods_tested=[],
    )

    assert report.crowding_risk == "high"
    assert report.conclusion_cap == "research_candidate"
    assert any(
        issue.code == "QUANT_HIGH_CROWDING_NO_STRESS_TEST"
        for issue in report.hard_failures
    )
