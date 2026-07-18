"""Live-trading channel HTTP routes (consent commit, kill switch, C2 status, runner control).

Mounted by ``agent/api_server.py`` via ``register_live_routes(app)``.

These are the privileged SURFACE actions of the live-trading channel
(live-trading SPEC, Consent §1/§3/§4). None is an agent tool:

- ``POST /mandate/commit``  — the single mandate writer (commit_mandate)
- ``POST /live/halt``       — trip the kill switch (P5 trip_halt)
- ``POST /live/resume``     — clear the kill switch (P5 clear_halt)
- ``GET /live/status``      — per-broker auth + mandate + runner + halt state (C2)
- ``POST /live/authorize``  — discover-only OAuth bootstrap on-ramp (C2)
- ``POST /live/runner/start`` — start the persistent §7.5 runner
- ``POST /live/runner/stop``  — stop the persistent §7.5 runner

Each best-effort relays a ``mandate.committed`` / ``live.halted`` / ``live.action``
event through the EXISTING session EventBus, so the frontend's already-wired
``/sessions/{id}/events`` SSE stream reflects the state change. No new bus.
"""

from __future__ import annotations

import asyncio
import logging
import sys as _sys
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models (live-exclusive; defined locally, monkeypatch-safe via re-export)
# ============================================================================


class CommitMandateRequest(BaseModel):
    """Surface-originated mandate commit (Consent §1 / §3).

    This is the ONLY write path that activates a live-trading mandate. It is a
    privileged HTTP action the user surface sends on an explicit click/keypress
    — NOT a tool the agent model can call. ``consent_ack`` MUST be ``true``.
    """

    broker: str = Field(..., min_length=1, max_length=64)
    proposal_id: str = Field(..., pattern=r"^mp_[0-9a-f]{32}$")
    selected_ordinal: int = Field(..., ge=1, le=10)
    adjustments: Optional[Dict[str, Any]] = None
    consent_ack: bool = Field(..., description="Explicit affirmative; must be true")
    session_id: Optional[str] = None
    account_ref: str = Field("", max_length=128)
    lifetime_days: int = Field(30, ge=1, le=365)


class LiveHaltRequest(BaseModel):
    """Trip or clear the live kill switch (Consent §4).

    Tripping/clearing is a privileged surface action, never an agent tool. When
    ``broker`` is omitted the GLOBAL switch is used (halts every broker).
    """

    broker: Optional[str] = Field(None, max_length=64)
    reason: str = Field("user requested halt", max_length=500)
    session_id: Optional[str] = None


class LiveAuthorizeRequest(BaseModel):
    """Kick off (or describe) the OAuth bootstrap for a live broker (C2).

    Vibe-Trading never holds funds and never operates a venue, so the OAuth
    bootstrap runs through the broker's own user-authorized device flow on the
    client (CLI / desktop MCP), not a server-side redirect. This endpoint is the
    web on-ramp: it tells a Web UI user exactly how to discover/start the flow.
    """

    broker: str = Field(..., min_length=1, max_length=64)


class LiveRunnerControlRequest(BaseModel):
    """Start or stop the persistent live runner for one broker (SPEC §7.5).

    The runner wakes on schedule/market events and trades autonomously inside a
    committed mandate. Starting it is a privileged surface action, never an
    agent tool. A committed, unexpired mandate must already exist.
    """

    broker: str = Field(..., min_length=1, max_length=64)
    session_id: Optional[str] = None


class BrokerAuthState(BaseModel):
    """Per-broker authorization snapshot for ``GET /live/status``."""

    broker: str
    oauth_token_present: bool = Field(..., description="Whether an OAuth token cache exists")
    is_live_broker: bool = Field(..., description="Whether this key is a recognized live broker")
    transport: Optional[str] = Field(None, description="Transport type (broker_sdk, remote_mcp, local_tws)")
    connection_state: Optional[str] = Field(None, description="Broker_sdk connection state (connected, not_configured, error)")
    profile_id: Optional[str] = Field(None, description="Verified broker_sdk profile id")
    configured: Optional[bool] = Field(None, description="Whether the selected SDK profile is configured")
    credential_source: Optional[str] = Field(None, description="Credential source label; never credential material")
    sdk_installed: Optional[bool] = Field(None, description="Whether the connector SDK is installed")
    environment_identity: Optional[str] = Field(None, description="How the account environment was identified")
    capabilities: Optional[List[str]] = Field(None, description="Capabilities declared by the verified profile")
    readonly: Optional[bool] = Field(None, description="Whether the verified profile is structurally read-only")
    last_checked_at: Optional[str] = Field(None, description="Timestamp of the latest connector verification")
    error_code: Optional[str] = Field(None, description="Stable redaction-safe connector error code")


