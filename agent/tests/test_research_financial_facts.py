"""Contract tests for portable financial facts in versioned research content."""

import json

import pytest

from src.research_artifacts.financial_facts import (
    decode_financial_facts,
    encode_financial_facts,
    validate_financial_facts,
)


def example_fact(**overrides):
    fact = {
        "metric": "revenue",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "period_kind": "duration",
        "scope": "consolidated",
        "definition": "Revenue under reporting GAAP",
        "value": 1998,
        "currency": "USD",
        "unit": "millions",
        "source_id": "filing-2025",
        "source_section": "Consolidated statement of income",
        "source_page": None,
        "verification_status": "verified",
    }
    fact.update(overrides)
    return fact


def example_document(*facts):
    return {
        "schema_version": "financial-facts/v1",
        "subject": "Example Corporation",
        "sources": [{"id": "filing-2025", "url": "https://example.org/filing"}],
        "facts": list(facts),
    }


def test_round_trip_preserves_numeric_fact_and_provenance():
    document = example_document(example_fact())
    assert decode_financial_facts(encode_financial_facts(document)) == document


def test_missing_value_must_not_be_marked_verified():
    with pytest.raises(ValueError, match="require a numeric value"):
        validate_financial_facts(example_document(example_fact(value=None)))


def test_unavailable_never_contains_a_number():
    with pytest.raises(ValueError, match="must have null value"):
        validate_financial_facts(
            example_document(example_fact(verification_status="unavailable"))
        )


def test_unavailable_can_preserve_missing_source():
    fact = example_fact(
        value=None,
        verification_status="unavailable",
        source_id=None,
        source_section=None,
        currency=None,
        unit=None,
    )
    assert validate_financial_facts(example_document(fact))["facts"][0] == fact


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "123"])
def test_invalid_numeric_values_rejected(value):
    with pytest.raises(ValueError, match="finite numeric"):
        validate_financial_facts(example_document(example_fact(value=value)))


def test_verified_requires_units_and_source():
    with pytest.raises(ValueError, match="provenance and units"):
        validate_financial_facts(example_document(example_fact(source_section=None)))


@pytest.mark.parametrize(
    "metric,unit,value",
    [
        ("shares_outstanding", "shares", 393_000_000),
        ("weighted_average_shares", "million shares", 393),
        ("operating_margin", "%", 24.5),
        ("return_on_equity", "ratio", 0.18),
        ("leverage", "times", 2.1),
    ],
)
def test_verified_non_monetary_units_allow_null_currency(metric, unit, value):
    fact = example_fact(metric=metric, unit=unit, value=value, currency=None)
    result = decode_financial_facts(encode_financial_facts(example_document(fact)))
    assert result["facts"][0] == fact


@pytest.mark.parametrize(
    "unit",
    ["millions", "thousands", "USD millions", "unknown reporting units"],
)
def test_verified_monetary_or_ambiguous_units_require_currency(unit):
    with pytest.raises(ValueError, match="require currency"):
        validate_financial_facts(
            example_document(example_fact(unit=unit, currency=None))
        )


def test_non_monetary_fact_still_requires_source_and_unit():
    with pytest.raises(ValueError, match="provenance and units"):
        validate_financial_facts(
            example_document(
                example_fact(
                    metric="shares_outstanding",
                    unit="shares",
                    currency=None,
                    source_id=None,
                )
            )
        )


def test_period_kind_is_explicit_for_stocks_and_flows():
    with pytest.raises(ValueError, match="period_kind"):
        validate_financial_facts(example_document(example_fact(period_kind="quarter")))


def test_narrative_research_is_not_misread_as_facts():
    with pytest.raises(ValueError, match="not a financial facts JSON envelope"):
        decode_financial_facts("Research summary: earnings increased.")


def test_unknown_schema_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        decode_financial_facts(json.dumps({"schema_version": "financial-facts/v2"}))


def test_existing_research_store_round_trip(tmp_path):
    from src.research_artifacts.store import ResearchArtifactStore

    store = ResearchArtifactStore(db_path=tmp_path / "research.sqlite")
    try:
        content = encode_financial_facts(example_document(example_fact()))
        saved = store.save(
            content=content,
            data_as_of="2026-11-04",
            subject="Example Corporation",
            universe="EXAMPLE",
            verification_status="partial",
            completeness="partial",
        )
        revision = store.get_revision(saved.revision.revision_id)
        assert revision is not None
        assert decode_financial_facts(revision.content)["facts"][0]["value"] == 1998
        assert revision.verification_status == "partial"
    finally:
        store.close()


@pytest.mark.parametrize(
    "start,end",
    [
        ("banana", "2025-12-31"),
        ("2025-12-31", "2025-01-01"),
        ("2025-01-01", "2025-99-99"),
    ],
)
def test_bad_duration_dates_rejected(start, end):
    with pytest.raises(ValueError, match="ISO date|invalid duration"):
        validate_financial_facts(
            example_document(example_fact(period_start=start, period_end=end))
        )


def test_balance_sheet_fact_requires_instant_date():
    with pytest.raises(ValueError, match="as_of_date"):
        validate_financial_facts(
            example_document(
                example_fact(
                    metric="cash",
                    period_kind="instant",
                    period_start=None,
                    period_end=None,
                )
            )
        )


def test_instant_fact_with_as_of_date():
    fact = example_fact(
        metric="cash",
        period_kind="instant",
        period_start=None,
        period_end=None,
        as_of_date="2025-12-31",
    )
    assert validate_financial_facts(example_document(fact))["facts"][0] == fact


def test_duplicate_metric_period_scope_units_rejected_even_if_value_differs():
    with pytest.raises(ValueError, match="duplicate financial fact identity"):
        validate_financial_facts(
            example_document(example_fact(value=100), example_fact(value=200))
        )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://example.org/filing",
        "https://user:password@example.org/filing",
    ],
)
def test_untrusted_source_urls_rejected(url):
    document = example_document(example_fact())
    document["sources"][0]["url"] = url
    with pytest.raises(ValueError, match="HTTPS URL"):
        validate_financial_facts(document)


def test_source_must_exist_in_envelope():
    with pytest.raises(ValueError, match="source_id not found"):
        validate_financial_facts(example_document(example_fact(source_id="missing")))


def test_empty_fact_collection_rejected():
    with pytest.raises(ValueError, match="between 1 and 1000"):
        validate_financial_facts(example_document())


def test_duplicate_source_ids_rejected():
    document = example_document(example_fact())
    document["sources"].append(dict(document["sources"][0]))
    with pytest.raises(ValueError, match="duplicate source id"):
        validate_financial_facts(document)
