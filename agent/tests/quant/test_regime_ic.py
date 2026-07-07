from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from src.reliability.quant.regime import (
    RegimeLabelArtifactRef,
    build_regime_ic_report,
)


def test_regime_labels_artifact_ref_not_dataframe_in_protocol() -> None:
    ref = RegimeLabelArtifactRef(
        artifact_ref="artifact://sha256/" + "a" * 64,
        sha256="a" * 64,
        calendar="XSHG",
        as_of_policy="as_of=signal_date",
    )

    assert ref.artifact_ref.startswith("artifact://")

    with pytest.raises(ValidationError):
        RegimeLabelArtifactRef(
            artifact_ref="artifact://sha256/" + "a" * 64,
            sha256="a" * 64,
            calendar="XSHG",
            as_of_policy="as_of=signal_date",
            labels=pd.Series(["sideways"]),
        )


def test_regime_negative_ic_caps_conclusion() -> None:
    report = build_regime_ic_report(
        regime_ic={
            "bull_market": 0.04,
            "bear_market": -0.02,
            "sideways": 0.03,
            "full_sample": 0.02,
        },
        regime_frequency={
            "bull_market": 0.30,
            "bear_market": 0.25,
            "sideways": 0.45,
        },
        regime_activation=False,
    )

    assert report.conclusion_cap == "research_candidate"
    assert any(
        issue.code == "QUANT_REGIME_NEGATIVE_IC_NO_ACTIVATION"
        for issue in report.hard_failures
    )


def test_regime_stability_near_zero_denominator_warns() -> None:
    report = build_regime_ic_report(
        regime_ic={
            "bull_market": 0.001,
            "bear_market": -0.001,
            "sideways": 0.0,
            "full_sample": 0.01,
        },
        regime_frequency={
            "bull_market": 0.3,
            "bear_market": 0.3,
            "sideways": 0.4,
        },
        regime_activation=True,
    )

    assert report.regime_stability_score is None
    assert any(issue.code == "QUANT_REGIME_STABILITY_DENOMINATOR_NEAR_ZERO" for issue in report.warnings)
