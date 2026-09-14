"""Tail-risk claims (VaR / ES / CVaR / 在险价值 / 风险价值) must be grounded.

Regression coverage for HKUDS/Vibe-Trading#1425: tail-risk vocabulary was
absent from the analysis gate entirely, so an invented VaR figure passed as
``valid=True`` without ever reaching the evidence check. Now the gate
classifies these claims as ``tail_risk``, compares them against kind-scoped
evidence (backtest artifacts or quantlib risk-tool output), and the
confidence frame in "VaR 95%: x" is masked so the 95% is never measured as
the claim's value.
"""

from pathlib import Path

import pytest

from src.agent.grounding import (
    _ANALYSIS_METRIC_RE,
    _TAIL_RISK_CONFIDENCE_RE,
    GroundingLedger,
    _metric_kind_for_text,
)

_measure = GroundingLedger._measure_numbers


@pytest.mark.parametrize(
    "text",
    [
        "VaR 95%: -1.57%",
        "VaR (99%) = 2.20%",
        "CVaR 2.1%",
        "ES 1.9%",
        "expected shortfall of 2.4%",
        "在险价值 VaR 为 1.57%",
        "95% 置信水平下 VaR 为 -1.57%",
        "风险价值 1.57%",
        "预期尾部损失为 2.1%",
    ],
)
def test_tail_risk_vocabulary_enters_the_gate(text):
    assert _ANALYSIS_METRIC_RE.search(text), f"not detected as a metric: {text!r}"
    assert _metric_kind_for_text(text) == "tail_risk", f"wrong kind for: {text!r}"


def test_es_futures_price_prose_is_not_tail_risk():
    """A bare ES with no attached figure is the E-mini ticker, not a metric."""
    text = "ES futures closed at 5,210 on the session"
    assert _metric_kind_for_text(text) is None or _ANALYSIS_METRIC_RE.search(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("VaR 95%: -1.57%", ["-1.57%"]),
        ("VaR (99%) = 2.20%", ["2.20%"]),
        ("95% 置信水平下 VaR 为 -1.57%", ["-1.57%"]),
        ("99% confidence level CVaR 2.1%", ["2.1%"]),
        ("ES 95%: -1.57%", ["-1.57%"]),
    ],
)
def test_confidence_figure_is_never_the_measurement(text, expected):
    """The confidence level frames the metric; it must not be measured."""
    assert _measure(text) == expected


def _ledger_with_tail_evidence(tmp_path: Path) -> GroundingLedger:
    """A completed backtest whose metrics.json carries VaR/CVaR figures."""
    (tmp_path / "metrics.json").write_text(
        '{"final_value": 834141.8, "total_return": -0.1659, '
        '"var_95": 0.0157, "cvar_95": 0.021}',
        encoding="utf-8",
    )
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测这个策略并给出风险指标")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result='{"status": "ok", "run_dir": "%s"}' % tmp_path,
        call_id="bt1",
        success=True,
    )
    return ledger


def test_grounded_tail_risk_claims_pass(tmp_path: Path):
    ledger = _ledger_with_tail_evidence(tmp_path)
    # evidence is a positive loss magnitude (0.0157); the claim writes it as a
    # signed percent (-1.57%) — both conventions must ground
    result = ledger.validate_final_answer(
        "回测完成。VaR 95%: -1.57%，95% 置信水平下 CVaR 为 -2.1%。"
    )
    assert all(i["code"] != "analysis_claim_unavailable" for i in result.issues)


def test_invented_tail_risk_figure_is_rejected(tmp_path: Path):
    ledger = _ledger_with_tail_evidence(tmp_path)
    result = ledger.validate_final_answer("回测完成。VaR 95%: -9.9%。")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in result.issues
    )


def test_tail_risk_claim_without_any_analysis_is_rejected(tmp_path: Path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="这个组合风险多大")
    result = ledger.validate_final_answer("该组合的 在险价值 VaR 为 1.57%。")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in result.issues
    )


def test_confidence_percentage_does_not_need_evidence(tmp_path: Path):
    """The 95 in "VaR 95%" is the frame, not a figure: no 95% evidence exists."""
    ledger = _ledger_with_tail_evidence(tmp_path)
    result = ledger.validate_final_answer("VaR 95%: -1.57%。")
    unsupported = [i for i in result.issues if i["code"] == "analysis_claim_unavailable"]
    assert unsupported == []


# Identity inside the family (#1427 review): measure (var vs es) and, when
# named, confidence must match the evidence. var_95 evidence is in the fixture.


def test_var95_evidence_grounds_var95_only(tmp_path: Path):
    ledger = _ledger_with_tail_evidence(tmp_path)
    ok = ledger.validate_final_answer("回测完成。VaR 95%: -1.57%。")
    assert all(i["code"] != "analysis_claim_unavailable" for i in ok.issues)


def test_var95_evidence_does_not_ground_var99(tmp_path: Path):
    ledger = _ledger_with_tail_evidence(tmp_path)
    result = ledger.validate_final_answer("回测完成。VaR 99%: -1.57%。")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in result.issues
    )


def test_var95_evidence_does_not_ground_cvar99(tmp_path: Path):
    # same number, different measure AND confidence: no ground
    ledger = _ledger_with_tail_evidence(tmp_path)
    result = ledger.validate_final_answer("回测完成。CVaR 99%: -1.57%。")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in result.issues
    )


def test_cvar95_evidence_grounds_es_and_cvar_but_not_var(tmp_path: Path):
    ledger = _ledger_with_tail_evidence(tmp_path)
    ok = ledger.validate_final_answer("回测完成。ES 95%: -2.1%，CVaR 95% 为 -2.1%。")
    assert all(i["code"] != "analysis_claim_unavailable" for i in ok.issues)
    bad = ledger.validate_final_answer("回测完成。VaR 95%: -2.1%。")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in bad.issues
    )


