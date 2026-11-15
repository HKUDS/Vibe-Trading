"""Strict fixed-point Decimal boundary values for portfolio accounting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Mapping, NoReturn

from .models import Currency, FeeModel, JsonObject, JsonValue, Market, PortfolioBucket
from .schema import PortfolioRequestError

if TYPE_CHECKING:
    from ..rules import MarketRules

_DECIMAL_PATTERN: Final = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_MAX_WIRE_VALUE: Final = Decimal("999999999999999999999999")
_MAX_SCALE: Final = 12


@dataclass(frozen=True, slots=True)
class DecimalSpec:
    """Scale and inclusive/exclusive bounds for one numeric domain."""

    scale: int
    minimum: Decimal | None = None
    maximum: Decimal | None = _MAX_WIRE_VALUE
    minimum_inclusive: bool = True


MONEY_SPEC: Final = DecimalSpec(scale=2, minimum=-_MAX_WIRE_VALUE)
PRICE_SPEC: Final = DecimalSpec(scale=6, minimum=Decimal(0), minimum_inclusive=False)
WEIGHT_SPEC: Final = DecimalSpec(scale=12, minimum=Decimal(0), maximum=Decimal(1))
FX_RATE_SPEC: Final = DecimalSpec(scale=12, minimum=Decimal(0), minimum_inclusive=False)
MAX_JSON_INTEGER: Final = (1 << 53) - 1

_CANONICAL_CURRENCIES: Final = {"cn_a": "CNY", "hk": "HKD", "us": "USD"}
_FEE_MONEY_SPEC: Final = DecimalSpec(scale=2)
_FEE_PER_SHARE_SPEC: Final = DecimalSpec(scale=6)
_FEE_RATE_SPEC: Final = DecimalSpec(scale=12, maximum=Decimal(1))
_FEE_PARAMETER_SPECS: Final = {
    "commission_min": _FEE_MONEY_SPEC,
    "commission_per_share": _FEE_PER_SHARE_SPEC,
    "commission_rate": _FEE_RATE_SPEC,
    "regulatory_levy_rate": _FEE_RATE_SPEC,
    "sec_fee_rate": _FEE_RATE_SPEC,
    "stamp_tax_rate": _FEE_RATE_SPEC,
    "stamp_tax_sell": _FEE_RATE_SPEC,
    "transfer_fee": _FEE_RATE_SPEC,
}
_DEFAULT_FEE_PARAMETERS: Final = {
    "cn_a": {
        "commission_rate": "0.00025",
        "commission_min": "5",
        "stamp_tax_sell": "0.0005",
        "transfer_fee": "0.00001",
    },
    "hk": {
        "commission_rate": "0.0003",
        "commission_min": "3",
        "stamp_tax_rate": "0.001",
        "regulatory_levy_rate": "0.00003",
    },
    "us": {
        "commission_per_share": "0.0049",
        "commission_min": "0.99",
        "sec_fee_rate": "0",
    },
}


def _reject(reason: str, path: str, detail: str = "") -> NoReturn:
    raise PortfolioRequestError(reason=reason, path=path, detail=detail)


def _check_spec(spec: DecimalSpec, path: str) -> None:
    if not 0 <= spec.scale <= _MAX_SCALE:
        _reject("invalid_numeric_spec", path, "scale is outside the supported range")
    if (
        spec.minimum is not None
        and spec.maximum is not None
        and spec.minimum > spec.maximum
    ):
        _reject("invalid_numeric_spec", path, "minimum exceeds maximum")


def _below_minimum(value: Decimal, spec: DecimalSpec) -> bool:
    if spec.minimum is None:
        return False
    if spec.minimum_inclusive:
        return value < spec.minimum
    return value <= spec.minimum


def _quantize_and_check(value: Decimal, spec: DecimalSpec, path: str) -> Decimal:
    _check_spec(spec, path)
    if not value.is_finite():
        _reject("invalid_decimal", path, "value must be finite")
    if value.is_zero() and value.is_signed():
        _reject("negative_zero", path)
    if _below_minimum(value, spec) or (
        spec.maximum is not None and value > spec.maximum
    ):
        _reject("decimal_out_of_range", path)
    try:
        with localcontext() as context:
            context.prec = 38
            quantum = Decimal(1).scaleb(-spec.scale)
            quantized = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        _reject("decimal_out_of_range", path, "value cannot be represented at this scale")
    if quantized.is_zero() and quantized.is_signed():
        _reject("negative_zero", path, "rounding would produce negative zero")
    if _below_minimum(quantized, spec) or (
        spec.maximum is not None and quantized > spec.maximum
    ):
        _reject("decimal_out_of_range", path, "rounded value is out of range")
    return quantized


def parse_decimal(value: JsonValue, spec: DecimalSpec, path: str = "$") -> Decimal:
    """Parse a JSON fixed-point string without float or exponent coercion."""
    if not isinstance(value, str) or _DECIMAL_PATTERN.fullmatch(value) is None:
        _reject("invalid_decimal", path, "expected a canonical fixed-point string")
    candidate = Decimal(value)
    if candidate.is_zero() and value.startswith("-"):
        _reject("negative_zero", path)
    return _quantize_and_check(candidate, spec, path)


def canonical_decimal(value: Decimal, spec: DecimalSpec, path: str = "$") -> str:
    """Render a finite Decimal as a scale-stable JSON/JCS-safe string."""
    if not isinstance(value, Decimal):
        _reject("invalid_decimal", path, "internal value must be Decimal")
    quantized = _quantize_and_check(value, spec, path)
    return format(quantized, f".{spec.scale}f")


def parse_money(value: JsonValue, path: str = "money") -> Decimal:
    """Parse signed money at two fractional digits."""
    return parse_decimal(value, MONEY_SPEC, path)


def parse_price(value: JsonValue, path: str = "price") -> Decimal:
    """Parse a positive price at six fractional digits."""
    return parse_decimal(value, PRICE_SPEC, path)


def parse_weight(value: JsonValue, path: str = "weight") -> Decimal:
    """Parse a long-only weight in the closed zero-to-one interval."""
    return parse_decimal(value, WEIGHT_SPEC, path)


def parse_fx_rate(value: JsonValue, path: str = "fx_rate") -> Decimal:
    """Parse a positive direct-pair rate at twelve fractional digits."""
    return parse_decimal(value, FX_RATE_SPEC, path)


def parse_quantity(value: JsonValue, path: str = "quantity", allow_zero: bool = False) -> int:
    """Parse a whole-share quantity inside the exact JSON integer range."""
    if type(value) is not int:
        _reject("invalid_quantity", path, "expected an integer, not a bool, float or string")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= MAX_JSON_INTEGER:
        _reject("quantity_out_of_range", path)
    return value


def parse_lot_size(value: JsonValue, path: str = "lot_size") -> int:
    """Parse a positive whole-share lot size."""
    return parse_quantity(value, path)


@dataclass(frozen=True, slots=True)
class EffectiveFeeModel:
    """Complete per-bucket Decimal fee parameters with canonical currency."""

    bucket_id: str
    market: Market
    currency: Currency
    parameters: Mapping[str, Decimal]

    def canonical_parameters(self) -> Mapping[str, str]:
        """Return sorted, scale-stable fee strings for JSON and JCS."""
        return {
            name: canonical_decimal(value, _FEE_PARAMETER_SPECS[name])
            for name, value in sorted(self.parameters.items())
        }

    def to_wire(self) -> JsonObject:
        """Return the internal effective model using JSON-native values only."""
        return {"currency": self.currency, "parameters": dict(self.canonical_parameters())}

    def market_rules(self) -> MarketRules:
        """Reuse the legacy fee primitive with a complete Decimal override map."""
        from ..rules import MarketRules

        return MarketRules(self.market, self.parameters)


def _fee_value(name: str, value: JsonValue, path: str) -> Decimal:
    if (
        isinstance(value, str)
        and _DECIMAL_PATTERN.fullmatch(value) is not None
        and Decimal(value) < 0
    ):
        _reject("negative_fee", path)
    parsed = parse_decimal(value, _FEE_PARAMETER_SPECS[name], path)
    if parsed < 0:
        _reject("negative_fee", path)
    return parsed


def _bucket_error(reason: str, path: str, bucket: PortfolioBucket) -> NoReturn:
    raise PortfolioRequestError(reason=reason, path=path, bucket_id=bucket.bucket_id)


def _check_bucket(bucket: PortfolioBucket, path: str) -> None:
    expected = _CANONICAL_CURRENCIES.get(bucket.market)
    bucket_path = path.removesuffix(".fee_model") or "$"
    if expected is None:
        _bucket_error("invalid_bucket_market", f"{bucket_path}.market", bucket)
    if bucket.market == "hk" and bucket.currency != "HKD":
        _bucket_error("non_hkd_hk_counter", f"{bucket_path}.currency", bucket)
    if bucket.currency != expected:
        _bucket_error("invalid_bucket_currency", f"{bucket_path}.currency", bucket)


def _raw_fee_parts(
    fee_model: FeeModel | JsonObject, path: str, bucket: PortfolioBucket
) -> tuple[JsonValue, Mapping[str, JsonValue]]:
    if isinstance(fee_model, FeeModel):
        parameters: dict[str, JsonValue] = {}
        for parameter in fee_model.parameters:
            if parameter.name in parameters:
                _bucket_error("duplicate_fee_parameter", f"{path}.parameters.{parameter.name}", bucket)
            parameters[parameter.name] = parameter.value
        return fee_model.currency, parameters
    if not isinstance(fee_model, dict) or set(fee_model) - {"currency", "parameters"}:
        _bucket_error("invalid_fee_model", path, bucket)
    raw_parameters = fee_model.get("parameters")
    if not isinstance(raw_parameters, dict) or not raw_parameters:
        _bucket_error("invalid_fee_parameters", f"{path}.parameters", bucket)
    return fee_model.get("currency"), raw_parameters


def _check_fee_currency(
    raw_currency: JsonValue, bucket: PortfolioBucket, path: str
) -> None:
    if raw_currency is None:
        return
    if bucket.market == "hk" and raw_currency != "HKD":
        _bucket_error("non_hkd_hk_counter", f"{path}.currency", bucket)
    if raw_currency != bucket.currency:
        _bucket_error("invalid_fee_currency", f"{path}.currency", bucket)


def parse_effective_fee_model(
    bucket: PortfolioBucket,
    fee_model: FeeModel | JsonObject | None = None,
    path: str = "fee_model",
) -> EffectiveFeeModel:
    """Merge strict per-bucket overrides over the frozen string defaults."""
    _check_bucket(bucket, path)
    raw_fee_model = bucket.fee_model if fee_model is None else fee_model
    raw_currency: JsonValue = None
    overrides: Mapping[str, JsonValue] = {}
    if raw_fee_model is not None:
        raw_currency, overrides = _raw_fee_parts(raw_fee_model, path, bucket)
        _check_fee_currency(raw_currency, bucket, path)
        if not overrides:
            _bucket_error("invalid_fee_parameters", f"{path}.parameters", bucket)
    defaults = _DEFAULT_FEE_PARAMETERS[bucket.market]
    unknown = set(overrides) - set(defaults)
    if unknown:
        name = sorted(unknown)[0]
        _bucket_error("unknown_fee_parameter", f"{path}.parameters.{name}", bucket)
    merged = {**defaults, **overrides}
    try:
        parameters = {
            name: _fee_value(name, value, f"{path}.parameters.{name}")
            for name, value in merged.items()
        }
    except PortfolioRequestError as exc:
        raise PortfolioRequestError(
            reason=exc.reason,
            path=exc.path,
            bucket_id=bucket.bucket_id,
            detail=exc.detail,
        ) from None
    return EffectiveFeeModel(
        bucket_id=bucket.bucket_id,
        market=bucket.market,
        currency=bucket.currency,
        parameters=MappingProxyType(parameters),
    )
