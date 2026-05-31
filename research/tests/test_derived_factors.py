import sys
from pathlib import Path
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

import numpy as np
import pandas as pd
import pytest

from lib.derived_factors import (
    basis_factors,
    funding_factors,
    oi_factors,
    SCREEN_MOM_HOURS,
    OI_MOM_HOURS,
    SCREEN_ZSCORE_DAYS,
)

N = 800  # enough bars to exceed the 720-bar rolling window


def _index(n: int = N) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="1h")


# ─── basis_factors ────────────────────────────────────────────────────────────

def test_basis_rel_exact_values():
    idx = _index()
    perp = pd.Series(np.linspace(100, 110, N), index=idx)
    spot = pd.Series(np.linspace(99, 109, N), index=idx)
    out = basis_factors(perp, spot)
    expected = (perp - spot) / spot
    pd.testing.assert_series_equal(out["basis_rel"], expected, check_names=False)


def test_basis_mom_24bar_diff():
    idx = _index()
    perp = pd.Series(np.linspace(100, 110, N), index=idx)
    spot = pd.Series(np.linspace(99, 109, N), index=idx)
    out = basis_factors(perp, spot)
    basis_rel = out["basis_rel"]
    i = 100
    expected_mom_at_i = basis_rel.iloc[i] - basis_rel.iloc[i - SCREEN_MOM_HOURS]
    assert abs(out["basis_mom"].iloc[i] - expected_mom_at_i) < 1e-12


def test_basis_output_index_matches_input():
    idx = _index()
    perp = pd.Series(np.ones(N), index=idx)
    spot = pd.Series(np.ones(N), index=idx)
    out = basis_factors(perp, spot)
    for key in ("basis_rel", "basis_z", "basis_mom"):
        assert out[key].index.equals(idx), f"{key} index mismatch"


def test_basis_no_lookahead():
    idx = _index()
    perp = pd.Series(np.random.default_rng(0).random(N) + 100, index=idx)
    spot = pd.Series(np.random.default_rng(1).random(N) + 99, index=idx)
    full = basis_factors(perp, spot)
    truncated = basis_factors(perp.iloc[:-1], spot.iloc[:-1])
    # Last common index point must agree
    for key in ("basis_rel", "basis_z", "basis_mom"):
        v_full = full[key].iloc[-2]
        v_trunc = truncated[key].iloc[-1]
        assert abs(v_full - v_trunc) < 1e-12 or (np.isnan(v_full) and np.isnan(v_trunc)), \
            f"look-ahead detected in {key}"


def test_basis_spot_reindex_ffill():
    # spot has fewer bars — should be forward-filled onto perp index
    perp_idx = _index()
    spot_idx = perp_idx[::2]  # every other hour
    perp = pd.Series(np.linspace(100, 110, N), index=perp_idx)
    spot = pd.Series(np.linspace(99, 104, len(spot_idx)), index=spot_idx)
    out = basis_factors(perp, spot)
    assert out["basis_rel"].index.equals(perp_idx)


# ─── funding_factors ──────────────────────────────────────────────────────────

def test_funding_index_matches():
    idx = _index()
    funding = pd.Series(np.random.default_rng(2).random(N) * 0.001, index=idx)
    out = funding_factors(funding)
    for key in ("funding_z", "funding_mom"):
        assert out[key].index.equals(idx), f"{key} index mismatch"


def test_funding_mom_24bar_diff():
    idx = _index()
    funding = pd.Series(np.linspace(0.0001, 0.0003, N), index=idx)
    out = funding_factors(funding)
    i = 100
    expected = funding.iloc[i] - funding.iloc[i - SCREEN_MOM_HOURS]
    assert abs(out["funding_mom"].iloc[i] - expected) < 1e-15


def test_funding_values_finite():
    idx = _index()
    funding = pd.Series(np.random.default_rng(3).normal(0, 0.0001, N), index=idx)
    out = funding_factors(funding)
    # After warm-up, z-scores should be finite
    assert np.all(np.isfinite(out["funding_z"].iloc[SCREEN_ZSCORE_DAYS * 24 :]))


def test_funding_no_lookahead():
    idx = _index()
    funding = pd.Series(np.random.default_rng(4).random(N), index=idx)
    full = funding_factors(funding)
    trunc = funding_factors(funding.iloc[:-1])
    for key in ("funding_z", "funding_mom"):
        v_full = full[key].iloc[-2]
        v_trunc = trunc[key].iloc[-1]
        assert abs(v_full - v_trunc) < 1e-12 or (np.isnan(v_full) and np.isnan(v_trunc)), \
            f"look-ahead detected in {key}"


# ─── oi_factors ───────────────────────────────────────────────────────────────

def test_oi_divergence_positive_same_direction():
    idx = _index()
    # Step up at bar 25; pct_change(24) at bar 48 compares iloc[48]=1100 to iloc[24]=1000 → +10%
    oi = pd.Series(np.ones(N) * 1000.0, index=idx)
    close = pd.Series(np.ones(N) * 50000.0, index=idx)
    oi.iloc[25:] = 1100.0
    close.iloc[25:] = 55000.0
    out = oi_factors(oi, close)
    assert out["oi_price_divergence"].iloc[48] > 0


def test_oi_divergence_negative_opposite_direction():
    idx = _index()
    # OI rises, price falls — product must be negative
    oi = pd.Series(np.ones(N) * 1000.0, index=idx)
    close = pd.Series(np.ones(N) * 50000.0, index=idx)
    oi.iloc[25:] = 1100.0
    close.iloc[25:] = 45000.0
    out = oi_factors(oi, close)
    assert out["oi_price_divergence"].iloc[48] < 0


def test_oi_mom_72bar_pct_change():
    idx = _index()
    oi = pd.Series(np.linspace(1000, 2000, N), index=idx)
    close = pd.Series(np.ones(N) * 50000.0, index=idx)
    out = oi_factors(oi, close)
    i = 200
    expected = oi.pct_change(OI_MOM_HOURS).iloc[i]
    assert abs(out["oi_mom"].iloc[i] - expected) < 1e-12


def test_oi_output_index_matches():
    idx = _index()
    oi = pd.Series(np.ones(N) * 1000.0, index=idx)
    close = pd.Series(np.ones(N) * 50000.0, index=idx)
    out = oi_factors(oi, close)
    for key in ("oi_z", "oi_price_divergence", "oi_mom"):
        assert out[key].index.equals(idx), f"{key} index mismatch"


def test_oi_no_lookahead():
    rng = np.random.default_rng(5)
    idx = _index()
    oi = pd.Series(rng.random(N) * 1000 + 500, index=idx)
    close = pd.Series(rng.random(N) * 10000 + 40000, index=idx)
    full = oi_factors(oi, close)
    trunc = oi_factors(oi.iloc[:-1], close.iloc[:-1])
    for key in ("oi_z", "oi_price_divergence", "oi_mom"):
        v_full = full[key].iloc[-2]
        v_trunc = trunc[key].iloc[-1]
        assert abs(v_full - v_trunc) < 1e-12 or (np.isnan(v_full) and np.isnan(v_trunc)), \
            f"look-ahead detected in {key}"
