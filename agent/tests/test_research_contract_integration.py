"""Entry-point coverage for the factor-research run contract.

These tests exercise both bench runners with an injected in-memory registry and
panel.  They verify the contract survives the runner's public result envelope
without making network requests or depending on the bundled alpha catalogue.
"""

from __future__ import annotations

import argparse
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.factors.bench_runner import run_bench
from src.factors.bench_runner_strict import run_bench_strict


def _panel(n_rows: int = 48, n_symbols: int = 6) -> dict[str, Any]:
    rng = np.random.default_rng(2026)
    index = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    symbols = [f"S{i}" for i in range(n_symbols)]
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(size=(n_rows, n_symbols)), axis=0),
        index=index,
        columns=symbols,
    )
    return {
        "close": close,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": pd.DataFrame(1_000_000.0, index=index, columns=symbols),
        "_meta": {"source": "test-panel"},
    }


class _Registry:
    """Small registry slice consumed by both bench runners."""

    ids = ["alpha_a", "alpha_b"]

    def list(self, *, zoo: str) -> list[str]:  # noqa: ARG002
        return list(self.ids)

    def get(self, alpha_id: str) -> Any:
        class _Handle:
            meta = {
                "theme": ["test"],
                "formula_latex": "close",
                "columns_required": [],
            }

        _Handle.alpha_id = alpha_id
        return _Handle()

    def compute(self, alpha_id: str, panel: dict[str, Any]) -> pd.DataFrame:
        close = panel["close"]
        if alpha_id == "alpha_a":
            return close
        # Keep the second factor distinct while retaining a fully populated
        # cross-section for Spearman IC calculations.
        return close.rank(axis=1, method="first")


def _patch_plain_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = _panel()
    monkeypatch.setattr(
        "src.factors.bench_runner._load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )
    monkeypatch.setattr(
        "src.factors.bench_runner._compute_forward_returns",
        lambda panel_in, horizon=1: panel_in["close"].pct_change(fill_method=None).shift(-1),
    )


def _patch_strict_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = _panel()
    monkeypatch.setattr(
        "src.factors.bench_runner_strict._load_universe_panel",
        lambda universe, period: panel,  # noqa: ARG005
    )
    monkeypatch.setattr(
        "src.factors.bench_runner_strict._compute_forward_returns",
        lambda panel_in, horizon=1: panel_in["close"].pct_change(fill_method=None).shift(-1),
    )


def test_plain_runner_emits_research_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_plain_runner(monkeypatch)

    result = run_bench(
        "test_zoo",
        "mock",
        "2024-2024",
        registry=_Registry(),
        research_stage="neutralization",
        research_lineage=["raw_alpha_library"],
        research_transformations=[{"kind": "neutralization", "controls": ["size"]}],
        horizon=21,
    )

    assert result["status"] == "ok"
    research = result["meta"]["research"]
    assert research["schema"] == "factor-research.run/v1"
    assert research["mode"] == "explore"
    assert research["stage"] == "neutralization"
    assert research["factor_ids"] == ["alpha_a", "alpha_b"]
    assert research["factor_count"] == 2
    assert research["lineage"] == [{"id": "raw_alpha_library"}]
    assert research["transformations"] == [
        {"kind": "neutralization", "controls": ["size"]}
    ]
    assert research["evaluation"] == {
        "horizon": 21,
        "forward_return_sampling": "non_overlapping",
        "method": "rank_ic",
    }


def test_strict_runner_emits_research_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_strict_runner(monkeypatch)

    result = run_bench_strict(
        "test_zoo",
        "mock",
        "2024-2024",
        random_control=False,
        registry=_Registry(),
        research_stage="composite_evaluation",
        research_lineage=[{"kind": "combined_factor", "id": "combo_1"}],
        research_transformations=["walk_forward_combination"],
    )

    assert result["status"] == "ok"
    research = result["meta"]["research"]
    assert research["schema"] == "factor-research.run/v1"
    assert research["mode"] == "strict"
    assert research["stage"] == "composite_evaluation"
    assert research["factor_ids"] == ["alpha_a", "alpha_b"]
    assert research["evaluation"]["method"] == "rank_ic"
    assert research["evaluation"]["horizon"] == 1
    assert research["lineage"] == [{"kind": "combined_factor", "id": "combo_1"}]
    assert research["transformations"] == [{"id": "walk_forward_combination"}]


def test_cli_can_explicitly_label_research_mode():
    from src.factors.cli_handlers import add_subparser

    parser = argparse.ArgumentParser()
    add_subparser(parser.add_subparsers())
    args = parser.parse_args(["alpha", "bench", "--zoo", "alpha101", "--universe", "csi300",
                              "--period", "2024-2024", "--research-mode", "locked"])
    assert args.research_mode == "locked"
