"""Pure computation core for the run attribution endpoint.

Builds the ``GET /runs/{run_id}/attribution`` payload exclusively from a run's
persisted artifacts (``equity.csv``, ``positions.csv``, ``ohlcv_<SYMBOL>.csv``,
``config.json``, ``metrics.csv``) — no market data is re-fetched. Every section
degrades independently: a missing artifact nulls its section and appends an
explanatory note instead of failing the request.

Mounted by ``attribution_routes.py``; kept in its own module so the route file
stays a thin registration slice.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Module constants (no magic numbers in the computation paths below)
# ---------------------------------------------------------------------------

#: Decimals every response float is rounded to, recursively.
_ATTRIBUTION_FLOAT_DECIMALS = 6
#: Maximum points per returned series; longer series are even-stride
#: downsampled with the last point always pinned.
_ATTRIBUTION_MAX_SERIES_POINTS = 500
#: Trailing window length (in bars) for rolling beta/alpha.
_ATTRIBUTION_ROLLING_WINDOW = 60
#: Minimum valid observations inside a rolling window for it to emit a point.
_ATTRIBUTION_MIN_ROLLING_OBS = 40
#: Minimum aligned observations for the full-sample factor regression.
_ATTRIBUTION_MIN_FACTOR_OBS = 10
#: Benchmark return variance below which the series is treated as constant.
_ATTRIBUTION_BENCHMARK_VARIANCE_FLOOR = 1e-16
#: Smallest positive cash weight reported as a Brinson cash row.
_ATTRIBUTION_CASH_WEIGHT_TOLERANCE = 1e-6
#: Smallest invested weight still reported in the invested/cash fallback.
_ATTRIBUTION_MIN_INVESTED_WEIGHT = 1e-9
#: Net asset-class weight below which asset-class Brinson degrades to the
#: invested/cash fallback instead of dividing by the class weight (a
#: market-neutral pair inside one class nets to zero and would crash).
_ATTRIBUTION_CLASS_WEIGHT_FLOOR = 1e-9
#: Annualization factor used when the run's interval is unknown.
_ATTRIBUTION_DEFAULT_BARS_PER_YEAR = 252

#: Bars per year by normalized (lower-cased) interval label.
_ATTRIBUTION_BARS_PER_YEAR_BY_INTERVAL = {
    "1d": 252,
    "d": 252,
    "daily": 252,
    "1wk": 52,
    "w": 52,
    "weekly": 52,
    "1mo": 12,
    "mo": 12,
    "monthly": 12,
    "1h": 1638,
    "30m": 3276,
    "15m": 6552,
    "5m": 19656,
    "1m": 98280,
}


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _attribution_finite_float(value: Any) -> Optional[float]:
    """Parse a finite float, returning ``None`` for invalid values."""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _attribution_iso_dates(values: List[Any]) -> List[str]:
    """Normalize timestamp cells to ``YYYY-MM-DD`` date-part strings."""
    dates: List[str] = []
    for value in values:
        text = str(value or "").strip()
        for separator in ("T", " "):
            if separator in text:
                text = text.split(separator, 1)[0]
        dates.append(text)
    return dates


def _attribution_bars_per_year(interval: Any) -> int:
    """Infer the annualization factor from the run's bar interval label."""
    if not interval:
        return _ATTRIBUTION_DEFAULT_BARS_PER_YEAR
    return _ATTRIBUTION_BARS_PER_YEAR_BY_INTERVAL.get(
        str(interval).strip().lower(), _ATTRIBUTION_DEFAULT_BARS_PER_YEAR
    )


