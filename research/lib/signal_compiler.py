"""signal_compiler.py — Compile a StrategySpec (YAML→Python).

Public API:
    compile_strategy(spec: StrategySpec, yaml_hash: str = "") -> str
        Renders a validated signal_engine.py source string from a StrategySpec.

The rendered source is checked with:
    1. ast.parse()                   — syntax validation
    2. _validate_signal_engine_source() — AST scrubber from backtest/runner.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import List, Optional

import jinja2

# ---------------------------------------------------------------------------
# Path bootstrap — ensure repo root is importable when running from research/
# ---------------------------------------------------------------------------
_LIB_DIR = Path(__file__).resolve().parent      # research/lib/
_RESEARCH_DIR = _LIB_DIR.parent                 # research/
_REPO_ROOT = _RESEARCH_DIR.parent               # repo root
_AGENT_DIR = _REPO_ROOT / "agent"

for _p in (str(_RESEARCH_DIR), str(_REPO_ROOT), str(_AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Late imports (depend on path bootstrap above)
# ---------------------------------------------------------------------------
from dashboard.server.schemas import (  # noqa: E402
    EntryBlock,
    IndicatorSpec,
    StrategySpec,
    _parse_condition,
)

# _validate_signal_engine_source expects a file Path, so we adapt it below.
# We import the raw AST helpers directly to avoid the file I/O wrapper.
from backtest.runner import (  # noqa: E402
    _validate_class_body,
    _validate_function_def,
    _is_safe_constant_assignment,
)

# ---------------------------------------------------------------------------
# Jinja2 template loader
# ---------------------------------------------------------------------------
_TEMPLATES_DIR = _REPO_ROOT / "research" / "strategies" / "code" / "_templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)


# ---------------------------------------------------------------------------
# Internal AST validation (mirrors _validate_signal_engine_source but works
# on a string instead of a file path)
# ---------------------------------------------------------------------------

def _validate_source_string(source: str, label: str = "<generated>") -> None:
    """Validate generated source using the same AST rules as runner.py."""
    try:
        tree = ast.parse(source, filename=label)
    except SyntaxError as exc:
        raise ValueError(f"Invalid signal_engine.py syntax: {exc}") from exc

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _validate_function_def(node)
            continue
        if isinstance(node, ast.ClassDef):
            _validate_class_body(node)
            continue
        if _is_safe_constant_assignment(node):
            continue
        raise ValueError(
            f"Executable top-level statement {type(node).__name__} is not allowed"
        )


# ---------------------------------------------------------------------------
# 3.3 — Indicator load renderer
# ---------------------------------------------------------------------------

def _render_indicator_load(name: str, spec: IndicatorSpec) -> str:
    """Render a single indicator load + optional smoothing as Python lines.

    Indented at 8 spaces (inside class method body).
    """
    # Extract factor name from source like "stage1:funding_rate"
    factor_key = spec.source.split(":", 1)[1]

    lines: list[str] = [
        f'        {name} = _factors["{factor_key}"]',
        # Align factor parquet index to ohlcv index (backtest window may differ from
        # stage1 dump). reindex + ffill = sample-and-hold for sparse factors too.
        f"        {name} = {name}.reindex(ohlcv.index, method='ffill')",
    ]

    smoothing = spec.smoothing
    if smoothing == "none":
        pass  # no extra line
    elif smoothing.startswith("sma_"):
        n = int(smoothing[4:])
        lines.append(f"        {name} = {name}.rolling({n}, min_periods=1).mean()")
    elif smoothing.startswith("ema_"):
        n = int(smoothing[4:])
        lines.append(f"        {name} = {name}.ewm(span={n}, adjust=False).mean()")
    else:
        raise ValueError(f"Unknown smoothing spec: {smoothing!r}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3.4 — Condition renderer
# ---------------------------------------------------------------------------
_PERCENTILE_INDICATOR_RE = re.compile(r"^([a-z][a-z0-9_]*)_percentile_(\d+)d$")
_ZSCORE_INDICATOR_RE = re.compile(r"^([a-z][a-z0-9_]*)_zscore_(\d+)d$")


def _resolve_indicator_var(
    indicator_expr: str,
    suffix_re: re.Pattern,
    indicator_var_map: Optional[dict],
) -> tuple[str, int]:
    """Return (python_var_name, n_days) for a percentile/zscore indicator_expr.

    When *indicator_var_map* is provided, the Python variable name is resolved
    by finding the indicator key whose name, when used as a prefix, matches the
    full *indicator_expr* (e.g. ``funding_rate`` → ``funding_rate_zscore_30d``).
    Falls back to the regex-extracted prefix when no map is supplied or no key
    matches (preserves backward-compatible behaviour for direct unit tests).
    """
    m = suffix_re.match(indicator_expr)
    assert m, f"Expected {suffix_re.pattern!r} to match {indicator_expr!r}"
    regex_base = m.group(1)
    n_days = int(m.group(2))

    if indicator_var_map:
        suffix = indicator_expr[len(regex_base):]   # e.g. "_zscore_30d"
        for key, var_name in indicator_var_map.items():
            if indicator_expr == f"{key}{suffix}":
                return var_name, n_days
        # No exact match — fall back to regex base
    return regex_base, n_days


def _render_condition(
    cond_str: str,
    indicator_var_map: Optional[dict] = None,
) -> str:
    """Translate a DSL condition string into a pandas boolean expression string.

    Parameters
    ----------
    cond_str:
        Raw DSL condition string, e.g. ``"funding_rate_zscore_30d <= -1.5 persist 2/3"``.
    indicator_var_map:
        Optional mapping of ``{indicator_key: python_var_name}`` from the
        StrategySpec.  When provided, zscore/percentile conditions are resolved
        to the correct Python variable rather than the regex-extracted prefix.

    Returns a Python expression string (no trailing newline, no indentation).
    """
    indicator_expr, op, value, persist_m, persist_n = _parse_condition(cond_str)

    # Determine if the indicator expression encodes percentile or zscore
    pct_m = _PERCENTILE_INDICATOR_RE.match(indicator_expr)
    zscore_m = _ZSCORE_INDICATOR_RE.match(indicator_expr)

    if pct_m:
        base_name, n_days = _resolve_indicator_var(
            indicator_expr, _PERCENTILE_INDICATOR_RE, indicator_var_map
        )
        base_cond = (
            f"({base_name}.rolling({n_days}*24, min_periods={n_days}*24//2).rank(pct=True)*100 {op} {value})"
        )
    elif zscore_m:
        base_name, n_days = _resolve_indicator_var(
            indicator_expr, _ZSCORE_INDICATOR_RE, indicator_var_map
        )
        base_cond = (
            f"(({base_name} - {base_name}.rolling({n_days}*24, min_periods={n_days}*24//2).mean()) "
            f"/ ({base_name}.rolling({n_days}*24, min_periods={n_days}*24//2).std() + 1e-9) {op} {value})"
        )
    else:
        # Raw comparison — indicator name used as-is
        base_cond = f"({indicator_expr} {op} {value})"

    if persist_m is not None and persist_n is not None:
        return f"(({base_cond}).rolling({persist_n}).sum() >= {persist_m})"

    return base_cond


# ---------------------------------------------------------------------------
# 3.5 — Entry block renderer
# ---------------------------------------------------------------------------

def _render_entry_block(
    side: str,
    block: Optional[EntryBlock],
    indicator_var_map: Optional[dict] = None,
) -> str:
    """Render entry_{side} boolean Series assignment.

    Indented at 8 spaces.
    """
    var = f"entry_{side}"
    if block is None:
        return f"        {var} = pd.Series(False, index=ohlcv.index)"

    cond_exprs = [_render_condition(c, indicator_var_map) for c in block.conditions]
    joined = " & ".join(cond_exprs)
    return f"        {var} = ({joined})"


# ---------------------------------------------------------------------------
# 3.6 — Exit state machine renderer
# ---------------------------------------------------------------------------
_INVALIDATION_RE = re.compile(
    r"^([a-z][a-z0-9_]*)_percentile_(\d+)d between (\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$"
)


def _render_exit_rule_check(
    rule,
    rule_idx: int = 0,
    indent: str = "                ",
) -> str:
    """Render one exit rule inside the loop else-body. Returns lines joined with newlines.

    Parameters
    ----------
    rule:
        Exit rule object.
    rule_idx:
        Index of this rule in the exit_rules list, used to generate unique
        pre-computed percentile variable names (``_inv_pct_0``, ``_inv_pct_1``,
        …) to avoid name collisions when multiple signal_invalidation rules
        are present.
    indent:
        Default indent is 16 spaces (inside: for-loop -> else -> rule checks).
    """
    condition = rule.condition

    if condition == "time_based":
        return f"{indent}if bars_held >= {rule.max_hold_hours}:\n{indent}    exit_flag = True"

    elif condition == "take_profit_pct":
        return f"{indent}if pnl_pct >= {rule.value} / 100:\n{indent}    exit_flag = True"

    elif condition == "stop_loss_pct":
        return f"{indent}if pnl_pct <= -{rule.value} / 100:\n{indent}    exit_flag = True"

    elif condition == "signal_invalidation":
        m = _INVALIDATION_RE.match(rule.expression)
        if not m:
            raise ValueError(f"Cannot parse signal_invalidation expression: {rule.expression!r}")
        lo = m.group(3)
        hi = m.group(4)
        # The pre-computed series is referenced by index to avoid name collisions
        pct_var = f"_inv_pct_{rule_idx}"
        lines = [
            f"{indent}if ({lo} <= {pct_var}.iloc[bar_i] <= {hi}) and position != 0:",
            f"{indent}    exit_flag = True",
        ]
        return "\n".join(lines)

    else:
        raise ValueError(f"Unknown exit rule condition: {condition!r}")


def _render_exit_state_machine(exit_rules) -> str:
    """Render the full exit state machine loop. Indented at 8 spaces (class method body)."""
    # Indentation levels:
    #   8  = method body
    #  12  = for-loop body
    #  16  = if/else branches inside for-loop body
    #  20  = nested inside else block
    i8 = "        "
    i12 = "            "
    i16 = "                "
    i20 = "                    "

    # Hoist signal_invalidation percentile computations BEFORE the loop to
    # avoid O(n²) rolling calculations and prevent _inv_pct name collisions.
    pre_loop_lines: list[str] = []
    for rule_idx, rule in enumerate(exit_rules):
        if rule.condition == "signal_invalidation":
            m = _INVALIDATION_RE.match(rule.expression)
            if not m:
                raise ValueError(
                    f"Cannot parse signal_invalidation expression: {rule.expression!r}"
                )
            indicator = m.group(1)
            n_days = int(m.group(2))
            pct_var = f"_inv_pct_{rule_idx}"
            pre_loop_lines.append(
                f"{i8}{pct_var} = {indicator}.rolling({n_days}*24, min_periods={n_days}*24//2)"
                f".rank(pct=True)*100"
            )

    rule_checks = "\n".join(
        _render_exit_rule_check(r, rule_idx=idx, indent=i16)
        for idx, r in enumerate(exit_rules)
    )

    lines = [
        f"{i8}signal = pd.Series(0.0, index=ohlcv.index)",
        f"{i8}position = 0",
        f"{i8}entry_price = None",
        f"{i8}bars_held = 0",
    ]

    if pre_loop_lines:
        lines.append(f"")
        lines.extend(pre_loop_lines)

    lines += [
        f"",
        # Use bar_i as loop counter so it does not clash with rule_idx (i)
        f"{i8}for bar_i, ts in enumerate(ohlcv.index):",
        f"{i12}if position == 0:",
        f"{i16}if entry_long.iloc[bar_i]:",
        f"{i20}position = 1",
        f'{i20}entry_price = ohlcv["close"].iloc[bar_i]',
        f"{i20}bars_held = 0",
        f"{i16}elif entry_short.iloc[bar_i]:",
        f"{i20}position = -1",
        f'{i20}entry_price = ohlcv["close"].iloc[bar_i]',
        f"{i20}bars_held = 0",
        f"{i12}else:",
        f"{i16}bars_held += 1",
        # Renamed from 'close' to '_close_price' to avoid shadowing any indicator
        # named 'close' that may be loaded earlier in the method.
        f'{i16}_close_price = ohlcv["close"].iloc[bar_i]',
        f"{i16}pnl_pct = (_close_price - entry_price) / entry_price * position",
        f"{i16}exit_flag = False",
    ]

    if exit_rules:
        lines.append("")
        lines.append(rule_checks)

    lines += [
        f"",
        f"{i16}if exit_flag:",
        f"{i20}position = 0",
        f"{i20}entry_price = None",
        f"{i20}bars_held = 0",
        f"",
        f"{i12}signal.iloc[bar_i] = float(position)",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3.7 — Public compile_strategy()
# ---------------------------------------------------------------------------

def compile_strategy(spec: StrategySpec, yaml_hash: str = "") -> str:
    """Compile a StrategySpec to signal_engine.py source code string.

    Parameters
    ----------
    spec:
        Validated StrategySpec instance.
    yaml_hash:
        Optional SHA-256 (or similar) hash of the source YAML, embedded as a
        comment in the generated file for traceability.

    Returns
    -------
    str
        Full Python source of signal_engine.py, ready to write to disk.

    Raises
    ------
    ValueError
        If the rendered source fails AST syntax check or the backtest AST
        scrubber rejects it.
    """
    # 1. Render indicator loads
    # Build a map {indicator_key: python_var_name} for condition resolution.
    # Currently the Python variable name equals the indicator key (both are the
    # dict key in spec.indicators), but the map makes the relationship explicit
    # and allows future divergence without touching condition rendering.
    indicator_var_map: dict[str, str] = {key: key for key in spec.indicators}

    indicator_lines = []
    for name, ind_spec in spec.indicators.items():
        indicator_lines.append(_render_indicator_load(name, ind_spec))
    indicator_code = "\n".join(indicator_lines) if indicator_lines else "        pass"

    # 2. Render entry blocks
    entry_long_code = _render_entry_block("long", spec.entry_long, indicator_var_map)
    entry_short_code = _render_entry_block("short", spec.entry_short, indicator_var_map)

    # 3. Render exit state machine
    exit_code = _render_exit_state_machine(spec.exit_rules)

    # 4. Render template
    template = _jinja_env.get_template("signal_engine.py.j2")
    source = template.render(
        yaml_hash=yaml_hash,
        spec=spec,
        indicator_code=indicator_code,
        entry_long_code=entry_long_code,
        entry_short_code=entry_short_code,
        exit_code=exit_code,
    )

    # 5. AST syntax check
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(
            f"Compiled signal_engine.py has a syntax error: {exc}\n\nSource:\n{source}"
        ) from exc

    # 6. AST scrubber check (same rules as backtest/runner.py loader)
    try:
        _validate_source_string(source, label="<compiled signal_engine.py>")
    except ValueError as exc:
        raise ValueError(
            f"Compiled signal_engine.py failed AST scrubber: {exc}\n\nSource:\n{source}"
        ) from exc

    return source
