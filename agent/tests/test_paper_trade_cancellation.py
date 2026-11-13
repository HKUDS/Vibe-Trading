"""Caller cancellation in the discrete, research-only 5m paper session."""

from __future__ import annotations

import copy
import json

import pytest

from src.tools.paper_trade.schema import parse_request
from src.tools.paper_trade.tool import run_paper_trade_step
from tests.test_paper_trade_5m_partial_fills import (
    _DAY,
    _FEE_MODEL,
    _SYM,
    _FakeCalendarClient,
    _FakeChClient,
    _FakeLoader,
    _intraday,
)


def _payload(**changes):
    payload = {
        "account_id": "paper_cancel",
        "market": "cn_a",
        "account_state": {"cash": 100_000.0, "positions": []},
        "from_date": _DAY,
        "to_date": _DAY,
        "interval": "5m",
        "fill_model": "volume_share",
        "order_volume_ratio": 0.1,
        "fee_model": dict(_FEE_MODEL),
        "orders": [
            {
                "symbol": _SYM,
                "side": "buy",
                "qty": 300,
                "limit": 10.0,
                "order_id": "alpha",
            }
        ],
    }
    payload.update(changes)
    return payload


def _cancel(at="09:40", order_id="alpha"):
    return {"order_id": order_id, "at": f"{_DAY}T{at}:00+08:00"}


def _run(payload, *, five=None):
    if five is None:
        five = _intraday(_DAY, ((10.2, 10.3, 9.8, 10.2, 1000.0),) * 3)
    loader = _FakeLoader({_SYM: five})
    document = run_paper_trade_step(
        payload,
        loader=loader,
        ch_client=_FakeChClient(),
        calendar_client=_FakeCalendarClient(frozenset({_DAY})),
        limits_client=None,
    )
    return json.loads(document), loader


