"""Data operands cannot masquerade as undeclared multiplicative constants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger


def _ledger(tmp_path: Path, values: tuple[float, ...]) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the calculation")
    ledger.ingest_tool_result(
        tool_name="measure",
        arguments={},
        result=json.dumps({f"amount_{i}": value for i, value in enumerate(values)}),
        call_id="measure",
        success=True,
    )
    return ledger


@pytest.mark.parametrize(
    ("values", "formula", "result"),
    [
        ((125,), "125 / 10000", "1.25%"),
        ((10000,), "125 / 10000", "1.25%"),
        ((125, 75), "(125 + 75) / 10000", "2.00%"),
        ((125,), "125 * 0.0001", "1.25%"),
    ],
)
def test_missing_data_operand_is_refused(tmp_path, values, formula, result):
    ledger = _ledger(tmp_path, values)
    verdict = ledger.validate_final_answer(
        f"Result: {result}.\n```figures\n{result} | derived | {formula} | measure\n```"
    )
    assert not verdict.valid
    assert verdict.issues[0]["reason"] == "operand_not_observed"


@pytest.mark.parametrize(
    ("formula", "result", "parameters"),
    [
        ("125 * 0.97", "121.25", (("0.97", "discount factor"),)),
        ("125 * 25%", "31.25", (("25%", "chosen weight"),)),
        ("125 * 25%", "31.25", (("25%", "w"),)),
        ("125 * 25%", "31.25", (("25%", "الوزن المختار"),)),
        ("125 * (1 - 3%)", "121.25", (("3%", "discount rate"),)),
        ("(125 + 75) / 2", "100.00", (("2", "sample count"),)),
    ],
)
def test_visible_declared_parameters_preserve_ordinary_arithmetic(
    tmp_path, formula, result, parameters
):
    ledger = _ledger(tmp_path, (125, 75))
    prose = "\n".join(f"{label}: {value}." for value, label in parameters)
    rows = "\n".join(f"{value} | count | {label}" for value, label in parameters)
    verdict = ledger.validate_final_answer(
        f"{prose}\nResult: {result}.\n```figures\n"
        f"{result} | derived | {formula} | measure\n{rows}\n```"
    )
    assert verdict.valid, verdict.issues


def test_fully_observed_ratio_needs_no_parameter_declaration(tmp_path):
    verdict = _ledger(tmp_path, (125, 10000)).validate_final_answer(
        "Ratio: 1.25%.\n```figures\n1.25% | derived | 125 / 10000 | measure\n```"
    )
    assert verdict.valid, verdict.issues


@pytest.mark.parametrize(
    "prose",
    ["", "Unrelated number: 10000.", "```text\nChosen base: 10000.\n```", "Chosen base: $10000."],
)
def test_hidden_or_mislabelled_parameter_cannot_ground_a_denominator(tmp_path, prose):
    verdict = _ledger(tmp_path, (125,)).validate_final_answer(
        f"{prose}\nRatio: 1.25%.\n```figures\n"
        "1.25% | derived | 125 / 10000 | measure\n10000 | count | chosen base\n```"
    )
    assert not verdict.valid
    assert any(issue.get("reason") == "operand_not_observed" for issue in verdict.issues)


def test_a_short_parameter_label_must_not_match_inside_an_unrelated_word(tmp_path):
    verdict = _ledger(tmp_path, (125,)).validate_final_answer(
        "Unknown number: 10000.\nRatio: 1.25%.\n```figures\n"
        "1.25% | derived | 125 / 10000 | measure\n10000 | count | n\n```"
    )
    assert not verdict.valid
    assert any(issue.get("reason") == "operand_not_observed" for issue in verdict.issues)


@pytest.mark.parametrize("formula", ["(125 + 75) / 10000 * 100", "((125 + 75) / 10000) × 100.0"])
def test_explicit_percent_conversion_keeps_data_operands_grounded(tmp_path, formula):
    verdict = _ledger(tmp_path, (125, 75, 10000)).validate_final_answer(
        f"Ratio: 2.00%.\n```figures\n2.00% | derived | {formula} | measure\n```"
    )
    assert verdict.valid, verdict.issues


def test_magnitude_suffix_expands_rather_than_mistranslating():
    # "345,624,709.24元 ÷ 1亿" is a unit conversion to 1e8. The magnitude suffix
    # must expand, not be dropped as vocabulary: dropping it made the run read
    # as "÷ 1" and report a derived result eight orders of magnitude off. The
    # currency mark trails the dividend and is not arithmetic.
    from src.agent.grounding.policies import _evaluate_formula

    evaluated = _evaluate_formula("345,624,709.24元 ÷ 1亿")
    assert evaluated is not None
    result, operands, _ = evaluated
    assert result == pytest.approx(345624709.24 / 1e8)
    assert 1e8 in operands


@pytest.mark.parametrize("values", [(125,), (10000,), (125, 75), (75, 10000)])
def test_percent_conversion_does_not_supply_missing_data(tmp_path, values):
    verdict = _ledger(tmp_path, values).validate_final_answer(
        "Ratio: 2.00%.\n```figures\n2.00% | derived | (125 + 75) / 10000 * 100 | measure\n```"
    )
    assert not verdict.valid
    assert verdict.issues[0]["reason"] in {"operand_not_observed", "additive_operand_not_observed"}


@pytest.mark.parametrize("figure", ["1.99%", "200.00%", "-2.00%"])
def test_explicit_percent_conversion_does_not_widen_value_or_sign_matching(tmp_path, figure):
    verdict = _ledger(tmp_path, (125, 75, 10000)).validate_final_answer(
        f"Ratio: {figure}.\n```figures\n{figure} | derived | (125 + 75) / 10000 * 100 | measure\n```"
    )
    assert not verdict.valid
    assert verdict.issues[0]["reason"] == "derivation_result_mismatch"


def test_percent_conversion_cannot_exempt_an_inner_hundred(tmp_path):
    verdict = _ledger(tmp_path, (125,)).validate_final_answer(
        "Ratio: 125.00%.\n```figures\n125.00% | derived | 125 / 100 * 100 | measure\n```"
    )
    assert not verdict.valid
    assert verdict.issues[0]["reason"] == "operand_not_observed"


def test_percent_conversion_can_convert_one_observed_fraction(tmp_path):
    verdict = _ledger(tmp_path, (0.125,)).validate_final_answer(
        "Ratio: 12.50%.\n```figures\n12.50% | derived | 0.125 * 100 | measure\n```"
    )
    assert verdict.valid, verdict.issues


def test_non_percent_claim_does_not_gain_a_free_multiplier(tmp_path):
    verdict = _ledger(tmp_path, (125, 75, 10000)).validate_final_answer(
        "Score: 2.00.\n```figures\n2.00 | derived | (125 + 75) / 10000 * 100 | measure\n```"
    )
    assert not verdict.valid
    assert verdict.issues[0]["reason"] == "operand_not_observed"
