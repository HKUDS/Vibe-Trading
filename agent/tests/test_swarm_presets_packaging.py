"""Regression tests for swarm preset discovery.

These guard against the v0.1.5 packaging bug (issue #55), where preset
YAMLs were declared via ``[tool.setuptools.data-files]`` and ended up at
``<venv>/config/swarm/`` while the loader looked under
``<site-packages>/config/swarm/``. Moving the YAMLs into the
``src.swarm.presets`` package keeps source-installs and built wheels in
sync; these tests fail fast if either side drifts again.
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


from pathlib import Path

import pytest

from src.swarm.presets import PRESETS_DIR, list_presets, load_preset


# Lock to the canonical roster shipped today. Bump intentionally if a preset
# is added or removed so a release that silently drops files is caught here.
EXPECTED_PRESET_COUNT = 30


def test_presets_dir_lives_inside_swarm_package() -> None:
    """PRESETS_DIR must be a sibling of presets.py so wheels can find it."""
    import src.swarm.presets as presets_module

    module_dir = Path(presets_module.__file__).resolve().parent
    assert PRESETS_DIR == module_dir / "presets"
    assert PRESETS_DIR.is_dir(), f"presets dir missing: {PRESETS_DIR}"


def test_list_presets_returns_full_roster() -> None:
    # Filter to bundled entries so a developer's own ~/.vibe-trading user
    # presets can never make the packaging regression flap.
    presets = [p for p in list_presets() if p["source"] == "bundled"]
    assert len(presets) == EXPECTED_PRESET_COUNT, (
        f"expected {EXPECTED_PRESET_COUNT} presets, got {len(presets)} — "
        "check pyproject package-data and that YAMLs were not dropped"
    )


def test_value_investing_committee_is_routable() -> None:
    """value_investing_committee must be in the routing table, not just on disk."""
    from src.tools.swarm_tool import _PRESET_NAMES, _normalize_preset_name

    assert "value_investing_committee" in _PRESET_NAMES
    assert _normalize_preset_name("value_investing_committee") == "value_investing_committee"


def test_every_preset_yaml_is_loadable() -> None:
    """Every YAML in the bundle must parse and expose required keys."""
    for entry in list_presets():
        name = entry["name"]
        data = load_preset(name)
        assert isinstance(data, dict), f"preset {name} did not parse to dict"
        assert data.get("agents"), f"preset {name} has no agents"
        assert data.get("tasks"), f"preset {name} has no tasks"


@pytest.mark.parametrize(
    "preset_name",
    ["investment_committee", "quant_strategy_desk", "risk_committee"],
)
def test_known_presets_load(preset_name: str) -> None:
    """Spot-check a few headline presets advertised in docs/UI."""
    data = load_preset(preset_name)
    assert data["agents"], f"{preset_name} has no agents"


def test_quant_strategy_desk_ends_with_report_aggregator() -> None:
    """quant_strategy_desk must deliver a final report, not stop at the risk audit.

    Regression for #1029: the preset's last task is task-report run by
    report_aggregator, consuming all four upstream task summaries.
    """
    data = load_preset("quant_strategy_desk")

    agents = {a["id"]: a for a in data["agents"]}
    assert "report_aggregator" in agents, "report_aggregator agent missing"

    report_task = next(t for t in data["tasks"] if t["id"] == "task-report")
    assert report_task["agent_id"] == "report_aggregator"
    assert report_task["depends_on"] == [
        "task-screen",
        "task-factor",
        "task-backtest",
        "task-risk",
    ]
    assert report_task["input_from"] == {
        "screener_result": "task-screen",
        "factors": "task-factor",
        "backtest_result": "task-backtest",
        "risk_audit": "task-risk",
    }


def test_quant_strategy_desk_report_prompt_covers_four_sections() -> None:
    """The aggregator prompt must require every deliverable a user expects."""
    from src.swarm.presets import inspect_preset

    data = load_preset("quant_strategy_desk")
    prompt = next(
        a["system_prompt"] for a in data["agents"] if a["id"] == "report_aggregator"
    )
    for marker in [
        "Final strategy",
        "Selected factors",
        "Backtest summary",
        "Risk audit",
    ]:
        assert marker in prompt, f"report prompt misses section {marker!r}"

    insp = inspect_preset("quant_strategy_desk")
    assert insp["valid"] is True, f"preset invalid: {insp['errors']}"
    assert insp["errors"] == []
    assert insp["layers"][-1][0]["task_id"] == "task-report"


# ── User presets directory (~/.vibe-trading/swarm/presets/) ──────────────────


_USER_PRESET_YAML = """\
name: my_custom_desk
title: "My Custom Desk"
description: "User-supplied preset."
agents:
  - id: analyst
    role: Analyst
    system_prompt: "Analyze {topic}."
    tools: [read_file]
