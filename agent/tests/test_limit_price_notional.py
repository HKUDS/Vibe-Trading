"""Buy-limit notional must be sized at the worse of quote and limit.

A buy limit at 2x the market used to be priced at the quote alone, so it
passed a cap sized for the quote while being fillable at twice the
authorized amount. Sell limits do not create exposure, so the quote stands
there. The MCP gate path (LiveOrderGuardTool via the Robinhood extractor)
must apply the same rule as the direct-SDK gate.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.live.paths as paths
import src.live.sdk_order_gate as sdk_order_gate
from src.live.enforcement import OrderIntent
from src.live.mandate.model import AssetClass, InstrumentType, MANDATE_SCHEMA_VERSION
from src.tools.mcp import MCPRemoteToolSpec


def _connector(last: float):
    return SimpleNamespace(get_quote=lambda symbol, config=None: {"quote": {"last": last}})


def _intent(limit_price: float | None, side: str = "buy") -> OrderIntent:
    return OrderIntent(
        symbol="AAPL",
        side=side,
        notional_usd=None,
        quantity=10.0,
        instrument_type=InstrumentType.EQUITY,
        asset_class=AssetClass.US_EQUITY,
        limit_price=limit_price,
    )


def test_buy_limit_above_quote_is_priced_at_the_limit() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=200.0), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(2000.0)


def test_buy_limit_below_quote_keeps_the_quote() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=80.0), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(1000.0)


def test_market_order_ignores_the_limit_path() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=None), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(1000.0)


def test_sell_limit_keeps_the_quote() -> None:
    intent = sdk_order_gate._normalize_notional(
        _intent(limit_price=200.0, side="sell"), _connector(last=100.0), config=None
    )
    assert intent is not None
    assert intent.notional_usd == pytest.approx(1000.0)


# --------------------------------------------------------------------------- #
# MCP gate path (LiveOrderGuardTool) — the same rule as the SDK path,          #
# reached through the Robinhood extractor + MCP adapter.                       #
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


class _McpQuoteAdapter:
    """Robinhood-shaped MCP adapter: quote tool + order placement recorder."""

    def __init__(self, *, price: float) -> None:
        self.server_name = "robinhood"
        self._price = price
        self.order_calls: list[dict] = []

    def call_tool(self, remote_name: str, arguments: dict, *, local_name=None) -> dict:
        if remote_name == "get_equity_positions":
            return {"positions": [], "status": "ok"}
        if remote_name == "get_portfolio":
            return {"equity": 5000.0, "status": "ok"}
        if remote_name == "get_equity_quotes":
            return {"status": "ok", "results": [{"symbol": arguments.get("symbol"), "last_price": self._price}]}
        self.order_calls.append({"remote": remote_name, "arguments": arguments})
        return {"status": "ok", "order_id": "rh_test_1", "state": "accepted"}


def _mcp_spec() -> MCPRemoteToolSpec:
    return MCPRemoteToolSpec(
        server_name="robinhood",
        remote_name="place_equity_order",
        local_name="mcp_robinhood_place_equity_order",
        description="Place an order.",
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
    )


def _write_mandate(live_runtime: Path, *, max_order_notional_usd: float) -> None:
    broker = live_runtime / "live" / "robinhood"
    broker.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    payload = {
        "schema_version": MANDATE_SCHEMA_VERSION,
        "hard_caps": {
            "account_funding_usd": 5000.0,
            "max_order_notional_usd": max_order_notional_usd,
            "max_total_exposure_usd": 5000.0,
            "max_leverage": 1.0,
            "allowed_instruments": ["equity", "etf"],
            "max_trades_per_day": 5,
        },
        "universe": {
            "asset_classes": ["us_equity", "us_etf"],
            "min_market_cap_usd": None,
            "min_avg_daily_volume_usd": None,
            "exclude_symbols": [],
        },
        "consent": {
            "created_at": created.isoformat(),
            "consent_token_sha256": "deadbeef",
            "broker": "robinhood",
            "account_ref": "acct_ref",
            "expires_at": (created + timedelta(days=30)).isoformat(),
        },
    }
    (broker / "mandate.json").write_text(json.dumps(payload), encoding="utf-8")


def _mcp_guard(live_runtime: Path, adapter, *, max_order_notional_usd: float = 750.0):
    from src.live.order_guard import LiveOrderGuardTool

    _write_mandate(live_runtime, max_order_notional_usd=max_order_notional_usd)
    return LiveOrderGuardTool(adapter, _mcp_spec(), broker="robinhood", session_id="s1")


def test_mcp_buy_limit_above_quote_is_blocked_at_the_limit(live_runtime: Path) -> None:
    """qty=5, quote=$100, limit=$200, cap=$750: worst-case fill $1000 must be
    enforced at the limit, so the order is BLOCKED, never forwarded."""
    adapter = _McpQuoteAdapter(price=100.0)
    guard = _mcp_guard(live_runtime, adapter, max_order_notional_usd=750.0)

    out = json.loads(
        guard.execute(
            symbol="AAPL", side="buy", instrument_type="equity",
            quantity=5.0, limit_price=200.0, order_type="limit",
        )
    )
    assert out["status"] == "blocked"
    assert out["breach"]["limit"] == "max_order_notional_usd"
    assert out["breach"]["attempted_value"] == pytest.approx(1000.0)
    assert adapter.order_calls == []


def test_mcp_buy_limit_below_quote_keeps_the_quote(live_runtime: Path) -> None:
    """A limit at or below the market is maximally fillable at the quote, so a
    $80 limit on a $100 quote must be sized at $100, not the (lower) limit."""
    adapter = _McpQuoteAdapter(price=100.0)
    guard = _mcp_guard(live_runtime, adapter, max_order_notional_usd=2000.0)

    out = json.loads(
        guard.execute(
            symbol="AAPL", side="buy", instrument_type="equity",
            quantity=10.0, limit_price=80.0, order_type="limit",
        )
    )
    assert out["status"] == "ok"  # 10 * 100 = 1000 <= 2000
    assert len(adapter.order_calls) == 1


def test_mcp_market_order_without_limit_is_unchanged(live_runtime: Path) -> None:
    adapter = _McpQuoteAdapter(price=100.0)
    guard = _mcp_guard(live_runtime, adapter, max_order_notional_usd=2000.0)

    out = json.loads(
        guard.execute(
            symbol="AAPL", side="buy", instrument_type="equity",
            quantity=10.0,
        )
    )
    assert out["status"] == "ok"
    assert len(adapter.order_calls) == 1


def test_mcp_sell_limit_keeps_the_quote(live_runtime: Path) -> None:
    """A sell limit does not create exposure, so a $200 sell limit on a $100
    quote must be sized at the quote (mirrors the SDK gate)."""
    adapter = _McpQuoteAdapter(price=100.0)
    guard = _mcp_guard(live_runtime, adapter, max_order_notional_usd=2000.0)

    out = json.loads(
        guard.execute(
            symbol="AAPL", side="sell", instrument_type="equity",
            quantity=5.0, limit_price=200.0, order_type="limit",
        )
    )
    # 5 * 100 = 500 <= 2000 → allowed; the $200 limit must not inflate it.
    assert out["status"] == "ok"
    assert len(adapter.order_calls) == 1


def test_mcp_garbage_limit_price_denies_fail_closed(live_runtime: Path) -> None:
    """A present-but-unparseable limit price is forwarded to the broker verbatim
    and cannot be priced → DENY (fail-closed), never a wave-through."""
    adapter = _McpQuoteAdapter(price=100.0)
    guard = _mcp_guard(live_runtime, adapter, max_order_notional_usd=2000.0)

    out = json.loads(
        guard.execute(
            symbol="AAPL", side="buy", instrument_type="equity",
            quantity=5.0, limit_price="not-a-price",
        )
    )
    assert out["status"] == "blocked"
    assert adapter.order_calls == []
