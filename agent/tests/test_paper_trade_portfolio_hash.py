"""Layered, fixed-point JCS provenance tests for pt-v2.0 portfolios."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import pytest

from src.tools.paper_trade.portfolio.data import (BucketMarketData, CalendarCoverage, DataSnapshot,
    PreparedBucketData, PriceBar, PriorMark, prepare_portfolio_data)
from src.tools.paper_trade.portfolio.hash import (PortfolioDataHashes, PortfolioHashInput,
    compute_portfolio_hashes, document_canonical_bytes, document_hash, execution_canonical_bytes,
    plan_canonical_bytes, planning_canonical_bytes)
from src.tools.paper_trade.portfolio.models import (FxConversion, FxSnapshot, JsonObject, MarketSession,
    PortfolioBucket, PortfolioHashes, PortfolioOrder, PortfolioPosition, PortfolioRequest, PortfolioState)
from src.tools.paper_trade.portfolio.numeric import parse_effective_fee_model
from src.tools.paper_trade.portfolio.schema import PortfolioRequestError
from src.tools.paper_trade.portfolio.sessions import resolve_portfolio_sessions
from src.tools.paper_trade.state_hash import engine_fingerprint

AS_OF = datetime(2026, 1, 5, 18, tzinfo=timezone.utc)
DAY = date(2026, 1, 5)
PRIOR = date(2026, 1, 2)
AGENT_ROOT = Path(__file__).resolve().parents[1]
Mutation = Literal["opening", "session", "fx", "conversion", "planning", "planner", "order", "fee", "execution", "rule"]


def _snapshot(day: date, rows: tuple[tuple[str, str], ...], source: str) -> DataSnapshot:
    return DataSnapshot(price_date=day, source=source, as_of=AS_OF,
                        bars=tuple(PriceBar(symbol=symbol, close=close) for symbol, close in rows))


def _request() -> PortfolioRequest:
    return PortfolioRequest(
        tool="paper_trade_step", schema_version="pt-v2.0", mode="portfolio",
        account_id="hash-fixture", base_currency="USD", trade_date=DAY,
        planning_at=AS_OF, valuation_at=datetime(2026, 1, 5, 19, tzinfo=timezone.utc),
        portfolio_state=PortfolioState(buckets=(
            PortfolioBucket(
                bucket_id="cn", market="cn_a", currency="CNY", cash="1000",
                positions=(PortfolioPosition(symbol="600000.SS", qty=10, avg_cost="9.5", currency="CNY"),),
                fee_model={"parameters": {"commission_min": "5"}},
            ),
            PortfolioBucket(
                bucket_id="hk", market="hk", currency="HKD", cash="2000.00",
                positions=(PortfolioPosition(symbol="0700.HK", qty=7, avg_cost="300", currency="HKD"),),
            ),
            PortfolioBucket(bucket_id="us", market="us", currency="USD", cash="3000.00", positions=()),
        )),
        sessions=(
            MarketSession(market="cn_a", status="open", source="cn-calendar", as_of=AS_OF),
            MarketSession(market="hk", status="closed", source="hk-calendar", as_of=AS_OF),
            MarketSession(market="us", status="open", source="us-calendar", as_of=AS_OF),
        ),
        fx_snapshots=(FxSnapshot(
            rate_id="usd-cny", from_currency="USD", to_currency="CNY", rate="7.8",
            as_of=AS_OF, source="caller-fx",
        ),),
        fx_conversions=(FxConversion(rate_id="usd-cny", from_bucket_id="us", to_bucket_id="cn", amount="25"),),
        orders=(
            PortfolioOrder(order_id="cn-1", bucket_id="cn", symbol="600000.SS", currency="CNY", side="buy", qty=10),
            PortfolioOrder(order_id="us-1", bucket_id="us", symbol="AAPL.US", currency="USD", side="buy", qty=2),
        ),
    )


def _material() -> PortfolioHashInput:
    request = _request()
    sessions = resolve_portfolio_sessions(
        request, price_dates={"cn_a": DAY, "hk": DAY, "us": DAY},
    )
    data = prepare_portfolio_data(sessions, (
        BucketMarketData(
            bucket_id="cn", market="cn_a", price_date=DAY,
            planning=_snapshot(PRIOR, (("600000.SS", "9.5"),), "cn-prior"),
            execution=_snapshot(DAY, (("600000.SS", "10.25"),), "cn-target"),
            valuation=_snapshot(DAY, (("600000.SS", "10.5"),), "cn-value"),
            calendar=CalendarCoverage(price_date=DAY, is_open=True, source="snapshot-calendar", as_of=AS_OF),
        ),
        BucketMarketData(
            bucket_id="hk", market="hk", price_date=DAY,
            planning=_snapshot(PRIOR, (("0700.HK", "299.5"),), "hk-prior"),
            execution=_snapshot(DAY, (), "hk-target"),
            valuation=_snapshot(DAY, (), "hk-value"),
            prior_marks=(PriorMark(symbol="0700.HK", price_date=PRIOR, close="300.25", source="hk-mark", as_of=AS_OF),),
        ),
        BucketMarketData(
            bucket_id="us", market="us", price_date=DAY,
            planning=_snapshot(PRIOR, (("AAPL.US", "199.5"),), "us-prior"),
            execution=_snapshot(DAY, (("AAPL.US", "201.25"),), "us-target"),
            valuation=_snapshot(DAY, (("AAPL.US", "201.5"),), "us-value"),
        ),
    ))
    return PortfolioHashInput(
        request=request,
        effective_fee_models=tuple(parse_effective_fee_model(bucket) for bucket in request.portfolio_state.buckets),
        sessions=sessions, data=data, planner_version="pt-planner-v1",
        rules_versions={"cn": "pt-rules-v5", "hk": "pt-rules-v5", "us": "pt-rules-v5"},
    )


def _document() -> JsonObject:
    return {
        "status": "success", "tool": "paper_trade_step", "schema_version": "pt-v2.0",
        "mode": "portfolio", "account_id": "hash-fixture", "base_currency": "USD",
        "trade_date": "2026-01-05", "complete": True, "warnings": [], "fills": [{"qty": 10, "price": "10.250000"}],
        "hashes": {"plan_hash": "0" * 64, "planning_data_hash": "0" * 64, "execution_data_fingerprint": "0" * 64, "document_hash": "0" * 64},
    }


def _data_hashes(hashes: PortfolioHashes) -> PortfolioDataHashes:
    return PortfolioDataHashes(plan_hash=hashes.plan_hash, planning_data_hash=hashes.planning_data_hash,
                               execution_data_fingerprint=hashes.execution_data_fingerprint)


def _replace_prepared(
    material: PortfolioHashInput, index: int, bucket: PreparedBucketData,
) -> PortfolioHashInput:
    buckets = list(material.data.buckets)
    buckets[index] = bucket
    return replace(material, data=replace(material.data, buckets=tuple(buckets)))


def _mutate(material: PortfolioHashInput, mutation: Mutation) -> PortfolioHashInput:
    request = material.request
    match mutation:
        case "opening":
            buckets = list(request.portfolio_state.buckets)
            buckets[0] = buckets[0].model_copy(update={"cash": "1001"})
            state = PortfolioState(buckets=tuple(buckets))
            return replace(material, request=request.model_copy(update={"portfolio_state": state}))
        case "session":
            buckets = list(material.sessions.buckets)
            buckets[0] = replace(buckets[0], session=buckets[0].session.model_copy(update={"source": "changed-calendar"}))
            return replace(material, sessions=replace(material.sessions, buckets=tuple(buckets)))
        case "fx":
            snapshots = (request.fx_snapshots[0].model_copy(update={"rate": "7.9"}),)
            return replace(material, request=request.model_copy(update={"fx_snapshots": snapshots}))
        case "conversion":
            conversions = (request.fx_conversions[0].model_copy(update={"amount": "26"}),)
            return replace(material, request=request.model_copy(update={"fx_conversions": conversions}))
        case "planning":
            bucket = material.data.buckets[0]
            old = bucket.planning
            planning = replace(old, bars=(replace(old.bars[0], close="9.75"),))
            return _replace_prepared(material, 0, replace(bucket, planning=planning))
        case "planner":
            return replace(material, planner_version="pt-planner-v2")
        case "order":
            orders = (request.orders[0].model_copy(update={"qty": 11}), *request.orders[1:])
            return replace(material, request=request.model_copy(update={"orders": orders}))
        case "fee":
            models = list(material.effective_fee_models)
            parameters = dict(models[0].parameters)
            parameters["commission_min"] = Decimal("6")
            models[0] = replace(models[0], parameters=MappingProxyType(parameters))
            return replace(material, effective_fee_models=tuple(models))
        case "execution":
            bucket = material.data.buckets[0]
            assert bucket.execution is not None
            execution = replace(bucket.execution, bars=(replace(bucket.execution.bars[0], close="10.75"),))
            return _replace_prepared(material, 0, replace(bucket, execution=execution))
        case "rule":
            versions = dict(material.rules_versions)
            versions["cn"] = "pt-rules-v6"
            return replace(material, rules_versions=versions)
        case unreachable:
            from typing import assert_never
            assert_never(unreachable)


def test_layers_render_fixed_point_bytes_and_four_distinct_hashes() -> None:
    # Given a three-market request with non-normalized fixed-point input strings.
    material = _material()
    # When all provenance layers are canonicalized and hashed.
    hashes = compute_portfolio_hashes(material, _document())
    planning_bytes = planning_canonical_bytes(material)
    plan_bytes = plan_canonical_bytes(material)
    execution_bytes = execution_canonical_bytes(material)
    # Then numeric domains are scale-stable and each digest covers its own bytes.
    assert b'"cash":"1000.00"' in plan_bytes
    assert b'"avg_cost":"9.500000"' in plan_bytes
    assert b'"rate":"7.800000000000"' in planning_bytes
    assert b'"amount":"25.00"' in planning_bytes
    assert b'"close":"9.500000"' in planning_bytes
    assert b'"close":"10.250000"' in execution_bytes
    assert hashes.plan_hash == hashlib.sha256(plan_bytes).hexdigest()
    assert hashes.planning_data_hash == hashlib.sha256(planning_bytes).hexdigest()
    assert hashes.execution_data_fingerprint == hashlib.sha256(execution_bytes).hexdigest()
    assert hashes.planning_data_hash != hashes.execution_data_fingerprint
    assert len({hashes.plan_hash, hashes.planning_data_hash, hashes.execution_data_fingerprint, hashes.document_hash}) == 4


def test_document_hash_has_an_independent_known_vector_and_no_hash_cycle() -> None:
    # Given authoritative layer hashes and a document containing stale embedded hashes.
    layers = PortfolioDataHashes("a" * 64, "b" * 64, "c" * 64)
    document = {"amount": "1.00", "complete": True, "status": "success", "hashes": {"document_hash": "f" * 64}}
    expected = (
        b'{"document":{"amount":"1.00","complete":true,"status":"success"},'
        + b'"execution_data_fingerprint":"' + b"c" * 64 + b'",'
        + b'"plan_hash":"' + b"a" * 64 + b'",'
        + b'"planning_data_hash":"' + b"b" * 64 + b'"}'
    )
    # When the final document layer is independently computed from canonical bytes.
    actual_bytes = document_canonical_bytes(document, layers)
    # Then embedded hash fields are replaced by the authoritative layer coverage.
    assert actual_bytes == expected
    assert document_hash(document, layers) == hashlib.sha256(expected).hexdigest()
    assert document_canonical_bytes({"amount": "1.00", "complete": True, "status": "success"}, layers) == expected


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("opening", {"plan_hash", "document_hash"}), ("session", {"plan_hash", "planning_data_hash", "document_hash"}),
        ("fx", {"plan_hash", "planning_data_hash", "document_hash"}), ("conversion", {"plan_hash", "planning_data_hash", "document_hash"}),
        ("planning", {"plan_hash", "planning_data_hash", "document_hash"}), ("planner", {"plan_hash", "document_hash"}),
        ("order", {"plan_hash", "document_hash"}), ("fee", {"plan_hash", "execution_data_fingerprint", "document_hash"}),
        ("execution", {"execution_data_fingerprint", "document_hash"}), ("rule", {"execution_data_fingerprint", "document_hash"}),
    ],
)
def test_each_mutation_changes_exactly_its_declared_layers(
    mutation: Mutation, expected: set[str],
) -> None:
    # Given baseline hashes for the complete layered provenance input.
    baseline = compute_portfolio_hashes(_material(), _document()).model_dump()
    # When exactly one declared input class changes.
    changed = compute_portfolio_hashes(_mutate(_material(), mutation), _document()).model_dump()
    # Then downstream document identity changes without contaminating unrelated data layers.
    assert {name for name in baseline if baseline[name] != changed[name]} == expected


def test_final_document_mutation_changes_only_document_hash() -> None:
    # Given an unchanged plan/data/execution provenance chain.
    material = _material()
    baseline = compute_portfolio_hashes(material, _document()).model_dump()
    # When only the returned document body changes.
    changed_document = {**_document(), "warnings": ["new warning"]}
    changed = compute_portfolio_hashes(material, changed_document).model_dump()
    # Then no input-data fingerprint is rewritten retroactively.
    assert {name for name in baseline if baseline[name] != changed[name]} == {"document_hash"}


@pytest.mark.parametrize("bad", [1.0, float("nan"), float("inf"), Decimal("1"), object(), {1: "non-string key"}])
def test_malformed_document_payloads_fail_closed(bad) -> None:
    # Given a non-JSON value or a forbidden float in a final document.
    layers = PortfolioDataHashes("a" * 64, "b" * 64, "c" * 64)
    # When / Then hashing fails before legacy JCS can coerce it.
    with pytest.raises(PortfolioRequestError) as caught:
        document_hash({"bad": bad}, layers)
    assert caught.value.reason == "invalid_hash_payload"


def test_legacy_engine_fingerprint_cannot_substitute_for_portfolio_identity() -> None:
    # Given an unchanged legacy fingerprint and a changed raw opening portfolio.
    legacy = engine_fingerprint(rules_version="pt-rules-v5", bar_fingerprint="fixed")
    baseline = compute_portfolio_hashes(_material(), _document())
    # When only portfolio opening state changes.
    changed = compute_portfolio_hashes(_mutate(_material(), "opening"), _document())
    # Then portfolio provenance detects it while the legacy value cannot represent it.
    assert changed.plan_hash != baseline.plan_hash
    assert engine_fingerprint(rules_version="pt-rules-v5", bar_fingerprint="fixed") == legacy
    assert legacy not in set(baseline.model_dump().values())


def test_cross_process_hash_seed_outputs_identical_hashes_and_canonical_bytes() -> None:
    # Given a driver that loads the same typed fixture in two fresh Python processes.
    driver = """
import json, runpy
ns = runpy.run_path('tests/test_paper_trade_portfolio_hash.py')
material, document = ns['_material'](), ns['_document']()
hashes = ns['compute_portfolio_hashes'](material, document)
layers = ns['_data_hashes'](hashes)
print(json.dumps({'hashes': hashes.model_dump(), 'bytes': {
    'plan': ns['plan_canonical_bytes'](material).decode('utf-8'),
    'planning': ns['planning_canonical_bytes'](material).decode('utf-8'),
    'execution': ns['execution_canonical_bytes'](material).decode('utf-8'),
    'document': ns['document_canonical_bytes'](document, layers).decode('utf-8'),
}}, sort_keys=True, separators=(',', ':')))
"""
    outputs = []
    for seed in ("1", "2"):
        completed = subprocess.run(
            [sys.executable, "-c", driver], cwd=AGENT_ROOT, check=True,
            capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": seed},
        )
        outputs.append(completed.stdout)
    # When / Then different hash seeds emit byte-identical canonical JSON and hashes.
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["hashes"]["document_hash"] == compute_portfolio_hashes(_material(), _document()).document_hash