tasks:
  - id: task-analyze
    agent_id: analyst
    prompt_template: "Analyze {topic}."
    depends_on: []
variables:
  - name: topic
    description: "Subject"
    required: true
"""


@pytest.fixture()
def user_presets_dir(tmp_path, monkeypatch):
    import src.swarm.presets as presets_module

    user_dir = tmp_path / "user-presets"
    user_dir.mkdir()
    monkeypatch.setattr(presets_module, "USER_PRESETS_DIR", user_dir)
    return user_dir


def test_user_preset_is_discovered(user_presets_dir) -> None:
    (user_presets_dir / "my_custom_desk.yaml").write_text(
        _USER_PRESET_YAML, encoding="utf-8"
    )
    data = load_preset("my_custom_desk")
    assert data["agents"][0]["id"] == "analyst"

    entries = {p["name"]: p for p in list_presets()}
    assert entries["my_custom_desk"]["source"] == "user"
    assert entries["investment_committee"]["source"] == "bundled"


def test_user_preset_overrides_bundled_stem(user_presets_dir) -> None:
    override = _USER_PRESET_YAML.replace("my_custom_desk", "risk_committee")
    (user_presets_dir / "risk_committee.yaml").write_text(override, encoding="utf-8")

    data = load_preset("risk_committee")
    assert len(data["agents"]) == 1                     # the user file won
    entries = {p["name"]: p for p in list_presets()}
    assert entries["risk_committee"]["source"] == "user"
    # Override replaces, never duplicates.
    assert sum(p["name"] == "risk_committee" for p in list_presets()) == 1


def test_missing_user_dir_changes_nothing(tmp_path, monkeypatch) -> None:
    import src.swarm.presets as presets_module

    monkeypatch.setattr(presets_module, "USER_PRESETS_DIR", tmp_path / "absent")
    assert load_preset("risk_committee")["agents"]
    assert all(p["source"] == "bundled" for p in list_presets())


@pytest.mark.parametrize("bad_name", ["../escape", "a/b", "..", "", "a\\b"])
def test_path_escaping_names_rejected(bad_name: str) -> None:
    with pytest.raises(ValueError):
        load_preset(bad_name)


def test_missing_preset_error_names_both_locations(user_presets_dir) -> None:
    with pytest.raises(FileNotFoundError) as excinfo:
        load_preset("does_not_exist")
    message = str(excinfo.value)
    assert "bundled" in message and str(user_presets_dir) in message


def test_explicit_user_preset_accepted_by_swarm_tool(user_presets_dir) -> None:
    """run_swarm(preset_name=...) reaches user presets; keyword routing does not."""
    from src.tools.swarm_tool import _match_preset, _normalize_preset_name

    (user_presets_dir / "my_custom_desk.yaml").write_text(
        _USER_PRESET_YAML, encoding="utf-8"
    )
    assert _normalize_preset_name("My Custom Desk") == "my_custom_desk"
    assert _normalize_preset_name("no_such_preset_anywhere") is None
    # A user preset must never be reachable via keyword auto-routing.
    assert _match_preset("please analyze my custom desk topic") != "my_custom_desk"


_INVESTMENT_COMMITTEE_FUNDAMENTAL_TOOLS = (
    "get_financial_statements",
    "get_fund_flow",
    "get_margin_trading",
    "get_research_reports",
    "get_stock_news",
)


def test_investment_committee_research_workers_have_fundamental_tools() -> None:
    """#1343: bull/bear/risk workers mandate fundamental analysis but their
    whitelist lacked every fundamental data tool, so each run reported "no
    fundamental data tool executable" and degraded to price-only claims."""
    preset = load_preset("investment_committee")
    researchers = {
        agent["id"]: set(agent.get("tools") or [])
        for agent in preset["agents"]
        if agent["id"] in ("bull_advocate", "bear_advocate", "risk_officer")
    }
    assert researchers, "expected the three research workers"
    for agent_id, tools in researchers.items():
        missing = [
            tool for tool in _INVESTMENT_COMMITTEE_FUNDAMENTAL_TOOLS if tool not in tools
        ]
        assert not missing, f"{agent_id} lacks fundamental data tools: {missing}"


def test_every_preset_tool_exists_in_local_registry() -> None:
    """A whitelist name the registry does not provide is silently dropped
    (_filter_registry logs and skips), leaving the worker without a tool its
    prompt may depend on. Every bundled preset tool must resolve."""
    from src.tools import build_registry

    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()), include_shell_tools=True)
    for entry in list_presets():
        preset = load_preset(entry["name"])
        for agent in preset["agents"]:
            for tool_name in agent.get("tools") or []:
                assert registry.get(tool_name), (
                    f"{entry['name']}/{agent['id']} requests tool {tool_name!r} "
                    "that the local registry does not provide; the worker "
                    "whitelist would silently drop it (#1343)."
                )
