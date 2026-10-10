"""PDF protection survives real CLI and agent confirmation surfaces."""

from __future__ import annotations

import json

import pytest

from src.channels.targets import DeliveryTarget
from src.scheduled_research import proposals, service
from src.scheduled_research.models import ScheduledResearchJob
from src.scheduled_research.store import ScheduledResearchJobStore
from src.tools.scheduled_research_tool import ScheduledResearchTool


@pytest.fixture
def email_target(monkeypatch):
    target = DeliveryTarget("reports", "Reports", "email", "reader@example.test")
    monkeypatch.setattr(service, "resolve_delivery_target", lambda _ref: target)
    monkeypatch.setattr("src.channels.targets.resolve_delivery_target", lambda _ref: target)
    return target


def test_protected_agent_proposal_keeps_choice_through_confirmation(
    tmp_path, monkeypatch, email_target
):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setattr(service, "email_pdf_password_configured", lambda: True, raising=False)
    monkeypatch.setattr(proposals, "scheduler_status", lambda: {"executable": True})
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    monkeypatch.setattr(proposals, "default_store", lambda: store)
    result = json.loads(ScheduledResearchTool().execute(
        action="propose_create",
        draft={
            "title": "Protected report",
            "source": {"kind": "prompt", "prompt": "Prepare a report"},
            "schedule": {"expression": "60000"},
            "end_at": None,
            "delivery": {"mode": "configured", "target_ref": "reports", "format": "pdf", "protect_pdf": True},
        },
    ))
    assert result["job"]["delivery"]["protect_pdf"] is True
    assert store.load() == {}
    committed = proposals.commit_proposal(result["proposal_id"])
    job = store.get(committed["committed_job_id"])
    assert job.protect_pdf is True
    assert service.public_job(job)["delivery"]["protect_pdf"] is True
    assert "pdf_password" not in json.dumps(job.to_dict())


def test_agent_schema_exposes_pdf_protection_choice():
    properties = ScheduledResearchTool.parameters["properties"]["draft"]["properties"]["delivery"]["properties"]
    assert properties["protect_pdf"]["type"] == "boolean"
    assert "pdf_password" not in properties


def test_cli_creates_protected_pdf_job(tmp_path, monkeypatch, capsys, email_target):
    from cli import _legacy

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setattr(service, "email_pdf_password_configured", lambda: True, raising=False)
    code = _legacy.main([
        "playbook", "create", "premarket-brief", "--delivery-target-ref", "reports",
        "--delivery-format", "pdf", "--protect-pdf", "--dry-run", "--json",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["protect_pdf"] is True
    assert payload["dry_run"] is True
    assert "pdf_password" not in payload


@pytest.mark.parametrize("channel,format", [("telegram", "pdf"), ("email", "html"), (None, "pdf")])
def test_protection_cannot_be_serialized_for_incompatible_delivery(channel, format):
    job = ScheduledResearchJob(
        id="invalid", prompt="report", schedule="60000", next_run_at=1,
        delivery_channel=channel, delivery_format=format, protect_pdf=True,
    )
    with pytest.raises(ValueError, match="PDF email"):
        job.to_dict()


def test_cli_protection_refuses_missing_password(monkeypatch, email_target):
    from cli.commands.research_playbook import build_job_from_playbook

    monkeypatch.setattr(service, "email_pdf_password_configured", lambda: False)
    job, error = build_job_from_playbook(
        "premarket-brief", delivery_target_ref="reports", delivery_format="pdf", protect_pdf=True
    )
    assert job is None
    assert "no PDF password" in error


def test_removed_password_refuses_proposal_commit(tmp_path, monkeypatch, email_target):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setattr(service, "email_pdf_password_configured", lambda: True)
    monkeypatch.setattr(proposals, "scheduler_status", lambda: {"executable": True})
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    monkeypatch.setattr(proposals, "default_store", lambda: store)
    draft = {
        "title": "Protected report", "source": {"kind": "prompt", "prompt": "report"},
        "schedule": {"expression": "60000"}, "end_at": None,
        "delivery": {"mode": "configured", "target_ref": "reports", "format": "pdf", "protect_pdf": True},
    }
    result = proposals.propose_create(draft)
    monkeypatch.setattr(service, "email_pdf_password_configured", lambda: False)
    with pytest.raises(proposals.ProposalError, match="no PDF password"):
        proposals.commit_proposal(result["proposal_id"])
    assert store.load() == {}


@pytest.mark.parametrize("enabled,label", [(True, "开启"), (False, "关闭")])
def test_cli_confirmation_shows_protection_choice(enabled, label):
    from io import StringIO

    from rich.console import Console

    from cli.main import _render_scheduled_proposal

    output = StringIO()
    _render_scheduled_proposal(Console(file=output, color_system=None), {
        "operation": "create",
        "job": {"delivery": {"channel": "email", "format": "pdf", "protect_pdf": enabled}},
    })
    assert f"PDF 密码保护: {label}" in output.getvalue()