def test_confidence_free_evidence_grounds_any_confidence(tmp_path: Path):
    """quantlib's bare `var` names no confidence; it must not become unusable."""
    (tmp_path / "metrics.json").write_text('{"var": 0.0157}', encoding="utf-8")
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测并给出风险指标")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result='{"status": "ok", "run_dir": "%s"}' % tmp_path,
        call_id="bt1",
        success=True,
    )
    ok = ledger.validate_final_answer("回测完成。VaR 99%: -1.57%。")
    assert all(i["code"] != "analysis_claim_unavailable" for i in ok.issues)


# Natural-wording edge cases from the #1427 review: a metric's proper name
# must not read as forecast prose, `was`/`fue` separate the confidence from
# the value, and bare connectives may sit between metric and confidence.


def test_expected_shortfall_is_not_a_forecast_frame(tmp_path: Path):
    """"Expected Shortfall" is the metric's proper name, not forecast prose:
    an invented ES value must still hit the evidence check (#1427 review)."""
    ledger = _ledger_with_tail_evidence(tmp_path)
    result = ledger.validate_final_answer("Expected Shortfall 95% was -99.9%.")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in result.issues
    )


def test_generic_forecast_still_skips_the_gate(tmp_path: Path):
    """Bare `expected` stays a forecast frame outside "Expected Shortfall"."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="what do you expect")
    ok = ledger.validate_final_answer("We forecast an expected return of 4.2% next year.")
    assert all(i["code"] != "analysis_claim_unavailable" for i in ok.issues)


def test_past_tense_was_separates_confidence_from_value(tmp_path: Path):
    """"VaR 95% was -1.57%": `was` separates the confidence from the value;
    the 95% must not leak into the measurement list (#1427 review)."""
    ledger = _ledger_with_tail_evidence(tmp_path)
    ok = ledger.validate_final_answer("回测完成。VaR 95% was -1.57%.")
    assert all(i["code"] != "analysis_claim_unavailable" for i in ok.issues)


def test_descriptive_words_between_metric_and_confidence(tmp_path: Path):
    """Bare connectives between the metric and its confidence must not break
    the identity link (#1427 review)."""
    ledger = _ledger_with_tail_evidence(tmp_path)
    ok = ledger.validate_final_answer("回测完成。historical daily VaR at 95% was -1.57%.")
    assert all(i["code"] != "analysis_claim_unavailable" for i in ok.issues)


def test_spanish_confidence_frame_is_masked():
    """Regex level: the Spanish confidence frame is consumed as the frame,
    not measured; the decimal-comma value parse rides #1419 (#1427 review)."""
    from src.agent.grounding import (
        _TAIL_RISK_CONFIDENCE_RE,
        _TAIL_RISK_CONFIDENCE_VALUE_RE,
    )

    text = "El VaR histórico diario al 95% fue 1,57%."
    assert _TAIL_RISK_CONFIDENCE_RE.search(text), f"confidence not masked: {text!r}"
    match = _TAIL_RISK_CONFIDENCE_VALUE_RE.search(text)
    assert match, f"confidence not extracted: {text!r}"
    assert float(match.group(1) or match.group(2)) == 95.0


def _ledger_with_var_and_drawdown(tmp_path: Path, *, drawdown: bool) -> GroundingLedger:
    """Backtest evidence carrying VaR, optionally with a max drawdown."""
    metrics = '{"final_value": 834141.8, "var_95": 0.0157'
    if drawdown:
        metrics += ', "max_drawdown": -0.05'
    metrics += "}"
    (tmp_path / "metrics.json").write_text(metrics, encoding="utf-8")
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测这个策略并给出风险指标")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result='{"status": "ok", "run_dir": "%s"}' % tmp_path,
        call_id="bt1",
        success=True,
    )
    return ledger


def test_mixed_tail_risk_and_drawdown_clause_grounds_each_by_its_kind(tmp_path: Path):
    """#1427 review: a mixed clause measures each figure against its own metric.

    Before the measurement function unified, the drawdown figure in this
    clause was checked against the tail-risk evidence and rejected.
    """
    ledger = _ledger_with_var_and_drawdown(tmp_path, drawdown=True)
    result = ledger.validate_final_answer("VaR 95%: -1.57% and max drawdown was -5%.")
    assert all(i["code"] != "analysis_claim_unavailable" for i in result.issues)


def test_mixed_clause_drawdown_figure_rejects_without_drawdown_evidence(tmp_path: Path):
    ledger = _ledger_with_var_and_drawdown(tmp_path, drawdown=False)
    result = ledger.validate_final_answer("VaR 95%: -1.57% and max drawdown was -5%.")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "drawdown"
        for i in result.issues
    )


def test_mixed_clause_tail_figure_rejects_without_tail_evidence(tmp_path: Path):
    """The mirror: only drawdown evidence present, the VaR figure rejects."""
    (tmp_path / "metrics.json").write_text(
        '{"final_value": 834141.8, "max_drawdown": -0.05}', encoding="utf-8"
    )
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测这个策略并给出风险指标")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result='{"status": "ok", "run_dir": "%s"}' % tmp_path,
        call_id="bt1",
        success=True,
    )
    result = ledger.validate_final_answer("VaR 95%: -1.57% and max drawdown was -5%.")
    assert any(
        i["code"] == "analysis_claim_unavailable" and i.get("kind") == "tail_risk"
        for i in result.issues
    )
