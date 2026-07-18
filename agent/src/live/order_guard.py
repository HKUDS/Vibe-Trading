"""Pre-trade enforcement gate (SPEC.md Mandate Enforcement §3).

:class:`LiveOrderGuardTool` is the dedicated wrapper that owns the live-order
gate. It subclasses :class:`~src.tools.mcp.MCPRemoteTool` and is instantiated
only for a broker's order-placing (WRITE/UNKNOWN) remote tools; every read tool
keeps the untouched plain ``MCPRemoteTool.execute()`` path with no gate.

On every ``execute()`` it runs, in order and **all fail-closed** before any
broker call:

1. ``load_mandate`` — no valid mandate / unknown schema version → DENY.
2. expiry — past ``consent.expires_at`` → DENY (routes to re-auth).
3. ``halt_flag_set`` — kill switch tripped → DENY, NO remote call.
4. ``extract_order_intent`` — unparseable order → DENY.
5. read positions + balance via the broker's READ MCP tools (plain path).
6. ``check_mandate`` — ALLOW (forward via ``super().execute``) / DENY
   (structural: universe|instrument) / PAUSE_FOR_REAUTH (quantitative).

The daily ``trade_counter.json`` is incremented only on a confirmed ALLOW whose
forwarded broker result is **non-error** (``MCPServerAdapter.call_tool`` returns
an error envelope, it does not raise — a failed forward never placed an order and
never consumes a count), with UTC-date rollover. Every decision writes one
live-action audit event via :func:`src.live.audit.write_live_action`, and the
returned tool_result carries that redacted record under the frozen
``"live_action"`` key so the api_server SSE relay can emit a ``live.action``
event without touching the agent loop.

When the order is sized by ``quantity``, the gate derives a live quote (the
broker-specific quote READ tool first, then the data loaders) and enforces the
LARGER of the explicit notional and ``quantity`` × price — fail-closed DENY when
no quote is obtainable — so the notional/exposure/leverage caps stay enforceable.

``repeatable = False`` mirrors the no-retry stance in
``MCPServerAdapter._call_tool`` — a live order must never be silently re-issued.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from src.config.accessor import get_env_config
from src.live.advisory import (
    AdvisoryContext,
    AdvisoryOrchestrator,
    Verdict,
    get_advisory_providers,
)
from src.live.audit import LiveActionEvent, write_live_action
from src.live.enforcement import (
    BREACH_KIND_INSTRUMENT,
    BREACH_KIND_UNIVERSE,
    BreachEvent,
    OrderIntent,
    check_mandate,
    instrument_asset_class,
    last_price_usd,
)
from src.live.extractors import get_extractor
from src.live.halt import halt_flag_set
from src.live.mandate.model import MANDATE_SCHEMA_VERSION, Mandate
from src.live.mandate.store import load_mandate
from src.live.daily_count import (
    DailyOrderLockUnavailable,
    daily_order_lock,
    increment_daily_count,
    read_daily_count,
)
from src.tools.mcp import MCPRemoteTool, MCPRemoteToolSpec, MCPServerAdapter

logger = logging.getLogger(__name__)

#: Frozen marker key the api_server SSE relay reads off the returned tool_result
#: to emit a ``live.action`` event without touching the agent loop.
LIVE_ACTION_RESULT_KEY = "live_action"

#: Fallback READ tools the gate uses to snapshot positions/balance and live
#: quotes. Connector mappings in ``src.trading`` override these when available.
_POSITIONS_TOOLS = ("get_positions",)
_BALANCE_TOOLS = ("get_account",)
_QUOTE_TOOLS = ("get_quotes",)

_DECISION_ALLOW = "allow"
_DECISION_DENY = "deny"
_DECISION_PAUSE = "pause_for_reauth"

#: Environment variable controlling advisory review activation.
#: Truthy values (case-insensitive): ``"1"``, ``"true"``, ``"yes"``.
#: Default: off (advisory layer is purely observational and opt-in).
_ADVISORY_ENABLED_ENV = "VIBE_TRADING_ENABLE_ADVISORY"
_ADVISORY_TRUTHY = frozenset({"1", "true", "yes"})


class LiveOrderGuardTool(MCPRemoteTool):
    """Mandate-enforcing wrapper for a broker's order-placing remote tool."""

    repeatable = False
    is_readonly = False

    def __init__(
        self,
        adapter: MCPServerAdapter,
        spec: MCPRemoteToolSpec,
        *,
        broker: str | None = None,
        session_id: str = "",
    ) -> None:
        """Initialize the gate wrapper.

        Args:
            adapter: Adapter used to invoke the remote server (read + write).
            spec: Resolved local metadata for the order-placing remote tool.
            broker: Broker key for mandate/counter/halt lookups. Defaults to the
                spec's ``server_name`` (the channel is keyed by broker, e.g.
                ``"robinhood"``).
            session_id: Originating session id, stamped onto audit events.
        """
        super().__init__(adapter, spec)
        self.broker = (broker or spec.server_name or "").strip().lower()
        self.session_id = session_id

    @property
    def remote_name(self) -> str:
        """The broker's un-prefixed remote tool name (e.g. ``place_order``)."""
        return self._spec.remote_name

    def execute(self, **kwargs: Any) -> str:
        """Run the pre-trade gate, then ALLOW / DENY / PAUSE the order.

        Args:
            **kwargs: Order-tool arguments from the agent loop.

        Returns:
            JSON string: on ALLOW, the forwarded broker result; otherwise a
            structured refusal envelope (``status: "blocked"``) carrying the
            decision and, for quantitative breaches, the :class:`BreachEvent`.
        """
        mandate = load_mandate(self.broker)
        if mandate is None or mandate.schema_version != MANDATE_SCHEMA_VERSION:
            return self._deny(
                reason="no valid mandate on file",
                checked=["mandate"],
                mandate=mandate,
            )

        if self._is_expired(mandate):
            return self._deny(
                reason="mandate expired — re-authorize",
                checked=["mandate", "expiry"],
                mandate=mandate,
                reauth=True,
            )

        if halt_flag_set(self.broker):
            return self._deny(
                reason="live trading halted",
                checked=["mandate", "expiry", "halt_flag"],
                mandate=mandate,
            )

        extractor = get_extractor(self.broker)
        intent = extractor(self.remote_name, kwargs) if extractor is not None else None
        if intent is None:
            return self._deny(
                reason="order intent could not be parsed",
                checked=["mandate", "expiry", "halt_flag", "intent"],
                mandate=mandate,
            )

        # Reconcile any quantity into a single authoritative notional BEFORE the
        # mandate checks so a {notional_usd, quantity} pair can't bypass the
        # notional cap (H3) and a quantity-only order stays cap-enforceable (H4).
        intent = self._normalize_intent_notional(intent)
        if intent is None:
            return self._deny(
                reason="quantity order notional could not be priced (fail-closed)",
                checked=["mandate", "expiry", "halt_flag", "intent", "quote"],
                mandate=mandate,
            )

        positions = self._read_first(self._read_tools("positions", _POSITIONS_TOOLS))
        balance = self._read_first(self._read_tools("account", _BALANCE_TOOLS))

        try:
            with daily_order_lock(self.broker):
                daily_count = self._read_daily_count()
                breach = check_mandate(
                    mandate,
                    intent,
                    positions,
                    balance,
                    broker=self.broker,
                    remote_tool=self.remote_name,
                    daily_count=daily_count,
                )

                if breach is None:
                    return self._allow(
                        mandate=mandate, intent=intent, kwargs=kwargs,
                        positions=positions, balance=balance,
                    )
        except DailyOrderLockUnavailable as exc:
            return self._deny(
                reason=str(exc),
                checked=["mandate", "expiry", "halt_flag", "daily_order_lock"],
                mandate=mandate,
            )

        if breach.kind in (BREACH_KIND_UNIVERSE, BREACH_KIND_INSTRUMENT):
            return self._deny_breach(breach, mandate=mandate, intent=intent, reauth=False)
        return self._deny_breach(breach, mandate=mandate, intent=intent, reauth=True)

    # -- intent normalization (quantity → notional) -------------------------

    def _normalize_intent_notional(self, intent: OrderIntent) -> OrderIntent | None:
        """Stamp a single authoritative ``notional_usd`` onto the intent.

        Closes two bypasses (SPEC §4):

        * **H3** — an order carrying BOTH ``notional_usd`` and ``quantity`` is
          enforced on the LARGER of (explicit notional, ``quantity`` × live
          price), so a small notional can't smuggle a huge quantity past the
          notional / exposure / leverage math.
        * **H4** — a quantity-only order derives its notional from a live quote
          so the notional cap stays enforceable.

        Fail-closed: when ``quantity`` is present but NO quote can be obtained
        from the broker quote tool or any data loader, the order is DENIED
        (returns ``None``) rather than waved through. When no ``quantity`` is
        present the intent passes through unchanged (its explicit notional, if
        any, is validated downstream).

        Args:
            intent: The extractor's normalized intent.

        Returns:
            A new :class:`OrderIntent` with ``notional_usd`` set to the enforced
            value, or ``None`` when a quantity order cannot be priced.
        """
        if intent.quantity is None:
            return intent

        price = self._quote_price(intent)
        if price is None:
            return None
        implied = intent.quantity * price
        if implied != implied or implied <= 0:  # NaN / non-positive → fail-closed
            return None

        explicit = intent.notional_usd if intent.notional_usd is not None else 0.0
        enforced = max(float(explicit), implied)
        return OrderIntent(
            symbol=intent.symbol,
            side=intent.side,
            notional_usd=enforced,
            quantity=intent.quantity,
            instrument_type=intent.instrument_type,
        )

    def _quote_price(self, intent: OrderIntent) -> float | None:
        """Return a live USD price for the intent's symbol, fail-closed.

        Prefers the broker's mapped READ quote tool so the price is the broker's
        own; falls back to Vibe-Trading's data loaders
        (:func:`src.live.enforcement.last_price_usd`, standard auto-fallback)
        when the broker quote is unavailable. Returns ``None`` when no source
        yields a usable price.

        Args:
            intent: The order intent whose symbol is priced.

        Returns:
            A positive USD price, or ``None`` (→ fail-closed DENY upstream).
        """
        broker_price = self._broker_quote_price(intent.symbol)
        if broker_price is not None:
            return broker_price
        asset_class = instrument_asset_class(intent.instrument_type)
        if asset_class is None:
            return None
        try:
            return last_price_usd(intent.symbol, asset_class)
        except Exception as exc:  # loader chain failure → fail-closed
            logger.warning("loader quote failed for %s: %s", intent.symbol, exc)
            return None

    def _broker_quote_price(self, symbol: str) -> float | None:
        """Read a USD price for ``symbol`` from the broker's quote tool.

        Calls the ungated read path (never the guard) for the mapped quote tool
        with the symbol argument and parses a price from the common envelope shapes.
        Returns ``None`` on any error envelope, missing field, or unparseable
        value — the caller then falls back to the data loaders.

        Args:
            symbol: Normalized upper-case symbol.

        Returns:
            A positive USD price, or ``None``.
        """
        for remote in self._read_tools("quote", _QUOTE_TOOLS):
            try:
                result = self._adapter.call_tool(
                    remote, {"symbol": symbol}, local_name=remote
                )
            except Exception as exc:
                logger.warning("broker quote tool %s failed: %s", remote, exc)
                continue
            if isinstance(result, dict) and result.get("status") == "error":
                continue
            price = _parse_quote_price(result, symbol)
            if price is not None:
                return price
        return None

    # -- decision helpers ---------------------------------------------------

    def _allow(
        self,
        *,
        mandate: Mandate,
        intent: OrderIntent,
        kwargs: dict,
        positions: object = None,
        balance: object = None,
    ) -> str:
        """Forward the order unchanged; consume a count + audit only on success.

        ``MCPServerAdapter.call_tool`` does NOT raise on broker/network failure —
        it returns a ``{"status": "error", ...}`` envelope. So the gate inspects
        the forwarded payload (H2):

        * **non-error** → increment the daily counter and audit
          ``kind="order_placed"`` / ``outcome="accepted"``.
        * **error envelope** → audit ``kind="order_rejected"`` /
          ``outcome="error"`` and do NOT consume a daily count (a failed forward
          never placed an order).

        Either way the returned tool_result carries the redacted audit record
        under :data:`LIVE_ACTION_RESULT_KEY` so the api_server SSE relay can emit
        a ``live.action`` event without touching the agent loop (H5).
        """
        advisory = self._advisory_review(intent, positions, balance, mandate)
        forwarded = super().execute(**kwargs)
        broker_response = self._safe_json(forwarded)
        is_error = self._is_error_envelope(broker_response)

        checked = [
            "mandate", "expiry", "halt_flag", "intent",
            "exclude_symbols", "allowed_instruments", "asset_classes",
            "max_order_notional_usd", "max_total_exposure_usd",
            "max_leverage", "max_trades_per_day", "account_funding_usd",
            "universe_floors",
        ]
        if advisory is not None:
            checked.append("advisory")
        gate_decision: dict[str, Any] = {
            "allowed": True,
            "decision": _DECISION_ALLOW,
            "checked_limits": checked,
            "advisory": advisory,
        }
        if is_error:
            record = self._audit(
                kind="order_rejected",
                outcome="error",
                mandate=mandate,
                intent=intent,
                broker_request=dict(kwargs),
                broker_response=broker_response,
                gate_decision=gate_decision,
                error=self._error_message(broker_response),
            )
        else:
            # Only a confirmed ALLOW + non-error forward consumes a daily count.
            self._increment_daily_count()
            record = self._audit(
                kind="order_placed",
                outcome="accepted",
                mandate=mandate,
                intent=intent,
                broker_request=dict(kwargs),
                broker_response=broker_response,
                gate_decision=gate_decision,
            )
        return self._embed_live_action(forwarded, record)

    # -- advisory review (observational, never blocks) ----------------------

    def _advisory_review(
        self,
        intent: OrderIntent,
        positions: object,
        balance: object,
        mandate: Mandate,
    ) -> dict | None:
        """Run advisory providers if enabled; return verdict dict or None.

        Returns None when advisory is disabled or no providers are configured.
        Returns a dict with ``verdict``, ``concerns``, ``results`` keys otherwise.
        Never raises — all exceptions are caught and converted to
        REVIEW_UNAVAILABLE.
        """
        if not get_env_config().agent_tuning.vibe_trading_enable_advisory:
            return None

        providers = get_advisory_providers()
        if not providers:
            logger.info(
                "advisory enabled but no providers registered — skipping review"
            )
            return None

        try:
            from src.live.enforcement import (
                account_balance_market_value,
                coerce_position_rows,
                positions_market_value,
            )

            equity = account_balance_market_value(balance) or 0.0
            exposure = positions_market_value(positions) or 0.0
            funding_usd = mandate.hard_caps.account_funding_usd

            if equity > 0 and funding_usd > 0:
                utilization = max(0.0, 1.0 - equity / funding_usd)
            else:
                utilization = 0.0

            pos_rows = coerce_position_rows(positions)
            open_count = len(pos_rows) if pos_rows is not None else 0

            context = AdvisoryContext(
                symbol=intent.symbol,
                side=intent.side,
                notional_usd=intent.notional_usd or 0.0,
                account_equity=equity,
                utilization_ratio=utilization,
                open_position_count=open_count,
                total_exposure_usd=exposure,
                funding_usd=funding_usd,
            )

            orchestrator = AdvisoryOrchestrator(providers)
            aggregated = orchestrator.review(context)
            return {
                "verdict": aggregated.verdict.value,
                "concerns": list(aggregated.all_concerns),
                "results": [
                    {
                        "verdict": r.verdict.value,
                        "summary": r.summary,
                        "concerns": list(r.concerns),
                        "provider": r.provider,
                        "confidence": r.confidence,
                    }
                    for r in aggregated.results
                ],
            }
        except Exception as exc:
            logger.warning("advisory review failed: %s", exc, exc_info=True)
            return {
                "verdict": Verdict.REVIEW_UNAVAILABLE.value,
                "concerns": [],
                "error": type(exc).__name__,
            }

    def _deny(
        self,
        *,
        reason: str,
        checked: list[str],
        mandate: Mandate | None,
        reauth: bool = False,
    ) -> str:
        """Audit + return a refusal envelope for a pre-intent / structural DENY."""
        record = self._audit(
            kind="order_rejected",
            outcome="blocked",
            mandate=mandate,
            intent=None,
            broker_request=None,
            broker_response=None,
            gate_decision={"allowed": False, "decision": _DECISION_DENY, "checked_limits": checked},
            error=reason,
        )
        return self._refusal(
            decision=_DECISION_DENY, reason=reason, reauth=reauth, record=record
        )

    def _deny_breach(
        self,
        breach: BreachEvent,
        *,
        mandate: Mandate,
        intent: OrderIntent,
        reauth: bool,
    ) -> str:
        """Audit + return a refusal for a ``check_mandate`` breach.

        Structural breaches (``reauth=False``) DENY outright; quantitative
        breaches (``reauth=True``) PAUSE for re-authorization and surface the
        full :class:`BreachEvent` so the consent layer can render a widen-prompt.
        """
        decision = _DECISION_PAUSE if reauth else _DECISION_DENY
        record = self._audit(
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
        return self._refusal(
            decision=decision,
            reason=breach.detail or f"order breaches {breach.limit}",
            reauth=reauth,
            breach=breach,
            record=record,
        )

    def _refusal(
        self,
        *,
        decision: str,
        reason: str,
        reauth: bool,
        breach: BreachEvent | None = None,
        record: dict | None = None,
    ) -> str:
        """Build the structured refusal envelope returned to the agent loop."""
        payload: dict[str, Any] = {
            "status": "blocked",
            "decision": decision,
            "reason": reason,
            "broker": self.broker,
            "remote_tool": self.remote_name,
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
                "remote_tool": breach.remote_tool,
                "created_at": breach.created_at,
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
        return json.dumps(payload, ensure_ascii=False)

    # -- read snapshot ------------------------------------------------------

    def _read_first(self, candidates: tuple[str, ...]) -> object:
        """Read the first responsive broker read tool, fail-closed.

        Routes through the plain ``MCPServerAdapter.call_tool`` path (NOT the
        guard) so reads are never gated. Returns ``None`` on any error envelope
        or exception so the downstream check fail-closes.

        Args:
            candidates: Ordered remote read-tool names to try.

        Returns:
            The first successful tool result payload, or ``None``.
        """
        for remote in candidates:
            try:
                result = self._adapter.call_tool(remote, {}, local_name=remote)
            except Exception as exc:
                logger.warning("live read tool %s failed: %s", remote, exc)
                continue
            if isinstance(result, dict) and result.get("status") == "error":
                continue
            return result
        return None

    def _read_tools(self, operation: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
        """Return connector-specific read tools, falling back to legacy names."""
        try:
            from src.trading.service import runner_tool_name

            remote = runner_tool_name(self.broker, operation)
        except Exception:  # pragma: no cover - guard must fail closed later
            remote = None
        return (remote,) if remote else fallback

    # -- daily counter ------------------------------------------------------

    def _read_daily_count(self) -> int:
        """Return today's order count via the shared per-broker counter."""
        return read_daily_count(self.broker)

    def _increment_daily_count(self) -> None:
        """Increment today's order count via the shared per-broker counter."""
        increment_daily_count(self.broker)

    # -- audit + misc -------------------------------------------------------

    def _audit(
        self,
        *,
        kind: str,
        outcome: str,
        mandate: Mandate | None,
        intent: OrderIntent | None,
        broker_request: dict | None,
        broker_response: dict | None,
        gate_decision: dict,
        error: str | None = None,
    ) -> dict | None:
        """Write one live-action audit event and return the redacted record.

        The returned record (identical to what was written to the ledger) is
        embedded under :data:`LIVE_ACTION_RESULT_KEY` in the tool_result so the
        SSE relay can emit a ``live.action`` event. Auditing must never block a
        decision, so a write failure logs and returns ``None``.

        Returns:
            The redacted audit record, or ``None`` when the write failed.
        """
        consent = mandate.consent if mandate is not None else None
        try:
            event = LiveActionEvent(
                kind=kind,  # type: ignore[arg-type]
                session_id=self.session_id,
                outcome=outcome,  # type: ignore[arg-type]
                server=self.broker,
                remote_tool=self.remote_name,
                intent_normalized=_describe_intent(intent),
                mandate_snapshot_ref=consent.consent_token_sha256 if consent else None,
                consent_record_ref=consent.account_ref if consent else None,
                broker_request=broker_request,
                broker_response=broker_response,
                gate_decision=gate_decision,
                error=error,
            )
            return _record_live_action(event)
        except Exception as exc:  # auditing must never block a decision
            logger.warning("live-action audit write failed (%s): %s", kind, exc)
            return None

    def _is_expired(self, mandate: Mandate) -> bool:
        """Return whether the mandate is past its ``expires_at`` (fail-closed).

        An unparseable ``expires_at`` is treated as expired (fail-closed): a
        live mandate with a malformed expiry must not keep trading.
        """
        raw = mandate.consent.expires_at
        try:
            expires = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires

    @staticmethod
    def _safe_json(text: str) -> dict | None:
        """Best-effort parse of the forwarded broker result for the audit record."""
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return {"raw": text}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}

    @staticmethod
    def _is_error_envelope(broker_response: dict | None) -> bool:
        """Whether the forwarded result is an error envelope (H2).

        ``MCPServerAdapter.call_tool`` returns ``{"status": "error", ...}`` on
        broker/network failure without raising. Treats a missing/unparseable
        response as an error too (fail-closed: no order was confirmed placed).
        """
        if not isinstance(broker_response, dict):
            return True
        return str(broker_response.get("status", "")).lower() == "error"

    @staticmethod
    def _error_message(broker_response: dict | None) -> str:
        """Extract a human-readable error from an error envelope."""
        if isinstance(broker_response, dict):
            for key in ("error", "message", "detail"):
                value = broker_response.get(key)
                if isinstance(value, str) and value:
                    return value
        return "broker forward returned an error"

    @staticmethod
    def _embed_live_action(forwarded: str, record: dict | None) -> str:
        """Embed the redacted audit record under the frozen live-action key (H5).

        The forwarded broker result is a JSON object string; the record is added
        as a top-level ``live_action`` key so the api_server SSE relay can emit a
        ``live.action`` event without touching ``loop.py``. If the result isn't a
        JSON object or there is no record, the forwarded string is returned
        unchanged.
        """
        if record is None:
            return forwarded
        try:
            payload = json.loads(forwarded)
        except (TypeError, ValueError):
            return forwarded
        if not isinstance(payload, dict):
            return forwarded
        payload[LIVE_ACTION_RESULT_KEY] = record
        return json.dumps(payload, ensure_ascii=False)


def _record_live_action(event: LiveActionEvent) -> dict | None:
    """Call ``write_live_action`` with the keyword contract, fall back positional.

    The frozen contract is
    ``write_live_action(event, *, event_callback=None, trace_writer=None)`` (G2
    is updating the signature). If only the positional form exists today, the
    keyword call raises ``TypeError`` and we retry positionally so this parcel
    works against either signature.
    """
    try:
        return write_live_action(event, event_callback=None, trace_writer=None)
    except TypeError:
        return write_live_action(event)


def _parse_quote_price(result: object, symbol: str) -> float | None:
    """Extract a positive USD price from a broker quote-tool payload, fail-closed.

    Accepts the common envelope shapes a ``get_quotes`` read tool may return:

    * a flat dict with a price field (``price`` / ``last_price`` / ``last`` /
      ``mark_price`` / ``ask`` / ``bid``);
    * a dict keyed by symbol → quote dict;
    * a dict with a ``quotes`` / ``data`` list of quote dicts (matched on
      ``symbol`` / ``ticker`` when present, else the sole entry).

    Unknown extra keys are ignored, never guessed. Returns ``None`` on anything
    unparseable so the caller falls back to the data loaders.

    Args:
        result: The broker quote tool's normalized payload.
        symbol: The normalized upper-case symbol requested.

    Returns:
        A positive USD price, or ``None``.
    """
    if not isinstance(result, dict):
        return None

    direct = _price_from_quote_dict(result)
    if direct is not None:
        return direct

    keyed = result.get(symbol)
    if isinstance(keyed, dict):
        price = _price_from_quote_dict(keyed)
        if price is not None:
            return price

    for container_key in ("quotes", "data", "results"):
        rows = result.get(container_key)
        if not isinstance(rows, list):
            continue
        match = _match_quote_row(rows, symbol)
        if match is not None:
            price = _price_from_quote_dict(match)
            if price is not None:
                return price
    return None


def _match_quote_row(rows: list, symbol: str) -> dict | None:
    """Pick the quote row for ``symbol`` from a list, or the sole entry."""
    dict_rows = [row for row in rows if isinstance(row, dict)]
    for row in dict_rows:
        for key in ("symbol", "ticker", "instrument"):
            value = row.get(key)
            if isinstance(value, str) and value.strip().upper() == symbol:
                return row
    return dict_rows[0] if len(dict_rows) == 1 else None


def _price_from_quote_dict(quote: dict) -> float | None:
    """Return the first parseable positive price from a quote dict, else None."""
    for key in ("price", "last_price", "last", "mark_price", "close", "ask", "bid"):
        if key in quote:
            try:
                value = float(quote[key])
            except (TypeError, ValueError):
                continue
            if value == value and value > 0:  # finite + positive
                return value
    return None


def _describe_intent(intent: OrderIntent | None) -> str | None:
    """Render a human-readable normalized intent for the audit record."""
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
