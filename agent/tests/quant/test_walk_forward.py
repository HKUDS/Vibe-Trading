from __future__ import annotations

import pytest

from src.reliability.quant.factor_eval import build_walk_forward_report


def test_walk_forward_is_ic_near_zero_hard_failure() -> None:
    report = build_walk_forward_report(
        effective_fold_count=6,
        is_ic_mean=0.001,
        oos_ic_mean=0.02,
        oos_ir=0.4,
        negative_oos_fold_ratio=0.1,
    )

    assert report.oos_is_ic_ratio is None
    assert report.passed is False
    assert any(issue.code == "QUANT_IS_IC_NEAR_ZERO" for issue in report.hard_failures)


def test_walk_forward_ratio_safe_division() -> None:
    report = build_walk_forward_report(
        effective_fold_count=6,
        is_ic_mean=0.10,
        oos_ic_mean=0.04,
        oos_ir=0.4,
        negative_oos_fold_ratio=0.1,
    )

    assert report.oos_is_ic_ratio == pytest.approx(0.4)
    assert report.passed is True


def test_walk_forward_failure_definitions() -> None:
    report = build_walk_forward_report(
        effective_fold_count=5,
        is_ic_mean=0.05,
        oos_ic_mean=-0.01,
        oos_ir=-0.2,
        negative_oos_fold_ratio=0.5,
    )

    assert report.passed is False
    assert "effective_fold_count < 6" in report.failure_reasons
    assert "OOS IC mean < 0" in report.failure_reasons
    assert "OOS IR < 0" in report.failure_reasons
    assert "negative OOS fold ratio > 40%" in report.failure_reasons
