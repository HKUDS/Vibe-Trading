"""API regressions for the run factor-analysis artifact endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from src.api import runs_routes
from tests.module_os_helpers import patch_module_os


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _write_factor_bundle(
    run_dir: Path,
    name: str,
    ic_csv: str,
    summary: dict | None,
    group_equity_csv: str | None = None,
) -> Path:
    bundle = run_dir / "artifacts" / "factor" / name
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "ic_series.csv").write_text(ic_csv, encoding="utf-8")
    if summary is not None:
        (bundle / "ic_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if group_equity_csv is not None:
        (bundle / "group_equity.csv").write_text(group_equity_csv, encoding="utf-8")
    return bundle


def _ic_csv(rows: list[tuple[str, float]]) -> str:
    lines = ["date,IC"]
    lines.extend(f"{date},{value}" for date, value in rows)
    lines.append("2024-01-30,not-a-number")  # malformed row must be skipped
    return "\n".join(lines) + "\n"


def _summary(ic_count: int) -> dict:
    return {
        "ic_mean": 0.031,
        "ic_std": 0.12,
        "ir": 0.258,
        "ic_positive_ratio": 0.56,
        "ic_count": ic_count,
    }


def test_factor_endpoint_single_factor_happy_path(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_20240102_093000"
    summary = _summary(730)
    _write_factor_bundle(
        run_dir,
        "momentum_20d",
        "date,IC\n2024-01-02,0.0432\n2024-01-03,not-a-number\n2024-01-04,0.0211\n",
        summary,
        "date,Group_1,Group_2,Group_3,Group_4,Group_5\n"
        "2024-01-02,1.0,1.001,1.002,1.003,1.004\n"
        "2024-01-03,0.99,1.002,1.005,1.007,1.01\n"
        "2024-01-04,0.95,1.0,1.03,1.05,1.07\n",
    )

    response = client.get("/runs/run_20240102_093000/factor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert payload["ic_correlation"] is None
    assert len(payload["factors"]) == 1
    factor = payload["factors"][0]
    assert factor["name"] == "momentum_20d"
    assert factor["path"] == "artifacts/factor/momentum_20d"
    assert factor["ic_series"] == [
        {"date": "2024-01-02", "ic": 0.0432},
        {"date": "2024-01-04", "ic": 0.0211},
    ]
    assert factor["ic_stats"] == summary
    assert factor["n_groups"] == 5
    assert factor["long_short_spread"] == round(1.07 - 0.95, 6)
    assert factor["group_final_equity"] == {
        "Group_1": 0.95,
        "Group_2": 1.0,
        "Group_3": 1.03,
        "Group_4": 1.05,
        "Group_5": 1.07,
    }
    assert factor["group_equity"][-1] == {
        "date": "2024-01-04",
        "Group_1": 0.95,
        "Group_2": 1.0,
        "Group_3": 1.03,
        "Group_4": 1.05,
        "Group_5": 1.07,
    }


def test_factor_endpoint_two_factors_ic_correlation(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_20240102_093100"
    dates = [f"2024-01-{day:02d}" for day in range(2, 14)]  # 12 common dates
    momentum_rows = [(date, round(0.01 * (index + 1), 4)) for index, date in enumerate(dates)]
    reversal_rows = [(date, round(-0.01 * (index + 1), 4)) for index, date in enumerate(dates)]
    _write_factor_bundle(run_dir, "momentum_20d", _ic_csv(momentum_rows), _summary(len(dates)))
    _write_factor_bundle(run_dir, "reversal_5d", _ic_csv(reversal_rows), _summary(len(dates)))

    response = client.get("/runs/run_20240102_093100/factor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert [factor["name"] for factor in payload["factors"]] == ["momentum_20d", "reversal_5d"]
    correlation = payload["ic_correlation"]
    assert correlation["labels"] == ["momentum_20d", "reversal_5d"]
    matrix = correlation["matrix"]
    assert len(matrix) == 2 and all(len(row) == 2 for row in matrix)
    assert matrix[0][0] == 1.0 and matrix[1][1] == 1.0
    assert matrix[0][1] == matrix[1][0]
    assert -1.0 <= matrix[0][1] <= 1.0
    assert matrix[0][1] == -1.0  # perfectly opposed IC series


def test_factor_endpoint_run_without_artifacts(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    (tmp_path / "runs" / "run_empty").mkdir(parents=True)

    response = client.get("/runs/run_empty/factor")

    assert response.status_code == 200
    assert response.json() == {"exists": False, "factors": [], "ic_correlation": None}


def test_factor_endpoint_unknown_run_returns_404(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/runs/missing_run/factor")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run missing_run not found"


def test_factor_endpoint_traversal_run_id_returns_400(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/runs/foo.bar/factor")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid run_id"


def test_factor_endpoint_offloads_scan_to_threadpool(tmp_path: Path, monkeypatch) -> None:
    """The blocking factor scan must run off the event loop via the threadpool."""
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_offload"
    _write_factor_bundle(run_dir, "momentum_20d", "date,IC\n2024-01-02,0.02\n", _summary(1))

    offloaded: list = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        offloaded.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(runs_routes, "run_in_threadpool", fake_run_in_threadpool)

    response = client.get("/runs/run_offload/factor")

    assert response.status_code == 200
    assert response.json()["exists"] is True
    assert runs_routes._scan_factor_results in offloaded


def test_factor_endpoint_missing_ic_summary_omits_ic_stats(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_no_summary"
    _write_factor_bundle(run_dir, "value_factor", "date,IC\n2024-01-02,0.01\n", None)

    response = client.get("/runs/run_no_summary/factor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    factor = payload["factors"][0]
    assert factor["name"] == "value_factor"
    assert "ic_stats" not in factor
    assert factor["group_equity"] == []
    assert factor["n_groups"] == 0
    assert factor["long_short_spread"] is None
    assert factor["group_final_equity"] == {}


def test_run_detail_has_factor_artifacts_flag(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    with_factor = tmp_path / "runs" / "run_with_factor"
    _write_factor_bundle(with_factor, "momentum_20d", "date,IC\n2024-01-02,0.02\n", _summary(1))
    (tmp_path / "runs" / "run_without_factor").mkdir(parents=True)

    response_with = client.get("/runs/run_with_factor")
    assert response_with.status_code == 200
    assert response_with.json()["has_factor_artifacts"] is True

    response_without = client.get("/runs/run_without_factor")
    assert response_without.status_code == 200
    assert response_without.json()["has_factor_artifacts"] is False


def test_run_detail_factor_flag_does_not_load_payload_files(tmp_path: Path, monkeypatch) -> None:
    """The lightweight detail flag must only inspect directory entries."""
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_probe_only"
    _write_factor_bundle(
        run_dir,
        "momentum_20d",
        "date,IC\n2024-01-02,0.02\n",
        _summary(1),
        "date,Group_1,Group_2\n2024-01-02,1.0,1.1\n",
    )

    def fail_payload_read(*_args, **_kwargs):
        raise AssertionError("run detail existence probe opened factor payload")

    monkeypatch.setattr(runs_routes, "_load_ic_series_csv", fail_payload_read)
    monkeypatch.setattr(runs_routes, "_load_group_equity_csv", fail_payload_read)
    monkeypatch.setattr(runs_routes, "_load_factor_summary", fail_payload_read)

    response = client.get("/runs/run_probe_only")

    assert response.status_code == 200
    assert response.json()["has_factor_artifacts"] is True


def test_factor_scan_caps_directory_entries(tmp_path: Path, monkeypatch) -> None:
    """A hostile wide tree cannot force an unbounded recursive traversal."""
    run_dir = tmp_path / "run_wide"
    artifacts_dir = run_dir / "artifacts"
    for index in range(40):
        (artifacts_dir / f"branch_{index:03d}").mkdir(parents=True)

    entry_limit = 7
    monkeypatch.setattr(runs_routes, "_FACTOR_MAX_SCAN_ENTRIES", entry_limit)
    real_scandir = runs_routes.os.scandir
    entries_seen = 0

    class GuardedScandir:
        def __init__(self, path: Path) -> None:
            self._context = real_scandir(path)
            self._iterator = None

        def __enter__(self):
            self._iterator = iter(self._context.__enter__())
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return self._context.__exit__(exc_type, exc_value, traceback)

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal entries_seen
            assert self._iterator is not None
            entry = next(self._iterator)
            entries_seen += 1
            assert entries_seen <= entry_limit
            return entry

    patch_module_os(monkeypatch, runs_routes, scandir=GuardedScandir)

    assert runs_routes._has_factor_artifacts(run_dir) is False
    assert entries_seen == entry_limit


def test_factor_scan_caps_nesting_depth(tmp_path: Path, monkeypatch) -> None:
    """A factor marker below the configured depth is never traversed."""
    run_dir = tmp_path / "run_deep"
    directory = run_dir / "artifacts"
    monkeypatch.setattr(runs_routes, "_FACTOR_MAX_SCAN_DEPTH", 2)
    for name in ("one", "two", "three"):
        directory = directory / name
    directory.mkdir(parents=True)
    (directory / "ic_series.csv").write_text("date,IC\n2024-01-02,0.1\n", encoding="utf-8")

    assert runs_routes._has_factor_artifacts(run_dir) is False


def test_factor_endpoint_removes_non_finite_values(tmp_path: Path, monkeypatch) -> None:
    """NaN and infinities in every supported artifact never reach JSON."""
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_non_finite"
    bundle = _write_factor_bundle(
        run_dir,
        "unsafe_factor",
        "date,IC\n2024-01-02,NaN\n2024-01-03,Infinity\n2024-01-04,-Infinity\n2024-01-05,0.125\n",
        None,
        "date,Group_1,Group_2\n2024-01-02,NaN,1.1\n2024-01-03,0.9,Infinity\n2024-01-04,-Infinity,1.2\n",
    )
    (bundle / "ic_summary.json").write_text(
        '{"ic_mean": NaN, "ic_std": Infinity, "ir": -Infinity, "ic_count": 4, '
        '"nested": [1.0, NaN, {"value": Infinity}]}',
        encoding="utf-8",
    )

    response = client.get("/runs/run_non_finite/factor")

    assert response.status_code == 200
    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    factor = response.json()["factors"][0]
    assert factor["ic_series"] == [{"date": "2024-01-05", "ic": 0.125}]
    assert factor["ic_stats"] == {
        "ic_mean": None,
        "ic_std": None,
        "ir": None,
        "ic_count": 4,
        "nested": [1.0, None, {"value": None}],
    }
    assert factor["group_equity"] == [
        {"date": "2024-01-02", "Group_2": 1.1},
        {"date": "2024-01-03", "Group_1": 0.9},
        {"date": "2024-01-04", "Group_2": 1.2},
    ]
    assert factor["long_short_spread"] is None
    assert factor["group_final_equity"] == {"Group_2": 1.2}


def test_factor_endpoint_enforces_row_budgets(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_row_budget"
    _write_factor_bundle(
        run_dir,
        "bounded_factor",
        "date,IC\n2024-01-01,0.1\n2024-01-02,0.2\n2024-01-03,0.3\n",
        _summary(3),
        "date,Group_1,Group_2\n2024-01-01,1.0,1.1\n2024-01-02,1.1,1.2\n2024-01-03,1.2,1.3\n",
    )
    monkeypatch.setattr(runs_routes, "_FACTOR_MAX_ROWS_PER_CSV", 2)
    monkeypatch.setattr(runs_routes, "_FACTOR_MAX_TOTAL_ROWS", 3)

    response = client.get("/runs/run_row_budget/factor")

    assert response.status_code == 200
    factor = response.json()["factors"][0]
    assert len(factor["ic_series"]) == 2
    assert len(factor["group_equity"]) == 1
    assert factor["truncated"] == {"ic_series": True, "group_equity": True}


def test_factor_endpoint_rejects_oversized_summary(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    run_dir = tmp_path / "runs" / "run_large_summary"
    _write_factor_bundle(
        run_dir,
        "large_summary",
        "date,IC\n2024-01-02,0.1\n",
        {"padding": "x" * 100},
    )
    monkeypatch.setattr(runs_routes, "_FACTOR_MAX_SUMMARY_BYTES", 32)

    response = client.get("/runs/run_large_summary/factor")

    assert response.status_code == 200
    factor = response.json()["factors"][0]
    assert "ic_stats" not in factor
    assert factor["truncated"] == {"ic_stats": True}
