"""Frequency-independent cross-sectional residualization and factor PCA.

Each panel row is one observation time and each column is an asset. Rows are
never pooled, resampled or filled across time. The caller must supply exposures
and classifications known at that observation time; alignment alone cannot
verify their publication dates. No returns or labels are used for selection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

__all__ = ["neutralize_factor", "pca_factors"]


@dataclass
class NeutralizationResult:
    """Residual panel and per-observation selection/exposure diagnostics."""

    residuals: pd.DataFrame
    diagnostics: list[dict[str, Any]]
    method: str
    control_selection: str


@dataclass
class FactorPCAResult:
    """Component panels and per-observation PCA loadings/variance diagnostics."""

    components: dict[str, pd.DataFrame]
    diagnostics: list[dict[str, Any]]


def _check_panel(panel: pd.DataFrame, name: str) -> None:
    if not isinstance(panel, pd.DataFrame):
        raise ValueError(f"{name} must be an indexed DataFrame (time x asset)")
    if panel.empty or not panel.index.is_unique or not panel.columns.is_unique:
        raise ValueError(f"{name} must be nonempty with unique time/asset labels")


def _numeric(panel: pd.DataFrame, name: str) -> pd.DataFrame:
    _check_panel(panel, name)
    try:
        values = panel.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numeric values") from exc
    values = np.where(np.isfinite(values), values, np.nan)
    return pd.DataFrame(values, index=panel.index, columns=panel.columns)


def _aligned(panel: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    return panel.reindex(index=reference.index, columns=reference.columns)


def _mask(mask: pd.DataFrame | None, reference: pd.DataFrame) -> np.ndarray:
    if mask is None:
        return np.ones(reference.shape, dtype=bool)
    _check_panel(mask, "mask")
    aligned = _aligned(mask, reference)
    if not aligned.isin([True, False]).all().all():
        raise ValueError("mask must have boolean values for every factor time/asset")
    return aligned.to_numpy(dtype=bool)


def _positive_int(value: int, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _mapping(value: Mapping[str, pd.DataFrame], name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must map names to DataFrames")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{name} requires nonempty string names")


def _weights(values: np.ndarray) -> np.ndarray:
    return values / values.max()


def _design(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    # Center/scale only on the current complete cross-section; this preserves
    # the regression span while making rank checks insensitive to input units.
    probability = weights / weights.sum()
    centered = x - probability @ x
    scale = np.sqrt(probability @ np.square(centered))
    scaled = centered / np.where(scale > 0, scale, 1.0)
    return np.column_stack([np.ones(len(x)), scaled])


def _rank(design: np.ndarray, weights: np.ndarray, rcond: float) -> int:
    singular = np.linalg.svd(design * np.sqrt(weights)[:, None], compute_uv=False)
    return int(np.count_nonzero(singular > rcond * singular[0]))


def _correlation(a: np.ndarray, b: np.ndarray, weights: np.ndarray) -> float | None:
    probability = weights / weights.sum()
    a = a - probability @ a
    b = b - probability @ b
    scale_a = float(np.sqrt(probability @ np.square(a)))
    scale_b = float(np.sqrt(probability @ np.square(b)))
    if scale_a == 0 or scale_b == 0:
        return None
    return float(np.clip(probability @ ((a / scale_a) * (b / scale_b)), -1, 1))


def _columns(
    numeric: dict[str, pd.DataFrame],
    categorical: dict[str, pd.DataFrame],
    row: int,
) -> dict[str, pd.DataFrame | pd.Series]:
    candidates: dict[str, pd.DataFrame | pd.Series] = {
        name: frame.iloc[row].to_frame(name) for name, frame in numeric.items()
    }
    for name, frame in categorical.items():
        candidates[name] = frame.iloc[row].astype("string")
    return candidates


def _complete(candidate: pd.DataFrame | pd.Series) -> np.ndarray:
    if isinstance(candidate, pd.Series):
        return candidate.notna().to_numpy()
    return np.isfinite(candidate.to_numpy()).all(axis=1)


def _select(
    candidates: dict[str, pd.DataFrame | pd.Series],
    base: np.ndarray,
    weights: np.ndarray,
    selection: str,
    min_coverage: float,
    min_observations: int,
    min_residual_dof: int,
    rcond: float,
) -> tuple[pd.DataFrame, np.ndarray, list[str], dict[str, str]]:
    matrix = pd.DataFrame(index=next(iter(candidates.values())).index)
    valid = base.copy()
    if selection == "explicit":
        for candidate in candidates.values():
            valid &= _complete(candidate)
    selected: list[str] = []
    dropped: dict[str, str] = {}
    for name, candidate in candidates.items():
        complete = _complete(candidate)
        trial_valid = valid & complete
        if isinstance(candidate, pd.Series):
            labels = candidate.where(trial_valid)
            candidate = pd.get_dummies(
                labels, prefix=name, prefix_sep="=", drop_first=True, dtype=float
            )
            candidate.loc[labels.isna(), :] = np.nan
            # One observed category has no estimable group contrast.
            if candidate.shape[1] == 0:
                candidate[f"{name}=constant"] = np.where(labels.notna(), 0.0, np.nan)
        trial = pd.concat([matrix, candidate], axis=1)
        if not trial.columns.is_unique:
            raise ValueError(
                "encoded control names collide; rename the supplied controls"
            )
        reason = None
        if selection == "auto":
            count = int(trial_valid.sum())
            if (base & complete).sum() / max(int(base.sum()), 1) < min_coverage:
                reason = "low_coverage"
            elif (
                count < min_observations
                or count - trial.shape[1] - 1 < min_residual_dof
            ):
                reason = "insufficient_sample_or_residual_dof"
            else:
                design = _design(
                    trial.to_numpy()[trial_valid], _weights(weights[trial_valid])
                )
                if (
                    _rank(design, _weights(weights[trial_valid]), rcond)
                    < design.shape[1]
                ):
                    reason = "constant_or_collinear"
        if reason:
            dropped[name] = reason
        else:
            matrix, valid = trial, trial_valid
            selected.append(name)
    return matrix, valid, selected, dropped


def neutralize_factor(
    factor: pd.DataFrame,
    controls: Mapping[str, pd.DataFrame] | None = None,
    *,
    categorical_controls: Mapping[str, pd.DataFrame] | None = None,
    method: str = "ols",
    weights: pd.DataFrame | None = None,
    control_selection: str = "explicit",
    min_coverage: float = 0.8,
    min_observations: int = 10,
    min_residual_dof: int = 2,
    standardize: bool = True,
    mask: pd.DataFrame | None = None,
    rcond: float = 1e-10,
) -> NeutralizationResult:
    """Remove specified exposures separately at every input observation time.

    Args:
        factor: Numeric time-by-asset panel at any frequency, including irregular.
        controls: Named numeric exposure panels, e.g. log_market_cap or beta.
        categorical_controls: Named contemporaneous classifications, dummy-coded
            per observation with one reference category omitted.
        method: 'ols' or 'wls'. WLS uses positive finite observation weights.
        weights: Required for WLS; missing/nonpositive cells are excluded.
        control_selection: 'explicit' requires all controls; 'auto' greedily
            selects in supplied order using coverage, rank and sample size only.
        min_coverage: Minimum per-control coverage in auto mode (0 < value <= 1).
        min_observations: Minimum complete assets in a fitted cross-section.
        min_residual_dof: Minimum observations minus design rank (incl. intercept).
        standardize: Scale residuals to unit weighted standard deviation. Exact
            zero residuals stay zero; residuals are never winsorized or ranked.
        mask: Fully aligned boolean tradable/universe panel.
        rcond: Relative singular-value threshold for rank checking and fitting.

    Returns:
        Residuals on the original axes, with NaN for excluded/skipped cells.
        Diagnostics disclose selected/dropped controls, coverage, rank, degrees
        of freedom and weighted Pearson exposure before/after on the same sample.

    Raises:
        ValueError: Invalid panels, settings or a missing WLS weight panel.

    Notes:
        No publication-date verification is possible without source metadata.
        Auto selection is data-quality filtering, not economic model selection.
        Rank-deficient explicit fits and empty auto selections are skipped;
        they never silently fall back to intercept-only demeaning. Compare IC
        and backtests separately using identical samples and holding horizons.
    """
    factor = _numeric(factor, "factor")
    controls = {} if controls is None else controls
    categorical_controls = {} if categorical_controls is None else categorical_controls
    _mapping(controls, "controls")
    _mapping(categorical_controls, "categorical_controls")
    if not controls and not categorical_controls:
        raise ValueError("at least one control is required")
    if set(controls) & set(categorical_controls):
        raise ValueError("numeric and categorical control names must be distinct")
    if method not in ("ols", "wls") or control_selection not in ("explicit", "auto"):
        raise ValueError(
            "method must be ols/wls; control_selection must be explicit/auto"
        )
    if not isinstance(standardize, bool):
        raise ValueError("standardize must be boolean")
    if (
        not isinstance(min_coverage, Real)
        or not np.isfinite(min_coverage)
        or not 0 < min_coverage <= 1
    ):
        raise ValueError("min_coverage must be in (0, 1]")
    if not isinstance(rcond, Real) or not np.isfinite(rcond) or not 0 < rcond < 1:
        raise ValueError("rcond must be in (0, 1)")
    _positive_int(min_observations, "min_observations", 2)
    _positive_int(min_residual_dof, "min_residual_dof")
    if method == "wls" and weights is None:
        raise ValueError("wls requires weights")
    if method == "ols" and weights is not None:
        raise ValueError(
            "weights require method='wls'; OLS never silently ignores them"
        )
    numeric = {
        name: _aligned(_numeric(frame, name), factor)
        for name, frame in controls.items()
    }
    categorical = {}
    for name, frame in categorical_controls.items():
        _check_panel(frame, name)
        categorical[name] = _aligned(frame, factor)
    allowed = _mask(mask, factor)
    weight_values = (
        _aligned(_numeric(weights, "weights"), factor).to_numpy()
        if weights is not None
        else np.ones(factor.shape)
    )
    residuals = pd.DataFrame(np.nan, index=factor.index, columns=factor.columns)
    diagnostics = []
    for row, timestamp in enumerate(factor.index):
        y = factor.iloc[row].to_numpy()
        w = weight_values[row]
        signal_valid = allowed[row] & np.isfinite(y)
        base = signal_valid & np.isfinite(w) & (w > 0)
        matrix, valid, selected, dropped = _select(
            _columns(numeric, categorical, row),
            base,
            w,
            control_selection,
            min_coverage,
            min_observations,
            min_residual_dof,
            rcond,
        )
        count = int(valid.sum())
        detail: dict[str, Any] = {
            "time": str(timestamp),
            "status": "skipped",
            "selected_controls": selected,
            "dropped_controls": dropped,
            "input_count": int(signal_valid.sum()),
            "complete_count": count,
            "fit_count": 0,
            "excluded_weight_count": int((signal_valid & ~base).sum()),
            "coverage": 0.0,
        }
        diagnostics.append(detail)
        if not selected:
            detail["reason"] = "no_usable_controls"
            continue
        if count < min_observations:
            detail["reason"] = "insufficient_sample"
            continue
        fit_w = _weights(w[valid])
        x = matrix.to_numpy()[valid]
        design = _design(x, fit_w)
        rank = _rank(design, fit_w, rcond)
        detail.update(rank=rank, residual_dof=count - rank)
        if rank != design.shape[1]:
            detail["reason"] = "rank_deficient"
            continue
        if count - rank < min_residual_dof:
            detail["reason"] = "insufficient_residual_dof"
            continue
        fit_y = y[valid]
        centered_y = fit_y - (fit_w / fit_w.sum()) @ fit_y
        root_w = np.sqrt(fit_w)
        beta = np.linalg.lstsq(
            design * root_w[:, None], centered_y * root_w, rcond=rcond
        )[0]
        residual = centered_y - design @ beta
        zero = (
            np.linalg.norm(residual)
            <= np.finfo(float).eps * np.linalg.norm(centered_y) * count
        )
        if zero:
            residual = np.zeros(count)
        elif standardize:
            residual /= np.sqrt((fit_w / fit_w.sum()) @ np.square(residual))
        residuals.iloc[row, np.flatnonzero(valid)] = residual
        detail.update(
            status="ok",
            fit_count=count,
            coverage=count / max(int(signal_valid.sum()), 1),
            zero_residual=bool(zero),
            exposure_before={
                name: _correlation(fit_y, x[:, col], fit_w)
                for col, name in enumerate(matrix.columns)
            },
            exposure_after={
                name: _correlation(residual, x[:, col], fit_w)
                for col, name in enumerate(matrix.columns)
            },
        )
    return NeutralizationResult(residuals, diagnostics, method, control_selection)


def pca_factors(
    factors: Mapping[str, pd.DataFrame],
    *,
    n_components: int | float = 0.95,
    min_observations: int = 10,
    standardize: bool = True,
    mask: pd.DataFrame | None = None,
) -> FactorPCAResult:
    """Compress factor columns using PCA fitted independently at each time.

    Args:
        factors: At least two named time-by-asset panels at any input frequency.
            The first panel defines output axes; others are aligned without fills.
        n_components: Positive component count, or explained-variance fraction
            strictly between zero and one. Fractions may yield different counts
            at different observation times; unused component rows stay NaN.
        min_observations: Minimum assets observed in every supplied factor.
        standardize: Standardize factor columns before PCA (correlation PCA).
        mask: Fully aligned boolean tradable/universe panel.

    Returns:
        PC score panels with original time/asset axes and diagnostics containing
        per-time loadings, means, scales and explained variance. Component signs
        are anchored by their largest loading; component identities can still
        rotate between times, particularly for similar eigenvalues.

    Raises:
        ValueError: Invalid settings, panels or fewer than two factors.

    Notes:
        PCA decorrelates components; it does not remove designated industry/style
        exposures. No full-period covariance or future rows are used. Missing
        assets are excluded, not imputed. Constant factors or insufficient rank
        produce a skipped observation instead of invented component scores.
    """
    _mapping(factors, "factors")
    if len(factors) < 2:
        raise ValueError("PCA requires at least two factors")
    _positive_int(min_observations, "min_observations", 2)
    if not isinstance(standardize, bool):
        raise ValueError("standardize must be boolean")
    fixed_count = isinstance(n_components, Integral) and not isinstance(
        n_components, bool
    )
    if fixed_count:
        _positive_int(n_components, "n_components")
        if n_components > len(factors):
            raise ValueError("n_components cannot exceed the factor count")
    elif (
        isinstance(n_components, bool)
        or not isinstance(n_components, Real)
        or not 0 < n_components < 1
    ):
        raise ValueError(
            "n_components must be a positive integer or fraction in (0, 1)"
        )
    panels = {name: _numeric(frame, name) for name, frame in factors.items()}
    reference = next(iter(panels.values()))
    arrays = [_aligned(frame, reference).to_numpy() for frame in panels.values()]
    allowed = _mask(mask, reference)
    components: dict[str, pd.DataFrame] = {}
    diagnostics = []
    for row, timestamp in enumerate(reference.index):
        x = np.column_stack([array[row] for array in arrays])
        eligible = allowed[row] & np.isfinite(x[:, 0])
        valid = allowed[row] & np.isfinite(x).all(axis=1)
        count = int(valid.sum())
        detail: dict[str, Any] = {
            "time": str(timestamp),
            "status": "skipped",
            "complete_count": count,
            "fit_count": 0,
            "input_count": int(eligible.sum()),
            "coverage": 0.0,
        }
        diagnostics.append(detail)
        if count < min_observations:
            detail["reason"] = "insufficient_sample"
            continue
        x = x[valid]
        means = x.mean(axis=0)
        scales = x.std(axis=0)
        if np.any(scales == 0):
            detail["reason"] = "constant_factor"
            continue
        fitted_scales = scales if standardize else np.ones(len(panels))
        z = (x - means) / fitted_scales
        rank = np.linalg.matrix_rank(z)
        detail["rank"] = int(rank)
        if rank == 0 or (fixed_count and n_components > rank):
            detail["reason"] = "insufficient_rank"
            continue
        model = PCA(n_components=min(rank, len(panels)), svd_solver="full")
        scores = model.fit_transform(z)
        keep = (
            int(n_components)
            if fixed_count
            else min(
                rank,
                int(
                    np.searchsorted(
                        np.cumsum(model.explained_variance_ratio_), n_components
                    )
                )
                + 1,
            )
        )
        loadings = model.components_[:keep].copy()
        for col in range(keep):
            if loadings[col, np.argmax(np.abs(loadings[col]))] < 0:
                loadings[col] *= -1
                scores[:, col] *= -1
            name = f"PC{col + 1}"
            if name not in components:
                components[name] = pd.DataFrame(
                    np.nan, index=reference.index, columns=reference.columns
                )
            components[name].iloc[row, np.flatnonzero(valid)] = scores[:, col]
        detail.update(
            status="ok",
            fit_count=count,
            coverage=count / max(int(eligible.sum()), 1),
            n_components=keep,
            explained_variance_ratio=model.explained_variance_ratio_[:keep].tolist(),
            retained_variance=float(model.explained_variance_ratio_[:keep].sum()),
            means=dict(zip(panels, means.tolist())),
            scales=dict(zip(panels, fitted_scales.tolist())),
            loadings={
                f"PC{col + 1}": dict(zip(panels, loadings[col].tolist()))
                for col in range(keep)
            },
        )
    return FactorPCAResult(components, diagnostics)
