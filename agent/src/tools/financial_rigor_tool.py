"""Agent tool: financial-rigor checks with exact decimal arithmetic.

A thin ``BaseTool`` wrapper around six pure-stdlib verification routines that
guard investment research against numerical error and hallucinated metrics.
Auto-discovered and registered via ``BaseTool.__subclasses__()``.

All arithmetic uses ``decimal.Decimal`` under a shared 28-digit context, so
results are free of IEEE-754 drift and are reproducible and auditable. The
tool takes raw numbers only — it does not fetch data. Pair it with the
market-data / financial-statement tools: fetch there, verify here.

Sub-commands (selected via ``command``):

- ``verify_market_cap`` — price × shares vs a reported cap; verdict at 1%/5%.
- ``verify_valuation`` — PE / PB / ROE / P/FCF / FCF yield / dividend yield /
  PS derived from raw per-share inputs.
- ``cross_validate`` — one field across several sources, flag deviations over
  a tolerance (default 2%), expose the median consensus.
- ``benford`` — Benford's-law first-digit check on a list of values; needs
  ≥50 samples; reports MAD / chi-square / conformity.
- ``calc`` — safe exact evaluation of an arithmetic expression string
  (AST-whitelisted: numbers and +, -, *, / only).
- ``three_scenario`` — bull / base / bear target prices from EPS-growth and
  target-PE assumptions.

Read-only: returns JSON verdicts, writes nothing.
"""

from __future__ import annotations

import ast
import json
import math
from decimal import Context, Decimal, ROUND_HALF_EVEN
from typing import Any

from src.agent.tools import BaseTool

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)

# Benford's-law expected first-digit frequencies.
_BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

# AST operator handlers for the ``calc`` evaluator. Only numbers and
# +, -, *, / (with optional unary sign) are honoured; anything else raises.
_AST_BINOPS = {
    ast.Add: _CTX.add,
    ast.Sub: _CTX.subtract,
    ast.Mult: _CTX.multiply,
    ast.Div: _CTX.divide,
}
_AST_UNARYOPS = {
    ast.UAdd: lambda d: d,
    ast.USub: lambda d: -d,
}


def _err(msg: str) -> str:
    """Build the standard error JSON envelope."""
    return json.dumps({"status": "error", "error": msg}, ensure_ascii=False)


def _exact(value: Any) -> Decimal:
    """Convert any numeric to an exact Decimal, avoiding float binary traps."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _fmt(value: float) -> str:
    """Render a large number with K / M / B / T suffixes for readability."""
    abs_v = abs(value)
    if abs_v >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs_v >= 1e3:
        return f"{value / 1e3:.2f}K"
    return f"{value:,.2f}"


def _eval_arith_node(node: ast.AST) -> Decimal:
    """Recursively evaluate an arithmetic AST node in the Decimal domain.

    Args:
        node: An AST node from a parsed expression.

    Returns:
        The exact Decimal value of the node.

    Raises:
        ValueError: If the node is not a supported numeric/arithmetic form.
    """
    if isinstance(node, ast.Constant):
        # bool is a subclass of int — reject it explicitly.
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are allowed")
        return _exact(node.value)
    if isinstance(node, ast.BinOp):
        op_fn = _AST_BINOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        return op_fn(_eval_arith_node(node.left), _eval_arith_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_fn = _AST_UNARYOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return op_fn(_eval_arith_node(node.operand))
    raise ValueError(f"disallowed element in expression: {type(node).__name__}")


def _safe_arith(expr: str) -> Decimal:
    """Evaluate a numeric arithmetic expression in the exact-Decimal domain.

    The expression is parsed and evaluated recursively with Decimal arithmetic,
    so ``0.1 + 0.2`` is exactly ``0.3`` — no IEEE-754 drift, and no ``eval``.
    Only numbers and the operators ``+ - * /`` (with optional unary sign) are
    permitted; any other AST node raises ``ValueError``.

    Args:
        expr: Arithmetic expression string, e.g. ``"510 * 9.11e9"``.

    Returns:
        The exact Decimal result.

    Raises:
        ValueError: If the expression is malformed or contains a disallowed
            element.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"malformed expression: {exc}") from exc
    return _eval_arith_node(tree.body)


