"""Trusted grounding inheritance across direct parent Attempts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.session.events import EventBus
from src.session.models import Attempt
from src.session.service import SessionService
from src.session.store import SessionStore


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _service(tmp_path: Path, monkeypatch) -> SessionService:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    return SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )


def _parent_artifact(service: SessionService, *, session_id: str) -> Attempt:
    run_dir = service.runs_dir / "parent-run"
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "identity": {
            "records": [
                {
                    "query": "AAPL",
                    "status": "locked",
                    "symbol": "AAPL.US",
                    "venue": "us",
                    "currency": "USD",
                    "source": ["yahoo"],
                }
            ]
        },
        "evidence": [
            {
                "call_id": "price-parent",
                "tool": "get_market_data",
                "symbol": "AAPL.US",
                "source": "yahoo",
                "timestamp": "2026-08-28",
                "field": "close",
                "value": 195.0,
                "status": "observed",
                "currency": "USD",
                "venue": "us",
                "observed_at": "2026-08-28T21:00:00Z",
                "market_session": "regular",
                "adjustment": "unadjusted",
                "unit": "share",
            }
        ],
    }
    (artifact_dir / "grounding_evidence.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    parent = Attempt(
        attempt_id="parent000001",
        session_id=session_id,
        prompt="分析 AAPL.US",
        run_dir=str(run_dir),
    )
    service.store.create_attempt(parent)
    return parent


def _child(parent: Attempt, prompt: str) -> Attempt:
    return Attempt(
        attempt_id="child0000001",
        session_id=parent.session_id,
        parent_attempt_id=parent.attempt_id,
        prompt=prompt,
    )


def test_confirmation_inherits_direct_parent_grounding(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")

    inherited = service._resolve_parent_grounding(_child(parent, "确认，继续完成"))

    assert inherited is not None
    assert len(inherited["evidence"]) == 1
    assert inherited["evidence"][0]["market_session"] == "regular"
    assert inherited["_inheritance"] == {
        "attempt_id": parent.attempt_id,
        "run_id": "parent-run",
    }


def test_previous_round_followup_inherits_direct_parent_grounding(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")

    inherited = service._resolve_parent_grounding(
        _child(parent, "沿用上一轮已经验证的价格和技术指标证据")
    )

    assert inherited is not None
    assert inherited["_inheritance"]["attempt_id"] == parent.attempt_id


def test_same_symbol_inherits_without_a_continuation_keyword(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")

    inherited = service._resolve_parent_grounding(
        _child(parent, "补充分析 AAPL.US 的估值")
    )

    assert inherited is not None


def test_new_symbol_does_not_inherit_parent_grounding(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")

    inherited = service._resolve_parent_grounding(_child(parent, "继续分析 MSFT.US"))

    assert inherited is None


def test_new_date_does_not_inherit_parent_grounding(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")

    inherited = service._resolve_parent_grounding(
        _child(parent, "继续分析 AAPL.US 在 2026-08-27 的表现")
    )

    assert inherited is None


def test_live_followup_inherits_identity_but_refreshes_evidence(
    tmp_path, monkeypatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")

    inherited = service._resolve_parent_grounding(
        _child(parent, "继续给出 AAPL.US 最新价格")
    )

    assert inherited is not None
    assert inherited["identity"]["records"][0]["symbol"] == "AAPL.US"
    assert inherited["evidence"] == []


def test_parent_run_outside_configured_root_is_rejected(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    outside = tmp_path / "outside" / "parent-run"
    (outside / "artifacts").mkdir(parents=True)
    (outside / "artifacts" / "grounding_evidence.json").write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8"
    )
    parent = Attempt(
        attempt_id="parent000001",
        session_id="abcdef012345",
        run_dir=str(outside),
    )
    service.store.create_attempt(parent)

    assert service._resolve_parent_grounding(_child(parent, "确认继续")) is None


def test_run_with_agent_passes_verified_parent_grounding(tmp_path, monkeypatch) -> None:
    captured = {}

    class _DummyAgentLoop:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def run(self, **kwargs):
            captured.update(kwargs)
            return {"status": "success", "content": "done"}

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr(
        "src.config.loader.load_runtime_agent_config",
        lambda overrides=None: object(),
    )
    monkeypatch.setattr(
        "src.config.loader.sanitize_session_overrides",
        lambda overrides: dict(overrides),
    )
    service = _service(tmp_path, monkeypatch)
    parent = _parent_artifact(service, session_id="abcdef012345")
    child = _child(parent, "确认，继续完成")

    asyncio.run(service._run_with_agent(child, messages=[], session_config={}))

    assert (
        captured["inherited_grounding"]["_inheritance"]["attempt_id"]
        == parent.attempt_id
    )
