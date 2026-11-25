"""One-day pt-v2.0 contribution, FX and weight-gap attribution.

The attribution document is a pure Decimal projection over the opening ledger,
the settled conversions, every execution fill, the ending ledger and the
planning/valuation marks. These tests freeze the exact NAV identity

    NAV_end_exact - NAV_start_exact
      = sum(position_contribution)
      + sum(cash_fx_effects)
      + conversion_effects
      + fee_effects
      + rounding_residual

and the weight tie-out between caller targets, the order plan and the realized
end ledger. Every mutation of a fill, conversion, mark, planned weight or
published realized weight must surface as a declared reconciliation issue; the
residual is never fitted to hide an error. No Brinson allocation/selection or
multi-day attribution is involved.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.analytics import build_portfolio_analytics
from src.tools.paper_trade.portfolio.schema import parse_portfolio_request


TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()
ZERO = Decimal(0)

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_PACKAGED_SCHEMA = (
    _AGENT_ROOT / "src" / "tools" / "paper_trade" / "paper_trade_step-v2.0.json"
)
_MIRROR_SCHEMA = (
    _AGENT_ROOT.parent / "schema" / "tool_contracts" / "paper_trade_step-v2.0.json"
)
_LEGACY_EXPLICIT_GOLDEN = (
    _AGENT_ROOT
    / "tests"
    / "fixtures"
    / "paper_trade"
    / "golden"
    / "portfolio_explicit_cn_hk_us.json"
)
# Frozen document hash of an archived pre-attribution golden.
_ARCHIVED_PRE_ATTRIBUTION_HASH = (
    "da38f7f6ea84cf7b9eeba0dfa4d3a4cf90f8f746422052eacfcfceb6fc996206"
)


class FakeLoader:
    """Offline loader double; attribution must never reach a provider."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frames[code] for code in codes if code in self.frames}


class OpenCalendar:
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
            "trade_date": PRIOR,
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
                "trade_date": DAY,
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


def _loaders() -> dict[str, FakeLoader]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 343.46)}, "us-fixture"),
    }


def _base_payload() -> dict[str, Any]:
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-attribution-01",
        "base_currency": "USD",
        "trade_date": DAY,
        "planning_at": "2026-11-13T12:00:00+00:00",
        "valuation_at": "2026-11-13T21:00:00+00:00",
        "interval": "1d",
        "fill_model": "all_or_none",
        "portfolio_state": {
            "buckets": [
                {
                    "bucket_id": "cn",
                    "market": "cn_a",
                    "currency": "CNY",
                    "cash": "100000.00",
                    "positions": [
                        {
                            "symbol": "600519.SH",
                            "qty": 100,
                            "avg_cost": "1400.00",
                            "currency": "CNY",
                        }
                    ],
                },
                {
                    "bucket_id": "hk",
                    "market": "hk",
                    "currency": "HKD",
                    "cash": "50000.00",
                    "positions": [
                        {
                            "symbol": "00700.HK",
                            "qty": 100,
                            "avg_cost": "300.00",
                            "currency": "HKD",
                        }
                    ],
                    "fee_model": {
                        "currency": "HKD",
                        "parameters": {"commission_rate": "0.0003"},
                    },
                },
                {
                    "bucket_id": "us",
                    "market": "us",
                    "currency": "USD",
                    "cash": "25000.00",
                    "positions": [],
                },
            ]
        },
        "sessions": [
            {
                "market": market,
                "status": "open",
                "source": "caller-calendar",
                "as_of": "2026-11-13T01:00:00+00:00",
            }
            for market in ("cn_a", "hk", "us")
        ],
        "fx_snapshots": [
            {
                "rate_id": "cny-usd-fix",
                "from": "CNY",
                "to": "USD",
                "rate": "0.14",
                "as_of": "2026-11-13T11:00:00+00:00",
                "source": "caller-fix",
            },
            {
                "rate_id": "hkd-usd-fix",
                "from": "HKD",
                "to": "USD",
                "rate": "0.128",
                "as_of": "2026-11-13T11:00:00+00:00",
                "source": "caller-fix",
            },
        ],
        "fx_conversions": [
            {
                "rate_id": "cny-usd-fix",
                "from_bucket_id": "cn",
                "to_bucket_id": "us",
                "amount": "1000.01",
            }
        ],
        "orders": [
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
        ],
        "sectors": [
            {"bucket_id": "cn", "symbol": "600519.SH", "sector": "consumer"},
            {"bucket_id": "hk", "symbol": "00700.HK", "sector": "technology"},
            {"bucket_id": "us", "symbol": "AAPL.US", "sector": "technology"},
        ],
    }


