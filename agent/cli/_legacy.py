"""Compatibility surface for the modular CLI command runtime.

The command implementation lives in :mod:`cli.commands.runtime` and parser
registration lives in :mod:`cli.commands.parser`. This module remains a small
import-compatible bridge for installed callers and older integrations while
new code imports the owning command modules directly.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any

from cli.commands import runtime as _runtime
from cli.commands.parser import build_parser as _build_parser_impl

# Snapshot names once so patched compatibility attributes can be synchronized
# into the runtime before a call. Module objects such as ``sys`` and
# ``subprocess`` are shared, so patching their attributes already propagates.
_EXPORT_NAMES = tuple(name for name in dir(_runtime) if not name.startswith("__") and name not in {"main", "_build_parser"})
_FUNCTION_NAMES = {name for name in _EXPORT_NAMES if inspect.isfunction(getattr(_runtime, name)) and name not in {"main", "_build_parser"}}
_ORIGINALS = {name: getattr(_runtime, name) for name in _EXPORT_NAMES}


def _sync_runtime_overrides() -> None:
    """Copy patched compatibility attributes into the owning runtime module."""
    namespace = globals()
    target_globals = [_runtime.__dict__]
    target_globals.extend(
        getattr(value, "__globals__", {})
        for value in _ORIGINALS.values()
        if inspect.isfunction(value)
    )
    for name in _EXPORT_NAMES:
        if name not in namespace:
            continue
        current = namespace[name]
        original = _ORIGINALS[name]
        desired = current
        if name in _FUNCTION_NAMES and getattr(current, "__wrapped__", None) is original:
            desired = original
        elif current is original:
            desired = original
        seen_targets: set[int] = set()
        for target in target_globals:
            if id(target) in seen_targets:
                continue
            seen_targets.add(id(target))
            if name in target:
                target[name] = desired


def _make_function(name: str, function: Any) -> Any:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        _sync_runtime_overrides()
        return getattr(_runtime, name)(*args, **kwargs)

    wrapper.__wrapped__ = function
    return wrapper


for _name in _EXPORT_NAMES:
    _value = getattr(_runtime, _name)
    globals()[_name] = _make_function(_name, _value) if _name in _FUNCTION_NAMES else _value


def _build_parser():
    return _build_parser_impl()


def main(argv: list[str] | None = None) -> int:
    _sync_runtime_overrides()
    return _runtime.main(argv)


__all__ = [name for name in _EXPORT_NAMES if not name.startswith("__")] + ["main"]
