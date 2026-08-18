from __future__ import annotations

from decimal import Decimal

import pytest

from src.portfolio.calculator import calculate_snapshot
from src.portfolio.store import PortfolioStore


def _store(tmp_path):
    return PortfolioStore(tmp_path / "portfolio.db")


def test_portfolio_scope_and_moving_average_accounting(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "长期投资")
    store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "10000", "currency": "CNY"})
    store.add_transaction("alice", portfolio.id, {"type": "buy", "symbol": "600519.SH", "market": "a_share", "quantity": "100", "price": "10", "fee": "1", "currency": "CNY", "trade_at": "2026-01-01"})
    store.add_transaction("alice", portfolio.id, {"type": "buy", "symbol": "600519.SH", "market": "a_share", "quantity": "50", "price": "14", "currency": "CNY", "trade_at": "2026-01-02"})
    store.add_transaction("alice", portfolio.id, {"type": "sell", "symbol": "600519.SH", "market": "a_share", "quantity": "80", "price": "20", "fee": "2", "currency": "CNY", "trade_at": "2026-01-03"})

    snapshot = calculate_snapshot(
        store.all_transactions("alice", portfolio.id),
        {"a_share:600519.SH": {"name": "贵州茅台", "price": "18", "change_pct": "2", "status": "ok"}},
    )
    holding = snapshot["holdings"][0]
    summary = snapshot["currencies"]["CNY"]
    assert holding["quantity"] == "70"
    assert holding["avg_cost"] == "11.34"
    assert summary["realized_pnl"] == "690.80"
    assert summary["cash"] == "9897"
    assert holding["price_status"] == "ok"

    assert store.list_portfolios("bob") == []
    with pytest.raises(KeyError):
        store.get_portfolio("bob", portfolio.id)


def test_dividend_fee_and_multicurrency_are_separate(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "全球 ETF")
    store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "1000", "currency": "USD"})
    store.add_transaction("alice", portfolio.id, {"type": "fee", "amount": "3", "currency": "USD"})
    store.add_transaction("alice", portfolio.id, {"type": "dividend", "amount": "12", "currency": "USD"})
    store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "5000", "currency": "CNY"})
    snapshot = calculate_snapshot(store.all_transactions("alice", portfolio.id))
    assert snapshot["currencies"]["USD"]["cash"] == "1009"
    assert snapshot["currencies"]["USD"]["dividends"] == "12"
    assert snapshot["currencies"]["USD"]["fees"] == "3"
    assert snapshot["currencies"]["CNY"]["cash"] == "5000"


def test_sell_over_position_and_duplicate_external_ref_are_rejected(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "短线")
    store.add_transaction("alice", portfolio.id, {"type": "buy", "symbol": "AAPL.US", "market": "us", "quantity": "1", "price": "100", "currency": "USD", "external_ref": "fill-1"})
    with pytest.raises(ValueError, match="available quantity"):
        store.add_transaction("alice", portfolio.id, {"type": "sell", "symbol": "AAPL.US", "market": "us", "quantity": "2", "price": "100", "currency": "USD"})
    with pytest.raises(ValueError, match="external_ref"):
        store.add_transaction("alice", portfolio.id, {"type": "buy", "symbol": "AAPL.US", "market": "us", "quantity": "1", "price": "100", "currency": "USD", "external_ref": "fill-1"})


def test_reversal_is_a_new_auditable_transaction(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "现金")
    original = store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "100", "currency": "CNY"})
    reversal = store.reverse_transaction("alice", portfolio.id, original.id)
    assert reversal.type == "withdrawal"
    assert reversal.external_ref == f"reversal:{original.id}"
    assert store.get_transaction("alice", portfolio.id, original.id).reversed_transaction_id == reversal.id
    snapshot = calculate_snapshot(store.all_transactions("alice", portfolio.id))
    assert Decimal(snapshot["currencies"]["CNY"]["cash"]) == Decimal("0")


def test_reversing_trade_restores_cash_cost_and_pnl(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "冲销")
    store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "1000", "currency": "CNY"})
    buy = store.add_transaction("alice", portfolio.id, {"type": "buy", "symbol": "600519.SH", "market": "a_share", "quantity": "10", "price": "10", "fee": "1", "currency": "CNY", "trade_at": "2026-01-01"})
    store.reverse_transaction("alice", portfolio.id, buy.id)
    snapshot = calculate_snapshot(store.all_transactions("alice", portfolio.id))
    assert snapshot["holdings"] == []
    assert snapshot["currencies"]["CNY"]["cash"] == "1000"
    assert snapshot["currencies"]["CNY"]["total_return"] == "0"


def test_dividend_fee_reduces_cash_and_return(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "分红")
    store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "1000", "currency": "CNY"})
    store.add_transaction("alice", portfolio.id, {"type": "dividend", "amount": "100", "fee": "3", "currency": "CNY"})
    snapshot = calculate_snapshot(store.all_transactions("alice", portfolio.id))
    assert snapshot["currencies"]["CNY"]["cash"] == "1097"
    assert snapshot["currencies"]["CNY"]["total_return"] == "97"


def test_deposit_and_withdrawal_costs_are_expenses(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "手续费")
    store.add_transaction("alice", portfolio.id, {"type": "deposit", "amount": "1000", "fee": "2", "currency": "CNY"})
    store.add_transaction("alice", portfolio.id, {"type": "withdrawal", "amount": "100", "tax": "1", "currency": "CNY"})
    summary = calculate_snapshot(store.all_transactions("alice", portfolio.id))["currencies"]["CNY"]
    assert summary["cash"] == "897"
    assert summary["total_return"] == "-3"


def test_commodity_asset_is_supported(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "黄金")
    item = store.add_transaction(
        "alice",
        portfolio.id,
        {"type": "buy", "symbol": "XAUUSD", "market": "commodity", "quantity": "2", "price": "2000", "currency": "USD"},
    )
    assert item.asset_type == "commodity"
    snapshot = calculate_snapshot(store.all_transactions("alice", portfolio.id))
    assert snapshot["holdings"][0]["asset_type"] == "commodity"


def test_manual_price_override_is_persisted(tmp_path):
    store = _store(tmp_path)
    portfolio = store.create_portfolio("alice", "积存金")
    store.add_transaction(
        "alice",
        portfolio.id,
        {"type": "buy", "symbol": "BANK_GOLD", "market": "other", "asset_type": "bank_gold", "quantity": "10", "price": "500", "currency": "CNY"},
    )
    saved = store.save_price_override("alice", portfolio.id, symbol="BANK_GOLD", market="other", currency="CNY", price="520")
    assert saved["price"] == "520"
    assert store.list_price_overrides("alice", portfolio.id)["other:BANK_GOLD:CNY"]["price"] == "520"


def test_instrument_search_includes_stock_metadata_and_gold(monkeypatch):
    from src.api import portfolio_routes
    from src.api import market_routes

    def fake_search(query, market):
        return [{"symbol": "600519.SH", "name": "贵州茅台", "short_name": "茅台", "market": market}]

    monkeypatch.setattr(market_routes, "_search_market_symbols", fake_search)
    items = portfolio_routes._portfolio_instrument_search("茅台")
    assert any(item["symbol"] == "600519.SH" and item["short_name"] == "茅台" for item in items)

    gold = portfolio_routes._portfolio_instrument_search("gold")
    assert gold[0]["symbol"] == "XAUUSD"
    assert gold[0]["asset_type"] == "commodity"