# ---------------------------------------------------------------------------
# Core verification routines (pure, return structured dicts, no I/O)
# ---------------------------------------------------------------------------

def verify_market_cap(
    price: Any, shares: Any, reported_cap: Any, currency: str = "",
) -> dict[str, Any]:
    """Verify ``market cap = price × shares`` against a reported value.

    Args:
        price: Current share price.
        shares: Total share count.
        reported_cap: The market-cap figure being checked.
        currency: Optional currency label for display only.

    Returns:
        Verdict dict. ``verdict`` is ``pass`` (≤1%), ``warn`` (1–5%) or
        ``fail`` (>5%).
    """
    p, s, r = _exact(price), _exact(shares), _exact(reported_cap)
    calculated = _CTX.multiply(p, s)
    deviation = abs(float(calculated - r) / float(r)) * 100 if r != 0 else 0.0
    if deviation > 5:
        verdict = "fail"
    elif deviation > 1:
        verdict = "warn"
    else:
        verdict = "pass"
    return {
        "price": float(p),
        "shares": float(s),
        "currency": currency,
        "calculated_market_cap": float(calculated),
        "calculated_market_cap_display": _fmt(float(calculated)),
        "reported_market_cap": float(r),
        "deviation_pct": round(deviation, 4),
        "verdict": verdict,
    }


def verify_valuation(
    price: Any,
    eps: Any | None = None,
    bvps: Any | None = None,
    fcf_per_share: Any | None = None,
    dividend: Any | None = None,
    revenue_per_share: Any | None = None,
) -> dict[str, Any]:
    """Derive valuation ratios from raw per-share inputs (exact decimal).

    Each optional input, when supplied and non-zero, contributes its metric(s).
    ROE additionally requires both ``eps`` and ``bvps``.

    Args:
        price: Current share price.
        eps: Earnings per share (TTM).
        bvps: Book value per share.
        fcf_per_share: Free cash flow per share.
        dividend: Dividend per share.
        revenue_per_share: Revenue per share.

    Returns:
        Dict with ``price`` and a ``metrics`` map (PE, PB, ROE_pct, P_FCF,
        FCF_yield_pct, dividend_yield_pct, PS — whichever apply).
    """
    p = _exact(price)
    metrics: dict[str, float] = {}
    if eps is not None:
        e = _exact(eps)
        if e != 0:
            metrics["PE"] = float(_CTX.divide(p, e))
            metrics["earnings_yield_pct"] = float(_CTX.divide(e, p) * 100)
    if bvps is not None:
        b = _exact(bvps)
        if b != 0:
            metrics["PB"] = float(_CTX.divide(p, b))
            if eps is not None and _exact(eps) != 0:
                metrics["ROE_pct"] = float(_CTX.divide(_exact(eps), b) * 100)
    if fcf_per_share is not None:
        f = _exact(fcf_per_share)
        if f != 0:
            metrics["P_FCF"] = float(_CTX.divide(p, f))
            metrics["FCF_yield_pct"] = float(_CTX.divide(f, p) * 100)
    if dividend is not None:
        d = _exact(dividend)
        if p != 0:
            metrics["dividend_yield_pct"] = float(_CTX.divide(d, p) * 100)
    if revenue_per_share is not None:
        rps = _exact(revenue_per_share)
        if rps != 0:
            metrics["PS"] = float(_CTX.divide(p, rps))
    return {"price": float(p), "metrics": metrics}


