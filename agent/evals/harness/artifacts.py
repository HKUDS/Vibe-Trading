"""Safe, read-only loading of persisted agent run artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JSON_LIMIT_BYTES = 16 * 1024 * 1024
TRACE_LIMIT_BYTES = 64 * 1024 * 1024


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
        llm_usage = load_object(run_root, "llm_usage.json", "llm_usage")
        manifest = load_object(trace_root, "run_manifest.json", "manifest")
        trace = _load_trace(trace_root, present, errors)
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
        )


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


def _load_trace(
    trace_root: Path,
    present: set[str],
    errors: dict[str, str],
) -> tuple[dict[str, Any], ...]:
    try:
        path = _safe_known_path(trace_root, "trace.jsonl")
    except ValueError as exc:
        errors["trace"] = str(exc)
        return ()
    if not path.exists():
        return ()
    present.add("trace")
    try:
        if path.stat().st_size > TRACE_LIMIT_BYTES:
            raise ValueError(
                f"trace.jsonl exceeds the {TRACE_LIMIT_BYTES}-byte safety limit"
            )
        records: list[dict[str, Any]] = []
        for number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"trace.jsonl:{number}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(f"trace.jsonl:{number}: record must be an object")
            record = dict(record)
            record["_line"] = number
            _resolve_trace_text(trace_root, record, "prompt")
            _resolve_trace_text(trace_root, record, "content")
            records.append(record)
        starts = [
            index
            for index, record in enumerate(records)
            if record.get("type") == "start"
        ]
        if starts:
            records = records[starts[-1] :]
        return tuple(records)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        errors["trace"] = str(exc)
        return ()


def _resolve_trace_text(
    trace_root: Path, record: dict[str, Any], field_name: str
) -> None:
    if field_name in record or f"{field_name}_path" not in record:
        return
    relative = record[f"{field_name}_path"]
    if not isinstance(relative, str):
        raise ValueError(
            f"trace.jsonl:{record['_line']}: {field_name}_path must be a string"
        )
    path = _safe_known_path(trace_root, relative)
    if not path.is_file():
        raise ValueError(f"trace.jsonl:{record['_line']}: missing {field_name} sidecar")
    if path.stat().st_size > JSON_LIMIT_BYTES:
        raise ValueError(
            f"trace.jsonl:{record['_line']}: {field_name} sidecar exceeds safety limit"
        )
    record[field_name] = path.read_text(encoding="utf-8")
