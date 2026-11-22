"""Atomic migration of archived sessions, with real-layout display parity."""
import json
import shutil
from pathlib import Path

import pytest

from src.session.event_projection import display_item
from src.session.migration import migrate_session
from src.session.replay import replay
from src.session.thread import ThreadLog


def _archive(path):
    path.mkdir(exist_ok=True)
    rows = [
        {"role": "user", "content": "Read the snapshot", "created_at": "2026-10-26T23:00:00+00:00"},
        {"role": "assistant", "content": "Snapshot complete", "linked_attempt_id": "old",
         "created_at": "2026-10-26T23:01:00+00:00",
         "metadata": {"run_id": "run-old", "metrics": {"sharpe": 1.2}, "provider": "offline", "model": "scripted", "status": "completed"},
         "tool_trail": [{"tool": "lookup", "call_id": "c1", "arguments": {"symbol": "TEST"}, "status": "ok", "preview": "snapshot", "elapsed_ms": 12}]},
    ]
    (path / "messages.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    return rows


def test_migration_preserves_display_and_is_idempotent(tmp_path):
    rows = _archive(tmp_path)
    assert migrate_session(tmp_path).migrated
    data = (tmp_path / "thread.jsonl").read_bytes()
    items = ThreadLog(tmp_path / "thread.jsonl").read()
    views = [display_item(item) for item in items]
    assert [v["content"] for v in views if v["type"] in {"user", "assistant"} and v.get("content")] == [r["content"] for r in rows]
    assert next(v for v in views if v["type"] == "tool_result")["content"] == "snapshot"
    assert views[-1]["display"]["metrics"] == {"sharpe": 1.2}
    assert views[-1]["ts"] == 1793055660
    assert replay(items)[-1]["content"] == "[prev_run: run-old]\nSnapshot complete"
    assert not migrate_session(tmp_path).migrated
    assert (tmp_path / "thread.jsonl").read_bytes() == data
    (tmp_path / "thread_migration.json").unlink()
    assert not migrate_session(tmp_path).migrated
    assert (tmp_path / "thread.jsonl").read_bytes() == data


def test_interrupted_migration_never_publishes_partial_thread(tmp_path, monkeypatch):
    _archive(tmp_path)
    import src.session.migration as migration
    append = migration._append_turn
    def fail(log, *args):
        append(log, *args)
        raise OSError("interrupted")
    monkeypatch.setattr(migration, "_append_turn", fail)
    with pytest.raises(OSError):
        migrate_session(tmp_path)
    assert not (tmp_path / "thread.jsonl").exists()
    assert not (tmp_path / "thread_migration.json").exists()
    monkeypatch.setattr(migration, "_append_turn", append)
    assert migrate_session(tmp_path).turns == 1


def test_mixed_archive_keeps_old_and_canonical_turns(tmp_path):
    _archive(tmp_path)
    log = ThreadLog(tmp_path / "thread.jsonl")
    log.append("turn_start", "new", prompt="continue")
    log.append("user", "new", content="continue", llm_content="continue")
    log.append("turn_end", "new", status="completed")
    log.append("compaction", "new", summary="prior context", replaces_through_seq=2)
    migrate_session(tmp_path)
    items = log.read()
    assert [i.turn_id for i in items if i.type == "turn_start"] == ["old", "new"]
    assert [i.seq for i in items] == list(range(1, len(items) + 1))
    new_user = next(i for i in items if i.type == "user" and i.turn_id == "new")
    assert items[-1].get("replaces_through_seq") == new_user.seq


def test_real_pre_thread_session_copy(tmp_path):
    # Owner-authorized read-only source. Nothing from the archive is printed or
    # committed; CI without the local archive exercises the fixed layout above.
    root = Path("/Users/wuhaozhe/.vibe-trading/sessions")
    candidates = [p for p in root.glob("*/messages.jsonl") if not (p.parent / "thread.jsonl").exists()]
    if not candidates:
        pytest.skip("owner's read-only archive unavailable")
    source = candidates[0]
    shutil.copytree(source.parent, tmp_path / "session")
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    migrate_session(tmp_path / "session")
    items = ThreadLog(tmp_path / "session/thread.jsonl").read()
    assert [i.get("content") for i in items if i.type in {"user", "assistant"} and i.get("content")] == [r["content"] for r in rows if r.get("content")]
    trails = [entry for row in rows for entry in row.get("tool_trail", [])]
    results = [i for i in items if i.type == "tool_result"]
    assert len(results) == len(trails)
    from src.tools.redaction import redact_payload, redact_tool_result
    calls = [call for item in items if item.type == "assistant" for call in (display_item(item).get("tool_calls") or [])]
    assert [call["arguments"] for call in calls] == [
        {key: str(value)[:200] for key, value in redact_payload(t.get("arguments") or {}).items()} for t in trails
    ]
    assert [i.get("elapsed_ms") for i in results] == [t.get("elapsed_ms") for t in trails]
    assert [i.get("content") for i in results] == [redact_tool_result(t.get("preview", "")) for t in trails]
