"""Unit tests for :class:`WorkspaceContextInjector`.

The widget / dashboard / context cases are built from the real
``openbb_ai.models`` classes rather than stand-ins, so a field that the SDK does
not actually have (``DashboardInfo`` has no ``description``, for example) shows
up as a failing assertion instead of a silently empty block.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("openbb_ai")

from openbb_ai.models import (
    DashboardInfo,
    DataContent,
    LlmClientFunctionCallResultMessage,
    LlmClientMessage,
    PlaintextDataFormat,
    QueryRequest,
    RawContext,
    SingleDataContent,
    Widget,
    WidgetCollection,
    WidgetParam,
    WorkspaceState,
)

from src.openbb_bridge.context_injector import (
    DATA_TRUNCATION_MARKER,
    MAX_DATA_CHARS,
    WorkspaceContextInjector,
)


def _data_content(*payloads: str) -> DataContent:
    return DataContent(
        items=[
            SingleDataContent(
                content=payload,
                data_format=PlaintextDataFormat(data_type="md", filename="d.md"),
            )
            for payload in payloads
        ],
        extra_citations=[],
    )


def _raw_context(name: str, *payloads: str, description: str = "") -> RawContext:
    return RawContext(
        uuid=uuid.uuid4(),
        name=name,
        description=description,
        data=_data_content(*payloads),
    )


def _widget(name: str, description: str = "", origin: str = "openbb", params=None) -> Widget:
    return Widget(
        uuid=uuid.uuid4(),
        origin=origin,
        widget_id=name.lower().replace(" ", "_"),
        name=name,
        description=description,
        params=params or [],
        metadata={},
    )


def _param(name: str, current_value=None) -> WidgetParam:
    return WidgetParam(
        name=name, type="ticker", description="", current_value=current_value
    )


def _request(**kwargs) -> QueryRequest:
    kwargs.setdefault("messages", [LlmClientMessage(role="human", content="q")])
    kwargs.setdefault("workspace_options", {})
    return QueryRequest(**kwargs)


def test_no_context_returns_message_unchanged():
    injector = WorkspaceContextInjector()
    assert injector.inject(_request(), "hello") == "hello"


def test_widget_names_and_params_are_injected():
    injector = WorkspaceContextInjector()
    request = _request(
        widgets=WidgetCollection(
            primary=[
                _widget("Price Chart", "AAPL price", params=[_param("symbol", "AAPL")])
            ],
            secondary=[],
            extra=[],
        )
    )
    result = injector.inject(request, "What is the trend?")

    assert "Price Chart" in result
    assert "symbol=AAPL" in result
    assert result.endswith("What is the trend?")
    assert "OpenBB Workspace context" in result


def test_widget_block_states_that_values_are_not_attached():
    """Guards against the model inventing widget values it never received."""
    injector = WorkspaceContextInjector()
    request = _request(
        widgets=WidgetCollection(primary=[_widget("Price Chart")], secondary=[], extra=[])
    )
    result = injector.inject(request, "q")

    assert "NOT attached" in result


def test_dashboard_name_and_tab_are_injected():
    injector = WorkspaceContextInjector()
    request = _request(
        workspace_state=WorkspaceState(
            current_dashboard_info=DashboardInfo(
                id="dash-1", name="My Portfolio", current_tab_id="tab-1"
            )
        )
    )
    result = injector.inject(request, "summarize")

    assert "My Portfolio" in result
    assert "tab-1" in result


def test_widget_list_is_truncated():
    injector = WorkspaceContextInjector()
    request = _request(
        widgets=WidgetCollection(
            primary=[_widget(f"W{i}") for i in range(25)], secondary=[], extra=[]
        )
    )
    result = injector.inject(request, "q")

    assert "more widget(s)" in result


def test_attached_context_data_is_ingested_verbatim():
    """``QueryRequest.context`` is the only place real values arrive."""
    injector = WorkspaceContextInjector()
    request = _request(
        context=[_raw_context("Prices", "AAPL,190.5\nMSFT,410.2", description="table")]
    )
    result = injector.inject(request, "which is cheaper?")

    assert "Prices" in result
    assert "AAPL,190.5" in result
    assert "MSFT,410.2" in result
    assert result.endswith("which is cheaper?")


def test_attached_context_data_is_bounded_with_a_marker():
    injector = WorkspaceContextInjector()
    payload = "P" * (MAX_DATA_CHARS * 3)
    request = _request(context=[_raw_context("Huge", payload)])
    result = injector.inject(request, "q")

    assert DATA_TRUNCATION_MARKER in result
    assert result.count(DATA_TRUNCATION_MARKER) == 1
    # The budget bounds the payload; headers and the marker are the only extras.
    assert result.count("P") == MAX_DATA_CHARS
    assert len(result) < MAX_DATA_CHARS + 500


def test_data_budget_is_shared_across_context_items():
    injector = WorkspaceContextInjector()
    request = _request(
        context=[
            _raw_context("First", "P" * MAX_DATA_CHARS),
            _raw_context("Second", "SECOND_ITEM_SENTINEL"),
        ]
    )
    result = injector.inject(request, "q")

    assert result.count("P") == MAX_DATA_CHARS
    assert "SECOND_ITEM_SENTINEL" not in result
    assert DATA_TRUNCATION_MARKER in result


def test_tool_result_payloads_are_extracted_not_reprd():
    injector = WorkspaceContextInjector()
    tool_message = LlmClientFunctionCallResultMessage(
        function="get_widget_data",
        input_arguments={},
        data=[_data_content("AAPL,190.5")],
        extra_state={},
    )
    request = _request(
        messages=[
            LlmClientMessage(role="human", content="q1"),
            tool_message,
            LlmClientMessage(role="human", content="q2"),
        ]
    )
    result = injector.inject(request, "q2")

    assert "get_widget_data" in result
    assert "AAPL,190.5" in result
    # A bare repr of the pydantic list would leak class names into the prompt.
    assert "DataContent(" not in result


def test_injection_never_raises_on_a_malformed_request():
    injector = WorkspaceContextInjector()
    broken = SimpleNamespace(context=object(), widgets=object(), workspace_state=object())

    assert injector.inject(broken, "hello") == "hello"
