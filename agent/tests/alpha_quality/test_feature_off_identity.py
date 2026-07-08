from __future__ import annotations

from typing import Any

import pandas as pd

from src.alpha_quality.model import FEATURE_FLAGS
from src.factors import bench_runner


class _IdentityRegistry:
    def list(self, zoo: str | None = None) -> list[str]:  # noqa: ARG002
        return ["identity_signal"]

    def get(self, alpha_id: str) -> Any:  # noqa: ARG002
        class _Alpha:
            meta = {"theme": ["identity"], "formula_latex": "identity"}

        return _Alpha()

    def compute(
        self, alpha_id: str, panel: dict[str, pd.DataFrame]  # noqa: ARG002
    ) -> pd.DataFrame:
        return panel["factor"]


def _panel() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    symbols = [f"S{i}" for i in range(6)]
    factor = pd.DataFrame(
        [[float(j) for j in range(len(symbols))] for _ in range(len(dates))],
        index=dates,
        columns=symbols,
    )
    return {"factor": factor, "close": factor + 100.0}


def _stable(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if k != "wall_seconds"}


def test_ags_feature_flags_default_false() -> None:
    assert FEATURE_FLAGS == {
        "VIBE_TRADING_AGS_ENABLED": False,
        "VIBE_TRADING_ALPHA_SCORECARD": False,
        "VIBE_TRADING_TRIAL_LEDGER": False,
        "VIBE_TRADING_ALPHA_FOUNDRY": False,
        "VIBE_TRADING_ADMISSION_GATE": False,
        "VIBE_TRADING_FORWARD_TRACKING": False,
        "VIBE_TRADING_ALPHA_REPORT_API": False,
    }


def test_feature_flags_off_keep_existing_run_bench_identity(monkeypatch) -> None:
    panel = _panel()
    monkeypatch.setattr(
        bench_runner,
        "_load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )
    monkeypatch.setattr(
        bench_runner,
        "_compute_forward_returns",
        lambda loaded_panel: loaded_panel["factor"] * 0.001,
    )
    for name in FEATURE_FLAGS:
        monkeypatch.delenv(name, raising=False)

    before = bench_runner.run_bench(
        "fixture",
        "fixture",
        "2024-2024",
        registry=_IdentityRegistry(),
    )
    after = bench_runner.run_bench(
        "fixture",
        "fixture",
        "2024-2024",
        registry=_IdentityRegistry(),
    )

    assert _stable(after) == _stable(before)
