"""Smoke tests for the Phase 0 tool inventory script."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dump_tool_inventory.py"


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location("dump_tool_inventory", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_inventory_rows_include_required_governance_fields() -> None:
    module = _load_inventory_module()

    rows = module.build_tool_inventory()

    assert rows
    names = [row["name"] for row in rows]
    assert names == sorted(names)
    assert len(names) == len(set(names))

    required_fields = {
        "name",
        "module",
        "is_readonly",
        "repeatable",
        "surface_guess",
        "risk_guess",
    }
    for row in rows:
        assert required_fields <= row.keys()
        assert isinstance(row["name"], str) and row["name"]
        assert isinstance(row["module"], str) and row["module"]
        assert isinstance(row["is_readonly"], bool)
        assert isinstance(row["repeatable"], bool)
        assert isinstance(row["surface_guess"], str) and row["surface_guess"]
        assert isinstance(row["risk_guess"], str) and row["risk_guess"]


def test_shell_tools_are_inventory_only_and_marked_r5() -> None:
    module = _load_inventory_module()

    rows = module.build_tool_inventory()
    by_name = {row["name"]: row for row in rows}

    assert "bash" in by_name
    assert by_name["bash"]["surface_guess"] == "local_cli"
    assert by_name["bash"]["risk_guess"] == "R5_SHELL"
