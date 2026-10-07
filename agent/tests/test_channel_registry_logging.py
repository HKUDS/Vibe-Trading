"""A failed channel load must produce a readable log, not a logging crash.

``logger.warning("... '%s': %s", name, exc_info=True)`` supplies only one
positional argument for two ``%s`` placeholders. ``logging`` formats lazily,
so this doesn't raise where it's called -- it raises inside the handler's
``emit()``, which swallows it and prints "--- Logging error ---" instead of
the message. The diagnostic the operator needed (which plugin, and why) never
reaches the log.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

from src.channels import registry


class _FailingEntryPoint:
    name = "broken_plugin"

    def load(self) -> Any:
        raise RuntimeError("boom")


def test_discover_plugins_logs_the_failure_reason_without_crashing(monkeypatch, caplog):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: (
            [_FailingEntryPoint()] if group == "vibe_trading.channels" else []
        ),
    )

    with caplog.at_level("WARNING", logger="src.channels.registry"):
        plugins = registry.discover_plugins()

    assert plugins == {}
    messages = [record.getMessage() for record in caplog.records]
    assert any("broken_plugin" in m and "boom" in m for m in messages), messages


def test_discover_enabled_logs_the_skip_reason_without_crashing(monkeypatch, caplog):
    def _boom(module_name: str) -> Any:
        raise ImportError("missing optional sdk")

    monkeypatch.setattr(registry, "load_channel_class", _boom)
    monkeypatch.setattr(registry, "discover_plugins", lambda *a, **k: {})

    with caplog.at_level("DEBUG", logger="src.channels.registry"):
        result = registry.discover_enabled(
            {"broken_channel"}, _names=["broken_channel"]
        )

    assert result == {}
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "broken_channel" in m and "missing optional sdk" in m for m in messages
    ), messages
