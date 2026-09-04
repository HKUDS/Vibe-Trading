"""Pre-trade mandate gate for DIRECT-SDK connectors (SPEC Mandate Enforcement §3).

The MCP :class:`~src.live.order_guard.LiveOrderGuardTool` gates Robinhood by
wrapping a remote MCP tool. Direct-SDK connectors (tiger / alpaca / okx /
binance / futu) place orders through a normal Python call, not an MCP tool, so
they need a function-based gate with the SAME ceremony, all fail-closed before
any order reaches the broker:

1. ``load_mandate`` — no valid mandate / unknown schema version → DENY.
2. expiry — past ``consent.expires_at`` → DENY (routes to re-auth).
3. ``halt_flag_set`` — kill switch tripped → DENY, no broker call.
4. notional normalization — a ``quantity`` order is priced (connector quote →
   data loaders) and enforced on the LARGER of explicit notional and
   ``quantity × price``; fail-closed DENY when unpriceable.
5. read positions + balance via the connector's own READ functions.
6. ``check_mandate`` — ALLOW → ``connector.place_order`` / DENY (structural) /
   PAUSE_FOR_REAUTH (quantitative).

A daily count is consumed only on a confirmed ALLOW whose ``place_order``
returned a non-error envelope. Every decision writes one audit event and the
returned payload carries the redacted record under ``live_action``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.live import pending_action
from src.live.audit import LiveActionEvent, write_live_action
from src.live.daily_count import (
    DailyCountError,
    DailyOrderLockUnavailable,
    daily_order_lock,
    increment_daily_count,
    read_daily_count,
)
from src.live.enforcement import (
    BREACH_KIND_INSTRUMENT,
    BREACH_KIND_UNIVERSE,
    OrderIntent,
    check_mandate,
    instrument_asset_class,
    last_price_usd,
)
from src.live.halt import halt_flag_set, trip_halt
from src.live.mandate.model import MANDATE_SCHEMA_VERSION, Mandate
from src.live.mandate.store import load_mandate

logger = logging.getLogger(__name__)

LIVE_ACTION_RESULT_KEY = "live_action"
_REMOTE_TOOL = "place_order"

_DECISION_ALLOW = "allow"
_DECISION_DENY = "deny"
_DECISION_PAUSE = "pause_for_reauth"


def execute_live_order(
    *,
    broker: str,
    connector_module: Any,
    config: Any,
    intent: OrderIntent,
    place_kwargs: dict[str, Any],
    session_id: str = "",
) -> dict[str, Any]:
    """Run the live mandate gate around a direct-SDK ``place_order``.

    Args:
        broker: Broker key (mandate/halt/counter/audit are keyed by this).
        connector_module: The connector's ``sdk`` module (provides
            ``place_order``/``get_positions``/``get_account_snapshot``/``get_quote``).
        config: The connector config object for a LIVE profile.
        intent: Normalized :class:`OrderIntent` built from the tool args.
        place_kwargs: Keyword args forwarded verbatim to ``connector_module.place_order``
            on ALLOW (``symbol``/``side``/``quantity``/``notional``/``order_type``/
            ``limit_price``/``time_in_force``).
        session_id: Originating session id, stamped onto audit events.

    Returns:
        On ALLOW: the connector's ``place_order`` result dict (with a
        ``live_action`` record attached). Otherwise a refusal envelope
        ``{"status":"blocked","decision",...}``.
    """
    broker = (broker or "").strip().lower()

    mandate = load_mandate(broker)
    if broker == "alpaca":
        try:
            with daily_order_lock(broker):
                recovery = _pending_recovery_result(
                    broker, session_id, connector_module, config, mandate
                )
        except DailyOrderLockUnavailable as exc:
            return _deny(
                broker, session_id, str(exc),
                ["pending_action", "daily_order_lock"], mandate, intent=None,
            )
        if recovery is not None:
            return recovery

    if mandate is None or mandate.schema_version != MANDATE_SCHEMA_VERSION:
        return _deny(broker, session_id, "no valid mandate on file", ["mandate"], mandate, intent=None)

    if _is_expired(mandate):
        return _deny(
            broker,
            session_id,
            "mandate expired — re-authorize",
            ["mandate", "expiry"],
            mandate,
            intent=None,
            reauth=True,
        )

    if halt_flag_set(broker):
        return _deny(
            broker, session_id, "live trading halted", ["mandate", "expiry", "halt_flag"], mandate, intent=None
        )

    normalized = _normalize_notional(intent, connector_module, config)
    if normalized is None:
        return _deny(
            broker,
            session_id,
            "quantity order notional could not be priced (fail-closed)",
            ["mandate", "expiry", "halt_flag", "quote"],
            mandate,
            intent=intent,
        )
    intent = normalized

    positions = _safe_read(connector_module, "get_positions", config)
    balance = _safe_read(connector_module, "get_account_snapshot", config)

    try:
        with daily_order_lock(broker):
            if broker == "alpaca":
                recovery = _pending_recovery_result(
                    broker, session_id, connector_module, config, mandate
                )
                if recovery is not None:
                    return recovery
            daily_count = read_daily_count(broker)
            breach = check_mandate(
                mandate,
                intent,
                positions,
                balance,
                broker=broker,
                remote_tool=_REMOTE_TOOL,
                daily_count=daily_count,
            )

            if breach is None:
                return _allow(
                    broker,
                    session_id,
                    connector_module,
                    config,
                    intent,
                    place_kwargs,
                    mandate,
                    positions,
                )
    except DailyOrderLockUnavailable as exc:
        return _deny(
            broker,
            session_id,
            str(exc),
            ["mandate", "expiry", "halt_flag", "daily_order_lock"],
            mandate,
            intent=intent,
        )

    reauth = breach.kind not in (BREACH_KIND_UNIVERSE, BREACH_KIND_INSTRUMENT)
    return _deny_breach(broker, session_id, breach, mandate, intent, reauth)


def _pending_recovery_result(broker, session_id, connector, config, mandate):
    """Recover an existing marker under the caller-held broker lock."""
    try:
        unresolved = pending_action.load_pending_action(broker)
    except pending_action.PendingActionError:
        return _deny(
            broker, session_id, "pending broker action is invalid and requires recovery",
            ["pending_action", "exact_broker_evidence"], mandate,
            intent=None, reason_code="pending_action_invalid",
        )
    if unresolved is None:
        return None
    if unresolved.phase == "resolved_needs_revalidation":
        return _deny(
            broker, session_id, "recovered broker order requires policy revalidation",
            ["pending_action", "exact_broker_evidence"], mandate,
            intent=None, reason_code="pending_action_needs_revalidation",
        )
    return _recover_pending_order(
        broker, session_id, connector, config, mandate, unresolved
    )


def execute_live_action(
    *,
    broker: str,
    connector_module: Any,
    config: Any,
    remote_tool: str,
    risk_reducing: bool,
    intent: OrderIntent | None,
    execute_fn: Any,
    audit_request: dict[str, Any] | None = None,
    session_id: str = "",
    structural_reason: str | None = None,
) -> dict[str, Any]:
    """Run the live mandate gate around a direct-SDK write that is not ``place_order``.

    Risk-reducing actions skip halt and mandate checks but are still
    audit-logged. Risk-increasing actions follow the same ceremony as
    :func:`execute_live_order`. The daily-count lock covers the final state
    reads, broker execution, successful count increment, and audit write so two
    concurrent actions cannot both consume the same last daily slot.
    """
    broker = (broker or "").strip().lower()
    mandate = load_mandate(broker)

    if structural_reason:
        return _deny(
            broker,
            session_id,
            structural_reason,
            ["structural_contract"],
            mandate,
            intent=intent,
        )

    if risk_reducing:
        return _execute_and_audit_live_action(
            broker=broker,
            session_id=session_id,
            remote_tool=remote_tool,
            mandate=mandate,
            intent=intent,
            execute_fn=execute_fn,
            audit_request=audit_request,
            checked=["risk_reducing"],
            consume_daily_count=False,
        )

    if mandate is None or mandate.schema_version != MANDATE_SCHEMA_VERSION:
        return _deny(
            broker,
            session_id,
            "no valid mandate on file",
            ["mandate"],
            mandate,
            intent=intent,
        )
    if intent is None:
        return _deny(
            broker,
            session_id,
            "live action missing risk intent (fail-closed)",
            ["mandate", "intent"],
            mandate,
            intent=None,
        )
    normalized = _normalize_notional(intent, connector_module, config)
    if normalized is None:
        return _deny(
            broker,
            session_id,
            "quantity order notional could not be priced (fail-closed)",
            ["mandate", "quote"],
            mandate,
            intent=intent,
        )
    intent = normalized
    checked = [
        "mandate",
        "expiry",
        "halt_flag",
        "exclude_symbols",
        "allowed_instruments",
        "asset_classes",
        "max_order_notional_usd",
        "max_total_exposure_usd",
        "max_leverage",
        "max_trades_per_day",
        "account_funding_usd",
        "universe_floors",
    ]
    try:
        with daily_order_lock(broker):
            if _is_expired(mandate):
                return _deny(
                    broker,
                    session_id,
                    "mandate expired — re-authorize",
                    ["mandate", "expiry"],
                    mandate,
                    intent=intent,
                    reauth=True,
                )
            if halt_flag_set(broker):
                return _deny(
                    broker,
                    session_id,
                    "live trading halted",
                    ["mandate", "expiry", "halt_flag"],
                    mandate,
                    intent=intent,
                )
            positions = _safe_read(connector_module, "get_positions", config)
            balance = _safe_read(connector_module, "get_account_snapshot", config)
            breach = check_mandate(
                mandate,
                intent,
                positions,
                balance,
                broker=broker,
                remote_tool=remote_tool,
                daily_count=read_daily_count(broker),
            )
            if breach is not None:
                reauth = breach.kind not in (
                    BREACH_KIND_UNIVERSE,
                    BREACH_KIND_INSTRUMENT,
                )
                return _deny_breach(
                    broker,
                    session_id,
                    breach,
                    mandate,
                    intent,
                    reauth,
                )
            return _execute_and_audit_live_action(
                broker=broker,
                session_id=session_id,
                remote_tool=remote_tool,
                mandate=mandate,
                intent=intent,
                execute_fn=execute_fn,
                audit_request=audit_request,
                checked=checked,
                consume_daily_count=True,
            )
    except DailyOrderLockUnavailable as exc:
        return _deny(
            broker,
            session_id,
            str(exc),
            ["mandate", "expiry", "halt_flag", "daily_order_lock"],
            mandate,
            intent=intent,
        )


def _execute_and_audit_live_action(
    *,
    broker: str,
    session_id: str,
    remote_tool: str,
    mandate: Mandate | None,
    intent: OrderIntent | None,
    execute_fn: Any,
    audit_request: dict[str, Any] | None,
    checked: list[str],
    consume_daily_count: bool,
) -> dict[str, Any]:
    """Execute one approved action and atomically account for its success."""
    try:
        result = execute_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("live %s raised for %s: %s", remote_tool, broker, exc)
        result = {"status": "error", "error": str(exc)}

    is_error = not isinstance(result, dict) or str(result.get("status", "")).lower() != "ok"
    if is_error:
        record = _audit_action(
            broker,
            session_id,
            remote_tool=remote_tool,
            kind="order_rejected",
            outcome="error",
            mandate=mandate,
            intent=intent,
            broker_request=audit_request,
            broker_response=result if isinstance(result, dict) else {"raw": result},
            gate_decision={
                "allowed": True,
                "decision": _DECISION_ALLOW,
                "checked_limits": checked,
            },
            error=_error_message(result),
        )
    else:
        if consume_daily_count:
            increment_daily_count(broker)
        record = _audit_action(
            broker,
            session_id,
            remote_tool=remote_tool,
            kind="order_placed",
            outcome="accepted",
            mandate=mandate,
            intent=intent,
            broker_request=audit_request,
            broker_response=result,
            gate_decision={
                "allowed": True,
                "decision": _DECISION_ALLOW,
                "checked_limits": checked,
            },
        )

    if isinstance(result, dict) and record is not None:
        result = {**result, LIVE_ACTION_RESULT_KEY: record}
    if isinstance(result, dict):
        return result
    return {"status": "error", "error": "non-dict broker result"}


# --------------------------------------------------------------------------- #
# Decision helpers
# --------------------------------------------------------------------------- #


def _allow(broker, session_id, connector_module, config, intent, place_kwargs, mandate, positions) -> dict[str, Any]:
    """Execute the order; consume a count + audit only on a non-error result."""
    pending = None
    if broker == "alpaca":
        pre_position_qty = _pre_position_qty(positions, intent.symbol)
        if place_kwargs.get("quantity") is not None and pre_position_qty is None:
            return _deny(
                broker, session_id, "exact pre-position evidence is unavailable",
                ["mandate", "expiry", "halt_flag", "pending_action", "position"],
                mandate, intent=intent,
                reason_code="pending_position_evidence_unavailable",
            )
        try:
            pending = pending_action.new_pending_order(
                broker, place_kwargs,
                pre_position_qty=pre_position_qty,
            )
            pending_action.save_pending_action(pending)
        except Exception as exc:  # noqa: BLE001 - missing evidence forbids the write
            logger.warning("pending action write failed for %s: %s", broker, exc)
            return _deny(
                broker, session_id, "pending broker action could not be persisted",
                ["mandate", "expiry", "halt_flag", "pending_action"], mandate,
                intent=intent, reason_code="pending_action_persist_failed",
            )
        place_kwargs = {**place_kwargs, "client_order_id": pending.client_order_id}

    try:
        result = connector_module.place_order(config, **place_kwargs)
    except Exception as exc:  # noqa: BLE001 - a connector raise must not escape the gate
        logger.warning("live place_order raised for %s: %s", broker, exc)
        result = {"status": "error", "error": str(exc)}

    is_error = not isinstance(result, dict) or str(result.get("status", "")).lower() != "ok"
    accounting_failed = False
    checked = [
        "mandate",
        "expiry",
        "halt_flag",
        "exclude_symbols",
        "allowed_instruments",
        "asset_classes",
        "max_order_notional_usd",
        "max_total_exposure_usd",
        "max_leverage",
        "max_trades_per_day",
        "account_funding_usd",
        "universe_floors",
    ]
    if is_error:
        record = _audit(
            broker,
            session_id,
            kind="order_rejected",
            outcome="error",
            mandate=mandate,
            intent=intent,
            broker_request=dict(place_kwargs),
            broker_response=result if isinstance(result, dict) else {"raw": result},
            gate_decision={"allowed": True, "decision": _DECISION_ALLOW, "checked_limits": checked,
                           **({"reason_code": "pending_action_unresolved"} if pending else {})},
            error=_error_message(result),
        )
    else:
        try:
            if pending is not None:
                increment_daily_count(broker, pending.action_id)
            else:
                increment_daily_count(broker)
        except DailyCountError:
            accounting_failed = True
        record = _audit(
            broker,
            session_id,
            kind="order_placed",
            outcome="accepted",
            mandate=mandate,
            intent=intent,
            broker_request=dict(place_kwargs),
            broker_response=result,
            gate_decision={"allowed": True, "decision": _DECISION_ALLOW, "checked_limits": checked,
                           **({"reason_code": "daily_action_accounting_failed"} if accounting_failed else {})},
        )
    if isinstance(result, dict) and record is not None:
        result = {**result, LIVE_ACTION_RESULT_KEY: record}
    if pending is not None:
        cleared = False
        exact_ack = (
            isinstance(result, dict)
            and result.get("client_order_id") == pending.client_order_id
            and bool(result.get("order_id"))
        )
        if not is_error and not accounting_failed and exact_ack and record is not None:
            try:
                pending_action.clear_pending_action(broker, pending.action_id)
                cleared = True
            except Exception as exc:  # noqa: BLE001 - retain the recovery block
                logger.warning("pending action clear failed for %s: %s", broker, exc)
        if not cleared:
            result = {
                **(result if isinstance(result, dict) else {"status": "error"}),
                "client_order_id": pending.client_order_id,
                "recovery_pending": True,
                "reason_code": "pending_action_unresolved",
            }
    return result if isinstance(result, dict) else {"status": "error", "error": "non-dict broker result"}


def _recover_pending_order(broker, session_id, connector, config, mandate, action):
    """Resolve one Alpaca submission by exact identity, never by resubmission."""
    checked = ["mandate", "expiry", "halt_flag", "pending_action", "exact_broker_evidence"]

    def unresolved(reason):
        return _deny(
            broker, session_id, reason, checked, mandate,
            intent=None, reason_code="pending_action_unresolved",
        )

    lookup = getattr(connector, "get_order_by_client_order_id", None)
    if lookup is None:
        return unresolved("connector lacks exact order recovery")
    try:
        response = lookup(config, client_order_id=action.client_order_id)
    except Exception as exc:  # noqa: BLE001 - read failure is insufficient evidence
        response = {"status": "error", "error": str(exc)}
    evidence = _validate_recovery_evidence(action, response)
    if evidence is None:
        return unresolved("exact broker evidence is missing or contradictory")

    status = evidence["order_status"]
    filled = Decimal(str(evidence["filled_qty"]))
    working = {"accepted", "new", "open", "pending_new", "accepted_for_bidding"}
    terminal = {"rejected", "canceled", "expired"}
    fill_statuses = {"partially_filled", "filled"}
    if (filled == 0 and status in fill_statuses) or (
        filled > 0 and status not in fill_statuses | {"canceled", "expired"}
    ):
        return _halt_fill_recovery(
            broker, session_id, mandate, action, evidence, None,
            "broker status contradicts filled quantity", checked,
        )
    if status != "rejected":
        try:
            increment_daily_count(broker, action.action_id)
        except DailyCountError:
            return unresolved("recovered order could not be durably accounted")
    if filled > 0:
        return _recover_correlated_fill(
            broker, session_id, connector, config, mandate, action, evidence, checked
        )

    record = _audit(
        broker, session_id,
        kind="order_rejected" if status == "rejected" else "order_placed",
        outcome="rejected" if status == "rejected" else ("filled" if status == "filled" else "accepted"),
        mandate=mandate, intent=None,
        broker_request=action.request.model_dump(mode="json"), broker_response=evidence,
        gate_decision={"allowed": False, "decision": _DECISION_DENY,
                       "checked_limits": checked, "reason_code": "exact_submit_recovered",
                       "action_id": action.action_id},
    )
    if record is None:
        return _recovery_refusal(broker, "recovery audit was not durable")
    if status in working:
        try:
            pending_action.transition_to_revalidation(action, evidence)
        except Exception as exc:  # noqa: BLE001 - retain the recovery block
            logger.warning("pending action transition failed for %s: %s", broker, exc)
            return _recovery_refusal(broker, "recovered order transition was not durable", record)
        return _recovery_refusal(
            broker, "recovered working order requires policy revalidation", record,
            reason_code="pending_action_needs_revalidation",
        )
    if status in terminal:
        try:
            pending_action.clear_pending_action(broker, action.action_id)
        except Exception as exc:  # noqa: BLE001 - retain the recovery block
            logger.warning("pending action clear failed for %s: %s", broker, exc)
            return _recovery_refusal(broker, "terminal recovery could not be cleared", record)
        return _recovery_refusal(
            broker, "exact terminal broker outcome recovered", record,
            reason_code="pending_action_resolved_terminal", recovery_pending=False,
        )
    return _recovery_refusal(broker, "exact fill requires position attribution", record)


def _recover_correlated_fill(
    broker, session_id, connector, config, mandate, action, evidence, checked
):
    """Attribute an exact quantity fill to the signed broker position delta."""
    request_qty = _exact_decimal(action.request.quantity)
    status = evidence["order_status"]
    persisted = action.position_resolution
    same_resolution = (
        action.phase == "resolved_fill_pending_audit"
        and action.resolution is not None
        and action.resolution.model_dump(mode="json") == evidence
        and persisted is not None
    )
    if same_resolution:
        positions = None
        before = _exact_decimal(persisted.pre_position_qty)
        after = _exact_decimal(persisted.current_position_qty)
        filled = _exact_decimal(persisted.attributed_filled_qty)
    else:
        positions = _safe_read(connector, "get_positions", config)
        before = _exact_decimal(action.pre_position_qty)
        after = _exact_position_qty(positions, action.request.symbol)
        filled = _exact_decimal(evidence["filled_qty"])
    coherent_size = (
        request_qty is not None
        and filled is not None
        and 0 < filled <= request_qty
        and before is not None
        and after is not None
        and (status != "filled" or filled == request_qty)
        and (status not in {"partially_filled", "canceled", "expired"} or filled < request_qty)
    )
    expected_after = None
    if coherent_size:
        expected_after = before + filled if action.request.side == "buy" else before - filled
    if not coherent_size or after != expected_after:
        return _halt_fill_recovery(
            broker, session_id, mandate, action, evidence, positions,
            "exact fill does not match durable quantity and signed position evidence",
            checked,
        )
    position_evidence = {
        "pre_position_qty": format(before, "f"),
        "current_position_qty": format(after, "f"),
        "attributed_filled_qty": format(filled, "f"),
    }
    if not same_resolution:
        try:
            action = pending_action.transition_to_fill_resolution(
                action, evidence, position_evidence
            )
        except Exception as exc:  # noqa: BLE001 - original marker remains fail-closed
            logger.warning("fill resolution persistence failed for %s: %s", broker, exc)
            return _recovery_refusal(broker, "fill resolution was not durable")

    broker_response = {"order": evidence, "position_evidence": position_evidence}
    record = _audit(
        broker, session_id, kind="order_placed", outcome="filled", mandate=mandate,
        intent=None, broker_request=action.request.model_dump(mode="json"),
        broker_response=broker_response,
        gate_decision={"allowed": False, "decision": _DECISION_DENY,
                       "checked_limits": checked + ["signed_position_delta"],
                       "reason_code": "exact_fill_attributed", "action_id": action.action_id},
    )
    if record is None:
        return _recovery_refusal(broker, "fill attribution audit was not durable")
    if status == "partially_filled":
        try:
            pending_action.transition_to_revalidation(action, evidence)
        except Exception as exc:  # noqa: BLE001 - retain exact evidence
            logger.warning("fill recovery transition failed for %s: %s", broker, exc)
            return _recovery_refusal(broker, "fill transition was not durable", record)
        return _recovery_refusal(
            broker, "working partial fill requires policy revalidation", record,
            reason_code="pending_action_needs_revalidation",
        )
    try:
        pending_action.clear_pending_action(broker, action.action_id)
    except Exception as exc:  # noqa: BLE001 - retain exact evidence
        logger.warning("fill recovery clear failed for %s: %s", broker, exc)
        return _recovery_refusal(broker, "resolved fill could not be cleared", record)
    return _recovery_refusal(
        broker, "exact terminal fill recovered", record,
        reason_code="pending_action_resolved_fill", recovery_pending=False,
    )


def _halt_fill_recovery(broker, session_id, mandate, action, evidence, positions, reason, checked):
    try:
        trip_halt(by="file", reason=reason, broker=broker)
    except Exception as exc:  # noqa: BLE001 - marker remains the fail-closed gate
        logger.error("fill recovery could not persist broker halt for %s: %s", broker, exc)
    record = _audit(
        broker, session_id, kind="halt_tripped", outcome="blocked", mandate=mandate,
        intent=None, broker_request=action.request.model_dump(mode="json"),
        broker_response={"order": evidence, "positions": positions},
        gate_decision={"allowed": False, "decision": _DECISION_DENY,
                       "checked_limits": checked + ["signed_position_delta"],
                       "reason_code": "pending_action_fill_inconsistent",
                       "action_id": action.action_id}, error=reason,
    )
    return _recovery_refusal(
        broker, reason, record, reason_code="pending_action_fill_inconsistent"
    )


def _exact_position_qty(positions, symbol) -> Decimal | None:
    rows = positions.get("positions", positions.get("data")) if isinstance(positions, dict) else positions
    if not isinstance(rows, list):
        return None
    target = str(symbol).strip().upper()
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get("symbol") or "").strip().upper() == target]
    if not matches:
        return Decimal(0)
    if len(matches) != 1:
        return None
    row = matches[0]
    exact_value = row.get("exact_quantity")
    try:
        quantity = _exact_decimal(
            exact_value if exact_value is not None else row.get("quantity", row.get("qty"))
        )
    except InvalidOperation:
        return None
    if quantity is None:
        return None
    if (
        exact_value is None
        and str(row.get("side") or "").strip().lower() in {"short", "sell"}
        and quantity > 0
    ):
        quantity = -quantity
    return quantity


def _validate_recovery_evidence(action, response) -> dict[str, Any] | None:
    order = response.get("order") if isinstance(response, dict) and response.get("status") == "ok" else None
    if (
        not isinstance(order, dict)
        or not isinstance(order.get("broker_order_id"), str)
        or not order["broker_order_id"]
    ):
        return None
    request = action.request
    expected = {"client_order_id": action.client_order_id, "symbol": request.symbol,
                "side": request.side, "order_type": request.order_type,
                "time_in_force": request.time_in_force}
    if any(order.get(key) != value for key, value in expected.items()):
        return None
    try:
        submitted = datetime.fromisoformat(str(order.get("submitted_at") or "").replace("Z", "+00:00"))
        normalized = dict(order)
        for key in ("quantity", "notional", "limit_price"):
            actual, wanted = _exact_decimal(order.get(key)), _exact_decimal(getattr(request, key))
            if actual != wanted:
                return None
            normalized[key] = format(actual, "f") if actual is not None else None
        filled = _exact_decimal(order.get("filled_qty"))
    except (InvalidOperation, ValueError):
        return None
    status = str(order.get("order_status") or "").strip().lower()
    supported = {"accepted", "new", "open", "pending_new", "accepted_for_bidding",
                 "rejected", "canceled", "expired", "partially_filled", "filled"}
    if submitted.tzinfo is None or filled is None or filled < 0 or status not in supported:
        return None
    normalized.update(broker_order_id=str(order["broker_order_id"]), filled_qty=format(filled, "f"),
                      order_status=status, submitted_at=submitted.isoformat())
    return normalized


def _exact_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidOperation
    number = Decimal(str(value))
    if not number.is_finite():
        raise InvalidOperation
    return number


def _recovery_refusal(
    broker, reason, record=None, *, reason_code="pending_action_unresolved", recovery_pending=True
) -> dict[str, Any]:
    result = _refusal(broker, decision=_DECISION_DENY, reason=reason, reauth=False, record=record)
    result.update(reason_code=reason_code, recovery_pending=recovery_pending)
    return result


def _deny(broker, session_id, reason, checked, mandate, *, intent, reauth=False, reason_code=None) -> dict[str, Any]:
    """Audit + return a refusal for a pre-check / structural DENY."""
    record = _audit(
        broker,
        session_id,
        kind="order_rejected",
        outcome="blocked",
        mandate=mandate,
        intent=intent,
        broker_request=None,
        broker_response=None,
        gate_decision={"allowed": False, "decision": _DECISION_DENY, "checked_limits": checked,
                       **({"reason_code": reason_code} if reason_code else {})},
        error=reason,
    )
    result = _refusal(broker, decision=_DECISION_DENY, reason=reason, reauth=reauth, record=record)
    if reason_code:
        result["reason_code"] = reason_code
    return result


def _deny_breach(broker, session_id, breach, mandate, intent, reauth) -> dict[str, Any]:
    """Audit + return a refusal for a ``check_mandate`` breach."""
    decision = _DECISION_PAUSE if reauth else _DECISION_DENY
    record = _audit(
        broker,
        session_id,
        kind="breach",
        outcome="blocked",
        mandate=mandate,
        intent=intent,
        broker_request=None,
        broker_response=None,
        gate_decision={
            "allowed": False,
            "decision": decision,
            "limit": breach.limit,
            "kind": breach.kind,
            "limit_value": breach.limit_value,
            "attempted_value": breach.attempted_value,
        },
        error=breach.detail or f"order breaches {breach.limit}",
    )
    return _refusal(
        broker,
        decision=decision,
        reason=breach.detail or f"order breaches {breach.limit}",
        reauth=reauth,
        breach=breach,
        record=record,
    )


def _refusal(broker, *, decision, reason, reauth, breach=None, record=None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "blocked",
        "decision": decision,
        "reason": reason,
        "broker": broker,
        "requires_reauthorization": reauth,
    }
    if record is not None:
        payload[LIVE_ACTION_RESULT_KEY] = record
    if breach is not None:
        payload["breach"] = {
            "broker": breach.broker,
            "limit": breach.limit,
            "limit_value": breach.limit_value,
            "attempted_value": breach.attempted_value,
            "overage": breach.overage,
            "kind": breach.kind,
            "detail": breach.detail,
            "proposed_action": {
                "symbol": breach.proposed_action.symbol,
                "side": breach.proposed_action.side,
                "notional_usd": breach.proposed_action.notional_usd,
                "quantity": breach.proposed_action.quantity,
                "instrument_type": breach.proposed_action.instrument_type.value,
            },
        }
    return payload


# --------------------------------------------------------------------------- #
# Notional normalization + reads
# --------------------------------------------------------------------------- #


def _normalize_notional(intent: OrderIntent, connector_module: Any, config: Any) -> OrderIntent | None:
    """Stamp a single authoritative ``notional_usd`` (quantity → priced).

    Currency note: the connector quote is the broker's native currency (HKD for
    HK, CNH for A-share). The mandate caps are USD; treating a local-currency
    figure as USD OVER-states USD exposure for HKD/CNH (≈7-8x), so the caps bind
    CONSERVATIVELY (over-deny, never under-deny). FX normalization is a follow-up
    before HK/CN are promoted past the structural asset-class gate.
    """
    if intent.quantity is None:
        return intent
    implied = _implied_notional(intent, connector_module, config)
    if implied is None or implied != implied or implied <= 0:
        return None
    explicit = intent.notional_usd if intent.notional_usd is not None else 0.0
    enforced = max(float(explicit), implied)
    return OrderIntent(
        symbol=intent.symbol,
        side=intent.side,
        notional_usd=enforced,
        quantity=intent.quantity,
        instrument_type=intent.instrument_type,
        asset_class=intent.asset_class,
    )


def _implied_notional(intent: OrderIntent, connector_module: Any, config: Any) -> float | None:
    """USD notional implied by ``intent.quantity``, fail-closed.

    A connector whose quantities are not unit-sized (MT5 lots: 1 lot EURUSD ==
    100,000 EUR) exposes ``quantity_notional_usd(config, symbol, quantity)``.
    When present the hook is AUTHORITATIVE and there is deliberately NO fallback
    to ``quantity x quote price`` — that product under-states a lot-sized order
    by roughly the contract size, which would silently disarm every USD cap.
    Absent the hook, behavior is byte-identical to the legacy path: quantity
    times the connector/loader quote.
    """
    sizer = getattr(connector_module, "quantity_notional_usd", None)
    if sizer is not None:
        try:
            value = sizer(config, intent.symbol, intent.quantity)
        except Exception as exc:  # noqa: BLE001 - sizing failure → fail-closed
            logger.warning("connector notional sizing failed for %s: %s", intent.symbol, exc)
            return None
        if value is None:
            return None
        return float(value)
    price = _quote_price(intent, connector_module, config)
    # A buy limit is fillable anywhere up to its limit, so the cap must be
    # sized for the worse of the two (#18): pricing it at the quote alone
    # would let a limit at 2x the market fill at twice the authorized amount.
    # Sell limits do not create exposure, so the quote stands there.
    if (
        intent.side == "buy"
        and intent.limit_price is not None
        and price is not None
    ):
        price = max(price, intent.limit_price)
    if price is None:
        return None
    return intent.quantity * price


def _quote_price(intent: OrderIntent, connector_module: Any, config: Any) -> float | None:
    """Live USD price for the intent symbol: connector quote first, loaders next."""
    broker_price = _connector_quote_price(connector_module, config, intent.symbol)
    if broker_price is not None:
        return broker_price
    asset_class = intent.asset_class or instrument_asset_class(intent.instrument_type)
    if asset_class is None:
        return None
    try:
        return last_price_usd(intent.symbol, asset_class)
    except Exception as exc:  # noqa: BLE001 - loader failure → fail-closed
        logger.warning("loader quote failed for %s: %s", intent.symbol, exc)
        return None


def _connector_quote_price(connector_module: Any, config: Any, symbol: str) -> float | None:
    """Parse a positive price from the connector's ``get_quote`` envelope."""
    getter = getattr(connector_module, "get_quote", None)
    if getter is None:
        return None
    try:
        result = getter(symbol, config=config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("connector quote failed for %s: %s", symbol, exc)
        return None
    if not isinstance(result, dict) or str(result.get("status", "")).lower() == "error":
        return None
    quote = result.get("quote")
    if not isinstance(quote, dict):
        return None
    for key in ("last", "ask", "bid", "close"):
        if key in quote:
            try:
                value = float(quote[key])
            except (TypeError, ValueError):
                continue
            if value == value and value > 0:
                return value
    return None


def _safe_read(connector_module: Any, fn_name: str, config: Any) -> object:
    """Call a connector read fn, returning ``None`` on any error (fail-closed)."""
    fn = getattr(connector_module, fn_name, None)
    if fn is None:
        return None
    try:
        result = fn(config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("connector read %s failed: %s", fn_name, exc)
        return None
    if isinstance(result, dict) and str(result.get("status", "")).lower() == "error":
        return None
    return result


def _pre_position_qty(positions: object, symbol: str) -> str | None:
    quantity = _exact_position_qty(positions, symbol)
    return format(quantity, "f") if quantity is not None else None


# --------------------------------------------------------------------------- #
# Audit + misc
# --------------------------------------------------------------------------- #


def _audit(
    broker, session_id, *, kind, outcome, mandate, intent, broker_request, broker_response, gate_decision, error=None
) -> dict | None:
    return _audit_action(
        broker,
        session_id,
        remote_tool=_REMOTE_TOOL,
        kind=kind,
        outcome=outcome,
        mandate=mandate,
        intent=intent,
        broker_request=broker_request,
        broker_response=broker_response,
        gate_decision=gate_decision,
        error=error,
        require_durable=broker == "alpaca",
    )


def _audit_action(
    broker,
    session_id,
    *,
    remote_tool: str,
    kind,
    outcome,
    mandate,
    intent,
    broker_request,
    broker_response,
    gate_decision,
    error=None,
    require_durable=False,
) -> dict | None:
    consent = mandate.consent if mandate is not None else None
    try:
        event = LiveActionEvent(
            kind=kind,  # type: ignore[arg-type]
            session_id=session_id,
            outcome=outcome,  # type: ignore[arg-type]
            server=broker,
            remote_tool=remote_tool,
            intent_normalized=_describe_intent(intent),
            mandate_snapshot_ref=consent.consent_token_sha256 if consent else None,
            consent_record_ref=consent.account_ref if consent else None,
            broker_request=broker_request,
            broker_response=broker_response,
            gate_decision=gate_decision,
            error=error,
        )
        try:
            return write_live_action(event, event_callback=None, trace_writer=None, require_durable=require_durable)
        except TypeError:
            return None if require_durable else write_live_action(event)
    except Exception as exc:  # auditing must never block a decision
        logger.warning("live-action audit write failed (%s): %s", kind, exc)
        return None


def _is_expired(mandate: Mandate) -> bool:
    raw = mandate.consent.expires_at
    try:
        expires = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires


def _error_message(result: object) -> str:
    if isinstance(result, dict):
        for key in ("error", "message", "detail"):
            value = result.get(key)
            if isinstance(value, str) and value:
                return value
    return "broker order returned an error"


def _describe_intent(intent: OrderIntent | None) -> str | None:
    if intent is None:
        return None
    size = (
        f"${intent.notional_usd:g}"
        if intent.notional_usd is not None
        else f"{intent.quantity:g} units"
        if intent.quantity is not None
        else "?"
    )
    return f"{intent.side} {size} {intent.symbol} ({intent.instrument_type.value})"
