"""Tests for src.quantlib.factormodel.

The recoverability tests build a cross-section from known factor returns and
check the regression gets them back. The standardisation tests pin the two
conventions that make an exposure mean what it claims: cap-weighted centring and
equal-weighted scaling.
"""

import numpy as np
import pandas as pd
import pytest

from src.quantlib.factormodel import (
    MARKET_FACTOR,
    MIN_CROSS_SECTION,
    STYLE_FACTOR_DEFINITIONS,
    build_style_exposures,
    cross_sectional_factor_returns,
    factor_return_attribution,
    portfolio_style_exposure,
    standardise_exposures,
    style_drift,
)


def _assets(n=200):
    return [f"A{i:03d}" for i in range(n)]


# --- standardisation ---


def test_standardised_exposure_has_unit_equal_weighted_dispersion():
    rng = np.random.default_rng(1)
    values = pd.Series(rng.normal(5.0, 2.0, 500), index=_assets(500))
    exposures = standardise_exposures(values, winsorise=0.0)

    assert exposures.mean() == pytest.approx(0.0, abs=1e-12)
    assert exposures.std(ddof=1) == pytest.approx(1.0, rel=1e-12)


def test_cap_weighted_centring_puts_the_market_portfolio_at_zero():
    # This is the property that makes a portfolio exposure readable as a tilt
    # away from the market rather than an absolute level.
    rng = np.random.default_rng(2)
    index = _assets(300)
    values = pd.Series(rng.normal(0.0, 1.0, 300), index=index)
    caps = pd.Series(rng.lognormal(10, 1.5, 300), index=index)

    exposures = standardise_exposures(values, market_caps=caps, winsorise=0.0)
    market_weights = caps / caps.sum()

    assert float((exposures * market_weights).sum()) == pytest.approx(0.0, abs=1e-12)


def test_equal_weighted_scaling_is_not_cap_weighted():
    # The asymmetry is deliberate: a few megacaps must not set the scale.
    rng = np.random.default_rng(3)
    index = _assets(300)
    values = pd.Series(rng.normal(0.0, 1.0, 300), index=index)
    caps = pd.Series(np.r_[np.full(5, 1e12), np.full(295, 1e8)], index=index)

    exposures = standardise_exposures(values, market_caps=caps, winsorise=0.0)
    assert exposures.std(ddof=1) == pytest.approx(1.0, rel=1e-12)


def test_winsorising_stops_one_outlier_compressing_the_cross_section():
    index = _assets(200)
    clean = pd.Series(np.linspace(-1, 1, 200), index=index)
    poisoned = clean.copy()
    poisoned.iloc[0] = 500.0

    without = standardise_exposures(poisoned, winsorise=0.0)
    with_winsor = standardise_exposures(poisoned, winsorise=0.025)

    # Without winsorising the outlier eats the scale and everything else
    # collapses toward zero.
    assert without.drop(index[0]).abs().max() < 0.1
    assert with_winsor.drop(index[0]).abs().max() > 1.0


def test_standardise_rejects_a_constant_characteristic():
    with pytest.raises(ValueError, match="no cross-sectional variation"):
        standardise_exposures(pd.Series(np.full(50, 3.0), index=_assets(50)))


def test_standardise_rejects_a_cross_section_too_small_to_scale():
    small = pd.Series(np.arange(float(MIN_CROSS_SECTION - 1)), index=_assets(MIN_CROSS_SECTION - 1))
    with pytest.raises(ValueError, match="at least"):
        standardise_exposures(small)


def test_standardise_rejects_bad_winsorise_fraction():
    values = pd.Series(np.arange(50.0), index=_assets(50))
    for bad in (-0.01, 0.5, 0.9):
        with pytest.raises(ValueError, match="winsorise must be"):
            standardise_exposures(values, winsorise=bad)


def test_standardise_rejects_market_caps_that_do_not_cover_the_universe():
    index = _assets(50)
    values = pd.Series(np.arange(50.0), index=index)
    caps = pd.Series(np.arange(1.0, 41.0), index=index[:40])
    with pytest.raises(ValueError, match="missing"):
        standardise_exposures(values, market_caps=caps)


# --- exposure assembly ---


