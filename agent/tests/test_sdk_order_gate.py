"""Tests for the direct-SDK live order gate + service order routing (Layer B/C).

The gate is the red-line code: live orders must pass mandate + kill-switch +
fail-closed pre-trade checks before any broker call. These tests use a fake
connector module + a stubbed mandate/halt so they need no broker SDK.
"""

from __future__ import annotations

import json
import sys
import threading
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import pytest

import src.live.paths as live_paths
from src.config.accessor import reset_env_config
from src.live import audit as live_audit
from src.live import halt as live_halt
from src.live import pending_action as pending_state
from src.live import sdk_order_gate as gate
from src.live.daily_count import read_daily_count
from src.live.enforcement import OrderIntent
from src.live.pending_action import load_pending_action, pending_action_path
from src.live.mandate.model import (
    AssetClass,
    ConsentMeta,
    HardCaps,
    InstrumentType,
    Mandate,
    UniverseConstraint,
)
from src.trading import service
from src.trading.connectors.alpaca import sdk as alpaca_sdk
from src.trading.connectors.longbridge import credentials as lb_credentials
from tests.module_os_helpers import patch_module_os

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_longbridge_credentials(monkeypatch, tmp_path):
    """Never let Longbridge cases consume workstation env/file credentials."""
    for env_name in (
        "LONGBRIDGE_APP_KEY",
        "LONGBRIDGE_APP_SECRET",
        "LONGBRIDGE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(env_name, raising=False)
    reset_env_config()
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(live_paths, "get_runtime_root", lambda: tmp_path)


class _FakeConnector:
    """Minimal connector module stand-in capturing place_order calls."""

    def __init__(self, *, positions=None, balance=None, quote_last=100.0):
        self.placed: list[dict] = []
        self.lookups: list[str] = []
        self.lookup_result: dict | BaseException = {"status": "error", "error": "not found"}
        self._positions = positions if positions is not None else {"status": "ok", "positions": []}
        self._balance = balance if balance is not None else {"status": "ok", "account": {}}
        self._quote_last = quote_last

    def place_order(self, config, **kwargs):
        self.placed.append(kwargs)
        return {"status": "ok", "order_id": "OID-1", **kwargs}

    def get_positions(self, config):
        return self._positions

    def get_account_snapshot(self, config):
        return self._balance

    def get_quote(self, symbol, *, config=None):
        return {"status": "ok", "symbol": symbol, "quote": {"last": self._quote_last}}

    def get_order_by_client_order_id(self, config, *, client_order_id):
        self.lookups.append(client_order_id)
        if isinstance(self.lookup_result, BaseException):
            raise self.lookup_result
        return self.lookup_result


class _LostResponseConnector(_FakeConnector):
    def place_order(self, config, **kwargs):
        self.placed.append(kwargs)
        raise TimeoutError("response lost")


def _mandate(
    *,
    max_order=1_000_000.0,
    max_trades=100,
    assets=(AssetClass.US_EQUITY,),
    instruments=(InstrumentType.EQUITY,),
):
    return Mandate(
        schema_version=1,
        hard_caps=HardCaps(
            account_funding_usd=1_000_000.0,
            max_order_notional_usd=max_order,
            max_total_exposure_usd=1_000_000.0,
            max_leverage=2.0,
            allowed_instruments=tuple(instruments),
            max_trades_per_day=max_trades,
        ),
        universe=UniverseConstraint(
            asset_classes=tuple(assets),
            min_market_cap_usd=None,
            min_avg_daily_volume_usd=None,
            exclude_symbols=(),
        ),
        consent=ConsentMeta(
            created_at="2026-01-01T00:00:00+00:00",
            consent_token_sha256="deadbeef",
            broker="alpaca",
            account_ref="acct-1",
            expires_at="2999-01-01T00:00:00+00:00",
        ),
    )


def _patch_gate(monkeypatch, *, mandate, halted=False):
    monkeypatch.setattr(gate, "load_mandate", lambda broker: mandate)
    monkeypatch.setattr(gate, "halt_flag_set", lambda broker: halted)
    monkeypatch.setattr(gate, "write_live_action", lambda *a, **k: {"audited": True})
    monkeypatch.setattr(gate, "read_daily_count", lambda broker: 0)
    monkeypatch.setattr(gate, "increment_daily_count", lambda broker, action_id=None: 1)
    monkeypatch.setattr(gate, "daily_order_lock", lambda broker: nullcontext())


def _intent(notional=500.0, qty=None, asset=AssetClass.US_EQUITY):
    return OrderIntent(
        symbol="AAPL", side="buy", notional_usd=notional, quantity=qty,
        instrument_type=InstrumentType.EQUITY, asset_class=asset,
    )


def _place(connector, **place_kwargs):
    return gate.execute_live_order(
        broker="alpaca", connector_module=connector, config=object(),
        intent=_intent(),
        place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0, **place_kwargs},
    )