def _target_payload() -> dict[str, Any]:
    payload = _base_payload()
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
    payload["rebalance_band"] = "0.01"
    return payload


def _noop_payload() -> dict[str, Any]:
    payload = _base_payload()
    payload["fx_conversions"] = []
    payload["orders"] = []
    payload["portfolio_state"]["buckets"][2]["positions"] = [
        {
            "symbol": "AAPL.US",
            "qty": 2,
            "avg_cost": "340.00",
            "currency": "USD",
        }
    ]
    return payload


def _rounding_payload() -> dict[str, Any]:
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-attribution-rounding-01",
        "base_currency": "USD",
        "trade_date": DAY,
        "planning_at": "2026-11-13T12:00:00+00:00",
        "valuation_at": "2026-11-13T21:00:00+00:00",
        "interval": "1d",
        "fill_model": "all_or_none",
        "portfolio_state": {
            "buckets": [
                {
                    "bucket_id": "us",
                    "market": "us",
                    "currency": "USD",
                    "cash": "1000.00",
                    "positions": [],
                }
            ]
        },
        "sessions": [
            {
                "market": "us",
                "status": "open",
                "source": "caller-calendar",
                "as_of": "2026-11-13T01:00:00+00:00",
            }
        ],
        "fx_snapshots": [],
        "fx_conversions": [],
        "orders": [
            {
                "order_id": "us-buy-rounding",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 3,
            }
        ],
    }


def _rounding_loaders() -> dict[str, FakeLoader]:
    return {
        "us": FakeLoader({"AAPL.US": _frame(50.0, 50.005)}, "us-fixture"),
    }


def _run(
    payload: dict[str, Any] | None = None,
    *,
    loaders: dict[str, FakeLoader] | None = None,
):
    return run_portfolio_step(
        payload or _base_payload(),
        loaders=loaders or _loaders(),
        calendar_client=OpenCalendar(),
    )


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def _sum(values) -> Decimal:
    return sum((_decimal(value) for value in values), ZERO)


def _attribution(step):
    attribution = step.document.analytics.attribution
    assert attribution is not None
    return attribution


def _rebuild(
    step,
    payload: dict[str, Any],
    *,
    fills=None,
    conversion_events=None,
    prepared=None,
    plan=None,
):
    request = parse_portfolio_request(payload)
    return build_portfolio_analytics(
        request,
        step.end_ledger,
        prepared or step.prepared_data,
        conversion_events=(
            step.conversion_replay.events
            if conversion_events is None
            else conversion_events
        ),
        opening_ledger=step.opening_ledger,
        post_conversion_ledger=step.post_conversion_ledger,
        fills=step.execution.fills if fills is None else fills,
        rejected_orders=step.execution.rejected_orders,
        canceled_orders=step.execution.canceled_orders,
        plan=step.order_plan if plan is None else plan,
    )


def _assert_attribution_identity(attribution) -> None:
    nav = attribution.nav
    total = (
        _decimal(attribution.position_contribution_base)
        + _decimal(attribution.cash_fx_effect_base)
        + _decimal(attribution.conversion_effect_base)
        + _decimal(attribution.fee_effect_base)
        + _decimal(attribution.rounding_residual)
    )
    assert total == _decimal(nav.nav_change_exact)
    assert _decimal(attribution.rounding_residual) == _decimal(
        attribution.expected_rounding_residual
    )
    assert _decimal(nav.nav_change_exact) == (
        _decimal(nav.end_exact_nav_base) - _decimal(nav.start_exact_nav_base)
    )
    assert _decimal(nav.start_exact_nav_base) == (
        _decimal(nav.start_nav_base) + _decimal(nav.start_rounding_residual)
    )
    assert _decimal(nav.end_exact_nav_base) == (
        _decimal(nav.end_nav_base) + _decimal(nav.end_rounding_residual)
    )


def _assert_weight_identity(attribution) -> None:
    weights = attribution.weights
    total = (
        _decimal(weights.lot_gap_total)
        + _decimal(weights.price_gap_total)
        + _decimal(weights.reject_gap_total)
        + _decimal(weights.cash_gap)
        + _decimal(weights.valuation_rounding_weight)
    )
    assert abs(total) <= _decimal(weights.weight_rounding_tolerance)
    assert abs(_decimal(weights.weight_rounding_residual)) == abs(total)
    assert weights.reconciled is True
