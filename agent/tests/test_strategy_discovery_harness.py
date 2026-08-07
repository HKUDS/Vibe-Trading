"""Frozen-contract tests for ``src.strategy_discovery.evidence_harness`` — #969.

AC3 (evidence from reproducible runs only) is exercised here end to end on
synthetic run directories built in tmp_path with the REAL engine artifact
schema (``backtest/engines/base.py::_write_artifacts``):

* ``artifacts/trades.csv`` — columns ``timestamp, code, side, price, qty,
  reason, pnl, holding_days, return_pct`` with TWO rows per round trip:
  an entry row (``reason="signal"``, ``pnl=0.0``, ``holding_days=0``)
  followed by the exit row carrying the realized pnl. Round trips must be
  counted ONCE (exit rows only); exit rows may reuse ``reason="signal"``
  (the base engine closes positions on signal), so the marker is pnl, not
  reason.
* ``artifacts/equity.csv`` — date column ``timestamp`` (the engine's index
  name) plus ``ret, equity, drawdown, benchmark_equity, active_ret``.
  Benchmark values live in ``benchmark_equity``.

The benchmark series is a piecewise-constant-slope curve engineered so
that, with ``benchmark_window=5`` and thresholds of ±0.05, days
2024-01-14..16 are a bear window, 2024-01-21..24 a bull window, and
2024-01-07..08 structural — regardless of whether the harness measures
the window return as an endpoint ratio or a mean of daily changes (both
agree inside the segments; the self-check class pins this).

Legacy one-row-per-trade artifacts (``date``/``benchmark`` columns, no
zero-pnl entry marker) stay covered through the alias + detection paths.
Deterministic: all dates are fixed strings, no wall-clock reads.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

try:
    from src.strategy_discovery import evidence_harness as sd_harness
    from src.strategy_discovery import models as sd_models
    from src.strategy_discovery import run_artifacts as sd_artifacts

    HARNESS_AVAILABLE = True
except ImportError:
    sd_harness = None
    sd_models = None
    sd_artifacts = None
    HARNESS_AVAILABLE = False

requires_harness = pytest.mark.skipif(
    not HARNESS_AVAILABLE,
    reason="waiting on sibling A: src.strategy_discovery.evidence_harness not landed yet (issue #969)",
)

START = date(2024, 1, 1)
DAYS = 39
BEAR_DAYS = {date(2024, 1, 14), date(2024, 1, 15), date(2024, 1, 16)}
BULL_DAYS = {date(2024, 1, 21), date(2024, 1, 22), date(2024, 1, 23), date(2024, 1, 24)}
STRUCTURAL_DAYS = {date(2024, 1, 7), date(2024, 1, 8)}
EXPECTED_COUNTS = {"bear_market": 3, "bull_market": 4, "structural": 2}
ALL_TRADE_DAYS = sorted(BEAR_DAYS | BULL_DAYS | STRUCTURAL_DAYS)

#: Exact column order written by base.py::_write_artifacts.
ENGINE_TRADE_COLUMNS = [
    "timestamp",
    "code",
    "side",
    "price",
    "qty",
    "reason",
    "pnl",
    "holding_days",
    "return_pct",
]
ENGINE_EQUITY_COLUMNS = ["ret", "equity", "drawdown", "benchmark_equity", "active_ret"]


def _benchmark_series() -> pd.Series:
    """Piecewise benchmark: flat, -5.5%/day decline, +6%/day rally, flat.

    Segments (1-based days → 0-based index i): Jan 1-8 flat 100.0; Jan 9-16
    (i 8..15) daily x0.945; Jan 17-24 (i 16..23) daily x1.06 from the bear
    end; Jan 25 - Feb 8 flat at the bull end.
    """
    bear_end = 100.0 * (0.945**8)
    bull_end = bear_end * (1.06**8)
    values = (
        [100.0] * 8
        + [100.0 * (0.945 ** (i - 7)) for i in range(8, 16)]
        + [bear_end * (1.06 ** (i - 15)) for i in range(16, 24)]
        + [bull_end] * 15
    )
    assert len(values) == DAYS
    index = [START + timedelta(days=i) for i in range(DAYS)]
    return pd.Series(values, index=pd.DatetimeIndex(index), name="benchmark_equity")


def _engine_equity_frame() -> pd.DataFrame:
    """equity.csv exactly as backtest/engines/base.py::_write_artifacts."""
    bench = _benchmark_series()
    equity = pd.Series(
        [1_000_000.0 * (1.001**i) for i in range(DAYS)], index=bench.index
    )
    port_ret = equity.pct_change().fillna(0.0)
    peak = equity.cummax()
    drawdown = (equity - peak) / peak.replace(0, 1)
    bench_ret = bench.pct_change().fillna(0.0)
    eq_df = pd.DataFrame(
        {
            "ret": port_ret,
            "equity": equity,
            "drawdown": drawdown,
            "benchmark_equity": bench,
            "active_ret": port_ret - bench_ret,
        },
        index=bench.index,
    )
    eq_df.index.name = "timestamp"
    return eq_df


def _entry_row(trade_date: date, code: str) -> dict:
    return {
        "timestamp": trade_date.strftime("%Y-%m-%d"),
        "code": code,
        "side": "buy",
        "price": 10.0,
        "qty": 100.0,
        "reason": "signal",
        "pnl": 0.0,
        "holding_days": 0,
        "return_pct": 0.0,
    }


def _exit_row(
    trade_date: date, code: str, *, pnl: float = 50.0, reason: str = "signal"
) -> dict:
    return {
        "timestamp": trade_date.strftime("%Y-%m-%d"),
        "code": code,
        "side": "sell",
        "price": 10.5,
        "qty": 100.0,
        "reason": reason,
        "pnl": pnl,
        "holding_days": 0,
        "return_pct": 0.5,
    }


def _engine_trade_rows(
    round_trips: Sequence[tuple[date, str, float, str]],
) -> list[dict]:
    """Entry+exit row pairs, exactly as the engine writer emits them."""
    rows: list[dict] = []
    for exit_date, code, pnl, exit_reason in round_trips:
        # Same-day round trips keep per-code holding intervals disjoint, so
        # the fixture is single-position by construction.
        rows.append(_entry_row(exit_date, code))
        rows.append(_exit_row(exit_date, code, pnl=pnl, reason=exit_reason))
    return rows


def _write_trades_csv(artifacts: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows, columns=ENGINE_TRADE_COLUMNS).to_csv(
        artifacts / "trades.csv", index=False
    )


#: Engine metrics.csv header (base.py::_write_artifacts flattens the metrics
#: dict into one header row + one value row). trade_count is the column the
#: Phase 2 hard gate reads for run ELIGIBILITY.
ENGINE_METRICS_COLUMNS = [
    "final_value",
    "total_return",
    "annual_return",
    "max_drawdown",
    "sharpe",
    "calmar",
    "sortino",
    "win_rate",
    "profit_loss_ratio",
    "profit_factor",
    "max_consecutive_loss",
    "avg_holding_days",
    "trade_count",
    "benchmark_return",
    "excess_return",
    "information_ratio",
]


def _write_run_state(run_dir: Path, *, trade_count: int, status: str = "success"):
    """Real-runtime state.json + engine metrics.csv for a fixture run.

    The Phase 2 hard gates read ``state.json`` (runtime-written, ``{"status":
    "success"}``) and ``artifacts/metrics.csv`` (engine-written header+value
    rows), so every fixture that must pass ingestion carries both.
    """
    (run_dir / "state.json").write_text(
        json.dumps({"status": status}), encoding="utf-8"
    )
    values = [1_000_000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0]
    values += [trade_count, 0.0, 0.0, 0.0]
    pd.DataFrame([values], columns=ENGINE_METRICS_COLUMNS).to_csv(
        run_dir / "artifacts" / "metrics.csv", index=False
    )


def _write_run_fixture(
    base_dir: Path, *, include_trades: bool = True, include_equity: bool = True
) -> Path:
    """Real engine-schema run_dir: 9 same-day round trips, one position."""
    run_dir = base_dir / "run_fixture"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    if include_equity:
        _engine_equity_frame().to_csv(artifacts / "equity.csv")

    if include_trades:
        round_trips = [
            (
                trade_date,
                "TEST.SH",
                50.0,
                # Exits reuse reason="signal" (base engine closes on signal
                # too) — the entry/exit marker must be pnl, not reason.
                "signal" if i < 8 else "end",
            )
            for i, trade_date in enumerate(ALL_TRADE_DAYS)
        ]
        _write_trades_csv(artifacts, _engine_trade_rows(round_trips))

    _write_run_state(run_dir, trade_count=len(ALL_TRADE_DAYS))
    return run_dir


def _write_multi_position_fixture(base_dir: Path) -> Path:
    """Two overlapping holdings: AAA Jan 14-16 and BBB Jan 15-21 → peak 2."""
    run_dir = base_dir / "multi_position_run"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    _engine_equity_frame().to_csv(artifacts / "equity.csv")

    rows = [
        _entry_row(date(2024, 1, 14), "AAA.US"),
        _entry_row(date(2024, 1, 15), "BBB.US"),
        _exit_row(date(2024, 1, 16), "AAA.US", pnl=30.0, reason="stop_loss"),
        _exit_row(date(2024, 1, 21), "BBB.US", pnl=40.0, reason="take_profit"),
    ]
    _write_trades_csv(artifacts, rows)
    _write_run_state(run_dir, trade_count=2)
    return run_dir


def _write_legacy_fixture(base_dir: Path) -> Path:
    """Legacy one-row-per-trade artifacts: date/benchmark aliases, no marker."""
    run_dir = base_dir / "legacy_run"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    bench = _benchmark_series()
    legacy_equity = pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in bench.index],
            "equity": [1_000_000.0 * (1.001**i) for i in range(DAYS)],
            "benchmark": bench.values,
        }
    )
    legacy_equity.to_csv(artifacts / "equity.csv", index=False)

    legacy_rows = [
        {
            "date": trade_date.strftime("%Y-%m-%d"),
            "code": "TEST.SH",
            "side": "sell",
            "pnl": 50.0,
            "return_pct": 0.5,
        }
        for trade_date in ALL_TRADE_DAYS
    ]
    pd.DataFrame(legacy_rows).to_csv(artifacts / "trades.csv", index=False)
    _write_run_state(run_dir, trade_count=len(ALL_TRADE_DAYS))
    return run_dir


def _call_compute(strategy_id, run_dir, **candidates):
    """Call compute_evidence_for_run binding args by name, filtering kwargs
    not in the signature so the fixture stays tolerant of additive changes."""
    func = sd_harness.compute_evidence_for_run
    sig = inspect.signature(func)
    has_varkw = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if has_varkw:
        kwargs = dict(candidates)
    else:
        kwargs = {k: v for k, v in candidates.items() if k in sig.parameters}
    return func(strategy_id=strategy_id, run_dir=run_dir, **kwargs)


def _compute_with_fixture_windows(run_dir):
    """Shared call shape: fixture-engineered windows + pinned today."""
    return _call_compute(
        "sdm:fixture_run",
        run_dir,
        benchmark_window=5,
        bear_threshold=-0.05,
        bull_threshold=0.05,
        today="2026-08-01",
    )


# ---------------------------------------------------------------------------
# Fixture self-check — pure pandas, runs TODAY without the sibling package
# ---------------------------------------------------------------------------


class TestFixtureSelfCheck:
    def test_benchmark_windows_are_unambiguous_for_both_regime_models(
        self, tmp_path
    ) -> None:
        bench = _benchmark_series()
        ratio_model = bench / bench.shift(5) - 1.0
        mean_model = bench.pct_change().rolling(5).mean()

        for trade_date, expected in (
            *[(d, "bear_market") for d in sorted(BEAR_DAYS)],
            *[(d, "bull_market") for d in sorted(BULL_DAYS)],
            *[(d, "structural") for d in sorted(STRUCTURAL_DAYS)],
        ):
            r_ratio = ratio_model.loc[pd.Timestamp(trade_date)]
            r_mean = mean_model.loc[pd.Timestamp(trade_date)]
            for value in (r_ratio, r_mean):
                assert math.isfinite(value), f"{trade_date}: window value not finite"
                if expected == "bear_market":
                    assert (
                        value < -0.05
                    ), f"{trade_date} should be a bear window (got {value:.4f})"
                elif expected == "bull_market":
                    assert (
                        value > 0.05
                    ), f"{trade_date} should be a bull window (got {value:.4f})"
                else:
                    assert (
                        -0.05 <= value <= 0.05
                    ), f"{trade_date} should be structural (got {value:.4f})"

    def test_trade_fixture_shape_matches_engine_schema(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        trades = pd.read_csv(run_dir / "artifacts" / "trades.csv")
        equity = pd.read_csv(run_dir / "artifacts" / "equity.csv")

        assert list(trades.columns) == ENGINE_TRADE_COLUMNS
        # 9 round trips → 18 rows: entry rows (pnl == 0) + exit rows (pnl > 0).
        assert len(trades) == 18
        assert int((trades["pnl"] == 0.0).sum()) == 9
        assert int((trades["pnl"] > 0).sum()) == 9
        assert (trades["reason"] != "").all()

        assert list(equity.columns) == ["timestamp", *ENGINE_EQUITY_COLUMNS]
        assert len(equity) == DAYS
        assert "benchmark" not in equity.columns, "no dual benchmark columns"
        assert "date" not in equity.columns, "no dual date columns"


# ---------------------------------------------------------------------------
# compute_evidence_for_run on the REAL engine schema
# ---------------------------------------------------------------------------


@requires_harness
class TestComputeEvidence:
    def test_real_schema_yields_rows_with_expected_attribution(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _compute_with_fixture_windows(run_dir)
        assert isinstance(rows, list)
        assert rows, "real engine-schema artifacts must produce evidence rows"
        counts = {row.regime: row.trades_in_regime for row in rows}
        regimes = {row.regime for row in rows}
        assert regimes == set(EXPECTED_COUNTS), f"unexpected regime set: {regimes}"
        for regime, expected in EXPECTED_COUNTS.items():
            assert (
                counts[regime] == expected
            ), f"regime {regime}: expected {expected} trades, harness counted {counts[regime]}"
        for row in rows:
            assert (
                row.last_verified == "2026-08-01"
            ), f"{row.regime}: explicit today= must pin last_verified, got {row.last_verified!r}"

    def test_entry_rows_are_excluded_from_trade_counts(self, tmp_path) -> None:
        trades_path = _write_run_fixture(tmp_path) / "artifacts" / "trades.csv"
        activity = sd_artifacts.read_trade_activity(trades_path)
        assert activity is not None
        exit_dates, max_concurrent = activity
        # 18 physical rows but exactly 9 round trips — one count per exit row.
        assert exit_dates == sorted(ALL_TRADE_DAYS)
        assert len(exit_dates) == 9
        assert max_concurrent == 1

        rows = _compute_with_fixture_windows(_write_run_fixture(tmp_path / "again"))
        assert sum(row.trades_in_regime for row in rows) == 9

    def test_benchmark_is_read_from_benchmark_equity(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        equity_frame = pd.read_csv(run_dir / "artifacts" / "equity.csv")
        assert "benchmark_equity" in equity_frame.columns
        assert "benchmark" not in equity_frame.columns

        rows = _compute_with_fixture_windows(run_dir)
        assert rows
        for row in rows:
            assert row.benchmark_in_regime is not None, (
                f"{row.regime}: benchmark must be read from the benchmark_equity "
                f"column"
            )
            assert row.excess_in_regime is not None

    def test_date_ranges_format(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _compute_with_fixture_windows(run_dir)
        pattern = re.compile(r"^\d{4}-\d{2} to \d{4}-\d{2}$")
        for row in rows:
            assert isinstance(row.date_ranges, tuple)
            assert row.date_ranges, f"{row.regime}: date_ranges must not be empty"
            for entry in row.date_ranges:
                assert pattern.match(entry), f"bad date_range format: {entry!r}"

    def test_quality_classification_applied(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _compute_with_fixture_windows(run_dir)
        for row in rows:
            coverage = sd_models.coverage_days_from_ranges(list(row.date_ranges))
            expected_quality = sd_models.classify_quality(
                row.trades_in_regime, coverage
            )
            assert row.evidence_quality == expected_quality, (
                f"{row.regime}: quality {row.evidence_quality!r} != "
                f"classify_quality({row.trades_in_regime}, {coverage}) = {expected_quality!r}"
            )
            # Every fixture regime has < MIN_TRADES trades → insufficient plus
            # the stable insufficient-trades: warning prefix.
            assert row.evidence_quality == "insufficient"
            assert any(w.startswith("insufficient-trades:") for w in row.warnings)

    def test_breakeven_uses_position_size(self, tmp_path) -> None:
        full_rows = _call_compute(
            "sdm:fixture_run",
            _write_run_fixture(tmp_path / "full"),
            benchmark_window=5,
            bear_threshold=-0.05,
            bull_threshold=0.05,
            position_size=1.0,
            today="2026-08-01",
        )
        half_rows = _call_compute(
            "sdm:fixture_run",
            _write_run_fixture(tmp_path / "half"),
            benchmark_window=5,
            bear_threshold=-0.05,
            bull_threshold=0.05,
            position_size=0.5,
            today="2026-08-01",
        )
        full_by_regime = {r.regime: r.breakeven_fee_bps for r in full_rows}
        half_by_regime = {r.regime: r.breakeven_fee_bps for r in half_rows}
        for regime, full in full_by_regime.items():
            half = half_by_regime[regime]
            assert full is not None and half is not None, f"{regime}: breakeven missing"
            assert full > 0, f"{regime}: expected positive gross edge in fixture"
            assert half == pytest.approx(2.0 * full, rel=1e-9), (
                f"{regime}: position_size=0.5 must double breakeven "
                f"(full={full}, half={half})"
            )

    def test_single_position_run_carries_no_concurrency_caveat(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _compute_with_fixture_windows(run_dir)
        assert rows
        for row in rows:
            assert not any(
                w.startswith(sd_harness.MULTI_POSITION_WARNING_PREFIX)
                for w in row.warnings
            ), f"{row.regime}: single-position runs need no concurrency caveat"
            assert (
                row.breakeven_fee_bps is not None
            ), f"{row.regime}: single-position runs keep the exact breakeven"

    def test_rows_carry_stage_provenance_and_regime_definition(self, tmp_path) -> None:
        # initial-d (#969): every row names its evidence stage, the run it
        # came from, and the regime-labeling parameters used.
        run_dir = _write_run_fixture(tmp_path)
        rows = _compute_with_fixture_windows(run_dir)
        assert rows
        definition = json.loads(rows[0].regime_definition)
        for row in rows:
            assert row.evidence_stage == "backtest"
            assert row.provenance == str(run_dir)
            assert json.loads(row.regime_definition) == definition
        assert definition["benchmark_window"] == 5
        assert definition["bear_threshold"] == -0.05
        assert definition["bull_threshold"] == 0.05
        assert definition["sharpe_annualization_bars"] == 252

    def test_unparseable_trade_dates_are_rejected_not_fatal(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        trades_path = run_dir / "artifacts" / "trades.csv"
        trades = pd.read_csv(trades_path)
        junk_row = {column: "" for column in trades.columns}
        junk_row.update(
            {"timestamp": "not-a-date", "code": "TEST.SH", "side": "sell", "pnl": 50.0}
        )
        pd.concat([trades, pd.DataFrame([junk_row])], ignore_index=True).to_csv(
            trades_path, index=False
        )

        rows = _compute_with_fixture_windows(run_dir)
        counts = {row.regime: row.trades_in_regime for row in rows}
        assert (
            counts == EXPECTED_COUNTS
        ), "unparseable-date rows must be skipped without changing counts"

    def test_missing_csvs_or_artifacts_returns_empty_list_no_crash(
        self, tmp_path
    ) -> None:
        empty_run = tmp_path / "empty_run"
        empty_run.mkdir()
        assert (
            _call_compute(
                "sdm:empty",
                empty_run,
                benchmark_window=5,
                bear_threshold=-0.05,
                bull_threshold=0.05,
                today="2026-08-01",
            )
            == []
        )

        no_artifacts = tmp_path / "no_artifacts"
        no_artifacts.mkdir()
        assert (
            _call_compute(
                "sdm:empty",
                no_artifacts,
                benchmark_window=5,
                bear_threshold=-0.05,
                bull_threshold=0.05,
                today="2026-08-01",
            )
            == []
        )

    def test_binary_garbage_trades_returns_empty_without_raising(
        self, tmp_path
    ) -> None:
        run_dir = _write_run_fixture(tmp_path)
        trades_path = run_dir / "artifacts" / "trades.csv"
        trades_path.write_bytes(b"\xff\xfe\x00\x81garbage\x93\xfd")

        assert sd_artifacts.read_trade_activity(trades_path) is None
        assert _compute_with_fixture_windows(run_dir) == []

    def test_binary_garbage_equity_returns_empty_without_raising(
        self, tmp_path
    ) -> None:
        run_dir = _write_run_fixture(tmp_path)
        equity_path = run_dir / "artifacts" / "equity.csv"
        equity_path.write_bytes(b"\x93\xfd\x00binary\xff\xfe")

        assert sd_artifacts.read_equity_series(equity_path) is None
        assert _compute_with_fixture_windows(run_dir) == []


# ---------------------------------------------------------------------------
# Legacy one-row-per-trade artifacts still parse via aliases
# ---------------------------------------------------------------------------


@requires_harness
class TestLegacyAliasSupport:
    def test_legacy_date_benchmark_artifacts_still_parse(self, tmp_path) -> None:
        run_dir = _write_legacy_fixture(tmp_path)
        equity = pd.read_csv(run_dir / "artifacts" / "equity.csv")
        assert {"date", "equity", "benchmark"} <= set(equity.columns)
        assert "timestamp" not in equity.columns

        rows = _compute_with_fixture_windows(run_dir)
        counts = {r.regime: r.trades_in_regime for r in rows}
        assert (
            counts == EXPECTED_COUNTS
        ), "legacy one-row-per-trade artifacts must keep counting every row"
        for row in rows:
            assert row.benchmark_in_regime is not None
            # No zero-pnl marker → concurrency undetectable → fail-closed:
            # generic caveat and a null breakeven, never a silent aggregate.
            assert row.breakeven_fee_bps is None
            assert any(
                w.startswith(sd_harness.MULTI_POSITION_WARNING_PREFIX)
                and "concurrency is unknown" in w
                for w in row.warnings
            ), f"{row.regime}: marker-less artifacts must carry the generic caveat"

    def test_legacy_reader_counts_every_row_without_concurrency(self, tmp_path) -> None:
        trades_path = _write_legacy_fixture(tmp_path) / "artifacts" / "trades.csv"
        activity = sd_artifacts.read_trade_activity(trades_path)
        assert activity is not None
        trade_dates, max_concurrent = activity
        assert trade_dates == sorted(ALL_TRADE_DAYS)
        assert max_concurrent is None


# ---------------------------------------------------------------------------
# Multi-position runs carry the aggregate-breakeven caveat
# ---------------------------------------------------------------------------


@requires_harness
class TestMultiPositionCaveat:
    def test_overlapping_positions_null_the_breakeven(self, tmp_path) -> None:
        # sergio12S (#969): the aggregate breakeven is structurally invalid
        # for multi-position runs, so the row stores null instead of a number
        # wrong by 1.1-6.5x — never a silent aggregate figure.
        run_dir = _write_multi_position_fixture(tmp_path)
        activity = sd_artifacts.read_trade_activity(
            run_dir / "artifacts" / "trades.csv"
        )
        assert activity is not None
        assert activity[1] == 2, "AAA (Jan 14-16) and BBB (Jan 15-21) overlap"

        rows = _compute_with_fixture_windows(run_dir)
        counts = {r.regime: r.trades_in_regime for r in rows}
        assert counts == {"bear_market": 1, "bull_market": 1}
        for row in rows:
            assert row.breakeven_fee_bps is None, (
                f"{row.regime}: multi-position breakeven must be null, got "
                f"{row.breakeven_fee_bps!r}"
            )
            assert (
                row.cost_sensitive is False
            ), f"{row.regime}: sensitivity is unverifiable, not assertable"
            caveats = [
                w
                for w in row.warnings
                if w.startswith(sd_harness.MULTI_POSITION_WARNING_PREFIX)
            ]
            assert len(caveats) == 1, f"{row.regime}: exactly one caveat expected"
            assert "2 concurrent positions" in caveats[0]
            assert "breakeven_fee_bps is null" in caveats[0]


# ---------------------------------------------------------------------------
# rebuild_evidence
# ---------------------------------------------------------------------------


def _make_store(tmp_path):
    from src.strategy_discovery.evidence_store import EvidenceStore

    return EvidenceStore(tmp_path / "evidence.db")


@requires_harness
class TestRebuildEvidence:
    def test_rebuild_clears_then_upserts_and_reports_skipped_dirs(
        self, tmp_path
    ) -> None:
        store = _make_store(tmp_path)
        junk = sd_models.EvidenceRow(
            strategy_id="junk:row", regime="bear_market", trades_in_regime=1
        )
        store.upsert_rows([junk])

        good_run = _write_run_fixture(tmp_path / "good")
        bad_run = tmp_path / "bad_run"
        bad_run.mkdir()

        envelope = sd_harness.rebuild_evidence(
            [
                {"strategy_id": "sdm:fixture_run", "run_dir": str(good_run)},
                {"strategy_id": "sdm:bad_run", "run_dir": str(bad_run)},
            ],
            store,
        )

        assert (
            store.get_rows(strategy_id="junk:row") == []
        ), "rebuild_evidence must clear the store before repopulating"
        store_rows = store.get_rows()
        assert store_rows, "good run_dir must have produced evidence rows"
        assert {r.strategy_id for r in store_rows} == {"sdm:fixture_run"}
        # Rebuild runs compute_evidence_for_run with its documented defaults;
        # whatever regime windows those defaults find, no fixture round trip
        # may be lost or double-counted (9 round trips, exit rows only).
        assert sum(r.trades_in_regime for r in store_rows) == 9

        assert isinstance(
            envelope, dict
        ), f"rebuild envelope must be a dict, got {type(envelope)}"
        assert envelope.get("status") == "ok"
        skipped = envelope.get("skipped")
        assert (
            skipped
        ), f"envelope must carry a 'skipped' entry for bad dirs: {envelope!r}"
        assert len(skipped) == 1
        skipped_entry = skipped[0]
        assert str(bad_run) in str(
            skipped_entry.get("run_dir", "")
        ), f"skipped entry must name the bad run_dir: {skipped_entry!r}"
        assert skipped_entry.get(
            "reason"
        ), f"skipped entry must carry a reason: {skipped_entry!r}"

    def test_rebuild_with_no_runs_leaves_store_empty(self, tmp_path) -> None:
        store = _make_store(tmp_path)
        junk = sd_models.EvidenceRow(
            strategy_id="junk:row", regime="bull_market", trades_in_regime=2
        )
        store.upsert_rows([junk])
        envelope = sd_harness.rebuild_evidence([], store)
        assert store.row_count() == 0
        assert envelope.get("status") == "ok"
        assert envelope.get("rows") == 0
