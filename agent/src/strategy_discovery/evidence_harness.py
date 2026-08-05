"""Evidence harness: compute per-regime evidence from real backtest artifacts.

Builds on the artifact readers in :mod:`run_artifacts`; this module owns the
regime labeling and the per-regime metrics. Conventions:

* Trade counting — engine ``trades.csv`` artifacts hold TWO rows per round
  trip (entry row ``pnl=0.0`` + exit row with realized pnl); only exit rows
  are counted, so a round trip contributes exactly one trade. Legacy
  one-row-per-trade artifacts are detected via the marker column and keep
  counting every row (see :func:`run_artifacts.read_trade_activity`).
* Regime labeling — each bar is labeled by the rolling cumulative benchmark
  return over the trailing ``benchmark_window`` bars ending at that bar
  (``<= bear_threshold`` → bear_market, ``>= bull_threshold`` → bull_market,
  else structural). Bars without enough history or a usable benchmark value
  are labeled ``structural`` and documented as warm-up, never guessed.
* Per-regime metrics use only regime bars: compounded strategy/benchmark
  returns are products of per-bar returns across the union of the regime's
  bars; Sharpe is mean/std of per-bar strategy returns inside regime bars,
  annualized with ``sqrt(252)`` (bars assumed daily); max drawdown tracks
  the strategy equity peak across regime bars.
* Multi-position caveat — ``breakeven_fee_bps`` divides aggregate run
  returns by aggregate trade counts; for runs that held several positions
  at once that is an approximation (issue #969). Runs with detected
  concurrency > 1 — or whose artifacts make concurrency undetectable —
  carry a stable ``multi-position-breakeven:`` warning on every row.

Missing inputs return ``[]`` with a warning: honest empty beats fabricated
rows every time.
"""

from __future__ import annotations

