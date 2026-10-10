"""A backtest whose config declares an artifact lands in that artifact's bench history.

Decay monitoring reads ``bench_history``, so the rows written here decide what
it sees: which runs count towards decay, whether a rerun is a new measurement,
and whether an idle run can pose as one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.strategy_store.metrics import DECAY_BENCH_TYPES
from src.strategy_store.models import Artifact, ArtifactType, BenchResult
from src.strategy_store.sqlite_store import SqliteStrategyStore
from src.strategy_store.store import InMemoryStrategyStore
from src.tools.backtest_tool import run_backtest
from src.tools.sdm_status_tool import SdmStatusTool

_METRICS_HEADER = "sharpe,annual_return,max_drawdown,calmar,trade_count\n"
_METRICS_ROW = "0.7845,0.1067,-0.2123,0.5026,1427\n"


@dataclass
class _FakeRunResult:
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    artifacts: dict[str, Path] = field(default_factory=dict)


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A fresh SQLite store per test, shared with the tools through the singleton."""
    monkeypatch.setenv(
        "VIBE_TRADING_STRATEGY_STORE_DB_PATH", str(tmp_path / "store.db")
    )
    import src.strategy_store._shared as shared

    # The env var alone does not isolate a test once the singleton exists.
    monkeypatch.setattr(shared, "_store", None)
    return shared.get_store()


@pytest.fixture()
def artifact_id(store: Any) -> str:
    """A registered strategy artifact."""
    return store.register_artifact(
        Artifact(
            id="",
            type=ArtifactType.STRATEGY,
            name="inverse vol weighting",
            universe="equity_hk",
        )
    )


@pytest.fixture()
def run_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Directory the backtest tool is allowed to run in."""
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(root))
    return root


@pytest.fixture()
def run_dir(run_root: Path) -> Path:
    """A run directory holding the metrics of a run that traded."""
    return _make_run_dir(run_root, "run")


def _make_run_dir(root: Path, name: str, metrics_row: str = _METRICS_ROW) -> Path:
    run_dir = root / name
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "code" / "signal_engine.py").write_text("", encoding="utf-8")
    _write_metrics(run_dir, metrics_row)
    return run_dir


def _write_metrics(run_dir: Path, row: str, header: str = _METRICS_HEADER) -> None:
    metrics_path = run_dir / "artifacts" / "metrics.csv"
    metrics_path.write_text(header + row, encoding="utf-8")


def _write_config(run_dir: Path, **extra: Any) -> None:
    config = {
        "source": "yfinance",
        "start_date": "2021-01-04",
        "end_date": "2026-09-25",
        **extra,
    }
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")


def _run(run_dir: Path, *, success: bool = True, exit_code: int = 0) -> dict[str, Any]:
    with (
        patch("src.tools.backtest_tool.emit_progress"),
        patch("src.tools.backtest_tool.Runner") as runner_cls,
    ):
        runner_cls.return_value.execute.return_value = _FakeRunResult(
            success=success, exit_code=exit_code
        )
        return json.loads(run_backtest(str(run_dir)))


def _decay_check(artifact_id: str) -> dict[str, Any]:
    return json.loads(
        SdmStatusTool().execute(action="decay_check", artifact_id=artifact_id)
    )


# -- recording ---------------------------------------------------------------


def test_declared_run_is_recorded_as_manual_by_default(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    _write_config(run_dir, artifact_id=artifact_id)

    envelope = _run(run_dir)

    assert envelope["status"] == "ok", envelope
    assert envelope["bench_record"] == {
        "status": "recorded",
        "artifact_id": artifact_id,
        "bench_type": "manual",
    }
    (row,) = store.get_bench_history(artifact_id)
    assert row.bench_type == "manual"
    assert row.sharpe == pytest.approx(0.7845)
    assert row.annual_return == pytest.approx(0.1067)
    assert row.max_drawdown == pytest.approx(-0.2123)
    assert row.calmar == pytest.approx(0.5026)
    assert (row.test_start, row.test_end) == ("2021-01-04", "2026-09-25")
    assert row.run_dir == str(run_dir)


def test_runner_leaves_grading_and_factor_metrics_empty(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    """Alive or dead is the evaluation step's verdict, and a strategy has no IC."""
    _write_config(run_dir, artifact_id=artifact_id)

    _run(run_dir)

    (row,) = store.get_bench_history(artifact_id)
    assert row.category is None
    assert row.ic_mean is None
    assert row.ic_std is None
    assert row.ir is None
    assert row.ic_positive_ratio is None
    assert row.t_stat is None


