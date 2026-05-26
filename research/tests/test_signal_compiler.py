"""Unit tests for research/lib/signal_compiler.py (Task 3).

Coverage:
  (a) compile_strategy(valid_spec) → ast.parse() doesn't raise
  (b) _validate_source_string passes (no exception)
  (c) rendered source contains "class SignalEngine" and "def generate"
  (d) "funding_zscore_30d <= -1.5 persist 2/3" → ".rolling(3).sum() >= 2"
  (e) two conditions in entry_long joined with "&"
  (f) each ExitRule type translates correctly
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup — mirror what signal_compiler.py does so tests can run from any cwd
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_RESEARCH_DIR = _HERE.parents[1]          # research/
_REPO_ROOT = _RESEARCH_DIR.parent         # repo root
_AGENT_DIR = _REPO_ROOT / "agent"

for _p in (str(_RESEARCH_DIR), str(_REPO_ROOT), str(_AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dashboard.server.schemas import (
    EntryBlock,
    IndicatorSpec,
    StrategySpec,
    _ExitTimeBased,
    _ExitTakeProfit,
    _ExitStopLoss,
    _ExitSignalInvalidation,
)
from lib.signal_compiler import (
    _render_condition,
    _render_entry_block,
    _render_exit_state_machine,
    _render_indicator_load,
    _validate_source_string,
    compile_strategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_spec(
    entry_long_conds=None,
    entry_short_conds=None,
    exit_rules=None,
    smoothing="none",
):
    """Build a minimal valid StrategySpec."""
    indicators = {
        "funding_rate": IndicatorSpec(source="stage1:funding_rate", smoothing=smoothing),
        "basis": IndicatorSpec(source="stage1:basis", smoothing="none"),
    }

    entry_long = None
    if entry_long_conds is not None:
        entry_long = EntryBlock(
            description="Long entry",
            conditions=entry_long_conds,
        )

    entry_short = None
    if entry_short_conds is not None:
        entry_short = EntryBlock(
            description="Short entry",
            conditions=entry_short_conds,
        )

    if exit_rules is None:
        exit_rules = [_ExitTimeBased(condition="time_based", max_hold_hours=48)]

    return StrategySpec(
        name="test_strategy",
        archetype="contrarian",
        symbol="ETH-USDT-SWAP",
        timeframe_signal="1H",
        indicators=indicators,
        entry_long=entry_long,
        entry_short=entry_short,
        exit_rules=exit_rules,
    )


@pytest.fixture
def basic_spec():
    return _make_spec(
        entry_long_conds=["funding_rate_percentile_90d <= 20.0"],
        entry_short_conds=["funding_rate_percentile_90d >= 80.0"],
        exit_rules=[_ExitTimeBased(condition="time_based", max_hold_hours=48)],
    )


# ---------------------------------------------------------------------------
# (a) compile_strategy — ast.parse succeeds
# ---------------------------------------------------------------------------

def test_compile_strategy_parses_cleanly(basic_spec):
    """Compiled source must be valid Python (ast.parse doesn't raise)."""
    source = compile_strategy(basic_spec, yaml_hash="deadbeef")
    tree = ast.parse(source)  # should not raise
    assert tree is not None


# ---------------------------------------------------------------------------
# (b) _validate_source_string passes
# ---------------------------------------------------------------------------

def test_validate_source_string_passes(basic_spec):
    """Compiled source must pass the backtest AST scrubber."""
    source = compile_strategy(basic_spec, yaml_hash="abc123")
    # Should not raise
    _validate_source_string(source, label="test")


# ---------------------------------------------------------------------------
# (c) rendered source structure
# ---------------------------------------------------------------------------

def test_rendered_source_contains_class_and_method(basic_spec):
    source = compile_strategy(basic_spec)
    assert "class SignalEngine" in source
    assert "def generate" in source


def test_rendered_source_contains_yaml_hash():
    spec = _make_spec(
        entry_long_conds=["funding_rate_percentile_90d <= 20.0"],
    )
    source = compile_strategy(spec, yaml_hash="myhash123")
    assert "# yaml-hash: myhash123" in source


# ---------------------------------------------------------------------------
# (d) zscore condition with persist suffix
# ---------------------------------------------------------------------------

def test_zscore_persist_condition():
    """'funding_zscore_30d <= -1.5 persist 2/3' must produce .rolling(3).sum() >= 2"""
    cond = "funding_zscore_30d <= -1.5 persist 2/3"
    rendered = _render_condition(cond)
    assert ".rolling(3).sum() >= 2" in rendered
    assert "rolling(30*24" in rendered
    assert "-1.5" in rendered


def test_zscore_persist_in_compiled_output():
    # Convention: indicator key "funding_rate" → condition "funding_rate_zscore_30d"
    spec = _make_spec(
        entry_long_conds=["funding_rate_zscore_30d <= -1.5 persist 2/3"],
    )
    source = compile_strategy(spec)
    assert ".rolling(3).sum() >= 2" in source


# ---------------------------------------------------------------------------
# (e) two conditions in entry_long joined with "&"
# ---------------------------------------------------------------------------

def test_two_conditions_joined_with_and():
    spec = _make_spec(
        entry_long_conds=[
            "funding_rate_percentile_90d <= 20.0",
            "basis_percentile_90d <= 20.0",
        ],
    )
    source = compile_strategy(spec)
    # Find the entry_long line
    entry_line = next(
        line for line in source.splitlines() if "entry_long" in line and "=" in line
    )
    assert " & " in entry_line


# ---------------------------------------------------------------------------
# (f) ExitRule types translate correctly
# ---------------------------------------------------------------------------

def test_exit_time_based():
    rules = [_ExitTimeBased(condition="time_based", max_hold_hours=72)]
    code = _render_exit_state_machine(rules)
    assert "bars_held >= 72" in code


def test_exit_take_profit():
    rules = [_ExitTakeProfit(condition="take_profit_pct", value=5.0)]
    code = _render_exit_state_machine(rules)
    assert "pnl_pct >= 5.0 / 100" in code


def test_exit_stop_loss():
    rules = [_ExitStopLoss(condition="stop_loss_pct", value=3.0)]
    code = _render_exit_state_machine(rules)
    assert "pnl_pct <= -3.0 / 100" in code


def test_exit_signal_invalidation():
    rules = [
        _ExitSignalInvalidation(
            condition="signal_invalidation",
            expression="funding_rate_percentile_90d between 40,60",
        )
    ]
    code = _render_exit_state_machine(rules)
    assert "funding_rate" in code
    # The pre-computed series is referenced as _inv_pct_0.iloc[bar_i]
    assert "_inv_pct_0" in code
    assert "40 <=" in code
    assert "60" in code


def test_all_exit_rules_in_compiled_output():
    """All four exit rule types survive the full compile pipeline."""
    spec = _make_spec(
        entry_long_conds=["funding_rate_percentile_90d <= 20.0"],
        exit_rules=[
            _ExitTimeBased(condition="time_based", max_hold_hours=24),
            _ExitTakeProfit(condition="take_profit_pct", value=10.0),
            _ExitStopLoss(condition="stop_loss_pct", value=5.0),
            _ExitSignalInvalidation(
                condition="signal_invalidation",
                expression="funding_rate_percentile_90d between 40,60",
            ),
        ],
    )
    source = compile_strategy(spec)
    assert "bars_held >= 24" in source
    assert "pnl_pct >= 10.0 / 100" in source
    assert "pnl_pct <= -5.0 / 100" in source
    assert "_inv_pct" in source


# ---------------------------------------------------------------------------
# Indicator rendering tests
# ---------------------------------------------------------------------------

def test_indicator_load_no_smoothing():
    spec = IndicatorSpec(source="stage1:funding_rate", smoothing="none")
    code = _render_indicator_load("funding_rate", spec)
    assert 'funding_rate = _factors["funding_rate"]' in code
    # No extra line for smoothing
    assert code.count("\n") == 0


def test_indicator_load_sma():
    spec = IndicatorSpec(source="stage1:funding_rate", smoothing="sma_3")
    code = _render_indicator_load("funding_rate", spec)
    assert ".rolling(3, min_periods=1).mean()" in code


def test_indicator_load_ema():
    spec = IndicatorSpec(source="stage1:basis", smoothing="ema_12")
    code = _render_indicator_load("basis", spec)
    assert ".ewm(span=12, adjust=False).mean()" in code


# ---------------------------------------------------------------------------
# Entry block edge cases
# ---------------------------------------------------------------------------

def test_entry_block_none_produces_false_series():
    code = _render_entry_block("long", None)
    assert "pd.Series(False, index=ohlcv.index)" in code
    assert "entry_long" in code


def test_percentile_condition_rendering():
    cond = "funding_rate_percentile_90d <= 20.0"
    rendered = _render_condition(cond)
    assert "rolling(90*24" in rendered
    assert "rank(pct=True)*100" in rendered
    assert "<= 20.0" in rendered


def test_raw_condition_rendering():
    cond = "funding_rate <= 0.01"
    rendered = _render_condition(cond)
    assert "(funding_rate <= 0.01)" in rendered
