"""Tests for the ``financial_rigor`` agent tool.

Covers the pure core routines (exact decimal, safe arithmetic, valuation
math, cross-validation, Benford, three-scenario), the tool's JSON-Schema
contract, ``execute`` happy/error paths, calc injection rejection, and that
the tool is auto-discovered into the default registry.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from src.tools import build_registry
from src.tools.financial_rigor_tool import (
    FinancialRigorTool,
    _exact,
    _fmt,
    _safe_arith,
    benford_check,
    cross_validate,
    exact_calc,
    three_scenario_valuation,
    verify_market_cap,
    verify_valuation,
)

# ── helpers ───────────────────────────────────────────────────────────────


def test_exact_avoids_float_drift() -> None:
    # float 0.1 + 0.2 carries binary noise; exact decimal does not.
    assert _exact(0.1) + _exact(0.2) == _exact("0.3")
    # str-roundtrip keeps the literal value intact.
    assert _exact("0.1") == _exact(0.1)


def test_fmt_suffixes() -> None:
    assert _fmt(999) == "999.00"
    assert _fmt(1500) == "1.50K"
    assert _fmt(2_500_000) == "2.50M"
    assert _fmt(4_646_100_000_000) == "4.65T"


# ── _safe_arith ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("expr,expected", [
    ("510 * 9.11e9", 4_646_100_000_000.0),
    ("1 + 2 * 3", 7.0),
    ("(1 + 2) * 3", 9.0),
    ("10 / 4", 2.5),
    ("-5 + 3", -2.0),
])
def test_safe_arith_evaluates(expr: str, expected: float) -> None:
    assert float(_safe_arith(expr)) == expected


@pytest.mark.parametrize("evil", [
    "abc",                  # bare name
    "__import__('os')",     # function call
    "os.system('x')",       # attribute + call
    "1 + 2; print(3)",      # statements (not a single expression)
    "'abc'",                # string constant, not numeric
    "1.2.3",                # malformed
])
def test_safe_arith_rejects_disallowed(evil: str) -> None:
    with pytest.raises(ValueError):
        _safe_arith(evil)


# ── verify_market_cap ─────────────────────────────────────────────────────


def test_market_cap_verdict_thresholds() -> None:
    # calculated = 510 * 9.11e9 = 4.6461e12
    assert verify_market_cap(510, 9.11e9, 4.65e12)["verdict"] == "pass"   # ~0.08%
    assert verify_market_cap(510, 9.11e9, 4.50e12)["verdict"] == "warn"   # ~3.2%
    assert verify_market_cap(510, 9.11e9, 4.00e12)["verdict"] == "fail"   # ~14%


def test_market_cap_fields() -> None:
    out = verify_market_cap(510, 9.11e9, 4.65e12, currency="HKD")
    assert out["currency"] == "HKD"
    assert out["calculated_market_cap"] == pytest.approx(4.6461e12)
    assert out["calculated_market_cap_display"] == "4.65T"
    assert out["deviation_pct"] == pytest.approx(0.0839, abs=1e-3)


# ── verify_valuation ──────────────────────────────────────────────────────


def test_valuation_metrics_exact() -> None:
    metrics = verify_valuation(price=510, eps=23.5, bvps=120)["metrics"]
    assert metrics["PE"] == pytest.approx(21.7021, rel=1e-4)
    assert metrics["PB"] == pytest.approx(4.25)
    assert metrics["ROE_pct"] == pytest.approx(19.5833, rel=1e-4)
    assert metrics["earnings_yield_pct"] == pytest.approx(4.6078, rel=1e-4)


def test_valuation_skips_zero_and_missing_inputs() -> None:
    assert verify_valuation(price=100, eps=0, bvps=None)["metrics"] == {}


# ── cross_validate ────────────────────────────────────────────────────────


def test_cross_validate_marks_outlier() -> None:
    out = cross_validate("revenue", {"a": 100, "b": 101, "c": 200}, tolerance_pct=2.0)
    # median of {100,101,200} is 101; 'c' is ~98% off -> inconsistent.
    assert out["all_consistent"] is False
    by_src = {s["source"]: s for s in out["per_source"]}
    assert by_src["c"]["consistent"] is False
    assert by_src["a"]["consistent"] is True


def test_cross_validate_consensus_is_median() -> None:
    out = cross_validate("rev", {"a": 7500, "b": 7518, "c": 7520})
    assert out["consensus"] == 7518
    assert out["all_consistent"] is True


# ── benford_check ─────────────────────────────────────────────────────────


def test_benford_unreliable_below_50_samples() -> None:
    out = benford_check([123, 456, 789])
    assert out["reliable"] is False
    assert out["sample_size"] == 3


def _benford_conforming_sample(n: int = 1000) -> list[int]:
    """Build a list whose leading-digit distribution tracks Benford's law."""
    expected = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
    out: list[int] = []
    for d in range(1, 10):
        for _ in range(round(n * expected[d])):
            out.append(d * 1000 + d)  # leading digit is d
    return out


