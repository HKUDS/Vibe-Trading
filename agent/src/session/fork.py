"""Snapshot a committed conversation prefix into an independently owned fork."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.session.models import Attempt, AttemptStatus, Message, Principal, Session, SessionStatus
from src.session.store import SessionStore

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ROOT_FILES = frozenset(
    {
        "req.json",
        "state.json",
        "planner_output.json",
        "design_spec.json",
        "rag_metadata.json",
        "strategy_provenance.json",
        "run_card.json",
        "run_card.md",
        "llm_usage.json",
    }
)
_ARTIFACT_SUFFIXES = frozenset(
    {".csv", ".json", ".pine", ".html", ".md", ".py", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".pdf", ".parquet"}
)
_FORBIDDEN_PARTS = (
    "log",
    "trace",
    "secret",
    "credential",
    "token",
    "password",
    "cookie",
    "partial",
    "checkpoint",
    "compaction",
    "swarm",
    "channel",
    "memory",
)
_FORBIDDEN_CONFIG_KEYS = frozenset(
    {
        "mcpServers",
        "mcp_servers",
        "channels",
        "channel_mappings",
        "env",
        "environment",
        "headers",
        "credentials",
        "auth",
        "authorization",
        "cookies",
        "partial_response",
        "active_loop",
        "active_task",
        "background_handles",
        "compaction_summary",
        "temporary_compaction_summary",
        "live_loops",
        "active_loops",
        "active_tasks",
        "swarm_state",
        "runtime_state",
        "channel_mapping",
        "live_loop",
        "background_handle",
        "compaction",
        "task_handle",
        "sse_state",
        "loop_state",
        "task_state",
        "header",
        "env_vars",
        "env_file",
        "mcp",
        "swarm",
        "loop",
        "task",
        "background",
        "partial",
        "sse",
    }
)
_FORBIDDEN_CONFIG_KEYS_NORMALIZED = frozenset(
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in _FORBIDDEN_CONFIG_KEYS
)


class ForkSourceNotFound(LookupError):
    """The source session does not exist."""


class ForkSelectionError(ValueError):
    """The requested message is not a completed assistant cutoff."""


class ForkAuthorizationError(PermissionError):
    """An attributable principal does not own the source session."""


def validate_fork_id(value: str, kind: str) -> str:
    """Reject empty, oversized, or path-like identifiers before storage access."""
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ForkSelectionError(f"invalid {kind}")
    return value


def enforce_owner(source: Session, principal: Principal | None) -> None:
    """Enforce identity equality only when both owners are attributable."""
    if (
        principal is not None
        and source.owner is not None
        and source.owner.attributable
        and principal.attributable
        and (source.owner.subject, source.owner.tenant)
        != (principal.subject, principal.tenant)
    ):
        raise ForkAuthorizationError("the source session belongs to another principal")


def _fresh_id(used: set[str]) -> str:
    while True:
        value = uuid.uuid4().hex[:12]
        if value not in used:
            used.add(value)
            return value


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized in _FORBIDDEN_CONFIG_KEYS_NORMALIZED:
        return True
    if any(
        part in normalized
        for part in (
            "secret", "password", "apikey", "privatekey", "accesskey",
            "credential", "cookie", "authheader", "authentication",
        )
    ):
        return True
    if normalized in {"auth", "authorization", "headers", "env", "environment"}:
        return True
    if "token" not in normalized:
        return False
    # Model limits, accounting, and tokenizer settings are not credentials.
    if any(
        part in normalized
        for part in (
            "maxtoken", "tokenlimit", "tokenbudget", "tokenusage", "tokensused",
            "tokenprice", "tokenizer", "inputtokens", "outputtokens", "tokencount",
        )
    ):
        return False
    return True


def sanitize_fork_config(value: Any) -> Any:
    """Deep-copy ordinary settings while dropping runtime state and secrets."""
    if isinstance(value, dict):
        return {
            key: sanitize_fork_config(item)
            for key, item in value.items()
            if isinstance(key, str) and not _is_secret_key(key)
        }
    if isinstance(value, list):
        return [sanitize_fork_config(item) for item in value]
    return copy.deepcopy(value)


def _remap_text(value: str, replacements: list[tuple[str, str]]) -> str:
    for old, new in replacements:
        value = value.replace(old, new)
    return value


def _remap(value: Any, replacements: list[tuple[str, str]]) -> Any:
    """Recursively rewrite identifiers and run paths without changing other data."""
    if isinstance(value, str):
        return _remap_text(value, replacements)
    if isinstance(value, list):
        return [_remap(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            _remap_text(key, replacements) if isinstance(key, str) else key: _remap(item, replacements)
            for key, item in value.items()
        }
    return value


def _safe_run_dir(runs_dir: Path, run_dir: str) -> Path | None:
    path = Path(run_dir)
    if not _SAFE_ID_RE.fullmatch(path.name):
        return None
    try:
        # Legacy records may contain just the run id rather than its full path.
        resolved = (path if path.is_absolute() else runs_dir / path).resolve()
        resolved.relative_to(runs_dir.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _run_id_from_path(value: str, runs_dir: Path) -> str | None:
    """Extract a run id from an absolute or ``runs/{id}/...`` artifact path."""
    if "://" in value:
        return None
    path = Path(value)
    try:
        relative = path.relative_to(runs_dir)
    except ValueError:
        parts = path.parts
        try:
            index = len(parts) - 1 - parts[::-1].index(runs_dir.name)
        except ValueError:
            return None
        relative = Path(*parts[index + 1 :])
    return relative.parts[0] if relative.parts else None


def _eligible_assistant(
    message: Message,
    source_id: str,
    store: SessionStore,
) -> Attempt | None:
    if message.session_id != source_id or message.role != "assistant":
        raise ForkSelectionError("the cutoff must be an assistant message in the source session")
    if not isinstance(message.metadata, dict):
        raise ForkSelectionError("the cutoff message has invalid metadata")
    metadata = message.metadata
    status = metadata.get("status")
    status_value = getattr(status, "value", status)
    if status_value is not None and str(status_value).lower() != AttemptStatus.COMPLETED.value:
        raise ForkSelectionError("the cutoff assistant turn did not complete successfully")
    if any(metadata.get(key) for key in ("streaming", "partial", "in_progress", "failed", "cancelled", "interrupted")):
        raise ForkSelectionError("streaming, partial, and non-successful turns cannot be forked")
    linked_id = message.linked_attempt_id
    run_id = metadata.get("run_id")
    if linked_id:
        validate_fork_id(linked_id, "linked attempt id")
        attempt = store.get_attempt(source_id, linked_id)
        if attempt is None or attempt.session_id != source_id:
            raise ForkSelectionError("the cutoff attempt is missing or belongs to another session")
        if attempt.status is not AttemptStatus.COMPLETED:
            raise ForkSelectionError("the cutoff attempt did not complete successfully")
        return attempt
    if run_id:
        raise ForkSelectionError("a run-backed assistant message must link its completed attempt")
    # Older terminal replies have neither an attempt nor a run identifier.
    return None


def _run_references(value: Any) -> set[str]:
    """Find run ids and run-directory basenames in nested render metadata."""
    references: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {"runid", "rundir"} and isinstance(item, str) and item:
                references.add(Path(item).name)
            references.update(_run_references(item))
    elif isinstance(value, list):
        for item in value:
            references.update(_run_references(item))
    return references


def _attempt_snapshot(
    source_id: str,
    messages: list[Message],
    selected_attempt: Attempt | None,
    store: SessionStore,
    runs_dir: Path,
) -> tuple[list[Attempt], dict[str, str]]:
    attempts: dict[str, Attempt] = {}
    pending = [message.linked_attempt_id for message in messages if message.linked_attempt_id]
    if selected_attempt is not None:
        pending.append(selected_attempt.attempt_id)
    visited: set[str] = set()
    while pending:
        attempt_id = pending.pop()
        if not attempt_id or attempt_id in visited:
            continue
        visited.add(attempt_id)
        validate_fork_id(attempt_id, "attempt id")
        attempt = store.get_attempt(source_id, attempt_id)
        if attempt is None or attempt.session_id != source_id:
            raise ForkSelectionError("a copied message references a missing or foreign attempt")
        attempts[attempt_id] = attempt
        if attempt.parent_attempt_id:
            pending.append(attempt.parent_attempt_id)
    run_ids: set[str] = set()
    for message in messages:
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        run_ids.update(_run_references(metadata))
        run_ids.update(_run_references(message.tool_trail))
    for attempt in attempts.values():
        run_ids.update(_run_references(attempt.metrics))
        if attempt.run_dir:
            path = _safe_run_dir(runs_dir, attempt.run_dir)
            if path is None:
                raise ForkSelectionError("an attempt references an unsafe run directory")
            run_ids.add(path.name)
    for run_id in run_ids:
        validate_fork_id(run_id, "run id")
    return list(attempts.values()), {run_id: run_id for run_id in run_ids}


def _safe_artifact_file(path: Path, root: Path) -> bool:
    """Admit only renderable files, never links, logs, or runtime state."""
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            return False
        relative = path.relative_to(root)
    except (OSError, ValueError):
        return False
    if any(part.startswith(".") for part in relative.parts):
        return False
    if any(part in {"logs", "traces", "checkpoints", "partial_responses"} for part in relative.parts):
        return False
    name = path.name.lower()
    name_parts = set(re.split(r"[^a-z0-9]+", name))
    if (
        name_parts.intersection(_FORBIDDEN_PARTS)
        or any(part in name for part in ("secret", "credential", "password", "cookie", "checkpoint", "compaction"))
        or name == ".env"
    ):
        return False
    if path.parent == root:
        return name in _ROOT_FILES
    if relative.parts[0] == "code":
        return path.suffix.lower() == ".py"
    if relative.parts[0] == "artifacts":
        return path.suffix.lower() in _ARTIFACT_SUFFIXES
    return False


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_run(
    source: Path,
    staged: Path,
    replacements: list[tuple[str, str]],
) -> None:
    """Copy an allowlisted historical run into staging and remap its metadata."""
    (staged / "code").mkdir(parents=True, exist_ok=True)
    (staged / "artifacts").mkdir(parents=True, exist_ok=True)
    if not source.is_dir() or source.is_symlink():
        return
    for path in source.rglob("*"):
        if not path.is_file() or not _safe_artifact_file(path, source):
            continue
        relative = path.relative_to(source)
        destination = staged / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                # Unparseable metadata cannot be rendered safely; do not copy
                # opaque bytes that might contain credentials or raw traces.
                continue
            if relative.as_posix() == "req.json" and isinstance(payload, dict):
                payload = sanitize_fork_config(payload)
            _write_json(destination, _remap(payload, replacements))
        elif path.suffix.lower() in {".md", ".py", ".pine", ".html"}:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            destination.write_text(_remap(text, replacements), encoding="utf-8")
        else:
            shutil.copy2(path, destination)

    card_path = staged / "run_card.json"
    if card_path.is_file():
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            card = None
        if isinstance(card, dict):
            manifest = []
            for item in card.get("artifacts", []):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                candidate = staged / item["path"]
                if not candidate.is_file() or not _safe_artifact_file(candidate, staged):
                    continue
                payload = candidate.read_bytes()
                manifest.append({**item, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            card["artifacts"] = manifest
            allowed_trace_keys = {
                "tool", "status", "started_at", "ended_at", "args_hash", "result_hash",
            }
            card["tool_traces"] = [
                {key: value for key, value in trace.items() if key in allowed_trace_keys}
                for trace in card.get("tool_traces", [])
                if isinstance(trace, dict)
            ]
            _write_json(card_path, card)
            markdown_path = staged / "run_card.md"
            if markdown_path.exists():
                from backtest.run_card import _render_markdown

                try:
                    markdown = _render_markdown(card)
                except (KeyError, TypeError):
                    # Keep the already-remapped historical markdown when an
                    # older card schema cannot be rendered by today's writer.
                    logger.warning("Could not regenerate forked run card %s", staged)
                else:
                    markdown_path.write_text(markdown, encoding="utf-8")


def fork_session(
    service: Any,
    source_id: str,
    message_id: str,
    *,
    owner: Principal | None = None,
    goal_store: Any = None,
) -> Session:
    """Publish a durable, idle snapshot of a completed assistant prefix.

    The caller serializes this operation. No source execution claim is taken,
    so an active source run continues while its committed prefix is copied.
    """
    validate_fork_id(source_id, "source session id")
    validate_fork_id(message_id, "message id")
    store: SessionStore = service.store
    source = store.get_session(source_id)
    if source is None:
        raise ForkSourceNotFound(f"Session {source_id} not found")
    enforce_owner(source, owner)
    messages = store.get_messages(source_id, limit=None)
    matches = [index for index, item in enumerate(messages) if item.message_id == message_id]
    if len(matches) != 1:
        raise ForkSelectionError("the cutoff message is unknown or ambiguous")
    cutoff_index = matches[0]
    selected = messages[cutoff_index]
    selected_attempt = _eligible_assistant(selected, source_id, store)
    prefix = messages[: cutoff_index + 1]
    if len({item.message_id for item in prefix}) != len(prefix):
        raise ForkSelectionError("the source prefix contains duplicate message ids")
    attempts, run_ids = _attempt_snapshot(source_id, prefix, selected_attempt, store, service.runs_dir)

    used_ids = {item.session_id for item in store.list_sessions(limit=1_000_000)}
    used_ids.update(item.message_id for item in messages)
    used_ids.update(item.attempt_id for item in store.list_attempts())
    service.runs_dir.mkdir(parents=True, exist_ok=True)
    used_ids.update(path.name for path in service.runs_dir.iterdir() if path.is_dir())
    child_id = _fresh_id(used_ids)
    message_ids = {item.message_id: _fresh_id(used_ids) for item in prefix}
    attempt_ids = {item.attempt_id: _fresh_id(used_ids) for item in attempts}
    run_ids = {old: _fresh_id(used_ids) for old in run_ids}
    run_only_replacements = list(run_ids.items())
    replacements = [(source_id, child_id)]
    replacements.extend(run_only_replacements)
    replacements.extend((old, new) for old, new in attempt_ids.items())
    replacements.extend((old, new) for old, new in message_ids.items())
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    child = Session(
        session_id=child_id,
        title=source.title,
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        last_attempt_id=attempt_ids.get(selected_attempt.attempt_id) if selected_attempt else None,
        forked_from_session_id=source_id,
        forked_from_message_id=message_id,
        config=sanitize_fork_config(source.config),
        owner=owner,
    )
    child.config = _remap(child.config, replacements)
    child_messages = [
        replace(
            item,
            message_id=message_ids[item.message_id],
            session_id=child_id,
            linked_attempt_id=attempt_ids.get(item.linked_attempt_id) if item.linked_attempt_id else None,
            content=_remap(item.content, run_only_replacements),
            metadata=_remap(copy.deepcopy(item.metadata), replacements),
            tool_trail=_remap(copy.deepcopy(item.tool_trail), replacements),
        )
        for item in prefix
    ]
    message_run_by_attempt = {
        item.linked_attempt_id: item.metadata.get("run_id")
        for item in prefix
        if item.linked_attempt_id and isinstance(item.metadata, dict) and item.metadata.get("run_id")
    }
    child_attempts: list[Attempt] = []
    for item in attempts:
        old_run_id = Path(item.run_dir).name if item.run_dir else message_run_by_attempt.get(item.attempt_id)
        child_attempts.append(
            replace(
                item,
                attempt_id=attempt_ids[item.attempt_id],
                session_id=child_id,
                parent_attempt_id=attempt_ids.get(item.parent_attempt_id) if item.parent_attempt_id else None,
                run_dir=str(service.runs_dir / run_ids[old_run_id]) if old_run_id in run_ids else item.run_dir,
                prompt=_remap(item.prompt, run_only_replacements),
                summary=_remap(item.summary, run_only_replacements),
                # Raw ReAct traces can contain tool arguments, secrets, and
                # runtime handles. The user-visible tool trail is copied above.
                react_trace=[],
                error=_remap(item.error, replacements),
                metrics=_remap(copy.deepcopy(item.metrics), replacements),
            )
        )

    session_stage = store.base_dir / f".{child_id}.fork-{uuid.uuid4().hex}"
    run_stages: dict[str, Path] = {}
    published_runs: list[Path] = []
    child_published = False
    try:
        (session_stage / "attempts").mkdir(parents=True)
        _write_json(session_stage / "session.json", child.to_dict())
        with (session_stage / "messages.jsonl").open("w", encoding="utf-8") as handle:
            for item in child_messages:
                handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        for item in child_attempts:
            attempt_dir = session_stage / "attempts" / item.attempt_id
            attempt_dir.mkdir()
            _write_json(attempt_dir / "attempt.json", item.to_dict())

        if goal_store is not None:
            def ensure_goal_run(run_id: str) -> str:
                validate_fork_id(run_id, "goal evidence run id")
                if run_id not in run_ids:
                    run_ids[run_id] = _fresh_id(used_ids)
                return run_ids[run_id]

            def remap_goal_run(run_id: str) -> str:
                return ensure_goal_run(run_id)

            def remap_goal_path(value: str) -> str:
                # Goal state is from fork time and can reference runs newer
                # than the selected message. Clone those artifacts too, while
                # leaving uploads, reports, and shared-memory URIs untouched.
                if "://" in value:
                    return value
                referenced_run = _run_id_from_path(value, service.runs_dir)
                if referenced_run:
                    return _remap_text(value, [(referenced_run, ensure_goal_run(referenced_run))])
                dynamic = sorted(run_ids.items(), key=lambda pair: len(pair[0]), reverse=True)
                return _remap_text(value, dynamic)

            goal_store.clone_current_goal(
                source_id,
                target_session_id=child_id,
                remap_reference=remap_goal_path,
                remap_run_id=remap_goal_run,
            )

        for old_run_id, new_run_id in run_ids.items():
            source_run = service.runs_dir / old_run_id
            staged_run = service.runs_dir / f".{new_run_id}.fork-{uuid.uuid4().hex}"
            run_stages[old_run_id] = staged_run
            run_replacements = [(source_id, child_id), *run_ids.items(), *attempt_ids.items(), *message_ids.items()]
            run_replacements.append((str(source_run), str(service.runs_dir / new_run_id)))
            run_replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
            _copy_run(source_run, staged_run, run_replacements)

        # Runs become visible first; the session directory is the commit record
        # and is published last, so readers never see a partial child session.
        for old_run_id, new_run_id in run_ids.items():
            staged_run = run_stages[old_run_id]
            destination = service.runs_dir / new_run_id
            os.replace(staged_run, destination)
            published_runs.append(destination)
        os.replace(session_stage, store.base_dir / child_id)
        child_published = True

        service._search_index.index_session(child_id, child.title, ts=datetime.now(timezone.utc).timestamp())
        for item in child_messages:
            service._search_index.index_message(child_id, item.role, item.content)
        return child
    except Exception:
        # The child id is fresh, so unconditional cleanup is safe even when a
        # dependency raised after committing only part of its own transaction.
        cleanups = []
        if goal_store is not None:
            cleanups.append(lambda: goal_store.delete_session_goals(child_id))
        cleanups.append(lambda: service._search_index.remove_session(child_id))
        for cleanup in cleanups:
            try:
                cleanup()
            except Exception:  # pragma: no cover - best effort must not skip disk cleanup
                logger.exception("Fork dependency rollback failed for child %s", child_id)
        if child_published:
            shutil.rmtree(store.base_dir / child_id, ignore_errors=True)
        for path in published_runs:
            shutil.rmtree(path, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(session_stage, ignore_errors=True)
        for path in run_stages.values():
            shutil.rmtree(path, ignore_errors=True)
