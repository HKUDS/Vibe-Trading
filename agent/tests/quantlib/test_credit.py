"""Tests for src.quantlib.credit.

Note on the Altman references: what is pinned here are the *published
coefficients and cut-offs* of the three variants (Altman 1968 Z, Z' for private
firms, Z'' for non-manufacturers), with the arithmetic of each term written out
term by term so the expected value is derivable by eye rather than copied from
the implementation. No firm-level worked example is asserted, because none was
available from a source that could be checked here.
"""

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from src.quantlib.credit import (
    ALTMAN_MODELS,
    ZONE_LABELS_ZH,
    AltmanZScore,
    altman_z_score,
    credit_spread_analysis,
    distance_to_default,
    edf_reference_band,
    kmv_default_point,
    kmv_distance_to_default,
    merton_asset_solve,
    merton_model,
    spread_term_structure,
)

# One balance sheet, reused so the three variants can be compared like for like.
FIRM = dict(
    working_capital=200.0,   # X1 = 0.20
    retained_earnings=300.0,  # X2 = 0.30
    ebit=150.0,               # X3 = 0.15
    equity_value=900.0,       # X4 = 1.50
    total_liabilities=600.0,
    total_assets=1000.0,
    revenue=1200.0,           # X5 = 1.20
)


# --------------------------------------------------------------------------
# Altman Z-Score -- all three published variants
# --------------------------------------------------------------------------


def test_original_variant_uses_the_1968_coefficients():
    result = altman_z_score(**FIRM, model="original")
    expected = (
        1.2 * 0.20 + 1.4 * 0.30 + 3.3 * 0.15 + 0.6 * 1.50 + 1.0 * 1.20
    )  # 0.24 + 0.42 + 0.495 + 0.90 + 1.20 = 3.255
    assert expected == pytest.approx(3.255)
    assert result.z_score == pytest.approx(expected)
    assert (result.safe_threshold, result.distress_threshold) == (2.99, 1.81)
    assert result.zone == "safe"
    assert result.label_zh == ZONE_LABELS_ZH["safe"]


def test_prime_variant_uses_the_private_firm_coefficients():
    result = altman_z_score(**FIRM, model="prime")
    expected = (
        0.717 * 0.20 + 0.847 * 0.30 + 3.107 * 0.15 + 0.420 * 1.50 + 0.998 * 1.20
    )  # 0.1434 + 0.2541 + 0.46605 + 0.63 + 1.1976 = 2.69115
    assert expected == pytest.approx(2.69115)
    assert result.z_score == pytest.approx(expected)
    assert (result.safe_threshold, result.distress_threshold) == (2.90, 1.23)
    # 1.23 < 2.69115 < 2.90 -- the same firm that is safe on Z sits in Z''s grey
    # zone, which is the whole point of recalibrating for private firms.
    assert result.zone == "grey"


def test_double_prime_variant_drops_x5_entirely():
    result = altman_z_score(
        **{k: v for k, v in FIRM.items() if k != "revenue"}, model="double_prime"
    )
    expected = 6.56 * 0.20 + 3.26 * 0.30 + 6.72 * 0.15 + 1.05 * 1.50
    # 1.312 + 0.978 + 1.008 + 1.575 = 4.873
    assert expected == pytest.approx(4.873)
    assert result.z_score == pytest.approx(expected)
    assert (result.safe_threshold, result.distress_threshold) == (2.60, 1.10)
    assert result.zone == "safe"
    assert result.components["x5"] is None


def test_double_prime_ignores_revenue_even_when_supplied():
    with_revenue = altman_z_score(**FIRM, model="double_prime")
    without = altman_z_score(
        **{k: v for k, v in FIRM.items() if k != "revenue"}, model="double_prime"
    )
    assert with_revenue.z_score == pytest.approx(without.z_score)


def test_components_are_the_five_ratios():
    result = altman_z_score(**FIRM, model="original")
    assert result.components == pytest.approx(
        {"x1": 0.20, "x2": 0.30, "x3": 0.15, "x4": 1.50, "x5": 1.20}
    )


