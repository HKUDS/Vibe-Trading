"""Same-name REST step parity with the Agent core and CLI.

``POST /api/paper-trade/step`` and ``vibe-trading paper step`` are the only
public surfaces and both forward the caller's raw dict to the same
``run_paper_trade_step`` entry. This module proves the three surfaces return
the *same parsed document* (and the same content hash) for:

* a default-single legacy call (no ``mode`` key),
* an explicit ``mode="single"`` legacy call,
* a ``mode="portfolio"`` + ``schema_version="pt-v2.0"`` call,
* the in-band mode/version rejection envelopes,
* malformed and missing-field requests.

The route surface itself is asserted unchanged (six existing paper routes, one
``POST /api/paper-trade/step``) and the saved-account advance route continues
to reject portfolio-only fields with the existing strict-body 422. The suite is
offline: the tool entry is wrapped with fixed fake loaders/calendar and every
surface reads the same fake bars.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cli.commands.paper_trade import add_parser as add_paper_parser
from cli.commands.paper_trade import dispatch as dispatch_paper
from src.api import paper_trade_routes
from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.portfolio.wire import compute_raw_input_hash
from src.tools.paper_trade.tool import PaperTradeStepTool
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

_US_DAY = "2026-10-20"
_US_PRIOR = "2026-10-19"
_PORTFOLIO_DAY = "2026-11-13"
_PORTFOLIO_PRIOR = "2026-11-12"
_PORTFOLIO_STATE_CASH = "200000.00"


class FakeLoader:
    """Deterministic loader double shared by the Agent, REST and CLI surfaces."""

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        name: str,
        fetches: list[tuple[str, tuple[str, ...], str, str]],
    ) -> None:
        self.name = name
        self._frames = frames
        self._fetches = fetches

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        self._fetches.append((self.name, tuple(codes), start_date, end_date))
        return {code: self._frames[code] for code in codes if code in self._frames}


class FakeCalendar:
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
        return pd.DataFrame(
            rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"]
        )


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
    payload: dict[str, Any] = {
        "account_id": "pa_surface",
        "market": "us",
        "account_state": {"cash": 1000.0, "positions": []},
        "orders": [{"symbol": "AAPL.US", "side": "buy", "qty": 10}],
        "from_date": _US_DAY,
        "to_date": _US_DAY,
    }
    payload.update(overrides)
    return payload


def _portfolio_payload(**overrides: Any) -> dict[str, Any]:
    """The shared pt-v2.0 fixture with a funded cn bucket and a marketable buy."""
    payload = json.loads(json.dumps(valid_portfolio_payload()))
    payload["portfolio_state"]["buckets"][0]["cash"] = _PORTFOLIO_STATE_CASH
    payload["orders"][0].pop("limit", None)
    payload.update(overrides)
    return payload


def _legacy_loaders(
    fetches: list[tuple[str, tuple[str, ...], str, str]],
) -> dict[str, FakeLoader]:
    return {
        "us": FakeLoader(
            {"AAPL.US": _frame([(_US_PRIOR, 10.0), (_US_DAY, 11.0)])},
            "legacy-fixture",
            fetches,
        )
    }


def _portfolio_loaders(
    fetches: list[tuple[str, tuple[str, ...], str, str]],
) -> dict[str, FakeLoader]:
    return {
        "cn_a": FakeLoader(
            {"600519.SH": _frame([(_PORTFOLIO_PRIOR, 1418.0), (_PORTFOLIO_DAY, 1421.0)])},
            "cn-fixture",
            fetches,
        ),
        "hk": FakeLoader(
            {"00700.HK": _frame([(_PORTFOLIO_PRIOR, 410.0), (_PORTFOLIO_DAY, 417.8)])},
            "hk-fixture",
            fetches,
        ),
        "us": FakeLoader(
            {"AAPL.US": _frame([(_PORTFOLIO_PRIOR, 340.0), (_PORTFOLIO_DAY, 343.46)])},
            "us-fixture",
            fetches,
        ),
    }


@pytest.fixture()
def surfaces(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch the single tool entry with fake data and expose a REST test app."""
    real_step = tool_module.run_paper_trade_step
    fetches: list[tuple[str, tuple[str, ...], str, str]] = []
    seen: list[Any] = []

    def offline_step(payload: Any, **kwargs: Any) -> str:
        # The public surfaces never inject seams; this wrapper supplies the same
        # deterministic fixtures to the real core for every one of them.
        seen.append(payload)
        if (
            isinstance(payload, dict)
            and payload.get("mode") == "portfolio"
            and payload.get("schema_version") == "pt-v2.0"
        ):
            return real_step(
                payload,
                loader=_portfolio_loaders(fetches),
                ch_client=None,
                calendar_client=FakeCalendar((_PORTFOLIO_DAY,)),
            )
        return real_step(
            payload,
            loader=_legacy_loaders(fetches)["us"],
            ch_client=None,
            calendar_client=None,
            limits_client=None,
        )

    monkeypatch.setattr(tool_module, "run_paper_trade_step", offline_step)
    app = FastAPI()
    paper_trade_routes.register_paper_trade_routes(app)
    return SimpleNamespace(
        real_step=real_step,
        client=TestClient(app),
        app=app,
        fetches=fetches,
        seen=seen,
    )