def test_build_style_exposures_uses_the_documented_signs():
    rng = np.random.default_rng(4)
    index = _assets(200)
    characteristics = pd.DataFrame(
        {
            "log_market_cap": rng.normal(0, 1, 200),
            "book_to_price": rng.normal(0, 1, 200),
        },
        index=index,
    )
    exposures, _ = build_style_exposures(characteristics)

    # size is defined as -1 * log_market_cap: small caps get the large exposure.
    assert exposures["size"].corr(characteristics["log_market_cap"]) < -0.9
    # value is +1 * book_to_price: cheap names get the large exposure.
    assert exposures["value"].corr(characteristics["book_to_price"]) > 0.9


def test_multi_input_factor_averages_its_standardised_parts():
    rng = np.random.default_rng(5)
    index = _assets(200)
    # earnings_to_price has a hugely wider raw spread than book_to_price. If the
    # factor averaged the RAW inputs it would be an earnings-yield factor with a
    # book-to-price rounding error attached.
    characteristics = pd.DataFrame(
        {
            "book_to_price": rng.normal(0, 0.01, 200),
            "earnings_to_price": rng.normal(0, 100.0, 200),
        },
        index=index,
    )
    exposures, _ = build_style_exposures(characteristics)

    b = standardise_exposures(characteristics["book_to_price"])
    e = standardise_exposures(characteristics["earnings_to_price"])
    assert exposures["value"].corr(b) == pytest.approx(exposures["value"].corr(e), abs=0.15)


def test_missing_characteristic_cells_become_zero_and_are_counted():
    rng = np.random.default_rng(6)
    index = _assets(100)
    values = pd.Series(rng.normal(0, 1, 100), index=index)
    values.iloc[:20] = np.nan
    exposures, filled = build_style_exposures(pd.DataFrame({"book_to_price": values}))

    assert filled["value"] == 20
    assert (exposures["value"].iloc[:20] == 0.0).all()


def test_factors_with_no_supplied_characteristic_are_skipped_not_faked():
    rng = np.random.default_rng(7)
    frame = pd.DataFrame({"book_to_price": rng.normal(0, 1, 100)}, index=_assets(100))
    exposures, _ = build_style_exposures(frame)

    assert list(exposures.columns) == ["value"]
    assert "momentum" not in exposures.columns


def test_build_rejects_a_frame_with_no_usable_characteristic():
    frame = pd.DataFrame({"unrelated_column": np.arange(100.0)}, index=_assets(100))
    with pytest.raises(ValueError, match="no factor could be built"):
        build_style_exposures(frame)


def test_build_rejects_an_empty_frame():
    with pytest.raises(ValueError, match="empty"):
        build_style_exposures(pd.DataFrame())


def test_every_documented_factor_declares_at_least_one_characteristic():
    for factor, recipe in STYLE_FACTOR_DEFINITIONS.items():
        assert recipe, f"{factor} has no characteristics"
        assert all(sign in (1, -1) for sign in recipe.values()), factor


# --- cross-sectional factor returns ---


def test_factor_returns_recover_the_generating_coefficients():
    rng = np.random.default_rng(8)
    index = _assets(400)
    exposures = pd.DataFrame(
        {
            "value": rng.normal(0, 1, 400),
            "momentum": rng.normal(0, 1, 400),
            "size": rng.normal(0, 1, 400),
        },
        index=index,
    )
    true_market, true_value, true_momentum, true_size = 0.004, 0.002, -0.003, 0.0015
    returns = pd.Series(
        true_market
        + true_value * exposures["value"]
        + true_momentum * exposures["momentum"]
        + true_size * exposures["size"]
        + rng.normal(0, 0.002, 400),
        index=index,
    )

    fit = cross_sectional_factor_returns(returns, exposures)

    assert fit.factor_returns[MARKET_FACTOR] == pytest.approx(true_market, abs=0.0004)
    assert fit.factor_returns["value"] == pytest.approx(true_value, abs=0.0004)
    assert fit.factor_returns["momentum"] == pytest.approx(true_momentum, abs=0.0004)
    assert fit.factor_returns["size"] == pytest.approx(true_size, abs=0.0004)
    assert fit.r_squared > 0.7
    assert fit.observations == 400


def test_market_factor_is_always_present_as_the_intercept():
    rng = np.random.default_rng(9)
    index = _assets(100)
    exposures = pd.DataFrame({"value": rng.normal(0, 1, 100)}, index=index)
    # Everything returns +2% regardless of exposure: that is a market move and
    # it must land on the market factor, not on value.
    returns = pd.Series(np.full(100, 0.02), index=index)

    fit = cross_sectional_factor_returns(returns, exposures)

    assert fit.factor_returns[MARKET_FACTOR] == pytest.approx(0.02, abs=1e-9)
    assert fit.factor_returns["value"] == pytest.approx(0.0, abs=1e-9)


