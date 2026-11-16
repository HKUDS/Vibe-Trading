"""PR2 gate — pt-v2.0 internal portfolio goldens, determinism and mutations.

Four checked-in documents under ``fixtures/paper_trade/golden/`` freeze the
complete ``PortfolioResult`` emitted by the real internal
``run_portfolio_step`` with offline fake loaders:

* explicit cn_a + hk + us orders,
* target weights plus one caller-declared pre-fill FX conversion,
* CN-open / HK-closed / US-open with a carried prior HK mark,
* one rejected order forcing ``complete=false`` while the other fill stands.

Every assertion compares the whole parsed document and its four layered
hashes, never selected fields. Determinism is proved in two fresh
interpreter processes (``PYTHONHASHSEED=1`` and ``2``) whose emitted bytes
must equal each other and the checked-in golden. Mutation tests remove a
target bar, reorder buckets, alter an FX rate and drop a plan order outcome,
requiring a declared structured error or a detected golden diff.

Offline by construction: fake loaders and a fake calendar client, injected
dates, no clock and no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade import engine
from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.execution import DecimalExecutionAdapter
from src.tools.paper_trade.portfolio.hash import PortfolioDataHashes, document_hash
from src.tools.paper_trade.portfolio.models import PortfolioResult
from src.tools.paper_trade.portfolio.orchestrator import (
    ExecutionOutcome,
    OrchestrationError,
)
from src.tools.paper_trade.portfolio.schema import (
    load_portfolio_contract_schema,
)
from src.tools.paper_trade.portfolio.sessions import PortfolioSessionError
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

TRADE_DATE = "2026-11-13"
PRIOR_DATE = "2026-11-12"
_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "golden"
_AGENT_ROOT = Path(__file__).resolve().parents[1]

_EXPLICIT = "portfolio_explicit_cn_hk_us"
_TARGET = "portfolio_target_weights_conversion"
_CLOSED = "portfolio_cn_open_hk_closed_us_open"
_REJECTION = "portfolio_per_order_rejection"
_SCENARIOS = (_EXPLICIT, _TARGET, _CLOSED, _REJECTION)


class FakeLoader:
    """Offline loader double; the golden step must never reach a provider."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frames[code] for code in codes if code in self.frames}


class OpenCalendar:
    """cn_a SH calendar double: every requested day is open."""

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": 1,
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


def _frame(prior: float, target: float | None) -> pd.DataFrame:
    records = [
        {
            "trade_date": PRIOR_DATE,
            "open": prior,
            "high": prior,
            "low": prior,
            "close": prior,
            "volume": 1000.0,
        }
    ]
    if target is not None:
        records.append(
            {
                "trade_date": TRADE_DATE,
                "open": target,
                "high": target,
                "low": target,
                "close": target,
                "volume": 1000.0,
            }
        )
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _loaders(*, us_target: float | None = 343.46) -> dict[str, Any]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, us_target)}, "us-fixture"),
    }


def _payload() -> dict[str, Any]:
    return json.loads(json.dumps(valid_portfolio_payload()))


def _explicit_payload() -> dict[str, Any]:
    payload = _payload()
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = "200000.00"
    payload["portfolio_state"]["buckets"][1]["fee_model"] = {
        "currency": "HKD",
        "parameters": {"commission_rate": "0.0003", "commission_min": "20.00"},
    }
    payload["orders"] = [
        {
            "order_id": "cn-buy-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "hk-buy-1",
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
        },
    ]
    return payload


def _target_payload() -> dict[str, Any]:
    payload = _payload()
    payload.pop("orders")
    payload["target_weights"] = [
        {
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "weight": "0.00",
        },
        {
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "weight": "0.16",
        },
        {
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "weight": "0.20",
        },
    ]
    payload["rebalance_band"] = "0"
    return payload


def _closed_payload() -> dict[str, Any]:
    payload = _payload()
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = "200000.00"
    payload["orders"] = [
        {
            "order_id": "cn-buy-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
        },
    ]
    for session in payload["sessions"]:
        if session["market"] == "hk":
            session["status"] = "closed"
    return payload


def _rejection_payload() -> dict[str, Any]:
    payload = _payload()
    payload["fx_conversions"] = []
    payload["orders"] = [
        {
            "order_id": "cn-sell-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "sell",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
            "limit": "300.00",
        },
    ]
    return payload


_PAYLOADS: Mapping[str, Callable[[], dict[str, Any]]] = {
    _EXPLICIT: _explicit_payload,
    _TARGET: _target_payload,
    _CLOSED: _closed_payload,
    _REJECTION: _rejection_payload,
}


