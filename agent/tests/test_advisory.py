"""Advisory interface and gate integration tests (#317).

Covers the PreTradeAdvisoryInterface contract, MockAdvisory behavior,
AdvisoryOrchestrator fail-open semantics, and LiveOrderGuardTool advisory
wiring (disabled by default, enabled with env var, observational only).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import src.live.paths as paths
from src.live.advisory import (
    AdvisoryContext,
    AdvisoryOrchestrator,
    AdvisoryResult,
    AggregatedVerdict,
    Verdict,
    clear_advisory_providers,
    register_advisory_provider,
)
from src.live.advisory.mock import MockAdvisory
from src.live.mandate.model import (
    MANDATE_SCHEMA_VERSION,
    AssetClass,
    ConsentMeta,
    HardCaps,
    InstrumentType,
    Mandate,
    UniverseConstraint,
)
from src.live.order_guard import LiveOrderGuardTool
from src.tools.mcp import MCPRemoteToolSpec


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


class _MockAdapter:
    def __init__(self, *, positions: Any = None, balance: Any = 5000.0) -> None:
        self.server_name = "robinhood"
        self._positions = positions if positions is not None else []
        self._balance = balance
        self.order_calls: list[dict[str, Any]] = []

    def call_tool(self, remote_name: str, arguments: dict, *, local_name: str | None = None) -> dict:
        if remote_name == "get_equity_positions":
            return {"positions": self._positions, "status": "ok"}
        if remote_name == "get_portfolio":
            return {"equity": self._balance, "status": "ok"}
        self.order_calls.append({"remote": remote_name, "arguments": arguments})
        return {"status": "ok", "order_id": "rh_test_1", "state": "accepted"}


def _spec() -> MCPRemoteToolSpec:
    return MCPRemoteToolSpec(
        server_name="robinhood",
        remote_name="place_equity_order",
        local_name="mcp_robinhood_place_equity_order",
        description="Place an order.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string"},
                "instrument_type": {"type": "string"},
                "notional_usd": {"type": "number"},
                "quantity": {"type": "number"},
            },
            "additionalProperties": True,
        },
    )


def _mandate(**caps_overrides: Any) -> Mandate:
    created = datetime.now(timezone.utc)
    caps: dict[str, Any] = {
        "account_funding_usd": 5000.0,
        "max_order_notional_usd": 750.0,
        "max_total_exposure_usd": 5000.0,
        "max_leverage": 1.0,
        "allowed_instruments": (InstrumentType.EQUITY, InstrumentType.ETF),
        "max_trades_per_day": 5,
    }
    caps.update(caps_overrides)
    return Mandate(
        schema_version=MANDATE_SCHEMA_VERSION,
        hard_caps=HardCaps(**caps),
        universe=UniverseConstraint(
            asset_classes=(AssetClass.US_EQUITY, AssetClass.US_ETF),
            min_market_cap_usd=None,
            min_avg_daily_volume_usd=None,
            exclude_symbols=("GME",),
        ),
        consent=ConsentMeta(
            created_at=created.isoformat(),
            consent_token_sha256="deadbeef",
            broker="robinhood",
            account_ref="acct_ref_xyz",
            expires_at=(created + timedelta(days=30)).isoformat(),
        ),
    )


def _write_mandate(live_runtime: Path, mandate: Mandate) -> None:
    broker = live_runtime / "live" / "robinhood"
    broker.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": mandate.schema_version,
        "hard_caps": {
            "account_funding_usd": mandate.hard_caps.account_funding_usd,
            "max_order_notional_usd": mandate.hard_caps.max_order_notional_usd,
            "max_total_exposure_usd": mandate.hard_caps.max_total_exposure_usd,
            "max_leverage": mandate.hard_caps.max_leverage,
            "allowed_instruments": [i.value for i in mandate.hard_caps.allowed_instruments],
            "max_trades_per_day": mandate.hard_caps.max_trades_per_day,
        },
        "universe": {
            "asset_classes": [a.value for a in mandate.universe.asset_classes],
            "min_market_cap_usd": mandate.universe.min_market_cap_usd,
            "min_avg_daily_volume_usd": mandate.universe.min_avg_daily_volume_usd,
            "exclude_symbols": list(mandate.universe.exclude_symbols),
        },
        "consent": {
            "created_at": mandate.consent.created_at,
            "consent_token_sha256": mandate.consent.consent_token_sha256,
            "broker": mandate.consent.broker,
            "account_ref": mandate.consent.account_ref,
            "expires_at": mandate.consent.expires_at,
        },
    }
    (broker / "mandate.json").write_text(json.dumps(payload), encoding="utf-8")


def _guard(adapter: _MockAdapter) -> LiveOrderGuardTool:
    return LiveOrderGuardTool(adapter, _spec(), broker="robinhood", session_id="s1")


def _make_context(**overrides: Any) -> AdvisoryContext:
    base: dict[str, Any] = {
        "symbol": "AAPL",
        "side": "buy",
        "notional_usd": 100.0,
        "account_equity": 5000.0,
        "utilization_ratio": 0.0,
        "open_position_count": 0,
        "total_exposure_usd": 0.0,
        "funding_usd": 5000.0,
    }
    base.update(overrides)
    return AdvisoryContext(**base)


# --------------------------------------------------------------------------- #
# 1. Verdict enum                                                              #
# --------------------------------------------------------------------------- #


def test_verdict_enum_members() -> None:
    assert len(Verdict) == 4
    assert Verdict.APPROVE.value == "approve"
    assert Verdict.APPROVE_WITH_CONCERNS.value == "approve_with_concerns"
    assert Verdict.REJECT.value == "reject"
    assert Verdict.REVIEW_UNAVAILABLE.value == "review_unavailable"


# --------------------------------------------------------------------------- #
# 2. AdvisoryContext frozen                                                    #
# --------------------------------------------------------------------------- #


def test_advisory_context_frozen() -> None:
    ctx = _make_context()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        ctx.symbol = "MSFT"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 3. AdvisoryResult auto-timestamp                                             #
# --------------------------------------------------------------------------- #


def test_advisory_result_auto_timestamp() -> None:
    result = AdvisoryResult(verdict=Verdict.APPROVE)
    assert result.created_at != ""
    parsed = datetime.fromisoformat(result.created_at)
    assert parsed.tzinfo is not None


# --------------------------------------------------------------------------- #
# 4. MockAdvisory default approve                                              #
# --------------------------------------------------------------------------- #


def test_mock_advisory_default_approve() -> None:
    mock = MockAdvisory()
    ctx = _make_context()
    result = mock.review(ctx)
    assert result.verdict == Verdict.APPROVE
    assert result.concerns == ()
    assert result.provider == "mock"
    assert len(mock.call_history) == 1


# --------------------------------------------------------------------------- #
# 5. MockAdvisory configurable verdict                                         #
# --------------------------------------------------------------------------- #


def test_mock_advisory_configurable_verdict() -> None:
    mock = MockAdvisory(
        verdict=Verdict.REJECT,
        concerns=("drawdown > 20%", "concentration risk"),
        summary="order rejected",
        confidence=0.9,
    )
    ctx = _make_context()
    result = mock.review(ctx)
    assert result.verdict == Verdict.REJECT
    assert result.concerns == ("drawdown > 20%", "concentration risk")
    assert result.summary == "order rejected"
    assert result.confidence == 0.9


# --------------------------------------------------------------------------- #
# 6. MockAdvisory raise_on_review                                              #
# --------------------------------------------------------------------------- #


def test_mock_advisory_raise_on_review() -> None:
    mock = MockAdvisory(raise_on_review=True)
    ctx = _make_context()
    with pytest.raises(RuntimeError, match="mock advisory failure"):
        mock.review(ctx)
    assert len(mock.call_history) == 1


# --------------------------------------------------------------------------- #
# 7. Orchestrator catches exception → REVIEW_UNAVAILABLE                       #
# --------------------------------------------------------------------------- #


def test_orchestrator_catches_exception() -> None:
    failing = MockAdvisory(raise_on_review=True, provider_id="failing")
    healthy = MockAdvisory(verdict=Verdict.APPROVE, provider_id="healthy")
    orchestrator = AdvisoryOrchestrator([failing, healthy])
    ctx = _make_context()

    aggregated = orchestrator.review(ctx)

    assert isinstance(aggregated, AggregatedVerdict)
    assert len(aggregated.results) == 2
    assert aggregated.results[0].verdict == Verdict.REVIEW_UNAVAILABLE
    assert aggregated.results[1].verdict == Verdict.APPROVE
    assert aggregated.verdict == Verdict.REVIEW_UNAVAILABLE


# --------------------------------------------------------------------------- #
# 8. Gate advisory disabled by default                                         #
# --------------------------------------------------------------------------- #


def test_gate_advisory_disabled_by_default(live_runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_ENABLE_ADVISORY", raising=False)
    _write_mandate(live_runtime, _mandate())
    adapter = _MockAdapter()
    guard = _guard(adapter)

    out = json.loads(guard.execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=100.0))

    assert out.get("status") == "ok"
    live_action = out.get("live_action")
    assert live_action is not None
    gate_decision = live_action["gate_decision"]
    assert gate_decision["advisory"] is None
    assert "advisory" not in gate_decision["checked_limits"]


# --------------------------------------------------------------------------- #
# 9. Gate advisory enabled with mock provider                                  #
# --------------------------------------------------------------------------- #


def test_gate_advisory_enabled_with_mock_provider(live_runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ENABLE_ADVISORY", "1")

    mock_provider = MockAdvisory(
        verdict=Verdict.APPROVE_WITH_CONCERNS,
        concerns=("high concentration",),
        summary="proceed with caution",
        provider_id="test_mock",
    )

    register_advisory_provider(mock_provider)
    try:
        _write_mandate(live_runtime, _mandate())
        adapter = _MockAdapter()
        guard = _guard(adapter)

        out = json.loads(guard.execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=100.0))

        assert out.get("status") == "ok"
        assert len(adapter.order_calls) == 1

        live_action = out.get("live_action")
        assert live_action is not None
        gate_decision = live_action["gate_decision"]
        assert "advisory" in gate_decision["checked_limits"]

        advisory = gate_decision["advisory"]
        assert advisory is not None
        assert advisory["verdict"] == "approve_with_concerns"
        assert "high concentration" in advisory["concerns"]
        assert len(advisory["results"]) == 1
        assert advisory["results"][0]["provider"] == "test_mock"
    finally:
        clear_advisory_providers()


def test_gate_advisory_reject_is_observational(live_runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ENABLE_ADVISORY", "1")

    register_advisory_provider(
        MockAdvisory(
            verdict=Verdict.REJECT,
            concerns=("risk service would reject this order",),
            provider_id="rejecting_mock",
        )
    )
    try:
        _write_mandate(live_runtime, _mandate())
        adapter = _MockAdapter()
        guard = _guard(adapter)

        out = json.loads(guard.execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=100.0))

        assert out.get("status") == "ok"
        assert len(adapter.order_calls) == 1

        advisory = out["live_action"]["gate_decision"]["advisory"]
        assert advisory["verdict"] == "reject"
        assert "risk service would reject this order" in advisory["concerns"]
    finally:
        clear_advisory_providers()


def test_gate_advisory_provider_failure_is_observational(live_runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ENABLE_ADVISORY", "1")

    register_advisory_provider(MockAdvisory(raise_on_review=True, provider_id="failing_mock"))
    try:
        _write_mandate(live_runtime, _mandate())
        adapter = _MockAdapter()
        guard = _guard(adapter)

        out = json.loads(guard.execute(symbol="AAPL", side="buy", instrument_type="equity", notional_usd=100.0))

        assert out.get("status") == "ok"
        assert len(adapter.order_calls) == 1

        advisory = out["live_action"]["gate_decision"]["advisory"]
        assert advisory["verdict"] == "review_unavailable"
        assert advisory["results"][0]["provider"] == "failing_mock"
        assert advisory["results"][0]["summary"] == "provider error: RuntimeError"
        assert "mock advisory failure" not in json.dumps(advisory)
    finally:
        clear_advisory_providers()