def test_residuals_are_the_specific_returns_and_sum_with_the_fit():
    rng = np.random.default_rng(10)
    index = _assets(150)
    exposures = pd.DataFrame({"value": rng.normal(0, 1, 150)}, index=index)
    returns = pd.Series(0.001 + 0.002 * exposures["value"] + rng.normal(0, 0.001, 150), index=index)

    fit = cross_sectional_factor_returns(returns, exposures)
    reconstructed = (
        fit.factor_returns[MARKET_FACTOR]
        + fit.factor_returns["value"] * exposures["value"]
        + fit.residuals
    )
    assert reconstructed.to_numpy() == pytest.approx(returns.to_numpy(), abs=1e-12)


def test_cap_weighting_changes_the_fit_toward_the_larger_names():
    rng = np.random.default_rng(11)
    index = _assets(200)
    exposures = pd.DataFrame({"value": rng.normal(0, 1, 200)}, index=index)
    returns = pd.Series(rng.normal(0, 0.01, 200), index=index)
    # Big names all get an extra +5% that the small ones do not.
    caps = pd.Series(np.r_[np.full(20, 1e12), np.full(180, 1e8)], index=index)
    returns.iloc[:20] += 0.05

    unweighted = cross_sectional_factor_returns(returns, exposures)
    weighted = cross_sectional_factor_returns(returns, exposures, market_caps=caps)

    assert weighted.factor_returns[MARKET_FACTOR] > unweighted.factor_returns[MARKET_FACTOR]


def test_collinear_exposures_are_rejected_not_silently_pseudo_inverted():
    rng = np.random.default_rng(12)
    index = _assets(100)
    base = rng.normal(0, 1, 100)
    exposures = pd.DataFrame({"a": base, "b": base * 2.0}, index=index)
    returns = pd.Series(rng.normal(0, 0.01, 100), index=index)

    with pytest.raises(ValueError, match="collinear"):
        cross_sectional_factor_returns(returns, exposures)


def test_constant_exposure_column_is_collinear_with_the_market():
    index = _assets(100)
    exposures = pd.DataFrame({"dud": np.ones(100)}, index=index)
    returns = pd.Series(np.random.default_rng(13).normal(0, 0.01, 100), index=index)

    with pytest.raises(ValueError, match="collinear"):
        cross_sectional_factor_returns(returns, exposures)


def test_too_few_assets_rejected():
    index = _assets(5)
    exposures = pd.DataFrame({"value": np.arange(5.0)}, index=index)
    returns = pd.Series(np.arange(5.0) / 100, index=index)

    with pytest.raises(ValueError, match="at least"):
        cross_sectional_factor_returns(returns, exposures)


def test_non_positive_market_caps_rejected():
    rng = np.random.default_rng(14)
    index = _assets(100)
    exposures = pd.DataFrame({"value": rng.normal(0, 1, 100)}, index=index)
    returns = pd.Series(rng.normal(0, 0.01, 100), index=index)
    caps = pd.Series(np.r_[np.zeros(1), np.full(99, 1e9)], index=index)

    with pytest.raises(ValueError, match="must be positive"):
        cross_sectional_factor_returns(returns, exposures, market_caps=caps)


# --- portfolio exposure ---


def test_portfolio_exposure_is_the_weighted_sum():
    index = _assets(4)
    exposures = pd.DataFrame({"value": [1.0, -1.0, 2.0, 0.0]}, index=index)
    holdings = pd.Series([0.25, 0.25, 0.25, 0.25], index=index)

    result = portfolio_style_exposure(holdings, exposures)
    assert result["value"] == pytest.approx(0.5)
    assert result["unmatched_weight"] == 0.0


def test_active_exposure_subtracts_the_benchmark():
    index = _assets(4)
    exposures = pd.DataFrame({"value": [1.0, 1.0, -1.0, -1.0]}, index=index)
    holdings = pd.Series([0.5, 0.5, 0.0, 0.0], index=index)
    benchmark = pd.Series([0.25, 0.25, 0.25, 0.25], index=index)

    active = portfolio_style_exposure(holdings, exposures, benchmark=benchmark)
    assert active["value"] == pytest.approx(1.0)


