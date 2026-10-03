"""FE-1 acceptance tests for the structured backtest summary (R1 + R4).

Pins the contract the web frontend consumes: a best-effort ``summary`` block
built from run_card.json + equity.csv + the ohlcv glob, the ``ohlcv`` map
inside the envelope's ``artifacts``, byte-identical legacy envelope fields,
and no summary on any failure path or corrupt input.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.backtest_summary import (
    MAX_PREVIEW_POINTS,
    build_backtest_summary,
    collect_ohlcv_paths,
    try_build_backtest_summary,
)
from src.tools.backtest_tool import run_backtest

CARD_METRICS = {
    "sharpe": 1.25,
    "return_pct": 0.1523,
    "max_drawdown": -0.0831,
    "annual_return": 0.31,
    "trades": 42,
}
EQUITY_COLUMNS = [
    "timestamp",
    "ret",
    "equity",
    "drawdown",
    "benchmark_equity",
    "active_ret",
]


def _run_card(
    codes: list[str] | None = None, warnings: list[str] | None = None
) -> dict:
    return {
        "schema_version": "1.0",
        "generated_at": "2026-09-30T00:00:00Z",
        "backtest": {
            "codes": codes if codes is not None else ["BTC-USDT"],
            "start_date": "2024-01-01",
            "end_date": "2024-06-30",
            "interval": "1D",
            "engine": "crypto",
            "initial_cash": 1000000,
            "source": "okx",
        },
        "reproducibility": {"config_hash": "0" * 64},
        "data_sources": ["okx"],
        "metrics": dict(CARD_METRICS),
        "warnings": warnings or [],
        "artifacts": [],
    }


def _equity_rows(count: int) -> list[dict]:
    start = date(2024, 1, 1)
    return [
        {
            "timestamp": (start + timedelta(days=i)).isoformat(),
            "ret": 0.001,
            "equity": 1000000.0 + 1000.0 * i,
            "drawdown": -0.0001 * i,
            "benchmark_equity": 1000000.0 + 500.0 * i,
            "active_ret": 0.0005,
        }
        for i in range(count)
    ]


def _write_equity_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=EQUITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _preview_point(row: dict) -> dict:
    return {
        "time": row["timestamp"],
        "equity": row["equity"],
        "drawdown": row["drawdown"],
        "benchmark_equity": row["benchmark_equity"],
    }


@pytest.fixture()
def summary_run_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run_dir = tmp_path / "run_20260930"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "config.json").write_text(
        json.dumps({"source": "okx"}), encoding="utf-8"
    )
    (run_dir / "code" / "signal_engine.py").write_text("", encoding="utf-8")
    (run_dir / "run_card.json").write_text(json.dumps(_run_card()), encoding="utf-8")
    _write_equity_csv(run_dir / "artifacts" / "equity.csv", _equity_rows(5))
    (run_dir / "artifacts" / "trades.csv").write_text(
        "symbol,pnl\nBTC-USDT,10\n", encoding="utf-8"
    )
    (run_dir / "artifacts" / "metrics.csv").write_text(
        "sharpe\n1.25\n", encoding="utf-8"
    )
    (run_dir / "artifacts" / "ohlcv_BTC-USDT.csv").write_text(
        "timestamp,open\n", encoding="utf-8"
    )
    return run_dir


@dataclass
class _FakeRunResult:
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    artifacts: dict = field(default_factory=dict)


def _run_tool(run_dir: Path, result: _FakeRunResult) -> dict:
    with (
        patch("src.tools.backtest_tool.emit_progress"),
        patch("src.tools.backtest_tool.Runner") as runner_cls,
    ):
        runner_cls.return_value.execute.return_value = result
        return json.loads(run_backtest(str(run_dir)))


# (a) summary matches the fixture run_card + equity exactly ------------------


def test_summary_matches_run_card_and_equity_fixture(summary_run_dir):
    summary = build_backtest_summary(summary_run_dir)
    rows = _equity_rows(5)
    artifacts = summary_run_dir / "artifacts"

    assert summary["schema_version"] == "1.0"
    assert summary["run_id"] == summary_run_dir.name
    assert summary["title"] == "BTC-USDT"
    assert summary["codes"] == ["BTC-USDT"]
    assert summary["start_date"] == "2024-01-01"
    assert summary["end_date"] == "2024-06-30"
    assert summary["interval"] == "1D"
    assert summary["initial_cash"] == 1000000
    assert summary["metrics"] == CARD_METRICS
    assert summary["warnings"] == []
    assert summary["equity_preview"] == [_preview_point(row) for row in rows]
    assert summary["artifact_paths"] == {
        "equity": str(artifacts / "equity.csv"),
        "trades": str(artifacts / "trades.csv"),
        "metrics": str(artifacts / "metrics.csv"),
        "run_card_json": str(summary_run_dir / "run_card.json"),
        "ohlcv": {"BTC-USDT": str(artifacts / "ohlcv_BTC-USDT.csv")},
    }


def test_title_joins_codes_with_middle_dot(summary_run_dir):
    card = _run_card(codes=["BTC-USDT", "ETH-USDT", "600519.SH"])
    (summary_run_dir / "run_card.json").write_text(json.dumps(card), encoding="utf-8")

    summary = build_backtest_summary(summary_run_dir)

    assert summary["title"] == "BTC-USDT \u00b7 ETH-USDT \u00b7 600519.SH"
    assert summary["codes"] == ["BTC-USDT", "ETH-USDT", "600519.SH"]


def test_warnings_come_from_the_run_card(summary_run_dir):
    card = _run_card(warnings=["mixed caliber", "annualisation adjusted"])
    (summary_run_dir / "run_card.json").write_text(json.dumps(card), encoding="utf-8")

    assert build_backtest_summary(summary_run_dir)["warnings"] == [
        "mixed caliber",
        "annualisation adjusted",
    ]


# (b) preview sampling: 200 rows -> <=50, first/last always kept -------------


def test_preview_samples_200_rows_with_endpoints_kept(summary_run_dir):
    rows = _equity_rows(200)
    _write_equity_csv(summary_run_dir / "artifacts" / "equity.csv", rows)

    preview = build_backtest_summary(summary_run_dir)["equity_preview"]

    assert len(preview) <= MAX_PREVIEW_POINTS
    assert preview[0] == _preview_point(rows[0])
    assert preview[-1] == _preview_point(rows[-1])
    times = [point["time"] for point in preview]
    assert times == sorted(times), "equal-stride sampling keeps chronological order"


# (c) metrics identical to the run_card metrics dict -------------------------


def test_metrics_are_the_full_run_card_object(summary_run_dir):
    summary = build_backtest_summary(summary_run_dir)
    card = json.loads((summary_run_dir / "run_card.json").read_text(encoding="utf-8"))

    assert isinstance(summary["metrics"], dict)
    assert summary["metrics"] == card["metrics"]


def test_non_finite_metric_floats_are_sanitized_to_null(summary_run_dir):
    card = _run_card()
    card["metrics"]["bad_sharpe"] = float("nan")
    card["metrics"]["inf_return"] = float("inf")
    card["metrics"]["nested"] = {"deep": [float("-inf"), 1.5]}
    (summary_run_dir / "run_card.json").write_text(
        json.dumps(card, allow_nan=True), encoding="utf-8"
    )

    summary = build_backtest_summary(summary_run_dir)

    assert summary["metrics"]["bad_sharpe"] is None
    assert summary["metrics"]["inf_return"] is None
    assert summary["metrics"]["nested"] == {"deep": [None, 1.5]}
    assert summary["metrics"]["sharpe"] == 1.25
    json.dumps(summary, allow_nan=False)


# (d) legacy envelope fields byte-identical ----------------------------------


def test_legacy_success_envelope_fields_byte_identical(summary_run_dir):
    equity_path = summary_run_dir / "artifacts" / "equity.csv"
    result = _FakeRunResult(
        success=True,
        exit_code=0,
        stdout="engine done",
        artifacts={"equity": equity_path},
    )

    envelope = _run_tool(summary_run_dir, result)

    trimmed = dict(envelope)
    assert trimmed.pop("summary", None) is not None
    trimmed["artifacts"] = {
        name: path for name, path in trimmed["artifacts"].items() if name != "ohlcv"
    }
    golden = {
        "status": "ok",
        "exit_code": 0,
        "stdout": "engine done",
        "stderr": "",
        "artifacts": {"equity": str(equity_path)},
        "run_dir": str(summary_run_dir),
    }
    assert json.dumps(trimmed, ensure_ascii=False) == json.dumps(
        golden, ensure_ascii=False
    )


def test_legacy_failure_envelope_byte_identical_without_additions(summary_run_dir):
    result = _FakeRunResult(success=False, exit_code=3, stderr="boom")

    envelope = _run_tool(summary_run_dir, result)

    golden = {
        "status": "error",
        "exit_code": 3,
        "stdout": "",
        "stderr": "boom",
        "artifacts": {},
        "run_dir": str(summary_run_dir),
    }
    assert json.dumps(envelope, ensure_ascii=False) == json.dumps(
        golden, ensure_ascii=False
    )


def test_envelope_summary_matches_direct_build(summary_run_dir):
    envelope = _run_tool(summary_run_dir, _FakeRunResult(success=True, exit_code=0))

    direct = build_backtest_summary(
        summary_run_dir, collect_ohlcv_paths(summary_run_dir)
    )

    assert envelope["summary"] == direct
    assert envelope["artifacts"]["ohlcv"] == direct["artifact_paths"]["ohlcv"]


# (e) error paths carry no summary -------------------------------------------


def test_missing_config_error_envelope_has_no_summary(summary_run_dir):
    (summary_run_dir / "config.json").unlink()

    envelope = json.loads(run_backtest(str(summary_run_dir)))

    assert envelope["status"] == "error"
    assert "summary" not in envelope


def test_engine_failure_envelope_has_no_summary_and_no_ohlcv(summary_run_dir):
    envelope = _run_tool(
        summary_run_dir,
        _FakeRunResult(success=False, exit_code=1, stderr="engine crashed"),
    )

    assert envelope["status"] == "error"
    assert "summary" not in envelope
    assert "ohlcv" not in envelope["artifacts"]


# (f) corrupt run_card.json: envelope ok, no summary, no exception -----------


def test_corrupt_run_card_keeps_envelope_ok_without_summary(summary_run_dir):
    (summary_run_dir / "run_card.json").write_text("{not json", encoding="utf-8")

    envelope = _run_tool(summary_run_dir, _FakeRunResult(success=True, exit_code=0))

    assert envelope["status"] == "ok"
    assert "summary" not in envelope
    assert envelope["artifacts"]["ohlcv"] == {
        "BTC-USDT": str(summary_run_dir / "artifacts" / "ohlcv_BTC-USDT.csv")
    }
    assert try_build_backtest_summary(summary_run_dir) is None


def test_non_object_run_card_is_rejected_by_the_builder(summary_run_dir):
    (summary_run_dir / "run_card.json").write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ValueError):
        build_backtest_summary(summary_run_dir)
    assert try_build_backtest_summary(summary_run_dir) is None

    envelope = _run_tool(summary_run_dir, _FakeRunResult(success=True, exit_code=0))
    assert envelope["status"] == "ok"
    assert "summary" not in envelope


def test_missing_run_card_keeps_envelope_ok_without_summary(summary_run_dir):
    (summary_run_dir / "run_card.json").unlink()

    envelope = _run_tool(summary_run_dir, _FakeRunResult(success=True, exit_code=0))

    assert envelope["status"] == "ok"
    assert "summary" not in envelope
    assert try_build_backtest_summary(summary_run_dir) is None


# (g) stdout truncation does not touch summary.metrics (FE acceptance #3) ----


def test_summary_metrics_stay_complete_when_stdout_truncates(summary_run_dir):
    padded = "x" * 5000 + json.dumps({"sharpe": 1.25})
    result = _FakeRunResult(success=True, exit_code=0, stdout=padded)

    envelope = _run_tool(summary_run_dir, result)

    assert len(envelope["stdout"]) == 2000
    assert envelope["stdout"] == padded[-2000:]
    assert envelope["summary"]["metrics"] == CARD_METRICS


# (h) multi-code ohlcv glob mapping ------------------------------------------


def test_ohlcv_glob_maps_every_code(summary_run_dir):
    artifacts = summary_run_dir / "artifacts"
    (artifacts / "ohlcv_ETH-USDT.csv").write_text("timestamp,open\n", encoding="utf-8")
    (artifacts / "ohlcv_600519.SH.csv").write_text("timestamp,open\n", encoding="utf-8")
    expected = {
        "600519.SH": str(artifacts / "ohlcv_600519.SH.csv"),
        "BTC-USDT": str(artifacts / "ohlcv_BTC-USDT.csv"),
        "ETH-USDT": str(artifacts / "ohlcv_ETH-USDT.csv"),
    }

    assert collect_ohlcv_paths(summary_run_dir) == expected

    envelope = _run_tool(summary_run_dir, _FakeRunResult(success=True, exit_code=0))
    assert envelope["artifacts"]["ohlcv"] == expected
    assert envelope["summary"]["artifact_paths"]["ohlcv"] == expected


def test_ohlcv_map_is_empty_without_files(summary_run_dir):
    (summary_run_dir / "artifacts" / "ohlcv_BTC-USDT.csv").unlink()

    assert collect_ohlcv_paths(summary_run_dir) == {}

    envelope = _run_tool(summary_run_dir, _FakeRunResult(success=True, exit_code=0))
    assert envelope["artifacts"]["ohlcv"] == {}
    assert envelope["summary"]["artifact_paths"]["ohlcv"] == {}


def test_ohlcv_glob_ignores_other_artifacts(summary_run_dir):
    artifacts = summary_run_dir / "artifacts"
    (artifacts / "ohlcv_notes.txt").write_text("not a csv", encoding="utf-8")
    (artifacts / "ohlcv_.csv").write_text("timestamp,open\n", encoding="utf-8")

    assert collect_ohlcv_paths(summary_run_dir) == {
        "BTC-USDT": str(artifacts / "ohlcv_BTC-USDT.csv")
    }


# (i) NaN cells in equity.csv become null in the preview ----------------------


def test_nan_and_blank_equity_cells_become_null(summary_run_dir):
    (summary_run_dir / "artifacts" / "equity.csv").write_text(
        "timestamp,ret,equity,drawdown,benchmark_equity,active_ret\n"
        "2024-01-01,0.0,1000000.0,0.0,1000000.0,0.0\n"
        "2024-01-02,NaN,NaN,NaN,NaN,NaN\n"
        "2024-01-03,,inf,,,\n",
        encoding="utf-8",
    )

    summary = build_backtest_summary(summary_run_dir)

    assert summary["equity_preview"][1] == {
        "time": "2024-01-02",
        "equity": None,
        "drawdown": None,
        "benchmark_equity": None,
    }
    assert summary["equity_preview"][2] == {
        "time": "2024-01-03",
        "equity": None,
        "drawdown": None,
        "benchmark_equity": None,
    }
    json.dumps(summary, allow_nan=False)


# (j) equity within the limit returns every row -------------------------------


@pytest.mark.parametrize("count", [1, 3, MAX_PREVIEW_POINTS])
def test_equity_within_limit_returns_all_rows(summary_run_dir, count):
    rows = _equity_rows(count)
    _write_equity_csv(summary_run_dir / "artifacts" / "equity.csv", rows)

    preview = build_backtest_summary(summary_run_dir)["equity_preview"]

    assert preview == [_preview_point(row) for row in rows]


def test_equity_just_over_limit_samples_down(summary_run_dir):
    rows = _equity_rows(MAX_PREVIEW_POINTS + 1)
    _write_equity_csv(summary_run_dir / "artifacts" / "equity.csv", rows)

    preview = build_backtest_summary(summary_run_dir)["equity_preview"]

    assert len(preview) == MAX_PREVIEW_POINTS
    assert preview[0] == _preview_point(rows[0])
    assert preview[-1] == _preview_point(rows[-1])


def test_missing_equity_csv_yields_empty_preview(summary_run_dir):
    (summary_run_dir / "artifacts" / "equity.csv").unlink()

    summary = build_backtest_summary(summary_run_dir)

    assert summary["equity_preview"] == []
    assert summary["artifact_paths"]["equity"] is None
    assert summary["metrics"] == CARD_METRICS


def test_header_only_equity_csv_yields_empty_preview(summary_run_dir):
    _write_equity_csv(summary_run_dir / "artifacts" / "equity.csv", [])

    assert build_backtest_summary(summary_run_dir)["equity_preview"] == []
