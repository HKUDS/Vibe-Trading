"""T7 gate — the pt-v1.3 request slice (``order_volume_ratio`` + ``volume_share``).

Pins the additive request surface of the volume-share policy before any engine
behaviour exists (T8-T11 consume the parsed value).  The parse contract:

* ``fill_model="volume_share"`` is a pt-v1.3 selector and requires a ratio;
* ``order_volume_ratio`` defaults to ``1.0`` and is only legal together with
  ``fill_model="volume_share"`` (a pt-v1.2 document must not opt into it);
* the policy is 5m + cn_a only, refused in-band before any data fetch;
* the ratio must be a finite JSON number in ``(0, 1]`` and never a bool;
* ``schema_version`` precedence is explicit: v1.3 outranks v1.2, and a v1.2
  selector set alone stays v1.2 and cannot carry the v1.3 ratio.

Offline: no network, no clock, no writes.  A loader that raises proves every
rejection happens before the data layer is reached.
"""

from __future__ import annotations

import json

import pytest

from src.tools.paper_trade.schema import (
    FILL_MODELS,
    SCHEMA_VERSION,
    SCHEMA_VERSION_V1_2,
    PaperTradeSchemaError,
    parse_request,
)
from src.tools.paper_trade.tool import run_paper_trade_step

_DAY = "2026-10-20"


class _ExplodingLoader:
    """Any fetch means a gate ran too late: fail loudly, never touch the wire."""

    def fetch(self, *args, **kwargs):  # noqa: ANN002, ANN003 - test double
        raise AssertionError("the data layer must not be reached for a rejected request")


def _payload(**overrides):
    payload = {
        "account_id": "pa_v13_01",
        "market": "cn_a",
        "account_state": {"cash": 100000.0, "positions": []},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": _DAY,
        "to_date": _DAY,
    }
    payload.update(overrides)
    return payload


def _volume_share_payload(**overrides):
    fields = {"interval": "5m", "fill_model": "volume_share", "order_volume_ratio": 0.25}
    fields.update(overrides)
    return _payload(**fields)


# ── The additive vocabulary + the accepted request ──


def test_fill_models_grow_additively() -> None:
    assert "all_or_none" in FILL_MODELS
    assert "volume_share" in FILL_MODELS
    assert FILL_MODELS.index("all_or_none") < FILL_MODELS.index("volume_share")


def test_volume_share_with_a_ratio_parses_and_selects_v13() -> None:
    request = parse_request(_volume_share_payload())
    assert request.fill_model == "volume_share"
    assert request.order_volume_ratio == 0.25
    assert request.uses_v1_3 is True
    assert request.schema_version == "pt-v1.3"


def test_order_volume_ratio_defaults_to_one() -> None:
    request = parse_request(_payload())
    assert request.order_volume_ratio == 1.0
    assert request.uses_v1_3 is False
    assert request.schema_version == SCHEMA_VERSION == "pt-v1.1"

    # volume_share alone selects v1.3 and takes the documented ratio default.
    implied = parse_request(_payload(interval="5m", fill_model="volume_share"))
    assert implied.order_volume_ratio == 1.0
    assert implied.uses_v1_3 is True
    assert implied.schema_version == "pt-v1.3"


def test_explicit_null_ratio_is_the_default() -> None:
    request = parse_request(_payload(interval="5m", fill_model="volume_share", order_volume_ratio=None))
    assert request.order_volume_ratio == 1.0
    assert request.uses_v1_3 is True


# ── Ratio validation: type, finiteness, bounds ──


@pytest.mark.parametrize(
    "value",
    [0, 0.0, -0.1, 1.1, float("nan"), float("inf"), True, "0.5"],
)
def test_invalid_order_volume_ratios_are_rejected(value) -> None:
    with pytest.raises(PaperTradeSchemaError, match="order_volume_ratio"):
        parse_request(_volume_share_payload(order_volume_ratio=value))


@pytest.mark.parametrize("value", [1, 1.0, 0.25])
def test_ratios_inside_the_unit_interval_are_accepted(value) -> None:
    assert parse_request(_volume_share_payload(order_volume_ratio=value)).order_volume_ratio == float(value)


# ── Cross-field gates: ratio needs volume_share; volume_share is 5m + cn_a ──


@pytest.mark.parametrize(
    "overrides",
    [
        {"interval": "5m", "order_volume_ratio": 0.25},
        {"order_volume_ratio": 1.0},
    ],
)
def test_ratio_without_volume_share_is_rejected(overrides) -> None:
    with pytest.raises(PaperTradeSchemaError, match="order_volume_ratio"):
        parse_request(_payload(**overrides))


def test_volume_share_outside_five_minutes_is_rejected_before_any_fetch() -> None:
    document = json.loads(
        run_paper_trade_step(
            _payload(fill_model="volume_share", order_volume_ratio=0.5),
            loader=_ExplodingLoader(),
        )
    )
    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "volume_share" in document["message"]
    assert "5m" in document["message"]


@pytest.mark.parametrize("market", ["hk", "us"])
def test_volume_share_outside_cn_a_is_rejected_before_any_fetch(market: str) -> None:
    document = json.loads(
        run_paper_trade_step(
            _payload(
                market=market,
                interval="5m",
                fill_model="volume_share",
                order_volume_ratio=0.5,
            ),
            loader=_ExplodingLoader(),
        )
    )
    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "volume_share" in document["message"]
    assert "cn_a" in document["message"]


# ── Explicit schema-version precedence ──


def test_v13_fields_outrank_v12_selectors() -> None:
    request = parse_request(
        _payload(
            interval="5m",
            session="cn_a",
            path_model="bar_close",
            fill_model="volume_share",
            order_volume_ratio=0.25,
        )
    )
    assert request.uses_v1_3 is True
    assert request.schema_version == "pt-v1.3"
    assert request.schema_version != SCHEMA_VERSION_V1_2


def test_v12_selector_set_alone_stays_v12_and_cannot_carry_the_ratio() -> None:
    request = parse_request(_payload(interval="5m", path_model="bar_close"))
    assert request.uses_v1_3 is False
    assert request.schema_version == SCHEMA_VERSION_V1_2 == "pt-v1.2"

    with pytest.raises(PaperTradeSchemaError, match="order_volume_ratio"):
        parse_request(_payload(interval="5m", path_model="bar_close", order_volume_ratio=0.25))
