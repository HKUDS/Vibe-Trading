"""Internal single-day pt-v2.0 portfolio step tests.

``run_portfolio_step`` is the composition seam over the pure planner, the
all-bucket preflight, the fixed orchestrator order and the Decimal execution
adapter. It returns a deterministic internal document plus the exact Decimal
artifacts behind it; per-order rejects/cancels are rows with ``complete=False``
while any validation/data/adapter fault yields no document at all.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade import engine
from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.hash import PortfolioDataHashes, document_hash
from src.tools.paper_trade.portfolio.numeric import parse_effective_fee_model
from src.tools.paper_trade.portfolio.orchestrator import (
    ExecutionCancellation,
    ExecutionOutcome,
    OrchestrationError,
)
from src.tools.paper_trade.portfolio.schema import (
    PortfolioRequestError,
    load_portfolio_contract_schema,
)
from src.tools.paper_trade.portfolio.sessions import PortfolioSessionError
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()


class FakeLoader:
    """Offline loader double; the step must never reach a network provider."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frames[code] for code in codes if code in self.frames}


class OpenCalendar:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": 1,
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


def _frame(prior: float, target: float | None) -> pd.DataFrame:
    records = [
        {
            "trade_date": PRIOR,
            "open": prior,
            "high": prior,
            "low": prior,
            "close": prior,
            "volume": 1000.0,
        }
    ]
    if target is not None:
        records.append(
            {
                "trade_date": DAY,
                "open": target,
                "high": target,
                "low": target,
                "close": target,
                "volume": 1000.0,
            }
        )
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _loaders(*, us_target: float | None = 343.46) -> dict[str, Any]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, us_target)}, "us-fixture"),
    }


def _payload() -> dict[str, Any]:
    return json.loads(json.dumps(valid_portfolio_payload()))


def _run(payload: dict[str, Any], **kwargs: Any):
    return run_portfolio_step(
        payload,
        loaders=kwargs.pop("loaders", None) or _loaders(),
        calendar_client=kwargs.pop("calendar_client", None) or OpenCalendar(),
        **kwargs,
    )


def _explicit_payload() -> dict[str, Any]:
    payload = _payload()
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = "200000.00"
    payload["portfolio_state"]["buckets"][1]["fee_model"] = {
        "currency": "HKD",
        "parameters": {"commission_rate": "0.0003", "commission_min": "20.00"},
    }
    payload["orders"] = [
        {
            "order_id": "cn-buy-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "hk-buy-1",
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
        },
    ]
    return payload


def _target_payload() -> dict[str, Any]:
    payload = _payload()
    payload.pop("orders")
    payload["target_weights"] = [
        {
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "weight": "0.00",
        },
        {
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "weight": "0.16",
        },
        {
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "weight": "0.20",
        },
    ]
    payload["rebalance_band"] = "0"
    return payload


def _cash(step, bucket_id: str) -> Decimal:
    return next(
        bucket.cash for bucket in step.end_ledger.buckets if bucket.bucket_id == bucket_id
    )


def _hashes_check(document) -> None:
    layers = PortfolioDataHashes(
        plan_hash=document.hashes.plan_hash,
        planning_data_hash=document.hashes.planning_data_hash,
        execution_data_fingerprint=document.hashes.execution_data_fingerprint,
    )
    assert document.hashes.document_hash == document_hash(document, layers)
    assert document.hashes.planning_data_hash != document.hashes.execution_data_fingerprint
    for value in document.model_dump()["hashes"].values():
        assert len(value) == 64
        assert set(value) <= set("0123456789abcdef")