# --------------------------------------------------------------------------- #
# Gate decisions
# --------------------------------------------------------------------------- #


def test_gate_denies_without_mandate(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=None)
    conn = _FakeConnector()
    out = gate.execute_live_order(
        broker="alpaca", connector_module=conn, config=object(),
        intent=_intent(), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "blocked" and out["decision"] == "deny"
    assert "mandate" in out["reason"]
    assert conn.placed == []  # never reached the broker


def test_gate_denies_on_halt(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate(), halted=True)
    conn = _FakeConnector()
    out = gate.execute_live_order(
        broker="alpaca", connector_module=conn, config=object(),
        intent=_intent(), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "blocked"
    assert "halt" in out["reason"].lower()
    assert conn.placed == []


def test_gate_allows_in_bounds_and_places(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    conn = _FakeConnector()
    out = gate.execute_live_order(
        broker="alpaca", connector_module=conn, config=object(),
        intent=_intent(notional=500.0), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "ok" and out["order_id"] == "OID-1"
    assert len(conn.placed) == 1  # forwarded to broker
    assert "live_action" in out


def test_alpaca_marker_precedes_submit_and_audit_precedes_clear(monkeypatch) -> None:
    events: list[str] = []
    action_ids: list[str] = []

    class _OrderingConnector(_FakeConnector):
        def place_order(self, config, **kwargs):
            pending = load_pending_action("alpaca")
            assert pending is not None and pending.phase == "pending_write"
            assert pending.client_order_id == kwargs["client_order_id"]
            events.append("submit")
            return super().place_order(config, **kwargs)

    _patch_gate(monkeypatch, mandate=_mandate())
    def audited(*args, **kwargs):
        record = live_audit.write_live_action(*args, **kwargs)
        events.append("audit")
        return record

    monkeypatch.setattr(gate, "write_live_action", audited)
    monkeypatch.setattr(gate, "increment_daily_count",
                        lambda broker, action_id=None: action_ids.append(action_id) or 1)
    real_clear = pending_state.clear_pending_action
    monkeypatch.setattr(pending_state, "clear_pending_action",
                        lambda broker, action_id: events.append("clear") or real_clear(broker, action_id))

    connector = _OrderingConnector()
    first = _place(connector)
    second = _place(connector)

    assert first["status"] == second["status"] == "ok"
    assert events == ["submit", "audit", "clear"] * 2
    assert all(value and value.startswith("act_") for value in action_ids)
    assert connector.placed[0]["client_order_id"] != connector.placed[1]["client_order_id"]
    assert live_audit.audit_ledger_path().is_file()
    assert load_pending_action("alpaca") is None


def test_pending_persist_failure_makes_zero_broker_calls(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _FakeConnector()
    patch_module_os(
        monkeypatch, pending_state,
        fsync=lambda descriptor: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = _place(connector)

    assert result["status"] == "blocked"
    assert result["reason_code"] == "pending_action_persist_failed"
    assert connector.placed == []
    assert load_pending_action("alpaca") is None


def test_uncertain_submit_survives_restart_and_blocks_new_risk(monkeypatch) -> None:
    class _TimeoutConnector(_FakeConnector):
        def place_order(self, config, **kwargs):
            self.placed.append(kwargs)
            raise TimeoutError("response lost")

    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _TimeoutConnector()
    first = _place(connector, api_key="must-not-persist")
    restarted = load_pending_action("alpaca")
    second = _place(connector)
    raw = pending_action_path("alpaca").read_text(encoding="utf-8")

    assert first["status"] == "error" and first["recovery_pending"] is True
    assert first["reason_code"] == "pending_action_unresolved"
    assert restarted is not None and restarted.client_order_id == connector.placed[0]["client_order_id"]
    assert second["status"] == "blocked" and second["reason_code"] == "pending_action_unresolved"
    assert len(connector.placed) == 1
    assert "must-not-persist" not in raw and "api_key" not in raw
    assert set(json.loads(raw)["request"]) == {
        "symbol", "side", "quantity", "notional", "order_type", "limit_price", "time_in_force"
    }


@pytest.mark.parametrize(
    "response",
    [
        {"status": "ok", "order_id": ""},
        {"status": "ok", "order_id": "broker-1", "client_order_id": "other"},
        {},
        None,
    ],
)
def test_incomplete_or_mismatched_ack_retains_marker(monkeypatch, response) -> None:
    class _IncompleteAckConnector(_FakeConnector):
        def place_order(self, config, **kwargs):
            self.placed.append(kwargs)
            return response

    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _IncompleteAckConnector()

    result = _place(connector)

    assert result["recovery_pending"] is True
    assert result["reason_code"] == "pending_action_unresolved"
    assert load_pending_action("alpaca") is not None
    assert len(connector.placed) == 1


def _exact_order(action, *, status="new", filled_qty="0", **changes):
    order = {
        "broker_order_id": "broker-1", "client_order_id": action.client_order_id,
        "symbol": action.request.symbol, "side": action.request.side,
        "order_type": action.request.order_type, "time_in_force": action.request.time_in_force,
        "quantity": action.request.quantity, "notional": action.request.notional,
        "limit_price": action.request.limit_price, "filled_qty": filled_qty,
        "order_status": status, "submitted_at": "2026-08-25T00:00:00Z",
    }
    order.update(changes)
    return {"status": "ok", "order": order}


def test_restart_recovers_exact_working_order_once_and_never_resubmits(monkeypatch) -> None:
    counted: set[str] = set()
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(gate, "increment_daily_count",
                        lambda broker, action_id=None: counted.add(action_id) or 1)
    connector = _LostResponseConnector()
    _place(connector)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action)
    real_transition = pending_state.transition_to_revalidation
    attempts = iter((False, True))
    def crash_once(pending, evidence):
        if not next(attempts):
            raise OSError("crash after audit")
        return real_transition(pending, evidence)
    monkeypatch.setattr(pending_state, "transition_to_revalidation", crash_once)

    interrupted = _place(connector)
    recovered = _place(connector)
    replay = _place(connector)
    persisted = load_pending_action("alpaca")

    assert interrupted["reason_code"] == "pending_action_unresolved"
    assert recovered["reason_code"] == replay["reason_code"] == "pending_action_needs_revalidation"
    assert persisted.phase == "resolved_needs_revalidation" and persisted.broker_order_id == "broker-1"
    assert counted == {action.action_id}
    assert len(connector.placed) == 1 and connector.lookups == [action.client_order_id] * 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("order_status", "mystery"),
        ("submitted_at", "not-a-time"),
        ("filled_qty", -1),
        ("symbol", "MSFT"),
    ],
)
def test_persisted_resolution_revalidates_semantic_evidence(monkeypatch, field, value) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector()
    _place(connector)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action)
    _place(connector)
    path = pending_action_path("alpaca")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["resolution"][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = _place(connector)

    assert result["reason_code"] == "pending_action_invalid"
    assert len(connector.placed) == 1


@pytest.mark.parametrize("blocker", ["missing_mandate", "expired", "halted"])
def test_exact_recovery_precedes_current_policy_blockers(monkeypatch, blocker) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector()
    _place(connector)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status="canceled")
    connector.get_positions = lambda config: pytest.fail("recovery read positions")
    connector.get_account_snapshot = lambda config: pytest.fail("recovery read account")
    if blocker == "missing_mandate":
        monkeypatch.setattr(gate, "load_mandate", lambda broker: None)
    elif blocker == "expired":
        monkeypatch.setattr(gate, "_is_expired", lambda mandate: True)
    else:
        monkeypatch.setattr(gate, "halt_flag_set", lambda broker: True)

    result = _place(connector)

    assert result["reason_code"] == "pending_action_resolved_terminal"
    assert load_pending_action("alpaca") is None
    assert len(connector.placed) == 1
    assert connector.lookups == [action.client_order_id]


@pytest.mark.parametrize("change", [None, {"symbol": "MSFT"}, {"client_order_id": "manual"},
                                      {"order_status": "mystery"}])
def test_recovery_insufficient_or_mismatched_evidence_stays_blocked(monkeypatch, change) -> None:
    counted: list[str] = []
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(gate, "increment_daily_count",
                        lambda broker, action_id=None: counted.append(action_id) or 1)
    connector = _LostResponseConnector()
    _place(connector)
    action = load_pending_action("alpaca")
    connector.lookup_result = ({"status": "error", "error": "not found"}
                               if change is None else _exact_order(action, **change))

    result = _place(connector)

    assert result["reason_code"] == "pending_action_unresolved"
    assert load_pending_action("alpaca").phase == "pending_write"
    assert counted == [] and len(connector.placed) == 1


@pytest.mark.parametrize(("status", "was_counted"), [("rejected", False), ("canceled", True),
                                                      ("expired", True)])
def test_exact_zero_fill_terminal_is_audited_then_cleared(
    monkeypatch, status, was_counted,
) -> None:
    counted: list[str] = []
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(gate, "increment_daily_count",
                        lambda broker, action_id=None: counted.append(action_id) or 1)
    connector = _LostResponseConnector()
    _place(connector)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status=status)

    result = _place(connector)

    assert result["reason_code"] == "pending_action_resolved_terminal"
    assert load_pending_action("alpaca") is None
    assert counted == ([action.action_id] if was_counted else [])
    assert len(connector.placed) == 1


@pytest.mark.parametrize("status", ["partially_filled", "filled"])
def test_exact_fill_is_counted_but_retained_for_position_attribution(monkeypatch, status) -> None:
    counted: list[str] = []
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(gate, "increment_daily_count",
                        lambda broker, action_id=None: counted.append(action_id) or 1)
    connector = _LostResponseConnector()
    _place(connector)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status=status, filled_qty="1")

    result = _place(connector)

    assert result["reason_code"] == "pending_action_fill_inconsistent"
    assert load_pending_action("alpaca").phase == "pending_write"
    assert counted == [action.action_id] and len(connector.placed) == 1
    assert live_halt.halt_flag_set("alpaca") is True