class MandateLimits(BaseModel):
    """Flattened active-mandate limits surfaced to the UI (Mandate layer a/b)."""

    max_order_notional_usd: float
    max_total_exposure_usd: float
    max_leverage: float
    max_trades_per_day: int
    allowed_instruments: List[str]
    account_funding_usd: float


class ActiveMandateState(BaseModel):
    """Active-mandate snapshot with the expiry countdown (SPEC §9 dec. 2)."""

    broker: str
    account_ref: str
    created_at: str
    expires_at: str
    expires_in_seconds: Optional[int] = Field(
        None, description="Seconds until expiry; negative when already expired"
    )
    expired: bool
    limits: MandateLimits


class RunnerLivenessState(BaseModel):
    """Runner liveness snapshot via the §7.5 liveness contract."""

    broker: str
    alive: bool
    last_tick: Optional[float] = Field(None, description="Unix epoch of last heartbeat tick")
    last_tick_age_seconds: Optional[float] = None


class LiveBrokerStatus(BaseModel):
    """Combined live-channel status for a single broker."""

    auth: BrokerAuthState
    mandate: Optional[ActiveMandateState] = None
    runner: RunnerLivenessState
    halted: bool = Field(..., description="Per-broker OR global kill switch is tripped")


class LiveStatusResponse(BaseModel):
    """Top-level live-channel status (C2)."""

    global_halted: bool = Field(..., description="Whether the GLOBAL kill switch is tripped")
    brokers: List[LiveBrokerStatus]


# ============================================================================
# Runner state (module-level; monkeypatched by tests via api_server re-export)
# ============================================================================

_runner_tasks: Dict[str, "asyncio.Task[Any]"] = {}
_runner_factory: Optional[Any] = None


# ============================================================================
# Connector verify cache (bounded 15s, credential-free, fake-clock testable)
# ============================================================================

_CACHE_TTL_SECONDS = 15.0


