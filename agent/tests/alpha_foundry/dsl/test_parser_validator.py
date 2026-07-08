from __future__ import annotations

import pytest

from src.alpha_foundry.dsl.parser import FormulaParser
from src.alpha_foundry.dsl.validator import validate_expression


def test_parse_simple_formula_tree() -> None:
    ast = FormulaParser().parse("rank(delta(close, 5))")

    assert ast.op == "rank"
    assert ast.depth == 3
    assert ast.fields() == {"close"}
    assert ast.windows() == [5]


def test_negative_delay_rejected() -> None:
    ast = FormulaParser().parse("delay(close, -1)")

    result = validate_expression(ast)

    assert not result.ok
    assert "LOOKAHEAD_DETECTED" in result.errors


def test_future_return_field_rejected() -> None:
    ast = FormulaParser().parse("rank(future_return)")

    result = validate_expression(ast)

    assert not result.ok
    assert "LOOKAHEAD_DETECTED" in result.errors


def test_unknown_operator_rejected() -> None:
    ast = FormulaParser().parse("evil(close)")

    result = validate_expression(ast)

    assert not result.ok
    assert "OPERATOR_NOT_ALLOWED" in result.errors


def test_overdeep_ast_rejected() -> None:
    ast = FormulaParser().parse("rank(zscore(winsorize(decay_linear(delta(close, 2), 3))))")

    result = validate_expression(ast)

    assert not result.ok
    assert "AST_DEPTH_EXCEEDED" in result.errors


def test_large_window_rejected() -> None:
    ast = FormulaParser().parse("ts_mean(close, 300)")

    result = validate_expression(ast)

    assert not result.ok
    assert "WINDOW_OUT_OF_RANGE" in result.errors


def test_parser_rejects_non_call_syntax() -> None:
    with pytest.raises(ValueError, match="unsupported formula syntax"):
        FormulaParser().parse("close + 1")
