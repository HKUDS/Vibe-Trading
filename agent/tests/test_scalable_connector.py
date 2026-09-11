"""Tests for the read-only Scalable Capital connector (#1367).

The connector has no Scalable account behind it — nobody maintaining the repo
has one — so these tests pin exactly what can be verified without one: the
frozen tool catalog, the profile shape, the gate wiring, and the seeded
allowlist matching the curated READ names. Nothing here asserts that a read
returns the right numbers; that needs a live ``tools/list`` plus an account.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mcp import types as mcp_types

import src.live.paths as paths
from src.live.extractors import get_extractor
from src.live.mandate.model import MANDATE_SCHEMA_VERSION
from src.live.order_guard import LiveOrderGuardTool
from src.live.registry import is_live_broker, wrap_live_broker_tools
from src.tools.mcp import MCPRemoteTool, build_mcp_tool_wrappers

from src.config.schema import (
    LIVE_BROKER_SERVER_KEYS,
    LIVE_BROKER_URL_HOST_SUFFIX_TO_KEY,
    SCALABLE_MCP_SERVER_SEED,
    AgentConfig,
    MCPServerConfig,
    is_live_broker_url,
)
from src.live import registry
from src.live.classification import ToolClass, classify_tool
from src.trading import profiles, service
from src.trading.connectors.scalable.classification import SCALABLE_TOOL_CLASS
from src.trading.connectors.scalable.mcp import remote_arguments, remote_tool_name

pytestmark = pytest.mark.unit

_CURATED_READS = {name for name, cls in SCALABLE_TOOL_CLASS.items() if cls is ToolClass.READ}
_CURATED_WRITES = {name for name, cls in SCALABLE_TOOL_CLASS.items() if cls is ToolClass.WRITE}


def test_profile_is_registered_readonly_remote_mcp() -> None:
    profile = profiles.profile_by_id("scalable-live-mcp-readonly")

    assert profile.connector == "scalable"
    assert profile.environment == "live"
    assert profile.transport == "remote_mcp"
    assert profile.readonly is True
    assert profile.config == {"server": "scalable"}
    assert set(profile.capabilities) == {"account.read", "positions.read", "quotes.read"}
    # A read-only connector must not advertise an order capability in any form.
    assert not [c for c in profile.capabilities if c.startswith("orders.place")]


def test_no_builtin_scalable_profile_can_place_orders() -> None:
    scalable = [p for p in profiles.list_profiles() if p.connector == "scalable"]

    assert scalable, "scalable profiles missing from the registry"
    assert all(p.readonly for p in scalable)
    assert not any(c.startswith("orders.place") for p in scalable for c in p.capabilities)


def test_curated_catalog_pins_reads_and_writes() -> None:
    curated = registry._BROKER_CURATED_MAPS["scalable"]

    assert curated is SCALABLE_TOOL_CLASS
    for name in ("get_account_profile", "get_portfolio_holdings", "list_accessible_portfolios"):
        assert curated[name] is ToolClass.READ
        assert classify_tool(name, None, curated) is ToolClass.READ

    for name in ("submit_buy_order", "cancel_order", "upsert_savings_plan"):
        assert curated[name] is ToolClass.WRITE
        assert classify_tool(name, None, curated) is ToolClass.WRITE

    # An unrecognized Scalable tool fails closed.
    assert classify_tool("scalable_new_operation", None, curated) is ToolClass.UNKNOWN


def test_a_deceptive_readonly_annotation_cannot_demote_a_curated_write() -> None:
    from mcp.types import ToolAnnotations

    curated = registry._BROKER_CURATED_MAPS["scalable"]
    lying = ToolAnnotations(readOnlyHint=True, destructiveHint=False)

    for name in _CURATED_WRITES:
        assert classify_tool(name, lying, curated) is ToolClass.WRITE


def test_order_path_previews_are_pinned_write() -> None:
    """A preview mutates nothing, but it is on the order path — not a read."""
    for name in ("preview_buy_order", "preview_sell_order"):
        assert SCALABLE_TOOL_CLASS[name] is ToolClass.WRITE


def test_seed_allowlist_is_exactly_the_curated_read_names() -> None:
    seed = list(SCALABLE_MCP_SERVER_SEED["enabled_tools"])

    assert "*" not in seed
    assert set(seed) == _CURATED_READS, (
        "the seeded enabled_tools must equal the curated READ names; a seeded "
        "name the map does not classify READ would be gated and refused"
    )
    assert len(seed) == len(set(seed))


def test_seed_never_enables_an_order_path_tool() -> None:
    seed = set(SCALABLE_MCP_SERVER_SEED["enabled_tools"])

    assert not (seed & _CURATED_WRITES), "an order-path tool is seeded as enabled"


def test_seed_is_a_live_broker_channel_with_no_wildcard() -> None:
    cfg = AgentConfig.model_validate({"mcpServers": {"scalable": SCALABLE_MCP_SERVER_SEED}})
    server = cfg.mcp_servers["scalable"]

    assert server.resolved_transport() == "streamableHttp"
    assert server.url == "https://mcp.scalable.capital/mcp"
    assert server.auth is not None and server.auth.type == "oauth"
    assert server.auth.cache_dir == "~/.vibe-trading/live/scalable/oauth"
    assert server.auth.scopes == []
    assert "*" not in server.enabled_tools
    assert "scalable" in LIVE_BROKER_SERVER_KEYS


def test_wildcard_is_rejected_for_scalable() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        AgentConfig.model_validate(
            {
                "mcpServers": {
                    "scalable": {
                        "type": "streamableHttp",
                        "url": "https://mcp.scalable.capital/mcp",
                        "auth": {"type": "oauth"},
                        "enabledTools": ["*"],
                    }
                }
            }
        )


def test_aliased_key_with_scalable_url_is_still_a_live_broker() -> None:
    assert LIVE_BROKER_URL_HOST_SUFFIX_TO_KEY["scalable.capital"] == "scalable"
    assert is_live_broker_url("https://mcp.scalable.capital/mcp") is True
    assert is_live_broker_url("https://mcp.scalable.capital.evil.test/mcp") is False

    with pytest.raises(ValueError, match="wildcard"):
        AgentConfig.model_validate(
            {
                "mcpServers": {
                    "sc": {
                        "type": "streamableHttp",
                        "url": "https://mcp.scalable.capital/mcp",
                        "auth": {"type": "oauth"},
                        "enabledTools": ["*"],
                    }
                }
            }
        )


def test_generic_operations_map_to_read_tools() -> None:
    assert remote_tool_name("account") == "get_portfolio_overview"
    assert remote_tool_name("positions") == "get_portfolio_holdings"
    assert remote_tool_name("quote") == "get_security_quote"
    # No open-order read tool exists in the published catalog.
    assert remote_tool_name("orders") is None


def test_service_dispatch_reaches_the_scalable_mapping() -> None:
    assert service._remote_tool_name("scalable", "positions") == "get_portfolio_holdings"
    assert service._remote_arguments("scalable", "positions", {"account_number": "P-1"}) == {"portfolio_id": "P-1"}
    assert service._remote_tool_name("scalable", "orders") is None


def test_remote_arguments_never_invents_a_portfolio() -> None:
    assert remote_arguments("positions", {}) == {}
    assert remote_arguments("account", {"account_number": "   "}) == {}
    assert remote_arguments("quote", {"symbol": "IE00B4L5Y983"}) == {"symbols": ["IE00B4L5Y983"]}
    assert remote_arguments("quote", {"symbols": ["IE00B4L5Y983", "IE00B5BMR087"]}) == {
        "symbols": ["IE00B4L5Y983", "IE00B5BMR087"]
    }
    assert remote_arguments("quote", {}) == {}


# ── Adversarial pass: what an operator could still do, and where it lands ─────
#
# The seed is OFF-by-default, but nothing stops an operator hand-editing
# `enabledTools` — that is the documented path for the Robinhood write tools.
# These four tests take that path for Scalable and pin where it ends.

_SCALABLE_CATALOG = tuple(str(t) for t in SCALABLE_MCP_SERVER_SEED["enabled_tools"]) + ("submit_buy_order",)


class _RefusingClient:
    """Mock MCP client that fails the test if a remote call is ever attempted."""

    async def __aenter__(self) -> "_RefusingClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def list_tools(self) -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(name=name, description=f"remote {name}", inputSchema={"type": "object"})
            for name in _SCALABLE_CATALOG
        ]

    async def call_tool(self, name, arguments=None, *, timeout=None, raise_on_error=False):
        raise AssertionError(f"the gate must refuse before any remote call (tried {name})")


def _assemble(enabled_tools: list[str]) -> list[MCPRemoteTool]:
    """Discover + live-wrap the scalable channel for a given allowlist."""
    cfg = MCPServerConfig.model_validate(dict(SCALABLE_MCP_SERVER_SEED) | {"enabled_tools": enabled_tools})
    wrappers = build_mcp_tool_wrappers("scalable", cfg, client_factory=lambda: _RefusingClient())
    assert is_live_broker("scalable", cfg.url)
    return wrap_live_broker_tools("scalable", wrappers, url=cfg.url)


def test_seeded_read_tools_are_plain_readonly_and_ungated() -> None:
    tools = _assemble(list(SCALABLE_MCP_SERVER_SEED["enabled_tools"]))

    assert {t._spec.remote_name for t in tools} == set(SCALABLE_MCP_SERVER_SEED["enabled_tools"])
    assert all(type(t) is MCPRemoteTool and t.is_readonly for t in tools)
    assert not any(isinstance(t, LiveOrderGuardTool) for t in tools)


def test_a_hand_enabled_order_tool_is_gate_wrapped_not_exposed() -> None:
    """An operator adding a WRITE name by hand gets a gated tool, never a plain one."""
    tools = _assemble(list(SCALABLE_MCP_SERVER_SEED["enabled_tools"]) + ["submit_buy_order"])
    by_name = {t._spec.remote_name: t for t in tools}

    assert type(by_name["submit_buy_order"]) is LiveOrderGuardTool
    assert by_name["submit_buy_order"].broker == "scalable"
    assert type(by_name["get_portfolio_holdings"]) is MCPRemoteTool


def test_scalable_has_no_order_intent_extractor() -> None:
    """No extractor is registered for Scalable — the gate can only fail closed."""
    assert get_extractor("scalable") is None


def test_order_path_fails_closed_at_the_intent_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hand-enabled Scalable order is refused before any remote call.

    This exercises the gate's no-extractor branch, which had no test before this
    connector: Scalable is the first live-capable connector that ships without an
    order-intent extractor, so nothing else could reach
    "order intent could not be parsed". A committed mandate is deliberately
    present, so the refusal cannot be explained by a missing mandate.
    """
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    _commit_scalable_mandate(tmp_path)

    guard = {
        t._spec.remote_name: t
        for t in _assemble(list(SCALABLE_MCP_SERVER_SEED["enabled_tools"]) + ["submit_buy_order"])
    }["submit_buy_order"]
    # The fake client raises if this reaches the broker; a refusal payload is the
    # only way this line returns.
    payload = json.loads(guard.execute(symbol="VWCE", side="buy", quantity=1, instrument_type="etf"))

    assert payload["status"] == "blocked"
    assert payload["reason"] == "order intent could not be parsed"
    decision = payload["live_action"]["gate_decision"]
    assert decision["allowed"] is False
    assert decision["decision"] == "deny"
    assert decision["checked_limits"] == ["mandate", "expiry", "halt_flag", "intent"]
    # Nothing was sized and nothing reached the broker: the refusal is structural,
    # not a mandate-cap rejection.
    assert payload["live_action"]["intent_normalized"] is None
    assert payload["live_action"]["broker_request"] is None