@pytest.mark.parametrize(
    ("side", "before", "filled", "after", "status", "phase"),
    [
        ("buy", 25, 30, 55, "partially_filled", "resolved_needs_revalidation"),
        ("buy", 25, 100, 125, "filled", None),
        ("sell", 25, 100, -75, "filled", None),
        ("buy", 25, 30, 55, "canceled", None),
        ("sell", 100, 100, None, "filled", None),
    ],
)
def test_exact_quantity_fill_requires_matching_signed_position(
    monkeypatch, side, before, filled, after, status, phase,
) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector(
        positions={"status": "ok", "positions": [{"symbol": "AAPL", "quantity": before,
                                                    "market_value": before * 100, "side": "long"}]}
    )
    submitted = _place(connector, side=side, quantity=100, notional=None)
    action = load_pending_action("alpaca")
    assert action is not None, submitted
    connector.lookup_result = _exact_order(action, status=status, filled_qty=str(filled))
    connector._positions = {
        "status": "ok",
        "positions": ([] if after is None else [{"symbol": "AAPL", "quantity": after}]),
    }

    result = _place(connector)
    persisted = load_pending_action("alpaca")

    expected_code = "pending_action_needs_revalidation" if phase else "pending_action_resolved_fill"
    assert result["reason_code"] == expected_code
    assert (persisted.phase if persisted else None) == phase
    assert len(connector.placed) == 1 and live_halt.halt_flag_set("alpaca") is False


