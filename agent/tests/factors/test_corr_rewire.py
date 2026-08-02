"""Semantic tests for ``zoo/academic/corr_rewire``.

The AST purity gate and the look-ahead sentinel cover safety; these tests
pin the factor's *meaning*:

* an asset that decouples from its bloc must rank last (most negative
  factor value — it rewired the most, and the factor is stability-high);
* columns with insufficient in-window coverage go NaN without poisoning
  their peers' scores;
* output is invariant to column order (permutation equivariance);
* warmup rows are NaN, post-warmup rows are populated.

All panels are seeded and deterministic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.zoo.academic.corr_rewire import compute

N_BARS = 300
N_BLOC = 5  # correlated bloc members; one extra decoupling asset is added


def _bloc_panel(decouple_last: int = 25, seed: int = 7) -> dict[str, pd.DataFrame]:
    """Panel of one tight return bloc plus one asset that decouples late.

    Assets BLOC0..BLOC4 share a common return driver for all bars. DECOUPLER
    follows the same driver until the last ``decouple_last`` bars, then
    switches to independent noise of the same scale — so at the final bar its
    trailing 20-bar correlation row has collapsed while its 120-bar calm
    baseline is still bloc-like.

    Args:
        decouple_last: Bars at the end where DECOUPLER goes independent.
        seed: RNG seed (panel is fully deterministic).

    Returns:
        Panel dict with a ``close`` wide DataFrame.
    """
    rng = np.random.default_rng(seed)
    common = rng.normal(0.0, 0.02, N_BARS)
    cols = {}
    for i in range(N_BLOC):
        cols[f"BLOC{i}"] = common + rng.normal(0.0, 0.006, N_BARS)
    dec = common + rng.normal(0.0, 0.006, N_BARS)
    dec[-decouple_last:] = rng.normal(0.0, 0.02, decouple_last)
    cols["DECOUPLER"] = dec

    returns = pd.DataFrame(cols, index=pd.date_range("2024-01-01", periods=N_BARS))
    close = 100.0 * (1.0 + returns).cumprod()
    return {"close": close}


def test_decoupling_asset_ranks_last() -> None:
    """The asset whose correlation row rewired the most gets the lowest value."""
    out = compute(_bloc_panel())
    last = out.iloc[-1]
    assert last.notna().all()
    assert last.idxmin() == "DECOUPLER"
    # Cross-sectionally it should be a clear outlier, not a coin flip.
    assert last["DECOUPLER"] < -1.0


def test_low_coverage_column_is_nan_without_poisoning_peers() -> None:
    """A column below the 90% in-window coverage floor is NaN; peers are not."""
    panel = _bloc_panel()
    close = panel["close"].copy()
    close.iloc[::2, close.columns.get_loc("BLOC0")] = np.nan  # 50% coverage
    out = compute({"close": close})
    last = out.iloc[-1]
    assert np.isnan(last["BLOC0"])
    assert last.drop("BLOC0").notna().all()


def test_column_order_invariance() -> None:
    """Reversing panel column order must not change any per-symbol value."""
    panel = _bloc_panel()
    out = compute(panel)
    reversed_close = panel["close"].iloc[:, ::-1]
    out_reversed = compute({"close": reversed_close})
    pd.testing.assert_frame_equal(out_reversed[out.columns], out, check_exact=False, atol=1e-12)


def test_warmup_rows_are_nan_then_values_appear() -> None:
    """Everything before the 140-bar warmup is NaN; afterwards values exist."""
    out = compute(_bloc_panel())
    warmup = 120 + 20  # calm_window + event_window, matching the module
    assert out.iloc[: warmup - 1].isna().all().all()
    assert out.iloc[warmup - 1 :].notna().any().any()


def test_declared_warmup_covers_first_valid_row() -> None:
    """``min_warmup_bars`` in the meta must not promise values earlier than real."""
    from src.factors.zoo.academic.corr_rewire import __alpha_meta__

    out = compute(_bloc_panel())
    first_valid = int(np.argmax(out.notna().any(axis=1).to_numpy()))
    assert __alpha_meta__["min_warmup_bars"] >= first_valid


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
