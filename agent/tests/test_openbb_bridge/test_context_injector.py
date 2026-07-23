"""Unit tests for :class:`WidgetContextInjector`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("openbb_ai")

from src.openbb_bridge.context_injector import WidgetContextInjector


def _widget(name, description="", origin="", params=None):
    return SimpleNamespace(
        name=name,
        description=description,
        origin=origin,
        params=params or [],
    )


def _param(name, current_value=None):
    return SimpleNamespace(name=name, current_value=current_value)


def test_no_context_returns_message_unchanged():
    injector = WidgetContextInjector()
    request = SimpleNamespace(widgets=None, workspace_state=None, messages=[])
    assert injector.inject(request, "hello") == "hello"


def test_widget_names_are_injected():
    injector = WidgetContextInjector()
    request = SimpleNamespace(
        widgets=SimpleNamespace(
            primary=[_widget("Price Chart", "AAPL price", "openbb", [_param("symbol", "AAPL")])],
            secondary=[],
            extra=[],
        ),
        workspace_state=None,
        messages=[],
    )
    result = injector.inject(request, "What is the trend?")
    assert "Price Chart" in result
    assert "symbol=AAPL" in result
    assert result.endswith("What is the trend?")
    assert "OpenBB Workspace context" in result


def test_dashboard_info_is_injected():
    injector = WidgetContextInjector()
    request = SimpleNamespace(
        widgets=None,
        workspace_state=SimpleNamespace(
            current_dashboard_info=SimpleNamespace(
                name="My Portfolio", description="Tech holdings"
            )
        ),
        messages=[],
    )
    result = injector.inject(request, "summarize")
    assert "My Portfolio" in result


def test_widget_list_is_truncated():
    injector = WidgetContextInjector()
    widgets = [_widget(f"W{i}") for i in range(25)]
    request = SimpleNamespace(
        widgets=SimpleNamespace(primary=widgets, secondary=[], extra=[]),
        workspace_state=None,
        messages=[],
    )
    result = injector.inject(request, "q")
    assert "more widget(s)" in result


def test_prior_tool_results_are_summarised():
    injector = WidgetContextInjector()
    request = SimpleNamespace(
        widgets=None,
        workspace_state=None,
        messages=[SimpleNamespace(role="tool", function="get_price", data="123.45")],
    )
    result = injector.inject(request, "q")
    assert "get_price" in result
