"""Options analysis HTTP routes for the Web UI.

Mounted by ``agent/api_server.py`` via ``register_options_routes(app, ...)``.
Pulled into its own module because ``api_server.py`` is already huge, matching
the ``alpha_routes.py`` slice pattern.

Routes (auth via the caller-supplied ``require_auth`` dependency):

- ``POST /options/payoff``  — multi-leg expiry payoff + spot/IV scenario analysis
- ``GET  /options/chain``   — US-listed options chain for one expiration (Yahoo)

Both routes are thin HTTP wrappers around the existing agent tools
(``OptionsPayoffTool`` / ``OptionsChainTool``) so validation and math stay
identical to the MCP surface — no formula is reimplemented here.

``POST /options/payoff`` returns the tool's envelope verbatim plus one additive
top-level ``greeks`` object: portfolio Greeks at entry (sum of ``qty * greek``
per leg, scaled by ``multiplier`` so cards show dollar exposure). Computed via
``src.quantlib.options.bs_greeks`` — theta per calendar day, vega/rho per 1
percentage point, the quantlib native convention.

Error surface:

- Payoff: pydantic request validation → 422 (FastAPI default). A tool-level
  error envelope (``{"status": "error", ...}``) → 400 with that same body.
  An unexpected exception inside the tool call → 502 with a generic envelope.
- Chain: missing/blank ticker → 400 ``{"ok": false, "error": "ticker is
  required"}``; a tool failure envelope (``ok: false``) → 502 with the tool's
  body; an unexpected exception inside the tool call → 502 with a generic
  envelope. Success → 200 with the tool envelope verbatim.

The chain call does Yahoo network I/O and runs in ``asyncio.to_thread``; the
payoff call is CPU-light but also runs in a worker thread so both endpoints
keep the event loop free under concurrent use.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Awaitable, Callable, Literal

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from src.quantlib.options import bs_greeks
from src.tools.options_chain_tool import OptionsChainTool
from src.tools.options_payoff_tool import OptionsPayoffTool, _coerce_legs

logger = logging.getLogger(__name__)

# Keep in sync with OptionsPayoffTool's parameter schema. Duplicated as pydantic
# constraints so bad requests fail fast with 422 before any tool work happens;
# the tool re-validates everything, so drift degrades to its error envelope.
_MAX_LEGS = 20
_MIN_SPOT_POINTS = 21
_MAX_SPOT_POINTS = 501
_DEFAULT_SPOT_POINTS = 121
_MAX_IV_SCENARIOS = 9

_GREEK_KEYS = ("delta", "gamma", "theta", "vega", "rho")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PayoffLeg(BaseModel):
    """One signed option leg of a payoff request."""

    option_type: Literal["call", "put"]
    strike: float = Field(..., gt=0)
    qty: int
    premium: float | None = Field(None, ge=0)

    @field_validator("qty")
    @classmethod
    def _qty_nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("qty must be a non-zero integer")
        return v


class PayoffRequest(BaseModel):
    """POST /options/payoff body — mirrors ``OptionsPayoffTool.parameters``."""

    legs: list[PayoffLeg] = Field(..., min_length=1, max_length=_MAX_LEGS)
    entry_spot: float = Field(..., gt=0)
    expiry_days: float = Field(..., ge=0)
    risk_free_rate: float = Field(0.05)
    volatility: float = Field(0.3, gt=0)
    multiplier: float = Field(1.0, gt=0)
    commission_rate: float = Field(0.001, ge=0, lt=1)
    spot_min: float | None = Field(None, ge=0)
    spot_max: float | None = Field(None, gt=0)
    spot_points: int = Field(_DEFAULT_SPOT_POINTS, ge=_MIN_SPOT_POINTS, le=_MAX_SPOT_POINTS)
    scenario_iv_values: (
        list[Annotated[float, Field(gt=0)]] | None
    ) = Field(None, min_length=1, max_length=_MAX_IV_SCENARIOS)


def _tool_params(payload: PayoffRequest) -> dict[str, Any]:
    """Project the validated request onto the tool's execute() kwargs.

    Optional fields left at ``None`` are omitted so the tool applies its own
    defaults (chart bounds derived from strikes/spot, the five default IV
    scenarios), exactly as on the MCP surface.
    """
    params: dict[str, Any] = {
        "legs": [leg.model_dump(exclude_none=True) for leg in payload.legs],
        "entry_spot": payload.entry_spot,
        "expiry_days": payload.expiry_days,
        "risk_free_rate": payload.risk_free_rate,
        "volatility": payload.volatility,
        "multiplier": payload.multiplier,
        "commission_rate": payload.commission_rate,
        "spot_points": payload.spot_points,
    }
    if payload.spot_min is not None:
        params["spot_min"] = payload.spot_min
    if payload.spot_max is not None:
        params["spot_max"] = payload.spot_max
    if payload.scenario_iv_values is not None:
        params["scenario_iv_values"] = payload.scenario_iv_values
    return params


def _portfolio_greeks(payload: PayoffRequest) -> dict[str, float]:
    """Portfolio Greeks at entry, in dollar exposure per unit of ``multiplier``.

    Legs are re-run through the tool's own ``_coerce_legs`` so the Greeks use
    exactly the same leg values the payoff envelope was built from. ``qty`` is
    already signed, so summing ``qty * greek`` nets longs against shorts.
    Conventions are ``bs_greeks``' native ones: theta per calendar day,
    vega/rho per 1 percentage point — no conversion applied.
    """
    legs = _coerce_legs([leg.model_dump(exclude_none=True) for leg in payload.legs])
    time_to_expiry = payload.expiry_days / 365.0
    totals = {key: 0.0 for key in _GREEK_KEYS}
    for leg in legs:
        greeks = bs_greeks(
            S=payload.entry_spot,
            K=leg.strike,
            T=time_to_expiry,
            r=payload.risk_free_rate,
            sigma=payload.volatility,
            option_type=leg.option_type,
        )
        for key in _GREEK_KEYS:
            totals[key] += leg.qty * greeks[key]
    return {key: round(value * payload.multiplier, 6) for key, value in totals.items()}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_options_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the options routes onto ``app``.

    Args:
        app: The host FastAPI app.
        require_auth: Header-auth dependency for both endpoints.

    For backwards compatibility, when the dependency callable is not passed
    explicitly we resolve it from the host ``api_server`` module via
    ``sys.modules``. Prefer the explicit form in new call sites.
    """
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover — only triggers on weird import setups
            raise RuntimeError(
                "register_options_routes: api_server module not in sys.modules; "
                "pass require_auth explicitly"
            )
        require_auth = host.require_auth

    # -----------------------------------------------------------------------
    # POST /options/payoff
    # -----------------------------------------------------------------------

    @app.post("/options/payoff", dependencies=[Depends(require_auth)])
    async def options_payoff(payload: PayoffRequest) -> Response:
        """Tool-identical payoff analysis plus portfolio Greeks at entry."""
        params = _tool_params(payload)
        tool = OptionsPayoffTool()
        try:
            raw = await asyncio.to_thread(tool.execute, **params)
            envelope = json.loads(raw)
        except Exception:  # noqa: BLE001 — never leak a stack frame to clients
            logger.exception("options payoff tool call failed")
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "payoff computation failed"},
            )
        if envelope.get("status") != "ok":
            # Curated tool error envelope (bad bounds, bad scenarios, ...) —
            # surface it verbatim as a client error.
            return JSONResponse(status_code=400, content=envelope)
        envelope["greeks"] = _portfolio_greeks(payload)
        return envelope

    # -----------------------------------------------------------------------
    # GET /options/chain
    # -----------------------------------------------------------------------

    @app.get("/options/chain", dependencies=[Depends(require_auth)])
    async def options_chain(
        ticker: str | None = Query(None, max_length=64),
        expiration: int | None = Query(None),
    ) -> Response:
        """Wrap ``OptionsChainTool`` (Yahoo network I/O, run in a thread)."""
        if ticker is None or not ticker.strip():
            return JSONResponse(
                status_code=400, content={"ok": False, "error": "ticker is required"}
            )
        kwargs: dict[str, Any] = {"ticker": ticker}
        if expiration is not None:
            kwargs["expiration"] = expiration
        tool = OptionsChainTool()
        try:
            raw = await asyncio.to_thread(tool.execute, **kwargs)
            envelope = json.loads(raw)
        except Exception:  # noqa: BLE001 — never leak a stack frame to clients
            logger.exception("options chain tool call failed (ticker=%s)", ticker)
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "options chain request failed"},
            )
        if not envelope.get("ok"):
            return JSONResponse(status_code=502, content=envelope)
        return envelope
