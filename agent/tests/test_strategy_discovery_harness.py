"""Frozen-contract tests for ``src.strategy_discovery.evidence_harness`` — #969.

AC3 (evidence from reproducible runs only) is exercised here end to end on
synthetic run directories built in tmp_path: ``artifacts/trades.csv``
(date + pnl/return_pct rows, closed trades only) and ``artifacts/equity.csv``
(date, equity, benchmark). The benchmark series is a piecewise-constant-slope
curve engineered so that, with ``benchmark_window=5`` and thresholds of
±0.05, days 2024-01-14..16 are a bear window, 2024-01-21..24 a bull window,
and 2024-01-07..08 structural — regardless of whether the harness measures
the window return as an endpoint ratio or a mean of daily changes (both
agree inside the segments; the self-check class pins this).

``TestFixtureSelfCheck`` runs today without the sibling package; the rest
skips with a clear reason until ``src.strategy_discovery.evidence_harness``
lands. Deterministic: all dates are fixed strings, no wall-clock reads.
"""

from __future__ import annotations

import csv
import inspect
import math
import re
from datetime import date, timedelta

import pandas as pd
import pytest

try:
    from src.strategy_discovery import evidence_harness as sd_harness
    from src.strategy_discovery import models as sd_models

    HARNESS_AVAILABLE = True
except ImportError:
    sd_harness = None
    sd_models = None
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
    return pd.Series(values, index=pd.DatetimeIndex(index), name="benchmark")


def _write_run_fixture(base_dir, *, include_trades=True, include_equity=True):
    """Build a synthetic run_dir with artifacts/ CSVs (<= 40 rows each)."""
    run_dir = base_dir / "run_fixture"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    if include_equity:
        bench = _benchmark_series()
        equity = pd.Series(
            [1_000_000.0 * (1.001**i) for i in range(DAYS)], index=bench.index
        )
        df = pd.DataFrame({"equity": equity.values, "benchmark": bench.values})
        df.insert(0, "date", [d.strftime("%Y-%m-%d") for d in bench.index])
        df.insert(1, "timestamp", df["date"])
        df["benchmark_equity"] = df["benchmark"]
        df.to_csv(artifacts / "equity.csv", index=False)

    if include_trades:
        rows = []
        for trade_date in sorted(BEAR_DAYS | BULL_DAYS | STRUCTURAL_DAYS):
            rows.append(
                {
                    "date": trade_date.strftime("%Y-%m-%d"),
                    "timestamp": trade_date.strftime("%Y-%m-%d"),
                    "code": "TEST.SH",
                    "side": "sell",
                    "pnl": 50.0,
                    "return_pct": 0.5,
                }
            )
        with open(artifacts / "trades.csv", "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

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

    def test_trade_fixture_shape(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        trades = pd.read_csv(run_dir / "artifacts" / "trades.csv")
        equity = pd.read_csv(run_dir / "artifacts" / "equity.csv")
        assert len(trades) == 9
        assert {"date", "pnl", "return_pct"} <= set(trades.columns)
        assert len(equity) == DAYS
        assert {"date", "equity", "benchmark"} <= set(equity.columns)
        assert (trades["pnl"] > 0).all()


# ---------------------------------------------------------------------------
# compute_evidence_for_run
# ---------------------------------------------------------------------------


@requires_harness
class TestComputeEvidence:
    def test_expected_regime_attribution_and_trade_counts(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _call_compute(
            "sdm:fixture_run",
            run_dir,
            benchmark_window=5,
            bear_threshold=-0.05,
            bull_threshold=0.05,
            today="2026-08-01",
        )
        assert isinstance(rows, list)
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

    def test_date_ranges_format(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _call_compute(
            "sdm:fixture_run",
            run_dir,
            benchmark_window=5,
            bear_threshold=-0.05,
            bull_threshold=0.05,
            today="2026-08-01",
        )
        pattern = re.compile(r"^\d{4}-\d{2} to \d{4}-\d{2}$")
        for row in rows:
            assert isinstance(row.date_ranges, tuple)
            assert row.date_ranges, f"{row.regime}: date_ranges must not be empty"
            for entry in row.date_ranges:
                assert pattern.match(entry), f"bad date_range format: {entry!r}"

    def test_quality_classification_applied(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        rows = _call_compute(
            "sdm:fixture_run",
            run_dir,
            benchmark_window=5,
            bear_threshold=-0.05,
            bull_threshold=0.05,
            today="2026-08-01",
        )
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
        # whatever regime windows those defaults find, no fixture trade may be
        # lost or fabricated (9 closed trades in the fixture).
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
