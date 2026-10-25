"""Cross-sectional factor combination with caller-owned or IC-based weights.

Each panel row is one observation time and each column is one asset -- the same
contract as :mod:`src.quantlib.neutralization`. Several factor panels are
combined into a single composite score per ``(time, asset)``.

There is no complete list of combination methods: equal weight, IC weighting,
decayed IC, maximum IC, regression weights, trained models and risk-based
weights all exist, and new ones keep appearing. This module therefore does not
enumerate methods. It fixes the *weight contract* instead:

* ``weights`` accepts a static mapping or a ``time x factor`` DataFrame. Any
  method that produces such a table -- fitted elsewhere, tuned however the
  caller likes -- can be combined here. A table is auditable, reproducible and
  transportable over MCP; a callback is none of those.
* ``equal``, ``ic`` and ``icir`` are shipped as transparent baselines, not as a
  catalogue: they need no tuning, no dependency and no training.

Weight timing is the one rule that cannot be relaxed: a weight applied at row
``t`` may only use information from rows ``< t``. ``ic``/``icir`` enforce this
internally; a caller-supplied table must already respect it. Passing full-sample
IC weights leaks the evaluation period into the signal.

This module combines signals; it does not size positions, penalise turnover or
build a risk model. Hand the composite panel to a signal engine or a backtest.

Rank IC is computed locally rather than by importing
:mod:`src.factors.factor_analysis_core`: the factors package already imports
``src.quantlib.multipletesting``, so the reverse import would be circular.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["combine_factors"]

_METHODS: tuple[str, ...] = ("equal", "explicit", "ic", "icir")
_WEIGHTED_METHODS: tuple[str, ...] = ("ic", "icir")
_MIN_ASSETS = 5
_STD_FLOOR = 1e-12


@dataclass
class CombinationResult:
    """Composite panel, per-row weights and research diagnostics.

    Attributes:
        composite: Composite score per observation time and asset. ``NaN``
            wherever no factor was available or no weight had been estimated
            yet; never silently zero.
        weights: Weight per observation time and factor. Rows before the first
            estimable weight are ``NaN``; weights are held between rebalances.
        diagnostics: ``factor_ic``/``composite_ic``/``correlation`` summaries,
            weight turnover and the settings that produced them.
        method: The combination method that was requested.
    """

    composite: pd.DataFrame
    weights: pd.DataFrame
    diagnostics: dict[str, Any]
    method: str


# --- input guards (same shape as src/quantlib/neutralization.py) ---


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


def _positive_int(value: Any, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _ordered_union(labels: list[pd.Index]) -> pd.Index:
    """Union of labels in first-seen order (input order is preserved)."""
    seen: dict[Any, None] = {}
    for index in labels:
        for label in index:
            seen.setdefault(label, None)
    return pd.Index(list(seen))


def _bounded(values: np.ndarray) -> np.ndarray:
    """Scale each row by its largest magnitude.

    Centering and squared norms can overflow for large inputs (market caps) and
    underflow into a false zero variance for tiny ones (ratios); dividing by the
    row maximum first keeps the arithmetic inside the float range. Mirrors the
    guard in :func:`src.quantlib.neutralization._bounded`.
    """
    units = np.max(np.abs(values), axis=1, keepdims=True)
    units = np.where(np.isfinite(units) & (units > 0), units, 1.0)
    return values / units


def _cross_sectional_z(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-row z-score; rows with fewer than two values or no spread become NaN."""
    values = _bounded(panel.to_numpy(dtype=float))
    counts = np.sum(np.isfinite(values), axis=1, keepdims=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.nanmean(values, axis=1, keepdims=True)
            std = np.nanstd(values, axis=1, ddof=1, keepdims=True)
            z = (values - mean) / std
    usable = np.isfinite(std) & (std > _STD_FLOOR) & (counts >= 2)
    z = np.where(usable, z, np.nan)
    return pd.DataFrame(z, index=panel.index, columns=panel.columns)


# --- IC estimation ---


def _rank_ic(factor: pd.Series, forward: pd.Series, min_assets: int) -> float | None:
    """Spearman correlation of one cross-section; ``None`` when unestimable."""
    mask = factor.notna() & forward.notna()
    if int(mask.sum()) < min_assets:
        return None
    left = factor[mask].rank()
    right = forward[mask].rank()
    left = left - left.mean()
    right = right - right.mean()
    denominator = float(np.sqrt((left * left).sum() * (right * right).sum()))
    if not np.isfinite(denominator) or denominator <= 0:
        return None
    return float((left * right).sum() / denominator)


def _ic_series(factor: pd.DataFrame, forward: pd.DataFrame, min_assets: int) -> pd.Series:
    values = [_rank_ic(factor.loc[time], forward.loc[time], min_assets) for time in factor.index]
    return pd.Series(values, index=factor.index, dtype=float)


def _ic_stats(ic: pd.Series) -> dict[str, Any]:
    clean = ic.dropna()
    count = int(clean.size)
    if count == 0:
        return {
            "ic_mean": None,
            "ic_std": None,
            "ir": None,
            "ic_positive_ratio": None,
            "n_obs": 0,
        }
    mean = float(clean.mean())
    # A sample standard deviation needs two observations; one IC is a point,
    # not a spread. Reporting 0.0 claims the IC is perfectly stable on the
    # strength of a single date, which is why ir and weight_turnover already
    # answer None for the same sample size.
    std = float(clean.std(ddof=1)) if count > 1 else None
    return {
        "ic_mean": mean,
        "ic_std": std,
        "ir": (mean / std) if std is not None and std > 0 else None,
        "ic_positive_ratio": float((clean > 0).mean()),
        "n_obs": count,
    }


def _mean_rank_correlation(panels: Mapping[str, pd.DataFrame], min_assets: int) -> pd.DataFrame:
    """Average per-date Spearman correlation between factor panels."""
    names = list(panels)
    total = pd.DataFrame(0.0, index=names, columns=names)
    seen = pd.DataFrame(0, index=names, columns=names)
    for time in next(iter(panels.values())).index:
        cross = pd.DataFrame({name: panels[name].loc[time] for name in names})
        cross = cross.dropna(how="any")
        if len(cross) < min_assets:
            continue
        correlation = cross.corr(method="spearman")
        total = total.add(correlation.fillna(0.0))
        seen = seen.add(correlation.notna().astype(int))
    return total / seen.replace(0, np.nan)


# --- weights ---


def _constant_weights(names: list[str], index: pd.Index, values: Mapping[str, float]) -> pd.DataFrame:
    row = np.array([float(values[name]) for name in names], dtype=float)
    return pd.DataFrame(np.tile(row, (len(index), 1)), index=index, columns=names)


def _walk_forward_weights(
    ic_history: Mapping[str, pd.Series],
    index: pd.Index,
    *,
    method: str,
    window: int | None,
    min_periods: int,
    rebalance: int,
    insufficient: str,
) -> pd.DataFrame:
    """Estimate weights at each rebalance from strictly earlier IC values."""
    names = list(ic_history)
    frame = pd.DataFrame(np.nan, index=index, columns=names)
    for position in range(0, len(index), rebalance):
        estimates: dict[str, float] = {}
        for name in names:
            history = ic_history[name].iloc[:position].dropna()
            if window is not None:
                history = history.iloc[-window:]
            if len(history) < min_periods:
                continue
            if method == "ic":
                value = float(history.mean())
            else:
                deviation = float(history.std(ddof=1))
                if not deviation > 0:
                    continue
                value = float(history.mean() / deviation)
            if np.isfinite(value):
                estimates[name] = value
        if not estimates:
            if insufficient == "equal":
                # Normalised like every other weight path, and like
                # method="equal": an un-normalised 1.0 per factor leaves the
                # row summing to the factor count, which reads as a full-book
                # rebalance in weight_turnover once a real estimate replaces it.
                frame.iloc[position] = 1.0 / len(names)
            continue
        total = float(sum(abs(value) for value in estimates.values()))
        if not np.isfinite(total) or total <= 0:
            continue
        frame.iloc[position] = [estimates.get(name, 0.0) / total for name in names]
    return frame.ffill()


def _static_weights(weights: Mapping[str, float], names: list[str], index: pd.Index) -> pd.DataFrame:
    missing = [name for name in names if name not in weights]
    unknown = [name for name in weights if name not in names]
    if missing or unknown:
        raise ValueError(f"weights must cover every factor exactly; missing={missing}, unknown={unknown}")
    values: dict[str, float] = {}
    for name in names:
        value = weights[name]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"weight for {name!r} must be a real number")
        if not np.isfinite(float(value)):
            raise ValueError(f"weight for {name!r} must be finite")
        values[name] = float(value)
    if not any(values.values()):
        raise ValueError("at least one weight must be nonzero")
    scale = max(abs(value) for value in values.values())
    scaled = {name: value / scale for name, value in values.items()}
    total = float(sum(abs(value) for value in scaled.values()))
    return _constant_weights(
        names, index, {name: scaled[name] / total for name in names}
    )


