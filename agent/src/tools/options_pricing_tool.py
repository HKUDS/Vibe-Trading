"""Options pricing tool: Black-Scholes theoretical price and Greeks."""

from __future__ import annotations

import json
import math
from typing import Any

from src.agent.tools import BaseTool
from src.quantlib.options import bs_greeks, bs_price


def _validate_inputs(
    spot: float, strike: float, expiry_days: float, sigma: float, r: float, option_type: str
) -> str | None:
    """Reject genuinely invalid inputs at the boundary (P06).

    T == 0 is a *valid* expiry (handled downstream as intrinsic value), so
    it is intentionally NOT rejected here — only invalid inputs are.
    """
    if option_type not in ("call", "put"):
        return f"option_type must be 'call' or 'put', got {option_type!r}"
    for _name, _val in (
        ("spot", spot),
        ("strike", strike),
        ("expiry_days", expiry_days),
        ("volatility", sigma),
        ("risk_free_rate", r),
    ):
        if not math.isfinite(_val):
            return f"{_name} must be a finite number, got {_val}"
    if spot <= 0:
        return f"spot must be positive, got {spot}"
    if strike <= 0:
        return f"strike must be positive, got {strike}"
    if sigma <= 0:
        return f"volatility must be positive, got {sigma}"
    if expiry_days < 0:
        return f"expiry_days must be non-negative, got {expiry_days}"
    return None


def _bs_price_and_greeks(
    spot: float,
    strike: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> dict:
    """Compute Black-Scholes price and Greeks.

    Thin adapter over :mod:`src.quantlib.options`, which owns the one
    implementation of this formula in the repo. This function's only jobs are
    to merge price and Greeks into a single dict and to round for display.

    Args:
        spot: Current underlying price.
        strike: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate.
        sigma: Annualised volatility.
        option_type: "call" or "put".

    Returns:
        Dict containing price, delta, gamma, theta, vega and rho, each rounded
        to six decimal places.
    """
    price = bs_price(spot, strike, T, r, sigma, option_type)
    greeks = bs_greeks(spot, strike, T, r, sigma, option_type)
    return {
        "price": round(price, 6),
        **{name: round(value, 6) for name, value in greeks.items()},
    }


class OptionsPricingTool(BaseTool):
    """Options pricing tool: Black-Scholes theoretical price and Greeks."""

    name = "options_pricing"
    description = "Options pricing: compute theoretical price and Greeks using the Black-Scholes model."
    parameters = {
        "type": "object",
        "properties": {
            "spot": {"type": "number", "description": "Current underlying price"},
            "strike": {"type": "number", "description": "Strike price"},
            "expiry_days": {"type": "number", "description": "Days to expiry"},
            "risk_free_rate": {"type": "number", "description": "Risk-free rate", "default": 0.05},
            "volatility": {"type": "number", "description": "Annualised volatility"},
            "option_type": {"type": "string", "enum": ["call", "put"], "description": "Option type"},
        },
        "required": ["spot", "strike", "expiry_days", "volatility", "option_type"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Run options pricing calculation.

        Args:
            **kwargs: Must include spot, strike, expiry_days, volatility, option_type.
                     Optional risk_free_rate.

        Returns:
            JSON string containing price, delta, gamma, theta, vega, or an error
            envelope when an argument is missing or cannot be read as a number.
            ``risk_free_rate`` is optional and defaults to its schema value 0.05,
            so an explicit JSON ``null`` is treated as omission.
        """
        try:
            if "spot" not in kwargs or kwargs["spot"] is None:
                raise ValueError("spot is required")
            if "strike" not in kwargs or kwargs["strike"] is None:
                raise ValueError("strike is required")
            if "expiry_days" not in kwargs or kwargs["expiry_days"] is None:
                raise ValueError("expiry_days is required")
            if "volatility" not in kwargs or kwargs["volatility"] is None:
                raise ValueError("volatility is required")
            spot = float(kwargs["spot"])
            strike = float(kwargs["strike"])
            expiry_days = float(kwargs["expiry_days"])
            r_val = kwargs.get("risk_free_rate")
            r = float(r_val if r_val is not None and r_val != "" else 0.05)
            sigma = float(kwargs["volatility"])
            option_type = str(kwargs.get("option_type") or "")
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            # OverflowError: a JSON integer larger than a float (e.g. 10**10000)
            # raises it from float(), and it must not escape this envelope.
            return json.dumps(
                {"status": "error", "tool": "options_pricing", "error": f"invalid or missing input argument: {exc}"},
                ensure_ascii=False,
            )

        err = _validate_inputs(spot, strike, expiry_days, sigma, r, option_type)
        if err is not None:
            return json.dumps(
                {"status": "error", "tool": "options_pricing", "error": err},
                ensure_ascii=False,
            )

        T = expiry_days / 365.0

        result = _bs_price_and_greeks(spot, strike, T, r, sigma, option_type)
        result["inputs"] = {
            "spot": spot,
            "strike": strike,
            "expiry_days": expiry_days,
            "risk_free_rate": r,
            "volatility": sigma,
            "option_type": option_type,
            "T_years": round(T, 6),
        }
        nonfinite = any(
            k not in result or not math.isfinite(float(result[k])) for k in ("price", "delta", "gamma", "theta", "vega")
        )
        if T == 0.0 or nonfinite:
            result["status"] = "degenerate"
            result["degenerate"] = True
            result["warning"] = (
                "option at expiry (T=0): Greeks are singular; intrinsic value returned"
                if T == 0.0
                else "non-finite result (extreme inputs); values unreliable"
            )
        else:
            result["status"] = "ok"

        try:
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except ValueError as exc:
            return json.dumps(
                {"status": "error", "tool": "options_pricing", "error": f"non-serializable numeric result: {exc}"},
                ensure_ascii=False,
            )
