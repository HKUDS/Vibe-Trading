from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.factors.bench_runner_strict import run_bench_strict
from src.reliability.quant.scorecard import (
    build_alpha_bench_scorecard,
    write_alpha_bench_scorecard_artifact,
)


def _strict_result() -> dict:
    return {
        "status": "ok",
        "zoo": "alpha101",
        "universe": "csi300",
        "period": "2024-2024",
        "random_control": True,
        "n_random_seeds": 5,
        "oos_split": "2024-07-01",
        "rows": [
            {
                "id": "alpha101_001",
                "random_ic_mean": 0.001,
                "alpha_t_full": 2.5,
                "alpha_t_train": 3.0,
                "alpha_t_test": 2.2,
                "ic_mean": 0.03,
                "ir": 0.5,
                "_category": "confirmed_alive",
            }
        ],
    }


def test_strict_alpha_bench_random_control_results_consumed_not_duplicated() -> None:
    with patch(
        "src.factors.bench_runner_strict.compute_random_ic_series",
        side_effect=AssertionError("adapter must not recompute random control"),
    ):
        card = build_alpha_bench_scorecard(_strict_result(), scorecard_id="sc_alpha")

    assert card.random_control is not None
    assert card.random_control["source"] == "bench_runner_strict"
    assert card.random_control["random_control"] is True
    assert card.random_control["rows"][0]["random_ic_mean"] == 0.001
    assert card.score_breakdown["random_control"] == 1.0


def test_alpha_bench_scorecard_artifact_generated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    monkeypatch.setenv("VIBE_TRADING_ARTIFACT_ROOT", str(tmp_path / "artifact_root"))

    record = write_alpha_bench_scorecard_artifact(
        _strict_result(),
        scorecard_id="sc_alpha_artifact",
    )

    assert record is not None
    assert record.artifact_type == "scorecard"
    payload_path = Path(record.path)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["random_control"]["source"] == "bench_runner_strict"


class _OneAlphaRegistry:
    def list(self, *, zoo: str) -> list[str]:  # noqa: ARG002
        return ["alpha_test"]

    def get(self, aid: str):
        class _Handle:
            meta = {"theme": ["test"], "formula_latex": aid}

        return _Handle()

    def compute(self, aid: str, panel: dict) -> pd.DataFrame:  # noqa: ARG002
        return panel["close"].pct_change().fillna(0.0)


def _patch_strict_inputs(monkeypatch) -> None:
    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    columns = [f"S{i}" for i in range(6)]
    close = pd.DataFrame(
        np.tile(np.arange(1, 81, dtype=float).reshape(-1, 1), (1, 6)),
        index=dates,
        columns=columns,
    )
    close = close.add(np.arange(6), axis=1)
    panel = {"close": close}
    monkeypatch.setattr(
        "src.factors.bench_runner_strict._load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )
    monkeypatch.setattr(
        "src.factors.bench_runner_strict._compute_forward_returns",
        lambda loaded: loaded["close"].pct_change().shift(-1),
    )


def test_alpha_bench_completed_generates_scorecard_summary(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    _patch_strict_inputs(monkeypatch)

    result = run_bench_strict(
        zoo="alpha101",
        universe="csi300",
        period="2024-2024",
        random_control=True,
        registry=_OneAlphaRegistry(),
    )

    assert result["status"] == "ok"
    assert result["scorecard"]["random_control"]["source"] == "bench_runner_strict"


def test_alpha_bench_reliability_mode_off_skips_scorecard_summary(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "off")
    _patch_strict_inputs(monkeypatch)

    result = run_bench_strict(
        zoo="alpha101",
        universe="csi300",
        period="2024-2024",
        random_control=True,
        registry=_OneAlphaRegistry(),
    )

    assert result["status"] == "ok"
    assert "scorecard" not in result
