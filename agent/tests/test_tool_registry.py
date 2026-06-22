"""Unit tests for BaseTool and ToolRegistry."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from src.agent.tools import BaseTool, ToolRegistry


# ---------------------------------------------------------------------------
# Stub tools
# ---------------------------------------------------------------------------


class EchoTool(BaseTool):
    """Simple tool that echoes its input as JSON."""

    name = "echo"
    description = "Echoes input back"
    parameters = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    }

    def execute(self, **kwargs: Any) -> str:
        return json.dumps({"status": "ok", "echo": kwargs.get("message", "")})


class FailingTool(BaseTool):
    """Tool that always raises an exception."""

    name = "fail"
    description = "Always fails"

    def execute(self, **kwargs: Any) -> str:
        raise RuntimeError("something went wrong")


class NoParamsTool(BaseTool):
    """Tool with no parameters defined."""

    name = "noop"
    description = "Does nothing"
    parameters: Dict[str, Any] = {}

    def execute(self, **kwargs: Any) -> str:
        return json.dumps({"status": "ok"})


class AddTool(BaseTool):
    """Tool that adds two numbers, used to verify kwargs passing."""

    name = "add"
    description = "Adds a and b"
    parameters = {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    }

    def execute(self, **kwargs: Any) -> str:
        result = kwargs["a"] + kwargs["b"]
        return json.dumps({"status": "ok", "result": result})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def echo_tool() -> EchoTool:
    return EchoTool()


@pytest.fixture
def failing_tool() -> FailingTool:
    return FailingTool()


# ---------------------------------------------------------------------------
# BaseTool tests
# ---------------------------------------------------------------------------


class TestBaseTool:
    def test_check_available_default_returns_true(self) -> None:
        assert EchoTool.check_available() is True

    def test_to_openai_schema_format(self, echo_tool: EchoTool) -> None:
        schema = echo_tool.to_openai_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "echo"
        assert schema["function"]["description"] == "Echoes input back"
        assert schema["function"]["parameters"] == echo_tool.parameters

    def test_to_openai_schema_empty_params(self) -> None:
        tool = NoParamsTool()
        schema = tool.to_openai_schema()

        expected_params = {"type": "object", "properties": {}, "required": []}
        assert schema["function"]["parameters"] == expected_params


# ---------------------------------------------------------------------------
# ToolRegistry registration tests
# ---------------------------------------------------------------------------


class TestToolRegistryRegistration:
    def test_register_adds_tool(self, registry: ToolRegistry, echo_tool: EchoTool) -> None:
        registry.register(echo_tool)
        assert registry.get("echo") is echo_tool

    def test_register_duplicate_name_overwrites(self, registry: ToolRegistry) -> None:
        tool_a = EchoTool()
        tool_b = EchoTool()
        registry.register(tool_a)
        registry.register(tool_b)

        assert registry.get("echo") is tool_b

    def test_get_unregistered_returns_none(self, registry: ToolRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_len_reflects_registered_count(self, registry: ToolRegistry) -> None:
        assert len(registry) == 0
        registry.register(EchoTool())
        assert len(registry) == 1
        registry.register(AddTool())
        assert len(registry) == 2

    def test_contains_checks_registration(self, registry: ToolRegistry, echo_tool: EchoTool) -> None:
        assert "echo" not in registry
        registry.register(echo_tool)
        assert "echo" in registry
        assert "unknown" not in registry


# ---------------------------------------------------------------------------
# ToolRegistry execution tests
# ---------------------------------------------------------------------------


class TestToolRegistryExecution:
    def test_execute_calls_tool_and_returns_result(self, registry: ToolRegistry, echo_tool: EchoTool) -> None:
        registry.register(echo_tool)
        result = registry.execute("echo", {"message": "hello"})
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["echo"] == "hello"

    def test_execute_unknown_tool_returns_error_json(self, registry: ToolRegistry) -> None:
        result = registry.execute("ghost", {})
        data = json.loads(result)

        assert data["status"] == "error"
        assert "ghost" in data["error"]

    def test_execute_exception_returns_error_json(self, registry: ToolRegistry, failing_tool: FailingTool) -> None:
        registry.register(failing_tool)
        result = registry.execute("fail", {})
        data = json.loads(result)

        assert data["status"] == "error"
        assert data["tool"] == "fail"

    def test_execute_exception_preserves_message(self, registry: ToolRegistry, failing_tool: FailingTool) -> None:
        registry.register(failing_tool)
        result = registry.execute("fail", {})
        data = json.loads(result)

        assert data["error"] == "something went wrong"

    def test_execute_passes_params_as_kwargs(self, registry: ToolRegistry) -> None:
        registry.register(AddTool())
        result = registry.execute("add", {"a": 3, "b": 7})
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["result"] == 10


# ---------------------------------------------------------------------------
# get_definitions tests
# ---------------------------------------------------------------------------


class TestGetDefinitions:
    def test_get_definitions_returns_all_schemas(self, registry: ToolRegistry) -> None:
        registry.register(EchoTool())
        registry.register(AddTool())
        defs = registry.get_definitions()

        assert len(defs) == 2
        names = {d["function"]["name"] for d in defs}
        assert names == {"echo", "add"}

    def test_get_definitions_empty_registry(self, registry: ToolRegistry) -> None:
        assert registry.get_definitions() == []


# ---------------------------------------------------------------------------
# tool_names property tests
# ---------------------------------------------------------------------------


class TestToolNames:
    def test_tool_names_returns_registered_names(self, registry: ToolRegistry) -> None:
        registry.register(EchoTool())
        registry.register(AddTool())

        names = registry.tool_names
        assert set(names) == {"echo", "add"}