def _run(
    payload: dict[str, Any],
    *,
    loaders: dict[str, Any] | None = None,
):
    return run_portfolio_step(
        payload,
        loaders=loaders or _loaders(),
        calendar_client=OpenCalendar(),
    )


def run_scenario(name: str, *, loaders: dict[str, Any] | None = None):
    """Run one golden scenario through the real internal step seam."""
    return _run(_PAYLOADS[name](), loaders=loaders)


def _canonical(document: PortfolioResult) -> bytes:
    payload = document.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def emit_document(name: str) -> bytes:
    """Return the exact canonical bytes frozen in ``fixtures/.../golden``."""
    return _canonical(run_scenario(name).document)


def _golden_bytes(name: str) -> bytes:
    return (_GOLDEN_DIR / f"{name}.json").read_bytes()


def _layers(parsed: dict[str, Any]) -> PortfolioDataHashes:
    hashes = parsed["hashes"]
    return PortfolioDataHashes(
        plan_hash=hashes["plan_hash"],
        planning_data_hash=hashes["planning_data_hash"],
        execution_data_fingerprint=hashes["execution_data_fingerprint"],
    )


def _assert_document_integrity(parsed: dict[str, Any]) -> None:
    document = PortfolioResult.model_validate(parsed)
    layers = _layers(parsed)
    assert parsed["hashes"]["document_hash"] == document_hash(document, layers)
    assert layers.planning_data_hash != layers.execution_data_fingerprint
    assert len(set(parsed["hashes"].values())) == 4
    for value in parsed["hashes"].values():
        assert len(value) == 64
        assert set(value) <= set("0123456789abcdef")
    schema = load_portfolio_contract_schema("result")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            parsed
        )
    ) == []


@pytest.mark.parametrize("name", _SCENARIOS)
def test_golden_matches_the_complete_parsed_document(name: str) -> None:
    # Given/When the real internal step runs against the frozen scenario.
    live = emit_document(name)
    frozen = _golden_bytes(name)
    live_document = json.loads(live)
    frozen_document = json.loads(frozen)

    # Then the whole document and every hash are byte-identical.
    assert live == frozen
    assert live_document == frozen_document
    assert live_document["hashes"] == frozen_document["hashes"]
    _assert_document_integrity(frozen_document)

    # Then each layer hash covers its own material independently.
    assert frozen_document["hashes"]["plan_hash"] != (
        frozen_document["hashes"]["planning_data_hash"]
    )
    assert frozen_document["hashes"]["execution_data_fingerprint"] != (
        frozen_document["hashes"]["planning_data_hash"]
    )


