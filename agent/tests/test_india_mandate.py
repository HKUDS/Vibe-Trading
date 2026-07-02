"""India (IN_EQUITY) mandate-enforcement wiring.

Confirms the ``in_equity`` asset class flows through the live mandate gate:
  - An IN_EQUITY order is denied (structural universe breach) when the mandate
    does not permit it.
  - It passes the asset-class gate when the mandate permits IN_EQUITY.
  - The enforcement loader chain resolves IN_EQUITY to the india_equity market.
"""

from __future__ import annotations

from src.live.enforcement import (
    BREACH_KIND_UNIVERSE,
    OrderIntent,
    _resolve_loader,
    check_mandate,
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


def _mandate(asset_classes: tuple[AssetClass, ...]) -> Mandate:
    return Mandate(
        schema_version=MANDATE_SCHEMA_VERSION,
        flatten_on_halt=False,
        hard_caps=HardCaps(
            account_funding_usd=100_000.0,
            max_order_notional_usd=10_000.0,
            max_total_exposure_usd=100_000.0,
            max_leverage=1.0,
            allowed_instruments=(InstrumentType.EQUITY,),
            max_trades_per_day=10,
        ),
        universe=UniverseConstraint(
            asset_classes=asset_classes,
            min_market_cap_usd=None,
            min_avg_daily_volume_usd=None,
            exclude_symbols=(),
        ),
        consent=ConsentMeta(
            created_at="2026-06-01T00:00:00Z",
            consent_token_sha256="b" * 64,
            broker="shoonya",
            account_ref="shoonya_acct_opaque",
            expires_at="2099-01-01T00:00:00Z",
        ),
    )


def _india_intent() -> OrderIntent:
    return OrderIntent(
        symbol="RELIANCE",
        side="buy",
        notional_usd=1_000.0,
        quantity=None,
        instrument_type=InstrumentType.EQUITY,
        asset_class=AssetClass.IN_EQUITY,
    )


def test_in_equity_denied_when_not_permitted() -> None:
    breach = check_mandate(
        _mandate((AssetClass.US_EQUITY,)),
        _india_intent(),
        None,
        None,
        broker="shoonya",
        remote_tool="place_order",
        daily_count=0,
    )
    assert breach is not None
    assert breach.kind == BREACH_KIND_UNIVERSE
    assert breach.limit == "asset_classes"


def test_in_equity_passes_asset_class_gate_when_permitted() -> None:
    breach = check_mandate(
        _mandate((AssetClass.IN_EQUITY,)),
        _india_intent(),
        None,
        None,
        broker="shoonya",
        remote_tool="place_order",
        daily_count=0,
    )
    # It must not be rejected by the asset-class gate (other quantitative checks
    # are out of scope for this wiring test).
    assert breach is None or breach.limit != "asset_classes"


def test_in_equity_resolves_to_india_equity_loader() -> None:
    loader = _resolve_loader(AssetClass.IN_EQUITY)
    assert "india_equity" in loader.markets