@pytest.mark.parametrize("model", list(ALTMAN_MODELS))
def test_zone_boundaries_follow_the_published_cutoffs(model):
    spec = ALTMAN_MODELS[model]
    # X4 is the only ratio in every variant, so drive the score through it alone.
    weight = spec.coefficients[3]
    assets = 1000.0
    liabilities = 600.0

    def score_at(target_z):
        equity = target_z / weight * liabilities
        return altman_z_score(
            working_capital=0.0,
            retained_earnings=0.0,
            ebit=0.0,
            equity_value=equity,
            total_liabilities=liabilities,
            total_assets=assets,
            revenue=0.0,
            model=model,
        )

    # The cut-offs are published to two decimals; these nudges locate them to
    # 1e-6. Landing exactly on a threshold is not asserted, because building a
    # score that is bitwise equal to it is not achievable in floating point.
    nudge = 1e-6
    assert score_at(spec.safe_threshold + nudge).zone == "safe"
    assert score_at(spec.safe_threshold - nudge).zone == "grey"
    assert score_at(spec.distress_threshold + nudge).zone == "grey"
    assert score_at(spec.distress_threshold - nudge).zone == "distress"
    mid = (spec.safe_threshold + spec.distress_threshold) / 2
    assert score_at(mid).zone == "grey"
    assert score_at(mid).label_zh == ZONE_LABELS_ZH["grey"]


def test_result_is_frozen():
    result = altman_z_score(**FIRM)
    assert isinstance(result, AltmanZScore)
    with pytest.raises(Exception):
        result.z_score = 0.0  # type: ignore[misc]


def test_altman_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="unknown model"):
        altman_z_score(**FIRM, model="z_triple_prime")


def test_altman_rejects_zero_denominators():
    with pytest.raises(ValueError, match="total_assets"):
        altman_z_score(**{**FIRM, "total_assets": 0.0})
    with pytest.raises(ValueError, match="total_liabilities"):
        altman_z_score(**{**FIRM, "total_liabilities": 0.0})


def test_altman_requires_revenue_for_the_variants_that_use_x5():
    for model in ("original", "prime"):
        with pytest.raises(ValueError, match="needs revenue"):
            altman_z_score(
                **{k: v for k, v in FIRM.items() if k != "revenue"}, model=model
            )


# --------------------------------------------------------------------------
# Merton / KMV
# --------------------------------------------------------------------------

BASE_MERTON = dict(
    equity_value=100.0, equity_vol=0.40, debt_face=100.0, risk_free=0.03, horizon=1.0
)


def test_asset_solve_satisfies_both_equations_it_was_solving():
    equity, vol, debt, rate, horizon = 100.0, 0.40, 100.0, 0.03, 1.0
    asset_value, asset_vol = merton_asset_solve(equity, vol, debt, rate, horizon)

    d1 = (
        math.log(asset_value / debt) + (rate + 0.5 * asset_vol**2) * horizon
    ) / (asset_vol * math.sqrt(horizon))
    d2 = d1 - asset_vol * math.sqrt(horizon)

    call = asset_value * norm.cdf(d1) - debt * math.exp(-rate * horizon) * norm.cdf(d2)
    assert call == pytest.approx(equity, rel=1e-9)
    assert norm.cdf(d1) * asset_vol * asset_value == pytest.approx(
        vol * equity, rel=1e-9
    )


@pytest.mark.parametrize("equity,equity_vol,debt,rate,horizon", [
    # Thin-equity, low-asset-vol issuers: the implied sigma_V lands near 1e-3 or
    # below, which is where a step-tolerance-limited root finder stops early.
    (0.5, 2.00, 500.0, 0.03, 0.25),
    (2.0, 0.80, 1000.0, 0.02, 5.00),
    (1.0, 0.25, 1000.0, 0.00, 5.00),
    (1.0, 0.10, 10000.0, 0.00, 10.00),
    (1.0, 1.50, 10000.0, 0.03, 10.00),
])
def test_asset_solve_converges_for_thin_equity_high_leverage_issuers(
    equity, equity_vol, debt, rate, horizon
):
    # These solve cleanly -- the root exists and is reachable -- so refusing them
    # would silently blank out the distressed end of the book, which is the end
    # Merton is actually used on.
    asset_value, asset_vol = merton_asset_solve(
        equity, equity_vol, debt, rate, horizon
    )
    d1 = (math.log(asset_value / debt) + (rate + 0.5 * asset_vol**2) * horizon) / (
        asset_vol * math.sqrt(horizon)
    )
    d2 = d1 - asset_vol * math.sqrt(horizon)
    call = asset_value * norm.cdf(d1) - debt * math.exp(-rate * horizon) * norm.cdf(d2)
    assert call == pytest.approx(equity, rel=1e-8)
    assert norm.cdf(d1) * asset_vol * asset_value == pytest.approx(
        equity_vol * equity, rel=1e-8
    )
    assert asset_value > equity
    assert 0.0 < asset_vol < equity_vol