def test_fractional_fill_preserves_exact_position_decimals(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector(
        positions={
            "status": "ok",
            "positions": [{
                "symbol": "AAPL",
                "quantity": "0.123456789123456789",
                "market_value": "12.3456789123456789",
                "side": "long",
            }],
        }
    )
    _place(connector, quantity=0.1, notional=None)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status="filled", filled_qty="0.1")
    connector._positions = {
        "status": "ok",
        "positions": [{"symbol": "AAPL", "quantity": "0.223456789123456789"}],
    }

    result = _place(connector)

    assert result["reason_code"] == "pending_action_resolved_fill"
    assert load_pending_action("alpaca") is None
    assert live_halt.halt_flag_set("alpaca") is False


def test_exact_fill_recovery_remains_available_while_halted(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector(positions={"status": "ok", "positions": []})
    _place(connector, quantity=10, notional=None)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status="filled", filled_qty="10")
    connector._positions = {
        "status": "ok", "positions": [{"symbol": "AAPL", "quantity": "10"}]
    }
    monkeypatch.setattr(gate, "halt_flag_set", lambda broker: True)

    result = _place(connector)

    assert result["reason_code"] == "pending_action_resolved_fill"
    assert load_pending_action("alpaca") is None
    assert len(connector.placed) == 1


