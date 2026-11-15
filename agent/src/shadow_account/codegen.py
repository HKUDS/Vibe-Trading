"""Shadow Account — code generation (rules → signal_engine.py + config.json).

Inputs are always a ``ShadowProfile`` (contract-stable). Outputs are:
    * ``signal_engine.py`` source, validated with ``ast.parse`` + a shape
      check on ``class SignalEngine.generate``.
    * ``config.json`` dict, ready to drop into a run_dir.

No external I/O here — callers (backtester) are responsible for writing
files and launching ``run_backtest``.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.shadow_account.models import (
    PRICE_FEATURES,
    ShadowProfile,
    ShadowRule,
    canonical_comparison,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SIGNAL_ENGINE_TEMPLATE = "signal_engine.py.j2"


def _literal_safe_value(value: Any) -> Any:
    """Return a value that can be faithfully represented as a Python literal."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite floats cannot be rendered as Python literals")
        return value
    if isinstance(value, list):
        return [_literal_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_literal_safe_value(item) for item in value)
    if isinstance(value, dict):
        return {
            _literal_safe_value(key): _literal_safe_value(item)
            for key, item in value.items()
        }
    raise TypeError(
        f"Unsupported generated Python literal type: {type(value).__name__}",
    )


def _python_literal(value: Any) -> str:
    """Render ``value`` as source text for a safe Python literal."""
    literal = repr(_literal_safe_value(value))
    try:
        ast.literal_eval(literal)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Invalid generated Python literal: {literal!r}") from exc
    return literal


def _env() -> Environment:
    """Jinja2 environment rooted at our templates directory."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["py_literal"] = _python_literal
    return env


def _finite_number(value: Any) -> float | None:
    """Return *value* as a finite float, or ``None`` when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _unsupported_bound(feature: str, bounds: Any) -> ValueError:
    """Build the refusal for a condition the template cannot express exactly."""
    return ValueError(
        f"entry_condition[{feature!r}] = {bounds!r} cannot be expressed by the "
        "signal-engine template, which supports inclusive bounds only "
        "('>=' / '<=' or {\"min\", \"max\"})"
    )


def _inclusive_slot(op: Any) -> str | None:
    """Map an inclusive comparison operator to a template bound slot."""
    return {">=": "min", "<=": "max"}.get(canonical_comparison(op) or "")


def _pair_or_scalar_bound(feature: str, bounds: Any) -> tuple[str, float]:
    """Map one ``(op, value)`` pair or bare scalar to a single bound slot.

    A bare scalar means ``>=``, which is how the scanner reads one.

    Args:
        feature: The ``PRICE_FEATURES`` name the condition belongs to.
        bounds: The condition as the profile states it.

    Returns:
        ``("min" | "max", threshold)``.

    Raises:
        ValueError: If the pair is malformed or its operator has no exact
            inclusive representation.
    """
    if isinstance(bounds, (list, tuple)):
        if len(bounds) < 2:
            raise _unsupported_bound(feature, bounds)
        slot = _inclusive_slot(bounds[0])
        threshold = _finite_number(bounds[1])
    else:
        slot, threshold = "min", _finite_number(bounds)
    if slot is None or threshold is None:
        raise _unsupported_bound(feature, bounds)
    return slot, threshold


def _rule_to_context(rule: ShadowRule) -> dict[str, Any]:
    """Flatten a ShadowRule into the scalar fields the template consumes.

    A condition that names a price feature must either become a bound the
    template can express or be refused: a bound the template silently ignores
    would backtest the rule wider than the profile states it. ``None`` means
    "no bound" and is not an error.

    Args:
        rule: The rule to flatten.

    Returns:
        Scalar context for the signal-engine template.

    Raises:
        ValueError: If ``market`` is not a string, or a price-feature
            condition cannot be expressed as an inclusive bound.
    """
    market = rule.entry_condition.get("market", "other")
    if not isinstance(market, str):
        raise ValueError(
            f"entry_condition['market'] = {market!r} must be a string; a "
            "comparison cannot name a market bucket"
        )
    hour = rule.entry_condition.get("entry_hour") or {}
    hold_lo, hold_hi = rule.holding_days_range
    hold_days = max(1, int(round((hold_lo + hold_hi) / 2)))
    ctx: dict[str, Any] = {
        "rule_id": rule.rule_id,
        "market": market,
        "entry_hour_min": int(hour.get("min", 0)),
        "entry_hour_max": int(hour.get("max", 23)),
        "hold_days": hold_days,
        "weight": float(rule.weight),
    }
    for feature in PRICE_FEATURES:
        bounds = rule.entry_condition.get(feature)
        if bounds is None:
            continue
        if isinstance(bounds, dict):
            for slot in ("min", "max"):
                if slot not in bounds or bounds[slot] is None:
                    continue
                threshold = _finite_number(bounds[slot])
                if threshold is None:
                    raise _unsupported_bound(feature, bounds)
                ctx[f"{feature}_{slot}"] = threshold
            continue
        slot, threshold = _pair_or_scalar_bound(feature, bounds)
        ctx[f"{feature}_{slot}"] = threshold
    return ctx


