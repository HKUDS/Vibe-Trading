"""Tests for swarm preset inspection and static validation."""

from __future__ import annotations

from pathlib import Path

from src.swarm import presets


def test_all_bundled_presets_inspect_without_errors() -> None:
    """Bundled presets should have valid agent/task references and DAGs."""
    for entry in presets.list_presets():
        report = presets.inspect_preset(entry["name"])
        assert report["valid"], f"{entry['name']} errors: {report['errors']}"
        assert report["layers"], f"{entry['name']} has no execution layers"


def test_inspect_preset_returns_dry_run_layers() -> None:
    report = presets.inspect_preset("investment_committee")

    assert report["valid"]
    assert report["variables"] == ["market", "target"]
    assert report["layers"][0] == [
        {"task_id": "task-bull", "agent_id": "bull_advocate"},
        {"task_id": "task-bear", "agent_id": "bear_advocate"},
    ]
    assert report["layers"][-1] == [
        {"task_id": "task-decision", "agent_id": "portfolio_manager"}
    ]


def test_investment_committee_exposes_cross_market_research_tools() -> None:
    """The committee must expose both A-share and U.S. evidence surfaces."""
    report = presets.inspect_preset("investment_committee")
    expected = {
        "search_symbol",
        "get_market_data",
        "get_a_share_data",
        "get_financial_statements",
        "get_stock_profile",
        "get_stock_news",
        "get_fund_flow",
        "get_sector_info",
        "get_research_reports",
        "get_sec_filings",
        "get_margin_trading",
        "get_shareholder_count",
        "get_lockup_expiry",
        "get_northbound_flow",
        "get_institutional_holdings",
    }

    agents = {entry["id"]: set(entry["tools"]) for entry in report["agents"]}
    for agent_id in ("bull_advocate", "bear_advocate", "risk_officer", "portfolio_manager"):
        assert expected <= agents[agent_id]

    assert "market-specific tool" in presets.load_preset("investment_committee")["agents"][0]["system_prompt"]


def test_inspect_preset_reports_invalid_references(
    tmp_path: Path,
    monkeypatch,
) -> None:
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()
    (preset_dir / "broken.yaml").write_text(
        """
name: broken
title: Broken Preset
agents:
  - id: analyst
    role: Analyst
    system_prompt: ""
tasks:
  - id: task-a
    agent_id: missing_agent
    prompt_template: "Analyze {target}"
    depends_on: [missing_task]
variables:
  - name: market
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(presets, "PRESETS_DIR", preset_dir)

    report = presets.inspect_preset("broken")

    assert not report["valid"]
    assert "Task 'task-a' references unknown agent 'missing_agent'" in report["errors"]
    assert "Task 'task-a' depends on unknown task 'missing_task'" in report["errors"]
    assert "Prompt templates use undeclared variables: target" in report["warnings"]
    assert "Declared variables are not used by task prompt templates: market" in report["warnings"]
