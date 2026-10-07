"""Security regressions for live mandate proposal commit boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import src.live.paths as paths
from src.live.mandate.commit import CommitError, _profile_to_hard_caps, commit_mandate, save_proposal
from src.live.enforcement import OrderIntent, check_mandate
from src.live.mandate.model import InstrumentType
from src.live.mandate.store import load_mandate

pytestmark = pytest.mark.unit


def _proposal(proposal_id: str) -> dict[str, object]:
    """Return a minimal valid proposal payload for commit_mandate."""
    return {
        "proposal_id": proposal_id,
        "account": {"broker": "robinhood"},
        "ceilings": {
            "max_order_notional_usd": 100.0,
            "max_total_exposure_usd": 500.0,
            "max_trades_per_day": 2,
            "leverage": "none",
        },
        "profiles": [
            {
                "ordinal": 1,
                "account_funding_usd": 500.0,
                "max_order_usd": 100.0,
                "max_total_exposure_usd": 500.0,
                "daily_trade_cap": 2,
                "leverage": "none",
                "instruments": ["equity"],
                "asset_classes": ["us_equity"],
                "exclude_symbols": ["GME"],
            }
        ],
    }


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point live-channel state at a temp runtime root."""
    monkeypatch.setattr(paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


def test_commit_mandate_accepts_saved_bare_proposal_id(live_runtime: Path) -> None:
    """The normal propose -> commit flow still works for opaque proposal ids."""
    proposal_id = "mp_" + "a" * 32
    save_proposal(_proposal(proposal_id))

    result = commit_mandate(
        proposal_id=proposal_id,
        ordinal=1,
        adjustments=None,
        consent_ack=True,
        broker="robinhood",
        account_ref="acct-ok",
    )

    assert result["broker"] == "robinhood"
    mandate_path = live_runtime / "live" / "robinhood" / "mandate.json"
    assert mandate_path.is_file()
    mandate = json.loads(mandate_path.read_text(encoding="utf-8"))
    assert mandate["consent"]["account_ref"] == "acct-ok"


def test_save_proposal_rejects_path_shaped_proposal_id(live_runtime: Path) -> None:
    """Only generated mp_<hex> ids may be persisted as proposal records."""
    with pytest.raises(ValueError, match="proposal_id"):
        save_proposal(_proposal("../outside"))

    assert not (live_runtime / "outside.json").exists()


def test_commit_mandate_rejects_proposal_id_traversal_to_external_json(live_runtime: Path) -> None:
    """A commit must not resolve proposal_id outside the broker proposals dir.

    Before the fix, _load_proposal() joined ``proposal_id`` directly into
    ``<live>/<broker>/proposals/{proposal_id}.json``. A path-shaped id could
    escape that directory and load an attacker-controlled JSON file, then write
    a live mandate from it.
    """
    from src.live.paths import broker_dir

    proposals_dir = broker_dir("robinhood") / "proposals"
    proposals_dir.mkdir(parents=True)

    external = live_runtime / "uploads" / "crafted_proposal.json"
    external.parent.mkdir(parents=True)
    marker = "VIBE_TRAVERSAL_PROPOSAL_SHOULD_NOT_COMMIT"
    payload = _proposal("mp_" + "b" * 32)
    payload["profiles"][0]["exclude_symbols"] = [marker]  # type: ignore[index]
    external.write_text(json.dumps(payload), encoding="utf-8")

    # commit_mandate appends ".json", so omit the suffix from the relative path.
    traversal_id = os.path.relpath(external.with_suffix(""), proposals_dir)
    assert ".." in Path(traversal_id).parts

    with pytest.raises(CommitError, match="not live"):
        commit_mandate(
            proposal_id=traversal_id,
            ordinal=1,
            adjustments=None,
            consent_ack=True,
            broker="robinhood",
            account_ref="acct-traversal",
        )

    mandate_path = broker_dir("robinhood") / "mandate.json"
    assert not mandate_path.exists()


@pytest.mark.parametrize("exposure", [0.0, 50.0])
def test_commit_mandate_persists_an_explicit_exposure_narrowing(live_runtime: Path, exposure: float) -> None:
    """A legal narrowing to zero exposure must not be widened back on persist.

    _resolve_profile allows an adjustment to narrow max_total_exposure_usd down
    to 0 (any value <= the rendered limit is a legal narrowing). Before the
    fix, _profile_to_hard_caps used the ``x or default`` idiom, which treated
    that explicit 0 the same as "field missing" and silently substituted the
    rendered max_order_usd instead, so the persisted mandate authorized more
    exposure than the user consented to.
    """
    proposal_id = "mp_" + "c" * 32
    save_proposal(_proposal(proposal_id))

    result = commit_mandate(
        proposal_id=proposal_id,
        ordinal=1,
        adjustments={"max_total_exposure_usd": exposure},
        consent_ack=True,
        broker="robinhood",
        account_ref="acct-zero",
    )

    assert result["resolved_profile"]["max_total_exposure_usd"] == exposure
    mandate_path = live_runtime / "live" / "robinhood" / "mandate.json"
    mandate = json.loads(mandate_path.read_text(encoding="utf-8"))
    assert mandate["hard_caps"]["max_total_exposure_usd"] == exposure

    # Read the persisted contract through the same loader the order gates use.
    committed = load_mandate("robinhood")
    assert committed is not None
    breach = check_mandate(
        committed,
        OrderIntent("AAPL", "buy", 25.0, None, InstrumentType.EQUITY),
        [], {"equity": 500.0},
        broker="robinhood", remote_tool="place_equity_order", daily_count=0,
    )
    if exposure == 0:
        assert breach is not None
        assert breach.limit == "max_total_exposure_usd"
        assert breach.limit_value == 0.0
    else:
        assert breach is None


@pytest.mark.parametrize(
    "profile,expected",
    [
        ({}, (0.0, 0.0, 0.0)),
        ({"max_order_usd": 100}, (100.0, 100.0, 100.0)),
        ({"max_order_usd": 100, "max_total_exposure_usd": 0}, (0.0, 100.0, 0.0)),
        ({"max_order_usd": 100, "account_funding_usd": 0}, (0.0, 100.0, 0.0)),
        ({"max_order_usd": 0, "account_funding_usd": 500}, (500.0, 0.0, 500.0)),
        ({"max_order_usd": 100, "account_funding_usd": 500, "max_total_exposure_usd": 0}, (500.0, 100.0, 0.0)),
        ({"max_order_usd": 100, "account_funding_usd": 0, "max_total_exposure_usd": 50}, (0.0, 100.0, 50.0)),
        ({"max_order_usd": None, "account_funding_usd": None, "max_total_exposure_usd": None}, (0.0, 0.0, 0.0)),
    ],
)
def test_cap_mapping_distinguishes_zero_from_an_unspecified_limit(profile, expected) -> None:
    caps = _profile_to_hard_caps(profile)
    assert (caps["account_funding_usd"], caps["max_order_notional_usd"], caps["max_total_exposure_usd"]) == expected
