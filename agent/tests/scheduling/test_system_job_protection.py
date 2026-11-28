"""System-job protection across the six caller-provided-id entry points.

A system job carries an id with the ``system:`` prefix
(:data:`src.scheduling.system_jobs.SYSTEM_JOB_ID_PREFIX`) and is seeded and
repaired only by ``ensure_system_jobs``. No user-facing surface may delete,
modify, create or replace one. The six entries audited here:

1. ``DELETE /scheduled-runs/{job_id}`` — REST-visible behavior is the
   path-parameter **400** (``_validate_path_param`` rejects the ':' every
   system id carries BEFORE the handler runs); the handler-level 403 guard is
   defense in depth for non-REST callers.
2. ``PATCH /scheduled-runs/{job_id}`` — same 400-before-handler reality.
3. ``propose_create`` / ``build_job_from_draft`` — a draft id that is
   ``system:``-prefixed or outside ``SAFE_JOB_ID_RE`` is refused at propose.
4. ``commit_proposal`` — the AUTHORITATIVE guard: proposal files live under
   ``<runtime root>/scheduled_research/proposals/`` and can be hand-written
   or edited between propose and commit, so commit re-reads the store and
   refuses any system-job create/replace/cancel with the store untouched.
5. ``POST /scheduled-runs`` body — the request model has no ``source_type`` /
   ``executor_kind`` field; escalation keys are ignored and the job lands as
   a plain prompt job (pinned), and a forged ``system:`` id dies on the
   create-path id rule (422).
6. CLI ``vibe-trading playbook create <slug> --id <id>`` — writes the store
   directly, bypassing every route; the guard mirrors the REST playbook
   route's safe-id validation.

Normal-job behavior is asserted byte-identical throughout: the 404 detail
text ``scheduled run <id> not found``, the truly-empty 204 delete body, and
the playbook create contract (``source_type == "playbook"``).
"""

from __future__ import annotations

import cli.commands.dispatch as _cmd_dispatch

import json
import time
import uuid
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

import api_server
from cli.commands.research_playbook import build_job_from_playbook
from src.api import scheduled_routes
from src.scheduled_research import proposals
from src.scheduled_research.models import JobStatus, ScheduledResearchJob
from src.scheduled_research.proposals import ProposalError
from src.scheduled_research.store import ScheduledResearchJobStore
from src.scheduling.system_jobs import SYSTEM_JOB_ID_PREFIX, is_system_job_id

SYSTEM_ID = f"{SYSTEM_JOB_ID_PREFIX}memory-consolidation"
SAMPLE_SLUG = "premarket-brief"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _hermetic_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore any user playbook directory on the developer's machine."""
    monkeypatch.delenv("VIBE_TRADING_PLAYBOOK_DIR", raising=False)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduledResearchJobStore:
    """Isolate the route module's store singleton onto a temp file."""
    isolated = ScheduledResearchJobStore(path=tmp_path / "scheduled_jobs.json")
    monkeypatch.setattr(scheduled_routes, "_scheduled_research_store", isolated)
    return isolated


