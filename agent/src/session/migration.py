"""One-time conversion of pre-thread session records into thread items."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from datetime import datetime
from contextlib import contextmanager
import threading

from src.tools.redaction import redact_payload, redact_tool_result

from src.session.store import SessionStore
from src.session.thread import ThreadLog

MIGRATION_MARKER = "thread_migration.json"
MIGRATION_VERSION = 1
_LOCK = threading.RLock()


@contextmanager
def _locked(directory: Path):
    """Serialize migration across threads and processes before opening a log."""
    from src.session.thread import fcntl

    directory.mkdir(parents=True, exist_ok=True)
    with _LOCK, (directory / ".thread-migration.lock").open("a") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _timestamp(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return default



@dataclass(frozen=True)
class MigrationResult:
    """Outcome of migrating one session directory."""

    session_id: str
    migrated: bool
    turns: int
    items: int


def marker_path(session_dir: Path) -> Path:
    """Return the marker path for a session directory.

    Args:
        session_dir: Directory containing the session data.

    Returns:
        The path to the migration marker.
    """
    return Path(session_dir) / MIGRATION_MARKER


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        for raw in stream:
            if not raw.strip():
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Cannot migrate malformed archive: {path}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _attempts(session_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in (Path(session_dir) / "attempts").glob("*/attempt.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot migrate malformed attempt: {path}") from exc
        if isinstance(value, dict):
            attempt_id = path.parent.name
            if isinstance(attempt_id, str):
                result[attempt_id] = value
    return result


def _metadata(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _turn_id(prompt: str, index: int, attempt_id: str | None) -> str:
    if attempt_id:
        return attempt_id
    digest = hashlib.sha1(f"{index}:{prompt}".encode("utf-8")).hexdigest()[:12]
    return f"legacy-{digest}"


def _status(assistant: Mapping[str, Any] | None, attempt: Mapping[str, Any] | None) -> str:
    metadata = _metadata(assistant or {})
    value = metadata.get("status") or (attempt or {}).get("status")
    value = getattr(value, "value", value)
    return value if value in {"completed", "failed", "cancelled", "interrupted", "waiting_user"} else "completed"


def _append_turn(log: ThreadLog, record: Mapping[str, Any], index: int, attempts: Mapping[str, Mapping[str, Any]]) -> int:
    user = record.get("user") if isinstance(record.get("user"), Mapping) else {}
    assistant = record.get("assistant") if isinstance(record.get("assistant"), Mapping) else None
    prompt = str(user.get("content") or (record.get("attempt") or {}).get("prompt") or "")
    metadata = _metadata(assistant or {})
    attempt_id = assistant.get("linked_attempt_id") if assistant else None
    if not isinstance(attempt_id, str) or not attempt_id:
        candidate = record.get("attempt_id")
        attempt_id = candidate if isinstance(candidate, str) else None
    attempt = attempts.get(attempt_id or "")
    turn_id = _turn_id(prompt, index, attempt_id)
    provider = metadata.get("provider") or metadata.get("configured_provider")
    model = metadata.get("model") or metadata.get("configured_model")
    stamp = _timestamp(user.get("created_at"), _timestamp((attempt or {}).get("created_at")))
    log = ThreadLog(log.path, clock=lambda: stamp)
    log.append("turn_start", turn_id, prompt=prompt, provider=provider, model=model)
    user_metadata = _metadata(user)
    user_payload: dict[str, Any] = {"content": prompt, "llm_content": prompt}
    input_id = user_metadata.get("queued_input_id")
    if isinstance(input_id, str) and input_id:
        user_payload["input_id"] = input_id
    if user or prompt:
        log.append("user", turn_id, **user_payload)
    for extra in record.get("users", [])[1:]:
        extra_content = str(extra.get("content") or "")
        log.append("user", turn_id, content=extra_content, llm_content=extra_content)

    trail = assistant.get("tool_trail") if assistant else []
    trail = [entry for entry in trail if isinstance(entry, Mapping)] if isinstance(trail, list) else []
    calls = []
    for position, entry in enumerate(trail):
        if not isinstance(entry, Mapping):
            continue
        call_id = entry.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"legacy-call-{index}-{position}"
        name = str(entry.get("tool") or "unknown")
        arguments = entry.get("arguments")
        if not isinstance(arguments, Mapping):
            arguments = {}
        calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(redact_payload(dict(arguments)), ensure_ascii=False, sort_keys=True)},
        })
    if calls:
        for entry, call in zip(trail, calls):
            stamp = _timestamp(entry.get("timestamp"), stamp * 1000) / 1000
            log.append("assistant", turn_id, content=None, tool_calls=[call], phase="commentary", provider=provider, model=model)
            if not isinstance(entry, Mapping):
                continue
            content = redact_tool_result(str(entry.get("preview") or ""))
            status = "ok" if entry.get("status") == "ok" else "error"
            payload: dict[str, Any] = {
                "tool_call_id": call["id"],
                "name": call["function"]["name"],
                "content": content,
                "status": status,
                "elapsed_ms": entry.get("elapsed_ms"),
            }
            if isinstance(entry.get("artifact"), Mapping):
                payload["artifact"] = redact_payload(dict(entry["artifact"]))
            log.append("tool_result", turn_id, **payload)
    if assistant is not None:
        stamp = _timestamp(assistant.get("created_at"), stamp)
        content = assistant.get("content")
        if not isinstance(content, str):
            content = ""
        run_id = metadata.get("run_id")
        llm_content = content
        if isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run_id) and f"[prev_run: {run_id}]" not in content:
            llm_content = f"[prev_run: {run_id}]\n{content}"
        log.append("assistant", turn_id, content=content, llm_content=llm_content, tool_calls=[], phase="final", provider=provider, model=model)

    if attempt_id:
        partial = record.get("partial")
        if isinstance(partial, str):
            log.append("checkpoint", turn_id, content=partial)
    if assistant is None and (attempt or {}).get("status") in {"pending", "running"}:
        return 1
    metadata = _metadata(assistant or {})
    status = _status(assistant, attempt)
    usage = metadata.get("usage")
    elapsed = metadata.get("elapsed_ms")
    run_dir = metadata.get("run_dir")
    if not isinstance(run_dir, str):
        run_dir = (attempt or {}).get("run_dir")
    error = metadata.get("error") or (attempt or {}).get("error")
    summary = assistant.get("content") if assistant else (attempt or {}).get("summary")
    log.append(
        "turn_end",
        turn_id,
        status=status,
        usage=usage if isinstance(usage, Mapping) else None,
        elapsed_ms=elapsed if isinstance(elapsed, (int, float)) else None,
        summary=summary if isinstance(summary, str) else None,
        error=error if isinstance(error, str) else None,
        run_dir=run_dir if isinstance(run_dir, str) else None,
        provider=provider if isinstance(provider, str) else None,
        model=model if isinstance(model, str) else None,
        display=redact_payload({key: metadata[key] for key in ("run_id", "metrics", "started_at", "reasoning_effort") if key in metadata}),
    )
    return 1


def migrate_session(session_dir: Path, *, session_id: str | None = None) -> MigrationResult:
    """Atomically migrate once before exposing a session's thread.

    Args:
        session_dir: Session directory containing legacy data.
        session_id: Session identifier override, when supplied.

    Returns:
        The migration outcome for that directory.
    """
    with _locked(Path(session_dir)):
        return _migrate_session(Path(session_dir), session_id=session_id)


def _migrate_session(session_dir: Path, *, session_id: str | None = None) -> MigrationResult:
    """Convert one pre-thread session exactly once."""
    session_dir = Path(session_dir)
    sid = session_id or session_dir.name
    marker = marker_path(session_dir)
    if marker.exists():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            return MigrationResult(sid, False, int(payload.get("turns", 0)), int(payload.get("items", 0)))
        except (OSError, ValueError, TypeError):
            marker.unlink(missing_ok=True)

    thread_path = session_dir / "thread.jsonl"
    existing = ThreadLog(thread_path).read()
    existing_turns = {item.turn_id for item in existing}
    rows = _read_jsonl(session_dir / "messages.jsonl")
    attempts = _attempts(session_dir)
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        if row.get("role") == "user":
            if current is None:
                current = {"user": row, "users": []}
            current.setdefault("users", []).append(row)
        elif row.get("role") == "assistant":
            if current is None:
                current = {}
            current["assistant"] = row
            records.append(current)
            current = None
    if current is not None:
        records.append(current)
    for record in records:
        if record.get("assistant") is not None:
            continue
        prompt = (record.get("user") or {}).get("content")
        match = next(((key, attempt) for key, attempt in attempts.items()
                      if attempt.get("prompt") == prompt), None)
        if match:
            record["attempt_id"], record["attempt"] = match
            partial_path = session_dir / "attempts" / match[0] / "partial_response.json"
            if partial_path.exists():
                record["partial"] = json.loads(partial_path.read_text()).get("content")
    seen = {record.get("assistant", {}).get("linked_attempt_id") for record in records if isinstance(record.get("assistant"), Mapping)}
    for attempt_id, attempt in attempts.items():
        if attempt_id in seen or any(record.get("attempt_id") == attempt_id for record in records):
            continue
        partial_path = session_dir / "attempts" / attempt_id / "partial_response.json"
        partial = json.loads(partial_path.read_text()).get("content") if partial_path.exists() else None
        records.append({"attempt_id": attempt_id, "attempt": attempt, "partial": partial})
    records.sort(key=lambda record: str((record.get("user") or record.get("assistant") or record.get("attempt") or {}).get("created_at") or ""))
    for index, record in enumerate(records):
        prompt = str((record.get("user") or {}).get("content") or (record.get("attempt") or {}).get("prompt") or "")
        attempt_id = (record.get("assistant") or {}).get("linked_attempt_id") or record.get("attempt_id")
        record["attempt_id"] = _turn_id(prompt, index, attempt_id)
    records = [record for record in records if record["attempt_id"] not in existing_turns]
    # Publish the thread atomically so interruption leaves an exact retry source.
    with tempfile.TemporaryDirectory(dir=session_dir, prefix=".migration-") as scratch:
        staged = Path(scratch) / "thread.jsonl"
        log = ThreadLog(staged)
        for index, record in enumerate(records):
            _append_turn(log, record, index, attempts)
        items = log.read()
        if existing:
            with staged.open("a", encoding="utf-8") as output:
                for item in existing:
                    record = item.to_dict()
                    offset = len(items)
                    record["seq"] = offset + item.seq
                    if item.type == "compaction":
                        record["replaces_through_seq"] = offset + record.get("replaces_through_seq", 0)
                        for change in record.get("changes", []):
                            change["seq"] += offset
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
            items = log.read()
        if staged.exists():
            os.replace(staged, thread_path)
    result = MigrationResult(sid, bool(records), len({item.turn_id for item in items}), len(items))

    SessionStore._write_json(
        marker,
        {"version": MIGRATION_VERSION, "migrated_at": time.time(), "turns": result.turns, "items": result.items},
        indent=None,
    )
    return result


def migrate_all(sessions_dir: Path) -> list[MigrationResult]:
    """Migrate every session directory below a sessions root.

    Args:
        sessions_dir: Root containing session directories.

    Returns:
        Migration outcomes in directory order for children with session.json, or an empty list if
        the root is absent.
    """
    root = Path(sessions_dir)
    if not root.exists():
        return []
    return [migrate_session(path) for path in sorted(root.iterdir()) if path.is_dir() and (path / "session.json").exists()]

