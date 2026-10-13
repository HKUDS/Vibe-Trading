"""Statistical invariants, timing boundaries and tool contract for factor transforms."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.quantlib.neutralization import neutralize_factor, pca_factors
from src.tools.quantlib_tool import QuantlibCallTool


def panel(values, times=None):
    values = np.atleast_2d(values).astype(float)
    if times is None:
        times = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        values, index=times, columns=[f"s{i}" for i in range(values.shape[1])]
    )


def sample(n_rows=3, times=None):
    rng = np.random.default_rng(20)
    x = panel(rng.normal(size=(n_rows, 20)), times)
    other = panel(rng.normal(size=(n_rows, 20)), times)
    noise = panel(rng.normal(size=(n_rows, 20)), times)
    return 3 + 2 * x - other + noise, {"size": x, "momentum": other}


def test_ols_matches_independent_least_squares_and_preserves_inputs():
    signal, controls = sample()
    original = signal.copy(deep=True)
    result = neutralize_factor(signal, controls, standardize=False)
    for row in range(len(signal)):
        x = np.column_stack(
            [np.ones(20), *[value.iloc[row].to_numpy() for value in controls.values()]]
        )
        y = signal.iloc[row].to_numpy()
        expected = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
        np.testing.assert_allclose(result.residuals.iloc[row], expected, atol=1e-12)
        np.testing.assert_allclose(x.T @ result.residuals.iloc[row], 0, atol=1e-12)
        assert (
            max(
                abs(value)
                for value in result.diagnostics[row]["exposure_after"].values()
            )
            < 1e-12
        )
    pd.testing.assert_frame_equal(signal, original)


def test_wls_matches_reference_and_standardization_preserves_weighted_orthogonality():
    signal, controls = sample()
    weights = panel(np.tile(np.arange(1, 21), (3, 1)))
    result = neutralize_factor(signal, controls, method="wls", weights=weights)
    for row in range(len(signal)):
        x = np.column_stack(
            [np.ones(20), *[value.iloc[row].to_numpy() for value in controls.values()]]
        )
        y = signal.iloc[row].to_numpy()
        w = weights.iloc[row].to_numpy()
        beta = np.linalg.lstsq(x * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
        expected = y - x @ beta
        expected /= np.sqrt(np.average(expected**2, weights=w))
        np.testing.assert_allclose(result.residuals.iloc[row], expected, atol=1e-12)
        np.testing.assert_allclose(
            x.T @ (w * result.residuals.iloc[row]), 0, atol=1e-10
        )
        assert (
            max(
                abs(value)
                for value in result.diagnostics[row]["exposure_after"].values()
            )
            < 1e-12
        )
    equal = neutralize_factor(signal, controls, method="wls", weights=weights * 0 + 1)
    pd.testing.assert_frame_equal(
        equal.residuals, neutralize_factor(signal, controls).residuals
    )


def test_industry_dummies_remove_group_means_and_preserve_missing_labels():
    signal = panel([2, 4, 10, 14, 3, 7, 11, 15, 6, 8, 20, 22])
    industry = pd.DataFrame(
        [["A", "A", "B", "B"] * 3], index=signal.index, columns=signal.columns
    )
    industry.iloc[0, -1] = None
    result = neutralize_factor(
        signal, categorical_controls={"industry": industry}, standardize=False
    )
    for tag in ("A", "B"):
        assert result.residuals.iloc[0][
            industry.iloc[0] == tag
        ].mean() == pytest.approx(0, abs=1e-12)
    assert pd.isna(result.residuals.iloc[0, -1])
    assert result.diagnostics[0]["fit_count"] == 11


def test_auto_selection_reports_low_coverage_constants_and_collinearity():
    signal, controls = sample()
    sparse = controls["size"].copy()
    sparse.iloc[:, :10] = np.nan
    candidates = {
        "size": controls["size"],
        "size_copy": controls["size"] * 4 + 10,
        "constant": controls["size"] * 0 + 1,
        "sparse": sparse,
        "momentum": controls["momentum"],
    }
    result = neutralize_factor(signal, candidates, control_selection="auto")
    for detail in result.diagnostics:
        assert detail["selected_controls"] == ["size", "momentum"]
        assert detail["dropped_controls"] == {
            "size_copy": "constant_or_collinear",
            "constant": "constant_or_collinear",
            "sparse": "low_coverage",
        }
    pd.testing.assert_frame_equal(
        result.residuals, neutralize_factor(signal, controls).residuals
    )


def test_categorical_reference_uses_fitted_assets_not_masked_or_missing_assets():
    signal, controls = sample(n_rows=1)
    industry = pd.DataFrame(
        [["A"] + ["B", "C"] * 9 + ["B"]], index=signal.index, columns=signal.columns
    )
    mask = pd.DataFrame(True, index=signal.index, columns=signal.columns)
    mask.iloc[0, 0] = False
    masked = neutralize_factor(
        signal, categorical_controls={"industry": industry}, mask=mask
    )
    assert masked.diagnostics[0]["status"] == "ok"
    controls["size"].iloc[0, 0] = np.nan
    missing = neutralize_factor(
        signal, controls, categorical_controls={"industry": industry}
    )
    assert missing.diagnostics[0]["status"] == "ok"
    assert missing.diagnostics[0]["fit_count"] == 19
    auto = neutralize_factor(
        signal,
        controls,
        categorical_controls={"industry": industry},
        control_selection="auto",
    )
    assert auto.diagnostics[0]["selected_controls"] == ["size", "momentum", "industry"]
    pd.testing.assert_frame_equal(auto.residuals, missing.residuals)


def test_encoded_control_name_collisions_are_rejected():
    signal, controls = sample(n_rows=1)
    industry = pd.DataFrame(
        [["A", "B"] * 10], index=signal.index, columns=signal.columns
    )
    with pytest.raises(ValueError, match="names collide"):
        neutralize_factor(
            signal,
            {"industry=B": controls["size"]},
            categorical_controls={"industry": industry},
        )


def test_auto_checks_joint_coverage_and_skipped_output_coverage_is_zero():
    signal, controls = sample(n_rows=1)
    controls["size"].iloc[0, :4] = np.nan
    controls["momentum"].iloc[0, 4:8] = np.nan
    result = neutralize_factor(
        signal, controls, control_selection="auto", min_observations=14
    )
    detail = result.diagnostics[0]
    assert detail["selected_controls"] == ["size"]
    assert detail["fit_count"] == 16
    assert detail["coverage"] == pytest.approx(0.8)
    assert (
        detail["dropped_controls"]["momentum"] == "insufficient_sample_or_residual_dof"
    )
    skipped = neutralize_factor(signal, controls, min_observations=20)
    assert skipped.diagnostics[0]["coverage"] == 0
    assert skipped.diagnostics[0]["fit_count"] == 0


def test_auto_selection_respects_residual_dof_and_does_not_fallback_to_demeaning():
    signal, controls = sample()
    result = neutralize_factor(
        signal, controls, control_selection="auto", min_residual_dof=18
    )
    assert result.diagnostics[0]["selected_controls"] == ["size"]
    assert (
        result.diagnostics[0]["dropped_controls"]["momentum"]
        == "insufficient_sample_or_residual_dof"
    )
    empty = neutralize_factor(
        signal, {"constant": signal * 0 + 1}, control_selection="auto"
    )
    assert empty.residuals.isna().all().all()
    assert all(detail["reason"] == "no_usable_controls" for detail in empty.diagnostics)


def test_alignment_mask_and_wls_weight_exclusions_are_explicit():
    signal, controls = sample()
    aligned = {name: value.iloc[::-1, ::-1] for name, value in controls.items()}
    pd.testing.assert_frame_equal(
        neutralize_factor(signal, controls).residuals,
        neutralize_factor(signal, aligned).residuals,
    )
    weights = signal * 0 + 1
    weights.iloc[0, :4] = [0, -1, np.nan, np.inf]
    mask = pd.DataFrame(True, index=signal.index, columns=signal.columns)
    mask.iloc[0, 4] = False
    signal.iloc[0, 5] = np.nan
    controls["size"].iloc[0, 6] = np.nan
    result = neutralize_factor(
        signal, controls, method="wls", weights=weights, mask=mask
    )
    assert result.residuals.iloc[0, :7].isna().all()
    assert result.diagnostics[0]["excluded_weight_count"] == 4
    assert result.diagnostics[0]["fit_count"] == 13
    pd.testing.assert_index_equal(result.residuals.index, signal.index)
    pd.testing.assert_index_equal(result.residuals.columns, signal.columns)


@pytest.mark.parametrize("frequency", ["min", "h", "D", "W", "MS"])
def test_frequency_independence_and_no_future_row_influence(frequency):
    times = pd.date_range("2024-01-01", periods=3, freq=frequency, tz="UTC")
    signal, controls = sample(times=times)
    result = neutralize_factor(signal, controls, control_selection="auto")
    pca = pca_factors(controls, n_components=2)
    signal.iloc[1:] *= -1000
    for frame in controls.values():
        frame.iloc[1:] *= 42
    updated = neutralize_factor(signal, controls, control_selection="auto")
    updated_pca = pca_factors(controls, n_components=2)
    pd.testing.assert_series_equal(result.residuals.iloc[0], updated.residuals.iloc[0])
    assert result.diagnostics[0] == updated.diagnostics[0]
    for name in pca.components:
        pd.testing.assert_series_equal(
            pca.components[name].iloc[0], updated_pca.components[name].iloc[0]
        )
    assert pca.diagnostics[0] == updated_pca.diagnostics[0]


def test_irregular_times_are_not_sorted_or_resampled_and_missing_dates_are_not_filled():
    times = pd.to_datetime(["2024-02-01 10:01", "2024-01-04 09:32", "2024-02-01 10:08"])
    signal, controls = sample(times=times)
    controls["size"] = controls["size"].iloc[:2]
    result = neutralize_factor(signal, controls)
    pd.testing.assert_index_equal(result.residuals.index, times)
    assert result.residuals.iloc[2].isna().all()
    assert result.diagnostics[2]["reason"] == "insufficient_sample"


def test_explicit_collinearity_is_skipped_and_exactly_explained_signal_stays_zero():
    signal, controls = sample()
    bad = neutralize_factor(signal, {"x": controls["size"], "copy": controls["size"]})
    assert bad.residuals.isna().all().all()
    assert all(detail["reason"] == "rank_deficient" for detail in bad.diagnostics)
    perfect = neutralize_factor(controls["size"] * 2 + 3, {"size": controls["size"]})
    np.testing.assert_array_equal(perfect.residuals, 0)
    assert all(detail["zero_residual"] for detail in perfect.diagnostics)


def test_tiny_signal_is_not_mistaken_for_zero_residual():
    signal, controls = sample()
    expected = neutralize_factor(signal, controls)
    actual = neutralize_factor(signal * 1e-15, controls)
    np.testing.assert_allclose(actual.residuals, expected.residuals, atol=1e-12)


def test_pca_components_are_uncorrelated_and_full_components_reconstruct_inputs():
    _, factors = sample()
    result = pca_factors(factors, n_components=2)
    for row, detail in enumerate(result.diagnostics):
        scores = np.column_stack(
            [frame.iloc[row].to_numpy() for frame in result.components.values()]
        )
        covariance = np.cov(scores.T)
        assert covariance[0, 1] == pytest.approx(0, abs=1e-12)
        loadings = np.array(
            [list(detail["loadings"][name].values()) for name in result.components]
        )
        x = np.column_stack([frame.iloc[row].to_numpy() for frame in factors.values()])
        expected = (x - x.mean(axis=0)) / x.std(axis=0)
        np.testing.assert_allclose(scores @ loadings, expected, atol=1e-12)
        assert sum(detail["explained_variance_ratio"]) == pytest.approx(1)
        for loading in loadings:
            assert loading[np.argmax(np.abs(loading))] >= 0


def test_pca_variance_fraction_handles_variable_component_counts_and_missing_assets():
    _, factors = sample()
    factors["momentum"].iloc[0] = factors["size"].iloc[0] * 2
    factors["momentum"].iloc[2, 0] = np.nan
    result = pca_factors(factors, n_components=0.95)
    assert result.diagnostics[0]["n_components"] == 1
    assert result.diagnostics[1]["n_components"] == 2
    assert result.components["PC2"].iloc[0].isna().all()
    assert pd.isna(result.components["PC1"].iloc[2, 0])
    assert all(detail["retained_variance"] >= 0.95 for detail in result.diagnostics)


def test_pca_constant_and_insufficient_rank_observations_are_skipped():
    _, factors = sample()
    constant = pca_factors({"x": factors["size"], "constant": factors["size"] * 0 + 1})
    assert not constant.components
    assert all(detail["reason"] == "constant_factor" for detail in constant.diagnostics)
    rank_one = pca_factors(
        {"x": factors["size"], "copy": factors["size"]}, n_components=2
    )
    assert not rank_one.components
    assert all(
        detail["reason"] == "insufficient_rank" for detail in rank_one.diagnostics
    )
    short = pca_factors({name: frame.iloc[:, :3] for name, frame in factors.items()})
    assert all(
        detail["reason"] == "insufficient_sample" for detail in short.diagnostics
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": "unknown"},
        {"control_selection": "best_ic"},
        {"method": "wls"},
        {"min_coverage": 0},
        {"min_coverage": np.nan},
        {"min_observations": True},
        {"min_residual_dof": 0},
        {"rcond": 0},
        {"standardize": "yes"},
    ],
)
def test_invalid_residualization_settings_are_rejected(kwargs):
    signal, controls = sample()
    with pytest.raises(ValueError):
        neutralize_factor(signal, controls, **kwargs)


def test_invalid_panels_masks_and_weight_method_combinations_are_rejected():
    signal, controls = sample()
    with pytest.raises(ValueError, match="at least one"):
        neutralize_factor(signal)
    with pytest.raises(ValueError, match="unique"):
        neutralize_factor(pd.concat([signal, signal]), controls)
    with pytest.raises(ValueError, match="boolean"):
        neutralize_factor(signal, controls, mask=signal * 0 + 2)
    with pytest.raises(ValueError, match="weights require"):
        neutralize_factor(signal, controls, weights=signal * 0 + 1)
    with pytest.raises(ValueError, match="distinct"):
        neutralize_factor(signal, controls, categorical_controls=controls)


@pytest.mark.parametrize("count", [0, -1, True, 1.0, 1.1, np.nan, 3])
def test_invalid_pca_component_counts_are_rejected(count):
    _, factors = sample()
    with pytest.raises(ValueError):
        pca_factors(factors, n_components=count)


def envelope(frame):
    return {
        "__dataframe__": {
            "index": [str(time) for time in frame.index],
            "columns": list(frame.columns),
            "data": frame.to_numpy().tolist(),
        }
    }


def test_quantlib_tool_lists_calls_and_serializes_both_transforms():
    tool = QuantlibCallTool()
    listing = json.loads(tool.execute(action="list", module="neutralization"))
    assert {item["name"] for item in listing["functions"]} == {
        "neutralize_factor",
        "pca_factors",
    }
    signal, controls = sample(n_rows=1)
    encoded = {name: envelope(frame) for name, frame in controls.items()}
    residual = json.loads(
        tool.execute(
            action="call",
            module="neutralization",
            function="neutralize_factor",
            kwargs={"factor": envelope(signal), "controls": encoded},
        )
    )
    assert residual["ok"]
    assert residual["result"]["diagnostics"][0]["status"] == "ok"
    assert "__dataframe__" in residual["result"]["residuals"]
    pca = json.loads(
        tool.execute(
            action="call",
            module="neutralization",
            function="pca_factors",
            kwargs={"factors": encoded, "n_components": 2},
        )
    )
    assert pca["ok"]
    assert set(pca["result"]["components"]) == {"PC1", "PC2"}
    error = json.loads(
        tool.execute(
            action="call",
            module="neutralization",
            function="neutralize_factor",
            kwargs={"factor": envelope(signal), "controls": encoded, "method": "wls"},
        )
    )
    assert not error["ok"]
    assert "requires weights" in error["error"]