def test_golden_manifest_freezes_exact_bytes_and_hashes() -> None:
    manifest = json.loads(
        (_GOLDEN_DIR / "portfolio_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "paper_trade.portfolio_golden_manifest/v1"
    entries = {entry["file"]: entry for entry in manifest["goldens"]}
    assert set(entries) == {f"{name}.json" for name in _SCENARIOS}
    for name in _SCENARIOS:
        entry = entries[f"{name}.json"]
        raw = _golden_bytes(name)
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        assert json.loads(raw)["hashes"]["document_hash"] == entry["document_hash"]


_EMIT_ALL = "\n".join(
    (
        "import hashlib, json",
        "from tests.test_paper_trade_portfolio_golden import _SCENARIOS, emit_document",
        "output = {}",
        "for name in _SCENARIOS:",
        "    text = emit_document(name)",
        "    output[name] = {",
        "        'sha256': hashlib.sha256(text).hexdigest(),",
        "        'text': text.decode('utf-8'),",
        "    }",
        "print(json.dumps(output, sort_keys=True))",
    )
)


def test_goldens_are_byte_identical_across_fresh_processes() -> None:
    observed: dict[str, dict[str, dict[str, str]]] = {}
    for seed in ("1", "2"):
        environment = {**os.environ, "PYTHONHASHSEED": seed}
        completed = subprocess.run(
            [sys.executable, "-c", _EMIT_ALL],
            cwd=_AGENT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        observed[seed] = json.loads(completed.stdout)

    # Then both hash seeds emit the same complete documents.
    assert observed["1"] == observed["2"]
    for name in _SCENARIOS:
        emitted = observed["1"][name]
        text = emitted["text"].encode("utf-8")
        assert hashlib.sha256(text).hexdigest() == emitted["sha256"]
        # Then both fresh processes match the checked-in golden exactly.
        assert text == _golden_bytes(name)
        _assert_document_integrity(json.loads(text))


def test_closed_hk_golden_uses_prior_marks_without_matcher_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the CN-open / HK-closed / US-open scenario.
    called: list[str] = []
    real_run = engine.run_day_loop

    def recording(*args, **kwargs):
        called.append(str(kwargs["market"]))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(engine, "run_day_loop", recording)

    # When the step runs.
    step = run_scenario(_CLOSED)
    parsed = json.loads(_golden_bytes(_CLOSED))

    # Then the closed HK bucket never reached the matcher and carried 410.00.
    assert called == ["cn_a", "us"]
    assert [fill["bucket_id"] for fill in parsed["fills"]] == ["cn", "us"]
    hk = next(row for row in parsed["bucket_results"] if row["bucket_id"] == "hk")
    assert (hk["cash"], hk["position_value"], hk["nav_base"]) == (
        "50000.00",
        "41000.00",
        "11648.00",
    )
    assert parsed["sessions"][1]["status"] == "closed"
    assert any("hk: market closed" in warning for warning in parsed["warnings"])
    assert step.document.complete is True


def test_removing_a_target_bar_fails_closed_with_structured_error() -> None:
    # Given the explicit-orders scenario with the US target bar removed.
    loaders = _loaders(us_target=None)

    # When the step preflights the open US bucket.
    with pytest.raises(PortfolioSessionError) as raised:
        run_scenario(_EXPLICIT, loaders=loaders)

    # Then the structured data-not-ready error names the bucket and field.
    assert raised.value.code == "PAPER_DATA_NOT_READY"
    assert raised.value.reason == "open_bucket_zero_target_bars"
    assert raised.value.path == "market_data.us.execution.bars"
    assert raised.value.bucket_id == "us"


def test_reordering_buckets_is_detected_as_a_golden_diff() -> None:
    # Given the explicit-orders buckets reordered to us, cn, hk.
    payload = _explicit_payload()
    buckets = payload["portfolio_state"]["buckets"]
    payload["portfolio_state"]["buckets"] = [buckets[2], buckets[0], buckets[1]]

    # When the step runs.
    mutated = _canonical(_run(payload).document)
    frozen = _golden_bytes(_EXPLICIT)

    # Then the whole document differs from the golden in bucket order...
    assert mutated != frozen
    parsed = json.loads(mutated)
    frozen_document = json.loads(frozen)
    assert [row["bucket_id"] for row in parsed["opening_portfolio"]["buckets"]] == [
        "us",
        "cn",
        "hk",
    ]
    assert [row["bucket_id"] for row in parsed["bucket_results"]] == [
        "us",
        "cn",
        "hk",
    ]

    # Then every hash layer that covers bucket order changed too.
    assert parsed["hashes"] != frozen_document["hashes"]
    assert parsed["hashes"]["planning_data_hash"] != (
        frozen_document["hashes"]["planning_data_hash"]
    )
    _assert_document_integrity(parsed)


def test_altered_fx_rate_is_detected_as_a_golden_diff() -> None:
    # Given the target-weights scenario with a different CNY->USD rate.
    payload = _target_payload()
    payload["fx_snapshots"][0]["rate"] = "0.145"

    # When the step runs.
    mutated = _canonical(_run(payload).document)
    frozen = _golden_bytes(_TARGET)

    # Then the complete document and layered hashes differ from the golden.
    assert mutated != frozen
    parsed = json.loads(mutated)
    frozen_document = json.loads(frozen)
    assert parsed["post_conversion_portfolio"] != (
        frozen_document["post_conversion_portfolio"]
    )
    assert parsed["hashes"]["planning_data_hash"] != (
        frozen_document["hashes"]["planning_data_hash"]
    )
    assert parsed["hashes"]["document_hash"] != (
        frozen_document["hashes"]["document_hash"]
    )
    _assert_document_integrity(parsed)


def test_dropping_a_plan_order_outcome_aborts_without_a_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a matcher that silently drops the last planned order outcome.
    real_match = DecimalExecutionAdapter.match

    def dropping(self, request, ledger, plan, prepared):
        outcome = real_match(self, request, ledger, plan, prepared)
        assert isinstance(outcome, ExecutionOutcome)
        return replace(outcome, fills=outcome.fills[:-1])

    monkeypatch.setattr(DecimalExecutionAdapter, "match", dropping)

    # When the orchestrator validates the terminal outcomes.
    with pytest.raises(OrchestrationError) as raised:
        run_scenario(_EXPLICIT)

    # Then it aborts on the missing plan ID before any document exists.
    assert raised.value.stage == "match_orders"
    assert raised.value.reason == "missing_order_outcome"
    assert raised.value.code == "INTERNAL"
    assert raised.value.bucket_id is None
    assert "us-buy-1" in raised.value.detail
