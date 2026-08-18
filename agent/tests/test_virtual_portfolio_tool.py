from __future__ import annotations

import ast
import json
from pathlib import Path

from src.portfolio.store import PortfolioStore
from src.tools import build_registry
from src.tools import virtual_portfolio_tool
from src.tools.virtual_portfolio_tool import VirtualPortfolioTradeTool


def test_virtual_trade_records_buy_and_sell_by_portfolio_name(tmp_path, monkeypatch):
    store = PortfolioStore(tmp_path / "portfolio.db")
    portfolio = store.create_portfolio("shared-key-holder", "量化A", "CNY")
    monkeypatch.setattr(virtual_portfolio_tool, "PortfolioStore", lambda: store)

    buy = json.loads(
        VirtualPortfolioTradeTool().execute(
            portfolio="量化A",
            symbol="600519.SH",
            side="buy",
            quantity=100,
            price=1500,
            external_ref="quant-a-buy-1",
        )
    )
    sell = json.loads(
        VirtualPortfolioTradeTool().execute(
            portfolio=portfolio.id,
            symbol="600519.SH",
            side="sell",
            quantity=20,
            price=1550,
            external_ref="quant-a-sell-1",
        )
    )

    assert buy["status"] == "ok"
    assert buy["mode"] == "virtual"
    assert buy["portfolio"]["name"] == "量化A"
    assert sell["transaction"]["type"] == "sell"
    assert sell["transaction"]["quantity"] == "20"
    snapshot = store.all_transactions("shared-key-holder", portfolio.id)
    assert {(item.type, str(item.quantity)) for item in snapshot} == {
        ("buy", "100"),
        ("sell", "20"),
    }


def test_virtual_trade_is_idempotent_and_sell_is_balance_checked(tmp_path, monkeypatch):
    store = PortfolioStore(tmp_path / "portfolio.db")
    portfolio = store.create_portfolio("shared-key-holder", "量化A", "CNY")
    monkeypatch.setattr(virtual_portfolio_tool, "PortfolioStore", lambda: store)
    tool = VirtualPortfolioTradeTool()

    kwargs = {
        "portfolio": portfolio.id,
        "symbol": "AAPL.US",
        "side": "buy",
        "quantity": 1,
        "price": 200,
        "market": "us",
        "currency": "USD",
        "external_ref": "same-fill",
    }
    assert json.loads(tool.execute(**kwargs))["status"] == "ok"
    duplicate = json.loads(tool.execute(**kwargs))
    assert duplicate["status"] == "error"
    assert "external_ref" in duplicate["error"]

    oversell = json.loads(
        tool.execute(
            **{
                **kwargs,
                "side": "sell",
                "quantity": 2,
                "external_ref": "oversell",
            }
        )
    )
    assert oversell["status"] == "error"
    assert "available quantity" in oversell["error"]


def test_virtual_trade_is_registered_and_cannot_place_broker_orders():
    registry = build_registry()

    tool = registry.get("virtual_portfolio_trade")
    assert tool is not None
    assert tool.is_readonly is False
    assert "broker" in tool.description
    assert "trading_place_order" in registry.tool_names


def test_virtual_and_broker_interfaces_have_distinct_domains_and_imports():
    from src.tools.trading_connector_tool import TradingPlaceOrderTool

    assert VirtualPortfolioTradeTool.execution_domain == "virtual_portfolio"
    assert TradingPlaceOrderTool.execution_domain == "broker"

    source = Path(virtual_portfolio_tool.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(module.startswith("src.trading") for module in imported_modules)


def test_virtual_trade_rejects_broker_routing_arguments(tmp_path, monkeypatch):
    store = PortfolioStore(tmp_path / "portfolio.db")
    portfolio = store.create_portfolio("shared-key-holder", "量化A", "CNY")
    monkeypatch.setattr(virtual_portfolio_tool, "PortfolioStore", lambda: store)

    result = json.loads(
        VirtualPortfolioTradeTool().execute(
            portfolio=portfolio.id,
            symbol="600519.SH",
            side="buy",
            quantity=100,
            price=1500,
            external_ref="broker-argument-rejected",
            connection="alpaca-live",
        )
    )

    assert result["status"] == "error"
    assert "broker/order-routing" in result["error"]
    assert store.all_transactions("shared-key-holder", portfolio.id) == []
