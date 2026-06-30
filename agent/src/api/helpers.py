from __future__ import annotations

import csv
import json
import logging
import os
import re
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from src.api.models import Artifact, BacktestMetrics, RAGSelection, RunResponse

logger = logging.getLogger(__name__)

# ============================================================================
# Path constants
# ============================================================================

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "runs"
SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "sessions"
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
AGENT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = AGENT_DIR / ".env"
ENV_EXAMPLE_PATH = AGENT_DIR / ".env.example"
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"

# ============================================================================
# SPA fallback constants
# ============================================================================

# Patterns are written narrowly so the SPA shell only shadows paths that
# actually correspond to frontend pages. In particular ``/runs/{id}`` is
# the RunDetail page, but ``/runs/{id}/code`` and ``/runs/{id}/pine`` are
# API-only endpoints with no SPA route — using a broad ``/runs/`` prefix
# here would incorrectly hijack those when the browser sets ``Accept:
# text/html`` (e.g. a user pasting the URL into the address bar).

_SPA_HTML_EXACT_PATHS: frozenset[str] = frozenset({"/correlation"})
# Each regex matches a complete request path. Trailing slash optional.
_SPA_HTML_PATH_REGEX: tuple[re.Pattern[str], ...] = (
    # ``/runs/{run_id}`` — RunDetail page. Excludes ``/runs/{id}/code``,
    # ``/runs/{id}/pine`` (API only) and ``/runs`` (collection endpoint).
    re.compile(r"^/runs/[^/]+/?$"),
)


def _is_spa_html_route(path: str) -> bool:
    """Return True when ``path`` corresponds to a frontend SPA page that
    shadows an API endpoint and should fall back to ``index.html`` on
    browser navigation."""
    if path in _SPA_HTML_EXACT_PATHS:
        return True
    return any(pattern.match(path) for pattern in _SPA_HTML_PATH_REGEX)


# ============================================================================
# Settings / env helpers
# ============================================================================


def _ensure_agent_env_file() -> Path:
    """Ensure the project-local agent/.env exists."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Created by Vibe-Trading Web UI settings.\n", encoding="utf-8")
    return ENV_PATH


def _strip_env_value(value: str) -> str:
    """Remove basic dotenv quotes and inline comments."""
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _read_env_values(path: Path) -> Dict[str, str]:
    """Read active KEY=value entries from a dotenv file."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _strip_env_value(value)
    return values


def _read_settings_env_values() -> Dict[str, str]:
    """Read settings without creating agent/.env.

    Prefer the user's active agent/.env. If it does not exist yet, fall back to
    agent/.env.example for display defaults only.
    """
    if ENV_PATH.exists():
        return _read_env_values(ENV_PATH)
    if ENV_EXAMPLE_PATH.exists():
        return _read_env_values(ENV_EXAMPLE_PATH)
    return {}


def _project_relative_path(path: Path) -> str:
    """Return a project-relative display path without leaking an absolute path."""
    try:
        return path.resolve().relative_to(AGENT_DIR.parent.resolve()).as_posix()
    except ValueError:
        return path.name


