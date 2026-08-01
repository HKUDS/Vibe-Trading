"""Shared fixtures for strategy_registry tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.skills.strategy_registry.registry import StrategyRegistry
from src.skills.strategy_registry.registry.models import Scenario, StrategyEntry

# ---------------------------------------------------------------------------
# Sample YAML content (mirrors real seed file structure)
# ---------------------------------------------------------------------------

SAMPLE_FFSCORE_YAML = """\
strategy_id: quantsplaybook_ffscore
name: HuaTai F-Score + Low PB Value Strategy
source: builtin
area: factor
description: F-Score value strategy with low PB filter.
effective_scenarios:
  - regime_agnostic
  - value_rotation
  - bear_market_defense
failure_scenarios:
  - momentum_continuation
tuning_hints:
  - 'fscore_threshold: 7'
  - 'pb_percentile: 0.3'
benchmark_results:
  period: 2018-01-01 to 2026-06-30
  total_return: 601.56
  sharpe: 1.151
  max_drawdown: -21.71
implementation:
  skill: strategy-generate
  factor_backend: factor-research
"""

SAMPLE_RELSTRENGTH_YAML = """\
strategy_id: quantsplaybook_relstrength
name: Relative Strength Unidirectional Volatility
source: builtin
area: timing
description: RSUW volatility timing strategy.
effective_scenarios:
  - bear_market_defense
  - high_volatility_regime
failure_scenarios:
  - bull_market_momentum
  - momentum_continuation
tuning_hints:
  - 'window: 20'
  - 'threshold: 1.2'
benchmark_results:
  period: 2015-02-02 to 2026-06-04
  total_return: 30.33
  sharpe: 0.014
  max_drawdown: -33.94
implementation:
  skill: strategy-generate
"""

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_seed_dir(tmp_path: Path) -> Path:
    """Create a temporary seed directory with 2 valid YAML strategy files.

    Returns the ``Path`` to the seed directory.
    """
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()

    (seed_dir / "quantsplaybook_ffscore.yaml").write_text(SAMPLE_FFSCORE_YAML, encoding="utf-8")
    (seed_dir / "quantsplaybook_relstrength.yaml").write_text(SAMPLE_RELSTRENGTH_YAML, encoding="utf-8")

    return seed_dir


@pytest.fixture
def sample_entry() -> StrategyEntry:
    """Return a valid StrategyEntry for the ffscore strategy."""
    return StrategyEntry(
        strategy_id="quantsplaybook_ffscore",
        name="HuaTai F-Score + Low PB Value Strategy",
        source="builtin",
        area="factor",
        description="F-Score value strategy with low PB filter.",
        effective_scenarios=[
            Scenario.REGIME_AGNOSTIC,
            Scenario.VALUE_ROTATION,
            Scenario.BEAR_MARKET_DEFENSE,
        ],
        failure_scenarios=[Scenario.MOMENTUM_CONTINUATION],
        tuning_hints=["fscore_threshold: 7", "pb_percentile: 0.3"],
        benchmark_results={
            "period": "2018-01-01 to 2026-06-30",
            "total_return": 601.56,
            "sharpe": 1.151,
            "max_drawdown": -21.71,
        },
        implementation={"skill": "strategy-generate", "factor_backend": "factor-research"},
    )


@pytest.fixture
def entry_dict() -> dict:
    """Return a plain dict that maps to a valid StrategyEntry."""
    return {
        "strategy_id": "test_strategy_01",
        "name": "Test Strategy",
        "source": "builtin",
        "area": "timing",
        "description": "A test strategy.",
        "effective_scenarios": ["bear_market_defense"],
        "failure_scenarios": [],
        "tuning_hints": [],
        "benchmark_results": None,
        "implementation": None,
    }


@pytest.fixture
def isolated_registry() -> None:
    """Reset the registry and mock SDM entries to return empty lists.

    This prevents SDM artifacts from leaking into tests that need
    a clean, deterministic state.  ``_loaded`` is forced on so the bundled
    seed directory is not auto-loaded behind the test's back.
    """
    StrategyRegistry._builtin = {}
    StrategyRegistry._loaded = True
    with patch.object(StrategyRegistry, "_sdm_entries", return_value=[]), \
         patch.object(StrategyRegistry, "_sdm_is_available", return_value=False):
        yield
    StrategyRegistry._builtin = {}
    StrategyRegistry._loaded = False