def _commit_scalable_mandate(runtime_root: Path) -> None:
    """Write a valid committed mandate for Scalable, so a denial is not 'no mandate'."""
    broker = runtime_root / "live" / "scalable"
    broker.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    payload = {
        "schema_version": MANDATE_SCHEMA_VERSION,
        "hard_caps": {
            "account_funding_usd": 5000.0,
            "max_order_notional_usd": 750.0,
            "max_total_exposure_usd": 5000.0,
            "max_leverage": 1.0,
            "allowed_instruments": ["equity", "etf"],
            "max_trades_per_day": 5,
        },
        "universe": {
            # No EU bucket exists in the mandate AssetClass vocabulary (us/hk/cn/in
            # equity, crypto, forex) — see the follow-up noted in the PR. Any
            # valid bucket works here; the refusal under test happens earlier.
            "asset_classes": ["us_etf"],
            "min_market_cap_usd": None,
            "min_avg_daily_volume_usd": None,
            "exclude_symbols": [],
        },
        "consent": {
            "created_at": created.isoformat(),
            "consent_token_sha256": "deadbeef",
            "broker": "scalable",
            "account_ref": "acct_ref",
            "expires_at": (created + timedelta(days=30)).isoformat(),
        },
    }
    (broker / "mandate.json").write_text(json.dumps(payload), encoding="utf-8")
