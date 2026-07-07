"""Dump a read-only inventory of registered local tools.

Phase 0 uses this as an audit helper only. It builds the existing registry,
records metadata, and never calls ``ToolRegistry.execute`` or any tool's
``execute`` method.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from src.agent.tools import BaseTool  # noqa: E402
from src.tools import build_registry  # noqa: E402


SHELL_TOOL_NAMES = {"bash", "background_run"}
TRADE_WRITE_TERMS = (
    "place_order",
    "cancel_order",
    "modify_order",
    "submit_order",
    "flatten",
    "trade_write",
    "order_write",
)
TRADE_READ_TERMS = (
    "account",
    "balance",
    "broker",
    "connector",
    "order",
    "position",
    "portfolio",
    "trading",
)
NETWORK_TERMS = (
    "market_data",
    "web_",
    "url",
    "news",
    "sec_",
    "fred",
    "iwencai",
    "dragon_tiger",
    "northbound",
    "fund_flow",
    "financial_statements",
    "stock_profile",
)
LOCAL_WRITE_TERMS = ("write", "edit", "remember", "journal", "save")


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def guess_surface(tool: BaseTool) -> str:
    """Best-effort surface classification for Phase 0 review."""
    name = tool.name.lower()
    module = tool.__class__.__module__.lower()
    combined = f"{module}.{name}"

    if name in SHELL_TOOL_NAMES:
        return "local_cli"
    if ".mcp" in module or tool.__class__.__name__.lower().startswith("mcp"):
        return "mcp"
    if "live" in module or "trading_connector" in module or "broker" in combined:
        return "live_connector"
    if module.endswith((".read_file_tool", ".write_file_tool", ".edit_file_tool")) or _contains_any(
        name,
        ("read_file", "write_file", "edit_file"),
    ):
        return "filesystem"
    if _contains_any(combined, NETWORK_TERMS):
        return "network_data"
    return "local_research"


def guess_risk(tool: BaseTool) -> str:
    """Best-effort risk classification aligned with AGENTS.md risk levels."""
    name = tool.name.lower()
    module = tool.__class__.__module__.lower()
    combined = f"{module}.{name}"
    is_readonly = bool(getattr(tool, "is_readonly", True))

    if name in SHELL_TOOL_NAMES:
        return "R5_SHELL"
    if _contains_any(combined, TRADE_WRITE_TERMS) or (
        not is_readonly and "trading_connector" in module
    ):
        return "R4_TRADE_WRITE"
    if _contains_any(combined, TRADE_READ_TERMS) and "trading" in combined:
        return "R3_TRADE_READ"
    if not is_readonly:
        if _contains_any(combined, LOCAL_WRITE_TERMS):
            return "R1_WRITE_LOCAL"
        return "R1_WRITE_LOCAL"
    if _contains_any(combined, NETWORK_TERMS):
        return "R2_NETWORK"
    return "R0_READ"


def build_tool_inventory(*, include_shell_tools: bool = True) -> list[dict[str, Any]]:
    """Return inventory rows for currently available local tools."""
    registry = build_registry(include_shell_tools=include_shell_tools, interactive=False)
    rows: list[dict[str, Any]] = []
    for name in registry.tool_names:
        tool = registry.get(name)
        if tool is None:
            continue
        rows.append({
            "name": tool.name,
            "module": tool.__class__.__module__,
            "class_name": tool.__class__.__name__,
            "is_readonly": bool(getattr(tool, "is_readonly", True)),
            "repeatable": bool(getattr(tool, "repeatable", False)),
            "surface_guess": guess_surface(tool),
            "risk_guess": guess_risk(tool),
        })
    return sorted(rows, key=lambda row: row["name"])


def _format_table(rows: list[dict[str, Any]]) -> str:
    headers = ["name", "module", "is_readonly", "repeatable", "surface_guess", "risk_guess"]
    table = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        table.append("| " + " | ".join(str(row[column]) for column in headers) + " |")
    return "\n".join(table)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump the Vibe-Trading local tool inventory.")
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format. Defaults to JSON for machine review.",
    )
    parser.add_argument(
        "--exclude-shell-tools",
        action="store_true",
        help="Exclude shell-capable tools from the inventory.",
    )
    args = parser.parse_args(argv)

    rows = build_tool_inventory(include_shell_tools=not args.exclude_shell_tools)
    if args.format == "table":
        print(_format_table(rows))
    else:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
