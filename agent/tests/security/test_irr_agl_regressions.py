from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.core.runner import _copy_runtime_env
from src.governance.decisions import RuntimeContext
from src.governance.discovery import ManifestCache
from src.governance.errors import PolicyDenied
from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface
from src.governance.policy_engine import PolicyEngine, PolicyRule
from src.governance.runtime import GovernedToolRegistry
from src.reliability.artifacts.store import resolve_under_root
from src.reliability.data.contracts import DataAuditReport
from src.reliability.errors import ArtifactPathError
from src.research_card.builder import ResearchCardGraph, build_research_card


def _manifest(
    *,
    name: str,
    surface: ToolSurface,
    risk: RiskLevel,
    readonly: bool = False,
    live_classification: str | None = None,
) -> ToolManifest:
    return ToolManifest(
        name=name,
        surface=surface,
        readonly=readonly,
        repeatable=True,
        risk_level=risk,
        requires_auth=False,
        requires_consent=risk == RiskLevel.R4_TRADE_WRITE,
        allowed_modes=["research", "paper", "advisory", "live"],
        secret_access="none",
        timeout_seconds=30,
        side_effects=["test"],
        live_classification=live_classification,
    )


def _context(surface: ToolSurface, mode: str = "enforce") -> RuntimeContext:
    return RuntimeContext(surface=surface, mode=mode)


