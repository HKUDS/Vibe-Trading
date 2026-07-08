from __future__ import annotations

import pandas as pd
import pytest

from src.alpha_foundry.residualize import residualize_candidate_by_date


def test_residualize_candidate_by_date_removes_linear_base_exposure() -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    cols = [f"S{i}" for i in range(40)]
    base = pd.DataFrame(
        [[float(j) for j in range(len(cols))] for _ in idx],
        index=idx,
        columns=cols,
    )
    candidate = base * 2.0 + 5.0

    residual = residualize_candidate_by_date(candidate, {"base": base})

    assert residual.stack().abs().mean() == pytest.approx(0.0, abs=1e-8)


def test_residualize_skips_dates_with_too_few_symbols() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    cols = ["A", "B", "C"]
    base = pd.DataFrame([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]], index=idx, columns=cols)
    candidate = base.copy()

    residual = residualize_candidate_by_date(candidate, {"base": base}, min_cross_section=30)

    assert residual.isna().all().all()
