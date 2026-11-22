"""Attribution schema/golden tests: optional field, mirror identity, hashes.

The packaged contract and its public mirror stay one byte-identical contract
with attribution optional; an archived task-23 document keeps its frozen hash
without attribution, and a new document retains its real attribution across
re-validation. Shared fixtures live in
``paper_trade_portfolio_attribution_helpers``.
"""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio.hash import PortfolioDataHashes, document_hash
from src.tools.paper_trade.portfolio.models import PortfolioResult
from src.tools.paper_trade.portfolio.wire import build_success_payload
from tests.paper_trade_portfolio_attribution_helpers import (
    _LEGACY_EXPLICIT_GOLDEN,
    _MIRROR_SCHEMA,
    _PACKAGED_SCHEMA,
    _TASK23_EXPLICIT_HASH,
    _base_payload,
    _noop_payload,
    _run,
)


def test_schema_mirrors_are_byte_identical_and_keep_attribution_optional() -> None:
    # Then the packaged contract and its public mirror stay one contract.
    assert _PACKAGED_SCHEMA.read_bytes() == _MIRROR_SCHEMA.read_bytes()
    document = json.loads(_PACKAGED_SCHEMA.read_text(encoding="utf-8"))
    analytics = document["schemas"]["result"]["$defs"]["analytics"]
    assert "attribution" in analytics["properties"]
    assert "attribution" not in analytics["required"]

    # And an old-shaped analytics object without attribution still validates.
    public = build_success_payload(_run(_noop_payload()))
    legacy = json.loads(json.dumps(public))
    legacy["analytics"].pop("attribution")
    schema = document["schemas"]["result"]
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(legacy)
    ) == []
    assert PortfolioResult.model_validate(legacy).analytics.attribution is None


def test_task23_benchmark_document_without_attribution_keeps_its_hash() -> None:
    # Given a task-23-era document with a benchmark but no attribution key.
    payload = json.loads(_LEGACY_EXPLICIT_GOLDEN.read_text(encoding="utf-8"))
    payload["analytics"].pop("attribution")
    payload["hashes"]["document_hash"] = _TASK23_EXPLICIT_HASH
    layers = PortfolioDataHashes(
        plan_hash=payload["hashes"]["plan_hash"],
        planning_data_hash=payload["hashes"]["planning_data_hash"],
        execution_data_fingerprint=payload["hashes"]["execution_data_fingerprint"],
    )

    # When the archived document is validated and its hash recomputed...
    document = PortfolioResult.model_validate(payload)
    analytics = document.analytics
    assert analytics is not None

    # Then attribution is not resurrected as null and the archived hash holds.
    assert "attribution" not in analytics.model_fields_set
    assert document_hash(document, layers) == _TASK23_EXPLICIT_HASH
    public = build_success_payload(document)
    assert "attribution" not in public["analytics"]
    assert public["analytics"]["benchmark"] is not None


def test_new_attribution_document_keeps_attribution_and_explicit_benchmark() -> None:
    # Given a new document whose caller declared no benchmark.
    step = _run(_base_payload())
    document = step.document
    dumped = document.model_dump(mode="json", by_alias=True)
    layers = PortfolioDataHashes(
        plan_hash=dumped["hashes"]["plan_hash"],
        planning_data_hash=dumped["hashes"]["planning_data_hash"],
        execution_data_fingerprint=dumped["hashes"]["execution_data_fingerprint"],
    )

    # Then the real attribution is retained and the benchmark is explicit null.
    public = build_success_payload(document)
    assert public["analytics"]["attribution"]["scope"] == "one_day"
    assert "benchmark" in public["analytics"]
    assert public["analytics"]["benchmark"] is None

    # Then re-validating the full document neither drops nor invents attribution.
    reparsed = PortfolioResult.model_validate(dumped)
    redumped = reparsed.model_dump(mode="json", by_alias=True)
    assert redumped["analytics"]["attribution"] == dumped["analytics"]["attribution"]
    assert document_hash(reparsed, layers) == dumped["hashes"]["document_hash"]
