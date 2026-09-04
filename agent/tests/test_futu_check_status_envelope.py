"""The Futu health report must carry the envelope ``/live/status`` consumes.

``check_status`` used to return only ``status``/``error``. The Web UI reads
``connection_state`` through a closed vocabulary in ``live_routes`` and treats
anything other than ``connected``/``ready`` as unavailable, so a working OpenD
connection rendered as down. These tests pin the envelope against the ACTUAL
consumer's vocabulary rather than against a hand-copied list, so widening the
vocabulary on one side without the other fails here.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.api.live_routes import _CONNECTION_STATES, _ERROR_CODES
from src.trading.connectors.futu import sdk as futu_sdk


@pytest.fixture()
def cfg() -> Any:
    return futu_sdk.FutuConfig()


def _patch(monkeypatch, *, port_open=True, installed=True, snapshot=None, raises=None):
    monkeypatch.setattr(futu_sdk, "tcp_port_open", lambda host, port: port_open)
    monkeypatch.setattr(futu_sdk, "futu_available", lambda: installed)

    def _snapshot(config=None):
        if raises is not None:
            raise raises
        return snapshot or {"acc_id": 42}

    monkeypatch.setattr(futu_sdk, "get_account_snapshot", _snapshot)


def test_healthy_report_is_connected_and_timestamped(monkeypatch, cfg):
    _patch(monkeypatch)
    report = futu_sdk.check_status(cfg)
    assert report["status"] == "ok"
    assert report["connection_state"] == "connected"
    assert report["error_code"] is None
    assert report["error"] is None
    assert report["last_checked_at"]


@pytest.mark.parametrize(
    ("kwargs", "expected_code"),
    [
        ({"port_open": False}, "network_unreachable"),
        ({"installed": False}, "sdk_missing"),
        ({"raises": RuntimeError("acc list failed")}, "broker_error"),
    ],
)
def test_failure_reports_carry_a_closed_vocabulary_code(
    monkeypatch, cfg, kwargs, expected_code
):
    _patch(monkeypatch, **kwargs)
    report = futu_sdk.check_status(cfg)
    assert report["status"] == "error"
    assert report["connection_state"] == "error"
    assert report["error_code"] == expected_code
    assert report["error"]


def test_every_emitted_value_survives_the_route_vocabulary(monkeypatch, cfg):
    """The route drops any value outside its frozensets — none may be dropped."""
    cases = [{}, {"port_open": False}, {"installed": False},
             {"raises": RuntimeError("boom")}]
    for kwargs in cases:
        _patch(monkeypatch, **kwargs)
        report = futu_sdk.check_status(cfg)
        assert report["connection_state"] in _CONNECTION_STATES
        if report["error_code"] is not None:
            assert report["error_code"] in _ERROR_CODES