def test_asset_value_exceeds_equity_and_asset_vol_is_below_equity_vol():
    result = merton_model(**BASE_MERTON)
    assert result.asset_value > BASE_MERTON["equity_value"]
    assert 0.0 < result.asset_vol < BASE_MERTON["equity_vol"]


def test_asset_solve_rejects_non_positive_inputs():
    for bad in ("equity_value", "equity_vol", "debt_face", "horizon"):
        with pytest.raises(ValueError, match="must all be positive"):
            merton_asset_solve(**{**BASE_MERTON, bad: 0.0})


def test_distance_to_default_falls_monotonically_as_leverage_rises():
    dds = [
        merton_model(**{**BASE_MERTON, "debt_face": face}).distance_to_default
        for face in (40.0, 60.0, 80.0, 100.0, 140.0, 200.0, 300.0)
    ]
    assert all(later < earlier for earlier, later in zip(dds, dds[1:])), dds


def test_distance_to_default_falls_monotonically_as_volatility_rises():
    dds = [
        merton_model(**{**BASE_MERTON, "equity_vol": vol}).distance_to_default
        for vol in (0.10, 0.20, 0.30, 0.45, 0.60, 0.80, 1.20)
    ]
    assert all(later < earlier for earlier, later in zip(dds, dds[1:])), dds


def test_default_probability_and_spread_rise_with_leverage():
    low = merton_model(**{**BASE_MERTON, "debt_face": 60.0})
    high = merton_model(**{**BASE_MERTON, "debt_face": 200.0})
    assert high.default_probability > low.default_probability
    assert high.credit_spread > low.credit_spread > 0.0


def test_default_probability_and_spread_rise_with_volatility():
    calm = merton_model(**{**BASE_MERTON, "equity_vol": 0.15})
    wild = merton_model(**{**BASE_MERTON, "equity_vol": 0.90})
    assert wild.default_probability > calm.default_probability
    assert wild.credit_spread > calm.credit_spread


def test_default_probability_is_the_normal_tail_at_minus_d2():
    result = merton_model(**BASE_MERTON)
    assert result.default_probability == pytest.approx(norm.cdf(-result.d2))
    assert result.distance_to_default == pytest.approx(result.d2)


def test_credit_spread_bp_is_the_spread_in_basis_points():
    result = merton_model(**BASE_MERTON)
    assert result.credit_spread_bp == pytest.approx(result.credit_spread * 1e4)


def test_debt_value_plus_equity_equals_asset_value():
    result = merton_model(**BASE_MERTON)
    assert result.debt_value + BASE_MERTON["equity_value"] == pytest.approx(
        result.asset_value, rel=1e-9
    )


def test_a_higher_asset_drift_pushes_distance_to_default_up():
    risk_neutral = merton_model(**BASE_MERTON)
    real_world = merton_model(**BASE_MERTON, asset_drift=0.12)
    assert real_world.distance_to_default > risk_neutral.distance_to_default
    # The drift only enters the distance to default, never the pricing legs.
    assert real_world.d2 == pytest.approx(risk_neutral.d2)
    assert real_world.credit_spread == pytest.approx(risk_neutral.credit_spread)


def test_distance_to_default_matches_its_closed_form():
    assert distance_to_default(200.0, 0.25, 100.0, 2.0, drift=0.06) == pytest.approx(
        (math.log(2.0) + (0.06 - 0.5 * 0.25**2) * 2.0) / (0.25 * math.sqrt(2.0))
    )


def test_distance_to_default_rejects_non_positive_inputs():
    with pytest.raises(ValueError, match="must all be positive"):
        distance_to_default(0.0, 0.25, 100.0, 1.0)
    with pytest.raises(ValueError, match="must all be positive"):
        distance_to_default(200.0, 0.25, 100.0, 0.0)


def test_kmv_default_point_takes_all_short_and_half_the_long_book():
    assert kmv_default_point(100.0, 200.0) == pytest.approx(200.0)
    assert kmv_default_point(100.0, 200.0, long_term_weight=0.0) == pytest.approx(100.0)
    assert kmv_default_point(100.0, 200.0, long_term_weight=1.0) == pytest.approx(300.0)


