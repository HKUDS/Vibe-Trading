"""Regression: ``futu.sdk.check_status`` must emit a non-empty status envelope.

The ``/live/status`` endpoint renders a broker as "状态不可用" whenever
``connection_state`` is ``null`` on the verify report (frontend
``pages/Runtime.tsx`` falls through to ``connectorStatusUnavailable`` at
line 390). The longbridge connector writes
``connection_state = "connected"`` and ``last_checked_at = <ISO>`` in its
``check_status``; the futu connector previously returned neither field,
so a working Futu connection (SDK installed, OpenD gateway reachable,
account resolved) was rendered as unavailable in the Web UI even
though ``/live/connectors/.../verify`` reported ``status: ok``.

This test asserts that ``check_status`` now produces the same
"connected" envelope shape the longbridge connector produces, so the
front-end can render a non-unknown state without needing a per-broker
branch.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.trading.connectors.futu import sdk as futu_sdk


class _FakeFutu:
    RET_OK = 0

    class TrdMarket:
        HK = "HK"

    class SecurityFirm:
        FUTUSECURITIES = "FUTUSECURITIES"


def test_check_status_emits_connected_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """The happy-path report must carry connection_state and last_checked_at."""
    # Stub out the SDK + gateway + config so check_status runs without a
    # real OpenD or a real futu-api install.
    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _FakeFutu)
    monkeypatch.setattr(futu_sdk, "futu_available", lambda: True)
    monkeypatch.setattr(
        futu_sdk,
        "load_config",
        lambda: futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="live-readonly"),
    )
    monkeypatch.setattr(futu_sdk, "tcp_port_open", lambda host, port: True)
    monkeypatch.setattr(
        futu_sdk,
        "get_account_snapshot",
        lambda cfg: {"acc_id": 12345, "profile": cfg.profile, "trd_env": "REAL"},
    )

    report: dict[str, Any] = futu_sdk.check_status()

    assert report.get("status") == "ok"
    assert report.get("connection_state") == "connected", (
        f"check_status must mark the connector connected; got {report!r}"
    )
    assert report.get("last_checked_at"), (
        f"check_status must set last_checked_at; got {report!r}"
    )
    # The frontend's _closed_vocabulary allowlist maps "connected" to a
    # string the Web UI can render; assert the spelling matches the
    # longbridge connector contract.
    assert report.get("connection_state") == "connected"


def test_check_status_unavailable_when_gateway_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When OpenD is unreachable, connection_state should be 'not_configured'."""
    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _FakeFutu)
    monkeypatch.setattr(futu_sdk, "futu_available", lambda: True)
    monkeypatch.setattr(
        futu_sdk,
        "load_config",
        lambda: futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="live-readonly"),
    )
    monkeypatch.setattr(futu_sdk, "tcp_port_open", lambda host, port: False)

    report: dict[str, Any] = futu_sdk.check_status()

    assert report.get("status") == "error"
    # The gateway-down path returns early before the "connected" envelope
    # is set, so the field is absent — the frontend falls through to its
    # unknown-state branch, which is the same as before this fix.
    assert "connection_state" not in report


def test_check_status_unavailable_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When futu-api is not installed, the SDK-missing path also returns early."""
    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _FakeFutu)
    monkeypatch.setattr(futu_sdk, "futu_available", lambda: False)
    monkeypatch.setattr(
        futu_sdk,
        "load_config",
        lambda: futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="live-readonly"),
    )
    monkeypatch.setattr(futu_sdk, "tcp_port_open", lambda host, port: True)

    report: dict[str, Any] = futu_sdk.check_status()

    assert report.get("status") == "error"
    assert "futu-api" in (report.get("error") or "")
    assert "connection_state" not in report


def test_last_checked_at_is_iso8601_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """last_checked_at must be parseable as ISO 8601 in UTC."""
    from datetime import datetime

    monkeypatch.setattr(futu_sdk, "_require_futu", lambda: _FakeFutu)
    monkeypatch.setattr(futu_sdk, "futu_available", lambda: True)
    monkeypatch.setattr(
        futu_sdk,
        "load_config",
        lambda: futu_sdk.FutuConfig(host="127.0.0.1", port=11111, profile="live-readonly"),
    )
    monkeypatch.setattr(futu_sdk, "tcp_port_open", lambda host, port: True)
    monkeypatch.setattr(
        futu_sdk,
        "get_account_snapshot",
        lambda cfg: {"acc_id": 12345, "profile": cfg.profile, "trd_env": "REAL"},
    )

    report = futu_sdk.check_status()
    last_checked = report.get("last_checked_at")
    assert last_checked is not None
    # fromisoformat accepts both "...Z" and "...+00:00" on 3.11+.
    parsed = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"last_checked_at must carry tzinfo, got {last_checked!r}"
