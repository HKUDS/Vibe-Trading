"""Frozen-contract tests for Strategy Discovery prompt routing — issue #969.

AC2 (routing validated at startup): ``ContextBuilder.build_system_prompt()``
must include the Strategy Discovery routing block when — and only when — all
three tools are present in the tool registry, and must degrade to a clean
prompt (no block, no crash) when ``src.strategy_discovery`` cannot be
imported. The expected block text is derived from
``src.strategy_discovery.guard.routing_block`` so these tests stay decoupled
from the block's exact wording.

Registries are real ``ToolRegistry`` objects with minimal ``BaseTool``
stubs; ``SkillsLoader`` points at empty tmp dirs so no bundled skill scan or
network can affect the prompt. No wall-clock assertions.
"""

from __future__ import annotations

import inspect
import json
import sys

import pytest

from src.agent.context import ContextBuilder
from src.agent.memory import WorkspaceMemory
from src.agent.skills import SkillsLoader
from src.agent.tools import BaseTool, ToolRegistry

try:
    from src.strategy_discovery import guard as sd_guard

    GUARD_AVAILABLE = True
except ImportError:
    sd_guard = None
    GUARD_AVAILABLE = False

SD_TOOLS = ("list_strategies", "query_strategies", "get_strategy_evidence")


class _StubTool(BaseTool):
    description = "strategy discovery stub"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, **kwargs) -> str:
        return json.dumps({"status": "ok"})


def _registry_with(names) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(_StubTool(name))
    return registry


def _context_module():
    from src.agent import context as context_mod

    return context_mod


def _wiring_landed() -> bool:
    if not GUARD_AVAILABLE:
        return False
    try:
        source = inspect.getsource(_context_module())
    except OSError:
        return False
    return "strategy_discovery" in source


requires_routing = pytest.mark.skipif(
    not _wiring_landed(),
    reason=(
        "waiting on sibling A+B: src.strategy_discovery.guard and/or the "
        "src.agent.context Strategy Discovery routing wiring not landed yet (issue #969)"
    ),
)


@pytest.fixture
def builder_factory(tmp_path):
    """Build ContextBuilders over empty skill dirs (hermetic, offline)."""

    def _build(registry: ToolRegistry) -> ContextBuilder:
        empty_bundled = tmp_path / "bundled_skills"
        empty_user = tmp_path / "user_skills"
        empty_bundled.mkdir(exist_ok=True)
        empty_user.mkdir(exist_ok=True)
        return ContextBuilder(
            registry=registry,
            memory=WorkspaceMemory(),
            skills_loader=SkillsLoader(
                skills_dir=empty_bundled, user_skills_dir=empty_user
            ),
        )

    return _build


@requires_routing
class TestRoutingBlockInPrompt:
    def test_block_present_when_all_tools_registered(self, builder_factory) -> None:
        registry = _registry_with(SD_TOOLS)
        expected_block = sd_guard.routing_block(registry)
        assert (
            expected_block.strip()
        ), "guard block must be non-empty for a full registry"

        prompt = builder_factory(registry).build_system_prompt()
        assert expected_block in prompt, (
            "build_system_prompt() must embed the guard routing block when all "
            "Strategy Discovery tools are registered"
        )
        for tool_name in SD_TOOLS:
            assert tool_name in prompt

    def test_block_absent_when_tools_missing(self, builder_factory) -> None:
        partial = _registry_with(("list_strategies",))
        full = _registry_with(SD_TOOLS)
        full_block = sd_guard.routing_block(full)
        assert full_block.strip()

        prompt = builder_factory(partial).build_system_prompt()
        assert (
            full_block not in prompt
        ), "routing block must be omitted when tools are missing (fail-safe, AC2)"
        # Tools absent from the registry must not be advertised anywhere.
        assert "query_strategies" not in prompt
        assert "get_strategy_evidence" not in prompt

    def test_prompt_still_builds_when_strategy_discovery_import_raises(
        self, builder_factory, monkeypatch
    ) -> None:
        context_mod = _context_module()
        registry = _registry_with(SD_TOOLS)
        full_block = sd_guard.routing_block(registry)

        def _raiser(*args, **kwargs):
            raise RuntimeError("simulated strategy_discovery import failure")

        class _BrokenModule:
            def __getattr__(self, item):
                raise RuntimeError("simulated strategy_discovery import failure")

        # Break the package for any deferred import inside build_system_prompt
        # (an entry set to None makes ``import`` raise ImportError).
        monkeypatch.setitem(sys.modules, "src.strategy_discovery", None)
        monkeypatch.setitem(sys.modules, "src.strategy_discovery.guard", None)
        # Additionally poison any module-level binding the context may hold,
        # covering top-level-import designs that call the guard at runtime.
        for name in dir(context_mod):
            obj = getattr(context_mod, name, None)
            module_of = getattr(obj, "__module__", "")
            if module_of.startswith("src.strategy_discovery"):
                monkeypatch.setattr(context_mod, name, _raiser, raising=True)
            elif inspect.ismodule(obj) and obj.__name__.startswith(
                "src.strategy_discovery"
            ):
                monkeypatch.setattr(context_mod, name, _BrokenModule(), raising=True)

        prompt = builder_factory(registry).build_system_prompt()
        assert (
            isinstance(prompt, str) and prompt.strip()
        ), "prompt must still build when src.strategy_discovery import fails"
        assert (
            full_block not in prompt
        ), "broken import must degrade to no routing block"