@pytest.mark.parametrize("surface", [ToolSurface.REMOTE_API, ToolSurface.CHANNEL_BOT])
def test_remote_and_channel_surfaces_deny_r5_shell(surface: ToolSurface) -> None:
    decision = PolicyEngine().evaluate(
        name="bash",
        params={},
        manifest=_manifest(name="bash", surface=surface, risk=RiskLevel.R5_SHELL),
        context=_context(surface),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P20"


def test_scheduler_denies_live_write_and_shell() -> None:
    engine = PolicyEngine()

    for name, risk in (("place_order", RiskLevel.R4_TRADE_WRITE), ("bash", RiskLevel.R5_SHELL)):
        decision = engine.evaluate(
            name=name,
            params={},
            manifest=_manifest(name=name, surface=ToolSurface.SCHEDULER, risk=risk),
            context=_context(ToolSurface.SCHEDULER),
        )
        assert decision.action == "deny"
        assert decision.rule_id == "P30"


def test_unknown_live_connector_fails_closed() -> None:
    decision = PolicyEngine().evaluate(
        name="broker_new_order_tool",
        params={},
        manifest=_manifest(
            name="broker_new_order_tool",
            surface=ToolSurface.LIVE_CONNECTOR,
            risk=RiskLevel.R4_TRADE_WRITE,
            live_classification="UNKNOWN",
        ),
        context=_context(ToolSurface.LIVE_CONNECTOR),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P10"


class _CountingTool(BaseTool):
    name = "counting"
    description = "counting"
    parameters = {"type": "object", "properties": {}}
    repeatable = True
    is_readonly = False

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        return json.dumps({"calls": self.calls})


@pytest.mark.parametrize(
    ("risk", "surface", "mode"),
    [
        (RiskLevel.R4_TRADE_WRITE, ToolSurface.CLI, "observe"),
        (RiskLevel.R5_SHELL, ToolSurface.REMOTE_API, "warn"),
    ],
)
def test_r4_r5_policy_denies_are_shadow_denied_without_execution(
    risk: RiskLevel,
    surface: ToolSurface,
    mode: str,
) -> None:
    tool = _CountingTool()
    inner = ToolRegistry()
    inner.register(tool)
    manifest = _manifest(name="counting", surface=surface, risk=risk)
    governed = GovernedToolRegistry(
        inner,
        manifest_cache=ManifestCache({"counting": manifest}, surface=surface),
        context=RuntimeContext(surface=surface, mode=mode),
    )

    with pytest.raises(PolicyDenied) as raised:
        governed.execute("counting", {})

    assert raised.value.shadow is True
    assert raised.value.trace_status == "skipped"
    assert tool.calls == 0


def test_explicit_local_market_data_fallback_to_network_is_denied() -> None:
    decision = PolicyEngine().evaluate(
        name="get_market_data",
        params={"explicit_local": True, "fallback_to_network": True},
        manifest=_manifest(
            name="get_market_data",
            surface=ToolSurface.CLI,
            risk=RiskLevel.R2_NETWORK,
            readonly=True,
        ),
        context=_context(ToolSurface.CLI, mode="observe"),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "P50"


def test_all_sources_open_becomes_visible_research_card_warning() -> None:
    audit = DataAuditReport.model_validate(
        {
            "audit_id": "audit_all_open",
            "schema_version": "1.0.0",
            "access_contract": {
                "source": "auto",
                "selected_source": "none",
                "request_params_hash": "0" * 64,
                "fallback_chain": ["eastmoney", "sina"],
                "fetched_at": "2026-01-01T00:00:00Z",
                "explicit_local": False,
            },
            "row_count": 0,
            "symbol_count": 0,
            "field_coverage": {},
            "all_sources_open": True,
        }
    )

    card = build_research_card(
        ResearchCardGraph(
            card_id="card_all_open",
            title="all sources open regression",
            data_audits=[audit],
            has_oos=False,
            has_cost_model=False,
            has_benchmark=False,
        )
    )

    warning = next(item for item in card.warnings if item.code == "DATA_ALL_SOURCES_OPEN")
    assert warning.severity == "hard_failure"
    assert card.conclusion_level != "paper_trade_candidate"


def test_artifact_path_containment_rejects_escape_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    with pytest.raises(ArtifactPathError):
        resolve_under_root(root, "../outside/payload.json")

    link = root / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    with pytest.raises(ArtifactPathError):
        resolve_under_root(root, "link/payload.json")


def test_generated_backtest_subprocess_env_allowlist_excludes_live_and_llm_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "llm-secret")
    monkeypatch.setenv("API_AUTH_KEY", "api-secret")
    monkeypatch.setenv("BROKER_ACCESS_TOKEN", "broker-secret")
    monkeypatch.setenv("TUSHARE_TOKEN", "market-data-token")

    copied = _copy_runtime_env()

    assert copied.get("TUSHARE_TOKEN") == "market-data-token"
    assert "OPENAI_API_KEY" not in copied
    assert "API_AUTH_KEY" not in copied
    assert "BROKER_ACCESS_TOKEN" not in copied
    assert "llm-secret" not in json.dumps(copied, ensure_ascii=False)
    assert "broker-secret" not in json.dumps(copied, ensure_ascii=False)


def test_agent_tool_surface_cannot_import_or_reference_commit_mandate() -> None:
    offenders: list[str] = []
    tools_root = Path(__file__).resolve().parents[2] / "src" / "tools"
    for path in tools_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.names:
                names = {alias.name for alias in node.names}
                if "commit_mandate" in names:
                    offenders.append(f"{path.name} imports commit_mandate")
            elif isinstance(node, ast.Name) and node.id == "commit_mandate":
                offenders.append(f"{path.name} references commit_mandate")
            elif isinstance(node, ast.Attribute) and node.attr == "commit_mandate":
                offenders.append(f"{path.name} references .commit_mandate")

    assert offenders == []


def test_policy_engine_exception_high_risk_fails_safe() -> None:
    def raises(**kwargs):
        raise RuntimeError("boom")

    decision = PolicyEngine(
        rules=[
            PolicyRule(
                priority=1,
                rule_id="raising",
                description="raise",
                action="allow",
                predicate=raises,
            )
        ]
    ).evaluate(
        name="bash",
        params={},
        manifest=_manifest(name="bash", surface=ToolSurface.REMOTE_API, risk=RiskLevel.R5_SHELL),
        context=_context(ToolSurface.REMOTE_API),
    )

    assert decision.action == "deny"
    assert decision.rule_id == "policy_exception"