def test_quantity_submit_requires_unambiguous_pre_position(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector(
        positions={
            "status": "ok",
            "positions": [
                {"symbol": "AAPL", "quantity": 1, "market_value": 100},
                {"symbol": "AAPL", "quantity": 2, "market_value": 200},
            ],
        }
    )

    result = _place(connector, quantity=10, notional=None)

    assert result["status"] == "blocked"
    assert result["reason_code"] == "pending_position_evidence_unavailable"
    assert connector.placed == []
    assert load_pending_action("alpaca") is None


@pytest.mark.parametrize(
    ("quantity", "filled", "after"),
    [(100, 101, 126), (100, 30, 54), (100, 0, 25), (None, 5, 5)],
)
def test_unattributable_fill_halts_and_retains_exact_evidence(
    monkeypatch, quantity, filled, after,
) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector(
        positions={"status": "ok", "positions": [{"symbol": "AAPL", "quantity": 25,
                                                    "market_value": 2500, "side": "long"}]}
    )
    submitted = _place(connector, quantity=quantity, notional=500.0 if quantity is None else None)
    action = load_pending_action("alpaca")
    assert action is not None, submitted
    connector.lookup_result = _exact_order(action, status="filled", filled_qty=str(filled))
    connector._positions = {
        "status": "ok", "positions": [{"symbol": "AAPL", "quantity": after}]
    }

    result = _place(connector)

    assert result["reason_code"] == "pending_action_fill_inconsistent"
    assert load_pending_action("alpaca").action_id == action.action_id
    assert len(connector.placed) == 1 and live_halt.halt_flag_set("alpaca") is True


def test_fill_position_read_failure_halts_without_clearing(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _LostResponseConnector(positions={"status": "ok", "positions": []})
    _place(connector, quantity=10, notional=None)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status="filled", filled_qty="10")
    connector._positions = {"status": "error", "error": "unavailable"}

    result = _place(connector)

    assert result["reason_code"] == "pending_action_fill_inconsistent"
    assert load_pending_action("alpaca") is not None
    assert len(connector.placed) == 1 and live_halt.halt_flag_set("alpaca") is True


def test_attributed_fill_survives_audit_failure_and_replays_without_submit(monkeypatch) -> None:
    counted: set[str] = set()
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(gate, "increment_daily_count",
                        lambda broker, action_id=None: counted.add(action_id) or 1)
    connector = _LostResponseConnector(positions={"status": "ok", "positions": []})
    _place(connector, quantity=10, notional=None)
    action = load_pending_action("alpaca")
    connector.lookup_result = _exact_order(action, status="filled", filled_qty="10")
    connector._positions = {
        "status": "ok", "positions": [{"symbol": "AAPL", "quantity": 10}]
    }
    monkeypatch.setattr(gate, "write_live_action", lambda *args, **kwargs: None)

    interrupted = _place(connector)
    persisted = load_pending_action("alpaca")
    connector._positions = {
        "status": "ok", "positions": [{"symbol": "AAPL", "quantity": 999}]
    }
    connector.lookup_result = _exact_order(action, status="filled", filled_qty="11")
    contradictory = _place(connector)
    connector.lookup_result = _exact_order(action, status="filled", filled_qty="10")
    monkeypatch.setattr(gate, "write_live_action", lambda *args, **kwargs: {"audited": True})
    replay = _place(connector)

    assert interrupted["reason_code"] == "pending_action_unresolved"
    assert persisted.phase == "resolved_fill_pending_audit"
    assert persisted.resolution.filled_qty == "10"
    assert persisted.position_resolution is not None
    assert contradictory["reason_code"] == "pending_action_fill_inconsistent"
    assert replay["reason_code"] == "pending_action_resolved_fill"
    assert load_pending_action("alpaca") is None and counted == {action.action_id}
    assert len(connector.placed) == 1
    assert connector.lookups == [action.client_order_id] * 3


def test_corrupt_pending_marker_and_failed_audit_both_fail_closed(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    connector = _FakeConnector()
    monkeypatch.setattr(gate, "write_live_action", lambda *a, **k: None)

    result = _place(connector)
    assert result["status"] == "ok" and result["recovery_pending"] is True
    assert len(connector.placed) == 1

    pending_action_path("alpaca").write_text('{"schema_version":999}\n', encoding="utf-8")
    blocked = _place(connector)
    assert blocked["status"] == "blocked" and blocked["reason_code"] == "pending_action_invalid"
    assert len(connector.placed) == 1


def test_audit_durability_failure_retains_pending_marker(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(gate, "write_live_action", live_audit.write_live_action)
    connector = _FakeConnector()
    patch_module_os(monkeypatch, live_audit, fsync=lambda fd: (_ for _ in ()).throw(OSError("disk")))

    result = _place(connector)

    assert result["status"] == "ok" and result["recovery_pending"] is True
    assert result["reason_code"] == "pending_action_unresolved"
    assert len(connector.placed) == 1 and load_pending_action("alpaca") is not None


def test_acknowledged_submit_count_failure_retains_recovery_marker(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())
    monkeypatch.setattr(
        gate, "increment_daily_count",
        lambda *args: (_ for _ in ()).throw(gate.DailyCountError("disk")),
    )
    connector = _FakeConnector()

    result = _place(connector)

    assert result["status"] == "ok" and result["recovery_pending"] is True
    assert result["reason_code"] == "pending_action_unresolved"
    assert len(connector.placed) == 1 and load_pending_action("alpaca") is not None


def test_external_client_id_reaches_direct_sdk_and_tap(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Request:
        def __init__(self, **kwargs):
            captured["request"] = kwargs

    class _Client:
        def submit_order(self, *, order_data):
            return SimpleNamespace(id="oid", status="accepted", filled_qty="0")

    enums = ModuleType("alpaca.trading.enums")
    enums.OrderSide = SimpleNamespace(BUY="buy", SELL="sell")
    enums.TimeInForce = SimpleNamespace(DAY="day", GTC="gtc")
    requests = ModuleType("alpaca.trading.requests")
    requests.LimitOrderRequest = requests.MarketOrderRequest = _Request
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests)
    monkeypatch.setattr(alpaca_sdk, "_trading_client", lambda cfg: _Client())
    monkeypatch.setattr(alpaca_sdk.tap_forward, "tap_enabled", lambda: False)

    direct = alpaca_sdk.place_order(
        alpaca_sdk.AlpacaConfig(profile="paper"), symbol="AAPL", side="buy",
        quantity=1, client_order_id="vt-direct",
    )
    assert direct["status"] == "ok" and captured["request"]["client_order_id"] == "vt-direct"
    alpaca_sdk.place_order(alpaca_sdk.AlpacaConfig(profile="paper"),
                           symbol="AAPL", side="buy", quantity=1)
    assert "client_order_id" not in captured["request"]

    monkeypatch.setattr(alpaca_sdk.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(
        alpaca_sdk.tap_forward, "forward",
        lambda target, method, body, headers: captured.update(tap=json.loads(body))
        or {"ok": True, "body": {"id": "tap-oid", "status": "accepted"}},
    )
    tap = alpaca_sdk.place_order(
        alpaca_sdk.AlpacaConfig(profile="paper"), symbol="AAPL", side="buy",
        quantity=1, client_order_id="vt-tap",
    )
    assert tap["status"] == "ok" and captured["tap"]["client_order_id"] == "vt-tap"


def test_exact_lookup_normalizes_equivalent_direct_and_tap_evidence(monkeypatch) -> None:
    payload = {"id": "oid", "client_order_id": "vt-exact", "symbol": "AAPL",
               "side": "buy", "type": "market", "time_in_force": "day", "qty": "1",
               "notional": None, "limit_price": None, "filled_qty": "0", "status": "new",
               "submitted_at": "2026-08-25T00:00:00Z"}

    class _Client:
        def get_order_by_client_id(self, client_id):
            assert client_id == "vt-exact"
            return SimpleNamespace(**payload)

    monkeypatch.setattr(alpaca_sdk, "_trading_client", lambda cfg: _Client())
    monkeypatch.setattr(alpaca_sdk.tap_forward, "tap_enabled", lambda: False)
    direct = alpaca_sdk.get_order_by_client_order_id(
        alpaca_sdk.AlpacaConfig(profile="paper"), client_order_id="vt-exact")
    captured: dict[str, str] = {}
    monkeypatch.setattr(alpaca_sdk.tap_forward, "tap_enabled", lambda: True)
    monkeypatch.setattr(alpaca_sdk.tap_forward, "forward",
                        lambda target, method, body, headers:
                        captured.update(target=target, method=method) or {"ok": True, "body": payload})
    tap = alpaca_sdk.get_order_by_client_order_id(
        alpaca_sdk.AlpacaConfig(profile="paper"), client_order_id="vt-exact")

    assert direct == tap and direct["order"]["client_order_id"] == "vt-exact"
    assert captured["method"] == "GET" and "client_order_id=vt-exact" in captured["target"]


def test_gate_blocks_oversized_order(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate(max_order=100.0))
    conn = _FakeConnector()
    out = gate.execute_live_order(
        broker="alpaca", connector_module=conn, config=object(),
        intent=_intent(notional=5000.0), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 5000.0},
    )
    assert out["status"] == "blocked"
    assert out["decision"] in ("pause_for_reauth", "deny")
    assert conn.placed == []  # breach → never placed


def test_gate_blocks_disallowed_asset_class(monkeypatch) -> None:
    # Mandate allows only US equity; an HK-equity order must be denied structurally.
    _patch_gate(monkeypatch, mandate=_mandate(assets=(AssetClass.US_EQUITY,)))
    conn = _FakeConnector()
    out = gate.execute_live_order(
        broker="tiger", connector_module=conn, config=object(),
        intent=_intent(asset=AssetClass.HK_EQUITY),
        place_kwargs={"symbol": "700.HK", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "blocked" and out["decision"] == "deny"
    assert conn.placed == []


def test_gate_quantity_order_priced_and_enforced(monkeypatch) -> None:
    # quantity-only order: gate prices via connector quote (last=100) → 10*100=1000 notional.
    _patch_gate(monkeypatch, mandate=_mandate(max_order=500.0))
    conn = _FakeConnector(quote_last=100.0)
    out = gate.execute_live_order(
        broker="alpaca", connector_module=conn, config=object(),
        intent=_intent(notional=None, qty=10.0),
        place_kwargs={"symbol": "AAPL", "side": "buy", "quantity": 10.0},
    )
    # 1000 > max_order 500 → blocked
    assert out["status"] == "blocked"
    assert conn.placed == []


# --------------------------------------------------------------------------- #
# Service routing
# --------------------------------------------------------------------------- #


def test_service_place_order_paper_is_direct(monkeypatch) -> None:
    """Paper profile places directly (sandbox), bypassing the live gate."""
    conn = _FakeConnector()
    monkeypatch.setattr(service, "_sdk_module", lambda c: conn)
    monkeypatch.setattr(conn, "build_config", lambda *a, **k: object(), raising=False)
    # build_config is called on the module; give the fake one.
    conn.build_config = lambda profile_config, overrides: object()
    out = service.place_order("AAPL", "alpaca-paper-trade", side="buy", quantity=1)
    assert out["status"] == "ok"
    assert len(conn.placed) == 1
    assert out["environment"] == "paper"


def test_service_place_order_live_routes_through_gate(monkeypatch) -> None:
    """Live profile routes through the gate; no mandate → blocked, not placed."""
    conn = _FakeConnector()
    conn.build_config = lambda profile_config, overrides: object()
    monkeypatch.setattr(service, "_sdk_module", lambda c: conn)
    monkeypatch.setattr("src.live.sdk_order_gate.load_mandate", lambda broker: None)
    monkeypatch.setattr("src.live.sdk_order_gate.write_live_action", lambda *a, **k: {"audited": True})
    out = service.place_order("AAPL", "alpaca-live-trade", side="buy", notional=500.0)
    assert out["status"] == "blocked"
    assert conn.placed == []
    assert out["environment"] == "live"


def test_service_cancel_live_routes_through_live_action_gate(monkeypatch) -> None:
    """A live cancel reaches the connector only through the shared action gate."""
    conn = _FakeConnector()
    conn.cancelled = []
    conn.cancel_order = lambda config, order_id, **kwargs: (
        conn.cancelled.append((order_id, kwargs)) or {"status": "ok", "order_id": order_id}
    )
    conn.build_config = lambda profile_config, overrides: object()
    monkeypatch.setattr(service, "_sdk_module", lambda connector: conn)
    seen: dict[str, object] = {}

    def fake_execute_live_action(**kwargs):
        seen.update(kwargs)
        return {"status": "ok", "gated": True}

    monkeypatch.setattr(gate, "execute_live_action", fake_execute_live_action)
    out = service.cancel_order(
        "OID-1", "alpaca-live-trade", symbol="AAPL", session_id="session-1"
    )

    assert out["gated"] is True
    assert conn.cancelled == []
    assert seen["remote_tool"] == "cancel_order"
    assert seen["risk_reducing"] is True
    assert seen["session_id"] == "session-1"
    assert seen["audit_kind"] == "order_cancelled"


def test_no_longbridge_live_trade_profile() -> None:
    from src.trading import profiles

    ids = {p.id for p in profiles.list_profiles()}
    assert "longbridge-paper-trade" in ids
    assert "longbridge-live-trade" not in ids  # capped: no live order placement


def test_trade_profiles_have_place_capability() -> None:
    from src.trading import profiles

    for pid in ("alpaca-live-trade", "okx-live-trade", "binance-live-trade", "futu-live-trade", "tiger-live-trade"):
        prof = profiles.profile_by_id(pid)
        assert prof.readonly is False
        assert any("requires_mandate" in c for c in prof.capabilities)


# --------------------------------------------------------------------------- #
# Gate edges: expiry, count-only-on-success, connector raise, unpriceable qty
# --------------------------------------------------------------------------- #


def _expired_mandate():
    m = _mandate()
    return Mandate(
        schema_version=1, hard_caps=m.hard_caps, universe=m.universe,
        consent=ConsentMeta(
            created_at="2020-01-01T00:00:00+00:00", consent_token_sha256="x",
            broker="alpaca", account_ref="a", expires_at="2020-02-01T00:00:00+00:00",
        ),
    )


def test_gate_denies_expired_mandate(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_expired_mandate())
    conn = _FakeConnector()
    out = gate.execute_live_order(
        broker="alpaca", connector_module=conn, config=object(),
        intent=_intent(), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "blocked" and out["requires_reauthorization"] is True
    assert conn.placed == []


def test_gate_count_consumed_only_on_success(monkeypatch) -> None:
    increments: list[str] = []
    monkeypatch.setattr(gate, "load_mandate", lambda b: _mandate())
    monkeypatch.setattr(gate, "halt_flag_set", lambda b: False)
    monkeypatch.setattr(gate, "write_live_action", lambda *a, **k: {"audited": True})
    monkeypatch.setattr(gate, "read_daily_count", lambda b: 0)
    monkeypatch.setattr(gate, "increment_daily_count", lambda b: increments.append(b))
    monkeypatch.setattr(gate, "daily_order_lock", lambda broker: nullcontext())

    # Connector returns an error envelope → no count consumed.
    class _ErrConn(_FakeConnector):
        def place_order(self, config, **kwargs):
            return {"status": "error", "error": "broker rejected"}

    out = gate.execute_live_order(
        broker="alpaca", connector_module=_ErrConn(), config=object(),
        intent=_intent(), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "error"
    assert increments == []  # failed placement must not consume a daily count
    assert out["recovery_pending"] is True
    assert load_pending_action("alpaca") is not None


def test_concurrent_orders_share_one_daily_cap_permit(
    tmp_path,
    monkeypatch,
) -> None:
    """Two callers racing a cap of one must make only one broker call."""
    runtime_root = tmp_path / ".vibe-trading"
    monkeypatch.setattr(live_paths, "get_runtime_root", lambda: runtime_root)
    monkeypatch.setattr(gate, "load_mandate", lambda broker: _mandate(max_trades=1))
    monkeypatch.setattr(gate, "halt_flag_set", lambda broker: False)
    monkeypatch.setattr(gate, "write_live_action", lambda *a, **k: {"audited": True})

    entered = threading.Event()
    release = threading.Event()

    class _BlockingConnector(_FakeConnector):
        def place_order(self, config, **kwargs):
            self.placed.append(kwargs)
            entered.set()
            assert release.wait(timeout=5)
            return {"status": "ok", "order_id": f"OID-{len(self.placed)}", **kwargs}

    connector = _BlockingConnector()
    outputs: list[dict] = []
    errors: list[BaseException] = []

    def place() -> None:
        try:
            outputs.append(
                gate.execute_live_order(
                    broker="alpaca",
                    connector_module=connector,
                    config=object(),
                    intent=_intent(),
                    place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
                )
            )
        except BaseException as exc:  # test captures thread failures explicitly
            errors.append(exc)

    first = threading.Thread(target=place)
    second = threading.Thread(target=place)
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    second.join(timeout=1)
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert errors == []
    assert len(connector.placed) == 1
    assert read_daily_count("alpaca") == 1
    assert sorted(output["status"] for output in outputs) == ["blocked", "ok"]


def test_gate_connector_raise_is_caught(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())

    class _RaiseConn(_FakeConnector):
        def place_order(self, config, **kwargs):
            raise RuntimeError("sdk boom")

    out = gate.execute_live_order(
        broker="alpaca", connector_module=_RaiseConn(), config=object(),
        intent=_intent(), place_kwargs={"symbol": "AAPL", "side": "buy", "notional": 500.0},
    )
    assert out["status"] == "error"  # raise converted to error envelope, not propagated


def test_gate_quantity_unpriceable_denies(monkeypatch) -> None:
    _patch_gate(monkeypatch, mandate=_mandate())

    class _NoQuoteConn(_FakeConnector):
        def get_quote(self, symbol, *, config=None):
            return {"status": "error", "error": "no quote"}

    # Force the loader fallback to also fail so pricing is impossible.
    monkeypatch.setattr("src.live.sdk_order_gate.last_price_usd", lambda *a, **k: None)
    out = gate.execute_live_order(
        broker="alpaca", connector_module=_NoQuoteConn(), config=object(),
        intent=_intent(notional=None, qty=5.0),
        place_kwargs={"symbol": "AAPL", "side": "buy", "quantity": 5.0},
    )
    assert out["status"] == "blocked" and "priced" in out["reason"]


# --------------------------------------------------------------------------- #
# Connector order-method validation (fail-closed, no SDK needed)
# --------------------------------------------------------------------------- #


def test_longbridge_place_order_paper_only_guard() -> None:
    from src.trading.connectors.longbridge import sdk as lb

    cfg = lb.LongbridgeConfig(app_key="k", app_secret="s", access_token="t", profile="live-readonly")
    out = lb.place_order(cfg, symbol="700.HK", side="buy", quantity=100)
    assert out["status"] == "error" and "paper" in out["error"].lower()
    out2 = lb.cancel_order(cfg, "OID", symbol="700.HK")
    assert out2["status"] == "error" and "paper" in out2["error"].lower()


@pytest.mark.parametrize("connector", ["tiger", "alpaca", "okx", "binance", "futu", "longbridge", "mt5"])
def test_connector_place_order_rejects_bad_side(connector) -> None:
    import importlib

    mod = importlib.import_module(f"src.trading.connectors.{connector}.sdk")
    cfg = mod.build_config({"profile": "paper"}, None)
    out = mod.place_order(cfg, symbol="AAPL", side="hold", quantity=1)
    assert out["status"] == "error"


@pytest.mark.parametrize("connector", ["tiger", "alpaca", "okx", "binance", "futu", "longbridge", "mt5"])
def test_connector_place_order_rejects_both_qty_and_notional(connector) -> None:
    import importlib

    mod = importlib.import_module(f"src.trading.connectors.{connector}.sdk")
    cfg = mod.build_config({"profile": "paper"}, None)
    out = mod.place_order(cfg, symbol="AAPL", side="buy", quantity=1, notional=100)
    assert out["status"] == "error"


def test_okx_order_result_rejects_failed_scode() -> None:
    from src.trading.connectors.okx import sdk as ox

    cfg = ox.OKXConfig(api_key="k", api_secret="s", passphrase="p")
    # A 200 envelope (code 0) whose per-order sCode != 0 is a FAILED order.
    failed = ox._order_result(cfg, {"code": "0", "data": [{"sCode": "51008", "sMsg": "insufficient"}]}, symbol="BTC-USDT", side="buy", order_type="market", time_in_force="day")
    assert failed["status"] == "error"
    ok = ox._order_result(cfg, {"code": "0", "data": [{"ordId": "O1", "sCode": "0"}]}, symbol="BTC-USDT", side="buy", order_type="market", time_in_force="day")
    assert ok["status"] == "ok" and ok["order_id"] == "O1"
