"""Reach the finance-math layer from every transport, without a shell.

``src/quantlib`` holds ~250 tested functions, and until now the only way an
agent could run them was ``bash`` plus an ``import``. That gate is off by
default on the API and MCP transports, and correctly so: process-control tools
are an RCE surface regardless of transport, and force-enabling them on stdio was
the subject of two published advisories (see
``mcp_server._resolve_include_shell_tools``). So on Web, API and MCP the maths
layer was simply unreachable.

Widening the shell gate to fix that would trade a real security property for a
convenience. This tool takes the other route: one stable contract that can call
any *public* function of an allowlisted quantlib module, and nothing else.

WHY THIS IS NOT ARBITRARY CODE EXECUTION
----------------------------------------
Three structural limits, in order of what they rule out:

1. **Module allowlist.** Only the modules in :data:`ALLOWED_MODULES` are
   reachable. There is no path from a caller-supplied string to an arbitrary
   import -- the string is looked up in a dict, never passed to ``importlib``.
2. **``__all__`` only.** Within a module, only names the module itself exports
   are callable. A private helper, a re-exported third-party symbol, or a
   dunder is not reachable.
3. **No file-writing entry points.** Names matching :data:`_WRITER_PREFIXES` are
   refused even when exported, because they take a destination path. Everything
   left is pure computation: no filesystem, no network, no process. Use
   ``write_file`` if a file is what you want.

WHAT THIS DOES NOT DO
---------------------
It does not fetch data. Every argument comes from the caller, which usually
means a data tool ran first. A function that needs a price history needs you to
have retrieved that history.

PASSING PANDAS OBJECTS OVER JSON
--------------------------------
Several functions need a real indexed ``Series`` or ``DataFrame``, and a bare
JSON list loses the index -- which for an event study or a cash-flow series is
the part that carries the meaning. Two envelopes are therefore understood
anywhere in ``kwargs``::

    {"__series__": {"index": [...], "values": [...]}}
    {"__dataframe__": {"index": [...], "columns": [...], "data": [[...], ...]}}

A plain list stays a plain list, because most functions accept a sequence and
coercing every list into a Series would break the ones that do not.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import math
from enum import Enum
from typing import Any

from src.agent.tools import BaseTool

__all__ = ["ALLOWED_MODULES", "QuantlibCallTool"]

#: Short name -> dotted module path. A caller names the short form; nothing a
#: caller sends is ever handed to ``importlib``.
ALLOWED_MODULES: dict[str, str] = {
    "options": "src.quantlib.options",
    "fixedincome": "src.quantlib.fixedincome",
    "credit": "src.quantlib.credit",
    "timeseries": "src.quantlib.timeseries",
    "risk": "src.quantlib.risk",
    "var_backtest": "src.quantlib.var_backtest",
    "attribution": "src.quantlib.attribution",
    "impact": "src.quantlib.impact",
    "fundmath": "src.quantlib.fundmath",
    "performance": "src.quantlib.performance",
    "eventstudy": "src.quantlib.eventstudy",
    "factormodel": "src.quantlib.factormodel",
    "multipletesting": "src.quantlib.multipletesting",
    "crossvalidation": "src.quantlib.crossvalidation",
    "valuation.dcf": "src.quantlib.valuation.dcf",
    "valuation.comps": "src.quantlib.valuation.comps",
    "valuation.threestatement": "src.quantlib.valuation.threestatement",
    "valuation.artifact": "src.quantlib.valuation.artifact",
    "valuation.contracts": "src.quantlib.valuation.contracts",
}

#: Exported names refused because they write to a caller-supplied path. This
#: tool stays pure-compute; file creation belongs to ``write_file``.
_WRITER_PREFIXES: tuple[str, ...] = ("export_",)

#: Largest number of leaf values serialized back to the caller. A factor panel
#: or a full CSCV logit vector can be enormous, and silently returning 200k
#: numbers into a context window helps nobody.
_MAX_RESULT_LEAVES = 5000


def _import_module(short_name: str) -> Any:
    """Import an allowlisted module by its short name.

    Args:
        short_name: Key of :data:`ALLOWED_MODULES`.

    Returns:
        The imported module.

    Raises:
        KeyError: If the name is not allowlisted.
    """
    import importlib

    return importlib.import_module(ALLOWED_MODULES[short_name])


def _public_names(module: Any) -> list[str]:
    """Callable public names of a module, writers excluded.

    Args:
        module: An imported quantlib module.

    Returns:
        Sorted names from ``__all__`` that are callable and not file writers.
    """
    exported = getattr(module, "__all__", [])
    out = []
    for name in exported:
        if name.startswith(_WRITER_PREFIXES):
            continue
        obj = getattr(module, name, None)
        if callable(obj):
            out.append(name)
    return sorted(out)


def _decode(value: Any) -> Any:
    """Turn JSON envelopes into the pandas objects some functions require.

    Args:
        value: A decoded-JSON value, possibly a ``__series__`` or
            ``__dataframe__`` envelope, possibly nested inside a container.

    Returns:
        The value with any envelope replaced by the pandas object it describes.

    Raises:
        ValueError: If an envelope is malformed.
    """
    import pandas as pd

    if isinstance(value, dict):
        if "__series__" in value:
            spec = value["__series__"]
            if not isinstance(spec, dict) or "values" not in spec:
                raise ValueError("__series__ needs a 'values' list")
            return pd.Series(spec["values"], index=spec.get("index"))
        if "__dataframe__" in value:
            spec = value["__dataframe__"]
            if not isinstance(spec, dict) or "data" not in spec:
                raise ValueError("__dataframe__ needs a 'data' list of rows")
            return pd.DataFrame(
                spec["data"], index=spec.get("index"), columns=spec.get("columns")
            )
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


class _Budget:
    """Mutable leaf counter shared across one serialization pass."""

    def __init__(self) -> None:
        self.leaves = 0
        self.truncated = False


def _encode(value: Any, budget: _Budget) -> Any:
    """Serialize a quantlib result into JSON-safe data.

    Dataclasses become dicts, enums become their value, numpy and pandas objects
    become plain containers, and non-finite floats become explicit strings so a
    NaN cannot arrive at the caller as ``null`` and read as "absent".

    Args:
        value: Anything a quantlib function returns.
        budget: Shared leaf counter; once exhausted, containers are truncated
            and the fact is reported rather than hidden.

    Returns:
        A JSON-serializable structure.
    """
    import numpy as np
    import pandas as pd

    if budget.leaves >= _MAX_RESULT_LEAVES:
        budget.truncated = True
        return "<truncated>"

    if value is None or isinstance(value, (bool, int, str)):
        budget.leaves += 1
        return value
    if isinstance(value, float):
        budget.leaves += 1
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, Enum):
        budget.leaves += 1
        return value.value
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return _encode(value.item(), budget)
    if isinstance(value, np.ndarray):
        return [_encode(v, budget) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return {
            "__series__": {
                "index": [_encode(i, budget) for i in value.index.tolist()],
                "values": [_encode(v, budget) for v in value.tolist()],
            }
        }
    if isinstance(value, pd.DataFrame):
        return {
            "__dataframe__": {
                "index": [_encode(i, budget) for i in value.index.tolist()],
                "columns": [str(c) for c in value.columns],
                "data": [[_encode(v, budget) for v in row] for row in value.to_numpy().tolist()],
            }
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _encode(getattr(value, f.name), budget)
            for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(k): _encode(v, budget) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_encode(v, budget) for v in value]

    budget.leaves += 1
    return str(value)


class QuantlibCallTool(BaseTool):
    """Call any public function of the tested finance-math layer."""

    name = "quantlib_call"
    description = (
        "Run a function from the tested finance-math library (src/quantlib): "
        "Black-Scholes and implied vol, bond math and curve fitting, Altman Z "
        "and Merton/KMV, stationarity/cointegration/GARCH/regime switching, "
        "VaR/CVaR/EVT and VaR backtesting (Kupiec/Christoffersen/Basel), "
        "Brinson-Fachler attribution, market impact, fund maths "
        "(XIRR/MOIC/DPI/TVPI/PME/waterfalls), TWR/Dietz/MWR, event studies "
        "(CAR/CAAR/Patell/BMP), style factor models, deflated Sharpe and PBO, "
        "purged cross-validation, and the valuation engine (DCF / comps / "
        "three-statement). Read-only and pure-compute: it fetches no data and "
        "writes no files. Start with action='list' to see modules, then "
        "action='list' with a module to see its functions, then "
        "action='describe' for a signature. "
        'Example: quantlib_call(action="call", module="risk", '
        'function="historical_var", kwargs={"returns": [0.01, -0.02], "confidence": 0.95}).'
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "describe", "call"],
                "description": (
                    "'list' enumerates modules (or a module's functions when "
                    "'module' is given); 'describe' returns one function's "
                    "signature and docstring; 'call' runs it."
                ),
                "default": "list",
            },
            "module": {
                "type": "string",
                "description": (
                    "Short module name, e.g. 'risk', 'options', 'valuation.dcf'. "
                    "Required for 'describe' and 'call'."
                ),
            },
            "function": {
                "type": "string",
                "description": "Public function name. Required for 'describe' and 'call'.",
            },
            "kwargs": {
                "type": "object",
                "description": (
                    "Keyword arguments. Pass an indexed pandas Series as "
                    '{"__series__": {"index": [...], "values": [...]}} and a '
                    'DataFrame as {"__dataframe__": {"index": [...], '
                    '"columns": [...], "data": [[...]]}}; a plain list stays a list.'
                ),
                "default": {},
            },
        },
        "required": ["action"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Dispatch a list / describe / call request.

        Args:
            **kwargs: See :attr:`parameters`.

        Returns:
            A JSON envelope. Every failure path returns ``ok=false`` with an
            actionable ``error`` rather than raising, matching the other
            read-only tools.
        """
        action = str(kwargs.get("action") or "list").strip().lower()
        module_name = kwargs.get("module")
        function_name = kwargs.get("function")

        try:
            if action == "list":
                return self._list(module_name)
            if action not in ("describe", "call"):
                return self._error(f"unknown action {action!r}; use list, describe or call")
            if not module_name or not function_name:
                return self._error(f"action='{action}' needs both 'module' and 'function'")

            resolved = self._resolve(str(module_name), str(function_name))
            if isinstance(resolved, str):
                return resolved
            func = resolved

            if action == "describe":
                return self._describe(str(module_name), str(function_name), func)
            return self._call(str(module_name), str(function_name), func, kwargs.get("kwargs") or {})
        except Exception as exc:  # noqa: BLE001 - envelope, never raise to the loop
            return self._error(f"{type(exc).__name__}: {exc}")

    def _resolve(self, module_name: str, function_name: str) -> Any:
        """Look up a callable, or return an error envelope string.

        Args:
            module_name: Short module name.
            function_name: Public function name.

        Returns:
            The callable, or a JSON error envelope string.
        """
        if module_name not in ALLOWED_MODULES:
            return self._error(
                f"unknown module {module_name!r}; available: {sorted(ALLOWED_MODULES)}"
            )
        module = _import_module(module_name)
        allowed = _public_names(module)
        if function_name not in allowed:
            if function_name.startswith(_WRITER_PREFIXES):
                return self._error(
                    f"{function_name!r} writes to a path and is not callable here; "
                    "this tool is pure-compute"
                )
            return self._error(
                f"{function_name!r} is not a public function of {module_name!r}; "
                f"available: {allowed}"
            )
        return getattr(module, function_name)

    def _list(self, module_name: Any) -> str:
        """List modules, or one module's public functions."""
        if not module_name:
            return json.dumps(
                {
                    "ok": True,
                    "modules": sorted(ALLOWED_MODULES),
                    "hint": "call again with module=<name> to list its functions",
                },
                ensure_ascii=False,
            )
        name = str(module_name)
        if name not in ALLOWED_MODULES:
            return self._error(f"unknown module {name!r}; available: {sorted(ALLOWED_MODULES)}")
        module = _import_module(name)
        functions = []
        for fn_name in _public_names(module):
            fn = getattr(module, fn_name)
            doc = (inspect.getdoc(fn) or "").strip().splitlines()
            functions.append({"name": fn_name, "summary": doc[0] if doc else ""})
        return json.dumps(
            {"ok": True, "module": name, "functions": functions}, ensure_ascii=False
        )

    def _describe(self, module_name: str, function_name: str, func: Any) -> str:
        """Return one function's signature and docstring."""
        try:
            signature = str(inspect.signature(func))
        except (TypeError, ValueError):
            signature = "(signature unavailable)"
        return json.dumps(
            {
                "ok": True,
                "module": module_name,
                "function": function_name,
                "signature": signature,
                "doc": inspect.getdoc(func) or "",
            },
            ensure_ascii=False,
        )

    def _call(self, module_name: str, function_name: str, func: Any, raw_kwargs: Any) -> str:
        """Run the function and serialize its result."""
        if not isinstance(raw_kwargs, dict):
            return self._error("'kwargs' must be an object")
        try:
            decoded = {str(k): _decode(v) for k, v in raw_kwargs.items()}
        except ValueError as exc:
            return self._error(f"bad argument envelope: {exc}")

        try:
            result = func(**decoded)
        except TypeError as exc:
            # Almost always a wrong/missing argument; hand back the signature so
            # the next attempt is informed rather than another guess.
            try:
                signature = str(inspect.signature(func))
            except (TypeError, ValueError):
                signature = "(signature unavailable)"
            return self._error(f"{exc}", signature=signature)
        except Exception as exc:  # noqa: BLE001
            # A domain refusal (bad confidence level, missing input, no sign
            # change) is information, not a crash: surface it verbatim.
            return self._error(f"{type(exc).__name__}: {exc}")

        budget = _Budget()
        payload = {
            "ok": True,
            "module": module_name,
            "function": function_name,
            "result": _encode(result, budget),
        }
        if budget.truncated:
            payload["truncated"] = True
            payload["truncation_note"] = (
                f"result exceeded {_MAX_RESULT_LEAVES} values and was truncated; "
                "narrow the inputs or request a summary statistic instead"
            )
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _error(message: str, **extra: Any) -> str:
        """Build a uniform failure envelope."""
        return json.dumps({"ok": False, "error": message, **extra}, ensure_ascii=False)