class _ConnectorVerifyCache:
    """A bounded, credential-free cache for connector verify results.

    Each entry stores only the status-level envelope returned by
    ``service.check_connection`` — stripped of any ``config`` sub-dict that
    might contain secret material.  The cache is keyed by profile id and
    expires after ``_CACHE_TTL_SECONDS``.  An explicit ``force=True`` bypass
    always hits the service.

    The ``_clock`` attribute is a callable returning ``time.time()`` and is
    monkeypatchable by tests for deterministic TTL assertions.
    """

    def __init__(self, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._store: Dict[str, Dict[str, Any]] = {}
        self._clock = time.time

    def get(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Return a cached entry if fresh, else ``None``."""
        entry = self._store.get(profile_id)
        if entry is None:
            return None
        age = self._clock() - entry["_cached_at"]
        if age >= self._ttl:
            self._store.pop(profile_id, None)
            return None
        return dict(entry)

    def put(self, profile_id: str, payload: Dict[str, Any]) -> None:
        """Store a sanitized copy (no ``config`` key, no secrets)."""
        sanitized = {k: v for k, v in payload.items() if k != "config"}
        sanitized["_cached_at"] = self._clock()
        self._store[profile_id] = sanitized

    def clear(self) -> None:
        """Drop all entries (used in test setup)."""
        self._store.clear()


_connector_verify_cache = _ConnectorVerifyCache()


_CREDENTIAL_SOURCES = frozenset({"environment", "runtime_file"})
_ENVIRONMENT_IDENTITIES = frozenset(
    {
        "config_declared",
        "config_declared_live",
        "config-declared",
        "header_flag+uid_pin",
        "host_separated",
        "read_only_no_runtime_discriminator",
        "simulated_locally",
        "trd_env_acc_list",
    }
)
_CONNECTION_STATES = frozenset({"connected", "error", "not_configured", "ready"})
_ERROR_CODES = frozenset(
    {
        "authentication_failed",
        "broker_error",
        "credentials_conflict",
        "credentials_missing",
        "credentials_partial",
        "network_unreachable",
        "sdk_missing",
    }
)


def _closed_vocabulary(value: Any, allowed: frozenset[str]) -> Optional[str]:
    """Return a known diagnostic label, never arbitrary report-controlled text."""
    return value if type(value) is str and value in allowed else None


def _canonical_utc_timestamp(value: Any) -> Optional[str]:
    """Validate an ISO-8601 timestamp and emit one canonical UTC representation."""
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, ValueError):
        return None


def _check_connector_status(profile_id: str, force: bool = False) -> Dict[str, Any]:
    """Resolve a connector profile and return its verify envelope.

    Uses the bounded cache when ``force`` is ``False`` and the entry is fresh.
    Known broker/SDK exceptions are normalised into a stable envelope; raw
    exception objects and credential-bearing strings never escape.
    """
    if not force:
        cached = _connector_verify_cache.get(profile_id)
        if cached is not None:
            return cached

    from src.trading.service import check_connection

    try:
        report = check_connection(profile_id)
    except ValueError:
        report = {
            "status": "error",
            "configured": False,
            "connection_state": "error",
            "error": f"unknown connector profile: {profile_id}",
            "connector": None,
            "transport": None,
            "profile_id": profile_id,
        }
    except Exception as exc:  # noqa: BLE001 - verify must never raise
        report = {
            "status": "error",
            "configured": False,
            "connection_state": "error",
            "error": f"unexpected error: {type(exc).__name__}",
            "connector": None,
            "transport": None,
            "profile_id": profile_id,
        }

    # Sanitize: strip any ``config`` sub-dict that may hold secrets
    sanitized = {k: v for k, v in report.items() if k != "config"}

    _connector_verify_cache.put(profile_id, sanitized)
    return sanitized


# ============================================================================
# Exception (live-exclusive)
# ============================================================================


class LiveRunnerUnavailable(RuntimeError):
    """Raised when a live runner cannot be wired (broker not configured/authorized).

    Distinct from a programming error so the start endpoint can map it to a 503
    rather than a 500: the runtime is fine, the broker channel just isn't ready.
    """


# ============================================================================
# Host resolution — shared deps and monkeypatched symbols
# ============================================================================


def _host() -> Any:
    """Return the host ``api_server`` module for shared deps and monkeypatched symbols."""
    return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")


# ============================================================================
# Helper functions
# ============================================================================


def _emit_live_event(session_id: Optional[str], event_type: str, data: Dict[str, Any]) -> None:
    """Best-effort relay of a live-channel event through the existing bus.

    The event flows out the existing ``/sessions/{session_id}/events`` SSE
    stream. Notifications never gate autonomy (SPEC Consent §5): a relay failure
    or a missing session is swallowed — the state change already happened on disk.
    """
    if not session_id:
        return
    try:
        svc = _host()._get_session_service()
        if svc and svc.get_session(session_id):
            svc.event_bus.emit(session_id, event_type, data)
    except Exception:  # pragma: no cover - relay is non-blocking by contract
        logger.debug("live event relay failed for %s/%s", session_id, event_type, exc_info=True)


def _live_broker_adapter(broker: str) -> Any:
    """Build an ``MCPServerAdapter`` for a live broker from the user-side config.

    Raises:
        LiveRunnerUnavailable: When no MCP server is configured for the broker.
    """
    from src.config.loader import load_agent_config
    from src.tools.mcp import MCPServerAdapter

    try:
        from src.config.schema import is_live_broker_entry
    except Exception:  # pragma: no cover - older schema without URL detection
        is_live_broker_entry = None  # type: ignore[assignment]

    cfg = load_agent_config()
    servers = getattr(cfg, "mcp_servers", {}) or {}
    for name, server_cfg in servers.items():
        is_match = name == broker
        if not is_match and is_live_broker_entry is not None and broker == "robinhood":
            try:
                is_match = is_live_broker_entry(name, server_cfg)
            except Exception:  # pragma: no cover
                is_match = False
        if is_match:
            return MCPServerAdapter(name, server_cfg)
    raise LiveRunnerUnavailable(f"no MCP server configured for live broker {broker!r}")


def _fetch_broker_ceilings(broker: str) -> Optional[Dict[str, Any]]:
    """Best-effort fetch of broker-side account ceilings for the commit re-check.

    Returns ``None`` on any failure so the caller falls back to the proposal's
    own snapshot — a commit is never blocked on a broker read.
    """
    h = _host()
    try:
        adapter = h._live_broker_adapter(broker)
    except LiveRunnerUnavailable:
        return None
    try:
        from src.trading.service import runner_tool_name

        account_tool = runner_tool_name(broker, "account") or "get_account"
        result = adapter.call_tool(account_tool, {})
    except Exception:  # pragma: no cover - status/commit must never raise here
        logger.debug("broker ceiling fetch failed for %s", broker, exc_info=True)
        return None
    if not isinstance(result, dict) or result.get("status") == "error":
        return None
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    funding: Optional[float] = None
    for key in ("account_funding_usd", "buying_power", "cash", "portfolio_value", "equity"):
        raw = payload.get(key) if isinstance(payload, dict) else None
        try:
            if raw is not None:
                funding = float(raw)
                break
        except (TypeError, ValueError):
            continue
    if funding is None or funding <= 0:
        return None
    return {
        "account_funding_usd": funding,
        "max_order_notional_usd": funding,
        "max_total_exposure_usd": funding,
    }


def _known_live_brokers() -> List[str]:
    """Return the recognized live-broker keys (SPEC §7.2) — OAuth/mandate path only."""
    from src.config.schema import LIVE_BROKER_SERVER_KEYS

    return sorted(LIVE_BROKER_SERVER_KEYS)


def _live_broker_sdk_connectors() -> List[str]:
    """Return the recognized broker_sdk connector keys from the profile registry.

    These are direct-SDK connectors (e.g. Longbridge) that appear in
    ``/live/status`` but are NOT OAuth/mandate live brokers.  They are
    discovered from the profile registry rather than a hard-coded list.
    """
    from src.trading.profiles import list_profiles

    seen: set[str] = set()
    result: list[str] = []
    for profile in list_profiles():
        if profile.environment == "live" and profile.transport == "broker_sdk":
            if profile.connector not in seen:
                seen.add(profile.connector)
                result.append(profile.connector)
    return sorted(result)


def _oauth_token_present(broker: str) -> bool:
    """Return whether an OAuth token cache exists for a broker (C2 auth state)."""
    try:
        from src.live.paths import broker_dir

        oauth_dir = broker_dir(broker) / "oauth"
        return oauth_dir.is_dir() and any(oauth_dir.iterdir())
    except Exception:  # pragma: no cover - status must never raise
        logger.debug("oauth presence check failed for %s", broker, exc_info=True)
        return False


def _active_mandate_state(broker: str) -> Optional[ActiveMandateState]:
    """Build the active-mandate snapshot for a broker, or ``None`` when absent."""
    from src.live.mandate.store import load_mandate

    mandate = load_mandate(broker)
    if mandate is None:
        return None

    consent = mandate.consent
    caps = mandate.hard_caps
    expires_in: Optional[int] = None
    expired = False
    try:
        expires_dt = datetime.fromisoformat(consent.expires_at.replace("Z", "+00:00"))
        from datetime import timezone

        now = datetime.now(timezone.utc)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        delta = expires_dt - now
        expires_in = int(delta.total_seconds())
        expired = expires_in <= 0
    except (ValueError, AttributeError):
        logger.debug("could not parse expires_at for %s mandate", broker, exc_info=True)

    return ActiveMandateState(
        broker=broker,
        account_ref=consent.account_ref,
        created_at=consent.created_at,
        expires_at=consent.expires_at,
        expires_in_seconds=expires_in,
        expired=expired,
        limits=MandateLimits(
            max_order_notional_usd=caps.max_order_notional_usd,
            max_total_exposure_usd=caps.max_total_exposure_usd,
            max_leverage=caps.max_leverage,
            max_trades_per_day=caps.max_trades_per_day,
            allowed_instruments=[str(getattr(i, "value", i)) for i in caps.allowed_instruments],
            account_funding_usd=caps.account_funding_usd,
        ),
    )


def _runner_liveness_state(broker: str) -> RunnerLivenessState:
    """Build the runner-liveness snapshot for a broker (SPEC §7.5 contract)."""
    alive = False
    tick: Optional[float] = None
    age: Optional[float] = None
    try:
        from src.live.runtime import liveness

        alive = bool(liveness.is_runner_alive(broker))
        raw_tick = liveness.last_tick(broker)
        if raw_tick is not None:
            tick = float(raw_tick)
            age = max(0.0, time.time() - tick)
    except Exception:  # pragma: no cover - liveness module is built concurrently
        logger.debug("runner liveness lookup failed for %s", broker, exc_info=True)

    return RunnerLivenessState(broker=broker, alive=alive, last_tick=tick, last_tick_age_seconds=age)


def _build_live_runner(broker: str) -> Any:
    """Construct a fully-wired ``LiveRunner`` for a broker (SPEC §7.5 R-INT).

    Wires the runner to the real surfaces — the public ``SessionService`` agent
    caller (never the protected loop internals), the broker's READ/WRITE MCP
    tools, the R4 reconciler, the R1 scheduler, and R3 market-hours triggers —
    and injects an audit ``event_callback`` so every autonomous live action is
    broadcast as a ``live.action`` SSE event on the runner's session bus.

    Raises:
        LiveRunnerUnavailable: When the broker channel is not configured.
    """
    h = _host()

    # _runner_factory is monkeypatched on host by tests
    factory = getattr(h, "_runner_factory", None)
    if factory is not None:
        return factory(broker)

    from src.live.audit import write_live_action
    from src.live.runtime.reconcile import reconcile
    from src.live.runtime.runner import LiveRunner
    from src.live.runtime.scheduler import Scheduler
    from src.live.runtime.triggers import Trigger
    from src.trading.service import runner_tool_name

    def _tool(operation: str) -> str:
        remote_tool = runner_tool_name(broker, operation)
        if remote_tool is None:
            raise LiveRunnerUnavailable(
                f"live runner for {broker!r} does not define remote tool {operation!r}"
            )
        return remote_tool

    positions_tool = _tool("positions")
    balance_tool = _tool("account")
    open_orders_tool = _tool("orders")
    submit_order_tool = _tool("submit_order")
    cancel_order_tool = _tool("cancel_order")

    # _live_broker_adapter is monkeypatched on host by tests
    adapter = h._live_broker_adapter(broker)

    def _read(remote_tool: str):
        return lambda: adapter.call_tool(remote_tool, {})

    def _submit(order: Dict[str, Any]) -> Dict[str, Any]:
        if order.get("action") == "cancel":
            return adapter.call_tool(cancel_order_tool, order)
        return adapter.call_tool(submit_order_tool, order)

    svc = h._get_session_service()
    session = svc.create_session(title=f"live-runner:{broker}")
    session_id = session.session_id

    async def _agent_caller(sid: str, prompt: str) -> Dict[str, Any]:
        return await svc.send_message(sid, prompt)

    def _audit_with_bus(event: Any) -> Dict[str, Any]:
        return write_live_action(
            event,
            event_callback=lambda etype, record: svc.event_bus.emit(session_id, etype, record),
        )

    runner_holder: Dict[str, Any] = {}

    async def _on_fire(_job: Any) -> None:
        runner = runner_holder.get("runner")
        if runner is not None:
            await runner.run_once()

    scheduler = Scheduler(_on_fire)

    runner = LiveRunner(
        broker,
        agent_caller=_agent_caller,
        reconcile_fn=reconcile,
        read_positions=_read(positions_tool),
        read_balance=_read(balance_tool),
        read_open_orders=_read(open_orders_tool),
        submit_fn=_submit,
        write_audit_fn=_audit_with_bus,
        scheduler=scheduler,
        triggers=[Trigger.market("us_equity")],
        session_id=session_id,
    )
    runner_holder["runner"] = runner
    return runner


async def _drive_runner(runner: Any) -> None:
    """Run a runner's ``run_loop`` to completion, sync or async."""
    result = runner.run_loop()
    if asyncio.iscoroutine(result):
        await result
    else:
        await asyncio.get_running_loop().run_in_executor(None, lambda: result)


# ============================================================================
# Route registration
# ============================================================================


AuthDep = Callable[..., Awaitable[Any] | Any]


def register_live_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the live-trading routes onto ``app``."""
    h = _host()
    if h is None:
        raise RuntimeError(
            "register_live_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = h.require_auth

    # All route handlers resolve monkeypatched symbols from host at call time
    # via ``_host()`` so that ``monkeypatch.setattr(api_server, ...)`` works.

    @app.post("/mandate/commit", dependencies=[Depends(require_auth)])
    async def commit_mandate_endpoint(payload: CommitMandateRequest):
        """Commit a user-selected mandate profile — the only mandate write path."""
        if payload.consent_ack is not True:
            raise HTTPException(status_code=400, detail="consent_ack must be true to commit a mandate")

        from src.live.mandate.commit import CommitError, commit_mandate

        broker_ceilings = _host()._fetch_broker_ceilings(payload.broker)

        try:
            result = commit_mandate(
                proposal_id=payload.proposal_id,
                ordinal=payload.selected_ordinal,
                adjustments=payload.adjustments,
                consent_ack=payload.consent_ack,
                broker=payload.broker,
                account_ref=payload.account_ref,
                session_id=payload.session_id,
                ceilings_ref=broker_ceilings,
                lifetime_days=payload.lifetime_days,
            )
        except CommitError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _host()._emit_live_event(payload.session_id, "mandate.committed", result)
        _host()._emit_live_event(
            payload.session_id,
            "live.action",
            {"kind": "mandate_committed", "broker": result["broker"], "mandate_id": result["mandate_id"]},
        )
        return result

    @app.post("/live/halt", dependencies=[Depends(require_auth)])
    async def halt_live_endpoint(payload: LiveHaltRequest):
        """Trip the live kill switch (privileged surface action, Consent §4)."""
        from src.live.halt import trip_halt

        try:
            path = trip_halt(by="frontend", reason=payload.reason, broker=payload.broker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        result = {"halted": True, "broker": payload.broker, "reason": payload.reason, "sentinel": str(path)}
        _host()._emit_live_event(payload.session_id, "live.halted", result)
        _host()._emit_live_event(
            payload.session_id,
            "live.action",
            {"kind": "halt_tripped", "broker": payload.broker, "reason": payload.reason},
        )
        return result

    @app.post("/live/resume", dependencies=[Depends(require_auth)])
    async def resume_live_endpoint(payload: LiveHaltRequest):
        """Clear the live kill switch (privileged surface action, Consent §4)."""
        from src.live.halt import clear_halt

        try:
            cleared = clear_halt(broker=payload.broker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        result = {"halted": False, "broker": payload.broker, "cleared": cleared}
        _host()._emit_live_event(payload.session_id, "live.resumed", result)
        _host()._emit_live_event(
            payload.session_id,
            "live.action",
            {"kind": "halt_cleared", "broker": payload.broker, "cleared": cleared},
        )
        return result

    @app.get("/live/status", response_model=LiveStatusResponse, dependencies=[Depends(require_auth)])
    async def live_status_endpoint(broker: Optional[str] = Query(None, max_length=64)):
        """Return live-channel status: auth, active mandate, runner liveness, halt (C2).

        Includes both OAuth/mandate live brokers (robinhood, ibkr) and
        broker_sdk connectors (longbridge, etc.) discovered from the profile
        registry.
        """
        from src.live.halt import halt_flag_set

        all_brokers = sorted(set(_known_live_brokers()) | set(_live_broker_sdk_connectors()))

        if broker is not None:
            target = broker.strip().lower()
            if not target:
                raise HTTPException(status_code=400, detail="broker must not be blank")
            if target not in all_brokers:
                raise HTTPException(status_code=404, detail=f"unknown broker: {target}")
            brokers = [target]
        else:
            brokers = all_brokers

        known = set(_known_live_brokers())
        h = _host()
        statuses: List[LiveBrokerStatus] = []
        for key in brokers:
            # Determine transport type and select the live broker_sdk profile from
            # the registry.  Do not derive a profile id from the connector name.
            transport: Optional[str] = None
            selected_profile = None
            try:
                from src.trading.profiles import list_profiles

                live_profiles = [
                    profile
                    for profile in list_profiles()
                    if profile.connector == key and profile.environment == "live"
                ]
                if live_profiles:
                    transport = live_profiles[0].transport
                declared_readonly_sdk_profiles = [
                    profile
                    for profile in live_profiles
                    if profile.transport == "broker_sdk"
                    and type(profile.id) is str
                    and type(profile.readonly) is bool
                    and profile.readonly is True
                ]
                suffixed_readonly_profiles = [
                    profile
                    for profile in declared_readonly_sdk_profiles
                    if profile.id.endswith("-readonly")
                ]
                # Registry readonly=True is mandatory even when an id ends in
                # ``-readonly``. Prefer one canonical suffixed profile; if none
                # exists, accept one unique declared-readonly profile. Any
                # ambiguity fails closed without making a connector request.
                if len(suffixed_readonly_profiles) == 1:
                    selected_profile = suffixed_readonly_profiles[0]
                elif not suffixed_readonly_profiles and len(declared_readonly_sdk_profiles) == 1:
                    selected_profile = declared_readonly_sdk_profiles[0]
            except Exception:  # noqa: BLE001 - status must never raise
                pass

            # Explicit response allowlist.  Unknown or mismatched verify reports
            # remain fail-closed and cannot supply permission metadata.
            sdk_metadata: Dict[str, Any] = {}
            if selected_profile is not None:
                try:
                    verify_report = h._check_connector_status(selected_profile.id)
                    if verify_report.get("profile_id") == selected_profile.id:
                        def _normalize_capabilities(value: Any) -> Optional[tuple[str, ...]]:
                            if not isinstance(value, (list, tuple)) or not value:
                                return None
                            if not all(
                                type(item) is str and bool(item.strip()) for item in value
                            ):
                                return None
                            return tuple(value)

                        # Permissions are trusted registry declarations, never
                        # reflected from a connector report. The exact profile-id
                        # match above binds the report to this registry profile.
                        registry_capabilities = _normalize_capabilities(
                            selected_profile.capabilities
                        )
                        registry_readonly = (
                            selected_profile.readonly
                            if type(selected_profile.readonly) is bool
                            else None
                        )
                        if registry_readonly is True and (
                            registry_capabilities is None
                            or any(
                                not (
                                    capability.endswith(".read")
                                    or ".read." in capability
                                )
                                for capability in registry_capabilities
                            )
                        ):
                            registry_readonly = None

                        sdk_report = verify_report.get("sdk")
                        sdk_installed = verify_report.get("sdk_installed")
                        if not isinstance(sdk_installed, bool) and isinstance(sdk_report, dict):
                            sdk_installed = sdk_report.get("installed")

                        sdk_metadata = {
                            "profile_id": selected_profile.id,
                            "configured": verify_report.get("configured")
                            if isinstance(verify_report.get("configured"), bool)
                            else None,
                            "credential_source": _closed_vocabulary(
                                verify_report.get("credential_source"),
                                _CREDENTIAL_SOURCES,
                            ),
                            "sdk_installed": sdk_installed
                            if isinstance(sdk_installed, bool)
                            else None,
                            "environment_identity": next(
                                (
                                    normalized
                                    for value in (
                                        verify_report.get("environment_identity"),
                                        verify_report.get("paper_guard"),
                                    )
                                    if (
                                        normalized := _closed_vocabulary(
                                            value, _ENVIRONMENT_IDENTITIES
                                        )
                                    )
                                    is not None
                                ),
                                None,
                            ),
                            "capabilities": list(registry_capabilities)
                            if registry_capabilities is not None
                            else None,
                            "readonly": registry_readonly,
                            "last_checked_at": _canonical_utc_timestamp(
                                verify_report.get("last_checked_at")
                            ),
                            "error_code": _closed_vocabulary(
                                verify_report.get("error_code"), _ERROR_CODES
                            ),
                            "connection_state": _closed_vocabulary(
                                verify_report.get("connection_state"),
                                _CONNECTION_STATES,
                            ),
                        }
                except Exception:  # noqa: BLE001 - status must never raise
                    sdk_metadata = {}

            statuses.append(
                LiveBrokerStatus(
                    auth=BrokerAuthState(
                        broker=key,
                        oauth_token_present=_oauth_token_present(key),
                        is_live_broker=key in known,
                        transport=transport,
                        **sdk_metadata,
                    ),
                    mandate=h._active_mandate_state(key),
                    runner=_runner_liveness_state(key),
                    halted=halt_flag_set(broker=key),
                )
            )

        return LiveStatusResponse(global_halted=halt_flag_set(broker=None), brokers=statuses)

    @app.post("/live/authorize", dependencies=[Depends(require_auth)])
    async def live_authorize_endpoint(payload: LiveAuthorizeRequest):
        """Describe the OAuth bootstrap on-ramp for a live broker (C2 web on-ramp)."""
        broker = payload.broker.strip().lower()
        if not broker:
            raise HTTPException(status_code=400, detail="broker must not be blank")
        if broker not in set(_known_live_brokers()):
            raise HTTPException(status_code=400, detail=f"unknown live broker: {broker}")

        from src.trading.service import connector_profile_id_for_broker

        connector_profile = connector_profile_id_for_broker(broker)
        return {
            "broker": broker,
            "connector_profile": connector_profile,
            "oauth_token_present": _oauth_token_present(broker),
            "instruction": (
                f"Run `vibe-trading connector authorize {connector_profile}` "
                "from the device that will hold the broker session. This opens the "
                "broker's own OAuth consent flow; Vibe-Trading never holds funds and "
                "only relays intent once you authorize."
            ),
            "note": (
                "The live channel stays read-only until the OAuth token is present AND a "
                "mandate is committed AND order tools are explicitly enabled."
            ),
        }

    @app.post("/live/connectors/{profile_id}/verify", dependencies=[Depends(require_auth)])
    async def verify_connector_endpoint(
        profile_id: str,
        force: bool = Query(False, description="Bypass the bounded status cache"),
    ):
        """Read-only idempotent verify for a connector profile (transport-neutral).

        Never requires a mandate.  Never writes or mutates broker state.
        Longbridge and other broker_sdk profiles use this endpoint for a
        credential-free connectivity check.  The result is cached for at most
        15 seconds to avoid hammering the SDK; ``force=true`` bypasses the cache.
        """
        h = _host()

        # Validate the profile exists and is a live broker_sdk connector
        try:
            from src.trading.profiles import profile_by_id
            profile = profile_by_id(profile_id)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"unknown connector profile: {profile_id}")

        if profile.environment != "live":
            raise HTTPException(
                status_code=400,
                detail=f"connector profile '{profile_id}' is not a live profile",
            )

        if profile.transport != "broker_sdk":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"connector profile '{profile_id}' uses transport "
                    f"'{profile.transport}', not broker_sdk; verify is only "
                    "supported for direct-SDK profiles"
                ),
            )

        report = h._check_connector_status(profile_id, force=force)
        return report

    @app.post("/live/runner/start", dependencies=[Depends(require_auth)])
    async def start_runner_endpoint(payload: LiveRunnerControlRequest):
        """Start the persistent live runner for a broker (SPEC §7.5)."""
        from src.live.halt import halt_flag_set
        from src.trading.service import broker_supports_live_runner

        broker = payload.broker.strip().lower()
        if not broker:
            raise HTTPException(status_code=400, detail="broker must not be blank")

        if not broker_supports_live_runner(broker):
            raise HTTPException(
                status_code=400,
                detail=f"live runner is not supported for {broker}",
            )

        h = _host()
        tasks = h._runner_tasks

        existing = tasks.get(broker)
        if existing is not None and not existing.done():
            return {"broker": broker, "started": False, "already_running": True}

        mandate = h._active_mandate_state(broker)
        if mandate is None:
            raise HTTPException(status_code=409, detail=f"no committed mandate for {broker}")
        if mandate.expired:
            raise HTTPException(status_code=409, detail=f"mandate for {broker} has expired; re-authorize first")
        if halt_flag_set(broker=broker) or halt_flag_set(broker=None):
            raise HTTPException(status_code=409, detail="kill switch is tripped; resume before starting the runner")

        try:
            runner = h._build_live_runner(broker)
        except LiveRunnerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"could not construct runner: {exc}") from exc

        task = asyncio.ensure_future(h._drive_runner(runner))
        tasks[broker] = task
        task.add_done_callback(
            lambda t, b=broker: tasks.pop(b, None) if tasks.get(b) is t else None
        )

        h._emit_live_event(
            payload.session_id,
            "live.action",
            {"kind": "runner_started", "broker": broker},
        )
        return {"broker": broker, "started": True, "already_running": False}

    @app.post("/live/runner/stop", dependencies=[Depends(require_auth)])
    async def stop_runner_endpoint(payload: LiveRunnerControlRequest):
        """Stop the persistent live runner for a broker (SPEC §7.5)."""
        from src.trading.service import broker_supports_live_runner

        broker = payload.broker.strip().lower()
        if not broker:
            raise HTTPException(status_code=400, detail="broker must not be blank")

        if not broker_supports_live_runner(broker):
            raise HTTPException(
                status_code=400,
                detail=f"live runner is not supported for {broker}",
            )

        h = _host()
        tasks = h._runner_tasks
        task = tasks.pop(broker, None)
        if task is None or task.done():
            return {"broker": broker, "stopped": False, "was_running": False}

        task.cancel()
        h._emit_live_event(
            payload.session_id,
            "live.action",
            {"kind": "runner_stopped", "broker": broker},
        )
        return {"broker": broker, "stopped": True, "was_running": True}
