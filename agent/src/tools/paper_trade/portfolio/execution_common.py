"""Shared execution-stage error, abort and Decimal/fee primitives.

Holds the stable :class:`ExecutionAdapterError` rejection, the local
``_abort`` helper, the numeric canonical ``_exact_product`` re-export,
the legacy-value readers, the fee primitive, the synthetic day calendar
and the fee-model/market-rules builders shared by the validation,
legacy-match, rows, outcome and adapter modules.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import NoReturn

import pandas as pd

from ..rules import MarketRules
from .ledger import BucketLedger, PortfolioLedger
from .models import PortfolioRequest
from .numeric import (
    EffectiveFeeModel,
    _EXACT_PRECISION as _EXACT_PRECISION,
    _exact_product as _exact_product,
    parse_effective_fee_model,
)
from .schema import PortfolioRequestError


@dataclass(frozen=True, slots=True)
class ExecutionAdapterError(ValueError):
    """One stable execution-stage rejection with no partial outcome attached."""

    reason: str
    path: str
    bucket_id: str | None = None
    detail: str = ""

    def __str__(self) -> str:
        return f"EXECUTION_MISMATCH:{self.reason}:{self.path}"


def _abort(
    reason: str,
    path: str,
    *,
    bucket_id: str | None = None,
    detail: str = "",
) -> NoReturn:
    raise ExecutionAdapterError(
        reason=reason,
        path=path,
        bucket_id=bucket_id,
        detail=detail,
    )


def _finite_decimal(value: object, path: str, bucket_id: str | None = None) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        _abort("nonfinite_decimal", path, bucket_id=bucket_id)
    return value


def _legacy_decimal(value: object, path: str, bucket_id: str) -> Decimal:
    """Read one legacy float as an exact Decimal, or abort on any lossiness."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _abort("invalid_legacy_value", path, bucket_id=bucket_id)
    if isinstance(value, float) and not math.isfinite(value):
        _abort("nonfinite_legacy_value", path, bucket_id=bucket_id)
    if isinstance(value, Decimal) and not value.is_finite():
        _abort("nonfinite_legacy_value", path, bucket_id=bucket_id)
    try:
        return Decimal(str(value))
    except InvalidOperation:
        _abort("invalid_legacy_value", path, bucket_id=bucket_id)


def _price_decimal(value: object, path: str, bucket_id: str) -> Decimal:
    if not isinstance(value, str):
        _abort("invalid_execution_price", path, bucket_id=bucket_id)
    try:
        price = Decimal(value)
    except InvalidOperation:
        _abort("invalid_execution_price", path, bucket_id=bucket_id)
    if not price.is_finite() or price <= 0:
        _abort("invalid_execution_price", path, bucket_id=bucket_id)
    return price


def _fee_for(
    rules: MarketRules,
    side: str,
    qty: int,
    price: Decimal,
) -> Decimal:
    """One fee from the exact fee primitive shared with planning and legacy."""
    try:
        return rules.fee(side, qty, price)
    except (ArithmeticError, ValueError, TypeError):
        _abort("invalid_execution_fee", "execution.fee")


@dataclass(frozen=True, slots=True)
class _PreparedDayCalendar:
    """Replays the preflight day plan through the engine's calendar seam."""

    open_days: frozenset[str]

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self.open_days),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


def _bucket_map(ledger: PortfolioLedger) -> dict[str, BucketLedger]:
    return {bucket.bucket_id: bucket for bucket in ledger.buckets}


def _effective_models(
    request: PortfolioRequest,
    supplied: Sequence[EffectiveFeeModel],
) -> dict[str, EffectiveFeeModel]:
    buckets = {bucket.bucket_id: bucket for bucket in request.portfolio_state.buckets}
    if supplied:
        if isinstance(supplied, (str, bytes, dict)):
            _abort("invalid_effective_fee_models", "fee_models")
        models: dict[str, EffectiveFeeModel] = {}
        for index, model in enumerate(supplied):
            path = f"fee_models[{index}]"
            if not isinstance(model, EffectiveFeeModel):
                _abort("invalid_effective_fee_model", path)
            bucket = buckets.get(model.bucket_id)
            if bucket is None:
                _abort("unknown_fee_bucket", f"{path}.bucket_id", bucket_id=model.bucket_id)
            if model.bucket_id in models:
                _abort("duplicate_effective_fee_model", f"{path}.bucket_id", bucket_id=model.bucket_id)
            if model.market != bucket.market or model.currency != bucket.currency:
                _abort("fee_bucket_mismatch", path, bucket_id=model.bucket_id)
            models[model.bucket_id] = model
    else:
        try:
            models = {
                bucket.bucket_id: parse_effective_fee_model(bucket)
                for bucket in request.portfolio_state.buckets
            }
        except PortfolioRequestError as exc:
            _abort(
                "invalid_fee_model",
                exc.path,
                bucket_id=exc.bucket_id,
                detail=exc.detail,
            )
    missing = set(buckets) - set(models)
    if missing:
        bucket_id = sorted(missing)[0]
        _abort("missing_effective_fee_model", f"fee_models.{bucket_id}", bucket_id=bucket_id)
    return models


def _market_rules(
    model: EffectiveFeeModel,
    hk_lot_sizes: Mapping[str, int] | None,
) -> MarketRules:
    try:
        return MarketRules(
            model.market,
            dict(model.parameters),
            hk_lot_sizes=hk_lot_sizes,
        )
    except (ArithmeticError, TypeError, ValueError):
        _abort("invalid_market_rules", f"fee_models.{model.bucket_id}", bucket_id=model.bucket_id)