import bisect
import logging
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from src.strategy_discovery.evidence_store import EvidenceStore
from src.strategy_discovery.models import (
    COST_SENSITIVE_BREAKEVEN_BPS,
    REGIMES,
    EvidenceRow,
    breakeven_fee_bps,
    build_warnings,
    classify_quality,
    coverage_days_from_ranges,
)
from src.strategy_discovery.run_artifacts import (
    parse_finite_float,
    read_equity_series,
    read_trade_activity,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regime thresholds — named, documented, configurable (not magic numbers).
# ---------------------------------------------------------------------------

#: Rolling window in bars used to classify each bar's market regime.
#: Default 252 ≈ one trading year of daily bars.
DEFAULT_BENCHMARK_WINDOW = 252

#: Rolling benchmark return at or below this value labels a bar bear_market.
DEFAULT_BEAR_THRESHOLD = -0.10

#: Rolling benchmark return at or above this value labels a bar bull_market.
DEFAULT_BULL_THRESHOLD = 0.15

#: Annualization factor for Sharpe: bars are assumed daily, so the per-bar
#: Sharpe is scaled by sqrt(252). Documented convention, not a hidden magic.
SHARPE_ANNUALIZATION_BARS = 252

#: Stable warning prefix for the multi-position breakeven caveat, kept in
#: the same prefix-token style as ``models.build_warnings`` so downstream
#: tools can match it without parsing prose.
MULTI_POSITION_WARNING_PREFIX = "multi-position-breakeven:"

#: Known approximation error of the aggregate breakeven estimate for
#: multi-position runs (issue #969 discussion): 1.1x-6.5x. The direction is
#: conservative — it can over-flag ``cost_sensitive``, never under-flag an
#: unaffordable strategy.
_MULTI_POSITION_CAVEAT_BODY = (
    "breakeven_fee_bps is computed from aggregate run figures and is an "
    "approximation for multi-position/multi-name runs (known error "
    "1.1-6.5x, conservative — may over-flag cost_sensitive, never "
    "under-flag unaffordable costs)"
)


def _breakeven_caveat(max_concurrent: int | None) -> str | None:
    """Run-level caveat for the aggregate breakeven estimate, or ``None``.

    ``max_concurrent`` comes from the entry/exit pairs in ``trades.csv``:
    above 1 the breakeven arithmetic (aggregate return divided by
    aggregate trade count) is only an approximation, so every evidence row
    of that run carries the caveat. ``None`` (missing entry/exit marker →
    concurrency undetectable) gets the generic wording instead of silence.
    Single-position runs need no caveat.
    """
    if max_concurrent is None:
        return (
            f"{MULTI_POSITION_WARNING_PREFIX} trades.csv lacks the engine "
            f"entry/exit marker (zero-pnl rows), so position concurrency "
            f"is unknown; {_MULTI_POSITION_CAVEAT_BODY}"
        )
    if max_concurrent > 1:
        return (
            f"{MULTI_POSITION_WARNING_PREFIX} run held up to "
            f"{max_concurrent} concurrent positions; "
            f"{_MULTI_POSITION_CAVEAT_BODY}"
        )
    return None


# ---------------------------------------------------------------------------
# Regime labeling
# ---------------------------------------------------------------------------


def _label_regimes(
    benchmarks: Sequence[float | None],
    benchmark_window: int,
    bear_threshold: float,
    bull_threshold: float,
) -> list[str]:
    """Regime label per bar from the trailing rolling benchmark return.

    Bars without ``benchmark_window`` bars of history, or without finite
    positive benchmark anchors at both ends of the window, are labeled
    ``structural`` and documented as warm-up / unlabeled — never guessed.
    """
    return [
        _regime_for_bar(
            index, benchmarks, benchmark_window, bear_threshold, bull_threshold
        )
        for index in range(len(benchmarks))
    ]


def _regime_for_bar(
    index: int,
    benchmarks: Sequence[float | None],
    benchmark_window: int,
    bear_threshold: float,
    bull_threshold: float,
) -> str:
    if index < benchmark_window:
        return REGIMES[2]  # warm-up: not enough history for a rolling label
    current = benchmarks[index]
    anchor = benchmarks[index - benchmark_window]
    if (
        current is None
        or anchor is None
        or not math.isfinite(current)
        or not math.isfinite(anchor)
        or anchor <= 0
    ):
        return REGIMES[2]
    rolling_return = current / anchor - 1.0
    if rolling_return <= bear_threshold:
        return REGIMES[0]  # bear_market
    if rolling_return >= bull_threshold:
        return REGIMES[1]  # bull_market
    return REGIMES[2]


# ---------------------------------------------------------------------------
# Per-regime metric helpers
# ---------------------------------------------------------------------------


def _month_spans(bar_indices: Sequence[int], dates: Sequence[date]) -> tuple[str, ...]:
    """Contiguous runs of regime bars as ``YYYY-MM to YYYY-MM`` strings."""
    if not bar_indices:
        return ()
    spans: list[str] = []
    run_start = previous = bar_indices[0]
    for index in bar_indices[1:]:
        if index == previous + 1:
            previous = index
            continue
        spans.append(f"{dates[run_start]:%Y-%m} to {dates[previous]:%Y-%m}")
        run_start = previous = index
    spans.append(f"{dates[run_start]:%Y-%m} to {dates[previous]:%Y-%m}")
    return tuple(spans)


def _bar_returns(bar_indices: Sequence[int], series: Sequence[float]) -> list[float]:
    """Per-bar simple returns for the given bars (previous bar may be any regime)."""
    returns: list[float] = []
    for index in bar_indices:
        if index <= 0:
            continue
        previous = series[index - 1]
        current = series[index]
        if previous <= 0 or not math.isfinite(current):
            continue
        returns.append(current / previous - 1.0)
    return returns


def _compounded(returns: Sequence[float]) -> float:
    """Compounded return from per-bar simple returns (empty product → 0.0)."""
    growth = 1.0
    for ret in returns:
        growth *= 1.0 + ret
    return growth - 1.0


def _max_drawdown(
    bar_indices: Sequence[int], equities: Sequence[float]
) -> float | None:
    """Peak-to-trough drawdown of strategy equity across the regime bars."""
    peak: float | None = None
    max_dd: float | None = None
    for index in bar_indices:
        equity = equities[index]
        if not math.isfinite(equity) or equity <= 0:
            continue
        if peak is None or equity > peak:
            peak = equity
        if peak is None or peak <= 0:
            continue
        drawdown = equity / peak - 1.0
        if max_dd is None or drawdown < max_dd:
            max_dd = drawdown
    if max_dd is None:
        return None
    return min(0.0, max_dd)


def _resolve_position_size(
    explicit: float | None, exposures: Sequence[float]
) -> float | None:
    """Explicit sizing wins; otherwise the mean recorded exposure; else unknown."""
    if explicit is not None:
        size = parse_finite_float(explicit)
        if size is None or size <= 0:
            logger.warning(
                "invalid explicit position_size %r; treating as unknown", explicit
            )
            return None
        return size
    if exposures:
        mean_exposure = statistics.fmean(exposures)
        if math.isfinite(mean_exposure) and mean_exposure > 0:
            return mean_exposure
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_evidence_for_run(
    strategy_id: str,
    run_dir: str | Path,
    *,
    benchmark_window: int = DEFAULT_BENCHMARK_WINDOW,
    bear_threshold: float = DEFAULT_BEAR_THRESHOLD,
    bull_threshold: float = DEFAULT_BULL_THRESHOLD,
    position_size: float | None = None,
    today: str | None = None,
) -> list[EvidenceRow]:
    """Compute per-regime evidence rows from one run's artifact directory.

    Returns ``[]`` (with a warning) whenever the required artifacts are
    absent or unusable — the harness never fabricates missing data.
    """
    if benchmark_window <= 0:
        raise ValueError("benchmark_window must be a positive integer")
    if bear_threshold >= bull_threshold:
        raise ValueError("bear_threshold must be strictly below bull_threshold")

    run_path = Path(run_dir)
    trades_path = run_path / "artifacts" / "trades.csv"
    equity_path = run_path / "artifacts" / "equity.csv"
    if not trades_path.is_file() or not equity_path.is_file():
        logger.warning(
            "strategy %s: missing trades.csv and/or equity.csv under %s — "
            "no evidence computed (honest empty, nothing fabricated)",
            strategy_id,
            run_path / "artifacts",
        )
        return []

    activity = read_trade_activity(trades_path)
    if activity is None or not activity[0]:
        logger.warning(
            "strategy %s: trades.csv unusable or empty — no evidence computed",
            strategy_id,
        )
        return []
    trade_dates, max_concurrent = activity
    series = read_equity_series(equity_path)
    if series is None:
        logger.warning(
            "strategy %s: equity.csv unusable or empty — no evidence computed",
            strategy_id,
        )
        return []
    dates, equities, benchmarks, exposures = series

    regime_per_bar = _label_regimes(
        benchmarks, benchmark_window, bear_threshold, bull_threshold
    )

    # Bucket trades into the regime of the most recent bar on/before their date.
    trades_per_regime: dict[str, int] = {}
    unlabeled_trades = 0
    for trade_date in trade_dates:
        bar_index = bisect.bisect_right(dates, trade_date) - 1
        if bar_index < 0:
            unlabeled_trades += 1  # trade predates the equity window
            continue
        regime = regime_per_bar[bar_index]
        trades_per_regime[regime] = trades_per_regime.get(regime, 0) + 1
    if unlabeled_trades:
        logger.info(
            "strategy %s: %d trade(s) predate the equity window and were excluded",
            strategy_id,
            unlabeled_trades,
        )

    resolved_size = _resolve_position_size(position_size, exposures)
    breakeven_caveat = _breakeven_caveat(max_concurrent)
    last_verified = (
        today if isinstance(today, str) and today else date.today().isoformat()
    )

    rows: list[EvidenceRow] = []
    for regime in REGIMES:
        trades_in_regime = trades_per_regime.get(regime, 0)
        if trades_in_regime < 1:
            continue
        bar_indices = [i for i, label in enumerate(regime_per_bar) if label == regime]

        strategy_returns = _bar_returns(bar_indices, equities)
        compounded_return = _compounded(strategy_returns)

        benchmark_compounded: float | None = None
        if all(value is not None for value in benchmarks):
            benchmark_returns = _bar_returns(bar_indices, benchmarks)  # type: ignore[arg-type]
            benchmark_compounded = _compounded(benchmark_returns)
        excess = (
            compounded_return - benchmark_compounded
            if benchmark_compounded is not None
            else None
        )

        sharpe: float | None = None
        if len(strategy_returns) >= 2:
            stdev = statistics.stdev(strategy_returns)
            if math.isfinite(stdev) and stdev > 0:
                sharpe = (
                    statistics.fmean(strategy_returns)
                    / stdev
                    * math.sqrt(SHARPE_ANNUALIZATION_BARS)
                )

        max_dd = _max_drawdown(bar_indices, equities)
        date_ranges = _month_spans(bar_indices, dates)

        breakeven = breakeven_fee_bps(
            compounded_return, trades_in_regime, resolved_size
        )
        cost_sensitive = (
            breakeven is not None and breakeven < COST_SENSITIVE_BREAKEVEN_BPS
        )
        coverage_days = coverage_days_from_ranges(date_ranges)
        quality = classify_quality(trades_in_regime, coverage_days)
        warnings = build_warnings(
            trades_in_regime, coverage_days, breakeven, quality, cost_sensitive
        )
        if breakeven_caveat is not None:
            warnings = (*warnings, breakeven_caveat)

        rows.append(
            EvidenceRow(
                strategy_id=strategy_id,
                regime=regime,
                trades_in_regime=trades_in_regime,
                position_size=resolved_size,
                return_in_regime=compounded_return,
                benchmark_in_regime=benchmark_compounded,
                excess_in_regime=excess,
                sharpe_in_regime=sharpe,
                max_drawdown_in_regime=max_dd,
                date_ranges=date_ranges,
                breakeven_fee_bps=breakeven,
                cost_sensitive=cost_sensitive,
                evidence_quality=quality,
                warnings=warnings,
                last_verified=last_verified,
            )
        )
    return rows


def rebuild_evidence(runs: Sequence[Mapping], store: EvidenceStore) -> dict:
    """Clear the store and rebuild it from a sequence of run specifications.

    Each mapping needs ``strategy_id`` and ``run_dir``; an optional
    ``position_size`` overrides exposure-derived sizing. Runs that yield no
    computable evidence are reported in ``skipped`` with a reason — nothing
    is invented for them.
    """
    skipped: list[dict] = []
    all_rows: list[EvidenceRow] = []
    ok_strategies: set[str] = set()

    store.clear()

    for index, spec in enumerate(runs):
        if not isinstance(spec, Mapping):
            skipped.append(
                {
                    "run_dir": None,
                    "reason": f"run spec at index {index} is not a mapping",
                }
            )
            continue
        strategy_id = spec.get("strategy_id")
        run_dir = spec.get("run_dir")
        if (
            not isinstance(strategy_id, str)
            or not strategy_id.strip()
            or run_dir is None
            or not str(run_dir).strip()
        ):
            skipped.append(
                {
                    "run_dir": None if run_dir is None else str(run_dir),
                    "reason": "missing strategy_id or run_dir",
                }
            )
            continue
        try:
            rows = compute_evidence_for_run(
                strategy_id, run_dir, position_size=spec.get("position_size")
            )
        except Exception as exc:  # noqa: BLE001 — one bad run must not sink the rebuild
            logger.exception(
                "evidence computation failed for %s (%s)", strategy_id, run_dir
            )
            skipped.append(
                {"run_dir": str(run_dir), "reason": f"computation failed: {exc}"}
            )
            continue
        if not rows:
            skipped.append(
                {
                    "run_dir": str(run_dir),
                    "reason": (
                        "no computable evidence (missing/empty trades.csv or equity.csv, "
                        "or no trades labelable on the equity window)"
                    ),
                }
            )
            continue
        all_rows.extend(rows)
        ok_strategies.add(strategy_id)

    written = store.upsert_rows(all_rows)
    return {
        "status": "ok",
        "runs": len(runs),
        "strategies": len(ok_strategies),
        "rows": written,
        "skipped": skipped,
    }