def test_explicit_orders_across_three_markets_return_deterministic_document() -> None:
    # Given explicit orders for cn_a, hk and us with an HK fee override.
    payload = _explicit_payload()

    # When the internal step composes preflight, plan, match and Decimal replay.
    step = _run(payload)
    document = step.document

    # Then every order fills at its target close and the document is complete.
    assert document.complete is True
    assert document.errors == ()
    assert [(fill.plan_order_id, fill.bucket_id) for fill in document.fills] == [
        ("cn-buy-1", "cn"),
        ("hk-buy-1", "hk"),
        ("us-buy-1", "us"),
    ]
    assert [(fill.price, fill.fee) for fill in document.fills] == [
        ("1421.000000", "36.95"),
        ("417.800000", "63.25"),
        ("343.460000", "0.99"),
    ]

    # Then the plan used the same effective fee models as execution.
    fee_models = {
        bucket.bucket_id: parse_effective_fee_model(bucket)
        for bucket in document.opening_portfolio.buckets
    }
    for order, fill in zip(step.order_plan.orders, document.fills, strict=True):
        rules = fee_models[order.bucket_id].market_rules()
        assert order.estimated_fee_local == rules.fee("buy", order.qty, order.price)
        assert fill.fee == str(rules.fee("buy", order.qty, Decimal(fill.price)))

    # Then the Decimal end ledger is exact and each bucket result is present.
    assert _cash(step, "cn") == Decimal("57863.05")
    assert _cash(step, "hk") == Decimal("8156.75")
    assert _cash(step, "us") == Decimal("21564.41")
    assert [row.bucket_id for row in document.bucket_results] == ["cn", "hk", "us"]
    assert [entry.bucket_id for entry in step.prepared_data.preflight] == [
        "cn",
        "hk",
        "us",
    ]
    assert step.order_plan.mode == "explicit_orders"
    assert len(step.order_plan.orders) == 3
    _hashes_check(document)
    schema = load_portfolio_contract_schema("result")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            document.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
    ) == []

    # Then a second call is byte-identical.
    repeated = _run(payload)
    assert repeated.document.model_dump(mode="json", by_alias=True) == document.model_dump(
        mode="json", by_alias=True
    )


def test_target_weights_return_order_plan_and_complete_document() -> None:
    # Given long-only target weights and one pre-fill FX conversion.
    step = _run(_target_payload())
    document = step.document

    # Then the plan is the deterministic sell-before-buy canonical sequence.
    assert document.complete is True
    assert step.order_plan.mode == "target_weights"
    assert [
        (order.bucket_id, order.side, order.qty) for order in step.order_plan.orders
    ] == [("cn", "sell", 100), ("hk", "buy", 100), ("us", "buy", 41)]
    assert [fill.plan_order_id for fill in document.fills] == [
        order.plan_order_id for order in step.order_plan.orders
    ]

    # Then every fill carries its bucket and plan identity and the ledger ends exact.
    assert {(fill.bucket_id, fill.plan_order_id) for fill in document.fills} == {
        (order.bucket_id, order.plan_order_id) for order in step.order_plan.orders
    }
    assert _cash(step, "cn") == Decimal("240992.00")
    assert _cash(step, "hk") == Decimal("8164.21")
    assert _cash(step, "us") == Decimal("11057.15")
    assert [row.bucket_id for row in document.bucket_results] == ["cn", "hk", "us"]
    _hashes_check(document)

    repeated = _run(_target_payload())
    assert repeated.document.model_dump(mode="json", by_alias=True) == document.model_dump(
        mode="json", by_alias=True
    )


def test_closed_holdings_only_bucket_uses_prior_marks_without_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a closed HK bucket with holdings and no HK orders.
    payload = _payload()
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = "200000.00"
    payload["orders"] = [
        {
            "order_id": "cn-buy-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
        },
    ]
    for session in payload["sessions"]:
        if session["market"] == "hk":
            session["status"] = "closed"
    called: list[str] = []
    real_run = engine.run_day_loop

    def recording(*args, **kwargs):
        called.append(str(kwargs["market"]))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(engine, "run_day_loop", recording)

    # When the step runs.
    step = _run(payload, loaders=_loaders())
    document = step.document

    # Then only the two open market buckets reached the matcher.
    assert called == ["cn_a", "us"]
    assert document.complete is True
    assert [fill.bucket_id for fill in document.fills] == ["cn", "us"]

    # Then the closed bucket was valued at its explicit prior mark.
    hk = next(row for row in document.bucket_results if row.bucket_id == "hk")
    assert (hk.cash, hk.position_value, hk.nav_base) == (
        "50000.00",
        "41000.00",
        "11648.00",
    )
    assert any("hk: market closed" in warning for warning in document.warnings)
    assert len(step.prepared_data.preflight) == 3
    _hashes_check(document)


def test_rejected_order_forces_complete_false_with_explicit_fill_and_error() -> None:
    # Given one sell that fills and one US buy limit below the target close.
    payload = _payload()
    payload["fx_conversions"] = []
    payload["orders"] = [
        {
            "order_id": "cn-sell-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "sell",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
            "limit": "300.00",
        },
    ]

    # When the matcher rejects the limit order as a terminal outcome.
    document = _run(payload).document

    # Then the successful fill is preserved but the document is incomplete.
    assert document.complete is False
    assert [(fill.plan_order_id, fill.bucket_id) for fill in document.fills] == [
        ("cn-sell-1", "cn")
    ]
    assert [
        (row.plan_order_id, row.bucket_id, row.reason_code)
        for row in document.rejected_orders
    ] == [("us-buy-1", "us", "limit_not_marketable")]
    assert [(row.reason, row.bucket_id) for row in document.errors] == [
        ("limit_not_marketable", "us")
    ]
    assert document.end_portfolio.buckets[2].cash == "25000.00"
    _hashes_check(document)