def cross_validate(
    field_name: str,
    source_values: dict[str, Any],
    unit: str = "",
    tolerance_pct: float = 2.0,
) -> dict[str, Any]:
    """Compare one field across sources, flag deviations over a tolerance.

    The median of the supplied values is used as the reference, and each
    source's percent deviation from it is reported.

    Args:
        field_name: Field being compared (e.g. ``"revenue"``).
        source_values: Mapping of source name to numeric value.
        unit: Optional unit label for display.
        tolerance_pct: Percent deviation above which a source is inconsistent.

    Returns:
        Dict with ``median_reference``/``consensus``, ``all_consistent`` and a
        per-source breakdown.
    """
    values = {k: _exact(v) for k, v in source_values.items()}
    nums = sorted(float(v) for v in values.values())
    n = len(nums)
    if n == 0:
        median = 0.0
    elif n % 2 == 1:
        median = nums[n // 2]
    else:
        median = (nums[n // 2 - 1] + nums[n // 2]) / 2
    per_source: list[dict[str, Any]] = []
    all_consistent = True
    for src, val in values.items():
        dev = abs(float(val) - median) / median * 100 if median != 0 else 0.0
        consistent = dev <= tolerance_pct
        all_consistent = all_consistent and consistent
        per_source.append({
            "source": src,
            "value": float(val),
            "deviation_pct": round(dev, 4),
            "consistent": consistent,
        })
    return {
        "field": field_name,
        "unit": unit,
        "tolerance_pct": tolerance_pct,
        "median_reference": median,
        "consensus": median,
        "all_consistent": all_consistent,
        "per_source": per_source,
    }


def benford_check(values: list[Any]) -> dict[str, Any]:
    """First-digit Benford's-law check on a list of financial values.

    Args:
        values: Numeric values to inspect.

    Returns:
        Dict with ``sample_size``, ``reliable`` (False when ``n < 50``), and —
        when reliable — ``mad`` (Nigrini's MAD), ``chi2``, ``conformity`` and a
        per-digit ``distribution``.
    """
    digits: list[int] = []
    for raw in values:
        v = abs(float(raw))
        if v > 0:
            sig = 10 ** (math.log10(v) - math.floor(math.log10(v)))
            d = int(sig)
            if 1 <= d <= 9:
                digits.append(d)
    n = len(digits)
    if n < 50:
        return {
            "sample_size": n,
            "reliable": False,
            "note": "Benford analysis needs >= 50 samples to be meaningful",
        }
    counts = {d: 0 for d in range(1, 10)}
    for d in digits:
        counts[d] += 1
    observed = {d: counts[d] / n for d in range(1, 10)}
    mad = sum(abs(observed[d] - _BENFORD[d]) for d in range(1, 10)) / 9
    chi2 = sum(
        (counts[d] - _BENFORD[d] * n) ** 2 / (_BENFORD[d] * n) for d in range(1, 10)
    )
    if mad < 0.006:
        conformity = "close"
    elif mad < 0.012:
        conformity = "acceptable"
    elif mad < 0.015:
        conformity = "marginal"
    else:
        conformity = "nonconforming"
    distribution = [
        {
            "digit": d,
            "observed": round(observed[d], 4),
            "expected": round(_BENFORD[d], 4),
            "deviation": round(observed[d] - _BENFORD[d], 4),
        }
        for d in range(1, 10)
    ]
    return {
        "sample_size": n,
        "reliable": True,
        "mad": round(mad, 6),
        "chi2": round(chi2, 4),
        "conformity": conformity,
        "is_conforming": mad < 0.015,
        "distribution": distribution,
    }


def exact_calc(expr: str) -> dict[str, Any]:
    """Evaluate an arithmetic expression with exact decimal arithmetic.

    Args:
        expr: Arithmetic expression string (numbers and ``+ - * /`` only).

    Returns:
        Dict with ``result`` (float) and ``result_exact`` (Decimal string).

    Raises:
        ValueError: If the expression is malformed or contains a disallowed
            element (surfaced by the caller as a tool error).
    """
    d = _safe_arith(expr)
    return {"expr": expr, "result": float(d), "result_exact": str(d)}


def three_scenario_valuation(
    current_price: Any,
    current_eps: Any,
    shares_billion: Any,
    growth_optimistic: Any,
    growth_neutral: Any,
    growth_pessimistic: Any,
    pe_optimistic: Any,
    pe_neutral: Any,
    pe_pessimistic: Any,
    years: int = 3,
    currency: str = "",
) -> dict[str, Any]:
    """Bull / base / bear target prices from EPS-growth and target-PE assumptions.

    Future EPS = ``current_eps × (1 + growth) ** years``; target price = future
    EPS × target PE. All math is exact decimal.

    Args:
        current_price: Current share price.
        current_eps: Current EPS.
        shares_billion: Share count in billions.
        growth_optimistic / growth_neutral / growth_pessimistic: Annual EPS
            growth rate per scenario (e.g. ``0.15`` for 15%).
        pe_optimistic / pe_neutral / pe_pessimistic: Target PE per scenario.
        years: Forecast horizon in years.
        currency: Optional currency label.

    Returns:
        Dict with the assumptions and a ``scenarios`` list, each carrying its
        ``future_eps``, ``target_price`` and ``upside_pct``.
    """
    p, eps, shares = _exact(current_price), _exact(current_eps), _exact(shares_billion)
    spec = [
        ("bull", growth_optimistic, pe_optimistic),
        ("base", growth_neutral, pe_neutral),
        ("bear", growth_pessimistic, pe_pessimistic),
    ]
    scenarios: list[dict[str, Any]] = []
    normalized: list[str] = []
    for name, growth, pe in spec:
        g, target_pe = _exact(growth), _exact(pe)
        # Defensive: LLMs frequently pass "15%" as 15 instead of 0.15. Treat
        # |growth| > 1 (i.e. > 100%) as a percent and normalize, flagging it.
        if abs(float(g)) > 1:
            g = _CTX.divide(g, Decimal("100"))
            normalized.append(name)
        future_eps = eps
        for _ in range(int(years)):
            future_eps = _CTX.multiply(future_eps, _CTX.add(Decimal("1"), g))
        target_price = _CTX.multiply(future_eps, target_pe)
        upside = float(target_price - p) / float(p) * 100 if p != 0 else 0.0
        scenarios.append({
            "scenario": name,
            "annual_growth": float(g),
            "target_pe": float(target_pe),
            "future_eps": float(future_eps),
            "target_price": float(target_price),
            "upside_pct": round(upside, 2),
        })
    result: dict[str, Any] = {
        "current_price": float(p),
        "current_eps": float(eps),
        "shares_billion": float(shares),
        "years": int(years),
        "currency": currency,
        "scenarios": scenarios,
    }
    if normalized:
        result["growth_normalized_from_percent"] = normalized
        result["note"] = (
            f"growth values > 1 (100%) were treated as percentages and divided "
            f"by 100 for scenarios: {normalized}. Pass 0.15 for 15% to avoid this."
        )
    return result


class FinancialRigorTool(BaseTool):
    """Exact-decimal financial verification across six sub-commands."""

    name = "financial_rigor"
    description = (
        "Verify financial-data accuracy with exact decimal arithmetic (no float "
        "drift). Takes raw numbers only — does not fetch data. Pair it with the "
        "market-data / financial-statement tools: fetch there, verify here. Six "
        "sub-commands selected via `command`: 'verify_market_cap' (price x shares "
        "vs reported cap, verdict at 1%/5%), 'verify_valuation' (PE/PB/ROE/P-FCF/"
        "yields/PS from raw per-share inputs), 'cross_validate' (one field across "
        "sources, flag deviations > tolerance_pct, expose median consensus), "
        "'benford' (Benford first-digit fabrication check, needs >=50 samples), "
        "'calc' (safe exact arithmetic on an expression string), 'three_scenario' "
        "(bull/base/bear target prices from EPS-growth and target-PE assumptions)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": [
                    "verify_market_cap", "verify_valuation", "cross_validate",
                    "benford", "calc", "three_scenario",
                ],
                "description": "Which verification to run.",
            },
            "price": {"type": "number", "description": "Share price."},
            "shares": {
                "type": "number",
                "description": "verify_market_cap: total share count; "
                               "three_scenario: share count in billions.",
            },
            "reported_cap": {"type": "number", "description": "Reported market cap."},
            "currency": {"type": "string", "description": "Currency label (display only)."},
            "eps": {"type": "number", "description": "Earnings per share."},
            "bvps": {"type": "number", "description": "Book value per share."},
            "fcf_per_share": {"type": "number", "description": "Free cash flow per share."},
            "dividend": {"type": "number", "description": "Dividend per share."},
            "revenue_per_share": {"type": "number", "description": "Revenue per share."},
            "field": {"type": "string", "description": "cross_validate: field name."},
            "source_values": {
                "type": "object",
                "description": "cross_validate: mapping of source name to value.",
            },
            "unit": {"type": "string", "description": "cross_validate: unit label."},
            "tolerance_pct": {
                "type": "number", "default": 2.0,
                "description": "cross_validate: max acceptable percent deviation.",
            },
            "values": {
                "type": "array", "items": {"type": "number"},
                "description": "benford: list of financial values to inspect.",
            },
            "expr": {
                "type": "string",
                "description": "calc: arithmetic expression (numbers and + - * /).",
            },
            "growth": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "three_scenario: annual EPS growth as a decimal [bull, base, bear], e.g. 0.15 for 15% (values > 1 are auto-treated as percent).",
            },
            "pe": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "three_scenario: target PE [bull, base, bear].",
            },
            "years": {"type": "integer", "default": 3, "description": "three_scenario horizon."},
        },
        "required": ["command"],
    }
    is_readonly = True
    repeatable = True  # loop.py dedups non-repeatable tools by name; users call
                       # different sub-commands / params in one session.

    def execute(self, **kwargs: Any) -> str:
        """Dispatch to the requested sub-command and return a JSON envelope.

        Args:
            **kwargs: ``command`` plus the inputs for that sub-command.

        Returns:
            JSON string — ``status="ok"`` with the verdict on success,
            ``status="error"`` with a message otherwise.
        """
        command = str(kwargs.get("command") or "").strip()
        try:
            if command == "verify_market_cap":
                for key in ("price", "shares", "reported_cap"):
                    if kwargs.get(key) is None:
                        return _err(f"{key} is required for verify_market_cap")
                result: dict[str, Any] = verify_market_cap(
                    kwargs["price"], kwargs["shares"], kwargs["reported_cap"],
                    currency=str(kwargs.get("currency") or ""),
                )
            elif command == "verify_valuation":
                if kwargs.get("price") is None:
                    return _err("price is required for verify_valuation")
                result = verify_valuation(
                    kwargs["price"], kwargs.get("eps"), kwargs.get("bvps"),
                    kwargs.get("fcf_per_share"), kwargs.get("dividend"),
                    kwargs.get("revenue_per_share"),
                )
            elif command == "cross_validate":
                if not kwargs.get("field") or not kwargs.get("source_values"):
                    return _err("field and source_values are required for cross_validate")
                result = cross_validate(
                    str(kwargs["field"]), kwargs["source_values"],
                    unit=str(kwargs.get("unit") or ""),
                    tolerance_pct=float(kwargs.get("tolerance_pct") or 2.0),
                )
            elif command == "benford":
                vals = kwargs.get("values")
                if not isinstance(vals, list) or not vals:
                    return _err("values (non-empty list) is required for benford")
                result = benford_check(vals)
            elif command == "calc":
                if not kwargs.get("expr"):
                    return _err("expr is required for calc")
                result = exact_calc(str(kwargs["expr"]))
            elif command == "three_scenario":
                for key in ("price", "eps", "shares", "growth", "pe"):
                    if kwargs.get(key) is None:
                        return _err(f"{key} is required for three_scenario")
                growth = kwargs["growth"]
                pe = kwargs["pe"]
                if not isinstance(growth, list) or len(growth) != 3:
                    return _err("growth must be a list of 3 numbers [bull, base, bear]")
                if not isinstance(pe, list) or len(pe) != 3:
                    return _err("pe must be a list of 3 numbers [bull, base, bear]")
                result = three_scenario_valuation(
                    kwargs["price"], kwargs["eps"], kwargs["shares"],
                    growth[0], growth[1], growth[2],
                    pe[0], pe[1], pe[2],
                    years=int(kwargs.get("years") or 3),
                    currency=str(kwargs.get("currency") or ""),
                )
            else:
                return _err(f"unknown command: {command}")
        except Exception as exc:  # noqa: BLE001 - surface a clean tool error
            return json.dumps(
                {"status": "error", "command": command, "error": str(exc)},
                ensure_ascii=False,
            )
        return json.dumps(
            {"status": "ok", "command": command, **result}, ensure_ascii=False,
        )