@pytest.fixture
def client(store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the runtime root at ``tmp_path`` so CLI/proposals write temp files."""
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    return tmp_path


def _seed_system_job(store: ScheduledResearchJobStore, job_id: str = SYSTEM_ID) -> ScheduledResearchJob:
    """Insert a system row the way ``ensure_system_jobs`` would."""
    job = ScheduledResearchJob(
        id=job_id,
        title="Memory consolidation",
        prompt="",
        schedule="3600000",
        next_run_at=1_700_000_000_000,
        status=JobStatus.PENDING,
        created_at=1_700_000_000_000,
        source_type="system",
        executor_kind="internal",
        internal_callable="memory.consolidate",
    )
    store.upsert(job)
    return job


def _seed_normal_job(store: ScheduledResearchJobStore, job_id: str = "job-normal") -> ScheduledResearchJob:
    job = ScheduledResearchJob(
        id=job_id,
        prompt="scan momentum names",
        schedule="60000",
        next_run_at=1_700_000_000_000,
        status=JobStatus.PENDING,
        created_at=1_700_000_000_000,
    )
    store.upsert(job)
    return job


def _store_bytes(store: ScheduledResearchJobStore) -> bytes | None:
    return store.path.read_bytes() if store.path.exists() else None


def _wire_proposals(
    monkeypatch: pytest.MonkeyPatch, store: ScheduledResearchJobStore
) -> None:
    monkeypatch.setattr(proposals, "default_store", lambda: store)
    monkeypatch.setattr(
        proposals,
        "scheduler_status",
        lambda: {"enabled": True, "running": True, "executable": True},
    )


def _write_proposal(home: Path, payload: dict) -> str:
    directory = home / "scheduled_research" / "proposals"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['proposal_id']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload["proposal_id"]


def _handwritten_payload(operation: str, **extra: object) -> dict:
    now = int(time.time() * 1000)
    payload: dict = {
        "proposal_id": f"srp_{uuid.uuid4().hex}",
        "operation": operation,
        "status": "pending",
        "session_id": None,
        "created_at": now,
        "expires_at": now + 15 * 60 * 1000,
    }
    payload.update(extra)
    return payload


def _run_cli(argv: List[str]) -> int:
    """Drive the real argparse dispatcher, returning its exit code."""

    return int(_cmd_dispatch.main(argv))


# ---------------------------------------------------------------------------
# ②b — structural pin: system ids are unforgeable at the regex level
# ---------------------------------------------------------------------------


def test_safe_job_id_regex_rejects_system_ids() -> None:
    from src.api.helpers import _SAFE_PATH_PARAM_RE
    from src.scheduling.system_jobs import SAFE_JOB_ID_RE, is_safe_job_id

    assert SAFE_JOB_ID_RE.match(SYSTEM_ID) is None
    assert SAFE_JOB_ID_RE.fullmatch(SYSTEM_ID) is None
    assert is_safe_job_id(SYSTEM_ID) is False
    assert _SAFE_PATH_PARAM_RE.match(SYSTEM_ID) is None
    assert is_system_job_id(SYSTEM_ID) is True


def test_shared_job_id_rule_cannot_drift_from_host_path_param_rule() -> None:
    # The structural anti-forgery guarantee holds only while BOTH grammars
    # reject ':' — pin them to the same pattern so a one-sided edit fails.
    from src.api.helpers import _SAFE_PATH_PARAM_RE
    from src.scheduling.system_jobs import SAFE_JOB_ID_RE

    assert SAFE_JOB_ID_RE.pattern == _SAFE_PATH_PARAM_RE.pattern


def test_route_registration_order_keeps_static_paths_before_job_id() -> None:
    scheduled = [
        (index, route)
        for index, route in enumerate(api_server.app.routes)
        if hasattr(route, "path") and route.path.startswith("/scheduled-runs")
    ]

    def _first(path: str, method: str | None = None) -> int:
        for index, route in scheduled:
            if route.path == path and (method is None or method in route.methods):
                return index
        raise AssertionError(f"route {path} ({method}) not registered")

    # The GET-single {job_id} route must stay registered AFTER /status and
    # /playbooks so those literal segments are never consumed as a job id.
    get_single = _first("/scheduled-runs/{job_id}", "GET")
    assert _first("/scheduled-runs/status") < get_single
    assert _first("/scheduled-runs/playbooks") < get_single
    assert _first("/scheduled-runs/playbooks/{slug}", "GET") < get_single
    assert _first("/scheduled-runs/playbooks/{slug}", "POST") < get_single


def test_tool_draft_schema_forbids_unknown_keys() -> None:
    from src.tools.scheduled_research_tool import ScheduledResearchTool

    draft_schema = ScheduledResearchTool.parameters["properties"]["draft"]
    assert draft_schema["additionalProperties"] is False
    assert "id" not in draft_schema["properties"]


# ---------------------------------------------------------------------------
# Entries 1+2 — DELETE / PATCH routes: REST-visible 400, store untouched
# ---------------------------------------------------------------------------


def test_delete_system_job_returns_400_and_store_unchanged(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    _seed_system_job(store)
    before = _store_bytes(store)

    response = client.delete(f"/scheduled-runs/{SYSTEM_ID}")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid job_id"
    assert _store_bytes(store) == before
    assert store.get(SYSTEM_ID) is not None


def test_patch_system_job_returns_400_and_store_unchanged(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    _seed_system_job(store)
    before = _store_bytes(store)

    response = client.patch(
        f"/scheduled-runs/{SYSTEM_ID}", json={"title": "hijacked", "prompt": "injected"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid job_id"
    assert _store_bytes(store) == before
    kept = store.get(SYSTEM_ID)
    assert kept is not None
    assert kept.title == "Memory consolidation"
    assert kept.prompt == ""


def test_delete_unknown_id_still_returns_404_not_403(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    response = client.delete("/scheduled-runs/no-such-job")

    assert response.status_code == 404
    assert response.json()["detail"] == "scheduled run no-such-job not found"


def test_patch_unknown_id_still_returns_404_not_403(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    response = client.patch("/scheduled-runs/no-such-job", json={"title": "x"})

    assert response.status_code == 404
    assert response.json()["detail"] == "scheduled run no-such-job not found"


def test_delete_normal_job_returns_truly_empty_204(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    _seed_normal_job(store)

    response = client.delete("/scheduled-runs/job-normal")

    assert response.status_code == 204
    assert response.content == b""
    assert store.get("job-normal") is None


# ---------------------------------------------------------------------------
# Entry 5 — POST /scheduled-runs body: no system row can land
# ---------------------------------------------------------------------------


def test_post_cannot_forge_system_id_and_existing_row_untouched(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    _seed_system_job(store)
    before = _store_bytes(store)

    response = client.post(
        "/scheduled-runs",
        json={"id": SYSTEM_ID, "prompt": "injected", "schedule": "60000"},
    )

    assert response.status_code == 422
    assert _store_bytes(store) == before
    kept = store.get(SYSTEM_ID)
    assert kept is not None
    assert kept.source_type == "system"
    assert kept.prompt == ""


def test_post_ignores_source_type_and_executor_kind_escalation(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    response = client.post(
        "/scheduled-runs",
        json={
            "id": "escalation-attempt",
            "prompt": "ordinary prompt",
            "schedule": "60000",
            "source_type": "system",
            "executor_kind": "internal",
            "internal_callable": "memory.consolidate",
        },
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == "prompt"
    stored = store.get("escalation-attempt")
    assert stored is not None
    assert stored.source_type == "prompt"
    assert stored.executor_kind == "prompt"
    assert stored.internal_callable is None


def test_playbook_route_rejects_system_id_with_400(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    _seed_system_job(store)
    before = _store_bytes(store)

    response = client.post(
        f"/scheduled-runs/playbooks/{SAMPLE_SLUG}", json={"id": SYSTEM_ID}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid id"
    assert _store_bytes(store) == before


def test_playbook_route_creates_playbook_sourced_job(
    client: TestClient, store: ScheduledResearchJobStore
) -> None:
    response = client.post(
        f"/scheduled-runs/playbooks/{SAMPLE_SLUG}", json={"id": "desk-brief"}
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == "playbook"
    stored = store.get("desk-brief")
    assert stored is not None
    assert stored.source_type == "playbook"
    assert stored.executor_kind == "prompt"


# ---------------------------------------------------------------------------
# Entries 3+4 — proposals: refuse at propose AND at commit (authoritative)
# ---------------------------------------------------------------------------


def test_propose_create_rejects_system_id_draft(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_proposals(monkeypatch, store)
    _seed_system_job(store)
    before = _store_bytes(store)
    draft = {
        "title": "hijack",
        "id": SYSTEM_ID,
        "source": {"kind": "prompt", "prompt": "injected"},
        "schedule": {"expression": "60000"},
        "delivery": {"mode": "in_app"},
    }

    with pytest.raises(ValueError, match="reserved for protected system jobs"):
        proposals.propose_create(draft)

    assert _store_bytes(store) == before
    assert not (home / "scheduled_research" / "proposals").exists()


def test_propose_create_rejects_unsafe_id_draft(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_proposals(monkeypatch, store)
    draft = {
        "title": "x",
        "id": "id with space",
        "source": {"kind": "prompt", "prompt": "p"},
        "schedule": {"expression": "60000"},
        "delivery": {"mode": "in_app"},
    }

    with pytest.raises(ValueError, match="1-128 characters"):
        proposals.propose_create(draft)

    assert not (home / "scheduled_research" / "proposals").exists()


def test_commit_refuses_handwritten_proposal_replacing_system_job(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v2 — the authoritative guard: a tampered proposal file on disk must die
    at COMMIT with the store byte-identical."""
    _wire_proposals(monkeypatch, store)
    _seed_system_job(store)
    before = _store_bytes(store)
    internal_job = ScheduledResearchJob(
        id=SYSTEM_ID,
        title="hijack",
        prompt="injected",
        schedule="60000",
        next_run_at=2_000_000_000_000,
        status=JobStatus.PENDING,
        created_at=1_700_000_000_000,
    ).to_dict()
    proposal_id = _write_proposal(
        home, _handwritten_payload("create", job=None, internal_job=internal_job)
    )

    with pytest.raises(ProposalError, match="protected system job"):
        proposals.commit_proposal(proposal_id)

    assert _store_bytes(store) == before
    kept = store.get(SYSTEM_ID)
    assert kept is not None
    assert kept.source_type == "system"
    assert kept.prompt == ""
    assert kept.internal_callable == "memory.consolidate"
    on_disk = json.loads(
        (home / "scheduled_research" / "proposals" / f"{proposal_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["status"] == "pending"


def test_commit_refuses_handwritten_proposal_minting_new_system_job(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_proposals(monkeypatch, store)
    internal_job = ScheduledResearchJob(
        id=f"{SYSTEM_JOB_ID_PREFIX}brand-new",
        title="mint",
        prompt="",
        schedule="3600000",
        next_run_at=2_000_000_000_000,
        status=JobStatus.PENDING,
        created_at=1_700_000_000_000,
        source_type="system",
        executor_kind="internal",
        internal_callable="memory.consolidate",
    ).to_dict()
    proposal_id = _write_proposal(
        home, _handwritten_payload("create", job=None, internal_job=internal_job)
    )

    with pytest.raises(ProposalError, match="protected system job"):
        proposals.commit_proposal(proposal_id)

    assert store.load() == {}


def test_propose_cancel_rejects_system_job(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_proposals(monkeypatch, store)
    _seed_system_job(store)
    before = _store_bytes(store)

    with pytest.raises(ProposalError, match="protected system job"):
        proposals.propose_cancel(SYSTEM_ID)

    assert _store_bytes(store) == before
    assert not (home / "scheduled_research" / "proposals").exists()


def test_commit_refuses_handwritten_cancel_of_system_job(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_proposals(monkeypatch, store)
    _seed_system_job(store)
    before = _store_bytes(store)
    proposal_id = _write_proposal(
        home, _handwritten_payload("cancel", job_id=SYSTEM_ID, job=None)
    )

    with pytest.raises(ProposalError, match="protected system job"):
        proposals.commit_proposal(proposal_id)

    assert _store_bytes(store) == before
    assert store.get(SYSTEM_ID) is not None


def test_commit_create_and_cancel_normal_jobs_still_work(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_proposals(monkeypatch, store)
    created = proposals.propose_create(
        {
            "title": "Morning scan",
            "source": {"kind": "prompt", "prompt": "Summarize the market."},
            "schedule": {"expression": "60000"},
            "delivery": {"mode": "in_app"},
        }
    )
    proposals.commit_proposal(created["proposal_id"])
    assert len(store.load()) == 1
    job = next(iter(store.load().values()))
    assert job.source_type == "prompt"

    cancelled = proposals.propose_cancel(job.id)
    proposals.commit_proposal(cancelled["proposal_id"])
    assert store.load() == {}


def test_commit_still_gated_on_executable_runtime(
    home: Path, store: ScheduledResearchJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proposals, "default_store", lambda: store)
    monkeypatch.setattr(
        proposals,
        "scheduler_status",
        lambda: {"enabled": False, "running": False, "executable": False},
    )
    internal_job = ScheduledResearchJob(
        id="plain-job",
        title="t",
        prompt="p",
        schedule="60000",
        next_run_at=2_000_000_000_000,
        status=JobStatus.PENDING,
        created_at=1_700_000_000_000,
    ).to_dict()
    proposal_id = _write_proposal(
        home, _handwritten_payload("create", job=None, internal_job=internal_job)
    )

    with pytest.raises(ProposalError, match="not enabled and running"):
        proposals.commit_proposal(proposal_id)

    assert store.load() == {}


# ---------------------------------------------------------------------------
# Entry 6 — CLI `playbook create --id` writes the store directly
# ---------------------------------------------------------------------------


def test_cli_create_rejects_system_id_and_store_untouched(home: Path) -> None:
    cli_store = ScheduledResearchJobStore()
    _seed_system_job(cli_store)
    before = _store_bytes(cli_store)

    code = _run_cli(["playbook", "create", SAMPLE_SLUG, "--id", SYSTEM_ID])

    assert code == 1
    assert _store_bytes(cli_store) == before
    kept = cli_store.get(SYSTEM_ID)
    assert kept is not None
    assert kept.source_type == "system"
    assert kept.prompt == ""
    assert kept.internal_callable == "memory.consolidate"


def test_cli_create_rejects_unsafe_id_and_store_untouched(home: Path) -> None:
    cli_store = ScheduledResearchJobStore()
    _seed_system_job(cli_store)
    before = _store_bytes(cli_store)

    code = _run_cli(["playbook", "create", SAMPLE_SLUG, "--id", "bad id!"])

    assert code == 1
    assert _store_bytes(cli_store) == before


def test_cli_create_normal_id_still_persists_playbook_job(home: Path) -> None:
    code = _run_cli(["playbook", "create", SAMPLE_SLUG, "--id", "desk-brief"])

    assert code == 0
    stored = ScheduledResearchJobStore().get("desk-brief")
    assert stored is not None
    assert stored.source_type == "playbook"
    assert stored.executor_kind == "prompt"


def test_build_job_from_playbook_unit_guard() -> None:
    job, error = build_job_from_playbook(SAMPLE_SLUG, job_id=SYSTEM_ID)
    assert job is None
    assert error is not None
    assert "reserved for protected system jobs" in error

    job, error = build_job_from_playbook(SAMPLE_SLUG, job_id="bad id!")
    assert job is None
    assert error is not None
    assert "1-128 characters" in error