def _agent(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(PaperTradeStepTool().execute(**payload))


def _rest(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/paper-trade/step", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _cli(payload: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parser = argparse.ArgumentParser(prog="vibe-trading")
    commands = parser.add_subparsers(dest="command")
    add_paper_parser(commands)
    args = parser.parse_args(["paper", "step", str(path)])
    exit_code = dispatch_paper(args)
    captured = capsys.readouterr()
    assert captured.err == ""
    return exit_code, json.loads(captured.out)


def _canonical(document: dict[str, Any]) -> str:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(document).encode("utf-8")).hexdigest()


def _assert_three_surface_parity(
    surfaces: SimpleNamespace,
    payload: dict[str, Any],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    expected_exit: int,
) -> SimpleNamespace:
    before = len(surfaces.seen)
    agent = _agent(payload)
    rest = _rest(surfaces.client, payload)
    exit_code, cli = _cli(payload, tmp_path, capsys)

    assert exit_code == expected_exit
    assert agent == rest == cli
    assert _digest(agent) == _digest(rest) == _digest(cli)
    # Every surface handed the untouched raw payload to the single entry point.
    assert surfaces.seen[before:] == [payload, payload, payload]
    return SimpleNamespace(agent=agent, rest=rest, cli=cli, exit_code=exit_code)


# ── happy: one document on every surface ──


def test_default_single_step_parity(surfaces, tmp_path, capsys) -> None:
    parity = _assert_three_surface_parity(
        surfaces, _legacy_payload(), tmp_path, capsys, expected_exit=0
    )
    document = parity.agent

    assert document["tool"] == "paper_trade_step"
    assert document["schema_version"] == "pt-v1.1"
    assert document["market"] == "us"
    assert len(document["fills"]) == 1
    assert document["fills"][0]["symbol"] == "AAPL.US"
    assert {
        surface["received_state_hash"]
        for surface in (parity.agent, parity.rest, parity.cli)
    } == {document["received_state_hash"]}

    baseline = json.loads(
        surfaces.real_step(
            _legacy_payload(),
            loader=_legacy_loaders([])["us"],
            ch_client=None,
            calendar_client=None,
            limits_client=None,
        )
    )
    assert document == baseline


def test_explicit_single_step_matches_default_single(surfaces, tmp_path, capsys) -> None:
    default = _assert_three_surface_parity(
        surfaces, _legacy_payload(), tmp_path, capsys, expected_exit=0
    )
    explicit = _assert_three_surface_parity(
        surfaces,
        _legacy_payload(mode="single"),
        tmp_path,
        capsys,
        expected_exit=0,
    )

    assert explicit.agent == default.agent
    assert _digest(explicit.agent) == _digest(default.agent)


def test_pt_v2_portfolio_step_parity(surfaces, tmp_path, capsys) -> None:
    parity = _assert_three_surface_parity(
        surfaces, _portfolio_payload(), tmp_path, capsys, expected_exit=0
    )
    document = parity.agent

    assert document["status"] == "success"
    assert document["tool"] == "paper_trade_step"
    assert document["schema_version"] == "pt-v2.0"
    assert document["mode"] == "portfolio"
    assert document["complete"] is True
    assert [
        (fill["plan_order_id"], fill["bucket_id"], fill["price"])
        for fill in document["fills"]
    ] == [
        ("cn-buy-1", "cn", "1421.000000"),
        ("us-buy-1", "us", "343.460000"),
    ]

    # The document's own hash set is identical on every surface because the
    # three parsed documents are byte-identical above.
    assert set(document["hashes"]) == {
        "plan_hash",
        "planning_data_hash",
        "execution_data_fingerprint",
        "document_hash",
    }
    assert {
        _canonical(surface["hashes"])
        for surface in (parity.agent, parity.rest, parity.cli)
    } == {_canonical(document["hashes"])}
    assert len(document["hashes"]["document_hash"]) == 64

    baseline = json.loads(
        surfaces.real_step(
            _portfolio_payload(),
            loader=_portfolio_loaders([]),
            ch_client=None,
            calendar_client=FakeCalendar((_PORTFOLIO_DAY,)),
        )
    )
    assert document == baseline


# ── failure: the same in-band envelope on every surface ──


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"mode": "hybrid"}, "invalid_mode"),
        ({"mode": ["portfolio"]}, "invalid_mode"),
        ({"mode": "single", "schema_version": "pt-v2.0"}, "invalid_mode"),
        ({"schema_version": "pt-v2.0"}, "missing_mode"),
    ],
)
def test_invalid_mode_envelope_parity(
    surfaces, tmp_path, capsys, payload, reason
) -> None:
    parity = _assert_three_surface_parity(
        surfaces, payload, tmp_path, capsys, expected_exit=1
    )
    document = parity.agent

    assert document["status"] == "error"
    assert document["tool"] == "paper_trade_step"
    assert document["schema_version"] == "pt-v2.0"
    assert document["mode"] == "portfolio"
    assert document["code"] == "INVALID_REQUEST"
    assert (document["error"]["reason"], document["error"]["path"]) == (reason, "mode")
    assert document["error"]["detail"].count("input_sha256=") == 1
    assert document["error"]["detail"].endswith(
        f"; input_sha256={compute_raw_input_hash(payload)}"
    )
    assert "end_portfolio" not in document and "fills" not in document
    assert surfaces.fetches == []


