"""Security tests for Shadow Account code generation."""

from __future__ import annotations

import ast
import uuid

import numpy as np
import pandas as pd
import pytest

from backtest.runner import _load_module_from_file
from src.shadow_account.codegen import render_signal_engine, validate_generated
from src.shadow_account.models import ShadowProfile, ShadowRule


def _malicious_profile() -> ShadowProfile:
    """Build a profile whose dynamic strings look like Python code."""
    rule_id = 'R1"""\nINJECTED_RULE_ID = "boom"\n"""'
    market = 'china_a"""\nINJECTED_MARKET = "boom"\n"""'
    return ShadowProfile(
        shadow_id='shadow_abc"""\nINJECTED_SHADOW_ID = "boom"\n"""',
        created_at="2026-05-05T00:00:00Z",
        journal_hash="deadbeef",
        source_market="china_a",
        profitable_roundtrips=7,
        total_roundtrips=11,
        date_range=(
            '2026-01-01"; INJECTED_START = "boom"; #',
            '2026-01-31\nINJECTED_END = "boom"',
        ),
        profile_text="security regression profile",
        rules=(
            ShadowRule(
                rule_id=rule_id,
                human_text="security regression rule",
                entry_condition={
                    "market": market,
                    "entry_hour": {"min": 9, "max": 15},
                },
                exit_condition={},
                holding_days_range=(2, 4),
                support_count=3,
                coverage_rate=0.42,
                sample_trades=("600519.SH@2026-01-05",),
                weight=0.75,
            ),
        ),
        preferred_markets=(
            'china_a"; INJECTED_PREFERRED = "boom"; #',
            'us\nINJECTED_PREFERRED_2 = "boom"',
        ),
        typical_holding_days=(2.0, 4.0),
    )


@pytest.mark.unit
def test_render_signal_engine_escapes_python_literals_for_dynamic_values() -> None:
    """LLM/user strings must stay data, never executable generated code."""
    profile = _malicious_profile()
    source = render_signal_engine(profile)

    tree = ast.parse(source)
    ok, err = validate_generated(source)
    assert ok, f"generated source failed validation: {err}"

    stored_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    assert not any(name.startswith("INJECTED_") for name in stored_names)

    namespace: dict[str, object] = {"__name__": "shadow_codegen_security_test"}
    exec(compile(source, "<generated-signal-engine>", "exec"), namespace)

    assert not any(name.startswith("INJECTED_") for name in namespace)
    assert namespace["SHADOW_ID"] == profile.shadow_id
    assert namespace["PREFERRED_MARKETS"] == list(profile.preferred_markets)

    rules = namespace["RULES"]
    assert isinstance(rules, list)
    assert rules[0]["rule_id"] == profile.rules[0].rule_id
    assert rules[0]["market"] == profile.rules[0].entry_condition["market"]


def _conditional_entry_profile() -> ShadowProfile:
    """Profile with RSI + negative prior-return bounds (issue #985 shape)."""
    return ShadowProfile(
        shadow_id="shadow_entry985",
        created_at="2026-08-06T00:00:00Z",
        journal_hash="deadbeef",
        source_market="china_a",
        profitable_roundtrips=5,
        total_roundtrips=8,
        date_range=("2026-01-01", "2026-06-30"),
        profile_text="conditional entry regression profile",
        rules=(
            ShadowRule(
                rule_id="R1",
                human_text="buy low RSI after a pullback, hold 3 days",
                entry_condition={
                    "market": "china_a",
                    "entry_hour": {"min": 9, "max": 15},
                    "entry_rsi14": {"min": 20.0, "max": 45.0},
                    "prior_5d_return": {"min": -0.08, "max": 0.02},
                },
                exit_condition={},
                holding_days_range=(3, 3),
                support_count=4,
                coverage_rate=0.5,
                sample_trades=("600519.SH@2026-02-03",),
                weight=1.0,
            ),
        ),
        preferred_markets=("china_a",),
        typical_holding_days=(3.0, 3.0),
    )


@pytest.mark.unit
def test_rendered_signal_engine_passes_runner_validation(tmp_path) -> None:
    """Issue #985: the generated engine must clear the backtest runner's
    strict AST validator, not just codegen's own looser shape check.

    Two historical rejection paths are covered together:
    * ``@staticmethod`` decorators on the helper methods (the runner rejects
      every decorator), and
    * negative mined thresholds (``prior_5d_return_min = -0.08``) in the
      top-level ``RULES`` literal, which parse as ``UnaryOp(USub)``.
    """
    source = render_signal_engine(_conditional_entry_profile())
    ok, err = validate_generated(source)
    assert ok, f"generated source failed codegen validation: {err}"

    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(source, encoding="utf-8")

    module = _load_module_from_file(signal_file, f"signal_engine_{uuid.uuid4().hex}")

    engine = module.SignalEngine()
    rng = np.random.default_rng(7)
    idx = pd.date_range("2026-01-05", periods=120, freq="B")
    close = pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(-0.002, 0.012, len(idx)))), index=idx
    )
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=idx,
    )

    signals = engine.generate({"600519.SH": df})

    assert set(signals) == {"600519.SH"}
    series = signals["600519.SH"]
    assert len(series) == len(idx)
    assert (series > 0).any(), "conditional entry should fire on the pullback"
