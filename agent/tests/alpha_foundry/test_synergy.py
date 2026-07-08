from __future__ import annotations

import pandas as pd

from src.alpha_foundry.synergy import compute_marginal_portfolio_value, synergy_decision


def test_low_ic_orthogonal_factor_can_have_positive_delta_ir() -> None:
    idx = pd.date_range("2024-01-01", periods=12, freq="D")
    pool = pd.DataFrame(
        {
            "a": [0.01, -0.005] * 6,
            "b": [0.008, -0.004] * 6,
        },
        index=idx,
    )
    candidate = pd.Series([0.0, 0.006] * 6, index=idx, name="candidate")

    result = compute_marginal_portfolio_value(candidate, pool)

    assert result["delta_ir"] > 0
    assert synergy_decision(result) == "ACCEPT_INCREMENTAL_ALPHA"


def test_synergy_rejects_redundant_high_correlation_factor() -> None:
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    base = pd.Series([0.01, -0.004] * 5, index=idx, name="base")
    pool = pd.DataFrame({"base": base})
    candidate = base.copy()
    candidate.name = "candidate"

    result = compute_marginal_portfolio_value(candidate, pool)

    assert result["correlation_to_pool"] > 0.99
    assert synergy_decision(result) == "REJECT_REDUNDANT_ALPHA"