@pytest.mark.parametrize(
    ("schema_version", "reason"),
    [
        (None, "missing_schema_version"),
        ("pt-v1.1", "invalid_schema_version"),
        ("pt-v2.1", "invalid_schema_version"),
    ],
)
def test_invalid_portfolio_version_envelope_parity(
    surfaces, tmp_path, capsys, schema_version, reason
) -> None:
    payload = _portfolio_payload()
    if schema_version is None:
        payload.pop("schema_version")
    else:
        payload["schema_version"] = schema_version

    parity = _assert_three_surface_parity(
        surfaces, payload, tmp_path, capsys, expected_exit=1
    )
    document = parity.agent

    assert document["code"] == "INVALID_REQUEST"
    assert (document["error"]["reason"], document["error"]["path"]) == (
        reason,
        "schema_version",
    )
    assert surfaces.fetches == []


def test_missing_portfolio_state_envelope_parity(surfaces, tmp_path, capsys) -> None:
    payload = _portfolio_payload()
    payload.pop("portfolio_state")

    parity = _assert_three_surface_parity(
        surfaces, payload, tmp_path, capsys, expected_exit=1
    )
    document = parity.agent

    assert document["code"] == "INVALID_REQUEST"
    assert (document["error"]["reason"], document["error"]["path"]) == (
        "invalid_field",
        "portfolio_state",
    )
    assert surfaces.fetches == []