def test_kmv_default_point_validates_its_inputs():
    with pytest.raises(ValueError, match="non-negative"):
        kmv_default_point(-1.0, 200.0)
    with pytest.raises(ValueError, match=r"must lie in \[0, 1\]"):
        kmv_default_point(100.0, 200.0, long_term_weight=1.5)


def test_kmv_distance_to_default_is_the_linear_gap_not_the_log_one():
    linear = kmv_distance_to_default(1000.0, 0.25, 200.0)
    assert linear == pytest.approx((1000.0 - 200.0) / (1000.0 * 0.25))
    # It is deliberately a different quantity from the Merton/lognormal version.
    assert linear != pytest.approx(distance_to_default(1000.0, 0.25, 200.0, 1.0))


def test_kmv_distance_to_default_goes_negative_below_the_default_point():
    assert kmv_distance_to_default(100.0, 0.25, 150.0) < 0.0


def test_kmv_distance_to_default_rejects_non_positive_inputs():
    with pytest.raises(ValueError, match="must be positive"):
        kmv_distance_to_default(0.0, 0.25, 100.0)


@pytest.mark.parametrize("dd,expected", [
    (6.0, (0.0, 0.001)),
    (4.01, (0.0, 0.001)),
    (3.0, (0.001, 0.01)),
    (2.5, (0.001, 0.01)),
    (1.5, (0.01, 0.05)),
    (0.5, (0.05, math.inf)),
    (-2.0, (0.05, math.inf)),
])
def test_edf_reference_bands_follow_the_published_table(dd, expected):
    assert edf_reference_band(dd) == expected


def test_edf_reference_band_rejects_a_non_finite_input():
    with pytest.raises(ValueError, match="must be finite"):
        edf_reference_band(float("nan"))


# --------------------------------------------------------------------------
# spread analytics
# --------------------------------------------------------------------------


@pytest.fixture
def spread_inputs():
    index = pd.date_range("2024-01-01", periods=80, freq="D")
    bond = pd.Series(np.linspace(3.00, 3.79, 80), index=index)
    risk_free = pd.Series(np.full(80, 2.50), index=index)
    return bond, risk_free


def test_credit_spread_analysis_columns_and_first_level(spread_inputs):
    bond, risk_free = spread_inputs
    out = credit_spread_analysis(bond, risk_free, window=20)

    assert list(out.columns) == [
        "spread_bp",
        "rolling_mean_bp",
        "rolling_std_bp",
        "z_score",
        "historical_percentile",
        "change_1p_bp",
        "change_lookback_bp",
        "signal",
    ]
    assert out.index.equals(bond.index)
    # 3.00% - 2.50% = 0.50% = 50bp.
    assert out["spread_bp"].iloc[0] == pytest.approx(50.0)
    assert out["change_1p_bp"].iloc[1] == pytest.approx(1.0)
    assert out["change_lookback_bp"].iloc[21] == pytest.approx(21.0)


def test_the_three_input_units_are_consistent_with_each_other(spread_inputs):
    bond, risk_free = spread_inputs
    percent = credit_spread_analysis(bond, risk_free, window=20)["spread_bp"]
    decimal = credit_spread_analysis(
        bond / 100, risk_free / 100, window=20, input_unit="decimal"
    )["spread_bp"]
    basis = credit_spread_analysis(
        bond * 100, risk_free * 100, window=20, input_unit="bp"
    )["spread_bp"]
    pd.testing.assert_series_equal(percent, decimal)
    pd.testing.assert_series_equal(percent, basis)


def test_signals_fire_on_the_z_score_threshold():
    index = pd.date_range("2024-01-01", periods=40, freq="D")
    values = np.full(40, 3.0)
    values[-1] = 9.0  # a violent widening at the end
    bond = pd.Series(values, index=index)
    risk_free = pd.Series(np.full(40, 2.0), index=index)

    out = credit_spread_analysis(bond, risk_free, window=10, signal_z=1.5)
    assert out["signal"].iloc[-1] == "cheap"
    assert out["z_score"].iloc[-1] > 1.5
    assert set(out["signal"].iloc[10:-1]) == {"neutral"}


def test_a_tighter_signal_threshold_flags_more_rows():
    index = pd.date_range("2024-01-01", periods=60, freq="D")
    rng = np.random.default_rng(20260806)
    bond = pd.Series(3.0 + rng.normal(0, 0.1, 60), index=index)
    risk_free = pd.Series(np.full(60, 2.0), index=index)

    loose = credit_spread_analysis(bond, risk_free, window=15, signal_z=2.5)
    tight = credit_spread_analysis(bond, risk_free, window=15, signal_z=0.5)
    assert (tight["signal"] != "neutral").sum() > (loose["signal"] != "neutral").sum()


