"""Qlib's BETA and RESI features share one trailing OLS fit."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

_WINDOWS = (5, 10, 20, 30, 60)


def _close_through(window: int) -> pd.DataFrame:
    steps = np.arange(window + 1, dtype=np.float64)
    values = 30.0 + 0.7 * steps + 0.11 * steps**2 + np.sin(steps * 0.8)
    return pd.DataFrame(values, columns=["A"])


def _fit(window: np.ndarray) -> tuple[float, float]:
    slope, intercept = np.polyfit(np.arange(window.size, dtype=np.float64), window, 1)
    return float(slope), float(intercept)


@pytest.mark.parametrize("window", _WINDOWS)
def test_beta_is_the_ols_slope_over_latest_close(window: int) -> None:
    close = _close_through(window)
    module = importlib.import_module(f"src.factors.zoo.qlib158.beta{window}")

    actual = module.compute({"close": close})["A"]

    for end in (window - 1, window):
        values = close["A"].iloc[end - window + 1 : end + 1].to_numpy()
        slope, _ = _fit(values)
        assert actual.iloc[end] == pytest.approx(slope / values[-1], abs=1e-12)


@pytest.mark.parametrize("window", _WINDOWS)
def test_resi_is_the_latest_point_residual_over_latest_close(window: int) -> None:
    close = _close_through(window)
    module = importlib.import_module(f"src.factors.zoo.qlib158.resi{window}")

    actual = module.compute({"close": close})["A"]

    for end in (window - 1, window):
        values = close["A"].iloc[end - window + 1 : end + 1].to_numpy()
        slope, intercept = _fit(values)
        fitted = intercept + slope * (window - 1)
        assert actual.iloc[end] == pytest.approx(
            (values[-1] - fitted) / values[-1], abs=1e-12
        )


@pytest.mark.parametrize("stem", ("beta", "resi"))
def test_regression_features_require_a_complete_gap_free_window(stem: str) -> None:
    close = pd.DataFrame(
        {"A": [20.0, 21.0, 23.0, 24.0, 27.0, 28.0, 32.0, 33.0, 37.0, 39.0, 42.0, 46.0]}
    )
    close.iloc[3, 0] = np.nan
    module = importlib.import_module(f"src.factors.zoo.qlib158.{stem}5")

    actual = module.compute({"close": close})["A"]

    assert actual.iloc[3:8].isna().all()
    assert actual.iloc[8:].notna().all()
