from __future__ import annotations

import pandas as pd
import pytest

from src.alpha_quality.ic_metrics import compute_ic_metrics, compute_ic_series_safe


def _ranked_frame(n_dates: int = 8, n_symbols: int = 6) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n_dates, freq="D")
    cols = [f"S{i}" for i in range(n_symbols)]
    return pd.DataFrame(
        [[float(j) for j in range(n_symbols)] for _ in range(n_dates)],
        index=idx,
        columns=cols,
    )


def test_compute_ic_series_safe_aligns_and_masks() -> None:
    factor = _ranked_frame()
    returns = factor.copy()
    mask = pd.DataFrame(True, index=factor.index, columns=factor.columns)
    mask.iloc[0, :2] = False

    ic = compute_ic_series_safe(factor, returns, mask, min_cross_section=5)

    assert len(ic) == len(factor) - 1
    assert ic.iloc[0] == pytest.approx(1.0)


def test_compute_ic_metrics_uses_newey_west_for_overlapping_horizon() -> None:
    factor = _ranked_frame(n_dates=10)
    returns = factor.copy()
    mask = pd.DataFrame(True, index=factor.index, columns=factor.columns)

    metrics = compute_ic_metrics(factor, returns, horizon=5, valid_mask=mask)

    assert metrics.rank_ic_mean == pytest.approx(1.0)
    assert metrics.t_stat_method == "newey_west"
    assert metrics.n_obs == 10


def test_compute_ic_metrics_uses_standard_t_for_one_day_horizon() -> None:
    factor = _ranked_frame(n_dates=10)
    returns = factor.copy()
    mask = pd.DataFrame(True, index=factor.index, columns=factor.columns)

    metrics = compute_ic_metrics(factor, returns, horizon=1, valid_mask=mask)

    assert metrics.t_stat_method == "standard"
    assert metrics.n_obs == 10
