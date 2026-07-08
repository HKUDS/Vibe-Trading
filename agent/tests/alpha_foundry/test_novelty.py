from __future__ import annotations

import pandas as pd

from src.alpha_foundry.novelty import compute_novelty, novelty_decision


def _factor(scale: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=6, freq="D")
    cols = [f"S{i}" for i in range(8)]
    return pd.DataFrame(
        [[scale * (j + day / 10.0) for j in range(len(cols))] for day in range(len(idx))],
        index=idx,
        columns=cols,
    )


def test_duplicate_factor_hard_fails() -> None:
    factor = _factor()

    metrics = compute_novelty(candidate=factor, existing={"same": factor.copy()})

    assert metrics.max_factor_rank_corr_to_existing > 0.99
    assert novelty_decision(metrics) == "DUPLICATE_ALPHA"


def test_nonduplicate_factor_has_lower_rank_correlation() -> None:
    factor = _factor()
    reversed_factor = -factor

    metrics = compute_novelty(candidate=factor, existing={"reverse": reversed_factor})

    assert metrics.max_factor_rank_corr_to_existing < 0.0
    assert novelty_decision(metrics) is None
