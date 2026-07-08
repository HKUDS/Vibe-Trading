from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from src.alpha_quality.model import FactorOutputFrame, SplitConfig
from src.alpha_quality.scorecard import NonReproducibleError, compute_scorecard
from src.factors import bench_runner


class _ScorecardRegistry:
    def list(self, zoo: str | None = None) -> list[str]:  # noqa: ARG002
        return ["scorecard_signal"]

    def get(self, alpha_id: str) -> Any:  # noqa: ARG002
        class _Alpha:
            meta = {"theme": ["scorecard"], "formula_latex": "rank(scorecard)"}

        return _Alpha()

    def compute(
        self, alpha_id: str, panel: dict[str, pd.DataFrame]  # noqa: ARG002
    ) -> pd.DataFrame:
        return panel["factor"]


def _panel(n_dates: int = 16, n_symbols: int = 6) -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="D")
    symbols = [f"S{i}" for i in range(n_symbols)]
    slopes = [0.001 * (i + 1) for i in range(n_symbols)]
    close = pd.DataFrame(
        [
            [100.0 * (1.0 + slope * day) for slope in slopes]
            for day in range(n_dates)
        ],
        index=dates,
        columns=symbols,
    )
    factor = pd.DataFrame(
        [[float(i) for i in range(n_symbols)] for _ in range(n_dates)],
        index=dates,
        columns=symbols,
    )
    false = pd.DataFrame(False, index=dates, columns=symbols)
    return {
        "close": close,
        "factor": factor,
        "st_flag": false.copy(),
        "suspended": false.copy(),
        "limit_up": false.copy(),
        "limit_down": false.copy(),
        "listed_days": pd.DataFrame(60, index=dates, columns=symbols),
        "amount": pd.DataFrame(10_000.0, index=dates, columns=symbols),
    }


def _factor_output(panel: dict[str, pd.DataFrame]) -> FactorOutputFrame:
    factor = panel["factor"]
    valid = pd.DataFrame(True, index=factor.index, columns=factor.columns)
    return FactorOutputFrame(
        factor_id="scorecard_signal",
        formula="rank(scorecard)",
        factor=factor,
        valid_mask=valid,
        tradable_mask=valid,
        universe_mask=valid,
        metadata={"source": "fixture"},
        factor_definition_hash="sha256:fixture",
    )


def _split() -> SplitConfig:
    return SplitConfig(
        train=("2024-01-01", "2024-01-06"),
        valid=("2024-01-07", "2024-01-10"),
        test=("2024-01-11", "2024-01-14"),
    )


def test_scorecard_discovery_scope_does_not_include_test_metrics() -> None:
    panel = _panel()
    scorecard = compute_scorecard(
        _factor_output(panel),
        panel,
        _split(),
        horizons=(1, 5),
        scope="discovery",
        data_snapshot_ref="snapshot:fixture",
        trial_ledger_ref="ledger:fixture",
    )

    assert scorecard.predictive.by_horizon[1].by_split["test"].rank_ic_mean is None
    assert "TEST_SCOPE_HELD_OUT" in scorecard.warnings


def test_scorecard_final_scope_requires_trial_ledger_and_snapshot() -> None:
    panel = _panel()

    with pytest.raises(NonReproducibleError):
        compute_scorecard(
            _factor_output(panel),
            panel,
            _split(),
            horizons=(1,),
            scope="final_quality_decision",
            data_snapshot_ref=None,
            trial_ledger_ref=None,
        )


def test_scorecard_serializes_to_strict_json_without_nan() -> None:
    panel = _panel()
    scorecard = compute_scorecard(
        _factor_output(panel),
        panel,
        _split(),
        horizons=(1,),
        scope="final_quality_decision",
        data_snapshot_ref="snapshot:fixture",
        trial_ledger_ref="ledger:fixture",
    )

    payload = scorecard.to_json()

    assert "NaN" not in payload
    assert "Infinity" not in payload
    assert json.loads(payload)["schema_version"] == "alpha_quality_scorecard.v1"


def test_run_bench_with_scorecard_is_additive(monkeypatch) -> None:
    panel = _panel()
    monkeypatch.setattr(
        bench_runner,
        "_load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )
    monkeypatch.setattr(
        bench_runner,
        "_compute_forward_returns",
        lambda loaded_panel: loaded_panel["close"].pct_change().shift(-1),
    )

    base = bench_runner.run_bench(
        "fixture",
        "fixture",
        "2024-2024",
        registry=_ScorecardRegistry(),
    )
    enriched = bench_runner.run_bench_with_scorecard(
        "fixture",
        "fixture",
        "2024-2024",
        registry=_ScorecardRegistry(),
        split_config=_split(),
        horizons=(1,),
        scope="discovery",
    )

    assert "scorecards" not in base
    assert enriched["status"] == "ok"
    assert "scorecards" in enriched
    assert enriched["scorecards"][0]["factor_id"] == "scorecard_signal"
    assert enriched["rows"] == base["rows"]
