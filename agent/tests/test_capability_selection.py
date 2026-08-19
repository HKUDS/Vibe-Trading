"""Slash capability selection contract tests."""

import pytest

from src.session.service import SessionService


def test_unknown_skill_is_rejected_before_agent_execution():
    with pytest.raises(ValueError, match="Unknown or unavailable skill"):
        SessionService._validate_selection(
            {
                "selected_skills": ["does-not-exist"],
                "selected_tools": [],
                "tool_mode": "auto",
                "force_tool": None,
            },
            include_shell_tools=False,
        )


def test_force_tool_requires_a_single_selected_tool(monkeypatch):
    class FakeRegistry:
        tool_names = ["get_market_data", "read_file"]

        def get(self, name):
            return object() if name in self.tool_names else None

    monkeypatch.setattr("src.tools.build_registry", lambda **_: FakeRegistry())
    with pytest.raises(ValueError, match="force_tool"):
        SessionService._validate_selection(
            {
                "selected_skills": [],
                "selected_tools": ["get_market_data", "read_file"],
                "tool_mode": "restricted",
                "force_tool": "get_market_data",
            },
            include_shell_tools=False,
        )
