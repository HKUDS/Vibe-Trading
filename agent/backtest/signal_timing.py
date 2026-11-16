"""Check for a second execution delay on generated strategy outputs.

Indicator lookbacks are consumed by comparisons/rolling calculations; a shift
forwarded directly to the returned target series needs an explicit declaration
of intentional delay. This is a bounded source check, not a proof of arbitrary
Python strategy semantics.
"""

from __future__ import annotations

import ast
from pathlib import Path


_PRESERVE = frozenset({"astype", "fillna", "ffill", "bfill", "copy", "clip", "rename", "reindex"})


def _integer(node: ast.AST | None) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _integer(node.operand)
        return -value if value is not None else None
    return None


def output_delays(source: str) -> set[int]:
    """Find positive shifts forwarded to outputs of SignalEngine.generate.

    Args:
        source: Python strategy source, already subject to the runner sandbox.

    Returns:
        Positive bar delays seen on returned targets, excluding feature shifts
        consumed by comparisons or rolling indicators.
    """
    tree = ast.parse(source)
    methods = [m for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "SignalEngine"
               for m in c.body if isinstance(m, ast.FunctionDef) and m.name == "generate"]
    returned: set[int] = set()

    def value(node, env):
        if isinstance(node, ast.Name):
            return env.get(node.id, set())
        if isinstance(node, ast.Dict):
            return set().union(*(value(v, env) for v in node.values))
        if isinstance(node, ast.Attribute) and node.attr in {"iloc", "loc", "values"}:
            return value(node.value, env)
        if isinstance(node, ast.Subscript):
            previous = value(node.value, env)
            offset = node.slice
            delay = (_integer(offset.right) if isinstance(offset, ast.BinOp)
                     and isinstance(offset.op, ast.Sub) else None)
            if isinstance(offset, ast.Slice) and offset.lower is None:
                stop = _integer(offset.upper)
                delay = -stop if stop is not None and stop < 0 else None
            if delay is not None and delay > 0:
                return {d + delay for d in previous} if previous else {delay}
            return previous
        if isinstance(node, ast.UnaryOp):
            return value(node.operand, env)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            if isinstance(node.right, ast.Constant):
                return value(node.left, env)
            if isinstance(node.left, ast.Constant):
                return value(node.right, env)
        if isinstance(node, ast.Call):
            method = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if method == "shift":
                period = next((k.value for k in node.keywords if k.arg == "periods"),
                              node.args[0] if node.args else ast.Constant(1))
                delay = _integer(period)
                previous = value(node.func.value, env)
                if delay is not None and delay > 0:
                    return {d + delay for d in previous} if previous else {delay}
                return previous
            if method in _PRESERVE:
                return value(node.func.value, env)
            if method == "Series" or isinstance(node.func, ast.Name) and node.func.id == "Series":
                data = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "data"), None)
                return value(data, env)
        return set()

    def assign(target, delays, env):
        if isinstance(target, ast.Name):
            env[target.id] = set(delays)
        elif isinstance(target, ast.Subscript):
            root = target.value
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name):
                env[root.id] = env.get(root.id, set()) | delays

    def walk(statements, env, guard=frozenset()):
        for node in statements:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assign(target, value(node.value, env) | guard, env)
            elif isinstance(node, ast.AnnAssign):
                assign(node.target, value(node.value, env) | guard, env)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == "append" and call.args:
                    container = call.func.value
                    if isinstance(container, ast.Name):
                        env[container.id] = env.get(container.id, set()) | value(call.args[0], env) | guard
            elif isinstance(node, ast.Return):
                returned.update(value(node.value, env))
            elif isinstance(node, (ast.For, ast.While, ast.If, ast.With)):
                branches = [node.body]
                if hasattr(node, "orelse"):
                    branches.append(node.orelse)
                for branch in branches:
                    local = {k: set(v) for k, v in env.items()}
                    branch_guard = guard | value(node.test, env) if isinstance(node, ast.If) else guard
                    walk(branch, local, branch_guard)
                    for key, delays in local.items():
                        env[key] = env.get(key, set()) | delays

    for method in methods:
        walk(method.body, {})
    return returned


def validate_signal_timing(path: Path, intentional_delay: int = 0) -> None:
    """Reject undeclared output shifts before executing generated daily code.

    Args:
        path: Strategy source path.
        intentional_delay: Extra bars explicitly intended by the strategy.

    Raises:
        ValueError: A returned target has an unacknowledged extra delay.
    """
    try:
        delays = output_delays(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise ValueError(f"Invalid signal_engine.py syntax: {exc}") from exc
    if delays and delays != {intentional_delay}:
        raise ValueError(
            f"signal_timing_double_delay: returned targets contain shift(s) of {sorted(delays)} bar(s). "
            "The engine already executes close-of-bar targets at the next open. "
            "Remove the extra target shift and rerun. Keep indicator lookbacks. "
            "Only if the strategy explicitly intends an additional delay, set "
            "intentional_signal_delay_bars to that number in config.json; this does not remove the engine delay."
        )
