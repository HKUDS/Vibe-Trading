"""Manifest discovery for existing tool registries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from src.governance.manifest import RiskLevel, ToolManifest, ToolSurface

if TYPE_CHECKING:  # pragma: no cover
    from src.agent.tools import BaseTool, ToolRegistry


SHELL_TOOL_NAMES = {"bash", "background_run"}
TRADE_WRITE_TERMS = (
    "place_order",
    "cancel_order",
    "modify_order",
    "submit_order",
    "flatten",
    "trade_write",
    "order_write",
    "select_connection",
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
    "history",
    "quote",
    "connection",
)
NETWORK_TERMS = (
    "market_data",
    "web_",
    "web.",
    "url",
    "news",
    "sec_",
    "sec.",
    "fred",
    "iwencai",
    "dragon_tiger",
    "northbound",
    "fund_flow",
    "financial_statements",
    "stock_profile",
    "research_reports",
    "macro",
    "media",
    "filing",
    "mcp_",
)
LOCAL_WRITE_TERMS = ("write", "edit", "remember", "journal", "save", "create", "delete", "copy")
KNOWN_LOCAL_MODULE_PREFIXES = (
    "src.tools.",
    "src.memory.",
    "src.goal.",
    "src.autopilot.",
    "src.live.",
)


class ManifestCache:
    """In-memory cache of tool manifests for a registry."""

    def __init__(self, manifests: Mapping[str, ToolManifest] | None = None, *, surface: ToolSurface = ToolSurface.CLI):
        self.surface = surface
        self._manifests = dict(manifests or {})

    @classmethod
    def from_registry(cls, registry: "ToolRegistry", *, surface: ToolSurface = ToolSurface.CLI) -> "ManifestCache":
        manifests: dict[str, ToolManifest] = {}
        names = getattr(registry, "tool_names", [])
        for name in names:
            get_tool = getattr(registry, "get", None)
            tool = get_tool(name) if callable(get_tool) else None
            if tool is not None:
                manifest = discover_tool_manifest(tool, surface=surface)
                if manifest.risk_level == RiskLevel.UNCLASSIFIED:
                    fallback_risk = RiskLevel.R0_READ if manifest.readonly else RiskLevel.R1_WRITE_LOCAL
                    manifest = manifest.model_copy(update={"risk_level": fallback_risk})
                manifests[name] = manifest
        return cls(manifests, surface=surface)

    def get(self, name: str) -> ToolManifest:
        manifest = self._manifests.get(name)
        if manifest is not None:
            return manifest
        return ToolManifest(
            name=name,
            surface=self.surface,
            readonly=False,
            repeatable=False,
            risk_level=RiskLevel.UNCLASSIFIED,
            requires_auth=False,
            requires_consent=False,
            allowed_modes=["research"],
            secret_access="none",
            timeout_seconds=30,
            side_effects=["unknown"],
        )

    def register(self, tool: "BaseTool") -> ToolManifest:
        """Register a manifest for a tool added after cache construction."""

        manifest = discover_tool_manifest(tool, surface=self.surface)
        if manifest.risk_level == RiskLevel.UNCLASSIFIED:
            fallback_risk = RiskLevel.R0_READ if manifest.readonly else RiskLevel.R1_WRITE_LOCAL
            manifest = manifest.model_copy(update={"risk_level": fallback_risk})
        self._manifests[manifest.name] = manifest
        return manifest


def discover_tool_manifest(tool: "BaseTool", *, surface: ToolSurface = ToolSurface.CLI) -> ToolManifest:
    """Derive a governance manifest from an existing BaseTool object."""

    name = str(getattr(tool, "name", tool.__class__.__name__))
    readonly = bool(getattr(tool, "is_readonly", True))
    repeatable = bool(getattr(tool, "repeatable", False))
    risk = _classify_risk(tool, readonly=readonly)
    live_classification = getattr(tool, "live_classification", None)
    if live_classification is None and _looks_live_connector(tool):
        live_classification = "READ" if readonly else "WRITE"
    return ToolManifest(
        name=name,
        surface=surface,
        readonly=readonly,
        repeatable=repeatable,
        risk_level=risk,
        requires_auth=risk in {RiskLevel.R3_TRADE_READ, RiskLevel.R4_TRADE_WRITE},
        requires_consent=risk == RiskLevel.R4_TRADE_WRITE,
        allowed_modes=_allowed_modes_for(risk),
        secret_access=_secret_access_for(risk),
        timeout_seconds=int(getattr(tool, "timeout_seconds", 30) or 30),
        side_effects=_side_effects_for(risk, readonly=readonly),
        live_classification=live_classification,
    )


def _classify_risk(tool: "BaseTool", *, readonly: bool) -> RiskLevel:
    name = str(getattr(tool, "name", "")).lower()
    class_name = tool.__class__.__name__.lower()
    module = tool.__class__.__module__.lower()
    description = str(getattr(tool, "description", "")).lower()
    combined = f"{module}.{class_name}.{name}.{description}"

    if name in SHELL_TOOL_NAMES or "shell" in combined or "subprocess" in combined or "generated code" in combined:
        return RiskLevel.R5_SHELL
    if _contains_any(combined, TRADE_WRITE_TERMS) or (not readonly and "trading_connector" in module):
        return RiskLevel.R4_TRADE_WRITE
    if _contains_any(combined, TRADE_READ_TERMS) and ("trading" in combined or "broker" in combined or "connector" in combined):
        return RiskLevel.R3_TRADE_READ
    if _contains_any(combined, NETWORK_TERMS):
        return RiskLevel.R2_NETWORK
    if not readonly:
        if module.startswith(KNOWN_LOCAL_MODULE_PREFIXES) or _contains_any(combined, LOCAL_WRITE_TERMS):
            return RiskLevel.R1_WRITE_LOCAL
        return RiskLevel.UNCLASSIFIED
    if module.startswith(KNOWN_LOCAL_MODULE_PREFIXES):
        return RiskLevel.R0_READ
    return RiskLevel.UNCLASSIFIED


def _looks_live_connector(tool: "BaseTool") -> bool:
    module = tool.__class__.__module__.lower()
    name = str(getattr(tool, "name", "")).lower()
    return "src.live." in module or name.startswith("trading_") or "broker" in f"{module}.{name}"


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _allowed_modes_for(risk: RiskLevel) -> list[str]:
    if risk == RiskLevel.R4_TRADE_WRITE:
        return ["live"]
    if risk == RiskLevel.R3_TRADE_READ:
        return ["research", "paper", "advisory", "live"]
    return ["research", "paper", "advisory"]


def _secret_access_for(risk: RiskLevel) -> str:
    if risk in {RiskLevel.R3_TRADE_READ, RiskLevel.R4_TRADE_WRITE}:
        return "broker"
    if risk == RiskLevel.R2_NETWORK:
        return "market_data_read"
    return "none"


def _side_effects_for(risk: RiskLevel, *, readonly: bool) -> list[str]:
    if risk == RiskLevel.R5_SHELL:
        return ["process_execution"]
    if risk == RiskLevel.R4_TRADE_WRITE:
        return ["live_trade_write"]
    if risk == RiskLevel.R3_TRADE_READ:
        return ["broker_read"]
    if risk == RiskLevel.R2_NETWORK:
        return ["network"]
    if risk == RiskLevel.R1_WRITE_LOCAL:
        return ["local_write"]
    return [] if readonly else ["unknown_write"]