def test_malformed_portfolio_state_envelope_parity(surfaces, tmp_path, capsys) -> None:
    parity = _assert_three_surface_parity(
        surfaces,
        _portfolio_payload(portfolio_state="not-a-state"),
        tmp_path,
        capsys,
        expected_exit=1,
    )
    document = parity.agent

    assert document["code"] == "INVALID_REQUEST"
    assert document["error"]["path"] == "portfolio_state"
    assert surfaces.fetches == []


def test_portfolio_mode_rejects_legacy_fields_on_every_surface(
    surfaces, tmp_path, capsys
) -> None:
    parity = _assert_three_surface_parity(
        surfaces,
        _portfolio_payload(market="us"),
        tmp_path,
        capsys,
        expected_exit=1,
    )
    document = parity.agent

    assert document["code"] == "INVALID_REQUEST"
    assert (document["error"]["reason"], document["error"]["path"]) == (
        "legacy_field_forbidden",
        "market",
    )
    assert surfaces.fetches == []


def test_missing_legacy_field_envelope_parity(surfaces, tmp_path, capsys) -> None:
    payload = _legacy_payload()
    payload.pop("market")

    parity = _assert_three_surface_parity(
        surfaces, payload, tmp_path, capsys, expected_exit=1
    )
    document = parity.agent

    assert document["status"] == "error"
    assert document["code"] == "INVALID_REQUEST"
    assert "market must be a string" in document["message"]
    assert surfaces.fetches == []


def test_single_mode_rejects_portfolio_fields_on_every_surface(
    surfaces, tmp_path, capsys
) -> None:
    parity = _assert_three_surface_parity(
        surfaces,
        _legacy_payload(mode="single", portfolio_state={"buckets": []}),
        tmp_path,
        capsys,
        expected_exit=1,
    )
    document = parity.agent

    assert document["code"] == "INVALID_REQUEST"
    assert (document["error"]["reason"], document["error"]["path"]) == (
        "portfolio_field_forbidden",
        "portfolio_state",
    )


# ── the REST surface itself is unchanged ──


def test_paper_route_table_is_unchanged() -> None:
    app = FastAPI()
    before = len(app.routes)
    paper_trade_routes.register_paper_trade_routes(app)

    paper_routes = sorted(
        (
            tuple(sorted(route.methods - {"HEAD", "OPTIONS"})),
            route.path,
        )
        for route in app.routes
        if "/api/paper" in getattr(route, "path", "")
    )

    assert paper_routes == [
        (("GET",), "/api/paper-accounts"),
        (("GET",), "/api/paper-accounts/{account_id}"),
        (("GET",), "/api/paper-accounts/{account_id}/history"),
        (("POST",), "/api/paper-accounts"),
        (("POST",), "/api/paper-accounts/{account_id}/advance"),
        (("POST",), "/api/paper-trade/step"),
    ]
    assert len(app.routes) == before + 6
    assert [route.path for route in app.routes].count("/api/paper-trade/step") == 1


def test_rest_non_object_body_keeps_the_declared_422_boundary(surfaces) -> None:
    # The Agent tool schema and both call sites take an object payload; the REST
    # route declares ``dict`` and FastAPI rejects a JSON array before dispatch.
    response = surfaces.client.post("/api/paper-trade/step", json=[])

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body"]


@pytest.mark.parametrize(
    "portfolio_field",
    ["portfolio_state", "fx_snapshots", "target_weights", "base_currency"],
)
def test_saved_account_advance_rejects_portfolio_only_fields(
    monkeypatch: pytest.MonkeyPatch, portfolio_field: str
) -> None:
    touched: list[str] = []

    class _ForbiddenAccounts:
        def __init__(self) -> None:
            touched.append("constructed")

    monkeypatch.setattr(paper_trade_routes, "PaperAccounts", _ForbiddenAccounts)
    app = FastAPI()
    paper_trade_routes.register_paper_trade_routes(app)
    client = TestClient(app)

    response = client.post(
        "/api/paper-accounts/pf-account/advance",
        json={
            "expected_revision": 0,
            "to_date": _PORTFOLIO_DAY,
            portfolio_field: {"buckets": []},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        item["type"] == "extra_forbidden" and item["loc"][-1] == portfolio_field
        for item in detail
    )
    assert touched == []
