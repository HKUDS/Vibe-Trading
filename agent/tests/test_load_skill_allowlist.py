"""Regression tests for the per-context ``load_skill`` skill allowlist.

``SwarmAgentSpec.skills`` documents a per-worker skill boundary
(``src/swarm/models.py``), but before this fix the boundary only filtered the
skill *descriptions* shown in the worker prompt — the ``load_skill`` tool
itself would load any skill by name, so the documented boundary was not
enforced at runtime. ``LoadSkillTool(allowed_skills=...)`` closes that gap;
these tests pin the three states (restricted / unrestricted / empty) plus the
registry-builder and swarm-worker wiring that delivers the allowlist.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.agent.skills import SkillsLoader
from src.swarm import worker as worker_mod
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.worker import run_worker
from src.tools import build_filtered_registry, build_swarm_registry
from src.tools.load_skill_tool import LoadSkillTool


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\n---\n\n# {name}\n\nBody.\n",
        encoding="utf-8",
    )


def _fixture_loader(tmp_path: Path) -> SkillsLoader:
    _write_skill(tmp_path, "alpha-one")
    _write_skill(tmp_path, "beta-two")
    return SkillsLoader(skills_dir=tmp_path, user_skills_dir=tmp_path / "absent")


def test_allowlist_permits_listed_skill(tmp_path: Path) -> None:
    tool = LoadSkillTool(
        _fixture_loader(tmp_path), allowed_skills=frozenset({"alpha-one"})
    )
    payload = json.loads(tool.execute(name="alpha-one"))
    assert payload["status"] == "ok"


def test_allowlist_refuses_unlisted_skill_and_names_allowed_set(tmp_path: Path) -> None:
    tool = LoadSkillTool(
        _fixture_loader(tmp_path), allowed_skills=frozenset({"alpha-one"})
    )
    payload = json.loads(tool.execute(name="beta-two"))
    assert payload["status"] == "error"
    assert "outside the skill allowlist" in payload["content"]
    assert "alpha-one" in payload["content"]


def test_allowlist_none_keeps_unrestricted_default(tmp_path: Path) -> None:
    tool = LoadSkillTool(_fixture_loader(tmp_path))
    assert json.loads(tool.execute(name="alpha-one"))["status"] == "ok"
    assert json.loads(tool.execute(name="beta-two"))["status"] == "ok"


def test_allowlist_empty_refuses_everything(tmp_path: Path) -> None:
    tool = LoadSkillTool(_fixture_loader(tmp_path), allowed_skills=frozenset())
    payload = json.loads(tool.execute(name="alpha-one"))
    assert payload["status"] == "error"
    assert "(none)" in payload["content"]


def test_filtered_registry_rebuilds_load_skill_with_allowlist() -> None:
    registry = build_filtered_registry(
        ["load_skill"], skill_allowlist=["strategy-generate"]
    )
    tool = registry.get("load_skill")
    assert tool is not None
    # An allowlisted bundled skill loads; any other bundled skill is refused.
    assert json.loads(tool.execute(name="strategy-generate"))["status"] == "ok"
    refused = json.loads(tool.execute(name="alpha-zoo"))
    assert refused["status"] == "error"
    assert "strategy-generate" in refused["content"]


def test_filtered_registry_none_allowlist_keeps_unrestricted_instance() -> None:
    registry = build_filtered_registry(["load_skill"])
    tool = registry.get("load_skill")
    assert tool is not None
    assert json.loads(tool.execute(name="alpha-zoo"))["status"] == "ok"


def test_allowlist_without_load_skill_in_whitelist_adds_nothing() -> None:
    registry = build_filtered_registry(
        ["read_file"], skill_allowlist=["strategy-generate"]
    )
    assert registry.get("load_skill") is None


def test_swarm_registry_honours_skill_allowlist() -> None:
    registry = build_swarm_registry(
        ["load_skill"], skill_allowlist=["strategy-generate"]
    )
    tool = registry.get("load_skill")
    assert tool is not None
    refused = json.loads(tool.execute(name="alpha-zoo"))
    assert refused["status"] == "error"
    assert "strategy-generate" in refused["content"]


def test_swarm_worker_passes_spec_skills_as_allowlist(tmp_path: Path) -> None:
    """run_worker must deliver ``agent_spec.skills`` to the registry builder —
    the one line that makes the documented per-worker boundary real."""
    captured: dict = {}

    class _CapturingRegistry:
        def get_definitions(self) -> list[dict]:
            return []

        def get(self, name: str):
            return None

        def execute(self, name: str, args: dict) -> str:
            return json.dumps({"status": "ok"})

    class _FinalAnswerLLM:
        def __call__(self, *args, **kwargs) -> "_FinalAnswerLLM":
            return self

        def close(self) -> None:
            pass

        def stream_chat(self, messages, tools=None, on_text_chunk=None, timeout=None):
            from src.providers.llm import LLMResponse

            return LLMResponse(content="done")

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return _CapturingRegistry()

    agent = SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="You analyze.",
        tools=["load_skill"],
        skills=["strategy-generate"],
        max_iterations=1,
        timeout_seconds=60,
    )
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Do the thing.")
    with (
        patch.object(worker_mod, "build_swarm_registry", _capture),
        patch.object(worker_mod, "ChatLLM", _FinalAnswerLLM()),
    ):
        run_worker(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
        )
    assert captured.get("skill_allowlist") == ["strategy-generate"]


def test_swarm_worker_empty_skills_stays_unrestricted(tmp_path: Path) -> None:
    """An empty ``skills`` list means unrestricted (prompt-side filter treats
    empty as include-all); the wiring must pass ``None``, not an empty list."""
    captured: dict = {}

    class _CapturingRegistry:
        def get_definitions(self) -> list[dict]:
            return []

        def get(self, name: str):
            return None

        def execute(self, name: str, args: dict) -> str:
            return json.dumps({"status": "ok"})

    class _FinalAnswerLLM:
        def __call__(self, *args, **kwargs) -> "_FinalAnswerLLM":
            return self

        def close(self) -> None:
            pass

        def stream_chat(self, messages, tools=None, on_text_chunk=None, timeout=None):
            from src.providers.llm import LLMResponse

            return LLMResponse(content="done")

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return _CapturingRegistry()

    agent = SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="You analyze.",
        tools=["load_skill"],
        skills=[],
        max_iterations=1,
        timeout_seconds=60,
    )
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Do the thing.")
    with (
        patch.object(worker_mod, "build_swarm_registry", _capture),
        patch.object(worker_mod, "ChatLLM", _FinalAnswerLLM()),
    ):
        run_worker(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
        )
    assert captured.get("skill_allowlist") is None
