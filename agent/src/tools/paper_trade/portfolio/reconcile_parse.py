"""Document and opening-state parsing for the portfolio replay.

Malformed input raises ``ValueError`` naming the first pydantic location so the
existing tool wrapper can emit its stable JSON error envelope.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..rules import MarketRules
from .models import PortfolioResult, PortfolioState
from .numeric import parse_effective_fee_model
from .schema import PortfolioRequestError


def _parse_result(result: Any) -> PortfolioResult:
    try:
        return PortfolioResult.model_validate(result)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "$"
        message = str(first.get("msg", "invalid document"))
        raise ValueError(
            "result must be a successful pt-v2.0 portfolio document "
            f"({location}: {message})"
        ) from exc


def _parse_account_state(account_state: Any) -> PortfolioState:
    if not isinstance(account_state, dict) or "buckets" not in account_state:
        raise ValueError(
            "account_state must be a pt-v2.0 portfolio_state object with buckets"
        )
    try:
        return PortfolioState.model_validate(account_state)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "$"
        message = str(first.get("msg", "invalid state"))
        raise ValueError(
            "account_state must be a pt-v2.0 portfolio_state object "
            f"({location}: {message})"
        ) from exc


def _fee_rules(
    state: PortfolioState,
) -> tuple[dict[str, MarketRules], dict[str, Any]]:
    rules: dict[str, MarketRules] = {}
    buckets: dict[str, Any] = {}
    for bucket in state.buckets:
        if bucket.bucket_id in buckets:
            continue
        buckets[bucket.bucket_id] = bucket
        try:
            model = parse_effective_fee_model(bucket)
            rules[bucket.bucket_id] = MarketRules(
                model.market, dict(model.parameters)
            )
        except (ArithmeticError, TypeError, ValueError, PortfolioRequestError) as exc:
            raise ValueError(
                "result.opening_portfolio fee model is invalid for bucket "
                f"{bucket.bucket_id}: {exc}"
            ) from exc
    return rules, buckets
