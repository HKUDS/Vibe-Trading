"""Unit tests for the entity and irregular cash-flow spine."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime

import pytest

from src.entities.cashflow import (
    CashFlow,
    CashFlowSeries,
    CurrencyMismatchError,
    normalize_kind,
)
from src.entities.ingest import CashFlowIngestError, load_cashflows
from src.entities.cashflow import FxRate, FxRateTable, MissingExchangeRateError, translate_cashflows
from src.entities.ingest import EntityPanel, PanelIngestError, PanelObservation, load_panel
from src.entities.models import (
    Bond,
    Entity,
    EntityType,
    Fund,
    FundStructure,
    Instrument,
    Security,
    SecurityType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flow(day: int, amount: float, kind: str = "coupon", currency: str = "USD") -> CashFlow:
    """Build a CashFlow on 2024-01-<day> for terse test construction."""
    return CashFlow(date=date(2024, 1, day), amount=amount, kind=kind, currency=currency)


def _write_csv(tmp_path, name: str, text: str, encoding: str = "utf-8"):
    """Write a fixture file and return its path."""
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


# ---------------------------------------------------------------------------
# CashFlow construction and immutability
# ---------------------------------------------------------------------------


def test_cashflow_constructs_and_normalizes():
    flow = CashFlow(date="2024-03-05", amount=-1000, kind="Capital Call", currency=" usd ")
    assert flow.date == date(2024, 3, 5)
    assert flow.amount == -1000.0
    assert isinstance(flow.amount, float)
    assert flow.kind == "capital_call"
    assert flow.currency == "USD"


def test_cashflow_accepts_datetime_and_truncates_to_date():
    flow = CashFlow(
        date=datetime(2024, 3, 5, 16, 30), amount=10.0, kind="coupon", currency="USD"
    )
    assert flow.date == date(2024, 3, 5)
    assert not isinstance(flow.date, datetime)


def test_cashflow_is_immutable():
    flow = _flow(1, 100.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        flow.amount = 999.0


def test_cashflow_metadata_is_read_only():
    flow = CashFlow(
        date=date(2024, 1, 1),
        amount=100.0,
        kind="coupon",
        currency="USD",
        metadata={"note": "semi-annual"},
    )
    assert flow.metadata["note"] == "semi-annual"
    with pytest.raises(TypeError):
        flow.metadata["note"] = "tampered"


def test_cashflow_metadata_copies_input_so_later_mutation_cannot_leak_in():
    source = {"note": "original"}
    flow = CashFlow(
        date=date(2024, 1, 1),
        amount=100.0,
        kind="coupon",
        currency="USD",
        metadata=source,
    )
    source["note"] = "changed after construction"
    assert flow.metadata["note"] == "original"


def test_cashflow_rejects_missing_currency():
    with pytest.raises(ValueError, match="currency is required"):
        CashFlow(date=date(2024, 1, 1), amount=1.0, kind="coupon", currency="")


def test_cashflow_rejects_non_finite_amount():
    with pytest.raises(ValueError, match="finite"):
        CashFlow(date=date(2024, 1, 1), amount=float("nan"), kind="coupon", currency="USD")


def test_cashflow_rejects_ambiguous_date_string():
    with pytest.raises(ValueError, match="ISO-8601"):
        CashFlow(date="03/04/2024", amount=1.0, kind="coupon", currency="USD")


# ---------------------------------------------------------------------------
# Sign convention -- enforced centrally, not by each caller
# ---------------------------------------------------------------------------


def test_sign_convention_rejects_positive_capital_call():
    with pytest.raises(ValueError, match="negative"):
        CashFlow(date=date(2024, 1, 1), amount=1000.0, kind="capital_call", currency="USD")


def test_sign_convention_rejects_negative_distribution():
    with pytest.raises(ValueError, match="positive"):
        CashFlow(date=date(2024, 1, 1), amount=-500.0, kind="distribution", currency="USD")


def test_sign_convention_applies_after_kind_normalization():
    """'Capital Call' must be checked as capital_call, not treated as custom."""
    with pytest.raises(ValueError, match="negative"):
        CashFlow(date=date(2024, 1, 1), amount=1000.0, kind="Capital Call", currency="USD")


def test_custom_kind_carries_no_sign_constraint():
    """The documented escape hatch: name the flow, do not disable the check."""
    clawback = CashFlow(
        date=date(2024, 1, 1),
        amount=-250.0,
        kind="recallable_distribution",
        currency="USD",
    )
    assert clawback.amount == -250.0


def test_zero_amount_is_allowed_for_a_signed_kind():
    waived = CashFlow(date=date(2024, 1, 1), amount=0.0, kind="fee", currency="USD")
    assert waived.amount == 0.0


def test_normalize_kind_collapses_separators():
    assert normalize_kind("  Capital -- Call ") == "capital_call"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_series_orders_by_date():
    series = CashFlowSeries(flows=(_flow(10, 1.0), _flow(2, 2.0), _flow(7, 3.0)))
    assert series.dates() == (date(2024, 1, 2), date(2024, 1, 7), date(2024, 1, 10))
    assert series.amounts() == (2.0, 3.0, 1.0)


def test_series_ordering_is_stable_within_a_date():
    first = _flow(5, -100.0, kind="capital_call")
    second = _flow(5, 400.0, kind="distribution")
    series = CashFlowSeries(flows=(first, second))
    assert list(series) == [first, second]


def test_series_is_immutable():
    series = CashFlowSeries(flows=(_flow(1, 1.0),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        series.flows = ()
    assert isinstance(series.flows, tuple)


# ---------------------------------------------------------------------------
# Currency coherence
# ---------------------------------------------------------------------------


def test_series_rejects_mixed_currencies():
    with pytest.raises(CurrencyMismatchError, match="multiple currencies"):
        CashFlowSeries(flows=(_flow(1, 1.0, currency="USD"), _flow(2, 1.0, currency="EUR")))


def test_series_infers_currency_from_its_flows():
    series = CashFlowSeries(flows=(_flow(1, 1.0, currency="jpy"),))
    assert series.currency == "JPY"


def test_series_rejects_declared_currency_contradicting_the_flows():
    with pytest.raises(CurrencyMismatchError, match="does not match"):
        CashFlowSeries(flows=(_flow(1, 1.0, currency="USD"),), currency="EUR")


def test_pre_translated_allows_mixed_currencies_when_told_explicitly():
    series = CashFlowSeries(
        flows=(_flow(1, 1.0, currency="USD"), _flow(2, 2.0, currency="EUR")),
        currency="USD",
        pre_translated=True,
    )
    assert series.currency == "USD"
    assert series.total() == pytest.approx(3.0)


def test_pre_translated_without_a_reporting_currency_is_refused():
    with pytest.raises(ValueError, match="reporting currency must be named"):
        CashFlowSeries(
            flows=(_flow(1, 1.0, currency="USD"), _flow(2, 2.0, currency="EUR")),
            pre_translated=True,
        )


# ---------------------------------------------------------------------------
# filter / between / total
# ---------------------------------------------------------------------------


def test_filter_by_single_and_multiple_kinds():
    series = CashFlowSeries(
        flows=(
            _flow(1, -100.0, kind="capital_call"),
            _flow(2, 50.0, kind="distribution"),
            _flow(3, 10.0, kind="coupon"),
        )
    )
    assert len(series.filter(kind="coupon")) == 1
    assert series.filter(kind="Capital Call").amounts() == (-100.0,)
    assert len(series.filter(kind=["coupon", "distribution"])) == 2


def test_filter_preserves_currency_even_when_it_empties_the_series():
    series = CashFlowSeries(flows=(_flow(1, 10.0, currency="EUR"),))
    empty = series.filter(kind="capital_call")
    assert empty.is_empty
    assert empty.currency == "EUR"


def test_between_is_inclusive_on_both_ends():
    series = CashFlowSeries(flows=(_flow(1, 1.0), _flow(5, 2.0), _flow(9, 3.0)))
    window = series.between(date(2024, 1, 5), date(2024, 1, 9))
    assert window.amounts() == (2.0, 3.0)


def test_between_accepts_open_ends_and_iso_strings():
    series = CashFlowSeries(flows=(_flow(1, 1.0), _flow(5, 2.0), _flow(9, 3.0)))
    assert series.between(end="2024-01-05").amounts() == (1.0, 2.0)
    assert series.between(start="2024-01-05").amounts() == (2.0, 3.0)
    assert series.between().amounts() == (1.0, 2.0, 3.0)


def test_between_rejects_a_reversed_window():
    series = CashFlowSeries(flows=(_flow(1, 1.0),))
    with pytest.raises(ValueError, match="is after end"):
        series.between(date(2024, 1, 9), date(2024, 1, 1))


def test_total_sums_signed_amounts():
    series = CashFlowSeries(
        flows=(_flow(1, -1000.0, kind="capital_call"), _flow(2, 250.0, kind="distribution"))
    )
    assert series.total() == pytest.approx(-750.0)


def test_total_excludes_nav_marks_by_default():
    series = CashFlowSeries(
        flows=(
            _flow(1, -1000.0, kind="capital_call"),
            _flow(2, 250.0, kind="distribution"),
            _flow(3, 900.0, kind="nav"),
        )
    )
    assert series.total() == pytest.approx(-750.0)
    assert series.total(include_valuations=True) == pytest.approx(150.0)


def test_nav_flow_is_flagged_as_a_valuation():
    assert _flow(1, 900.0, kind="nav").is_valuation
    assert not _flow(1, 900.0, kind="distribution").is_valuation


# ---------------------------------------------------------------------------
# Empty series behaves sanely
# ---------------------------------------------------------------------------


def test_empty_series_is_sane():
    series = CashFlowSeries()
    assert len(series) == 0
    assert series.is_empty
    assert series.dates() == ()
    assert series.amounts() == ()
    assert series.kinds() == ()
    assert series.total() == 0.0
    assert series.total(include_valuations=True) == 0.0
    assert list(series) == []
    assert series.currency is None
    assert series.filter(kind="coupon").is_empty
    assert series.between("2024-01-01", "2024-12-31").is_empty


def test_empty_series_mean_style_arithmetic_does_not_divide_by_zero():
    """Guard the obvious downstream footgun: total over an empty series."""
    series = CashFlowSeries()
    count = len(series)
    average = series.total() / count if count else 0.0
    assert average == 0.0


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def test_load_cashflows_reads_a_fixture_csv(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "date,amount,kind,currency\n"
        "2024-03-31,-1000.00,capital_call,USD\n"
        "2024-01-15,-500.00,capital_call,USD\n"
        "2024-06-30,250.00,distribution,USD\n",
    )
    series = load_cashflows(path)
    assert len(series) == 3
    assert series.currency == "USD"
    assert series.dates() == (date(2024, 1, 15), date(2024, 3, 31), date(2024, 6, 30))
    assert series.total() == pytest.approx(-1250.0)
    assert series.filter(kind="distribution").total() == pytest.approx(250.0)


def test_load_cashflows_preserves_unmapped_columns_as_metadata(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "date,amount,kind,currency,notice_id,fund\n"
        "2024-03-31,-1000.00,capital_call,USD,NOT-17,Fund II\n",
    )
    series = load_cashflows(path)
    flow = series[0]
    assert flow.metadata["notice_id"] == "NOT-17"
    assert flow.metadata["fund"] == "Fund II"
    assert flow.metadata["source_row"] == 1
    assert flow.metadata["source_file"] == str(path)


def test_load_cashflows_missing_required_column_raises_not_none(tmp_path):
    path = _write_csv(
        tmp_path, "flows.csv", "date,kind,currency\n2024-03-31,coupon,USD\n"
    )
    with pytest.raises(CashFlowIngestError) as excinfo:
        load_cashflows(path)
    message = str(excinfo.value)
    assert "amount" in message
    assert "date, kind, currency" in message  # tells the user what it did see


def test_load_cashflows_missing_currency_is_an_error_not_a_default(tmp_path):
    path = _write_csv(tmp_path, "flows.csv", "date,amount,kind\n2024-03-31,10,coupon\n")
    with pytest.raises(CashFlowIngestError, match="currency"):
        load_cashflows(path)


def test_load_cashflows_currency_argument_substitutes_for_a_missing_column(tmp_path):
    path = _write_csv(tmp_path, "flows.csv", "date,amount,kind\n2024-03-31,10,coupon\n")
    series = load_cashflows(path, currency="EUR")
    assert series.currency == "EUR"
    assert series[0].currency == "EUR"


def test_load_cashflows_missing_kind_is_an_error_unless_defaulted(tmp_path):
    path = _write_csv(tmp_path, "flows.csv", "date,amount,currency\n2024-03-31,10,USD\n")
    with pytest.raises(CashFlowIngestError, match="default_kind"):
        load_cashflows(path)
    series = load_cashflows(path, default_kind="coupon")
    assert series[0].kind == "coupon"


def test_load_cashflows_explicit_column_mapping(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "Payment Date,Net Cash,Description\n2024-03-31,-1000,Drawdown 4\n",
    )
    series = load_cashflows(
        path,
        columns={"date": "Payment Date", "amount": "Net Cash"},
        currency="USD",
        default_kind="capital_call",
    )
    assert series[0].amount == -1000.0
    assert series[0].metadata["Description"] == "Drawdown 4"


def test_load_cashflows_rejects_a_mapping_to_an_absent_column(tmp_path):
    path = _write_csv(tmp_path, "flows.csv", "date,amount,currency\n2024-03-31,10,USD\n")
    with pytest.raises(CashFlowIngestError, match="not in the file"):
        load_cashflows(path, columns={"amount": "Nope"}, default_kind="coupon")


def test_load_cashflows_header_aliases_are_matched_case_insensitively(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "Value Date,Cash Flow,Type,CCY\n2024-03-31,-1000,Capital Call,usd\n",
    )
    series = load_cashflows(path)
    assert series[0].kind == "capital_call"
    assert series[0].currency == "USD"


def test_load_cashflows_parses_accounting_negatives_and_separators(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        'date,amount,kind,currency\n2024-03-31,"(1,234.50)",capital_call,USD\n',
    )
    series = load_cashflows(path)
    assert series[0].amount == pytest.approx(-1234.50)


def test_load_cashflows_reads_european_grouping_without_mangling_it(tmp_path):
    """1.234,50 must be 1234.50, not 1.2345."""
    path = _write_csv(
        tmp_path,
        "flows.csv",
        'date,amount,kind,currency\n2024-03-31,"1.234,50",coupon,USD\n',
    )
    assert load_cashflows(path)[0].amount == pytest.approx(1234.50)


def test_load_cashflows_refuses_an_ambiguous_single_comma(tmp_path):
    """'1,234' is 1234 in a US export and 1.234 in a European one."""
    path = _write_csv(
        tmp_path, "flows.csv", 'date,amount,kind,currency\n2024-03-31,"1,234",coupon,USD\n'
    )
    with pytest.raises(CashFlowIngestError, match="decimal_separator"):
        load_cashflows(path)
    assert load_cashflows(path, decimal_separator=".")[0].amount == pytest.approx(1234.0)
    assert load_cashflows(path, decimal_separator=",")[0].amount == pytest.approx(1.234)


def test_load_cashflows_rejects_an_invalid_decimal_separator(tmp_path):
    path = _write_csv(
        tmp_path, "flows.csv", "date,amount,kind,currency\n2024-03-31,10,coupon,USD\n"
    )
    with pytest.raises(ValueError, match="decimal_separator must be"):
        load_cashflows(path, decimal_separator=";")


def test_load_cashflows_strips_currency_symbols_and_nbsp(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        'date,amount,kind,currency\n2024-03-31,"$ 1 234.50",coupon,USD\n',
    )
    assert load_cashflows(path)[0].amount == pytest.approx(1234.50)


def test_load_cashflows_invert_sign_restores_the_convention(tmp_path):
    """A file reporting calls as positive is corrected at the boundary."""
    path = _write_csv(
        tmp_path, "flows.csv", "date,amount,kind,currency\n2024-03-31,1000,capital_call,USD\n"
    )
    with pytest.raises(CashFlowIngestError, match="negative"):
        load_cashflows(path)
    series = load_cashflows(path, invert_sign=True)
    assert series[0].amount == -1000.0


def test_load_cashflows_requires_explicit_format_for_non_iso_dates(tmp_path):
    path = _write_csv(
        tmp_path, "flows.csv", "date,amount,kind,currency\n31/03/2024,10,coupon,USD\n"
    )
    with pytest.raises(CashFlowIngestError, match="date_format"):
        load_cashflows(path)
    series = load_cashflows(path, date_format="%d/%m/%Y")
    assert series[0].date == date(2024, 3, 31)


def test_load_cashflows_blank_amount_is_an_error_not_zero(tmp_path):
    path = _write_csv(
        tmp_path, "flows.csv", "date,amount,kind,currency\n2024-03-31,,coupon,USD\n"
    )
    with pytest.raises(CashFlowIngestError, match="blank"):
        load_cashflows(path)


def test_load_cashflows_reports_the_offending_row_number(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "date,amount,kind,currency\n"
        "2024-01-31,10,coupon,USD\n"
        "2024-02-29,oops,coupon,USD\n",
    )
    with pytest.raises(CashFlowIngestError, match="row 2"):
        load_cashflows(path)


def test_load_cashflows_missing_file_raises_ingest_error(tmp_path):
    with pytest.raises(CashFlowIngestError, match="not found"):
        load_cashflows(tmp_path / "absent.csv")


def test_load_cashflows_unsupported_suffix_is_explicit(tmp_path):
    path = _write_csv(tmp_path, "flows.xlsx", "date,amount\n")
    with pytest.raises(CashFlowIngestError, match="unsupported file type"):
        load_cashflows(path, currency="USD", default_kind="coupon")


def test_load_cashflows_header_only_file_yields_an_empty_series(tmp_path):
    path = _write_csv(tmp_path, "flows.csv", "date,amount,kind,currency\n")
    series = load_cashflows(path, currency="USD")
    assert series.is_empty
    assert series.total() == 0.0


def test_load_cashflows_mixed_currency_file_is_refused(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "date,amount,kind,currency\n"
        "2024-03-31,100,coupon,USD\n"
        "2024-04-30,100,coupon,EUR\n",
    )
    with pytest.raises(CurrencyMismatchError):
        load_cashflows(path)


def test_load_cashflows_tsv_delimiter_inferred_from_suffix(tmp_path):
    path = _write_csv(
        tmp_path, "flows.tsv", "date\tamount\tkind\tcurrency\n2024-03-31\t10\tcoupon\tUSD\n"
    )
    series = load_cashflows(path)
    assert series[0].amount == 10.0


def test_load_cashflows_skips_trailing_blank_line(tmp_path):
    path = _write_csv(
        tmp_path,
        "flows.csv",
        "date,amount,kind,currency\n2024-03-31,10,coupon,USD\n,,,\n",
    )
    assert len(load_cashflows(path)) == 1


# ---------------------------------------------------------------------------
# Entity / instrument models
# ---------------------------------------------------------------------------


def test_entity_constructs_and_is_immutable():
    entity = Entity(entity_id="LEI-123", name="Acme Capital", entity_type="manager")
    assert entity.entity_type is EntityType.MANAGER
    with pytest.raises(dataclasses.FrozenInstanceError):
        entity.name = "Other"


def test_entity_rejects_blank_id_and_unknown_type():
    with pytest.raises(ValueError, match="entity_id is required"):
        Entity(entity_id="   ")
    with pytest.raises(ValueError, match="unknown entity_type"):
        Entity(entity_id="E1", entity_type="wizard")


def test_entity_cannot_be_its_own_parent():
    with pytest.raises(ValueError, match="own parent"):
        Entity(entity_id="E1", parent_id="E1")


def test_instrument_requires_currency_and_normalizes_it():
    instrument = Instrument(instrument_id="X1", currency="usd")
    assert instrument.currency == "USD"
    with pytest.raises(ValueError, match="currency is required"):
        Instrument(instrument_id="X1", currency="")


def test_instrument_accepts_a_crypto_quote_asset():
    """Currency is not constrained to three letters; USDT is real here."""
    assert Instrument(instrument_id="BTC-USDT", currency="USDT").currency == "USDT"


def test_security_carries_venue_details():
    issuer = Entity(entity_id="CIK-320193", name="Apple Inc.")
    security = Security(
        instrument_id="US0378331005",
        currency="USD",
        symbol="AAPL",
        exchange="XNAS",
        security_type="etf",
        issuer=issuer,
    )
    assert security.security_type is SecurityType.ETF
    assert security.issuer.name == "Apple Inc."
    assert isinstance(security, Instrument)


def test_fund_validates_its_economics():
    fund = Fund(
        instrument_id="FUND-II",
        currency="EUR",
        vintage_year=2021,
        structure="closed_end",
        commitment=25_000_000,
        management_fee_rate=0.02,
    )
    assert fund.structure is FundStructure.CLOSED_END
    assert fund.commitment == 25_000_000.0
    with pytest.raises(ValueError, match="non-negative"):
        Fund(instrument_id="F", currency="EUR", commitment=-1)
    with pytest.raises(ValueError, match="decimal fraction"):
        Fund(instrument_id="F", currency="EUR", management_fee_rate=2.0)
    with pytest.raises(ValueError, match="vintage_year"):
        Fund(instrument_id="F", currency="EUR", vintage_year=12)


def test_bond_validates_coupon_and_maturity():
    bond = Bond(
        instrument_id="US912828",
        currency="USD",
        face_value=1000,
        coupon_rate=0.045,
        coupon_frequency=2,
        inception_date="2020-01-15",
        maturity_date="2030-01-15",
    )
    assert bond.maturity_date == date(2030, 1, 15)
    assert bond.coupon_rate == pytest.approx(0.045)

    with pytest.raises(ValueError, match="percentage"):
        Bond(instrument_id="B", currency="USD", coupon_rate=4.5)
    with pytest.raises(ValueError, match="face_value must be positive"):
        Bond(instrument_id="B", currency="USD", face_value=0)
    with pytest.raises(ValueError, match="zero-coupon"):
        Bond(instrument_id="B", currency="USD", coupon_rate=0.05, coupon_frequency=0)
    with pytest.raises(ValueError, match="precedes inception"):
        Bond(
            instrument_id="B",
            currency="USD",
            inception_date="2030-01-01",
            maturity_date="2020-01-01",
        )


def test_zero_coupon_bond_is_valid():
    bond = Bond(instrument_id="Z", currency="USD", coupon_rate=0.0, coupon_frequency=0)
    assert bond.coupon_frequency == 0


# ---------------------------------------------------------------------------
# The parallel-path guarantee
# ---------------------------------------------------------------------------


def test_spine_does_not_widen_the_bar_price_panel():
    """A nav must never become a column a bar engine could price as a close."""
    from backtest.runner import _PRICE_PANEL_COLUMNS, _VALID_INTERVALS

    assert _PRICE_PANEL_COLUMNS == ("open", "high", "low", "close", "volume", "vwap", "amount")
    assert "nav" not in _PRICE_PANEL_COLUMNS
    assert _VALID_INTERVALS == {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}


def test_series_is_not_a_dataframe_and_exposes_no_bar_fields():
    series = CashFlowSeries(flows=(_flow(1, 100.0, kind="nav"),))
    assert not hasattr(series, "close")
    assert not hasattr(series[0], "close")


# ---------------------------------------------------------------------------
# FX translation
# ---------------------------------------------------------------------------


def test_translate_cashflows_hand_calculated_multi_currency():
    """Two flows, different currency and date, checked against a hand calc."""
    flow_eur = CashFlow(
        date=date(2024, 1, 10), amount=1000.0, kind="distribution", currency="EUR"
    )
    flow_jpy = CashFlow(
        date=date(2024, 2, 15), amount=-2000.0, kind="capital_call", currency="JPY"
    )
    table = FxRateTable.from_rates(
        [
            FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 10), rate=1.10),
            FxRate(base_currency="JPY", quote_currency="USD", date=date(2024, 2, 15), rate=0.0067),
        ],
        quote_currency="USD",
    )
    series = translate_cashflows([flow_eur, flow_jpy], table)
    assert series.currency == "USD"
    assert series.pre_translated is True
    # Hand calc: 1000 EUR * 1.10 = 1100.0 USD; -2000 JPY * 0.0067 = -13.4 USD
    amounts = {f.metadata["fx_original_currency"]: f.amount for f in series}
    assert amounts["EUR"] == pytest.approx(1100.0, abs=1e-9)
    assert amounts["JPY"] == pytest.approx(-13.4, abs=1e-9)
    assert series.total() == pytest.approx(1100.0 - 13.4, abs=1e-9)


def test_translate_cashflows_uses_each_flows_own_settlement_date_rate_not_period_end():
    """A period-end rate would silently give 200.0 instead of the correct 100.0."""
    table = FxRateTable.from_rates(
        [
            FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 1), rate=1.0),
            FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 10), rate=2.0),
        ],
        quote_currency="USD",
    )
    early_flow = CashFlow(date=date(2024, 1, 1), amount=100.0, kind="coupon", currency="EUR")
    series = translate_cashflows([early_flow], table)
    assert series[0].amount == pytest.approx(100.0, abs=1e-9)
    assert series[0].amount != pytest.approx(200.0, abs=1e-9)
    assert series[0].metadata["fx_rate_date"] == date(2024, 1, 1)


def test_fx_rate_table_rejects_entry_quoted_against_the_wrong_currency():
    """A reversed-direction quote (base/quote swapped) cannot enter a table
    declared for the other currency -- caught at construction, not silently
    used in the wrong direction.
    """
    reversed_quote = FxRate(
        base_currency="USD", quote_currency="EUR", date=date(2024, 1, 10), rate=0.91
    )
    with pytest.raises(ValueError, match="does not quote against"):
        FxRateTable(quote_currency="USD", rates={("EUR", date(2024, 1, 10)): reversed_quote})


def test_translate_cashflows_reversed_rate_produces_a_grossly_wrong_number():
    """A confused caller who uses the reciprocal (150) instead of the correct
    quote-per-base rate (1/150) does not get a subtly-off number -- they get
    one nobody could mistake for correct.
    """
    flow = CashFlow(date=date(2024, 1, 1), amount=1_000_000.0, kind="distribution", currency="JPY")

    correct_rate = 1 / 150  # 1 JPY = 1/150 USD
    correct_table = FxRateTable.from_rates(
        [FxRate(base_currency="JPY", quote_currency="USD", date=date(2024, 1, 1), rate=correct_rate)],
        quote_currency="USD",
    )
    correct_amount = translate_cashflows([flow], correct_table)[0].amount
    assert correct_amount == pytest.approx(1_000_000.0 / 150, abs=1e-6)

    reversed_table = FxRateTable.from_rates(
        [FxRate(base_currency="JPY", quote_currency="USD", date=date(2024, 1, 1), rate=150.0)],
        quote_currency="USD",
    )
    reversed_amount = translate_cashflows([flow], reversed_table)[0].amount
    assert reversed_amount == pytest.approx(1_000_000.0 * 150, abs=1e-6)
    assert reversed_amount / correct_amount > 20_000  # off by 22,500x


def test_translate_cashflows_missing_rate_raises_explicit_error():
    flow = CashFlow(date=date(2024, 1, 10), amount=1000.0, kind="distribution", currency="EUR")
    table = FxRateTable(quote_currency="USD")
    with pytest.raises(MissingExchangeRateError, match="no EUR/USD rate"):
        translate_cashflows([flow], table)


def test_translate_cashflows_allow_stale_rates_flags_the_reused_quote():
    table = FxRateTable.from_rates(
        [FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 1), rate=1.1)],
        quote_currency="USD",
    )
    flow = CashFlow(date=date(2024, 1, 20), amount=100.0, kind="coupon", currency="EUR")
    with pytest.raises(MissingExchangeRateError):
        translate_cashflows([flow], table)  # off by default

    series = translate_cashflows([flow], table, allow_stale_rates=True)
    result = series[0]
    assert result.amount == pytest.approx(110.0, abs=1e-9)
    assert result.metadata["fx_rate_is_stale"] is True
    assert result.metadata["fx_rate_date"] == date(2024, 1, 1)


def test_translate_cashflows_max_staleness_days_bounds_the_stale_search():
    table = FxRateTable.from_rates(
        [FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 1), rate=1.1)],
        quote_currency="USD",
    )
    flow = CashFlow(date=date(2024, 1, 20), amount=100.0, kind="coupon", currency="EUR")
    with pytest.raises(MissingExchangeRateError, match="within 5 days"):
        translate_cashflows([flow], table, allow_stale_rates=True, max_staleness_days=5)

    series = translate_cashflows([flow], table, allow_stale_rates=True, max_staleness_days=30)
    assert series[0].metadata["fx_rate_is_stale"] is True


def test_fx_rate_rejects_non_positive_rate():
    with pytest.raises(ValueError, match="strictly positive"):
        FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 1), rate=0.0)
    with pytest.raises(ValueError, match="strictly positive"):
        FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 1), rate=-1.5)


def test_fx_rate_table_from_mapping_builds_a_table():
    table = FxRateTable.from_mapping(
        {("EUR", date(2024, 1, 1)): 1.1, ("JPY", date(2024, 1, 1)): 0.0067},
        quote_currency="USD",
    )
    rate, is_stale = table.get_rate("eur", date(2024, 1, 1))
    assert rate.rate == pytest.approx(1.1)
    assert is_stale is False


def test_translate_cashflows_preserves_original_amount_currency_rate_and_date():
    flow = CashFlow(
        date=date(2024, 1, 10),
        amount=1000.0,
        kind="distribution",
        currency="EUR",
        metadata={"note": "Q1 distribution"},
    )
    table = FxRateTable.from_rates(
        [FxRate(base_currency="EUR", quote_currency="USD", date=date(2024, 1, 10), rate=1.1)],
        quote_currency="USD",
    )
    translated = translate_cashflows([flow], table)[0]
    assert translated.metadata["fx_original_amount"] == 1000.0
    assert translated.metadata["fx_original_currency"] == "EUR"
    assert translated.metadata["fx_rate"] == pytest.approx(1.1)
    assert translated.metadata["fx_rate_date"] == date(2024, 1, 10)
    assert translated.metadata["fx_rate_is_stale"] is False
    assert translated.metadata["note"] == "Q1 distribution"  # original metadata kept too


def test_translate_cashflows_same_currency_flow_passes_through_unchanged():
    flow = CashFlow(date=date(2024, 1, 10), amount=250.0, kind="coupon", currency="USD")
    table = FxRateTable(quote_currency="USD")
    translated = translate_cashflows([flow], table)[0]
    assert translated.amount == pytest.approx(250.0)
    assert translated.metadata["fx_rate"] == 1.0
    assert translated.metadata["fx_rate_is_stale"] is False


# ---------------------------------------------------------------------------
# Panel ingestion (load_panel)
# ---------------------------------------------------------------------------


def test_load_panel_long_layout_reads_a_fixture_csv(tmp_path):
    path = _write_csv(
        tmp_path,
        "panel.csv",
        "entity,date,metric,value,currency,unit\n"
        "FUNDA,2024-01-01,nav,100.5,USD,USD\n"
        "FUNDA,2024-02-01,nav,101.2,USD,USD\n"
        "FUNDB,2024-01-01,nav,50.0,EUR,EUR\n",
    )
    panel = load_panel(path)
    assert len(panel) == 3
    assert panel.entities() == ("FUNDA", "FUNDB")
    assert panel.metrics() == ("nav",)
    observations = list(panel)
    assert observations[0].entity_id == "FUNDA"
    assert observations[0].date == date(2024, 1, 1)
    assert observations[0].value == pytest.approx(100.5)
    assert observations[0].currency == "USD"
    assert observations[0].unit == "USD"


def test_load_panel_infers_wide_dates_rows_layout_and_skips_holes(tmp_path):
    path = _write_csv(
        tmp_path,
        "wide.csv",
        "date,FUNDA,FUNDB\n2024-01-01,100.5,50.0\n2024-02-01,101.2,\n",
    )
    panel = load_panel(path, metric="nav", currency="USD", unit="USD")
    assert len(panel) == 3  # the blank FUNDB@2024-02-01 cell produced no observation
    assert panel.entities() == ("FUNDA", "FUNDB")
    values = {(o.entity_id, o.date): o.value for o in panel}
    assert values[("FUNDA", date(2024, 1, 1))] == pytest.approx(100.5)
    assert ("FUNDB", date(2024, 2, 1)) not in values


def test_load_panel_infers_wide_entities_rows_layout(tmp_path):
    path = _write_csv(
        tmp_path,
        "wide.csv",
        "entity,2024-01-01,2024-02-01\nFUNDA,100.5,101.2\nFUNDB,50.0,\n",
    )
    panel = load_panel(path, metric="nav", currency="USD", unit="USD")
    assert len(panel) == 3
    values = {(o.entity_id, o.date): o.value for o in panel}
    assert values[("FUNDA", date(2024, 2, 1))] == pytest.approx(101.2)
    assert ("FUNDB", date(2024, 2, 1)) not in values


def test_load_panel_missing_value_column_raises_not_none(tmp_path):
    path = _write_csv(
        tmp_path, "panel.csv", "entity,date,metric,currency,unit\nFUNDA,2024-01-01,nav,USD,USD\n"
    )
    with pytest.raises(PanelIngestError, match="value"):
        load_panel(path)


def test_load_panel_missing_currency_is_an_error_not_a_default(tmp_path):
    path = _write_csv(
        tmp_path, "panel.csv", "entity,date,metric,value,unit\nFUNDA,2024-01-01,nav,100,USD\n"
    )
    with pytest.raises(PanelIngestError, match="currency"):
        load_panel(path)


def test_load_panel_missing_unit_is_an_error_not_a_default(tmp_path):
    path = _write_csv(
        tmp_path, "panel.csv", "entity,date,metric,value,currency\nFUNDA,2024-01-01,nav,100,USD\n"
    )
    with pytest.raises(PanelIngestError, match="unit"):
        load_panel(path)


def test_load_panel_ambiguous_header_raises_and_explicit_layout_resolves_it(tmp_path):
    """A header that matches no recognised shape must not be silently guessed."""
    path = _write_csv(tmp_path, "panel.csv", "foo,bar,baz\nFUNDA,2024-01-01,100\n")
    with pytest.raises(PanelIngestError, match="could not infer a panel layout"):
        load_panel(path)

    panel = load_panel(
        path,
        layout="long",
        columns={"entity": "foo", "date": "bar", "value": "baz"},
        metric="nav",
        currency="USD",
        unit="USD",
    )
    assert len(panel) == 1
    obs = list(panel)[0]
    assert obs.entity_id == "FUNDA"
    assert obs.value == pytest.approx(100.0)


def test_load_panel_empty_file_raises_not_none(tmp_path):
    path = _write_csv(tmp_path, "empty.csv", "")
    with pytest.raises(PanelIngestError, match="no header row"):
        load_panel(path)


def test_load_panel_header_only_long_file_yields_an_empty_panel(tmp_path):
    path = _write_csv(tmp_path, "panel.csv", "entity,date,metric,value,currency,unit\n")
    panel = load_panel(path)
    assert panel.is_empty


def test_load_panel_wide_layout_requires_metric_currency_and_unit(tmp_path):
    path = _write_csv(tmp_path, "wide.csv", "date,FUNDA,FUNDB\n2024-01-01,100.5,50.0\n")
    with pytest.raises(PanelIngestError, match="metric"):
        load_panel(path, currency="USD", unit="USD")
    with pytest.raises(PanelIngestError, match="currency"):
        load_panel(path, metric="nav", unit="USD")
    with pytest.raises(PanelIngestError, match="unit"):
        load_panel(path, metric="nav", currency="USD")


def test_load_panel_wide_entities_rows_bad_date_header_raises(tmp_path):
    path = _write_csv(
        tmp_path, "wide.csv", "entity,2024-01-01,not-a-date\nFUNDA,100.5,101.2\n"
    )
    with pytest.raises(PanelIngestError, match="not a usable date"):
        load_panel(path, layout="wide_entities_rows", metric="nav", currency="USD", unit="USD")


def test_load_panel_explicit_column_mapping(tmp_path):
    path = _write_csv(
        tmp_path,
        "panel.csv",
        "Fund,AsOf,Field,Net,CCY,UOM\nFUNDA,2024-01-01,nav,100.5,USD,USD\n",
    )
    panel = load_panel(
        path,
        layout="long",
        columns={
            "entity": "Fund",
            "date": "AsOf",
            "metric": "Field",
            "value": "Net",
            "currency": "CCY",
            "unit": "UOM",
        },
    )
    assert len(panel) == 1
    assert list(panel)[0].value == pytest.approx(100.5)


def test_load_panel_metric_is_normalized(tmp_path):
    path = _write_csv(
        tmp_path,
        "panel.csv",
        "entity,date,metric,value,currency,unit\nFUNDA,2024-01-01,NAV,100,USD,USD\n",
    )
    panel = load_panel(path)
    assert list(panel)[0].metric == "nav"


def test_entity_panel_is_immutable_and_ordered(tmp_path):
    path = _write_csv(
        tmp_path,
        "panel.csv",
        "entity,date,metric,value,currency,unit\n"
        "FUNDB,2024-02-01,nav,1,USD,USD\n"
        "FUNDA,2024-01-01,nav,2,USD,USD\n",
    )
    panel = load_panel(path)
    entities_in_order = [o.entity_id for o in panel]
    assert entities_in_order == ["FUNDA", "FUNDB"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        panel.observations = ()


def test_load_panel_rejects_an_invalid_decimal_separator(tmp_path):
    path = _write_csv(
        tmp_path,
        "panel.csv",
        "entity,date,metric,value,currency,unit\nFUNDA,2024-01-01,nav,100,USD,USD\n",
    )
    with pytest.raises(ValueError, match="decimal_separator must be"):
        load_panel(path, decimal_separator=";")


def test_load_panel_rejects_an_invalid_layout_value(tmp_path):
    path = _write_csv(
        tmp_path,
        "panel.csv",
        "entity,date,metric,value,currency,unit\nFUNDA,2024-01-01,nav,100,USD,USD\n",
    )
    with pytest.raises(PanelIngestError, match="layout must be one of"):
        load_panel(path, layout="sideways")


def test_panel_observation_is_not_a_bar_and_exposes_no_ohlc_fields():
    obs = PanelObservation(
        entity_id="FUNDA", date=date(2024, 1, 1), metric="nav", value=100.0,
        currency="USD", unit="USD",
    )
    assert not hasattr(obs, "close")
    assert not hasattr(obs, "open")


def test_panel_path_does_not_touch_the_bar_price_panel_gate():
    """Same architectural guarantee as CashFlowSeries: the panel ingest path
    must never widen what a bar engine will accept as a price column.
    """
    from backtest.runner import _PRICE_PANEL_COLUMNS, _VALID_INTERVALS

    assert _PRICE_PANEL_COLUMNS == ("open", "high", "low", "close", "volume", "vwap", "amount")
    assert "nav" not in _PRICE_PANEL_COLUMNS
    assert _VALID_INTERVALS == {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}
