from __future__ import annotations

from src.alpha_foundry.dsl.model import ASTNode, ValidationResult

ALLOWED_OPERATORS = {
    "rank",
    "zscore",
    "winsorize",
    "clip",
    "group_neutralize",
    "ts_mean",
    "ts_std",
    "ts_rank",
    "ts_corr",
    "ts_cov",
    "delay",
    "delta",
    "decay_linear",
    "signed_power",
    "add",
    "sub",
    "mul",
    "div_safe",
    "neg",
    "log1p_abs",
    "volume_shock",
    "vwap_deviation",
    "illiquidity_proxy",
}

ALLOWED_FIELDS = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "vwap",
    "ret_1d",
    "turnover",
    "mktcap",
    "industry",
    "st_flag",
    "suspended",
    "limit_up",
    "limit_down",
}

MAX_AST_DEPTH = 4
MAX_AST_NODES = 12
MAX_WINDOW = 252


def validate_expression(node: ASTNode) -> ValidationResult:
    errors: list[str] = []
    if node.depth > MAX_AST_DEPTH:
        errors.append("AST_DEPTH_EXCEEDED")
    if node.node_count > MAX_AST_NODES:
        errors.append("AST_NODE_LIMIT_EXCEEDED")
    for op in node.operators():
        if op not in ALLOWED_OPERATORS:
            errors.append("OPERATOR_NOT_ALLOWED")
    for field in node.fields():
        if field.startswith("future_"):
            errors.append("LOOKAHEAD_DETECTED")
        if field not in ALLOWED_FIELDS:
            errors.append("FIELD_NOT_ALLOWED")
    for window in node.windows():
        if window < 1 or window > MAX_WINDOW:
            errors.append("WINDOW_OUT_OF_RANGE")
    _check_delay_lags(node, errors)
    return ValidationResult(ok=not errors, errors=sorted(set(errors)))


def _check_delay_lags(node: ASTNode, errors: list[str]) -> None:
    if node.op == "delay" and len(node.args) >= 2:
        lag = node.args[1]
        if isinstance(lag, int) and lag < 0:
            errors.append("LOOKAHEAD_DETECTED")
    for arg in node.args:
        if isinstance(arg, ASTNode):
            _check_delay_lags(arg, errors)