def test_historical_percentile_is_whole_sample_and_therefore_look_ahead():
    # Pinned as a known property, not endorsed: the column is inherited from the
    # markdown template and the docstring warns it must not drive a backtest.
    # The proof is that one row's value moves when only LATER rows are added.
    index = pd.date_range("2024-01-01", periods=100, freq="D")
    bond = pd.Series(np.arange(100.0) + 300.0, index=index)
    risk_free = pd.Series(np.full(100, 200.0), index=index)

    hundred = credit_spread_analysis(bond, risk_free, window=10)
    fifty = credit_spread_analysis(bond.iloc[:50], risk_free.iloc[:50], window=10)

    assert hundred["historical_percentile"].iloc[0] == pytest.approx(0.01)
    assert fifty["historical_percentile"].iloc[0] == pytest.approx(0.02)
    # Everything else on that row is computed from the past alone.
    assert hundred["spread_bp"].iloc[0] == pytest.approx(fifty["spread_bp"].iloc[0])
    pd.testing.assert_series_equal(
        hundred["z_score"].iloc[:50], fifty["z_score"], check_freq=False
    )
    assert list(hundred["signal"].iloc[:50]) == list(fifty["signal"])


def test_credit_spread_analysis_rejects_a_mismatched_index():
    a = pd.Series([1.0, 2.0], index=pd.date_range("2024-01-01", periods=2))
    b = pd.Series([1.0, 2.0], index=pd.date_range("2024-02-01", periods=2))
    with pytest.raises(ValueError, match="must share one index"):
        credit_spread_analysis(a, b)


def test_credit_spread_analysis_validates_windows_and_units():
    index = pd.date_range("2024-01-01", periods=5)
    a = pd.Series(np.arange(5.0), index=index)
    with pytest.raises(ValueError, match="must be positive"):
        credit_spread_analysis(a, a, window=0)
    with pytest.raises(ValueError, match="unknown input_unit"):
        credit_spread_analysis(a, a, input_unit="ratio")


def test_spread_term_structure_grid():
    issuers = {
        "AAA-LGFV": {1: 0.025, 3: 0.028, 5: 0.032},
        "AA-LGFV": {1: 0.032, 3: 0.041, 5: 0.055},
    }
    curve = {1: 0.020, 3: 0.022, 5: 0.025}
    out = spread_term_structure(issuers, curve)

    assert list(out.index) == ["AAA-LGFV", "AA-LGFV"]
    assert list(out.columns) == ["1Y_spread_bp", "3Y_spread_bp", "5Y_spread_bp"]
    assert out.loc["AAA-LGFV", "1Y_spread_bp"] == pytest.approx(50.0)
    assert out.loc["AA-LGFV", "5Y_spread_bp"] == pytest.approx(300.0)


def test_spread_term_structure_honours_the_input_unit():
    decimal = spread_term_structure({"x": {1: 0.025}}, {1: 0.020})
    percent = spread_term_structure({"x": {1: 2.5}}, {1: 2.0}, input_unit="percent")
    assert decimal.loc["x", "1Y_spread_bp"] == pytest.approx(50.0)
    assert percent.loc["x", "1Y_spread_bp"] == pytest.approx(50.0)


def test_spread_term_structure_leaves_an_unquoted_tenor_as_nan():
    out = spread_term_structure({"x": {1: 0.025, 7: 0.040}}, {1: 0.020})
    assert out.loc["x", "1Y_spread_bp"] == pytest.approx(50.0)
    assert math.isnan(out.loc["x", "7Y_spread_bp"])


def test_spread_term_structure_rounding_is_controllable():
    issuers = {"x": {1: 0.0250123}}
    assert spread_term_structure(issuers, {1: 0.02}).loc["x", "1Y_spread_bp"] == (
        pytest.approx(50.1)
    )
    assert spread_term_structure(issuers, {1: 0.02}, decimals=None).loc[
        "x", "1Y_spread_bp"
    ] == pytest.approx(50.123)


def test_spread_term_structure_validates_its_inputs():
    with pytest.raises(ValueError, match="at least one entry"):
        spread_term_structure({}, {1: 0.02})
    with pytest.raises(ValueError, match="unknown input_unit"):
        spread_term_structure({"x": {1: 0.025}}, {1: 0.02}, input_unit="ratio")
