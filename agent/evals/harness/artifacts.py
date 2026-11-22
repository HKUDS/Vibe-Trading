"""Safe, read-only loading of persisted agent run artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.session.thread import ThreadItem, diagnostic_records

JSON_LIMIT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactBundle:
    """Known artifacts and load errors for one completed run."""

    run_dir: Path
    trace_dir: Path
    req: dict[str, Any] | None
    state: dict[str, Any] | None
    grounding: dict[str, Any] | None
    llm_usage: dict[str, Any] | None
    manifest: dict[str, Any] | None
    trace: tuple[dict[str, Any], ...]
    present: frozenset[str]
    errors: dict[str, str] = field(default_factory=dict)
    identity: dict[str, Any] | None = None

    @classmethod
    def load(cls, run_dir: Path, *, trace_dir: Path | None = None) -> "ArtifactBundle":
        """Load only fixed artifact names without following paths outside their roots."""
        run_root = _require_directory(run_dir, "run_dir")
        trace_root = _require_directory(trace_dir or run_root, "trace_dir")
        present: set[str] = set()
        errors: dict[str, str] = {}

        def load_object(root: Path, relative: str, key: str) -> dict[str, Any] | None:
            try:
                path = _safe_known_path(root, relative)
            except ValueError as exc:
                errors[key] = str(exc)
                return None
            if not path.exists():
                return None
            present.add(key)
            try:
                value = _read_json(path)
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ) as exc:
                errors[key] = str(exc)
                return None
            if not isinstance(value, dict):
                errors[key] = f"{relative} must contain a JSON object"
                return None
            return value

        req = load_object(run_root, "req.json", "req")
        state = load_object(run_root, "state.json", "state")
        grounding = load_object(
            run_root, "artifacts/grounding_evidence.json", "grounding"
        )
        identity = load_object(run_root, "artifacts/identity_evidence.json", "identity")
        llm_usage = load_object(run_root, "llm_usage.json", "llm_usage")
        manifest = load_object(run_root, "run_manifest.json", "manifest")
        if trace_dir is None:
            try:
                trace_root = thread_directory(run_root, req)
            except (OSError, ValueError, TypeError) as exc:
                errors["trace"] = str(exc)
        context = (req or {}).get("context") or {}
        turn_id = context.get("turn_id") if isinstance(context, dict) else None
        trace = () if "trace" in errors else _load_thread_records(trace_root, present, errors, turn_id=turn_id)
        return cls(
            run_dir=run_root,
            trace_dir=trace_root,
            req=req,
            state=state,
            grounding=grounding,
            llm_usage=llm_usage,
            manifest=manifest,
            trace=trace,
            present=frozenset(present),
            errors=errors,
            identity=identity,
        )


def _load_thread_records(
    run_root: Path,
    present: set[str],
    errors: dict[str, str],
    *, turn_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Project conversation thread items for evaluations. The thread is the sole
    conversation record and includes diagnostics as event items.
    """
    try:
        thread_path = _safe_known_path(run_root, "thread.jsonl")
        if not thread_path.is_file():
            return ()
        if thread_path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("thread.jsonl exceeds the 64 MiB safety limit")
        items = []
        with thread_path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    items.append(ThreadItem.from_dict(json.loads(line)))
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValueError(f"thread.jsonl:{number}: invalid thread record") from exc
        starts = [item for item in items if item.type == "turn_start"]
        if turn_id:
            items = [item for item in items if item.turn_id == turn_id]
            if not items:
                raise ValueError("requested turn is absent from thread.jsonl")
        elif starts:
            items = [item for item in items if item.turn_id == starts[-1].turn_id]
    except (OSError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors["trace"] = str(exc)
        return ()
    if not items:
        return ()
    records = diagnostic_records(items)
    present.add("trace")
    return tuple(records)


def thread_directory(run_root: Path, request: dict | None = None) -> Path:
    """Resolve local records or the session under the configured session root.

    Request-supplied workspace paths never choose a filesystem read root.
    """
    if _safe_known_path(run_root, "thread.jsonl").is_file():
        return run_root
    if request is None and _safe_known_path(run_root, "req.json").is_file():
        request = _read_json(run_root / "req.json")
    context = request.get("context") if isinstance(request, dict) else None
    session_id = context.get("session_id") if isinstance(context, dict) else None
    if not isinstance(session_id, str) or not session_id:
        return run_root
    import re
    from src.config.paths import get_sessions_dir
    if re.fullmatch(r"[A-Za-z0-9_.-]+", session_id) is None or session_id in {".", ".."}:
        raise ValueError("invalid session identifier")
    sessions = get_sessions_dir().resolve()
    return _safe_known_path(sessions, session_id)


def _require_directory(path: Path, label: str) -> Path:
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"{label} is not a directory: {root}")
    return root


def _safe_known_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path escaped {root}: {relative}") from exc
    return path


def _read_json(path: Path) -> Any:
    if path.stat().st_size > JSON_LIMIT_BYTES:
        raise ValueError(
            f"{path.name} exceeds the {JSON_LIMIT_BYTES}-byte safety limit"
        )
    return json.loads(path.read_text(encoding="utf-8"))