def test_benford_conforming_sample_passes() -> None:
    out = benford_check(_benford_conforming_sample(1000))
    assert out["reliable"] is True
    assert out["is_conforming"] is True
    assert out["mad"] < 0.015
    assert len(out["distribution"]) == 9


def test_benford_all_same_leading_digit_fails() -> None:
    out = benford_check([1000 + i for i in range(100)])  # every value starts with 1
    assert out["reliable"] is True
    assert out["is_conforming"] is False


# ── exact_calc ────────────────────────────────────────────────────────────


def test_exact_calc_returns_exact_string() -> None:
    out = exact_calc("0.1 + 0.2")
    assert out["result"] == pytest.approx(0.3)
    assert out["result_exact"] == "0.3"


def test_exact_calc_raises_on_disallowed() -> None:
    with pytest.raises(ValueError):
        exact_calc("abc")


# ── three_scenario_valuation ──────────────────────────────────────────────


def test_three_scenario_future_eps_compounding() -> None:
    out = three_scenario_valuation(
        current_price=510, current_eps=23.5, shares_billion=9.11,
        growth_optimistic=0.15, growth_neutral=0.08, growth_pessimistic=0.0,
        pe_optimistic=25, pe_neutral=20, pe_pessimistic=15, years=3,
    )
    bull = next(s for s in out["scenarios"] if s["scenario"] == "bull")
    assert bull["future_eps"] == pytest.approx(23.5 * 1.15 ** 3)
    assert bull["target_price"] == pytest.approx(23.5 * 1.15 ** 3 * 25)
    bear = next(s for s in out["scenarios"] if s["scenario"] == "bear")
    assert bear["future_eps"] == 23.5  # 0% growth leaves EPS unchanged
    assert bear["upside_pct"] < 0  # bear case is below current price


def test_three_scenario_normalizes_percent_growth() -> None:
    # LLMs often pass 15 instead of 0.15; |g| > 1 is treated as a percent.
    out = three_scenario_valuation(
        current_price=510, current_eps=23.5, shares_billion=9.11,
        growth_optimistic=15, growth_neutral=8, growth_pessimistic=0,
        pe_optimistic=25, pe_neutral=20, pe_pessimistic=15, years=3,
    )
    bull = next(s for s in out["scenarios"] if s["scenario"] == "bull")
    assert bull["future_eps"] == pytest.approx(23.5 * 1.15 ** 3)  # 15 -> 0.15
    assert bull["annual_growth"] == pytest.approx(0.15)
    assert "bull" in out["growth_normalized_from_percent"]
    # bear g=0 is not normalized (|0| is not > 1).
    bear = next(s for s in out["scenarios"] if s["scenario"] == "bear")
    assert bear["future_eps"] == 23.5
    assert "bear" not in out.get("growth_normalized_from_percent", [])


# ── tool contract ─────────────────────────────────────────────────────────


def test_tool_metadata() -> None:
    tool = FinancialRigorTool()
    assert tool.name == "financial_rigor"
    assert tool.is_readonly is True
    assert tool.repeatable is True
    assert tool.parameters["required"] == ["command"]
    cmds = set(tool.parameters["properties"]["command"]["enum"])
    assert cmds == {"verify_market_cap", "verify_valuation", "cross_validate",
                    "benford", "calc", "three_scenario"}


def test_tool_is_auto_discovered() -> None:
    registry = build_registry()
    assert "financial_rigor" in registry.tool_names


# ── execute ───────────────────────────────────────────────────────────────


def _run(**kwargs: Any) -> dict[str, Any]:
    return json.loads(FinancialRigorTool().execute(**kwargs))


def test_execute_verify_valuation_happy() -> None:
    env = _run(command="verify_valuation", price=510, eps=23.5, bvps=120)
    assert env["status"] == "ok"
    assert env["metrics"]["PE"] == pytest.approx(21.7021, rel=1e-4)


def test_execute_calc_rejects_injection_as_error() -> None:
    env = _run(command="calc", expr="__import__('os')")
    assert env["status"] == "error"
    assert "disallowed" in env["error"]


def test_execute_missing_required_arg_is_error() -> None:
    env = _run(command="verify_market_cap", price=510)
    assert env["status"] == "error"


def test_execute_unknown_command_is_error() -> None:
    env = _run(command="bogus")
    assert env["status"] == "error"
    assert "unknown command" in env["error"]


def test_execute_benford_small_sample_is_not_reliable() -> None:
    env = _run(command="benford", values=[1, 2, 3])
    assert env["status"] == "ok"
    assert env["reliable"] is False


def test_execute_three_scenario_validates_growth_shape() -> None:
    env = _run(
        command="three_scenario", price=510, eps=23.5, shares=9.11,
        growth=[0.1, 0.2], pe=[25, 20, 15],  # growth has only 2 entries
    )
    assert env["status"] == "error"