def _format_env_value(value: str) -> str:
    """Format a dotenv value without allowing multiline injection."""
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Environment values cannot contain newlines")
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _write_env_values(path: Path, updates: Dict[str, str]) -> None:
    """Upsert active dotenv values while preserving comments and ordering."""
    _ensure_agent_env_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    for index, raw in enumerate(lines):
        stripped = raw.lstrip()
        is_comment = stripped.startswith("#")
        candidate = stripped[1:].lstrip() if is_comment else stripped
        if "=" not in candidate:
            continue
        key = candidate.split("=", 1)[0].strip()
        if key in updates and key not in seen:
            lines[index] = f"{key}={_format_env_value(updates[key])}"
            seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Updated from Web UI")
        for key in missing:
            lines.append(f"{key}={_format_env_value(updates[key])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _is_configured_secret(value: str, placeholders: set[str]) -> bool:
    """Return True when a secret is set and not a documented placeholder."""
    normalized = value.strip().strip('"').strip("'")
    if not normalized:
        return False
    return normalized.lower() not in {placeholder.lower() for placeholder in placeholders}


def _coerce_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================================
# Run-response helpers
# ============================================================================


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON from disk if present."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _load_csv_to_dict(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load CSV rows into a list of dictionaries."""
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
        if limit is not None:
            rows = rows[:limit]
        return rows
    except Exception:
        return []


def _build_response_from_run_dir(
    run_dir: Path,
    elapsed: float,
    *,
    include_analysis: bool = False,
    chart_symbol: Optional[str] = None,
    chart_payload: str = "full",
    chart_symbols_out: Optional[List[str]] = None,
) -> RunResponse:
    """Build a run response from a persisted run directory."""
    run_id = run_dir.name

    response = RunResponse(
        status="unknown",
        run_id=run_id,
        elapsed_seconds=elapsed,
        run_directory=str(run_dir),
    )

    state_data = _load_json_file(run_dir / "state.json")
    if state_data:
        state_status = str(state_data.get("status") or "").lower()
        if state_status == "success":
            response.status = "success"
        elif state_status == "failed":
            response.status = "failed"
            response.reason = state_data.get("reason", "")
        else:
            response.status = state_status or "unknown"
    else:
        response.status = "unknown"

    planner_path = run_dir / "planner_output.json"
    response.planner_output = _load_json_file(planner_path)

    design_path = run_dir / "design_spec.json"
    response.strategy_spec = _load_json_file(design_path)

    rag_path = run_dir / "rag_metadata.json"
    rag_data = _load_json_file(rag_path)
    if rag_data:
        response.rag_selection = RAGSelection(
            selected_api=rag_data.get("selected_api") or rag_data.get("api_code", ""),
            selected_name=rag_data.get("selected_name") or rag_data.get("api_name", ""),
            selected_score=float(rag_data.get("selected_score") or rag_data.get("score", 0.0)),
        )

    metrics_path = run_dir / "artifacts" / "metrics.csv"
    if metrics_path.exists():
        metrics_dict_list = _load_csv_to_dict(metrics_path, limit=1)
        if metrics_dict_list:
            row = metrics_dict_list[0]
            try:
                # Pass ALL CSV columns to BacktestMetrics (extra="allow")
                parsed: dict = {}
                for k, v in row.items():
                    if not k or not v:
                        continue
                    try:
                        parsed[k] = int(float(v)) if k == "trade_count" or k == "max_consecutive_loss" else float(v)
                    except (ValueError, TypeError):
                        continue
                if "final_value" in parsed:
                    response.metrics = BacktestMetrics(**parsed)
            except (ValueError, TypeError):
                pass


    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists():
        for file_path in artifacts_dir.iterdir():
            if file_path.is_file():
                file_type = file_path.suffix.lstrip(".")
                response.artifacts.append(
                    Artifact(
                        name=file_path.name,
                        path=str(file_path),
                        type=file_type if file_type else "unknown",
                        size=file_path.stat().st_size,
                        exists=True,
                    )
                )

    equity_path = run_dir / "artifacts" / "equity.csv"
    if equity_path.exists():
        response.artifacts_equity_csv = _load_csv_to_dict(equity_path)

    metrics_csv_path = run_dir / "artifacts" / "metrics.csv"
    if metrics_csv_path.exists():
        response.artifacts_metrics_csv = _load_csv_to_dict(metrics_csv_path)

    run_card_path = run_dir / "run_card.json"
    if run_card_path.exists():
        try:
            response.run_card = json.loads(run_card_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    llm_usage_path = run_dir / "llm_usage.json"
    if llm_usage_path.exists():
        try:
            response.llm_usage = json.loads(llm_usage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    trades_path = run_dir / "artifacts" / "trades.csv"
    if trades_path.exists():
        response.artifacts_trades_csv = _load_csv_to_dict(trades_path)

    validation_path = run_dir / "artifacts" / "validation.json"
    if validation_path.exists():
        try:
            response.validation = json.loads(validation_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    if response.artifacts_equity_csv:
        filtered_equity = []
        for row in response.artifacts_equity_csv[:1000]:
            filtered_row: Dict[str, Any] = {}
            if "timestamp" in row:
                filtered_row["time"] = row["timestamp"]
            if "equity" in row:
                filtered_row["equity"] = row["equity"]
            if "drawdown" in row:
                filtered_row["drawdown"] = row["drawdown"]
            filtered_equity.append(filtered_row)
        response.equity_curve = filtered_equity

    if response.artifacts_trades_csv:
        response.trade_log = response.artifacts_trades_csv[:500]

    if include_analysis:
        from src.ui_services import build_run_analysis

        analysis = build_run_analysis(
            run_dir,
        symbols=[chart_symbol] if chart_symbol else None,
        include_payload=chart_payload != "summary" or bool(chart_symbol),
        include_symbol_list=chart_symbols_out is not None,
    )
        if chart_symbols_out is not None:
            chart_symbols_out.extend(analysis.get("chart_symbols") or [])
        response.run_stage = analysis.get("run_stage")
        response.run_context = analysis.get("run_context")
        response.price_series = analysis.get("price_series")
        response.indicator_series = analysis.get("indicator_series")
        response.trade_markers = analysis.get("trade_markers")
        response.run_logs = analysis.get("run_logs")

    return response


def _run_response_payload(response: RunResponse) -> Dict[str, Any]:
    """Return a JSON-ready payload for opt-in run response variants."""
    return response.model_dump(mode="json")


# ============================================================================
# Path-parameter validation
# ============================================================================

# ``run_id`` and ``session_id`` flow directly into filesystem paths
# (``RUNS_DIR / run_id`` etc.). Restrict to a safe character class so that
# values like ``..`` or ``foo/../bar`` cannot escape the parent directory.
_SAFE_PATH_PARAM_RE = __import__("re").compile(r"^[A-Za-z0-9_-]{1,128}$")


def _validate_path_param(value: str, kind: str) -> None:
    """Reject path parameters that could escape the parent directory.

    Args:
        value: User-supplied path-parameter value.
        kind: Parameter name, used in the error detail.

    Raises:
        HTTPException: 400 when ``value`` does not match the safe character
            class, mirroring the existing ``_SHADOW_ID_RE`` check.
    """
    if not _SAFE_PATH_PARAM_RE.fullmatch(value or ""):
        raise HTTPException(status_code=400, detail=f"invalid {kind}")


# ============================================================================
# Process termination
# ============================================================================


def _terminate_current_process() -> None:
    """Stop the current API process after the response has been sent."""
    time.sleep(0.25)
    os.kill(os.getpid(), signal.SIGTERM)
