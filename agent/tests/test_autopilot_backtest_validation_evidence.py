"""link_autopilot_backtest must surface run_card.json's validation section.

write_run_card writes walk-forward / Monte-Carlo / bootstrap robustness
results as "validation", a top-level sibling of "metrics" (see
backtest/run_card.py). LinkAutopilotBacktestTool only ever read "metrics",
so an agent linking a backtest to a hypothesis received the performance
numbers while silently losing the evidence needed to judge whether that
performance is real or overfit.
"""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
from pathlib import Path

import pytest

from src.hypotheses import HypothesisRegistry
from src.tools.autopilot_tool import LinkAutopilotBacktestTool, _get_hypothesis


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBE_TRADING_HYPOTHESES_PATH", str(tmp_path / "hypotheses.json"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    return tmp_path


def _make_hypothesis() -> str:
    registry = HypothesisRegistry()
    return registry.create(
        title="A-share momentum",
        thesis="Cross-sectional momentum persists in large caps.",
        universe="CSI 300",
        signal_definition="rank(returns_20d) top decile",
        data_sources=["akshare"],
    ).hypothesis_id


def _run_dir(base: Path) -> Path:
    d = base / "runs" / "autopilot_test"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_run_card_with_validation(run_dir: Path) -> dict:
    # Mirrors write_run_card's real shape: validation is a sibling of
    # metrics, not nested inside it.
    validation = {
        "walk_forward": {
            "consistency_rate": 0.2,
            "n_windows": 5,
            "profitable_windows": 1,
        }
    }
    card = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "metrics": {"sharpe": 1.9, "total_return": 0.42, "max_drawdown": -0.11},
        "validation": validation,
    }
    (run_dir / "run_card.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return validation


def test_link_autopilot_backtest_surfaces_validation_section(isolated_env: Path) -> None:
    hyp_id = _make_hypothesis()
    run_dir = _run_dir(isolated_env)
    validation = _write_run_card_with_validation(run_dir)

    result = json.loads(LinkAutopilotBacktestTool(roots=FileRoots.from_config(get_env_config().api)).execute(hypothesis_id=hyp_id, run_dir=str(run_dir)))

    assert result["status"] == "ok"
    assert (
        "validation" in result
    ), f"link_autopilot_backtest dropped run_card.json's validation section from its result: {result}"
    assert result["validation"] == validation

    reloaded = _get_hypothesis(hyp_id)
    card = reloaded.run_cards[0]
    assert "validation" in card, "the persisted hypothesis run_card also lost the validation section"
    assert card["validation"] == validation
