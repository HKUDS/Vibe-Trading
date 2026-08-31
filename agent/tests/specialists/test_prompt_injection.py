"""Red tests for review finding B1: the specialist behavior contract
(``SpecialistSpec.prompt``) never reaches the sub-agent's system prompt.

``DelegateToSpecialistTool.execute()`` builds the child ``AgentLoop`` with a
filtered registry, an allowlisted skills loader and an LLM — and drops
``spec.prompt`` on the floor, so the specialist runs under the main agent's
generic system prompt instead of its own behavior contract.

These tests are TEST-FIRST and must ALL FAIL on the current code:

* (a) and (b) fail with ``TypeError`` — ``ContextBuilder`` has no
  ``system_template`` / ``role_prompt`` seam yet. Once the seam lands, both
  flip green without modification.
* (c) drives the REAL ``build_filtered_registry`` and the REAL ``AgentLoop``
  with only ``ChatLLM`` stubbed (capture-only), and fails with
  ``AssertionError`` because the marker never reaches the system-role
  message — the direct proof of B1.

Do not make these tests green by editing them; the product code changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable
from unittest.mock import patch

import pytest

from src.agent.context import ContextBuilder
from src.agent.memory import WorkspaceMemory
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse
from src.specialists.loader import reset_specialists_cache
from src.specialists.models import SpecialistSpec
from src.tools.delegate_tool import DelegateToSpecialistTool

ROLE_MARKER = "UNIQUE_BEHAVIOR_CONTRACT_MARKER"

# Frozen moment for case (a): build_system_prompt embeds the wall clock down
# to the minute (context.py:301), so a byte-identity assertion must pin it.
_FROZEN_NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)

# Case (b)'s slim specialist template. The seam contract these tests define:
# the template is ``str.format()``-ed with the same fields ``_SYSTEM_PROMPT``
# receives, plus ``{role_prompt}`` for the behavior contract.
_SLIM_TEMPLATE = """You are a domain specialist sub-agent.

## Behavior Contract

{role_prompt}

## Tools

{tool_descriptions}

## Current Date & Time

Today is {current_datetime}.
"""


@pytest.fixture(autouse=True)
def _fresh_roster():
    """Match test_delegate_tool.py: never leak the roster cache across tests."""
    reset_specialists_cache()
    yield
    reset_specialists_cache()


class _StubTool(BaseTool):
    """Minimal registry entry so the prompt's prose tool list is non-empty."""

    description = "specialist test stub tool"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, **kwargs: Any) -> str:  # pragma: no cover - never called
        return json.dumps({"status": "ok"})


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_StubTool("read_file"))
    return registry


def test_default_constructor_output_is_byte_identical_with_none_overrides() -> None:
    """(a) Adding the seam must not change the default prompt by one byte.

    Pins the real regression risk in the other direction: once
    ``system_template`` and ``role_prompt`` exist, passing ``None`` for both
    must reproduce the current default construction exactly. Today the
    keyword arguments do not exist, so this fails with ``TypeError:
    ... unexpected keyword argument ...``.
    """
    registry = _registry()
    memory = WorkspaceMemory()
    with patch("src.agent.context.datetime") as frozen_datetime:
        frozen_datetime.now.return_value = _FROZEN_NOW
        default_prompt = ContextBuilder(registry, memory).build_system_prompt()
        explicit_none_prompt = ContextBuilder(
            registry,
            memory,
            system_template=None,
            role_prompt=None,
        ).build_system_prompt()
    assert default_prompt == explicit_none_prompt


def test_system_template_and_role_prompt_reach_the_built_prompt() -> None:
    """(b) A slim template plus the role contract must shape the prompt.

    Today this fails with ``TypeError`` — the parameters do not exist.
    """
    prompt = ContextBuilder(
        _registry(),
        WorkspaceMemory(),
        system_template=_SLIM_TEMPLATE,
        role_prompt=ROLE_MARKER,
    ).build_system_prompt()

    assert ROLE_MARKER in prompt
    # The filtered registry's prose tool list survives into the prompt.
    assert "- read_file: specialist test stub tool" in prompt
    # The slim template replaces the main-agent prompt wholesale — the main
    # agent's Task Routing section must not leak into a specialist.
    assert "## Task Routing" not in prompt


class _CaptureChatLLM:
    """Constructor-compatible ChatLLM stub that records every message list.

    The ``stream_chat`` signature mirrors the real call sites in
    ``AgentLoop.run`` (src/agent/loop.py:1292 and :1346) exactly — all seven
    parameters, ``messages`` positional — so the only assertion that can
    fail is the missing marker, not the stub's interface. Returns a fixed
    terminal answer with no tool calls so the child loop finishes in one
    iteration.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name
        self.captured: list[list[dict[str, Any]]] = []
        self.closed = False

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> LLMResponse:
        self.captured.append(list(messages))
        return LLMResponse(
            content="Specialist run complete.",
            tool_calls=[],
            finish_reason="stop",
            response_model="capture-stub",
        )

    def chat(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> LLMResponse:  # pragma: no cover - fallback path
        self.captured.append(list(messages))
        return LLMResponse(content="Specialist run complete.", tool_calls=[])

    def close(self) -> None:
        self.closed = True


def test_delegate_injects_spec_prompt_into_child_system_message() -> None:
    """(c) End-to-end: the spec's prompt must reach the child's system message.

    Uses the REAL ``build_filtered_registry`` and the REAL ``AgentLoop``;
    only ``ChatLLM`` is stubbed (capture-only). On current code the marker
    in ``spec.prompt`` never reaches any system-role message, so this fails
    with ``AssertionError`` — the direct proof of B1.
    """
    spec = SpecialistSpec(
        name="marker-agent",
        description="marker specialist",
        prompt=f"You are a test specialist. {ROLE_MARKER}",
        tools=["read_file"],
        skills=["alpha-zoo"],
        max_iterations=3,
        timeout_seconds=120,
    )
    roster = {spec.name: spec}
    stub = _CaptureChatLLM()

    def _factory(model_name: str | None = None) -> _CaptureChatLLM:
        # execute() does ChatLLM(model_name=spec.model_name); route every
        # construction to the one shared stub so the test can introspect it
        # (same pattern as test_swarm_m4_e2e.py::_stub_llm_factory).
        stub.model_name = model_name
        return stub

    with (
        patch("src.tools.delegate_tool.load_specialists", lambda: roster),
        patch("src.providers.chat.ChatLLM", _factory),
    ):
        tool = DelegateToSpecialistTool()
        payload = json.loads(
            tool.execute(specialist=spec.name, task="Handle the marker task.")
        )

    assert payload["status"] == "success", payload
    assert stub.captured, "the child loop never called the LLM"
    system_contents = [
        message.get("content") or ""
        for messages in stub.captured
        for message in messages
        if message.get("role") == "system"
    ]
    assert system_contents, "the child loop sent no system message"
    assert any(ROLE_MARKER in content for content in system_contents), (
        "spec.prompt never reached the sub-agent's system prompt: "
        "delegate_tool.execute() drops the behavior contract (B1)"
    )
