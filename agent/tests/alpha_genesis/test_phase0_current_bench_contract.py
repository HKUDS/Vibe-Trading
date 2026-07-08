from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.factors import bench_runner


class _Phase0Registry:
    def list(self, zoo: str | None = None) -> list[str]:  # noqa: ARG002
        return ["phase0_signal"]

    def get(self, alpha_id: str) -> Any:  # noqa: ARG002
        class _Alpha:
            meta = {
                "theme": ["phase0_contract"],
                "formula_latex": "fixture_phase0_signal",
            }

        return _Alpha()

    def compute(
        self, alpha_id: str, panel: dict[str, pd.DataFrame]  # noqa: ARG002
    ) -> pd.DataFrame:
        return panel["factor"]


def _fixture_panel() -> dict[str, Any]:
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    symbols = [f"S{i}" for i in range(6)]
    factor = pd.DataFrame(
        [[float(i + j) for j in range(len(symbols))] for i in range(len(dates))],
        index=dates,
        columns=symbols,
    )
    returns = factor * 0.001
    return {
        "factor": factor,
        "close": factor + 100.0,
        "forward_returns": returns,
        "_meta": {
            "survivorship_bias": False,
            "pit_contract_present": False,
            "source": "phase0_fixture",
        },
    }


def test_run_bench_contract_contains_current_main_keys(monkeypatch) -> None:
    panel = _fixture_panel()
    monkeypatch.setattr(
        bench_runner,
        "_load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )
    monkeypatch.setattr(
        bench_runner,
        "_compute_forward_returns",
        lambda loaded_panel: loaded_panel["forward_returns"],
    )

    result = bench_runner.run_bench(
        zoo="fixture",
        universe="fixture",
        period="2024-2024",
        registry=_Phase0Registry(),
    )

    expected_keys = {
        "status",
        "rows",
        "meta",
        "top5_by_ir",
        "alive",
        "reversed",
        "dead",
        "n_alphas_tested",
        "n_skipped",
        "skipped",
        "by_theme",
        "wall_seconds",
    }
    assert expected_keys.issubset(result)
    assert result["status"] == "ok"
    assert result["n_alphas_tested"] == 1
    assert result["meta"]["source"] == "phase0_fixture"
    assert result["rows"][0]["id"] == "phase0_signal"
    assert result["rows"][0]["theme"] == ["phase0_contract"]


def test_phase0_baseline_document_records_required_boundaries() -> None:
    doc = Path("docs/ags-current-main-baseline.md")
    text = doc.read_text(encoding="utf-8")

    required_markers = [
        "Current Bench Function Signatures",
        "Current Forward Return Behavior",
        "Current Categorise Thresholds",
        "Existing Metadata Fields",
        "Live Safety Boundary To Avoid Touching",
        "Tests Run",
        "Phase 0 Scope Lock",
    ]
    for marker in required_markers:
        assert marker in text
