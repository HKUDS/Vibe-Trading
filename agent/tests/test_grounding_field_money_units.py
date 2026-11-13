"""Explicit monetary field units survive grounding without licensing guesses."""

import json

import pytest

from evals.grounding import GroundingLedger
from evals.grounding.evidence import _field_money_unit


@pytest.mark.parametrize(
    "suffix,unit,currency,scale",
    [("usd_bn", "billion", "USD", 1e9),
     ("usd_million", "million", "USD", 1e6),
     ("eur_mn", "million", "EUR", 1e6),
     ("cny_k", "thousand", "CNY", 1e3),
     ("USD_BN", "billion", "USD", 1e9)],
)
def test_explicit_field_units_preserve_currency_scale_and_reference(
    tmp_path, suffix, unit, currency, scale
):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Summarize AAPL's filing")
    field = f"revenue_{suffix}"
    other = f"earnings_{suffix}"
    ledger.ingest_tool_result(
        tool_name="get_sec_filings", arguments={"symbol": "AAPL"},
        result=json.dumps({"data": {field: 400.0, other: 20.0}}),
        call_id="f1", success=True,
    )
    record = next(r for r in ledger._evidence if r.field == f"data.{field}")
    assert record.value == 400.0 * scale
    assert record.currency == currency
    assert record.value_scale == scale

    def validate(value, stated_unit, stated_currency, ref):
        return ledger.validate_final_answer(
            f"AAPL.US reported revenue of {value} {stated_unit} {stated_currency}."
            f"\n```figures\n{value} | observed | revenue | {ref}\n```"
        )

    result = validate("400.0", unit, currency, f"f1::{field}")
    assert result.valid, result.issues
    assert not validate("401.0", unit, currency, f"f1::{field}").valid
    assert not validate("400.0", "", currency, f"f1::{field}").valid
    assert not validate("400.0", unit, "JPY", f"f1::{field}").valid
    assert not validate("400.0", unit, currency, f"f1::{other}").valid
    assert not validate("400.0", unit, currency, f"wrong_call::{field}").valid
    assert not ledger.validate_final_answer(
        f"AAPL.US reported revenue of 400.0 {unit} {currency}."
    ).valid
    # A money amount cannot become a percentage through a scoped field ref.
    assert not ledger.validate_final_answer(
        f"AAPL.US return was {400.0 * scale:.1f}%."
        f"\n```figures\n{400.0 * scale:.1f}% | observed | return | f1::{field}\n```"
    ).valid


@pytest.mark.parametrize("field", ["revenue_bn", "revenue_usd", "revenue_xyz_bn",
                                   "revenue_usd_bn_estimate", "revenue_usd_billionaires"])
def test_ambiguous_field_units_are_not_inferred(field):
    assert _field_money_unit(f"data.{field}") == (None, 1.0)
