from __future__ import annotations

from src.reliability.quant.neutralization import (
    build_neutralized_ic_report,
    select_industry_classification,
)


def test_industry_classification_fallbacks() -> None:
    assert select_industry_classification(
        wind=None,
        citic="citic_l1",
        sw="sw_l1",
    ).source == "citic_l1"

    unavailable = select_industry_classification(wind=None, citic=None, sw=None)
    assert unavailable.source == "unavailable"
    assert any(
        issue.code == "QUANT_INDUSTRY_CLASSIFICATION_UNAVAILABLE"
        for issue in unavailable.warnings
    )


def test_neutralized_ic_warning_when_style_exposure_large() -> None:
    report = build_neutralized_ic_report(
        ic_raw=0.06,
        ic_size_neutral=0.04,
        ic_industry_neutral=0.035,
        ic_double_neutral=0.02,
        classification_source="wind_l1",
        taxonomy="Wind",
        as_of="signal_date",
    )

    assert report.selected_ic == 0.02
    assert any(
        issue.code == "QUANT_STYLE_INDUSTRY_EXPOSURE_LARGE"
        for issue in report.warnings
    )


def test_neutralized_ic_unavailable_industry_falls_back_to_size() -> None:
    report = build_neutralized_ic_report(
        ic_raw=0.03,
        ic_size_neutral=0.025,
        ic_industry_neutral=None,
        ic_double_neutral=None,
        classification_source="unavailable",
        taxonomy="unavailable",
        as_of="signal_date",
    )

    assert report.selected_ic == 0.025
    assert report.ic_industry_neutral is None
    assert report.ic_double_neutral is None
    assert any(
        issue.code == "QUANT_INDUSTRY_CLASSIFICATION_UNAVAILABLE"
        for issue in report.warnings
    )
