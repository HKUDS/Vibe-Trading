"""T6 gate — the 5m strategy-mode gates of the public ``paper_trade_step``.

A 5m strategy step is driven by the strategy file the caller points at, so the
declared UNIVERSE is the only thing that can bound the order set.  These tests
pin that contract: a 5m strategy must declare an explicit non-empty UNIVERSE
before any fetch; it may not order outside that declaration (a refusal, not a
per-symbol suspension); an inside order still fills; 1d keeps its old,
ungated behaviour; and the strategy path honours the declared reference-price
model.

Input-scope gates (symbol support, multi-day, symbol budget, BJ, loader
resolution, calendar) live in ``test_paper_trade_5m_scope``; document shape,
fills and provider faults live in ``test_paper_trade_5m_tool``.  Seed
constants, payload builders and the strategy sources are shared from
``paper_trade_5m_fixtures``.  Offline: no network, no clock, no writes.
"""

from __future__ import annotations

import json

from src.tools.paper_trade.wire import received_state_hash_from_payload
from tests.paper_trade_5m_fixtures import (
    DispersedFirstBarLoader,
    FixtureLoader,
    _DAY,
    _SYM,
    _WITNESS,
    _install_strategy,
    _outside_universe_source,
    _run,
    _strategy_payload,
    _strategy_source,
)

# ── N1: 5m strategy mode requires an explicit UNIVERSE ──


def test_a_5m_strategy_without_a_universe_is_refused_before_any_fetch() -> None:
    path = _install_strategy("no_universe_5m.py", _strategy_source())
    loader = FixtureLoader()
    document, _ = _run(
        _strategy_payload(
            path,
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        ),
        loader=loader,
    )

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "explicit non-empty UNIVERSE" in document["message"]
    assert "rejected_orders" not in document
    assert "suspended" not in json.dumps(document)
    assert loader.calls == []


def test_a_5m_strategy_with_a_universe_fills_and_leaves_an_outside_position_alone() -> None:
    path = _install_strategy("universe_5m.py", _strategy_source(_SYM))
    loader = FixtureLoader()
    document, _ = _run(
        _strategy_payload(
            path,
            account_state={
                "cash": 1_000_000.0,
                "positions": [
                    {"symbol": _SYM, "qty": 100, "avg_cost": 1421.0},
                    {"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0},
                ],
            },
        ),
        loader=loader,
    )

    assert "status" not in document
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, "sell", 100.0, 1421.00)
    ]
    assert document["events"] == []
    assert document["rejected_orders"] == []
    assert loader.five_minute_calls()[0][0] == (_SYM,)
    witness = next(position for position in document["end_state"]["positions"] if position["symbol"] == _WITNESS)
    assert (witness["qty"], witness["avg_cost"]) == (1000.0, 10.0)


def test_a_1d_strategy_without_a_universe_keeps_running() -> None:
    path = _install_strategy("no_universe_1d.py", _strategy_source())
    payload = _strategy_payload(
        path,
        account_state={
            "cash": 1_000_000.0,
            "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
        },
    )
    payload.pop("interval")

    document, _ = _run(payload)

    assert document["schema_version"] == "pt-v1.1"
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, "sell", 100.0, 1422.0)
    ]


# ── N1-B: a 5m strategy may not order outside its declared UNIVERSE ──


def test_a_5m_strategy_order_outside_its_universe_is_refused_not_suspended() -> None:
    path = _install_strategy("outside_order_5m.py", _outside_universe_source((_SYM,), _WITNESS))
    payload = _strategy_payload(
        path,
        account_state={
            "cash": 1_000_000.0,
            "positions": [
                {"symbol": _SYM, "qty": 100, "avg_cost": 1421.0},
                {"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0},
            ],
        },
    )
    loader = FixtureLoader()
    document, _ = _run(payload, loader=loader)

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert _WITNESS in document["message"]
    assert "outside the 5m UNIVERSE" in document["message"]
    assert _SYM in document["message"]
    assert document.get("fills", []) == []
    assert document.get("rejected_orders", []) == []
    assert "suspended" not in json.dumps(document)
    assert "end_state" not in document
    assert document["received_state_hash"] == received_state_hash_from_payload(payload)
    assert loader.five_minute_calls()[0][0] == (_SYM,)


def test_a_5m_strategy_order_inside_its_universe_still_fills() -> None:
    path = _install_strategy("inside_order_5m.py", _outside_universe_source((_SYM,), _SYM))
    document, _ = _run(
        _strategy_payload(
            path,
            account_state={
                "cash": 1_000_000.0,
                "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
            },
        )
    )

    assert "status" not in document
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, "sell", 100.0, 1421.00)
    ]
    assert document["rejected_orders"] == []
    assert document["events"] == []


def test_a_1d_strategy_order_outside_its_universe_is_not_gated() -> None:
    path = _install_strategy("outside_order_1d.py", _outside_universe_source((_SYM,), _WITNESS))
    payload = _strategy_payload(
        path,
        account_state={
            "cash": 1_000_000.0,
            "positions": [{"symbol": _WITNESS, "qty": 1000, "avg_cost": 10.0}],
        },
    )
    payload.pop("interval")
    loader = FixtureLoader()
    document, _ = _run(payload, loader=loader)

    assert document["schema_version"] == "pt-v1.1"
    assert "status" not in document
    assert document["fills"] == []
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [(_WITNESS, "suspended")]
    assert loader.five_minute_calls() == []


# ── The strategy path honours the declared reference-price model ──


def test_a_5m_strategy_honours_the_declared_path_model() -> None:
    path = _install_strategy("path_model_5m.py", _strategy_source(_SYM))
    account_state = {
        "cash": 1_000_000.0,
        "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 1421.0}],
    }

    median_document, _ = _run(
        _strategy_payload(path, account_state=account_state, path_model="bar_median"),
        loader=DispersedFirstBarLoader(_SYM, _DAY),
    )
    close_document, _ = _run(
        _strategy_payload(path, account_state=account_state, path_model="bar_close"),
        loader=DispersedFirstBarLoader(_SYM, _DAY),
    )

    assert median_document["fills"][0]["price"] == 1421.50
    assert close_document["fills"][0]["price"] == 1422.00
    assert median_document["engine_fingerprint"] != close_document["engine_fingerprint"]
