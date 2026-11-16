"""Persisted research jobs and the single dispatch path for every surface."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.paths import get_runs_dir
from src.research_lab.execution import constructor_defaults, source_run
from src.research_lab.models import REQUEST_MODELS


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def job_root(job_id: str) -> Path:
    """Resolve a generated job ID without accepting a filesystem path."""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("invalid research job identifier")
    return get_runs_dir() / f"study-{job_id}"


def catalog() -> dict:
    """List reusable run inputs, constructor parameters and replay tasks."""
    from evals.harness.suite import list_cases

    rows = []
    runs = get_runs_dir()
    if runs.exists():
        for root in sorted(runs.iterdir(), reverse=True):
            if not root.is_dir() or root.name.startswith("study-"):
                continue
            try:
                source_run(str(root))
                if any(
                    not (root / relative).resolve().is_relative_to(root.resolve())
                    for relative in ("config.json", "code/signal_engine.py", "req.json", "trace.jsonl")
                ):
                    continue
                config = json.loads((root / "config.json").read_text()) if (root / "config.json").is_file() else {}
                if not config and not (root / "req.json").is_file():
                    continue
                signal = root / "code/signal_engine.py"
                rows.append(
                    {
                        "id": root.name,
                        "codes": config.get("codes", []),
                        "start_date": config.get("start_date"),
                        "end_date": config.get("end_date"),
                        "has_prices": bool(config.get("codes"))
                        and (root / "run_card.json").is_file()
                        and all(
                            (root / f"artifacts/ohlcv_{code.removeprefix('local:')}.csv").is_file()
                            for code in config.get("codes", [])
                        ),
                        "has_trace": (root / "trace.jsonl").is_file(),
                        "parameters": {
                            **(constructor_defaults(signal.read_text()) if signal.is_file() else {}),
                            **config.get("signal_parameters", {}),
                        },
                    }
                )
            except (OSError, ValueError, SyntaxError):
                continue
            if len(rows) >= 200:
                break
    return {"runs": rows, "cases": list_cases()}


def create_job(action: str, payload: dict[str, Any]) -> dict:
    """Validate a request and save its immutable submission before execution."""
    if action not in REQUEST_MODELS:
        raise ValueError("unknown research action")
    request = REQUEST_MODELS[action].model_validate(payload)
    if hasattr(request, "run_dir"):
        root = source_run(request.run_dir)
        if not root.is_dir():
            raise ValueError("source run does not exist")
    identifier = uuid.uuid4().hex
    root = job_root(identifier)
    now = datetime.now(timezone.utc).isoformat()
    state = {
        "id": identifier,
        "action": action,
        "status": "pending",
        "created_at": now,
        "request": request.model_dump(),
        "progress": None,
        "owner_pid": os.getpid(),
    }
    _write(root / "study.json", state)
    return state


def get_job(identifier: str) -> dict:
    """Read progress and the completed report without starting any work."""
    path = job_root(identifier) / "study.json"
    if not path.is_file():
        raise ValueError("research job not found")
    state = json.loads(path.read_text())
    if state["status"] in {"pending", "running"}:
        try:
            os.kill(state["owner_pid"], 0)
        except ProcessLookupError:
            state.update(
                status="failed",
                error="Research worker was interrupted; start a new job to rerun the saved request.",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            _write(path, state)
        except PermissionError:
            pass
    return state


def execute_job(identifier: str) -> dict:
    """Execute one persisted request; failures remain visible after completion."""
    root = job_root(identifier)
    state = get_job(identifier)
    if state["status"] != "pending":
        return state
    try:
        descriptor = os.open(root / "execution.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return get_job(identifier)
    os.close(descriptor)
    state["owner_pid"] = os.getpid()
    state["status"] = "running"
    _write(root / "study.json", state)

    def progress(value):
        state["progress"] = value
        _write(root / "study.json", state)

    try:
        action = state["action"]
        request = REQUEST_MODELS[action].model_validate(state["request"])
        if action == "cost_sensitivity":
            from src.research_lab.studies import cost_sensitivity

            result = cost_sensitivity(request, root, progress)
        elif action == "walk_forward":
            from src.research_lab.studies import walk_forward

            result = walk_forward(request, root, progress)
        elif action == "factor_audit":
            from src.factors.audit import audit_factors

            result = audit_factors(request.alpha_ids)
        else:
            from evals.harness.suite import replay_run

            result = replay_run(
                source_run(request.run_dir),
                request.case_ids,
                source_run(request.trace_dir) if request.trace_dir else None,
            )
        _write(root / "report.json", result)
        state.update(status="completed", result=result)
    except Exception as exc:
        from src.tools.redaction import redact_text

        state.update(status="failed", error=redact_text(str(exc)))
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write(root / "study.json", state)
    (root / "execution.lock").unlink(missing_ok=True)
    return state


def run(action: str, payload: dict) -> dict:
    """Run synchronously for CLI and agent callers using the same job contract."""
    return execute_job(create_job(action, payload)["id"])
