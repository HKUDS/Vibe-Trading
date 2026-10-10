import numpy as np
import pandas as pd
from backtest.regime import compute_edge_density, detect_regimes


def test_constant_asset_does_not_claim_zero_correlation_density():
    returns = pd.DataFrame({"flat": [0.01] * 4, "variable": [1.0, 2.0, 1.0, 3.0]})
    density = compute_edge_density(returns, corr_window=3)
    assert density.isna().all()


def test_incomplete_pair_matrix_is_unknown_not_a_smaller_density():
    returns = pd.DataFrame(
        {"flat": [0.01] * 4, "a": [1.0, 2.0, 1.0, 3.0], "b": [1.0, 2.0, 1.0, 3.0]}
    )
    assert compute_edge_density(returns, corr_window=3).isna().all()


def test_valid_low_density_still_exits_and_unknown_density_keeps_state():
    returns = pd.DataFrame({"a": [1.0, 2.0, 1.0], "b": [1.0, 2.0, 1.0]})
    assert compute_edge_density(returns, corr_window=3).iloc[-1] == 1.0
    actual = detect_regimes(pd.Series([1.0, np.nan, 0.0]), smooth_window=1)
    assert actual["fused"].tolist() == [1, 1, 0]