def _attribution_downsample(
    rows: List[Dict[str, Any]], max_points: int = _ATTRIBUTION_MAX_SERIES_POINTS
) -> List[Dict[str, Any]]:
    """Even-stride downsample a series, always pinning the last point.

    Args:
        rows: Series points in chronological order.
        max_points: Maximum number of points to keep.

    Returns:
        The original list when within budget, otherwise every ``step``-th row
        with the final row replacing the last sampled index when needed.
    """
    count = len(rows)
    if count <= max_points or max_points <= 0:
        return rows
    step = -(-count // max_points)  # ceil division
    indices = list(range(0, count, step))
    if indices[-1] != count - 1:
        indices[-1] = count - 1
    return [rows[index] for index in indices]


def _attribution_round_values(value: Any, decimals: int = _ATTRIBUTION_FLOAT_DECIMALS) -> Any:
    """Recursively round every float in a JSON-ready structure."""
    if isinstance(value, float):
        return round(value, decimals)
    if isinstance(value, dict):
        return {key: _attribution_round_values(item, decimals) for key, item in value.items()}
    if isinstance(value, list):
        return [_attribution_round_values(item, decimals) for item in value]
    return value


def _attribution_read_csv(path: Path) -> Tuple[Optional[List[str]], List[Dict[str, str]]]:
    """Read a CSV into ``(fieldnames, rows)``, refusing symlinks.

    Returns ``(None, [])`` when the file is missing, a symlink, or unreadable.
    """
    try:
        if path.is_symlink() or not path.is_file():
            return None, []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
        return fieldnames, rows
    except (OSError, UnicodeError, csv.Error):
        return None, []


def _attribution_load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON object from disk if present, not a symlink, and dict-shaped."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------


def _attribution_load_equity(
    run_dir: Path,
) -> Tuple[Optional[List[str]], Optional[List[float]], Optional[List[float]], str]:
    """Load dates, portfolio returns, and benchmark equity from ``equity.csv``.

    Args:
        run_dir: Root directory of the run.

    Returns:
        ``(dates, portfolio_returns, benchmark_equity, benchmark_state)`` where
        ``benchmark_state`` is ``"ok"``, ``"missing"``, or ``"non_finite"``.
        Dates and returns are ``None`` when equity.csv itself is unreadable.
    """
    fieldnames, rows = _attribution_read_csv(run_dir / "artifacts" / "equity.csv")
    if fieldnames is None or not rows or "ret" not in fieldnames or "timestamp" not in fieldnames:
        return None, None, None, "missing"

    dates: List[str] = []
    portfolio_returns: List[float] = []
    benchmark_equity: List[float] = []
    has_benchmark_column = "benchmark_equity" in fieldnames
    benchmark_all_blank = True
    for row in rows:
        ret = _attribution_finite_float(row.get("ret"))
        if ret is None:
            continue
        dates.append(str(row.get("timestamp") or ""))
        portfolio_returns.append(ret)
        if has_benchmark_column:
            benchmark_value = _attribution_finite_float(row.get("benchmark_equity"))
            if benchmark_value is not None:
                benchmark_all_blank = False
                benchmark_equity.append(benchmark_value)
            else:
                benchmark_equity.append(float("nan"))

    if not portfolio_returns:
        return None, None, None, "missing"

    if not has_benchmark_column or benchmark_all_blank:
        return _attribution_iso_dates(dates), portfolio_returns, None, "missing"
    if any(math.isnan(value) for value in benchmark_equity):
        return _attribution_iso_dates(dates), portfolio_returns, None, "non_finite"
    return _attribution_iso_dates(dates), portfolio_returns, benchmark_equity, "ok"


def _attribution_benchmark_returns_from_equity(benchmark_equity: List[float]) -> Optional[List[float]]:
    """Convert a benchmark equity curve into daily returns.

    The first bar's return is defined as 0.0 (the curve's first value is the
    first observation, matching the ``pct_change().fillna(0)`` convention).
    """
    if len(benchmark_equity) < 2:
        return None
    returns = [0.0]
    for previous, current in zip(benchmark_equity[:-1], benchmark_equity[1:]):
        if previous <= 0.0:
            return None
        returns.append(current / previous - 1.0)
    return returns


def _attribution_symbol_is_path_safe(symbol: str) -> bool:
    """Reject symbols that could escape the artifacts directory when used in paths.

    Symbols come from ``positions.csv`` headers and ``config.json`` codes and
    are interpolated into ``ohlcv_<symbol>.csv`` file names, so path
    separators, ``..`` sequences, and NUL bytes must never reach the path join.
    """
    return (
        bool(symbol)
        and "\x00" not in symbol
        and "/" not in symbol
        and "\\" not in symbol
        and ".." not in symbol
    )


def _attribution_symbol_cumulative_return(run_dir: Path, symbol: str) -> Optional[float]:
    """Buy-and-hold close-to-close return for one symbol from its OHLCV artifact.

    Returns ``last_close / first_close - 1`` over the date-sorted rows, or
    ``None`` when the artifact is missing, too short, or starts non-positive.
    """
    if not _attribution_symbol_is_path_safe(symbol):
        return None
    fieldnames, rows = _attribution_read_csv(run_dir / "artifacts" / f"ohlcv_{symbol}.csv")
    if fieldnames is None or "close" not in fieldnames or not rows:
        return None
    dated: List[Tuple[str, float]] = []
    for row in rows:
        close = _attribution_finite_float(row.get("close"))
        if close is not None:
            dated.append((str(row.get("trade_date") or ""), close))
    if len(dated) < 2:
        return None
    dated.sort(key=lambda item: item[0])
    first_close = dated[0][1]
    last_close = dated[-1][1]
    if first_close <= 0.0:
        return None
    return last_close / first_close - 1.0


def _attribution_equal_weight_returns(
    run_dir: Path, codes: List[str], dates: List[str]
) -> Optional[List[float]]:
    """Equal-weight daily mean of the configured codes' close-to-close returns.

    Used as the auto-benchmark series when ``equity.csv`` carries no
    ``benchmark_equity`` column. A symbol's first observed date contributes
    0.0. A date with no symbol coverage at all fails the whole series
    (``None``); dates with partial coverage average the available subset.
    """
    if not codes or not dates:
        return None
    per_symbol: List[Dict[str, float]] = []
    for symbol in codes:
        if not _attribution_symbol_is_path_safe(symbol):
            continue
        fieldnames, rows = _attribution_read_csv(run_dir / "artifacts" / f"ohlcv_{symbol}.csv")
        if fieldnames is None or "close" not in fieldnames or not rows:
            continue
        closes: List[Tuple[str, float]] = []
        for row in rows:
            close = _attribution_finite_float(row.get("close"))
            if close is not None:
                closes.append((str(row.get("trade_date") or ""), close))
        if not closes:
            continue
        closes.sort(key=lambda item: item[0])
        returns_by_date: Dict[str, float] = {closes[0][0]: 0.0}
        for index in range(1, len(closes)):
            previous_close = closes[index - 1][1]
            if previous_close > 0.0:
                returns_by_date[closes[index][0]] = closes[index][1] / previous_close - 1.0
        per_symbol.append(returns_by_date)
    if not per_symbol:
        return None
    series: List[float] = []
    for day in dates:
        values = [table[day] for table in per_symbol if day in table and math.isfinite(table[day])]
        if not values:
            return None
        series.append(math.fsum(values) / len(values))
    return series


# ---------------------------------------------------------------------------
# Factor section
# ---------------------------------------------------------------------------


def _attribution_ols(x_values: List[float], y_values: List[float]) -> Optional[Dict[str, float]]:
    """Ordinary least squares of ``y`` on ``x`` with an intercept.

    Returns ``{"alpha", "beta", "r_squared", "alpha_t_stat"}`` where
    ``alpha_t_stat`` is the t-statistic of the intercept, or ``None`` when the
    regressor variance is below ``_ATTRIBUTION_BENCHMARK_VARIANCE_FLOOR``.
    """
    n = len(x_values)
    if n < 2 or n != len(y_values):
        return None
    mean_x = math.fsum(x_values) / n
    mean_y = math.fsum(y_values) / n
    sxx = math.fsum((x - mean_x) ** 2 for x in x_values)
    if sxx / n < _ATTRIBUTION_BENCHMARK_VARIANCE_FLOOR:
        return None
    sxy = math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    ssr = math.fsum((y - alpha - beta * x) ** 2 for x, y in zip(x_values, y_values))
    sst = math.fsum((y - mean_y) ** 2 for y in y_values)
    if sst <= 0.0:
        r_squared = 1.0 if ssr <= 0.0 else 0.0
    else:
        r_squared = max(0.0, min(1.0, 1.0 - ssr / sst))
    alpha_t_stat = 0.0
    if n > 2:
        sigma_squared = ssr / (n - 2)
        variance_alpha = sigma_squared * (1.0 / n + mean_x * mean_x / sxx)
        if variance_alpha > 0.0:
            alpha_t_stat = alpha / math.sqrt(variance_alpha)
    return {"alpha": alpha, "beta": beta, "r_squared": r_squared, "alpha_t_stat": alpha_t_stat}


def _attribution_factor_section(
    dates: List[str],
    portfolio_returns: List[float],
    benchmark_returns: Optional[List[float]],
    bars_per_year: int,
    notes: List[str],
) -> Optional[Dict[str, Any]]:
    """Build the factor section: full-sample OLS plus rolling and cumulative series.

    Args:
        dates: Equity-curve dates aligned with ``portfolio_returns``.
        portfolio_returns: Portfolio daily returns from ``equity.csv``.
        benchmark_returns: Benchmark daily returns, or ``None`` when no usable
            benchmark series exists.
        bars_per_year: Annualization factor for the run interval.
        notes: Note accumulator; skip reasons are appended here.

    Returns:
        The factor section dict, or ``None`` with an explanatory note.
    """
    if benchmark_returns is None:
        notes.append("factor attribution skipped: no benchmark_equity series in equity.csv")
        return None

    count = min(len(dates), len(portfolio_returns), len(benchmark_returns))
    aligned: List[Tuple[str, float, float]] = []
    for index in range(count):
        portfolio_value = portfolio_returns[index]
        benchmark_value = benchmark_returns[index]
        if math.isfinite(portfolio_value) and math.isfinite(benchmark_value):
            aligned.append((dates[index], portfolio_value, benchmark_value))

    if not aligned:
        notes.append("factor attribution skipped: benchmark return series is missing or constant")
        return None
    if len(aligned) < _ATTRIBUTION_MIN_FACTOR_OBS:
        notes.append(
            "factor attribution skipped: only "
            f"{len(aligned)} observations available (need at least {_ATTRIBUTION_MIN_FACTOR_OBS})"
        )
        return None

    x_values = [row[2] for row in aligned]
    y_values = [row[1] for row in aligned]
    fit = _attribution_ols(x_values, y_values)
    if fit is None:
        notes.append("factor attribution skipped: benchmark return series is missing or constant")
        return None

    rolling: Optional[List[Dict[str, Any]]] = None
    if len(aligned) >= _ATTRIBUTION_ROLLING_WINDOW:
        points: List[Dict[str, Any]] = []
        for end in range(_ATTRIBUTION_ROLLING_WINDOW, len(aligned) + 1):
            window = aligned[end - _ATTRIBUTION_ROLLING_WINDOW : end]
            window_fit = _attribution_ols([row[2] for row in window], [row[1] for row in window])
            if window_fit is None:
                continue
            points.append(
                {
                    "date": window[-1][0],
                    "beta": window_fit["beta"],
                    "alpha_annualized": window_fit["alpha"] * bars_per_year,
                }
            )
        rolling = points or None

    cumulative: List[Dict[str, Any]] = []
    portfolio_wealth = 1.0
    benchmark_wealth = 1.0
    for day, portfolio_value, benchmark_value in aligned:
        portfolio_wealth *= 1.0 + portfolio_value
        benchmark_wealth *= 1.0 + benchmark_value
        cumulative.append(
            {
                "date": day,
                "portfolio": portfolio_wealth - 1.0,
                "benchmark": benchmark_wealth - 1.0,
                "active": portfolio_wealth - benchmark_wealth,
            }
        )

    return {
        "beta": fit["beta"],
        "alpha_per_period": fit["alpha"],
        "alpha_annualized": fit["alpha"] * bars_per_year,
        "alpha_t_stat": fit["alpha_t_stat"],
        "r_squared": fit["r_squared"],
        "n_obs": len(aligned),
        "rolling_window": _ATTRIBUTION_ROLLING_WINDOW,
        "rolling": _attribution_downsample(rolling) if rolling is not None else None,
        "cumulative": _attribution_downsample(cumulative),
    }


# ---------------------------------------------------------------------------
# Brinson section
# ---------------------------------------------------------------------------


def _attribution_run_brinson(
    mode: str,
    portfolio_weights: Dict[str, float],
    benchmark_weights: Dict[str, float],
    portfolio_returns: Dict[str, float],
    benchmark_returns: Dict[str, float],
    notes: List[str],
) -> Optional[Dict[str, Any]]:
    """Run ``brinson_fachler`` and serialize the result into the response shape.

    Args:
        mode: One of ``"symbol"``, ``"asset_class"``, ``"invested_cash"``.
        portfolio_weights: Sector label to portfolio weight.
        benchmark_weights: Sector label to benchmark weight.
        portfolio_returns: Sector label to portfolio sector return.
        benchmark_returns: Sector label to benchmark sector return.
        notes: Note accumulator; skip reasons are appended here.

    Returns:
        The serialized Brinson section, or ``None`` with an explanatory note.
    """
    if not portfolio_weights or not benchmark_weights or math.fsum(benchmark_weights.values()) == 0.0:
        notes.append("brinson attribution skipped: benchmark weight vector sums to zero")
        return None
    try:
        from src.quantlib.attribution import brinson_fachler

        result = brinson_fachler(
            portfolio_weights, benchmark_weights, portfolio_returns, benchmark_returns
        )
    except ValueError as exc:
        notes.append(f"brinson attribution skipped: {exc}")
        return None
    return {
        "mode": mode,
        "portfolio_return": result.portfolio_return,
        "benchmark_return": result.benchmark_return,
        "active_return": result.active_return,
        "allocation": result.allocation,
        "selection": result.selection,
        "interaction": result.interaction,
        "sectors": [
            {
                "sector": sector.sector,
                "portfolio_weight": sector.portfolio_weight,
                "benchmark_weight": sector.benchmark_weight,
                "portfolio_return": sector.portfolio_return,
                "benchmark_return": sector.benchmark_return,
                "allocation": sector.allocation,
                "selection": sector.selection,
                "interaction": sector.interaction,
                "total": sector.total,
            }
            for sector in result.sectors
        ],
    }


def _attribution_load_position_weights(run_dir: Path, notes: List[str]) -> Optional[Dict[str, float]]:
    """Read the last row of ``positions.csv`` as per-symbol weights.

    Returns ``None`` (with a skip note) when the artifact is missing or cannot
    be parsed into at least one weighted symbol column.
    """
    path = run_dir / "artifacts" / "positions.csv"
    try:
        if path.is_symlink() or not path.is_file():
            notes.append("brinson attribution skipped: positions.csv not found")
            return None
    except OSError:
        notes.append("brinson attribution skipped: positions.csv not found")
        return None
    fieldnames, rows = _attribution_read_csv(path)
    if fieldnames is None or len(fieldnames) < 2 or not rows:
        notes.append("brinson attribution skipped: positions.csv could not be parsed")
        return None
    symbols = [name.strip() for name in fieldnames[1:] if name and name.strip()]
    if not symbols:
        notes.append("brinson attribution skipped: positions.csv could not be parsed")
        return None
    last_row = rows[-1]
    weights: Dict[str, float] = {}
    for symbol in symbols:
        weight = _attribution_finite_float(last_row.get(symbol))
        weights[symbol] = weight if weight is not None else 0.0
    return weights


def _attribution_brinson_section(
    run_dir: Path,
    codes: List[str],
    benchmark_ticker: Optional[str],
    portfolio_returns: List[float],
    benchmark_equity_state: str,
    benchmark_equity: Optional[List[float]],
    notes: List[str],
) -> Optional[Dict[str, Any]]:
    """Build the Brinson-Fachler section in symbol, asset_class, or fallback mode.

    Args:
        run_dir: Root directory of the run.
        codes: Configured symbols from ``config.json``.
        benchmark_ticker: Explicit benchmark ticker, or ``None`` in auto mode.
        portfolio_returns: Portfolio daily returns from ``equity.csv``.
        benchmark_equity_state: ``"ok"``, ``"missing"``, or ``"non_finite"``.
        benchmark_equity: Finite benchmark equity values when state is ``"ok"``.
        notes: Note accumulator; skip reasons are appended here.

    Returns:
        The Brinson section dict, or ``None`` with an explanatory note.
    """
    weights = _attribution_load_position_weights(run_dir, notes)
    if weights is None:
        return None
    if all(weight == 0.0 for weight in weights.values()):
        notes.append("brinson attribution skipped: all position weights are zero")
        return None

    if benchmark_ticker is None:
        return _attribution_brinson_symbol_mode(run_dir, codes, weights, notes)
    return _attribution_brinson_asset_class_mode(
        run_dir, benchmark_ticker, weights, portfolio_returns,
        benchmark_equity_state, benchmark_equity, notes,
    )


def _attribution_brinson_symbol_mode(
    run_dir: Path,
    codes: List[str],
    weights: Dict[str, float],
    notes: List[str],
) -> Optional[Dict[str, Any]]:
    """Symbol-mode Brinson: each configured symbol is its own sector.

    Portfolio weights come from the last ``positions.csv`` row; benchmark
    weights are equal weight; both sides share the same buy-and-hold per-symbol
    returns, so selection and interaction vanish by construction.
    """
    candidates = codes or list(weights)
    symbols = [symbol for symbol in candidates if symbol in weights] or list(weights)
    returns: Dict[str, float] = {}
    for symbol in symbols:
        symbol_return = _attribution_symbol_cumulative_return(run_dir, symbol)
        if symbol_return is not None:
            returns[symbol] = symbol_return
    included = [symbol for symbol in symbols if symbol in returns]
    if not included:
        notes.append(
            "brinson attribution skipped: no per-symbol returns could be resolved from ohlcv artifacts"
        )
        return None

    portfolio_weights = {symbol: weights.get(symbol, 0.0) for symbol in included}
    portfolio_returns_map = dict(returns)
    benchmark_weights = {symbol: 1.0 / len(included) for symbol in included}
    cash_weight = 1.0 - math.fsum(portfolio_weights.values())
    if cash_weight > _ATTRIBUTION_CASH_WEIGHT_TOLERANCE:
        portfolio_weights["Cash"] = cash_weight
        portfolio_returns_map["Cash"] = 0.0

    notes.append(
        "brinson attribution computed in symbol-mode: buy-and-hold per-symbol returns, "
        "portfolio weights vs equal-weight benchmark"
    )
    return _attribution_run_brinson(
        "symbol", portfolio_weights, benchmark_weights, portfolio_returns_map, dict(returns), notes
    )


def _attribution_brinson_asset_class_mode(
    run_dir: Path,
    benchmark_ticker: str,
    weights: Dict[str, float],
    portfolio_returns: List[float],
    benchmark_equity_state: str,
    benchmark_equity: Optional[List[float]],
    notes: List[str],
) -> Optional[Dict[str, Any]]:
    """Asset-class Brinson against an explicit benchmark.

    Symbols are grouped by asset class; the benchmark is 100% in the benchmark
    ticker's own class, whose return is the cumulative ``benchmark_equity``
    return. Degrades to an invested/cash decomposition when class returns
    cannot be resolved.
    """
    from backtest.engines._market_hooks import _detect_market

    if benchmark_equity_state == "non_finite":
        notes.append("brinson attribution skipped: benchmark_equity contains non-finite values")
        return None
    if benchmark_equity_state != "ok" or not benchmark_equity:
        notes.append("brinson attribution skipped: no benchmark_equity series in equity.csv")
        return None
    if benchmark_equity[0] <= 0.0:
        notes.append("brinson attribution skipped: benchmark_equity starts at a non-positive value")
        return None
    benchmark_cumulative = benchmark_equity[-1] / benchmark_equity[0] - 1.0
    benchmark_class = str(_detect_market(benchmark_ticker))

    class_weights: Dict[str, float] = {}
    class_return_sums: Dict[str, float] = {}
    for symbol, weight in weights.items():
        if weight == 0.0:
            continue
        asset_class = str(_detect_market(symbol))
        class_weights[asset_class] = class_weights.get(asset_class, 0.0) + weight
        symbol_return = _attribution_symbol_cumulative_return(run_dir, symbol)
        if symbol_return is not None:
            class_return_sums[asset_class] = class_return_sums.get(asset_class, 0.0) + weight * symbol_return

    portfolio_weights: Dict[str, float] = {}
    portfolio_returns_by_class: Dict[str, float] = {}
    degraded = False
    for asset_class, class_weight in class_weights.items():
        # A class whose long/short weights net to zero (market-neutral pair
        # inside one class) would divide by zero below; degrade instead.
        if asset_class not in class_return_sums or abs(class_weight) <= _ATTRIBUTION_CLASS_WEIGHT_FLOOR:
            degraded = True
            break
        portfolio_weights[asset_class] = class_weight
        portfolio_returns_by_class[asset_class] = class_return_sums[asset_class] / class_weight

    if degraded:
        return _attribution_brinson_invested_cash_mode(
            benchmark_class, benchmark_cumulative, weights, portfolio_returns, notes
        )

    cash_weight = 1.0 - math.fsum(portfolio_weights.values())
    if cash_weight > _ATTRIBUTION_CASH_WEIGHT_TOLERANCE:
        portfolio_weights["Cash"] = cash_weight
        portfolio_returns_by_class["Cash"] = 0.0

    notes.append(
        "brinson attribution in asset_class mode uses a buy-and-hold approximation "
        "for portfolio sector returns"
    )
    return _attribution_run_brinson(
        "asset_class",
        portfolio_weights,
        {benchmark_class: 1.0},
        portfolio_returns_by_class,
        {benchmark_class: benchmark_cumulative},
        notes,
    )


def _attribution_brinson_invested_cash_mode(
    benchmark_class: str,
    benchmark_cumulative: float,
    weights: Dict[str, float],
    portfolio_returns: List[float],
    notes: List[str],
) -> Optional[Dict[str, Any]]:
    """Invested/cash fallback Brinson when class-level returns are unavailable."""
    invested_weight = math.fsum(abs(weight) for weight in weights.values())
    if invested_weight < _ATTRIBUTION_MIN_INVESTED_WEIGHT:
        notes.append("brinson attribution skipped: all position weights are zero")
        return None
    portfolio_wealth = 1.0
    for value in portfolio_returns:
        if math.isfinite(value):
            portfolio_wealth *= 1.0 + value
    invested_return = portfolio_wealth - 1.0

    notes.append("brinson attribution degraded to invested/cash decomposition")
    return _attribution_run_brinson(
        "invested_cash",
        {"invested": invested_weight, "Cash": 1.0 - invested_weight},
        {benchmark_class: 1.0},
        {"invested": invested_return, "Cash": 0.0},
        {benchmark_class: benchmark_cumulative},
        notes,
    )


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def _build_attribution_payload(run_dir: Path) -> Dict[str, Any]:
    """Assemble the full attribution payload from a run's artifacts.

    Args:
        run_dir: Root directory of the run.

    Returns:
        The response contract dict ``{"exists", "benchmark", "factor",
        "brinson", "notes"}`` with unrounded floats; the route rounds it.
    """
    notes: List[str] = []
    payload: Dict[str, Any] = {
        "exists": False,
        "benchmark": None,
        "factor": None,
        "brinson": None,
        "notes": notes,
    }

    config = _attribution_load_json(run_dir / "config.json") or {}
    raw_codes = config.get("codes")
    codes: List[str] = []
    if isinstance(raw_codes, list):
        codes = [str(code) for code in raw_codes if str(code).strip()]
    bars_per_year = _attribution_bars_per_year(config.get("interval"))

    # Mirror the factor scan's symlink rejection: a symlinked artifacts dir is
    # treated as having no readable artifacts rather than followed.
    artifacts_dir = run_dir / "artifacts"
    try:
        artifacts_usable = artifacts_dir.is_dir() and not artifacts_dir.is_symlink()
    except OSError:
        artifacts_usable = False

    if artifacts_usable:
        dates, portfolio_returns, benchmark_equity, benchmark_state = _attribution_load_equity(run_dir)
    else:
        dates, portfolio_returns, benchmark_equity, benchmark_state = None, None, None, "missing"

    if dates is None or portfolio_returns is None:
        notes.append("attribution skipped: equity.csv is missing or unreadable")
        return payload
    payload["exists"] = True

    benchmark_ticker: Optional[str] = None
    config_benchmark = config.get("benchmark")
    if isinstance(config_benchmark, dict):
        config_benchmark = config_benchmark.get("ticker") or config_benchmark.get("code")
    if config_benchmark is not None and str(config_benchmark).strip():
        benchmark_ticker = str(config_benchmark).strip()
    if benchmark_ticker is None:
        _metrics_fields, metrics_rows = _attribution_read_csv(run_dir / "artifacts" / "metrics.csv")
        if metrics_rows:
            candidate = metrics_rows[0].get("benchmark_ticker")
            if candidate is not None and str(candidate).strip():
                benchmark_ticker = str(candidate).strip()

    if benchmark_ticker is not None:
        payload["benchmark"] = {"ticker": benchmark_ticker, "mode": "explicit"}
    else:
        payload["benchmark"] = {"ticker": None, "mode": "auto_equal_weight"}

    benchmark_returns: Optional[List[float]] = None
    if benchmark_state == "ok" and benchmark_equity is not None:
        benchmark_returns = _attribution_benchmark_returns_from_equity(benchmark_equity)
    if benchmark_returns is None and benchmark_ticker is None:
        benchmark_returns = _attribution_equal_weight_returns(run_dir, codes, dates)

    payload["factor"] = _attribution_factor_section(
        dates, portfolio_returns, benchmark_returns, bars_per_year, notes
    )
    payload["brinson"] = _attribution_brinson_section(
        run_dir,
        codes,
        benchmark_ticker,
        portfolio_returns,
        benchmark_state,
        benchmark_equity,
        notes,
    )
    return payload
