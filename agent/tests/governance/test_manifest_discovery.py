from __future__ import annotations

import json

from scripts.dump_tool_inventory import build_tool_inventory
from src.agent.tools import BaseTool, ToolRegistry
from src.governance.decisions import build_param_audit
from src.governance.discovery import ManifestCache, discover_tool_manifest
from src.governance.manifest import RiskLevel, ToolSurface
from src.governance.runtime import GovernedToolRegistry
from src.tools import build_registry


class _ReadonlyTool(BaseTool):
    name = "sample_read"
    description = "read"
    parameters = {"type": "object", "properties": {"symbol": {"type": "string"}}}
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs):
        return json.dumps({"status": "ok", "kwargs": kwargs})


def test_manifest_contains_all_phase0_inventory_tools() -> None:
    inventory = build_tool_inventory(include_shell_tools=True)
    registry = build_registry(include_shell_tools=True, interactive=False)

    cache = ManifestCache.from_registry(registry, surface=ToolSurface.CLI)

    inventory_names = {row["name"] for row in inventory}
    manifest_names = {cache.get(name).name for name in inventory_names}
    assert manifest_names == inventory_names
    assert all(cache.get(name).risk_level != RiskLevel.UNCLASSIFIED for name in inventory_names)


def test_bash_is_r5_shell() -> None:
    registry = build_registry(include_shell_tools=True, interactive=False)
    bash = registry.get("bash")
    assert bash is not None

    manifest = discover_tool_manifest(bash, surface=ToolSurface.CLI)

    assert manifest.name == "bash"
    assert manifest.risk_level == RiskLevel.R5_SHELL
    assert manifest.readonly is False


def test_unknown_new_tool_is_unclassified() -> None:
    class NewTool(BaseTool):
        name = "new_unmapped_tool"
        description = "new"
        parameters = {"type": "object", "properties": {}}
        is_readonly = False

        def execute(self, **kwargs):
            return "{}"

    manifest = discover_tool_manifest(NewTool(), surface=ToolSurface.CLI)

    assert manifest.risk_level == RiskLevel.UNCLASSIFIED


def test_params_redacted_and_hashed() -> None:
    audit = build_param_audit(
        {
            "symbol": "AAPL",
            "api_key": "sk-this-value-must-not-appear",
            "nested": {"authorization": "Bearer secret-token"},
        }
    )

    rendered = json.dumps(audit.preview, ensure_ascii=False)
    assert audit.params_hash
    assert audit.params_hash != "sk-this-value-must-not-appear"
    assert "sk-this-value-must-not-appear" not in rendered
    assert "secret-token" not in rendered
    assert "[REDACTED]" in rendered


def test_tool_schema_unchanged_by_governed_registry() -> None:
    inner = ToolRegistry()
    inner.register(_ReadonlyTool())
    before = inner.get_definitions()

    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache.from_registry(inner, surface=ToolSurface.CLI),
    )

    assert governed.get_definitions() == before
