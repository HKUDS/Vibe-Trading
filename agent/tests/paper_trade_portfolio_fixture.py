"""Independent three-market pt-v2.0 request literal used by schema tests."""

from __future__ import annotations


def valid_portfolio_payload() -> dict:  # noqa: DICT_OK
    return {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "portfolio-cross-market-01",
        "base_currency": "USD",
        "trade_date": "2026-11-13",
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
                "amount": "1000.00",
            }
        ],
        "orders": [
            {
                "order_id": "cn-buy-1",
                "bucket_id": "cn",
                "symbol": "600519.SH",
                "currency": "CNY",
                "side": "buy",
                "qty": 100,
                "limit": "1405.00",
            },
            {
                "order_id": "us-buy-1",
                "bucket_id": "us",
                "symbol": "AAPL.US",
                "currency": "USD",
                "side": "buy",
                "qty": 2,
            },
        ],
        "benchmark": {
            "benchmark_id": "caller-usd-benchmark",
            "start": {
                "observed_at": "2026-11-12T21:00:00+00:00",
                "value": "100.00",
                "currency": "USD",
            },
            "end": {
                "observed_at": "2026-11-13T21:00:00+00:00",
                "value": "101.00",
                "currency": "USD",
            },
        },
        "sectors": [
            {
                "bucket_id": "cn",
                "symbol": "600519.SH",
                "sector": "consumer_staples",
            },
            {
                "bucket_id": "hk",
                "symbol": "00700.HK",
                "sector": "communication_services",
            },
        ],
    }