def test_canceled_order_forces_complete_false_with_bucket_and_plan_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a matcher that cancels every planned order without any ledger event.
    from src.tools.paper_trade.portfolio import step as step_module

    def cancel_all(self, request, ledger, plan, prepared):
        return ExecutionOutcome(
            canceled_orders=tuple(
                ExecutionCancellation(
                    plan_order_id=order.plan_order_id,
                    bucket_id=order.bucket_id,
                    symbol=order.symbol,
                    currency=order.currency,
                    side=order.side,
                    qty=order.qty,
                    trade_date=request.trade_date,
                    reason_code="day_end_cancel",
                    detail="canceled at session end",
                )
                for order in plan.orders
            )
        )

    monkeypatch.setattr(step_module.DecimalExecutionAdapter, "match", cancel_all)

    # When the step maps the terminal rows into the atomic envelope.
    step = _run(_explicit_payload())
    document = step.document

    # Then cancels are explicit rows and the document is incomplete but atomic.
    assert document.complete is False
    assert document.fills == ()
    assert [
        (row.bucket_id, row.plan_order_id, row.reason_code)
        for row in document.canceled_orders
    ] == [
        ("cn", "cn-buy-1", "day_end_cancel"),
        ("hk", "hk-buy-1", "day_end_cancel"),
        ("us", "us-buy-1", "day_end_cancel"),
    ]
    assert [row.reason for row in document.errors] == ["day_end_cancel"] * 3
    assert step.end_ledger == step.post_conversion_ledger
    _hashes_check(document)


def test_data_fault_returns_no_partial_document() -> None:
    # Given an open US bucket whose provider served no target-day bar.
    payload = _payload()
    payload["fx_conversions"] = []

    # When / Then preflight refuses the whole call before any fill can exist.
    with pytest.raises(PortfolioSessionError) as caught:
        _run(payload, loaders=_loaders(us_target=None))
    assert caught.value.code == "PAPER_DATA_NOT_READY"
    assert caught.value.reason == "open_bucket_zero_target_bars"
    assert caught.value.bucket_id == "us"


def test_adapter_mismatch_returns_no_partial_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a legacy matcher whose float fill disagrees with reconstruction.
    real_run = engine.run_day_loop

    def mismatched(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        if not outcome.fills:
            return outcome
        from dataclasses import replace

        fills = list(outcome.fills)
        fills[0] = replace(fills[0], fee=fills[0].fee + 1.0)
        return replace(outcome, fills=tuple(fills))

    monkeypatch.setattr(engine, "run_day_loop", mismatched)

    # When / Then the orchestrator aborts the entire in-memory document.
    with pytest.raises(OrchestrationError) as caught:
        _run(_explicit_payload())
    assert caught.value.stage == "match_orders"
    assert caught.value.code == "INTERNAL"
    assert caught.value.completed_stages == (
        "validate_opening_ledger",
        "apply_caller_conversions",
        "build_plan",
        "preflight_execution_inputs",
    )


def test_malformed_payload_is_an_invalid_request() -> None:
    # Given a portfolio-shaped payload without its required mode.
    payload = _payload()
    del payload["mode"]

    # When / Then parsing fails before any data provider is touched.
    with pytest.raises(PortfolioRequestError) as caught:
        run_portfolio_step(payload, loaders=_loaders(), calendar_client=OpenCalendar())
    assert caught.value.code == "INVALID_REQUEST"
    assert caught.value.reason == "missing_mode"


def test_missing_loader_is_rejected_before_any_network_fallback() -> None:
    # Given a loader map that does not cover the HK market.
    loaders = _loaders()
    loaders.pop("hk")

    # When / Then the step refuses instead of falling back to a live provider.
    with pytest.raises(PortfolioRequestError) as caught:
        _run(_payload(), loaders=loaders)
    assert caught.value.code == "INVALID_REQUEST"
    assert caught.value.reason == "missing_loader"
    assert caught.value.path == "loaders.hk"
