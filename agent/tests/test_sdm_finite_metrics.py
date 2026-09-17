"""Non-finite bench observations must not drive SDM health transitions."""

import json
import math

import pytest

from src.strategy_store.metrics import compute_decay_metrics
from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BenchResult,
)
from src.strategy_store.sqlite_store import SqliteStrategyStore
from src.strategy_store.store import InMemoryStrategyStore
from src.tools.sdm_decay_scan_tool import SdmDecayScanTool
from src.tools.sdm_status_tool import SdmStatusTool


@pytest.mark.parametrize("field", ["ic_mean", "sharpe"])
@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf])
def test_nonfinite_observations_do_not_satisfy_minimum_history(field, invalid):
    history = [BenchResult(**{field: value}) for value in [0.1, invalid, 0.2]]

    assert all(value is None for value in compute_decay_metrics(history).values())


@pytest.mark.parametrize("field", ["ic_mean", "sharpe"])
def test_nonfinite_observations_match_missing_observations(field):
    values = [0.01, math.nan, 0.04, math.inf, 0.02, -math.inf, 0.03]
    history = [BenchResult(**{field: value}) for value in values]
    missing = [
        BenchResult(**{field: value if math.isfinite(value) else None})
        for value in values
    ]

    assert compute_decay_metrics(history) == compute_decay_metrics(missing)


def test_missing_ic_does_not_discard_finite_sharpe():
    metrics = compute_decay_metrics(
        [BenchResult(ic_mean=math.nan, sharpe=0.0) for _ in range(3)]
    )

    assert metrics["ic_positive_ratio"] is None
    assert metrics["rolling_sharpe"] == 0.0


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize("field", ["ic_mean", "sharpe"])
@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf])
def test_tools_report_insufficient_data_without_changing_monitoring_state(
    tmp_path, monkeypatch, backend, field, invalid
):
    store = (
        InMemoryStrategyStore()
        if backend == "memory"
        else SqliteStrategyStore(db_path=tmp_path / "sdm.db")
    )
    monkeypatch.setattr("src.tools.sdm_decay_scan_tool._get_store", lambda: store)
    monkeypatch.setattr("src.tools.sdm_status_tool._get_store", lambda: store)
    artifact_id = store.register_artifact(
        Artifact(
            id="",
            name="nonfinite-bench",
            type=ArtifactType.STRATEGY if field == "sharpe" else ArtifactType.FACTOR,
            universe="test",
            status=ArtifactStatus.MONITORING,
        )
    )
    for _ in range(3):
        store.record_bench(BenchResult(artifact_id=artifact_id, **{field: invalid}))

    status = json.loads(
        SdmStatusTool().execute(action="decay_check", artifact_id=artifact_id)
    )
    scan = json.loads(SdmDecayScanTool().execute())

    assert status["status"] == scan["status"] == "ok"
    assert status["signal"] == "insufficient_data"
    assert scan["summary"]["insufficient_data"] == 1
    assert scan["transitions_applied"] == 0
    assert store.get_artifact(artifact_id).status == ArtifactStatus.MONITORING
    assert list(store.get_decay_history(artifact_id)) == []