@pytest.mark.parametrize(
    "at, filled", [("09:30", 0), ("09:35", 0), ("09:40", 100), ("09:45", 200)]
)
def test_cancel_precedes_matching_at_the_same_bar_label(at, filled):
    document, _ = _run(_payload(cancel_schedule=[_cancel(at)]))
    assert sum(row["qty"] for row in document["fills"]) == filled
    assert document["schema_version"] == "pt-v1.4"
    assert document["end_state"]["cash"] == 100_000 - filled * 10 - (filled // 100) * 5
    assert [
        (row["order_id"], row["qty"], row["reason_code"])
        for row in document["canceled_orders"]
    ] == [("alpha", 300 - filled, "canceled_by_caller")]
    assert [
        (row["order_id"], row["status"], row["filled"])
        for row in document["order_states"]
    ] == [("alpha", "canceled", filled)]
    assert document["cancel_results"] == [
        {
            **_cancel(at),
            "status": "pending_cancel",
            "filled": filled,
            "remaining": 300 - filled,
            "reason": "cancel_requested",
        }
    ]
    assert all(row["order_id"] == "alpha" for row in document["fills"])


def test_fully_executed_order_refuses_later_cancel_without_reversing_fills():
    document, _ = _run(_payload(cancel_schedule=[_cancel("15:00")]))
    assert document.get("cancel_results") == [
        {
            **_cancel("15:00"),
            "status": "rejected",
            "filled": 300,
            "remaining": 0,
            "reason": "terminal_held",
        }
    ]
    assert document["order_states"][0]["status"] == "held"
    assert document["canceled_orders"] == []
    assert sum(row["qty"] for row in document["fills"]) == 300
    assert document["end_state"]["cash"] == 96_985


def test_repeated_pending_cancel_does_not_duplicate_the_residual_or_fee():
    document, _ = _run(_payload(cancel_schedule=[_cancel(), _cancel("09:45")]))
    assert sum(row["qty"] for row in document["fills"]) == 100
    assert [row["reason"] for row in document["cancel_results"]] == [
        "cancel_requested",
        "already_pending_cancel",
    ]
    assert [row["status"] for row in document["cancel_results"]] == [
        "pending_cancel",
        "pending_cancel",
    ]
    assert len(document["canceled_orders"]) == 1
    assert document["canceled_orders"][0]["qty"] == 200
    assert sum(row["fee"] for row in document["fills"]) == 5


def test_schedule_is_chronological_even_when_input_is_not():
    document, _ = _run(_payload(cancel_schedule=[_cancel("09:45"), _cancel("09:40")]))
    assert document.get("cancel_results") == [
        {
            **_cancel("09:40"),
            "status": "pending_cancel",
            "filled": 100,
            "remaining": 200,
            "reason": "cancel_requested",
        },
        {
            **_cancel("09:45"),
            "status": "pending_cancel",
            "filled": 100,
            "remaining": 200,
            "reason": "already_pending_cancel",
        },
    ]


def test_caller_ids_distinguish_orders_for_the_same_symbol():
    payload = _payload()
    payload["orders"].append({**payload["orders"][0], "order_id": "beta"})
    payload["cancel_schedule"] = [_cancel("09:35")]
    document, _ = _run(payload)
    assert sum(row["qty"] for row in document["fills"]) == 300
    assert {row["order_id"] for row in document["fills"]} == {"beta"}
    assert [(row["order_id"], row["filled"]) for row in document["order_states"]] == [
        ("alpha", 0),
        ("beta", 300),
    ]


def test_positional_ids_are_still_available_to_the_caller():
    payload = _payload(cancel_schedule=[_cancel("09:35", "pt-0")])
    del payload["orders"][0]["order_id"]
    document, _ = _run(payload)
    assert document["fills"] == []
    assert document["order_states"][0]["order_id"] == "pt-0"


def test_id_only_request_selects_v14_and_returns_empty_cancel_results():
    document, _ = _run(_payload())
    assert document["schema_version"] == "pt-v1.4"
    assert document["order_states"][0]["order_id"] == "alpha"
    assert document["cancel_results"] == []


@pytest.mark.parametrize("order_id", ["", 3, False, "x" * 129, chr(0xD800)])
def test_malformed_explicit_id_is_rejected_before_fetch(order_id):
    payload = _payload()
    payload["orders"][0]["order_id"] = order_id
    document, loader = _run(payload)
    assert document.get("code") == "INVALID_REQUEST"
    assert "order_id" in document["message"]
    assert loader.calls == []


@pytest.mark.parametrize(
    "case", ["duplicate", "positional_collision", "unknown_cancel_id"]
)
def test_ambiguous_or_unknown_ids_fail_before_fetch(case):
    payload = _payload(cancel_schedule=[_cancel()])
    if case == "duplicate":
        payload["orders"].append(dict(payload["orders"][0]))
    elif case == "positional_collision":
        payload["orders"][0]["order_id"] = "pt-1"
        payload["orders"].append(
            {
                key: value
                for key, value in payload["orders"][0].items()
                if key != "order_id"
            }
        )
        payload["cancel_schedule"] = []
    else:
        payload["cancel_schedule"][0]["order_id"] = "missing"
    document, loader = _run(payload)
    assert document.get("code") == "INVALID_REQUEST"
    assert loader.calls == []


@pytest.mark.parametrize(
    "at",
    [
        f"{_DAY}T09:40:00",
        f"{_DAY}T01:40:00Z",
        f"{_DAY}T12:00:00+08:00",
        f"{_DAY}T09:41:00+08:00",
        f"{_DAY}T09:40:01+08:00",
        f"{_DAY}T15:05:00+08:00",
        "2026-10-21T09:40:00+08:00",
        "2026-02-30T09:40:00+08:00",
        None,
    ],
)
def test_cancel_time_must_be_a_same_day_session_grid_boundary(at):
    document, loader = _run(_payload(cancel_schedule=[{"order_id": "alpha", "at": at}]))
    assert document.get("code") == "INVALID_REQUEST"
    assert "cancel_schedule" in document["message"]
    assert loader.calls == []


@pytest.mark.parametrize(
    "schedule",
    [
        {},
        False,
        "09:40",
        [None],
        [{"order_id": "alpha", "at": f"{_DAY}T09:40:00+08:00", "typo": 1}],
    ],
)
def test_malformed_schedule_is_not_silently_ignored(schedule):
    document, loader = _run(_payload(cancel_schedule=schedule))
    assert document.get("code") == "INVALID_REQUEST"
    assert loader.calls == []


def test_schedule_is_covered_by_state_hash_and_engine_fingerprint():
    first, _ = _run(_payload(cancel_schedule=[_cancel("09:40")]))
    second, _ = _run(_payload(cancel_schedule=[_cancel("09:45")]))
    assert first["received_state_hash"] != second["received_state_hash"]
    assert first["engine_fingerprint"] != second["engine_fingerprint"]


def test_omitted_or_null_fields_keep_the_legacy_document_bytes():
    payload = _payload()
    del payload["orders"][0]["order_id"]
    legacy, _ = _run(payload)
    absent = copy.deepcopy(payload)
    absent["cancel_schedule"] = None
    absent["orders"][0]["order_id"] = None
    nulls, _ = _run(absent)
    assert legacy == nulls
    assert legacy["schema_version"] == "pt-v1.3"
    assert "cancel_results" not in legacy
    assert all("order_id" not in row for row in legacy["fills"])
    assert parse_request(absent).schema_version == "pt-v1.3"


@pytest.mark.parametrize("identifier", ["研究-😀", "账" * 128])
def test_valid_unicode_ids_are_preserved_without_normalization(identifier):
    payload = _payload(cancel_schedule=[_cancel(order_id=identifier)])
    payload["orders"][0]["order_id"] = identifier
    document, _ = _run(payload)
    assert document["cancel_results"][0]["order_id"] == identifier
    assert document["order_states"][0]["order_id"] == identifier
    assert json.dumps(document, ensure_ascii=False).encode("utf-8")
