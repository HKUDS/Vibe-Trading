"""Forex/CFD mandate vocabulary + lot-aware gate sizing hook (MT5 groundwork).

Covers the three Part-1 surfaces of the MT5/Exness integration:

* ``InstrumentType.FOREX`` / ``InstrumentType.CFD`` and ``AssetClass.FOREX``
  exist, parse from mandate JSON under schema v1, and route through
  ``check_mandate`` exactly like CRYPTO (forex) / OPTION (cfd).
* ``instrument_asset_class`` maps FOREX to its bucket and CFD to ``None``.
* The SDK order gate's notional normalization honors an optional, authoritative
  ``quantity_notional_usd`` connector hook (lot-sized quantities must never be
  priced as ``quantity x quote``), while the hook-less legacy path is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import src.live.sdk_order_gate as sdk_order_gate
from src.live.enforcement import (
    BREACH_KIND_INSTRUMENT,
    BREACH_KIND_UNIVERSE,
    OrderIntent,
    check_mandate,
    instrument_asset_class,
)
from src.live.mandate.model import (
    MANDATE_SCHEMA_VERSION,
    AssetClass,
    ConsentMeta,
    HardCaps,
    InstrumentType,
    Mandate,
    UniverseConstraint,
)
from src.live.mandate.store import _parse_mandate

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _mandate(
    *,
    instruments: tuple[InstrumentType, ...],
    asset_classes: tuple[AssetClass, ...],
    min_market_cap_usd: float | None = None,
    **caps_overrides: Any,
) -> Mandate:
    created = datetime.now(timezone.utc)
    caps = {
        "account_funding_usd": 5000.0,
        "max_order_notional_usd": 750.0,
        "max_total_exposure_usd": 5000.0,
        "max_leverage": 1.0,
        "allowed_instruments": instruments,
        "max_trades_per_day": 5,
    }
    caps.update(caps_overrides)
    return Mandate(
        schema_version=MANDATE_SCHEMA_VERSION,
        hard_caps=HardCaps(**caps),
        universe=UniverseConstraint(
            asset_classes=asset_classes,
            min_market_cap_usd=min_market_cap_usd,
            min_avg_daily_volume_usd=None,
            exclude_symbols=(),
        ),
        consent=ConsentMeta(
            created_at=created.isoformat(),
            consent_token_sha256="deadbeef",
            broker="mt5",
            account_ref="acct_ref_mt5",
            expires_at=(created + timedelta(days=30)).isoformat(),
        ),
    )


def _check(mandate: Mandate, intent: OrderIntent):
    return check_mandate(
        mandate,
        intent,
        positions=[],
        balance=None,
        broker="mt5",
        remote_tool="place_order",
        daily_count=0,
    )


def _raw_mandate_json(instruments: list[str], asset_classes: list[str]) -> dict:
    created = datetime.now(timezone.utc)
    return {
        "schema_version": MANDATE_SCHEMA_VERSION,
        "hard_caps": {
            "account_funding_usd": 5000.0,
            "max_order_notional_usd": 750.0,
            "max_total_exposure_usd": 5000.0,
            "max_leverage": 1.0,
            "allowed_instruments": instruments,
            "max_trades_per_day": 5,
        },
        "universe": {
            "asset_classes": asset_classes,
            "min_market_cap_usd": None,
            "min_avg_daily_volume_usd": None,
            "exclude_symbols": [],
        },
        "consent": {
            "created_at": created.isoformat(),
            "consent_token_sha256": "deadbeef",
            "broker": "mt5",
            "account_ref": "acct_ref_mt5",
            "expires_at": (created + timedelta(days=30)).isoformat(),
        },
    }


# --------------------------------------------------------------------------- #
# Vocabulary                                                                   #
# --------------------------------------------------------------------------- #


class TestVocabulary:
    def test_instrument_type_gains_forex_and_cfd(self) -> None:
        assert hasattr(InstrumentType, "FOREX"), "InstrumentType.FOREX missing"
        assert hasattr(InstrumentType, "CFD"), "InstrumentType.CFD missing"
        assert InstrumentType.FOREX.value == "forex"
        assert InstrumentType.CFD.value == "cfd"

    def test_asset_class_gains_forex(self) -> None:
        assert hasattr(AssetClass, "FOREX"), "AssetClass.FOREX missing"
        assert AssetClass.FOREX.value == "forex"

    def test_schema_version_unchanged(self) -> None:
        # Enum vocabulary growth is not a structural schema change: old
        # mandates contain only old values and must keep loading under v1.
        assert MANDATE_SCHEMA_VERSION == 1

    def test_instrument_asset_class_mapping(self) -> None:
        assert instrument_asset_class(InstrumentType.FOREX) is AssetClass.FOREX
        # CFD follows the OPTION precedent: no universe bucket, gated purely
        # by allowed_instruments.
        assert instrument_asset_class(InstrumentType.CFD) is None
        assert instrument_asset_class(InstrumentType.OPTION) is None


# --------------------------------------------------------------------------- #
# Mandate store round-trip (schema v1)                                         #
# --------------------------------------------------------------------------- #


class TestStoreRoundTrip:
    def test_parses_forex_and_cfd_values(self) -> None:
        raw = _raw_mandate_json(["equity", "forex", "cfd"], ["us_equity", "forex"])
        mandate = _parse_mandate(raw)
        assert InstrumentType.FOREX in mandate.hard_caps.allowed_instruments
        assert InstrumentType.CFD in mandate.hard_caps.allowed_instruments
        assert AssetClass.FOREX in mandate.universe.asset_classes

    def test_legacy_mandate_still_parses(self) -> None:
        raw = _raw_mandate_json(["equity", "etf"], ["us_equity", "us_etf"])
        mandate = _parse_mandate(raw)
        assert mandate.schema_version == MANDATE_SCHEMA_VERSION
        assert InstrumentType.EQUITY in mandate.hard_caps.allowed_instruments


# --------------------------------------------------------------------------- #
# check_mandate allow/deny matrix                                              #
# --------------------------------------------------------------------------- #


class TestCheckMandateForex:
    def _forex_intent(self, notional: float = 500.0) -> OrderIntent:
        return OrderIntent(
            symbol="EURUSD",
            side="buy",
            notional_usd=notional,
            quantity=None,
            instrument_type=InstrumentType.FOREX,
            asset_class=AssetClass.FOREX,
        )

    def test_forex_allowed_when_mandate_permits(self) -> None:
        mandate = _mandate(
            instruments=(InstrumentType.FOREX,),
            asset_classes=(AssetClass.FOREX,),
        )
        assert _check(mandate, self._forex_intent()) is None

    def test_forex_denied_by_equity_only_mandate(self) -> None:
        mandate = _mandate(
            instruments=(InstrumentType.EQUITY, InstrumentType.ETF),
            asset_classes=(AssetClass.US_EQUITY,),
        )
        breach = _check(mandate, self._forex_intent())
        assert breach is not None
        assert breach.kind == BREACH_KIND_INSTRUMENT
        assert breach.limit == "allowed_instruments"

    def test_forex_denied_when_asset_class_not_permitted(self) -> None:
        # Instrument allowed but the forex universe bucket is not.
        mandate = _mandate(
            instruments=(InstrumentType.FOREX,),
            asset_classes=(AssetClass.US_EQUITY,),
        )
        breach = _check(mandate, self._forex_intent())
        assert breach is not None
        assert breach.kind == BREACH_KIND_UNIVERSE
        assert breach.limit == "asset_classes"

    def test_forex_market_cap_floor_fails_closed(self) -> None:
        # No loader market is wired for AssetClass.FOREX, so a market-cap
        # floor must deny (fail-closed), never wave through.
        mandate = _mandate(
            instruments=(InstrumentType.FOREX,),
            asset_classes=(AssetClass.FOREX,),
            min_market_cap_usd=1e9,
        )
        breach = _check(mandate, self._forex_intent())
        assert breach is not None
        assert breach.kind == BREACH_KIND_UNIVERSE
        assert breach.limit == "min_market_cap_usd"


class TestCheckMandateCfd:
    def _cfd_intent(self) -> OrderIntent:
        return OrderIntent(
            symbol="XAUUSD",
            side="buy",
            notional_usd=500.0,
            quantity=None,
            instrument_type=InstrumentType.CFD,
            asset_class=None,
        )

    def test_cfd_requires_explicit_instrument_allowance(self) -> None:
        mandate = _mandate(
            instruments=(InstrumentType.FOREX,),
            asset_classes=(AssetClass.FOREX,),
        )
        breach = _check(mandate, self._cfd_intent())
        assert breach is not None
        assert breach.kind == BREACH_KIND_INSTRUMENT
        assert breach.limit == "allowed_instruments"

    def test_cfd_allowed_skips_asset_class_bucket(self) -> None:
        # CFD has no asset-class bucket (OPTION precedent): with "cfd"
        # explicitly allowed, the asset-class check is skipped even though
        # no equity/forex bucket would admit XAUUSD.
        mandate = _mandate(
            instruments=(InstrumentType.CFD,),
            asset_classes=(AssetClass.US_EQUITY,),
        )
        assert _check(mandate, self._cfd_intent()) is None


# --------------------------------------------------------------------------- #
# Gate sizing hook (_implied_notional)                                         #
# --------------------------------------------------------------------------- #


def _intent_with_quantity(quantity: float) -> OrderIntent:
    return OrderIntent(
        symbol="EURUSD",
        side="buy",
        notional_usd=None,
        quantity=quantity,
        instrument_type=InstrumentType.CRYPTO,
        asset_class=AssetClass.CRYPTO,
    )


class TestImpliedNotionalHook:
    def test_hook_is_authoritative_over_quote_product(self) -> None:
        # 0.1 lots EURUSD is ~$10,800 — NEVER 0.1 x 1.08. When the connector
        # exposes quantity_notional_usd there must be no quote-product fallback.
        connector = SimpleNamespace(
            quantity_notional_usd=lambda config, symbol, quantity: 10_800.0,
            get_quote=lambda symbol, config=None: {"quote": {"last": 1.08}},
        )
        intent = sdk_order_gate._normalize_notional(_intent_with_quantity(0.1), connector, config=None)
        assert intent is not None
        assert intent.notional_usd == pytest.approx(10_800.0)

    def test_hook_none_fails_closed(self) -> None:
        connector = SimpleNamespace(
            quantity_notional_usd=lambda config, symbol, quantity: None,
            get_quote=lambda symbol, config=None: {"quote": {"last": 1.08}},
        )
        assert sdk_order_gate._normalize_notional(_intent_with_quantity(0.1), connector, config=None) is None

    def test_hook_exception_fails_closed(self) -> None:
        def _boom(config: Any, symbol: str, quantity: float) -> float:
            raise RuntimeError("terminal gone")

        connector = SimpleNamespace(
            quantity_notional_usd=_boom,
            get_quote=lambda symbol, config=None: {"quote": {"last": 1.08}},
        )
        assert sdk_order_gate._normalize_notional(_intent_with_quantity(0.1), connector, config=None) is None

    def test_hook_nonpositive_fails_closed(self) -> None:
        connector = SimpleNamespace(
            quantity_notional_usd=lambda config, symbol, quantity: 0.0,
        )
        assert sdk_order_gate._normalize_notional(_intent_with_quantity(0.1), connector, config=None) is None

    def test_legacy_path_unchanged_without_hook(self) -> None:
        # Hook absent → exact legacy behavior: quantity x connector quote.
        connector = SimpleNamespace(
            get_quote=lambda symbol, config=None: {"quote": {"last": 50_000.0}},
        )
        intent = sdk_order_gate._normalize_notional(_intent_with_quantity(0.5), connector, config=None)
        assert intent is not None
        assert intent.notional_usd == pytest.approx(25_000.0)

    def test_explicit_notional_still_maxed_with_hook(self) -> None:
        # max(explicit, implied) posture preserved when the hook is present.
        connector = SimpleNamespace(
            quantity_notional_usd=lambda config, symbol, quantity: 10_800.0,
        )
        base = _intent_with_quantity(0.1)
        intent = OrderIntent(
            symbol=base.symbol,
            side=base.side,
            notional_usd=20_000.0,
            quantity=base.quantity,
            instrument_type=base.instrument_type,
            asset_class=base.asset_class,
        )
        normalized = sdk_order_gate._normalize_notional(intent, connector, config=None)
        assert normalized is not None
        assert normalized.notional_usd == pytest.approx(20_000.0)
