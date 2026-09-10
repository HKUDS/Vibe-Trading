"""Tests for the Toss Securities (토스증권) direct-SDK trading connector.

Mirrors ``test_sdk_connectors.py``: exercises profile registration, the
fully-read-only guard (Toss documents no verifiable sandbox, following the
Trading 212 precedent), config resolution, read/write classification, secret
redaction, and service dispatch degrading cleanly when nothing is configured
— no live credentials or network access required.
"""

from __future__ import annotations

import pytest

from src.live.classification import ToolClass
from src.trading import profiles, service
from src.trading.connectors.toss import sdk as toss
from src.trading.connectors.toss.classification import TOSS_TOOL_CLASS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Profile registration
# --------------------------------------------------------------------------- #


def test_toss_sdk_profile_registered() -> None:
    ids = {p.id for p in profiles.list_profiles()}
    assert "toss-live-sdk-readonly" in ids


def test_toss_exposes_no_paper_or_live_trade_profile() -> None:
    """Toss documents no verifiable sandbox — every profile is read-only,
    mirroring the Trading 212 precedent (never even a paper-trade profile)."""
    toss_profiles = [p for p in profiles.list_profiles() if p.connector == "toss"]
    assert toss_profiles
    for profile in toss_profiles:
        assert profile.readonly is True
        assert not any(".place" in cap for cap in profile.capabilities)


# --------------------------------------------------------------------------- #
# Order refusal (fully read-only, like Trading 212)
# --------------------------------------------------------------------------- #


def test_toss_place_order_always_refused() -> None:
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1", profile="live-readonly")
    result = toss.place_order(cfg, symbol="005930", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "read-only" in result["error"]
    assert result["paper_guard"] == "read_only_no_runtime_discriminator"


def test_toss_cancel_order_always_refused() -> None:
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1")
    result = toss.cancel_order(cfg, "ORD1")
    assert result["status"] == "error"
    assert "read-only" in result["error"]


def test_toss_place_order_refused_even_when_declared_paper() -> None:
    """No verified sandbox exists, so even a 'paper'-declared profile refuses —
    unlike Dhan/Upbit, there is no honest local simulation to fall back to."""
    cfg = toss.TossConfig(client_id="c", client_secret="s", account_seq="1", profile="paper")
    result = toss.place_order(cfg, symbol="005930", side="buy", quantity=1)
    assert result["status"] == "error"
    assert "disabled" in result["error"]


def test_toss_invalid_profile_rejected() -> None:
    with pytest.raises(toss.TossConfigError):
        toss.TossConfig.from_mapping({"profile": "go-live"})


# --------------------------------------------------------------------------- #
# Redaction / service dispatch / classification
# --------------------------------------------------------------------------- #


def test_toss_redacts_client_secret() -> None:
    cfg = toss.TossConfig(client_id="client-1234", client_secret="super-secret", account_seq="1")
    pub = toss._public_config(cfg)
    assert "super-secret" not in str(pub)
    assert pub["client_id"].endswith("***")
    assert pub["client_secret"] == "***redacted***"


def test_toss_service_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(toss, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("toss-live-sdk-readonly")
    assert result["status"] == "error"
    assert result["connector"] == "toss"
    assert result["transport"] == "broker_sdk"


def test_toss_order_ops_classified_write() -> None:
    for name in ("place_order", "cancel_order"):
        assert TOSS_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("get_positions", "get_account_snapshot"):
        assert TOSS_TOOL_CLASS[name] is ToolClass.READ
