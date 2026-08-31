"""Statistical validation for backtest results.

Three independent tools:
  - Monte Carlo permutation test: is the strategy significantly better than random?
  - Bootstrap Sharpe CI: how stable is the risk-adjusted return?
  - Walk-Forward analysis: is performance consistent across time windows?

Usage: called automatically by BaseEngine.run_backtest when config[\"validation\"]
is present, or invoked directly on backtest outputs.
"""

from __future__ import annotations

import json
import math
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest.models import TradeRecord


# ─── Monte Carlo Permutation Test ───


def monte_carlo_test(
    trades: List[TradeRecord],
    initial_capital: float,
    n_simulations: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Shuffle trade PnL order to test path significance.

    Null hypothesis: the observed Sharpe / max-drawdown is no better than
    a random ordering of the same trades.

    All Sharpe figures here are computed on the *per-trade* realised-PnL
    sequence (one observation per closed trade), then annualised by the
    strategy's realised trade frequency — ``sqrt(trades_per_year)``, derived
    from the first entry and last exit timestamp. The previous implementation
    hard-coded ``sqrt(252)`` as if each trade were one trading day, which
    inflated the reported Sharpe by ``sqrt(252 / trades_per_year)`` (roughly
    8x for a ~12-trade multi-year backtest). The p-values are unchanged by
    this: a constant factor applied to both the actual and every simulated
    Sharpe cannot change their ordering.

    ``actual_max_dd`` is the drawdown of the realised-PnL path (visible only
    at trade-exit granularity); it is deliberately *not* the mark-to-market
    daily max drawdown reported on the run card, because the permutation test
    is about trade ordering, not intraday marks.

    Args:
        trades: Completed round-trip trades from backtest.
        initial_capital: Starting capital.
        n_simulations: Number of random permutations.
        seed: Random seed for reproducibility.

    Returns:
        Dict with actual_sharpe, p_value_sharpe, actual_max_dd,
        p_value_max_dd, simulated_sharpe percentiles, plus ``basis``,
        ``trades_per_year`` and ``annualization_factor``.
    """
    if isinstance(n_simulations, bool) or not isinstance(n_simulations, Integral) or n_simulations < 1:
        return {
            "error": f"n_simulations must be >= 1, got {n_simulations}",
            "p_value_sharpe": 1.0,
        }
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        return {"error": f"seed must be >= 0, got {seed}", "p_value_sharpe": 1.0}
    if len(trades) < 3:
        return {"error": "need at least 3 trades", "p_value_sharpe": 1.0}

    pnls = np.array([t.pnl for t in trades])
    ann_factor, trades_per_year = _trade_annualization(trades)
    actual = _path_metrics(pnls, initial_capital, ann_factor)

    rng = np.random.default_rng(seed)
    sharpe_count = 0
    dd_count = 0
    sim_sharpes = []
    # The full path matrix feeds the fan-chart payload; skip it for
    # pathological sizes so a huge run cannot balloon memory or the JSON.
    keep_paths = n_simulations * len(pnls) <= 2_000_000
    sim_equities = np.empty((n_simulations, len(pnls))) if keep_paths else None

    for i in range(n_simulations):
        shuffled = rng.permutation(pnls)
        if sim_equities is not None:
            sim_equities[i] = initial_capital + np.cumsum(shuffled)
        sim = _path_metrics(shuffled, initial_capital, ann_factor)
        sim_sharpes.append(sim["sharpe"])
        if sim["sharpe"] >= actual["sharpe"]:
            sharpe_count += 1
        if sim["max_dd"] >= actual["max_dd"]:  # less negative = "better"
            dd_count += 1

    sim_arr = np.array(sim_sharpes)
    result = {
        "actual_sharpe": round(actual["sharpe"], 4),
        "actual_max_dd": round(actual["max_dd"], 4),
        "p_value_sharpe": round(sharpe_count / n_simulations, 4),
        "p_value_max_dd": round(dd_count / n_simulations, 4),
        "simulated_sharpe_mean": round(float(sim_arr.mean()), 4),
        "simulated_sharpe_std": round(float(sim_arr.std()), 4),
        "simulated_sharpe_p5": round(float(np.percentile(sim_arr, 5)), 4),
        "simulated_sharpe_p95": round(float(np.percentile(sim_arr, 95)), 4),
        "n_simulations": n_simulations,
        "n_trades": len(trades),
        "trades_per_year": round(trades_per_year, 2) if trades_per_year else None,
        "annualization_factor": round(ann_factor, 4),
        "basis": (
            "per-trade realised PnL sequence; Sharpe annualised by realised "
            "trade frequency (sqrt(trades_per_year)), not sqrt(252)"
        ),
        "sharpe_samples": [round(float(s), 4) for s in sim_sharpes],
    }
    if sim_equities is not None:
        idx = np.unique(np.linspace(0, len(pnls) - 1, min(len(pnls), 400)).astype(int))
        sample_rows = np.unique(
            np.linspace(0, n_simulations - 1, min(30, n_simulations)).astype(int)
        )
        result["equity_paths"] = {
            "steps": (idx + 1).tolist(),
            "initial_capital": round(float(initial_capital), 2),
            "actual": np.round((initial_capital + np.cumsum(pnls))[idx], 2).tolist(),
            "band_p5": np.round(np.percentile(sim_equities[:, idx], 5, axis=0), 2).tolist(),
            "band_p25": np.round(np.percentile(sim_equities[:, idx], 25, axis=0), 2).tolist(),
            "band_p50": np.round(np.percentile(sim_equities[:, idx], 50, axis=0), 2).tolist(),
            "band_p75": np.round(np.percentile(sim_equities[:, idx], 75, axis=0), 2).tolist(),
            "band_p95": np.round(np.percentile(sim_equities[:, idx], 95, axis=0), 2).tolist(),
            "samples": np.round(sim_equities[np.ix_(sample_rows, idx)], 2).tolist(),
        }
    return result


def _path_metrics(
    pnls: np.ndarray, initial_capital: float, ann_factor: float = 1.0
) -> Dict[str, float]:
    """Sharpe and max drawdown from a per-trade PnL sequence.

    ``ann_factor`` scales the raw per-trade Sharpe to an annual figure; it is
    ``sqrt(trades_per_year)`` (see :func:`_trade_annualization`). Pass ``1.0``
    to get the un-annualised per-trade Sharpe.
    """
    equity = initial_capital + np.cumsum(pnls)
    if len(equity) > 1:
        prev = equity[:-1]
        diff = np.diff(equity)
        returns = np.where(prev != 0, diff / np.where(prev != 0, prev, 1.0), 0.0)
    else:
        returns = np.array([0.0])
    std = returns.std()
    sharpe = float(returns.mean() / (std + 1e-10) * ann_factor)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1.0)
    max_dd = float(dd.min())
    return {"sharpe": sharpe, "max_dd": max_dd}


def _trade_annualization(trades: List[TradeRecord]) -> tuple[float, float | None]:
    """Return ``(sqrt(trades_per_year), trades_per_year)`` from the realised
    trade cadence — first entry to last exit. Falls back to ``(1.0, None)``
    (no annualisation) when the timestamps are missing or span no time, so a
    Sharpe is never silently annualised on a wrong basis.
    """
    try:
        stamps = [pd.Timestamp(t.entry_time) for t in trades]
        stamps += [pd.Timestamp(t.exit_time) for t in trades]
        stamps = [s for s in stamps if not pd.isna(s)]
        span_days = (max(stamps) - min(stamps)).total_seconds() / 86_400.0
    except (ValueError, TypeError, AttributeError):
        return 1.0, None
    if span_days <= 0 or len(trades) == 0:
        return 1.0, None
    trades_per_year = len(trades) / (span_days / 365.25)
    return math.sqrt(trades_per_year), trades_per_year


# ─── Bootstrap Sharpe CI ───


def bootstrap_sharpe_ci(
    equity_curve: pd.Series,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    bars_per_year: int = 252,
    seed: int = 42,
) -> Dict[str, Any]:
    """Resample daily returns to estimate Sharpe confidence interval.

    Args:
        equity_curve: Equity time series.
        n_bootstrap: Number of bootstrap samples.
        confidence: Confidence level (e.g. 0.95 for 95% CI).
        bars_per_year: Annualisation factor.
        seed: Random seed.

    Returns:
        Dict with observed_sharpe, ci_lower, ci_upper, median_sharpe,
        prob_positive (fraction of samples with Sharpe > 0).
    """
    if isinstance(n_bootstrap, bool) or not isinstance(n_bootstrap, Integral) or n_bootstrap < 1:
        return {"error": f"n_bootstrap must be >= 1, got {n_bootstrap}"}
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, Real)
        or not math.isfinite(float(confidence))
        or not 0.0 < confidence < 1.0
    ):
        return {"error": f"confidence must be in (0, 1), got {confidence}"}
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        return {"error": f"seed must be >= 0, got {seed}"}

    returns = equity_curve.pct_change().replace([np.inf, -np.inf], 0.0).dropna().values
    if len(returns) < 5:
        return {"error": "need at least 5 return observations"}

    observed = _sharpe(returns, bars_per_year)

    rng = np.random.default_rng(seed)
    boot_sharpes = []
    for _ in range(n_bootstrap):
        sample = rng.choice(returns, size=len(returns), replace=True)
        boot_sharpes.append(_sharpe(sample, bars_per_year))

    arr = np.array(boot_sharpes)
    alpha = (1 - confidence) / 2
    lower = float(np.percentile(arr, alpha * 100))
    upper = float(np.percentile(arr, (1 - alpha) * 100))
    prob_pos = float(np.mean(arr > 0))

    result = {
        "observed_sharpe": round(observed, 4),
        "ci_lower": round(lower, 4),
        "ci_upper": round(upper, 4),
        "median_sharpe": round(float(np.median(arr)), 4),
        "prob_positive": round(prob_pos, 4),
        "confidence": confidence,
        "n_bootstrap": n_bootstrap,
    }
    if n_bootstrap <= 20_000:
        result["sharpe_samples"] = [round(float(s), 4) for s in boot_sharpes]
    return result


def _sharpe(returns: np.ndarray, bars_per_year: int = 252) -> float:
    std = returns.std()
    return float(returns.mean() / (std + 1e-10) * np.sqrt(bars_per_year))


# ─── Walk-Forward Analysis ───


def walk_forward_analysis(
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    n_windows: int = 5,
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Split backtest into sequential windows, check consistency.

    Each window is evaluated independently (returns normalised to window start).

    Args:
        equity_curve: Equity time series.
        trades: Completed trades.
        n_windows: Number of non-overlapping windows.
        bars_per_year: Annualisation factor.

    Returns:
        Dict with per_window stats, consistency metrics.
    """
    if isinstance(n_windows, bool) or not isinstance(n_windows, Integral) or n_windows < 1:
        return {"error": f"n_windows must be >= 1, got {n_windows}"}
    if len(equity_curve) < n_windows * 2:
        return {"error": f"need at least {n_windows * 2} bars for {n_windows} windows"}

    indices = equity_curve.index
    window_size = len(indices) // n_windows
    windows = []

    for i in range(n_windows):
        start_idx = i * window_size
        end_idx = (i + 1) * window_size if i < n_windows - 1 else len(indices)
        win_eq = equity_curve.iloc[start_idx:end_idx]
        win_start = indices[start_idx]
        win_end = indices[end_idx - 1]

        # Per-window trades
        win_trades = [t for t in trades if win_start <= t.entry_time <= win_end]

        # Per-window metrics
        ret = float(win_eq.iloc[-1] / win_eq.iloc[0] - 1) if win_eq.iloc[0] > 0 else 0.0
        win_returns = win_eq.pct_change().replace([np.inf, -np.inf], 0.0).dropna().values
        sharpe = _sharpe(win_returns, bars_per_year) if len(win_returns) > 1 else 0.0

        peak = win_eq.cummax()
        dd = (win_eq - peak) / peak.replace(0, 1)
        max_dd = float(dd.min())

        win_pnls = [t.pnl for t in win_trades]
        win_rate = len([p for p in win_pnls if p > 0]) / len(win_pnls) if win_pnls else 0.0

        windows.append(
            {
                "window": i + 1,
                "start": str(win_start.date()) if hasattr(win_start, "date") else str(win_start),
                "end": str(win_end.date()) if hasattr(win_end, "date") else str(win_end),
                "return": round(ret, 6),
                "sharpe": round(sharpe, 4),
                "max_dd": round(max_dd, 6),
                "trades": len(win_trades),
                "win_rate": round(win_rate, 4),
            }
        )

    # Consistency metrics
    returns_list = [w["return"] for w in windows]
    sharpes_list = [w["sharpe"] for w in windows]
    profitable_windows = sum(1 for r in returns_list if r > 0)

    return {
        "n_windows": n_windows,
        "windows": windows,
        "profitable_windows": profitable_windows,
        "consistency_rate": round(profitable_windows / n_windows, 4),
        "return_mean": round(float(np.mean(returns_list)), 6),
        "return_std": round(float(np.std(returns_list)), 6),
        "sharpe_mean": round(float(np.mean(sharpes_list)), 4),
        "sharpe_std": round(float(np.std(sharpes_list)), 4),
    }


# ─── Runner integration ───


def run_validation(
    config: Dict[str, Any],
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    initial_capital: float,
    bars_per_year: int = 252,
) -> Dict[str, Any]:
    """Run configured validation checks.

    Reads from config["validation"]:
      - monte_carlo: {n_simulations, seed}
      - bootstrap: {n_bootstrap, confidence, seed}
      - walk_forward: {n_windows}

    Args:
        config: Backtest config (must contain "validation" key).
        equity_curve: Equity time series.
        trades: Completed trades.
        initial_capital: Starting capital.
        bars_per_year: Annualisation factor.

    Returns:
        Dict keyed by validation type with results.
    """
    v_cfg = config.get("validation", {})
    results: Dict[str, Any] = {}

    if "monte_carlo" in v_cfg:
        mc_cfg = v_cfg["monte_carlo"] if isinstance(v_cfg["monte_carlo"], dict) else {}
        results["monte_carlo"] = monte_carlo_test(
            trades,
            initial_capital,
            n_simulations=mc_cfg.get("n_simulations", 1000),
            seed=mc_cfg.get("seed", 42),
        )

    if "bootstrap" in v_cfg:
        bs_cfg = v_cfg["bootstrap"] if isinstance(v_cfg["bootstrap"], dict) else {}
        results["bootstrap"] = bootstrap_sharpe_ci(
            equity_curve,
            bars_per_year=bars_per_year,
            n_bootstrap=bs_cfg.get("n_bootstrap", 1000),
            confidence=bs_cfg.get("confidence", 0.95),
            seed=bs_cfg.get("seed", 42),
        )

    if "walk_forward" in v_cfg:
        wf_cfg = v_cfg["walk_forward"] if isinstance(v_cfg["walk_forward"], dict) else {}
        results["walk_forward"] = walk_forward_analysis(
            equity_curve,
            trades,
            n_windows=wf_cfg.get("n_windows", 5),
            bars_per_year=bars_per_year,
        )

    return results


# ─── Standalone CLI ───


def _load_equity(run_dir: Path) -> pd.Series:
    """Load equity curve from artifacts/equity.csv."""
    path = run_dir / "artifacts" / "equity.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    for col in ("equity", "nav", "value"):
        if col in df.columns:
            return df[col]
    raise ValueError(
        f"equity.csv must contain an equity/nav/value column; got {list(df.columns)}"
    )


def _load_trades(run_dir: Path) -> List[TradeRecord]:
    """Load trades from artifacts/trades.csv and convert to TradeRecord list."""
    path = run_dir / "artifacts" / "trades.csv"
    df = pd.read_csv(path)
    if df.empty:
        return []

    # trades.csv is time-ordered entry/exit rows. An entry row carries no
    # realised numbers (pnl / holding / return_pct all zero); an exit row
    # carries at least one. Pair each exit with the most recent open entry of
    # the same code so entry_time / entry_price are real — the old code keyed
    # only on ``pnl != 0`` (dropping zero-PnL exits) and stamped entry_time
    # with the exit timestamp (breaking walk-forward bucketing).
    def _num(row: pd.Series, col: str) -> float:
        val = pd.to_numeric(row.get(col), errors="coerce")
        return 0.0 if pd.isna(val) else float(val)

    df = df.sort_values("timestamp").reset_index(drop=True)
    open_entries: Dict[str, pd.Series] = {}
    trades: List[TradeRecord] = []
    for _, row in df.iterrows():
        code = str(row.get("code", ""))
        realised = _num(row, "pnl") or _num(row, "return_pct") or max(
            _num(row, "holding_bars"), _num(row, "holding_days")
        )
        if not realised and code not in open_entries:
            open_entries[code] = row
            continue
        entry = open_entries.pop(code, None)
        hold = _num(row, "holding_bars") or _num(row, "holding_days")
        trades.append(
            TradeRecord(
                symbol=code,
                direction=1 if row.get("side") == "sell" else -1,
                entry_price=_num(entry, "price") if entry is not None else 0.0,
                exit_price=_num(row, "price"),
                entry_time=pd.Timestamp(
                    (entry if entry is not None else row).get("timestamp", "2000-01-01")
                ),
                exit_time=pd.Timestamp(row.get("timestamp", "2000-01-01")),
                size=_num(row, "qty"),
                leverage=1.0,
                pnl=_num(row, "pnl"),
                pnl_pct=_num(row, "return_pct"),
                exit_reason=str(row.get("reason", "signal")),
                holding_bars=hold,
                commission=0.0,
            )
        )
    return trades


def _parse_run_dir(argv: List[str]) -> Path:
    """Validate CLI input and return a usable run directory path."""
    if len(argv) < 2:
        raise SystemExit("Usage: python -m backtest.validation <run_dir>")

    raw_run_dir = argv[1]
    if not raw_run_dir.strip():
        raise SystemExit("run_dir must be a non-empty path")
    if "\0" in raw_run_dir:
        raise SystemExit("Invalid run_dir path: embedded NUL byte")

    try:
        run_dir = Path(raw_run_dir).expanduser()
        exists = run_dir.exists()
        is_dir = run_dir.is_dir() if exists else False
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Invalid run_dir path: {exc}") from exc

    if not exists:
        raise SystemExit(f"run_dir does not exist: {run_dir}")
    if not is_dir:
        raise SystemExit(f"run_dir is not a directory: {run_dir}")
    return run_dir


def _json_safe(value: Any) -> Any:
    """Return a JSON-strict copy of validation results."""
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def write_validation_json(path: Path, results: Dict[str, Any]) -> Dict[str, Any]:
    """Write validation results to ``path`` as strict, RFC-8259 JSON.

    A validation metric can be non-finite (e.g. a Sharpe computed from a path
    whose equity touches zero), and ``json.dumps`` emits bare ``NaN`` /
    ``Infinity`` tokens for those by default (``allow_nan=True``) — tokens that
    strict parsers reject. Sanitize with :func:`_json_safe` (non-finite → null)
    and serialize with ``allow_nan=False`` so every writer of
    ``artifacts/validation.json`` produces the same valid JSON. Returns the
    sanitized payload that was written.
    """
    safe_results = _json_safe(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(safe_results, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return safe_results


def main(run_dir: Path) -> Dict[str, Any]:
    """Run all three validations on existing backtest artifacts.

    Reads equity.csv, trades.csv, and config.json from run_dir.

    Args:
        run_dir: Directory with artifacts/ subdirectory.

    Returns:
        Validation results dict.
    """
    # Load config for initial_cash
    config_path = run_dir / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}
    initial_capital = config.get("initial_cash", 1_000_000)

    equity = _load_equity(run_dir)
    trades = _load_trades(run_dir)

    results = {
        "monte_carlo": monte_carlo_test(trades, initial_capital),
        "bootstrap": bootstrap_sharpe_ci(equity),
        "walk_forward": walk_forward_analysis(equity, trades),
    }

    out = run_dir / "artifacts" / "validation.json"
    safe_results = write_validation_json(out, results)

    print(json.dumps(safe_results, indent=2, allow_nan=False))
    return safe_results


if __name__ == "__main__":
    import sys

    main(_parse_run_dir(sys.argv))