def render_signal_engine(profile: ShadowProfile) -> str:
    """Render the SignalEngine Python source for a profile.

    Args:
        profile: ShadowProfile carrying the rules to replay.

    Returns:
        Python source string. The caller is expected to ``validate_generated``
        before writing to disk.

    Raises:
        ValueError: If a rule carries a condition the template cannot express
            exactly as an inclusive bound (see ``_rule_to_context``).
    """
    template = _env().get_template(_SIGNAL_ENGINE_TEMPLATE)
    return template.render(
        shadow_id=profile.shadow_id,
        profitable_roundtrips=profile.profitable_roundtrips,
        date_range=list(profile.date_range),
        preferred_markets=list(profile.preferred_markets),
        rules=[_rule_to_context(r) for r in profile.rules],
    )


def validate_generated(source: str) -> tuple[bool, str]:
    """Static-check a generated signal_engine source.

    Checks:
        1. ``ast.parse`` succeeds.
        2. Module defines ``class SignalEngine``.
        3. ``SignalEngine`` has a ``generate`` method with one positional
           arg besides self.

    Returns:
        (ok, error_msg). ``error_msg`` is empty on success.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"

    signal_cls: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SignalEngine":
            signal_cls = node
            break
    if signal_cls is None:
        return False, "class SignalEngine not found"

    generate: ast.FunctionDef | None = None
    for node in signal_cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == "generate":
            generate = node
            break
    if generate is None:
        return False, "SignalEngine.generate method not found"

    non_self_args = [a for a in generate.args.args if a.arg != "self"]
    if len(non_self_args) < 1:
        return False, "SignalEngine.generate must accept a data_map argument"
    return True, ""


def render_config(
    profile: ShadowProfile,
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    initial_capital: float = 1_000_000.0,
    interval: str = "1D",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``config.json`` dict for a shadow backtest run.

    Args:
        profile: ShadowProfile (used only for metadata, not for engine logic).
        codes: Symbols to backtest across.
        start_date / end_date: ISO dates.
        source: Loader source; ``auto`` routes by symbol suffix.
        initial_capital: Starting cash.
        interval: Bar size (daily default).
        extra: Arbitrary overrides merged last.
    """
    cfg: dict[str, Any] = {
        "source": source,
        "codes": codes,
        "start_date": start_date,
        "end_date": end_date,
        "interval": interval,
        "initial_cash": initial_capital,
        "engine": "daily",
        "shadow_id": profile.shadow_id,
    }
    if extra:
        cfg.update(extra)
    return cfg


def write_run_dir(
    profile: ShadowProfile,
    run_dir: Path,
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    initial_capital: float = 1_000_000.0,
) -> Path:
    """Materialize a full run_dir with ``code/signal_engine.py`` + ``config.json``.

    Raises:
        ValueError: Generated signal_engine fails static validation, or
            ``render_signal_engine`` refuses a condition the template cannot
            express (the refusal propagates from here; callers are
            ``backtester.py`` and the ``shadow_account_tool`` backtest tool).
    """
    run_dir = Path(run_dir)
    (run_dir / "code").mkdir(parents=True, exist_ok=True)

    source_code = render_signal_engine(profile)
    ok, err = validate_generated(source_code)
    if not ok:
        raise ValueError(f"Generated signal_engine failed validation: {err}")

    (run_dir / "code" / "signal_engine.py").write_text(source_code, encoding="utf-8")
    cfg = render_config(
        profile,
        codes=codes,
        start_date=start_date,
        end_date=end_date,
        source=source,
        initial_capital=initial_capital,
    )
    (run_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return run_dir
