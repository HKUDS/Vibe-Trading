from __future__ import annotations

import json
import logging

from src.agent.tools import ToolRegistry


def test_missing_tool_reports_matching_import_failure() -> None:
    registry = ToolRegistry()
    registry.record_import_failure(
        "options_pricing_tool",
        "ImportError: No module named 'scipy'",
    )

    payload = json.loads(registry.execute("options_pricing", {}))

    assert payload["status"] == "error"
    assert payload["registry_incomplete"] is True
    assert payload["failed_source"] == "options_pricing_tool"
    assert "No module named 'scipy'" in payload["error"]


def test_build_registry_surfaces_aggregate_failure_warning(monkeypatch, caplog) -> None:
    import src.tools as tools_module

    monkeypatch.setattr(tools_module, "_discover_subclasses", lambda: [])
    monkeypatch.setattr(
        tools_module,
        "_DISCOVERY_FAILURES",
        {"options_pricing_tool": "ImportError: missing optional dependency"},
    )
    with caplog.at_level(logging.WARNING, logger="src.tools"):
        registry = tools_module.build_registry()

    assert registry.import_failures == {
        "options_pricing_tool": "ImportError: missing optional dependency"
    }
    assert (
        "Registered 0 local tools; 1 tool source(s) failed during registry construction"
        in caplog.messages
    )


def test_discovery_names_each_failed_module_at_warning(monkeypatch, caplog) -> None:
    """Discovery must name the module that dropped out, not just count it (#1124).

    The aggregate line in ``build_registry`` reports *how many* sources failed;
    only this per-module record says *which*. Demoting it to DEBUG puts an
    operator back in front of the silent partial registry the issue is about.
    """
    import src.tools as tools_module

    real_import = tools_module.importlib.import_module
    target = "sentiment_tool"

    class _ShimImportlib:
        @staticmethod
        def import_module(name: str):
            if name == f"src.tools.{target}":
                raise ImportError("no module named 'nowhere'")
            return real_import(name)

    # Patched on this package's namespace rather than on the shared
    # ``importlib`` module, whose replacement would reach every importer in
    # the process for the duration of the test (#1123).
    monkeypatch.setattr(tools_module, "importlib", _ShimImportlib)
    monkeypatch.setattr(tools_module, "_SUBCLASSES_CACHE", None)
    monkeypatch.setattr(tools_module, "_DISCOVERY_FAILURES", {})

    with caplog.at_level(logging.WARNING, logger="src.tools"):
        tools_module._discover_subclasses()

    assert [
        message
        for message in caplog.messages
        if target in message and "no module named 'nowhere'" in message
    ], caplog.messages
    assert tools_module._DISCOVERY_FAILURES[target] == (
        "ImportError: no module named 'nowhere'"
    )
