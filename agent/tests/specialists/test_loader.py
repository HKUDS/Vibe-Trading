"""Loader tests for the bundled specialist roster and user overrides."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from src.specialists.loader import (
    DEFINITIONS_DIR,
    _load_file,
    load_specialists,
    reset_specialists_cache,
)
from src.specialists.models import FORBIDDEN_SPECIALIST_TOOLS, SpecialistSpec
from src.tools import build_swarm_registry, known_local_tool_names


@pytest.fixture(autouse=True)
def _fresh_roster():
    reset_specialists_cache()
    yield
    reset_specialists_cache()


EXPECTED_ROSTER = {
    "altdata-agent",
    "derivatives-agent",
    "fundamentals-text-agent",
    "funds-fi-agent",
    "macro-sector-agent",
    "market-data-agent",
    "quant-agent",
    "risk-portfolio-agent",
    "trading-connector-agent",
    "user-analytics-agent",
    "valuation-agent",
    "web-docs-agent",
}


def test_bundled_roster_loads_complete_and_valid() -> None:
    specs = load_specialists()
    assert set(specs) == EXPECTED_ROSTER


def test_every_whitelist_tool_exists_in_local_registry() -> None:
    known = known_local_tool_names()
    for spec in load_specialists().values():
        unknown = [t for t in spec.tools if t not in known]
        assert not unknown, f"{spec.name}: unknown tools {unknown}"


def test_no_bundled_specialist_holds_forbidden_tools() -> None:
    for spec in load_specialists().values():
        blocked = FORBIDDEN_SPECIALIST_TOOLS.intersection(spec.tools)
        assert not blocked, f"{spec.name} holds forbidden tools {blocked}"


def test_definitions_live_inside_the_package() -> None:
    assert DEFINITIONS_DIR.is_dir()
    assert len(list(DEFINITIONS_DIR.glob("*.yaml"))) == len(EXPECTED_ROSTER)


def test_forbidden_tools_rejected_by_model() -> None:
    for bad in ("delegate_to_specialist", "run_swarm", "bash", "trading_place_order"):
        with pytest.raises(ValueError, match="structural exclusions"):
            SpecialistSpec(
                name="bad-agent",
                description="d",
                prompt="p",
                tools=[bad],
            )


def test_unknown_tool_fails_loud(tmp_path: Path) -> None:
    path = tmp_path / "bad-agent.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "bad-agent",
                "description": "d",
                "prompt": "p",
                "tools": ["no_such_tool_xyz"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown local tool"):
        _load_file(
            path,
            known_tools=known_local_tool_names(),
            known_skills=frozenset(),
        )


def test_unknown_skill_fails_loud(tmp_path: Path) -> None:
    path = tmp_path / "bad-agent.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "bad-agent",
                "description": "d",
                "prompt": "p",
                "tools": ["read_file"],
                "skills": ["no-such-skill-xyz"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown skill"):
        _load_file(
            path,
            known_tools=known_local_tool_names(),
            known_skills=frozenset({"strategy-generate"}),
        )


def test_skills_without_load_skill_fails_loud(tmp_path: Path) -> None:
    path = tmp_path / "no-loader-agent.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "no-loader-agent",
                "description": "d",
                "prompt": "p",
                "tools": ["read_file"],
                "skills": ["strategy-generate"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=r"no-loader-agent\.yaml: declares skills but does not grant load_skill",
    ):
        _load_file(
            path,
            known_tools=known_local_tool_names(),
            known_skills=frozenset({"strategy-generate"}),
        )


def test_user_override_replaces_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    user_dir = tmp_path / "specialists"
    user_dir.mkdir()
    bundled = load_specialists()["web-docs-agent"]
    (user_dir / "web-docs-agent.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "web-docs-agent",
                "description": "user override",
                "prompt": bundled.prompt,
                "tools": list(bundled.tools),
            }
        ),
        encoding="utf-8",
    )
    reset_specialists_cache()
    overridden = load_specialists()["web-docs-agent"]
    assert overridden.description == "user override"
    assert len(load_specialists()) == len(EXPECTED_ROSTER)


def test_broken_user_file_is_skipped_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    user_dir = tmp_path / "specialists"
    user_dir.mkdir()
    (user_dir / "broken-agent.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "broken-agent",
                "description": "d",
                "prompt": "p",
                "tools": ["no_such_tool_xyz"],
            }
        ),
        encoding="utf-8",
    )
    reset_specialists_cache()
    with caplog.at_level(logging.WARNING, logger="src.specialists.loader"):
        specs = load_specialists()
    assert "broken-agent" not in specs
    assert set(specs) == EXPECTED_ROSTER
    assert any("broken-agent.yaml" in r.message for r in caplog.records)


def test_empty_skills_with_load_skill_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "loose-agent.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "loose-agent",
                "description": "d",
                "prompt": "p",
                "tools": ["read_file", "load_skill"],
                "skills": [],
            }
        ),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="src.specialists.loader"):
        _load_file(
            path,
            known_tools=known_local_tool_names(),
            known_skills=frozenset(),
        )
    assert any("empty skills list" in r.message for r in caplog.records)


def test_swarm_workers_cannot_hold_delegate_tool() -> None:
    """Single orchestration channel: the delegate tool is stripped from swarm
    worker whitelists rather than nested inside a swarm."""
    registry = build_swarm_registry(["read_file", "delegate_to_specialist"])
    assert registry.get("delegate_to_specialist") is None
    assert registry.get("read_file") is not None