def test_holdings_without_exposure_data_are_disclosed_not_dropped():
    exposures = pd.DataFrame({"value": [1.0, 1.0]}, index=["A000", "A001"])
    holdings = pd.Series([0.3, 0.3, 0.4], index=["A000", "A001", "UNKNOWN"])

    result = portfolio_style_exposure(holdings, exposures)
    assert result["value"] == pytest.approx(0.6)
    assert result["unmatched_weight"] == pytest.approx(0.4)


def test_partially_invested_book_reports_a_scaled_exposure():
    exposures = pd.DataFrame({"value": [1.0, 1.0]}, index=["A000", "A001"])
    half_invested = pd.Series([0.3, 0.3], index=["A000", "A001"])
    assert portfolio_style_exposure(half_invested, exposures)["value"] == pytest.approx(0.6)


def test_empty_holdings_rejected():
    exposures = pd.DataFrame({"value": [1.0]}, index=["A000"])
    with pytest.raises(ValueError, match="holdings is empty"):
        portfolio_style_exposure(pd.Series(dtype=float), exposures)


# --- style drift ---


def test_style_drift_measures_movement_not_endpoints():
    # A fund that ends where it started but went somewhere else in between has
    # drifted, and total_change alone would say it had not.
    history = pd.DataFrame(
        {"value": [0.0, 1.5, -1.5, 0.0], "size": [0.2, 0.2, 0.2, 0.2]},
        index=pd.date_range("2024-01-31", periods=4, freq="ME"),
    )
    drift = style_drift(history)

    assert drift.total_change["value"] == pytest.approx(0.0)
    assert drift.max_abs_change["value"] == pytest.approx(3.0)
    assert drift.std_exposure["value"] > drift.std_exposure["size"]
    assert drift.std_exposure["size"] == pytest.approx(0.0)


def test_style_drift_reports_first_and_last():
    history = pd.DataFrame(
        {"momentum": [-1.0, 0.0, 1.0]},
        index=pd.date_range("2024-01-31", periods=3, freq="ME"),
    )
    drift = style_drift(history)
    assert drift.first_exposure["momentum"] == -1.0
    assert drift.last_exposure["momentum"] == 1.0
    assert drift.total_change["momentum"] == pytest.approx(2.0)


def test_style_drift_ignores_the_unmatched_weight_column():
    history = pd.DataFrame(
        {"value": [0.5, 0.7], "unmatched_weight": [0.1, 0.2]},
        index=pd.date_range("2024-01-31", periods=2, freq="ME"),
    )
    drift = style_drift(history)
    assert "unmatched_weight" not in drift.mean_exposure.index


def test_style_drift_needs_two_dates():
    history = pd.DataFrame({"value": [0.5]}, index=pd.date_range("2024-01-31", periods=1))
    with pytest.raises(ValueError, match="at least 2 dates"):
        style_drift(history)


# --- attribution ---


def test_attribution_parts_sum_to_the_portfolio_return_exactly():
    exposures = pd.Series({"value": 0.5, "momentum": -0.3, "unmatched_weight": 0.1})
    factor_returns = pd.Series({"value": 0.02, "momentum": 0.01, MARKET_FACTOR: 0.005})

    result = factor_return_attribution(exposures, factor_returns, portfolio_return=0.015)

    parts = result.drop(labels=["total"])
    assert float(parts.sum()) == pytest.approx(0.015, abs=1e-15)
    assert result["total"] == pytest.approx(0.015)
    assert result["value"] == pytest.approx(0.5 * 0.02)
    assert result["momentum"] == pytest.approx(-0.3 * 0.01)


def test_attribution_residual_absorbs_whatever_the_factors_miss():
    exposures = pd.Series({"value": 1.0})
    factor_returns = pd.Series({"value": 0.01})
    result = factor_return_attribution(exposures, factor_returns, portfolio_return=0.05)
    assert result["specific"] == pytest.approx(0.04)


def test_attribution_ignores_the_unmatched_weight_entry():
    exposures = pd.Series({"value": 1.0, "unmatched_weight": 0.9})
    factor_returns = pd.Series({"value": 0.01, "unmatched_weight": 99.0})
    result = factor_return_attribution(exposures, factor_returns, portfolio_return=0.02)
    assert "unmatched_weight" not in result.index
    assert result["specific"] == pytest.approx(0.01)


def test_attribution_rejects_disjoint_factor_sets():
    with pytest.raises(ValueError, match="share no factor"):
        factor_return_attribution(
            pd.Series({"value": 1.0}), pd.Series({"momentum": 0.01}), portfolio_return=0.0
        )
