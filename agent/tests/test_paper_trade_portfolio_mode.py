"""Default-single pre-parse dispatch and pt-v2.0 routing.

The public ``run_paper_trade_step`` entry owns a tiny raw-payload gate before
the legacy ``parse_request``: an omitted or explicit ``mode="single"`` payload
must follow the unchanged pt-v1.1 pipeline byte-for-byte, while
``mode="portfolio"`` + ``schema_version="pt-v2.0"`` may only reach the internal
``run_portfolio_step`` seam. Every invalid combination returns the in-band
``INVALID_REQUEST`` envelope without touching the legacy parser, matcher,
success assembly or state hash.

Offline by construction: legacy fakes match ``test_paper_trade_tool.py``; the
portfolio end-to-end path uses raw fake loaders and a caller calendar.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade import engine
from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.portfolio.schema import load_portfolio_contract_schema
from src.tools.paper_trade.portfolio.wire import compute_raw_input_hash
from src.tools.paper_trade.tool import run_paper_trade_step

_CN_A_DAY = "2026-10-20"
_CN_A_PREV = "2026-10-19"
_HK_DAY = "2026-10-16"
_PORTFOLIO_DAY = "2026-11-13"
_PORTFOLIO_PRIOR = "2026-11-12"

_CN_A_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}
_HK_FEES = {
    "commission_rate": 0.0003,
    "commission_min": 3.0,
    "stamp_tax_rate": 0.001,
    "regulatory_levy_rate": 0.00003,
}


class FakeChClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._frames.get(ts_code, pd.DataFrame())


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "tencent") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self._frames[code] for code in codes if code in self._frames}


class FakeCalendarClient:
    def __init__(self, open_days: tuple[str, ...]) -> None:
        self._open = set(open_days)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self._open),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {
            "trade_date": day,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000.0,
        }
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _legacy_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "account_id": "pa_gate",
        "market": "cn_a",
        "account_state": {"cash": 200000.0, "positions": []},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": _CN_A_DAY,
        "to_date": _CN_A_DAY,
        "fee_model": dict(_CN_A_FEES),
    }
    payload.update(overrides)
    return payload


def _legacy_fakes() -> dict[str, Any]:
    return {
        "loader": FakeLoader({"600519.SH": _frame([(_CN_A_DAY, 1421.0)])}, "tencent"),
        "ch_client": FakeChClient({"600519.SH": _frame([(_CN_A_PREV, 1418.0)])}),
        "calendar_client": FakeCalendarClient((_CN_A_DAY,)),
        "limits_client": None,
    }


def _portfolio_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": "pf_gate",
        "base_currency": "USD",
        "trade_date": _PORTFOLIO_DAY,
        "planning_at": "2026-11-13T12:00:00+00:00",
        "valuation_at": "2026-11-13T21:00:00+00:00",
        "portfolio_state": {
            "buckets": [
                {
                    "bucket_id": "cn",
                    "market": "cn_a",
                    "currency": "CNY",
                    "cash": "200000.00",
                    "positions": [],
                },
                {
                    "bucket_id": "hk",
                    "market": "hk",
                    "currency": "HKD",
                    "cash": "50000.00",
                    "positions": [],
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
        "orders": [
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
        ],
    }
    payload.update(overrides)
    return payload


def _portfolio_loaders() -> dict[str, Any]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame([(_PORTFOLIO_PRIOR, 1418.0), (_PORTFOLIO_DAY, 1421.0)])}, "cn"),
        "hk": FakeLoader({"00700.HK": _frame([(_PORTFOLIO_PRIOR, 410.0), (_PORTFOLIO_DAY, 417.8)])}, "hk"),
        "us": FakeLoader({"AAPL.US": _frame([(_PORTFOLIO_PRIOR, 340.0), (_PORTFOLIO_DAY, 343.46)])}, "us"),
    }


class _StubDocument:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"mode": "json", "by_alias": True, "exclude_none": True}
        return self.payload


class _StubStepResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.document = _StubDocument(payload)
        self.order_plan = object()
        self.prepared_data = object()


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("legacy paper-trade seam must not run for portfolio mode")


def _forbid_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_module, "parse_request", _boom)
    monkeypatch.setattr(engine, "match_orders", _boom)


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _assert_v2_error(document: dict[str, Any], code: str) -> dict[str, Any]:
    assert document["status"] == "error"
    assert document["tool"] == "paper_trade_step"
    assert document["schema_version"] == "pt-v2.0"
    assert document["mode"] == "portfolio"
    assert document["code"] == code
    schema = load_portfolio_contract_schema("error_envelope")
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document)
    ) == []
    return document["error"]


_INPUT_HASH_SUFFIX = re.compile(r"; input_sha256=([0-9a-f]{64})$")


def _assert_wire_error_detail(
    document: dict[str, Any], raw_payload: dict[str, Any]
) -> str:
    """The public detail ends with exactly one raw-input digest and no ledger."""
    detail = document["error"]["detail"]
    assert detail.count("input_sha256=") == 1
    match = _INPUT_HASH_SUFFIX.search(detail)
    assert match is not None, detail
    assert match.group(1) == compute_raw_input_hash(raw_payload)
    assert "end_portfolio" not in document
    assert "fills" not in document
    assert "hashes" not in document
    return detail


# ── default and explicit single follow the legacy pipeline ──


def test_omitted_mode_uses_the_legacy_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed: list[Any] = []
    real_parse = tool_module.parse_request
    monkeypatch.setattr(
        tool_module,
        "parse_request",
        lambda payload: parsed.append(payload) or real_parse(payload),
    )
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)

    document = run_paper_trade_step(_legacy_payload(), **_legacy_fakes())

    assert parsed == [_legacy_payload()]
    parsed_document = json.loads(document)
    assert parsed_document["schema_version"] == "pt-v1.1"
    assert parsed_document["market"] == "cn_a"
    assert parsed_document["fills"][0]["fee"] == 36.95


def test_explicit_single_mode_is_byte_identical_to_omitted_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed: list[Any] = []
    real_parse = tool_module.parse_request
    monkeypatch.setattr(
        tool_module,
        "parse_request",
        lambda payload: parsed.append(payload) or real_parse(payload),
    )
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)

    omitted = run_paper_trade_step(_legacy_payload(), **_legacy_fakes())
    explicit = run_paper_trade_step(_legacy_payload(mode="single"), **_legacy_fakes())

    assert explicit == omitted
    assert parsed == [_legacy_payload(), _legacy_payload(mode="single")]


def test_unknown_legacy_keys_stay_ignored_in_single_mode() -> None:
    # The gate must not turn legacy unknown-key tolerance into a strict schema.
    omitted = run_paper_trade_step(_legacy_payload(), **_legacy_fakes())
    with_note = run_paper_trade_step(
        _legacy_payload(mode="single", note="legacy client note"),
        **_legacy_fakes(),
    )
    assert with_note == omitted


# ── portfolio dispatch touches only the internal seam ──


def test_portfolio_mode_dispatches_only_to_run_portfolio_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    captured: dict[str, Any] = {}
    stub_body = {"status": "success", "schema_version": "pt-v2.0", "mode": "portfolio"}

    def _stub(payload: Any, **kwargs: Any) -> _StubStepResult:
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return _StubStepResult(stub_body)

    monkeypatch.setattr(tool_module, "run_portfolio_step", _stub)
    cn_loader, hk_loader, us_loader = object(), object(), object()

    document = run_paper_trade_step(
        _portfolio_payload(),
        loader={"cn_a": cn_loader, "hk": hk_loader, "us": us_loader},
        ch_client=None,
        calendar_client=None,
    )

    assert document == _canonical(stub_body)
    assert captured["payload"] == _portfolio_payload()
    assert captured["kwargs"]["loaders"] == {
        "cn_a": cn_loader,
        "hk": hk_loader,
        "us": us_loader,
    }
    assert captured["kwargs"]["ch_clients"] == {"cn_a": None, "hk": None, "us": None}
    assert captured["kwargs"]["calendar_client"] is None


def test_portfolio_dispatch_returns_the_public_document_not_the_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(
        tool_module,
        "run_portfolio_step",
        lambda payload, **kwargs: SimpleNamespace(document="PUBLIC-DOC"),
    )

    document = run_paper_trade_step(
        _portfolio_payload(),
        loader={},
        ch_client=None,
        calendar_client=None,
    )

    assert document == "PUBLIC-DOC"


def test_portfolio_mode_end_to_end_through_the_real_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)

    document = json.loads(
        run_paper_trade_step(
            _portfolio_payload(),
            loader=_portfolio_loaders(),
            ch_client=None,
            calendar_client=FakeCalendarClient((_PORTFOLIO_DAY,)),
        )
    )

    assert document["status"] == "success"
    assert document["schema_version"] == "pt-v2.0"
    assert document["mode"] == "portfolio"
    assert document["account_id"] == "pf_gate"
    assert document["complete"] is True
    assert [(fill["plan_order_id"], fill["bucket_id"]) for fill in document["fills"]] == [
        ("cn-buy-1", "cn"),
        ("hk-buy-1", "hk"),
        ("us-buy-1", "us"),
    ]
    assert set(document["hashes"]) == {
        "plan_hash",
        "planning_data_hash",
        "execution_data_fingerprint",
        "document_hash",
    }


# ── mode/version combinations fail closed before either branch ──


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {"schema_version": "pt-v2.0", "account_id": "pf", "trade_date": _PORTFOLIO_DAY},
            "missing_mode",
        ),
        (
            {"mode": "single", "schema_version": "pt-v2.0", "account_id": "pf"},
            "invalid_mode",
        ),
    ],
)
def test_v2_without_portfolio_mode_is_invalid_request(
    payload: dict[str, Any],
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)

    document = json.loads(run_paper_trade_step(payload))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"]) == (reason, "mode")
    assert "requires mode 'portfolio'" in error["detail"]


@pytest.mark.parametrize(
    "schema_version",
    [None, "pt-v1.1", "pt-v1.2", "pt-v1.3"],
)
def test_portfolio_mode_requires_exactly_pt_v2(
    schema_version: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)
    payload = _portfolio_payload()
    if schema_version is None:
        del payload["schema_version"]
    else:
        payload["schema_version"] = schema_version

    document = json.loads(run_paper_trade_step(payload))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    expected_reason = (
        "missing_schema_version" if schema_version is None else "invalid_schema_version"
    )
    assert (error["reason"], error["path"]) == (
        expected_reason,
        "schema_version",
    )
    assert "requires schema_version 'pt-v2.0'" in error["detail"]


def test_unknown_mode_is_invalid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)

    document = json.loads(run_paper_trade_step(_legacy_payload(mode="batch")))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"]) == ("invalid_mode", "mode")
    assert "mode must be 'single' or 'portfolio'" in error["detail"]


@pytest.mark.parametrize("legacy_field", ["market", "account_state", "from_date", "to_date"])
def test_portfolio_mode_rejects_legacy_only_fields(
    legacy_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)
    payload = _portfolio_payload()
    payload[legacy_field] = "legacy-value"

    document = json.loads(run_paper_trade_step(payload))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"]) == ("legacy_field_forbidden", legacy_field)
    assert "legacy field" in error["detail"]


@pytest.mark.parametrize(
    "portfolio_field",
    ["target_weights", "portfolio_state", "base_currency", "trade_date", "sessions"],
)
def test_single_mode_rejects_portfolio_only_fields(
    portfolio_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)
    payload = _legacy_payload(mode="single")
    payload[portfolio_field] = "portfolio-value"

    document = json.loads(run_paper_trade_step(payload))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"]) == (
        "portfolio_field_forbidden",
        portfolio_field,
    )
    assert "portfolio-only field" in error["detail"]


@pytest.mark.parametrize("legacy_field", ["strategy_path", "volume_share"])
def test_portfolio_unsupported_legacy_plan_fields_never_reach_matcher(
    legacy_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)
    payload = _portfolio_payload()
    payload[legacy_field] = "agent/strategies/x.py" if legacy_field == "strategy_path" else 0.25

    document = json.loads(run_paper_trade_step(payload))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"]) == ("legacy_field_forbidden", legacy_field)
    assert "legacy field" in error["detail"]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"mode": "hybrid", "account_id": "pf_hash"}, "invalid_mode"),
        ({"schema_version": "pt-v2.0", "account_id": "pf_hash"}, "missing_mode"),
        (
            {"mode": "single", "schema_version": "pt-v2.0", "account_id": "pf_hash"},
            "invalid_mode",
        ),
    ],
)
def test_portfolio_gate_error_detail_ends_with_one_raw_input_hash(
    payload: dict[str, Any],
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)
    monkeypatch.setattr(tool_module, "run_portfolio_step", _boom)

    document = json.loads(run_paper_trade_step(payload))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"]) == (reason, "mode")
    detail = _assert_wire_error_detail(document, payload)
    assert detail.split("; input_sha256=", 1)[0]


# ── portfolio runtime faults stay in-band and deterministic ──


def test_portfolio_request_error_maps_to_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.tools.paper_trade.portfolio.schema import PortfolioRequestError

    _forbid_legacy(monkeypatch)

    def _fail(payload: Any, **kwargs: Any) -> Any:
        raise PortfolioRequestError(
            reason="invalid_field",
            path="sessions",
            detail="sessions must be declared",
            bucket_id="cn",
        )

    monkeypatch.setattr(tool_module, "run_portfolio_step", _fail)
    payload = _portfolio_payload()

    document = json.loads(run_paper_trade_step(payload, loader={}))
    error = _assert_v2_error(document, "INVALID_REQUEST")

    assert (error["reason"], error["path"], error["bucket_id"]) == (
        "invalid_field",
        "sessions",
        "cn",
    )
    assert document["account_id"] == "pf_gate"
    assert _assert_wire_error_detail(document, payload) == (
        "sessions must be declared; "
        f"input_sha256={compute_raw_input_hash(payload)}"
    )


def test_portfolio_data_error_maps_to_paper_data_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.tools.paper_trade.portfolio.sessions import PortfolioSessionError

    _forbid_legacy(monkeypatch)

    def _fail(payload: Any, **kwargs: Any) -> Any:
        raise PortfolioSessionError(
            code="PAPER_DATA_NOT_READY",
            reason="target_bar_not_ready",
            path="market_data.cn.readiness",
            bucket_id="cn",
        )

    monkeypatch.setattr(tool_module, "run_portfolio_step", _fail)
    payload = _portfolio_payload()

    document = json.loads(run_paper_trade_step(payload, loader={}))
    error = _assert_v2_error(document, "PAPER_DATA_NOT_READY")

    assert (error["reason"], error["path"], error["bucket_id"]) == (
        "target_bar_not_ready",
        "market_data.cn.readiness",
        "cn",
    )
    assert _assert_wire_error_detail(document, payload).endswith(
        f"input_sha256={compute_raw_input_hash(payload)}"
    )


def test_portfolio_data_error_after_a_declared_conversion_carries_the_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real post-conversion data fault keeps the whole raw request identity."""
    _forbid_legacy(monkeypatch)
    payload = _portfolio_payload(
        fx_conversions=[
            {
                "rate_id": "cny-usd-fix",
                "from_bucket_id": "cn",
                "to_bucket_id": "us",
                "amount": "1000.00",
            }
        ]
    )
    loaders = _portfolio_loaders()
    # The USD bucket has only its planning mark: the target-day bar is missing
    # after the declared conversion has already been planned and preflighted.
    loaders["us"] = FakeLoader(
        {"AAPL.US": _frame([(_PORTFOLIO_PRIOR, 340.0)])}, "us"
    )

    document = json.loads(
        run_paper_trade_step(
            payload,
            loader=loaders,
            ch_client=None,
            calendar_client=FakeCalendarClient((_PORTFOLIO_DAY,)),
        )
    )
    error = _assert_v2_error(document, "PAPER_DATA_NOT_READY")

    assert (error["reason"], error["path"], error["bucket_id"]) == (
        "open_bucket_zero_target_bars",
        "market_data.us.execution.bars",
        "us",
    )
    assert _assert_wire_error_detail(document, payload).startswith(
        "PAPER_DATA_NOT_READY:open_bucket_zero_target_bars:"
    )


def test_portfolio_internal_error_is_not_masked_as_an_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.tools.paper_trade.portfolio.orchestrator import OrchestrationError

    _forbid_legacy(monkeypatch)

    def _fail(payload: Any, **kwargs: Any) -> Any:
        raise OrchestrationError(stage="match_orders", reason="internal_bug")

    monkeypatch.setattr(tool_module, "run_portfolio_step", _fail)

    with pytest.raises(OrchestrationError) as raised:
        run_paper_trade_step(_portfolio_payload(), loader={})
    assert raised.value.code == "INTERNAL"


def test_unexpected_portfolio_fault_is_not_masked_as_an_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy(monkeypatch)

    def _fail(payload: Any, **kwargs: Any) -> Any:
        raise RuntimeError("engine bug")

    monkeypatch.setattr(tool_module, "run_portfolio_step", _fail)

    with pytest.raises(RuntimeError, match="engine bug"):
        run_paper_trade_step(_portfolio_payload(), loader={})


def test_non_dict_payload_still_uses_the_legacy_error_envelope() -> None:
    document = json.loads(run_paper_trade_step(["not", "an", "object"]))
    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert document["account_id"] == "" and document["market"] == ""
    assert "received_state_hash" not in document
