"""``vibe-trading paper step`` parity with REST and the Agent.

The CLI keeps exactly the existing ``paper`` command surface and forwards the
caller-owned JSON file to the same ``run_paper_trade_step`` entry as the Agent
tool and ``POST /api/paper-trade/step``. These tests invoke the repository's
direct CLI seam (``add_parser`` + ``dispatch``), capture the printed document,
and assert parsed-output and hash parity for legacy and pt-v2.0 calls, the same
in-band error envelopes, and no command/flag expansion (no portfolio flag on
``paper advance``, no ``--mode`` switch on ``paper step``).
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
        "account_id": "pa_cli_surface",
        "market": "us",
        "account_state": {"cash": 1000.0, "positions": []},
        "orders": [{"symbol": "AAPL.US", "side": "buy", "qty": 10}],
        "from_date": _US_DAY,
        "to_date": _US_DAY,
    }
    payload.update(overrides)
    return payload


def _portfolio_payload(**overrides: Any) -> dict[str, Any]:
    payload = json.loads(json.dumps(valid_portfolio_payload()))
    payload["portfolio_state"]["buckets"][0]["cash"] = _PORTFOLIO_STATE_CASH
    payload["orders"][0].pop("limit", None)
    payload.update(overrides)
    return payload


def _loaders(fetches: list[tuple[str, tuple[str, ...], str, str]]) -> dict[str, FakeLoader]:
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


def _legacy_loader(
    fetches: list[tuple[str, tuple[str, ...], str, str]],
) -> FakeLoader:
    return FakeLoader(
        {"AAPL.US": _frame([(_US_PRIOR, 10.0), (_US_DAY, 11.0)])},
        "legacy-fixture",
        fetches,
    )


@pytest.fixture()
def surfaces(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    real_step = tool_module.run_paper_trade_step
    fetches: list[tuple[str, tuple[str, ...], str, str]] = []
    seen: list[Any] = []

    def offline_step(payload: Any, **kwargs: Any) -> str:
        seen.append(payload)
        if (
            isinstance(payload, dict)
            and payload.get("mode") == "portfolio"
            and payload.get("schema_version") == "pt-v2.0"
        ):
            return real_step(
                payload,
                loader=_loaders(fetches),
                ch_client=None,
                calendar_client=FakeCalendar((_PORTFOLIO_DAY,)),
            )
        return real_step(
            payload,
            loader=_legacy_loader(fetches),
            ch_client=None,
            calendar_client=None,
            limits_client=None,
        )

    monkeypatch.setattr(tool_module, "run_paper_trade_step", offline_step)
    app = FastAPI()
    paper_trade_routes.register_paper_trade_routes(app)
    return SimpleNamespace(
        client=TestClient(app), fetches=fetches, app=app, seen=seen, real_step=real_step
    )


def _agent(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(PaperTradeStepTool().execute(**payload))


def _rest(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/paper-trade/step", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _paper_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vibe-trading")
    commands = parser.add_subparsers(dest="command")
    add_paper_parser(commands)
    return parser


def _cli(
    payload: dict[str, Any] | str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, Any]:
    path = tmp_path / "payload.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    args = _paper_parser().parse_args(["paper", "step", str(path)])
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


def _parity(
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
    assert _digest(agent) == _digest(cli)
    assert surfaces.seen[before:] == [payload, payload, payload]
    return SimpleNamespace(agent=agent, rest=rest, cli=cli, exit_code=exit_code)


# ── happy: the CLI prints the same document as Agent and REST ──


def test_cli_default_single_parity(surfaces, tmp_path, capsys) -> None:
    parity = _parity(surfaces, _legacy_payload(), tmp_path, capsys, expected_exit=0)

    assert parity.cli["schema_version"] == "pt-v1.1"
    assert parity.cli["market"] == "us"
    assert parity.cli["received_state_hash"] == parity.agent["received_state_hash"]


def test_cli_explicit_single_parity(surfaces, tmp_path, capsys) -> None:
    default = _parity(surfaces, _legacy_payload(), tmp_path, capsys, expected_exit=0)
    explicit = _parity(
        surfaces,
        _legacy_payload(mode="single"),
        tmp_path,
        capsys,
        expected_exit=0,
    )

    assert explicit.cli == default.cli
    assert _digest(explicit.cli) == _digest(default.cli)


def test_cli_pt_v2_portfolio_parity(surfaces, tmp_path, capsys) -> None:
    parity = _parity(
        surfaces, _portfolio_payload(), tmp_path, capsys, expected_exit=0
    )

    assert parity.cli["status"] == "success"
    assert parity.cli["schema_version"] == "pt-v2.0"
    assert parity.cli["mode"] == "portfolio"
    assert parity.cli["complete"] is True
    assert parity.cli["hashes"] == parity.agent["hashes"] == parity.rest["hashes"]
    assert len(parity.cli["hashes"]["document_hash"]) == 64

    baseline = json.loads(
        surfaces.real_step(
            _portfolio_payload(),
            loader=_loaders([]),
            ch_client=None,
            calendar_client=FakeCalendar((_PORTFOLIO_DAY,)),
        )
    )
    assert parity.cli == baseline


# ── failure: the same declared envelope and exit code ──


@pytest.mark.parametrize(
    ("payload", "reason", "path"),
    [
        ({"mode": "batch"}, "invalid_mode", "mode"),
        ({"mode": "portfolio", "schema_version": "pt-v1.1"}, "invalid_schema_version", "schema_version"),
        ({"mode": "portfolio"}, "missing_schema_version", "schema_version"),
        ({"schema_version": "pt-v2.0"}, "missing_mode", "mode"),
    ],
)
def test_cli_error_envelope_parity(
    surfaces, tmp_path, capsys, payload, reason, path
) -> None:
    parity = _parity(surfaces, payload, tmp_path, capsys, expected_exit=1)

    assert parity.cli["status"] == "error"
    assert parity.cli["code"] == "INVALID_REQUEST"
    assert (parity.cli["error"]["reason"], parity.cli["error"]["path"]) == (reason, path)
    assert parity.cli["error"]["detail"].count("input_sha256=") == 1
    assert parity.cli["error"]["detail"].endswith(
        f"; input_sha256={compute_raw_input_hash(payload)}"
    )
    assert surfaces.fetches == []


def test_cli_missing_field_envelope_parity(surfaces, tmp_path, capsys) -> None:
    payload = _portfolio_payload()
    payload.pop("portfolio_state")
    parity = _parity(surfaces, payload, tmp_path, capsys, expected_exit=1)

    assert parity.cli["code"] == "INVALID_REQUEST"
    assert parity.cli["error"]["path"] == "portfolio_state"


def test_cli_malformed_json_file_keeps_the_declared_error(tmp_path, capsys) -> None:
    exit_code, reply = _cli("{not valid json", tmp_path, capsys)

    assert exit_code == 1
    assert list(reply) == ["error"]
    assert "Expecting" in reply["error"]


# ── the command surface itself is unchanged ──


def test_paper_command_surface_is_unchanged() -> None:
    from cli._legacy import _build_parser

    parser = _build_parser()
    top = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    paper = top.choices["paper"]
    commands = next(
        action
        for action in paper._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert sorted(commands.choices) == [
        "advance",
        "create",
        "history",
        "list",
        "show",
        "step",
    ]
    assert not {"portfolio", "saved", "save"} & set(commands.choices)


def test_paper_step_accepts_no_mode_switch(tmp_path) -> None:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(_legacy_payload()), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        _paper_parser().parse_args(["paper", "step", str(path), "--mode", "portfolio"])

    assert excinfo.value.code == 2


def test_paper_advance_rejects_portfolio_only_flags(tmp_path, capsys) -> None:
    orders = tmp_path / "orders.json"
    orders.write_text("[]", encoding="utf-8")

    for flag in ("--portfolio-state", "--base-currency", "--fx-snapshots"):
        with pytest.raises(SystemExit) as excinfo:
            _paper_parser().parse_args(
                [
                    "paper",
                    "advance",
                    "pf-account",
                    "--revision",
                    "0",
                    "--to-date",
                    _PORTFOLIO_DAY,
                    "--orders",
                    str(orders),
                    flag,
                    "{}",
                ]
            )
        assert excinfo.value.code == 2

    assert "unrecognized arguments" in capsys.readouterr().err
