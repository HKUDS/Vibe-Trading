from __future__ import annotations

import numpy as np
import pandas as pd

from src.alpha_foundry.dsl.model import ASTNode
from src.alpha_foundry.dsl.parser import FormulaParser
from src.alpha_foundry.dsl.validator import validate_expression


class FormulaValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(", ".join(errors))
        self.errors = errors


def evaluate_formula(text: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    node = FormulaParser().parse(text)
    validation = validate_expression(node)
    if not validation.ok:
        raise FormulaValidationError(validation.errors)
    return evaluate_ast(node, panel)


def evaluate_ast(node: ASTNode | int | float, panel: dict[str, pd.DataFrame]) -> pd.DataFrame | int | float:
    if isinstance(node, (int, float)):
        return node
    if node.op == "field":
        field = str(node.value)
        if field not in panel:
            raise KeyError(f"panel missing field {field!r}")
        return panel[field]
    args = [evaluate_ast(arg, panel) for arg in node.args]
    return _apply(node.op, args)


def _apply(op: str, args: list[pd.DataFrame | int | float]) -> pd.DataFrame:
    if op == "rank":
        return _frame(args[0]).rank(axis=1, pct=True)
    if op == "zscore":
        frame = _frame(args[0])
        return frame.sub(frame.mean(axis=1), axis=0).div(frame.std(axis=1).replace(0, np.nan), axis=0)
    if op == "winsorize":
        frame = _frame(args[0])
        lower = frame.quantile(0.01, axis=1)
        upper = frame.quantile(0.99, axis=1)
        return frame.clip(lower=lower, upper=upper, axis=0)
    if op == "clip":
        return _frame(args[0]).clip(lower=float(args[1]), upper=float(args[2]))
    if op == "delay":
        return _frame(args[0]).shift(int(args[1]))
    if op == "delta":
        frame = _frame(args[0])
        return frame - frame.shift(int(args[1]))
    if op == "neg":
        return -_frame(args[0])
    if op == "add":
        return _frame(args[0]) + _frame(args[1])
    if op == "sub":
        return _frame(args[0]) - _frame(args[1])
    if op == "mul":
        return _frame(args[0]) * _frame(args[1])
    if op == "div_safe":
        denom = _frame(args[1]).replace(0, np.nan)
        return _frame(args[0]) / denom
    if op == "ts_mean":
        return _frame(args[0]).rolling(int(args[1]), min_periods=int(args[1])).mean()
    if op == "decay_linear":
        frame = _frame(args[0])
        window = int(args[1])
        weights = np.arange(1, window + 1, dtype=float)
        weights /= weights.sum()
        return frame.rolling(window, min_periods=window).apply(lambda x: float(np.dot(x, weights)), raw=True)
    if op == "volume_shock":
        frame = _frame(args[0])
        window = int(args[1])
        avg = frame.rolling(window, min_periods=window).mean()
        return frame / avg.replace(0, np.nan)
    if op == "illiquidity_proxy":
        return _frame(args[0])
    if op == "log1p_abs":
        return np.log1p(_frame(args[0]).abs())
    if op in {"group_neutralize", "ts_std", "ts_rank", "ts_corr", "ts_cov", "signed_power", "vwap_deviation"}:
        raise NotImplementedError(f"operator {op!r} is validated but not implemented in core v1")
    raise FormulaValidationError(["OPERATOR_NOT_ALLOWED"])


def _frame(value: pd.DataFrame | int | float) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise TypeError("operator expected a DataFrame argument")
    return value