@pytest.mark.parametrize("bench_type", ["initial", "periodic", "manual"])
def test_declared_bench_type_is_recorded(
    run_dir: Path, store: Any, artifact_id: str, bench_type: str
) -> None:
    _write_config(run_dir, artifact_id=artifact_id, bench_type=bench_type)

    envelope = _run(run_dir)

    assert envelope["bench_record"]["bench_type"] == bench_type
    (row,) = store.get_bench_history(artifact_id)
    assert row.bench_type == bench_type


def test_unknown_bench_type_is_refused(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    _write_config(run_dir, artifact_id=artifact_id, bench_type="weekly")

    envelope = _run(run_dir)

    assert envelope["status"] == "ok"
    assert envelope["bench_record"]["status"] == "failed"
    assert store.get_bench_history(artifact_id) == []


def test_only_declared_periodic_runs_feed_decay(
    run_root: Path, store: Any, artifact_id: str
) -> None:
    """Default runs are bookkeeping; decay moves only on runs declared for it."""
    for index in range(3):
        manual = _make_run_dir(
            run_root, f"manual{index}", f"0.{index + 1},0.1,-0.2,0.5,10\n"
        )
        _write_config(manual, artifact_id=artifact_id)
        _run(manual)

    assert len(store.get_bench_history(artifact_id)) == 3
    assert _decay_check(artifact_id)["signal"] == "insufficient_data"

    for index in range(3):
        periodic = _make_run_dir(
            run_root, f"periodic{index}", f"1.{index + 1},0.1,-0.2,0.5,10\n"
        )
        _write_config(periodic, artifact_id=artifact_id, bench_type="periodic")
        _run(periodic)

    result = _decay_check(artifact_id)
    assert result["signal"] != "insufficient_data", result
    assert result["metrics"]["baseline_sharpe"] == pytest.approx(1.2)


# -- reruns ------------------------------------------------------------------


def test_identical_rerun_is_not_recorded_twice(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    """The same measurement counted twice would look like two confirmations."""
    _write_config(run_dir, artifact_id=artifact_id)
    _run(run_dir)

    envelope = _run(run_dir)

    assert envelope["bench_record"] == {
        "status": "skipped",
        "artifact_id": artifact_id,
        "reason": "identical bench already recorded",
    }
    assert len(store.get_bench_history(artifact_id)) == 1


def test_rerun_with_changed_metrics_is_recorded(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    """A rerun of the same directory that measured something new is kept."""
    _write_config(run_dir, artifact_id=artifact_id)
    _run(run_dir)
    _write_metrics(run_dir, "0.6012,0.0911,-0.2500,0.3644,1388\n")

    envelope = _run(run_dir)

    assert envelope["bench_record"]["status"] == "recorded"
    sharpes = [row.sharpe for row in store.get_bench_history(artifact_id)]
    assert sharpes == pytest.approx([0.6012, 0.7845])


# -- runs that must not be recorded ------------------------------------------


def test_undeclared_run_keeps_legacy_envelope_and_writes_nothing(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    _write_config(run_dir)

    envelope = _run(run_dir)

    assert envelope["status"] == "ok", envelope
    assert "bench_record" not in envelope
    assert store.get_bench_history(artifact_id) == []


def test_failed_backtest_records_no_bench(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    _write_config(run_dir, artifact_id=artifact_id)

    envelope = _run(run_dir, success=False, exit_code=3)

    assert envelope["status"] == "error"
    assert envelope["bench_record"] == {
        "status": "skipped",
        "artifact_id": artifact_id,
        "reason": "backtest did not succeed",
    }
    assert store.get_bench_history(artifact_id) == []


def test_zero_trade_run_is_skipped(run_dir: Path, store: Any, artifact_id: str) -> None:
    """Zero-valued metrics from an idle run would read as a performance collapse."""
    _write_config(run_dir, artifact_id=artifact_id)
    _write_metrics(run_dir, "0,0,0,0,0\n")

    envelope = _run(run_dir)

    assert envelope["bench_record"] == {
        "status": "skipped",
        "artifact_id": artifact_id,
        "reason": "backtest produced no trades",
    }
    assert store.get_bench_history(artifact_id) == []


def test_metrics_without_trade_count_are_skipped(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    _write_config(run_dir, artifact_id=artifact_id)
    _write_metrics(
        run_dir,
        "0.7845,0.1067,-0.2123,0.5026\n",
        header="sharpe,annual_return,max_drawdown,calmar\n",
    )

    envelope = _run(run_dir)

    assert envelope["bench_record"]["status"] == "skipped"
    assert store.get_bench_history(artifact_id) == []


def test_missing_metrics_csv_is_skipped(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    """An empty row would count towards the decay floor with nothing to measure."""
    _write_config(run_dir, artifact_id=artifact_id)
    (run_dir / "artifacts" / "metrics.csv").unlink()

    envelope = _run(run_dir)

    assert envelope["bench_record"]["status"] == "skipped"
    assert store.get_bench_history(artifact_id) == []


def test_store_failure_is_reported_without_failing_the_backtest(
    run_dir: Path, store: Any, artifact_id: str
) -> None:
    _write_config(run_dir, artifact_id=artifact_id)

    with patch(
        "src.strategy_store.sqlite_store.SqliteStrategyStore.record_bench",
        side_effect=RuntimeError("disk full"),
    ):
        envelope = _run(run_dir)

    assert envelope["status"] == "ok"
    assert envelope["bench_record"]["status"] == "failed"
    assert "disk full" in envelope["bench_record"]["reason"]
    assert store.get_bench_history(artifact_id) == []


def test_unregistered_artifact_id_is_refused(run_dir: Path, store: Any) -> None:
    """A mistyped id must surface as a failure, not as an orphaned row."""
    _write_config(run_dir, artifact_id="never-registered")

    envelope = _run(run_dir)

    assert envelope["status"] == "ok"
    assert envelope["bench_record"]["status"] == "failed"
    assert store.get_bench_history("never-registered") == []


# -- store contract ----------------------------------------------------------


@pytest.fixture(params=["memory", "sqlite"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    """An empty store of each backend."""
    if request.param == "memory":
        return InMemoryStrategyStore()
    return SqliteStrategyStore(db_path=tmp_path / "contract.db")


def _register(backend: Any) -> str:
    return backend.register_artifact(
        Artifact(
            id="", type=ArtifactType.STRATEGY, name="contract", universe="equity_us"
        )
    )


def test_has_bench_result_matches_only_identical_rows(backend: Any) -> None:
    artifact_id = _register(backend)
    stored = BenchResult(
        artifact_id=artifact_id, bench_type="manual", sharpe=0.5, run_dir="/runs/a"
    )
    backend.record_bench(stored)

    assert backend.has_bench_result(stored)
    assert backend.has_bench_result(replace(stored, created_at="2020-01-01"))
    assert not backend.has_bench_result(replace(stored, sharpe=0.6))
    assert not backend.has_bench_result(replace(stored, run_dir="/runs/b"))
    assert not backend.has_bench_result(replace(stored, bench_type="periodic"))


def test_bench_history_filters_by_type_before_limit(backend: Any) -> None:
    artifact_id = _register(backend)
    backend.record_bench(
        BenchResult(artifact_id=artifact_id, bench_type="periodic", sharpe=1.0)
    )
    backend.record_bench(
        BenchResult(artifact_id=artifact_id, bench_type="manual", sharpe=2.0)
    )

    rows = backend.get_bench_history(
        artifact_id, limit=1, bench_types=DECAY_BENCH_TYPES
    )

    assert [row.sharpe for row in rows] == [1.0]
    assert len(backend.get_bench_history(artifact_id)) == 2