def _table_weights(weights: pd.DataFrame, names: list[str], index: pd.Index) -> pd.DataFrame:
    """Align a caller-supplied ``time x factor`` weight table.

    Rows may be supplied only at rebalance dates; they are held forward. A
    missing weight is excluded from that row rather than read as zero, and rows
    whose weights are all missing stay ``NaN`` (honest empty, no default).
    """
    _check_panel(weights, "weights")
    missing = [name for name in names if name not in weights.columns]
    unknown = [column for column in weights.columns if column not in names]
    if missing or unknown:
        raise ValueError(f"weight table must cover every factor exactly; missing={missing}, unknown={unknown}")
    try:
        table = weights.reindex(index=index)[names].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise ValueError("weight table must contain numeric values") from exc
    table = np.where(np.isfinite(table), table, np.nan)
    scale = np.max(
        np.where(np.isfinite(table), np.abs(table), 0.0), axis=1, keepdims=True
    )
    scale = np.where(scale > 0, scale, 1.0)
    table = table / scale
    total = np.nansum(np.abs(table), axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        table = np.divide(
            table, total, out=np.full_like(table, np.nan), where=total > 0
        )
    return pd.DataFrame(table, index=index, columns=names).ffill()


def _turnover(weights: pd.DataFrame) -> float | None:
    effective = weights.dropna(how="all")
    if len(effective) < 2:
        return None
    change = effective.diff().iloc[1:].abs().sum(axis=1)
    return float(change.mean())


# --- public entry point ---


def combine_factors(
    panels: Mapping[str, pd.DataFrame],
    returns: pd.DataFrame | None = None,
    *,
    method: str = "equal",
    weights: Mapping[str, float] | pd.DataFrame | None = None,
    window: int | None = None,
    rebalance: int = 1,
    standardize: bool = True,
    min_assets: int = _MIN_ASSETS,
    min_periods: int = 20,
    insufficient: str = "skip",
) -> CombinationResult:
    """Combine factor panels into one composite score.

    Args:
        panels: Factor name -> panel (time x asset) of factor values.
        returns: Forward-return panel aligned to the factor panels: the value at
            row ``t`` is the return earned *after* observing ``t``. Required for
            ``method="ic"`` and ``"icir"``, unused otherwise.
        method: ``"equal"``, ``"explicit"``, ``"ic"`` (mean rank IC weights) or
            ``"icir"`` (mean/std rank IC weights). IC weights keep the sign, so
            a reversed factor receives a negative weight instead of being
            silently flipped. Use ``"explicit"`` to bring any other method:
            decayed IC, maximum IC, regression or trained weights, risk parity.
        weights: Required by ``method="explicit"`` and rejected otherwise.
            Either a mapping (factor -> constant weight) or a ``time x factor``
            DataFrame for weights that change over time; table rows may cover
            only rebalance dates and are held forward. Values are normalised by
            their absolute sum. A caller-supplied table must already respect
            walk-forward timing: this function cannot see how it was produced.
        window: Number of trailing IC observations used to estimate a weight.
            ``None`` uses all strictly earlier observations.
        rebalance: Re-estimate weights every ``rebalance`` rows; between
            rebalances the last estimate is held.
        standardize: Cross-sectionally z-score each factor per row before
            summing. Recommended when factor units differ.
        min_assets: Minimum instruments with both a factor and a return value
            for an IC observation to count.
        min_periods: Minimum IC observations required before a weight is
            estimated.
        insufficient: ``"skip"`` leaves rows before the first estimate ``NaN``
            (honest empty); ``"equal"`` falls back to equal weights there.

    Returns:
        A :class:`CombinationResult` with the composite panel, the per-row
        weight table and diagnostics.

    Raises:
        ValueError: On unknown method, malformed panels, missing returns for a
            weighted method, or weights that do not match the panel names.
    """
    if method not in _METHODS:
        raise ValueError(f"method must be one of {_METHODS}, got {method!r}")
    if weights is not None and method != "explicit":
        raise ValueError("weights is only accepted with method='explicit'")
    if not isinstance(panels, Mapping) or not panels:
        raise ValueError("panels must be a non-empty mapping of name -> DataFrame")
    for name, panel in panels.items():
        if not isinstance(name, str) or not name:
            raise ValueError("panel names must be non-empty strings")
        _check_panel(panel, f"panels[{name!r}]")
    _positive_int(rebalance, "rebalance")
    _positive_int(min_assets, "min_assets", minimum=2)
    _positive_int(min_periods, "min_periods", minimum=2)
    if window is not None:
        _positive_int(window, "window", minimum=2)
    if insufficient not in ("skip", "equal"):
        raise ValueError("insufficient must be 'skip' or 'equal'")

    names = list(panels)
    index = _ordered_union([panels[name].index for name in names])
    columns = _ordered_union([panels[name].columns for name in names])
    aligned = {
        name: _numeric(panels[name], f"panels[{name!r}]").reindex(index=index, columns=columns) for name in names
    }
    empty = [name for name in names if aligned[name].isna().all().all()]
    if len(empty) == len(names):
        raise ValueError("every factor panel is empty after alignment")

    forward: pd.DataFrame | None = None
    if method in _WEIGHTED_METHODS:
        if returns is None:
            raise ValueError(f"method={method!r} requires a forward-return panel")
        forward = _numeric(returns, "returns").reindex(index=index, columns=columns)

    explicit: Any = None
    if method == "explicit":
        if weights is None:
            raise ValueError("method='explicit' requires weights")
        if isinstance(weights, pd.DataFrame):
            explicit = _table_weights(weights, names, index)
        elif isinstance(weights, Mapping):
            explicit = _static_weights(weights, names, index)
        else:
            raise ValueError("weights must be a mapping of factor -> number or a time x factor DataFrame")

    factor_ic: dict[str, pd.Series] = {}
    if method in _WEIGHTED_METHODS and forward is not None:
        factor_ic = {name: _ic_series(aligned[name], forward, min_assets) for name in names}

    if method == "equal":
        weights_frame = _constant_weights(names, index, {name: 1.0 / len(names) for name in names})
    elif method == "explicit" and isinstance(explicit, pd.DataFrame):
        weights_frame = explicit
    else:
        weights_frame = _walk_forward_weights(
            factor_ic,
            index,
            method=method,
            window=window,
            min_periods=min_periods,
            rebalance=rebalance,
            insufficient=insufficient,
        )

    prepared = {name: _cross_sectional_z(aligned[name]) if standardize else aligned[name] for name in names}

    shape = (len(index), len(columns))
    numerator = np.zeros(shape, dtype=float)
    denominator = np.zeros(shape, dtype=float)
    for name in names:
        values = prepared[name].to_numpy(dtype=float)
        weight = weights_frame[name].to_numpy(dtype=float)[:, None]
        available = np.isfinite(values) & np.isfinite(weight)
        numerator += np.where(available, weight * np.nan_to_num(values), 0.0)
        denominator += np.where(available, np.abs(weight), 0.0)
    composite = np.divide(
        numerator,
        denominator,
        out=np.full(shape, np.nan),
        where=denominator > 0,
    )

    diagnostics: dict[str, Any] = {
        "method": method,
        "weights_source": (
            "caller_table"
            if isinstance(explicit, pd.DataFrame)
            else ("caller_mapping" if isinstance(explicit, Mapping) else method)
        ),
        "standardize": bool(standardize),
        "window": window,
        "rebalance": rebalance,
        "n_factors": len(names),
        "n_observations": int(len(index)),
        "n_assets": int(len(columns)),
        "factor_names": names,
        "factor_ic": pd.DataFrame({name: _ic_stats(factor_ic[name]) for name in names}).T if factor_ic else None,
        "composite_ic": _ic_stats(
            _ic_series(
                pd.DataFrame(composite, index=index, columns=columns),
                forward,
                min_assets,
            )
        )
        if forward is not None
        else None,
        "correlation": _mean_rank_correlation(prepared, min_assets) if len(names) > 1 else None,
        "weight_turnover": _turnover(weights_frame),
        "rows_without_weights": int(weights_frame.isna().all(axis=1).sum()),
        "notes": [
            "factor_ic and composite_ic are full-sample research diagnostics, "
            "not the walk-forward weights used to build the composite",
            "composite is the weighted mean of available factors per row, "
            "renormalised by the available absolute weight",
            f"weights are re-estimated every {rebalance} observation(s); set "
            "rebalance to the holding horizon the strategy will use",
        ],
    }

    return CombinationResult(
        composite=pd.DataFrame(composite, index=index, columns=columns),
        weights=weights_frame,
        diagnostics=diagnostics,
        method=method,
    )
