"""Mandate data model — the immutable bounded-autonomy contract.

Frozen dataclasses (no Pydantic): the mandate is read once at boot and never
mutated, so plain frozen dataclasses give the strongest immutability guarantee
with zero validation surface the agent could exploit. See
the live-trading SPEC, Mandate §1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MANDATE_SCHEMA_VERSION = 1


class InstrumentType(str, Enum):
    """Instrument classes the broker may report or accept.

    ``CFD`` covers margin contracts-for-difference that are not spot forex
    pairs (MT5 metals like XAUUSD, index/energy/crypto CFDs). Like ``OPTION``
    it has no universe asset-class bucket and is admitted only when the user's
    mandate explicitly lists ``"cfd"`` in ``allowed_instruments``.
    """

    EQUITY = "equity"
    ETF = "etf"
    OPTION = "option"
    CRYPTO = "crypto"
    FOREX = "forex"
    CFD = "cfd"


class AssetClass(str, Enum):
    """Universe-level asset class buckets the user may permit."""

    US_EQUITY = "us_equity"
    US_ETF = "us_etf"
    HK_EQUITY = "hk_equity"
    CN_EQUITY = "cn_equity"
    IN_EQUITY = "in_equity"
    CRYPTO = "crypto"
    FOREX = "forex"


@dataclass(frozen=True)
class HardCaps:
    """Layer (a): user-set quantitative ceilings.

    Funding is enforced BROKER-SIDE (Robinhood dedicated agentic account
    balance) and is the absolute ceiling the agent physically cannot exceed;
    it is mirrored here only for defense-in-depth pre-trade math, never as the
    primary guarantee. Every other field is enforced VIBE-SIDE in the gate.

    Attributes:
        account_funding_usd: Ring-fenced balance in the dedicated agentic
            account, USD. BROKER-ENFORCED ceiling; mirrored for local math.
        max_order_notional_usd: Vibe-enforced max single-order notional, USD.
        max_total_exposure_usd: Vibe-enforced cap on aggregate post-trade
            market value of all open positions, USD.
        max_leverage: Vibe-enforced gross leverage multiple. 1.0 == cash-only.
        allowed_instruments: Vibe-enforced whitelist of tradable instrument
            types. Empty == deny all (fail-closed).
        max_trades_per_day: Vibe-enforced count of order placements allowed
            per UTC calendar day. Counter persisted alongside the mandate.
    """

    account_funding_usd: float
    max_order_notional_usd: float
    max_total_exposure_usd: float
    max_leverage: float
    allowed_instruments: tuple[InstrumentType, ...]
    max_trades_per_day: int


@dataclass(frozen=True)
class OptionLimits:
    """Options-specific ceilings (#1435). Present only when the user opted in.

    ``Mandate.option_limits is None`` means options are disabled, whatever
    ``allowed_instruments`` says. Every amount is USD after the contract
    multiplier (premium ``2.50`` x 3 contracts x 100 == ``750``).

    Attributes:
        max_premium_per_order_usd: Premium one order may pay (net debit).
        max_loss_per_order_usd: Worst-case loss one order may carry.
        max_premium_per_day_usd: Premium paid across a UTC day.
        max_loss_per_day_usd: Worst-case loss opened across a UTC day.
        allow_naked_short: Whether a short leg not covered by a long leg of
            the same order is allowed. ``False`` by default; when ``True`` a
            naked short put counts strike x multiplier as its max loss and a
            naked short call stays refused (its loss is unbounded).
    """

    max_premium_per_order_usd: float
    max_loss_per_order_usd: float
    max_premium_per_day_usd: float
    max_loss_per_day_usd: float
    allow_naked_short: bool = False


@dataclass(frozen=True)
class UniverseConstraint:
    """Layer (b): user-set universe the agent picks symbols WITHIN.

    Not a ticker whitelist — that would kill agent discovery. The agent selects
    individual symbols freely so long as each clears these structural filters.

    Attributes:
        asset_classes: Permitted asset-class buckets. Empty == deny all.
        min_market_cap_usd: Market-cap floor, USD. ``None`` == no floor.
        min_avg_daily_volume_usd: Liquidity floor as trailing avg daily dollar
            volume, USD. ``None`` == no floor.
        exclude_symbols: Hard per-symbol denylist (normalized upper-case,
            e.g. ``BTC-USDT`` style for crypto). Takes precedence over every
            other universe rule.
    """

    asset_classes: tuple[AssetClass, ...]
    min_market_cap_usd: float | None
    min_avg_daily_volume_usd: float | None
    exclude_symbols: tuple[str, ...]


@dataclass(frozen=True)
class ConsentMeta:
    """Provenance proving the user (not the agent) authored this mandate.

    Attributes:
        created_at: ISO-8601 UTC timestamp the user committed the mandate.
        consent_token_sha256: Hash of the consent artifact emitted by the
            consent UX section, binding this file to an explicit human approval.
        broker: Broker key, e.g. ``"robinhood"``.
        account_ref: Opaque broker account identifier (NOT credentials).
        expires_at: ISO-8601 UTC timestamp after which the mandate is dead and
            the gate fail-closes until the user re-authorizes. Default lifetime
            30 days from ``created_at`` (configurable per commit). A live
            mandate must not live forever — see §9 decision 2.
    """

    created_at: str
    consent_token_sha256: str
    broker: str
    account_ref: str
    expires_at: str


@dataclass(frozen=True)
class Mandate:
    """Immutable bounded-autonomy mandate for one live broker channel.

    Loaded read-only at session boot from the user-side protected store. The
    agent loop has no constructor or write path to this object (see §2).

    Attributes:
        schema_version: ``MANDATE_SCHEMA_VERSION`` at write time; gate refuses
            to operate on an unknown future version (fail-closed).
        hard_caps: Layer (a) quantitative ceilings.
        universe: Layer (b) discovery universe.
        consent: Provenance/consent metadata.
        flatten_on_halt: Whether a kill-switch trip should flatten open
            positions (submit closing orders) in addition to cancelling resting
            orders. ``False`` (the default, and the value an old ``mandate.json``
            lacking this field loads as) means cancel-only — the safe default.
            ``True`` is an explicit per-mandate opt-in the user makes at commit.
            Read by ``src.live.runtime.flatten`` on a halt trip (SPEC §7.5 #6
            "optionally, per mandate").
        option_limits: Options ceilings the user approved at commit, or
            ``None`` (the default, and what an old ``mandate.json`` loads as)
            when options are disabled.
    """

    schema_version: int
    hard_caps: HardCaps
    universe: UniverseConstraint
    consent: ConsentMeta
    flatten_on_halt: bool = False
    option_limits: OptionLimits | None = None
