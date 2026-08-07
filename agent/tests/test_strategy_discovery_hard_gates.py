"""Phase 2 hard-gate contract for evidence ingestion (#969, plan D4/D5).

The backtest-diagnose Hard-Gate Checklist IS the evidence ingestion gate:
five stable ``hard-gate:*`` tokens, checked in order, refusing unhealthy
runs BEFORE any per-regime computation. Fixture run dirs are written in the
REAL engine artifact schema, reusing the builders from
``test_strategy_discovery_harness`` (entry+exit trade row pairs with the
zero-pnl marker, ``timestamp``-indexed equity.csv with ``benchmark_equity``,
runtime ``state.json`` with a ``status`` field, engine ``metrics.csv``
header row including ``trade_count``) — no second fixture schema.

Also pinned here:

* NaN mid-equity skips the run ENTIRELY — no partial-curve evidence rows
  (regression for the Phase 1 silent-skip latent, where ``read_equity_series``
  dropped the NaN bars and computed over the survivors).
* Atomic rebuild (D5): a mid-compute crash leaves previously stored rows
  intact because ``replace_rows`` never ran (the old clear-then-upsert path
  would have left the store empty).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

try:
    from src.strategy_discovery import evidence_harness as sd_harness
    from src.strategy_discovery import run_artifacts as sd_artifacts
    from src.strategy_discovery.evidence_store import EvidenceStore
    from src.strategy_discovery.models import EvidenceRow

    from tests.test_strategy_discovery_harness import (
        ALL_TRADE_DAYS,
        ENGINE_METRICS_COLUMNS,
        _engine_equity_frame,
        _write_run_fixture,
        _write_run_state,
    )

    GATES_AVAILABLE = True
except ImportError:
    sd_harness = None
    sd_artifacts = None
    EvidenceStore = None
    EvidenceRow = None
    GATES_AVAILABLE = False

requires_gates = pytest.mark.skipif(
    not GATES_AVAILABLE,
    reason="waiting on src.strategy_discovery hard gates (issue #969 Phase 2)",
)


def _prior_row(strategy_id="alpha_zoo:prior") -> "EvidenceRow":
    return EvidenceRow(
        strategy_id=strategy_id,
        regime="bear_market",
        trades_in_regime=12,
        date_ranges=("2018-01 to 2018-12",),
        last_verified="2026-08-01",
    )


def _make_store(tmp_path: Path) -> "EvidenceStore":
    return EvidenceStore(tmp_path / "evidence.db")


def _write_metrics_without_trade_count(run_dir: Path) -> None:
    columns = [c for c in ENGINE_METRICS_COLUMNS if c != "trade_count"]
    pd.DataFrame([[0.0] * len(columns)], columns=columns).to_csv(
        run_dir / "artifacts" / "metrics.csv", index=False
    )


def _write_nan_equity(run_dir: Path) -> None:
    equity = _engine_equity_frame()
    equity.loc[equity.index[20], "equity"] = float("nan")
    equity.to_csv(run_dir / "artifacts" / "equity.csv")


# ---------------------------------------------------------------------------
# The three gate readers
# ---------------------------------------------------------------------------


@requires_gates
class TestGateReaders:
    def test_read_run_status_success(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        assert sd_artifacts.read_run_status(run_dir) == "success"

    def test_read_run_status_missing_or_unusable(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        (run_dir / "state.json").unlink()
        assert sd_artifacts.read_run_status(run_dir) is None

        (run_dir / "state.json").write_text("{not json", encoding="utf-8")
        assert sd_artifacts.read_run_status(run_dir) is None

        (run_dir / "state.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert sd_artifacts.read_run_status(run_dir) is None

        (run_dir / "state.json").write_text('{"status": ""}', encoding="utf-8")
        assert sd_artifacts.read_run_status(run_dir) is None

    def test_read_metrics_trade_count(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        assert sd_artifacts.read_metrics_trade_count(run_dir) == len(ALL_TRADE_DAYS)

    def test_read_metrics_trade_count_missing_or_unusable(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        metrics = run_dir / "artifacts" / "metrics.csv"

        metrics.unlink()
        assert sd_artifacts.read_metrics_trade_count(run_dir) is None

        _write_metrics_without_trade_count(run_dir)
        assert sd_artifacts.read_metrics_trade_count(run_dir) is None

        metrics.write_text(
            ",".join(ENGINE_METRICS_COLUMNS) + "\n", encoding="utf-8"
        )  # header only, no value row
        assert sd_artifacts.read_metrics_trade_count(run_dir) is None

        values = ["0.0"] * len(ENGINE_METRICS_COLUMNS)
        values[ENGINE_METRICS_COLUMNS.index("trade_count")] = "not-a-number"
        metrics.write_text(
            ",".join(ENGINE_METRICS_COLUMNS) + "\n" + ",".join(values) + "\n",
            encoding="utf-8",
        )
        assert sd_artifacts.read_metrics_trade_count(run_dir) is None

    def test_equity_has_non_finite_false_for_healthy_curve(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        assert sd_artifacts.equity_has_non_finite(run_dir) is False

    def test_equity_has_non_finite_true_for_nan_mid_curve(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        _write_nan_equity(run_dir)
        assert sd_artifacts.equity_has_non_finite(run_dir) is True

    def test_equity_has_non_finite_none_when_unverifiable(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        equity = run_dir / "artifacts" / "equity.csv"

        equity.unlink()
        assert sd_artifacts.equity_has_non_finite(run_dir) is None

        equity.write_text("timestamp,ret,equity,drawdown,benchmark_equity,active_ret\n")
        assert sd_artifacts.equity_has_non_finite(run_dir) is None  # no data rows

        equity.write_bytes(b"\x93\xfd\x00binary\xff\xfe")
        assert sd_artifacts.equity_has_non_finite(run_dir) is None


# ---------------------------------------------------------------------------
# check_run_hard_gates: the five tokens, in order
# ---------------------------------------------------------------------------


@requires_gates
class TestCheckRunHardGates:
    def test_healthy_run_passes(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        assert sd_harness.check_run_hard_gates(run_dir) == (True, None)

    def test_failed_state_is_exit_nonzero(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        _write_run_state(run_dir, trade_count=len(ALL_TRADE_DAYS), status="failed")
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_EXIT_NONZERO + ":")
        assert "'failed'" in reason

    def test_missing_state_json_is_exit_nonzero_fail_closed(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        (run_dir / "state.json").unlink()
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_EXIT_NONZERO + ":")

    def test_missing_metrics_is_metrics_missing(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        (run_dir / "artifacts" / "metrics.csv").unlink()
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_METRICS_MISSING + ":")

    def test_empty_metrics_file_is_metrics_missing(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        (run_dir / "artifacts" / "metrics.csv").write_bytes(b"")
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_METRICS_MISSING + ":")

    def test_zero_trade_count_is_zero_trades(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        _write_run_state(run_dir, trade_count=0)
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_ZERO_TRADES + ":")

    def test_unparseable_trade_count_is_zero_trades_fail_closed(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        metrics = run_dir / "artifacts" / "metrics.csv"
        values = ["0.0"] * len(ENGINE_METRICS_COLUMNS)
        values[ENGINE_METRICS_COLUMNS.index("trade_count")] = "not-a-number"
        metrics.write_text(
            ",".join(ENGINE_METRICS_COLUMNS) + "\n" + ",".join(values) + "\n",
            encoding="utf-8",
        )
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_ZERO_TRADES + ":")

    def test_missing_equity_is_equity_empty(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        (run_dir / "artifacts" / "equity.csv").unlink()
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_EQUITY_EMPTY + ":")

    def test_nan_equity_is_equity_nan(self, tmp_path) -> None:
        run_dir = _write_run_fixture(tmp_path)
        _write_nan_equity(run_dir)
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_EQUITY_NAN + ":")

    def test_gate_order_first_failure_wins(self, tmp_path) -> None:
        # state.json missing AND metrics.csv missing → the status gate (1)
        # reports before the metrics gate (2).
        run_dir = _write_run_fixture(tmp_path)
        (run_dir / "state.json").unlink()
        (run_dir / "artifacts" / "metrics.csv").unlink()
        ok, reason = sd_harness.check_run_hard_gates(run_dir)
        assert ok is False
        assert reason.startswith(sd_harness.HARD_GATE_EXIT_NONZERO + ":")


# ---------------------------------------------------------------------------
# End to end through rebuild_evidence: gated runs yield zero evidence rows
# ---------------------------------------------------------------------------


@requires_gates
class TestHardGatesEndToEnd:
    def test_healthy_run_still_produces_rows(self, tmp_path) -> None:
        store = _make_store(tmp_path)
        run_dir = _write_run_fixture(tmp_path / "ok")
        envelope = sd_harness.rebuild_evidence(
            [{"strategy_id": "sdm:ok_run", "run_dir": str(run_dir)}], store
        )
        assert envelope["status"] == "ok"
        assert envelope["skipped"] == []
        rows = store.get_rows()
        assert rows, "a healthy run must still produce evidence rows"
        assert {r.strategy_id for r in rows} == {"sdm:ok_run"}
        assert sum(r.trades_in_regime for r in rows) == len(ALL_TRADE_DAYS)

    def test_gated_run_yields_zero_rows_with_gate_token(self, tmp_path) -> None:
        store = _make_store(tmp_path)
        run_dir = _write_run_fixture(tmp_path / "failed_state")
        _write_run_state(run_dir, trade_count=len(ALL_TRADE_DAYS), status="failed")
        envelope = sd_harness.rebuild_evidence(
            [{"strategy_id": "sdm:failed_run", "run_dir": str(run_dir)}], store
        )
        assert envelope["rows"] == 0
        assert store.row_count() == 0
        assert len(envelope["skipped"]) == 1
        assert envelope["skipped"][0]["run_dir"] == str(run_dir)
        assert envelope["skipped"][0]["reason"].startswith(
            sd_harness.HARD_GATE_EXIT_NONZERO + ":"
        )

    def test_missing_state_json_yields_zero_rows_end_to_end(self, tmp_path) -> None:
        store = _make_store(tmp_path)
        run_dir = _write_run_fixture(tmp_path / "no_state")
        (run_dir / "state.json").unlink()
        envelope = sd_harness.rebuild_evidence(
            [{"strategy_id": "sdm:no_state", "run_dir": str(run_dir)}], store
        )
        assert envelope["rows"] == 0
        assert store.row_count() == 0
        assert envelope["skipped"][0]["reason"].startswith(
            sd_harness.HARD_GATE_EXIT_NONZERO + ":"
        )

    def test_nan_equity_skips_entirely_not_partial_rows(self, tmp_path) -> None:
        # Regression for the Phase 1 silent-skip latent: read_equity_series
        # drops the NaN bars and returns the SURVIVING partial curve, which
        # pre-gate harnesses turned into partial-curve evidence rows. The
        # hard gate must refuse the whole run instead.
        run_dir = _write_run_fixture(tmp_path / "nan_equity")
        _write_nan_equity(run_dir)
        equity_path = run_dir / "artifacts" / "equity.csv"

        partial = sd_artifacts.read_equity_series(equity_path)
        assert partial is not None, "the Phase 1 reader still skips NaN bars"
        assert len(partial[0]) == 38, "one bar was silently skipped"

        store = _make_store(tmp_path)
        envelope = sd_harness.rebuild_evidence(
            [{"strategy_id": "sdm:nan_run", "run_dir": str(run_dir)}], store
        )
        assert envelope["rows"] == 0
        assert store.row_count() == 0, "no partial-curve evidence may be stored"
        assert envelope["skipped"][0]["reason"].startswith(
            sd_harness.HARD_GATE_EQUITY_NAN + ":"
        )

        # Direct library callers get the same refusal (internal guard).
        assert sd_harness.compute_evidence_for_run("sdm:nan_run", run_dir) == []

    def test_rebuild_with_only_gated_runs_clears_store(self, tmp_path) -> None:
        # A rebuild is a FULL statement of the evidence: even when every run
        # is refused, the (atomic) replace still happens — with zero rows.
        store = _make_store(tmp_path)
        store.upsert_rows([_prior_row()])
        run_dir = _write_run_fixture(tmp_path / "gated")
        (run_dir / "state.json").unlink()
        envelope = sd_harness.rebuild_evidence(
            [{"strategy_id": "sdm:gated", "run_dir": str(run_dir)}], store
        )
        assert envelope["rows"] == 0
        assert store.row_count() == 0
        assert envelope["skipped"][0]["reason"].startswith("hard-gate:")


# ---------------------------------------------------------------------------
# Atomicity (D5): compute-all first, ONE replace_rows, crash-safe
# ---------------------------------------------------------------------------


@requires_gates
class TestAtomicRebuild:
    def test_replace_rows_replaces_all_contents_atomically(self, tmp_path) -> None:
        store = _make_store(tmp_path)
        store.upsert_rows([_prior_row("alpha_zoo:old1"), _prior_row("alpha_zoo:old2")])
        new_row = EvidenceRow(
            strategy_id="sdm:new", regime="bull_market", trades_in_regime=11
        )
        assert store.replace_rows([new_row]) == 1
        rows = store.get_rows()
        assert len(rows) == 1
        assert rows[0].strategy_id == "sdm:new"

        assert store.replace_rows([]) == 0
        assert store.row_count() == 0

    def test_replace_rows_invalid_row_leaves_prior_rows_intact(self, tmp_path) -> None:
        store = _make_store(tmp_path)
        store.upsert_rows([_prior_row()])
        good = EvidenceRow(
            strategy_id="sdm:good", regime="bull_market", trades_in_regime=11
        )
        bad = EvidenceRow(
            strategy_id="sdm:bad",
            regime="structural",
            trades_in_regime=1,
            sharpe_in_regime=float("nan"),
        )
        with pytest.raises(ValueError):
            store.replace_rows([good, bad])
        rows = store.get_rows()
        assert len(rows) == 1
        assert rows[0].strategy_id == "alpha_zoo:prior"

    def test_mid_compute_crash_leaves_prior_rows_intact(
        self, tmp_path, monkeypatch
    ) -> None:
        # D5: a hard crash (SystemExit bypasses the per-run `except
        # Exception`) mid-compute must leave the store untouched, because
        # replace_rows is only reached after ALL rows computed. The old
        # clear-then-upsert path would have left the store empty here.
        store = _make_store(tmp_path)
        store.upsert_rows([_prior_row()])
        good_run = _write_run_fixture(tmp_path / "good")
        crash_run = _write_run_fixture(tmp_path / "crash")

        def crashing_compute(strategy_id, run_dir, **kwargs):
            if str(run_dir) == str(crash_run):
                raise SystemExit("simulated hard crash mid-compute")
            return [
                EvidenceRow(
                    strategy_id=strategy_id,
                    regime="structural",
                    trades_in_regime=len(ALL_TRADE_DAYS),
                )
            ]

        monkeypatch.setattr(sd_harness, "compute_evidence_for_run", crashing_compute)

        replace_calls: list = []
        original_replace = store.replace_rows

        def replace_spy(rows):
            replace_calls.append(list(rows))
            return original_replace(rows)

        monkeypatch.setattr(store, "replace_rows", replace_spy)

        with pytest.raises(SystemExit):
            sd_harness.rebuild_evidence(
                [
                    {"strategy_id": "sdm:good", "run_dir": str(good_run)},
                    {"strategy_id": "sdm:crash", "run_dir": str(crash_run)},
                ],
                store,
            )

        assert replace_calls == [], "replace_rows must never have run"
        rows = store.get_rows()
        assert len(rows) == 1, "prior rows survive a mid-compute crash"
        assert rows[0].strategy_id == "alpha_zoo:prior"
