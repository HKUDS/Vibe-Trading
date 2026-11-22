"""Shared offline fixtures and assertion helpers for the split wire suites.

The wire tests must never touch a provider: every step runs on the fake
loader/calendar doubles below, and the assertion helpers independently check
the published document shape (strict JSON types, canonical decimal strings,
packaged-schema validity) without importing the wire's own validators.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.schema import load_portfolio_contract_schema
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()

_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_DECIMAL_KEYS = {
    "amount",
    "avg_cost",
    "cash",
    "fee",
    "limit",
    "nav_base",
    "position_value",
    "price",
    "rebalance_band",
    "value",
    "weight",
}


class FakeLoader:
    """Offline loader double; the wire tests must never touch a provider."""

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


def _loaders() -> dict[str, Any]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 343.46)}, "us-fixture"),
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


def _run(payload: dict[str, Any]):
    return run_portfolio_step(
        payload,
        loaders=_loaders(),
        calendar_client=OpenCalendar(),
    )


def _validate(payload: dict[str, Any], schema_name: str) -> None:
    schema = load_portfolio_contract_schema(schema_name)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload)
    )
    assert errors == []


def _scan_numeric_types(value: Any, path: str = "$") -> None:
    """Fail on any public float/Decimal and every non-finite numeric."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        pytest.fail(f"float leaked at {path}: {value!r}")
    if isinstance(value, Decimal):
        pytest.fail(f"Decimal leaked at {path}: {value!r}")
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            _scan_numeric_types(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_numeric_types(item, f"{path}[{index}]")
        return
    pytest.fail(f"non-JSON value leaked at {path}: {type(value).__name__}")


def _assert_decimal_strings(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in _DECIMAL_KEYS:
                assert isinstance(item, str), f"{item_path} must be a decimal string"
                assert _DECIMAL_PATTERN.fullmatch(item), f"{item_path} is not canonical"
            elif key == "parameters":
                assert isinstance(item, dict)
                for name, parameter in item.items():
                    assert isinstance(parameter, str)
                    assert _DECIMAL_PATTERN.fullmatch(parameter), (
                        f"{item_path}.{name} is not canonical"
                    )
            else:
                _assert_decimal_strings(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_decimal_strings(item, f"{path}[{index}]")


def _outcome_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in ("fills", "rejected_orders", "canceled_orders"):
        rows.extend(payload[field])
    return rows


def _dumped(step: Any) -> dict[str, Any]:
    return step.document.model_dump(mode="json", by_alias=True, exclude_none=True)
