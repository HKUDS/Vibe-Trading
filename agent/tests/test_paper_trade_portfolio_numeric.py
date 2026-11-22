"""Canonical Decimal numerics and strict fee-model tests for pt-v2.0."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.tools.paper_trade.portfolio import errors, fx, ledger, numeric, schema
from src.tools.paper_trade.portfolio.models import Currency, FeeModel, JsonValue, Market, PortfolioBucket


def test_consolidated_error_and_helpers_are_single_source_objects() -> None:
    # Given the foundation modules that historically duplicated these definitions.
    # When / Then the rejection type is one shared class object everywhere.
    assert errors.PortfolioRequestError is numeric.PortfolioRequestError
    assert schema.PortfolioRequestError is numeric.PortfolioRequestError

    # And every runtime helper resolves to the single canonical numeric definition.
    assert schema._reject is numeric._reject
    assert fx._reject is numeric._reject
    assert ledger._reject is numeric._reject
    assert fx._exact_product is numeric._exact_product
    assert ledger._exact_product is numeric._exact_product
    assert fx._EXACT_PRECISION == ledger._EXACT_PRECISION == numeric._EXACT_PRECISION == 60
    assert schema._CANONICAL_CURRENCIES is numeric._CANONICAL_CURRENCIES
    assert ledger._CANONICAL_CURRENCIES is numeric._CANONICAL_CURRENCIES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("100.005", "100.00"), ("100.015", "100.02"), ("0", "0.00")],
)
def test_money_canonical_round_trip_uses_scale_and_half_even(
    raw: str, expected: str
) -> None:
    # Given a fixed-point money string at the explicit two-place scale.
    # When it is parsed and rendered for JSON/JCS.
    value = numeric.parse_money(raw)

    # Then ties use ROUND_HALF_EVEN and the canonical scale is stable.
    assert value == Decimal(expected)
    assert numeric.canonical_decimal(value, numeric.MONEY_SPEC) == expected
    assert numeric.parse_money(numeric.canonical_decimal(value, numeric.MONEY_SPEC)) == value


def test_domain_scales_are_explicit_and_stable() -> None:
    # Given price, weight and direct-pair FX strings with different precisions.
    # When each domain parser renders its JSON/JCS-safe value.
    price = numeric.parse_price("417.8")
    weight = numeric.parse_weight("0.1234567890126")
    fx_rate = numeric.parse_fx_rate("0.128")

    # Then each domain uses its declared scale and ROUND_HALF_EVEN.
    assert numeric.canonical_decimal(price, numeric.PRICE_SPEC) == "417.800000"
    assert numeric.canonical_decimal(weight, numeric.WEIGHT_SPEC) == "0.123456789013"
    assert numeric.canonical_decimal(fx_rate, numeric.FX_RATE_SPEC) == "0.128000000000"


@pytest.mark.parametrize(
    "raw",
    [
        None, True, False, 1, 1.0, [], "", "NaN", "Infinity", "-Infinity",
        "1e3", "1E-3", "+1", "01", " 1", "1 ", ".5", "1.", "--1",
    ],
)
def test_public_decimal_parser_rejects_noncanonical_and_non_string_input(raw) -> None:
    # Given a value outside the fixed-point JSON string contract.
    # When / Then the public parser rejects it with the existing domain error.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        numeric.parse_money(raw, path="portfolio_state.buckets[0].cash")

    assert caught.value.code == "INVALID_REQUEST"
    assert caught.value.reason == "invalid_decimal"
    assert caught.value.path == "portfolio_state.buckets[0].cash"


@pytest.mark.parametrize("raw", ["-0", "-0.0", "-0.000000000000"])
def test_negative_zero_is_rejected(raw: str) -> None:
    # Given a spelling that Decimal would otherwise normalize to signed zero.
    # When / Then it is rejected rather than leaked into canonical JSON.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        numeric.parse_money(raw)

    assert caught.value.reason == "negative_zero"


@pytest.mark.parametrize(
    ("parser", "raw"),
    [
        (numeric.parse_weight, "-0.01"),
        (numeric.parse_weight, "1.01"),
        (numeric.parse_price, "0"),
        (numeric.parse_price, "0.0000001"),
        (numeric.parse_fx_rate, "0"),
        (numeric.parse_money, "10000000000000000000000000"),
    ],
)
def test_domain_ranges_are_checked_before_and_after_rounding(parser, raw: str) -> None:
    # Given a value outside its domain, including one that rounds to zero.
    # When / Then no rounded representation can launder the range violation.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        parser(raw)

    assert caught.value.reason == "decimal_out_of_range"


def test_quantities_and_lot_sizes_are_json_safe_integers() -> None:
    # Given whole-share quantity and lot values at the JSON-safe boundary.
    # When they cross the numeric parser.
    quantity = numeric.parse_quantity(numeric.MAX_JSON_INTEGER)
    empty_position = numeric.parse_quantity(0, allow_zero=True)
    lot_size = numeric.parse_lot_size(100)

    # Then they remain integers without a float or string conversion.
    assert quantity == numeric.MAX_JSON_INTEGER
    assert type(quantity) is int
    assert empty_position == 0
    assert lot_size == 100


@pytest.mark.parametrize("raw", [None, True, 1.0, "1", 0, -1, numeric.MAX_JSON_INTEGER + 1])
def test_invalid_quantities_are_rejected(raw) -> None:
    # Given a non-integer, boolean, nonpositive or unsafe-integer quantity.
    # When / Then the parser fails closed with a typed reason.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        numeric.parse_quantity(raw, path="orders[0].qty")

    assert caught.value.code == "INVALID_REQUEST"
    assert caught.value.path == "orders[0].qty"
    assert caught.value.reason in {"invalid_quantity", "quantity_out_of_range"}


def _bucket(market: Market, currency: Currency, fee_model: FeeModel | None = None) -> PortfolioBucket:
    return PortfolioBucket(
        bucket_id=market,
        market=market,
        currency=currency,
        cash="0.00",
        positions=(),
        fee_model=fee_model,
    )


@pytest.mark.parametrize(
    ("market", "currency", "expected"),
    [
        (
            "cn_a",
            "CNY",
            {
                "commission_min": "5.00",
                "commission_rate": "0.000250000000",
                "stamp_tax_sell": "0.000500000000",
                "transfer_fee": "0.000010000000",
            },
        ),
        (
            "hk",
            "HKD",
            {
                "commission_min": "3.00",
                "commission_rate": "0.000300000000",
                "regulatory_levy_rate": "0.000030000000",
                "stamp_tax_rate": "0.001000000000",
            },
        ),
        (
            "us",
            "USD",
            {
                "commission_min": "0.99",
                "commission_per_share": "0.004900",
                "sec_fee_rate": "0.000000000000",
            },
        ),
    ],
)
def test_default_fee_models_are_complete_decimal_and_canonical(
    market: Market, currency: Currency, expected: dict[str, str]
) -> None:
    # Given a canonical bucket with no caller fee overrides.
    # When its effective fee model crosses the strict numeric parser.
    model = numeric.parse_effective_fee_model(_bucket(market, currency))

    # Then defaults are complete, exact and safe for deterministic JSON/JCS.
    assert model.bucket_id == market
    assert model.currency == currency
    assert all(type(value) is Decimal for value in model.parameters.values())
    assert model.canonical_parameters() == expected
    assert model.to_wire() == {"currency": currency, "parameters": expected}
    assert json.dumps(model.to_wire(), allow_nan=False)


def test_fee_currency_is_inherited_and_overrides_keep_other_defaults() -> None:
    # Given a canonical HK bucket and one rate-only caller override.
    bucket = _bucket(
        "hk",
        "HKD",
        FeeModel(parameters={"commission_rate": "0.0004"}),
    )

    # When the effective model is parsed.
    model = numeric.parse_effective_fee_model(bucket)

    # Then currency comes only from the bucket and all other defaults remain.
    assert model.currency == "HKD"
    assert model.parameters["commission_rate"] == Decimal("0.0004")
    assert model.parameters["commission_min"] == Decimal("3.00")
    assert model.parameters["stamp_tax_rate"] == Decimal("0.001")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, "invalid_decimal"), (True, "invalid_decimal"),
        (0.01, "invalid_decimal"), (1, "invalid_decimal"),
        ("NaN", "invalid_decimal"), ("Infinity", "invalid_decimal"),
        ("1e-2", "invalid_decimal"), ("01", "invalid_decimal"),
        ("-0", "negative_zero"), ("-0.00", "negative_zero"),
        ("-0.01", "negative_fee"),
    ],
)
def test_fee_values_reject_every_malformed_numeric_class(raw: JsonValue, reason: str) -> None:
    # Given a malformed commission minimum on an otherwise canonical bucket.
    raw_fee_model = {"currency": "CNY", "parameters": {"commission_min": raw}}

    # When / Then strict fee parsing fails at the exact parameter and bucket.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        numeric.parse_effective_fee_model(
            _bucket("cn_a", "CNY"),
            raw_fee_model,
            path="portfolio_state.buckets[0].fee_model",
        )

    error = caught.value
    assert error.code == "INVALID_REQUEST"
    assert error.reason == reason
    assert error.path == "portfolio_state.buckets[0].fee_model.parameters.commission_min"
    assert error.bucket_id == "cn_a"


@pytest.mark.parametrize(
    "name", ["commission_rate", "commission_min", "stamp_tax_sell", "transfer_fee"]
)
def test_every_cn_fee_parameter_rejects_negative_values(name: str) -> None:
    # Given a negative value for each supported cn_a fee component.
    # When / Then the parser rejects it instead of passing it to MarketRules.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        numeric.parse_effective_fee_model(
            _bucket("cn_a", "CNY"), {"parameters": {name: "-0.0001"}}
        )

    assert caught.value.reason == "negative_fee"


@pytest.mark.parametrize(
    ("market", "currency", "fee_currency", "reason"),
    [
        ("hk", "HKD", "USD", "non_hkd_hk_counter"),
        ("hk", "USD", None, "non_hkd_hk_counter"),
        ("cn_a", "HKD", None, "invalid_bucket_currency"),
        ("us", "USD", "HKD", "invalid_fee_currency"),
    ],
)
def test_fee_currency_requires_a_canonical_bucket(
    market: Market,
    currency: Currency,
    fee_currency: str | None,
    reason: str,
) -> None:
    # Given a noncanonical bucket or an explicit incompatible fee currency.
    raw_fee_model = (
        None
        if fee_currency is None
        else {"currency": fee_currency, "parameters": {"commission_min": "1"}}
    )

    # When / Then no currency is guessed and no non-HKD HK schedule is accepted.
    with pytest.raises(numeric.PortfolioRequestError) as caught:
        numeric.parse_effective_fee_model(_bucket(market, currency), raw_fee_model)

    assert caught.value.reason == reason
    assert caught.value.bucket_id == market


@pytest.mark.parametrize(
    "raw_fee_model",
    [
        [],
        {},
        {"parameters": []},
        {"parameters": {}},
        {"parameters": {"unknown": "1"}},
        {"parameters": {"commission_min": "1"}, "extra": "0"},
        {"currency": 1, "parameters": {"commission_min": "1"}},
    ],
)
def test_fee_model_shape_and_parameter_names_are_strict(raw_fee_model: JsonValue) -> None:
    # Given a structurally invalid fee model or unknown parameter.
    # When / Then parsing fails rather than silently ignoring a fee input.
    with pytest.raises(numeric.PortfolioRequestError):
        numeric.parse_effective_fee_model(_bucket("us", "USD"), raw_fee_model)


@pytest.mark.parametrize(
    ("market", "currency", "side", "quantity", "price", "expected"),
    [
        ("cn_a", "CNY", "buy", "100", "1421.00", "36.95"),
        ("cn_a", "CNY", "sell", "100", "1425.50", "108.34"),
        ("hk", "HKD", "buy", "100", "417.80", "55.79"),
        ("hk", "HKD", "buy", "100", "405.00", "54.37"),
        ("us", "USD", "buy", "10", "343.46", "0.99"),
        ("us", "USD", "buy", "1000", "343.46", "4.90"),
    ],
)
def test_market_rules_fee_arithmetic_matches_independent_known_good_literals(
    market: Market,
    currency: Currency,
    side: str,
    quantity: str,
    price: str,
    expected: str,
) -> None:
    # Given a default effective model and hand-computed legacy fee vectors.
    model = numeric.parse_effective_fee_model(_bucket(market, currency))

    # When the existing MarketRules primitive receives only Decimal inputs.
    rules = model.market_rules()
    fee = rules.fee(side, Decimal(quantity), Decimal(price))

    # Then the exact legacy result survives without float arithmetic or leakage.
    assert fee == Decimal(expected)
    assert numeric.canonical_decimal(fee, numeric.MONEY_SPEC) == expected
    assert all(type(value) is Decimal for value in rules.effective_fee_model.values())


@pytest.mark.parametrize(
    ("market", "currency", "expected_fee"),
    [("cn_a", "CNY", "36.95"), ("hk", "HKD", "55.79"), ("us", "USD", "0.99")],
)
def test_checked_in_golden_inputs_reproduce_the_same_decimal_fees(
    market: Market, currency: Currency, expected_fee: str
) -> None:
    # Given the immutable golden input decoded directly into Decimal values.
    path = Path(__file__).parent / "fixtures" / "paper_trade" / "golden" / f"{market}_orders_single_day.json"
    document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    fill = document["fills"][0]

    # When the parsed default model prices that golden fill through MarketRules.
    model = numeric.parse_effective_fee_model(_bucket(market, currency))
    fee = model.market_rules().fee(fill["side"], fill["qty"], fill["price"])

    # Then both the golden and independent literal pin the exact Decimal result.
    assert fill["fee"] == Decimal(expected_fee)
    assert fee == fill["fee"] == Decimal(expected_fee)
