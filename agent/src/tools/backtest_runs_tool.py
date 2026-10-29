"""Backtest run discovery: list earlier runs so their artifacts can be reused.

Each user turn gets its own run directory, so a follow-up turn cannot reach the
artifacts an earlier turn produced unless something names them. This tool lists
runs from the files the runtime already writes (``req.json``, ``run_card.json``;
no new index) and returns the absolute ``run_dir`` of every backtest for
``read_run_artifact``.

The session filter is a convenience, not an access control: runs have no owner,
``scope="all"`` lists what ``GET /runs`` already shows, and ``read_run_artifact``
and ``session_search`` reach the same data. Directories are confined to the
allowed run roots and symlinks are never followed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.config.paths import get_runs_dir
from src.tools.path_utils import safe_run_dir, safe_run_id

_SCOPES = ("session", "all")
_MAX_LIMIT = 20
_MAX_SCAN = 5000
_MAX_BACKTESTS = 20
_MAX_JSON_BYTES = 8 * 1024 * 1024
_PROMPT_CHARS = 160
_METRIC_KEYS = ("total_return", "sharpe", "max_drawdown", "unfilled_plan_rejections")


def _is_plain_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path, run_root: Path) -> dict[str, Any]:
    """A JSON object from a regular file inside ``run_root``, else ``{}``."""
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(run_root):
            return {}
        if path.stat().st_size > _MAX_JSON_BYTES:
            return {}
        return _as_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _session_of(run_root: Path) -> str | None:
    """Session that created a run, from the ``req.json`` the loop wrote."""
    return _as_dict(_read_json(run_root / "req.json", run_root).get("context")).get(
        "session_id"
    )


def _backtests_of(run_root: Path) -> list[dict[str, Any]]:
    """Backtests a turn left: the run itself and its direct sub-directories.

    A turn root that holds an archive manifest is a copy of one of its
    sub-directories, so it is not listed twice.
    """
    dirs = [] if (run_root / ".archived_backtest.json").exists() else [run_root]
    try:
        dirs += sorted(d for d in run_root.iterdir() if _is_plain_dir(d))
    except OSError:
        pass
    found = []
    for directory in dirs:
        card = _read_json(directory / "run_card.json", run_root)
        if not card:
            continue
        metrics = _as_dict(card.get("metrics"))
        config = _as_dict(card.get("backtest"))
        entry = {
            "name": directory.name if directory != run_root else ".",
            "run_dir": str(directory),
            "start_date": config.get("start_date"),
            "end_date": config.get("end_date"),
            "metrics": {key: metrics[key] for key in _METRIC_KEYS if key in metrics},
        }
        rejected = _as_dict(card.get("structured_metrics")).get(
            "unfilled_plan_rejections_by_symbol"
        )
        if rejected:
            if len(json.dumps(rejected)) <= TOOL_RESULT_LIMIT // 8:
                entry["unfilled_plan_rejections_by_symbol"] = rejected
            else:
                entry["unfilled_plan_rejections_by_symbol_omitted"] = True
        found.append(entry)
    return found[:_MAX_BACKTESTS]


def _run_summary(run_root: Path) -> dict[str, Any]:
    prompt = " ".join(
        str(_read_json(run_root / "req.json", run_root).get("prompt") or "").split()
    )
    result = {
        "run_id": run_root.name,
        "run_dir": str(run_root),
        "prompt": prompt[:_PROMPT_CHARS],
        "backtests": _backtests_of(run_root),
    }
    omitted = 0
    while len(result["backtests"]) > 1 and len(json.dumps(result)) > TOOL_RESULT_LIMIT // 2:
        result["backtests"].pop()
        omitted += 1
    if omitted:
        result["omitted_backtests"] = omitted
    return result


def _candidates(runs_root: Path):
    """Allowed run directories, newest first."""
    try:
        names = sorted(
            (d.name for d in runs_root.iterdir() if _is_plain_dir(d)), reverse=True
        )
    except OSError:
        return
    for name in names[:_MAX_SCAN]:
        try:
            yield safe_run_dir(str(runs_root / name))
        except ValueError:
            continue


def list_backtest_runs(
    *,
    current_run_dir: str | None = None,
    scope: str = "session",
    run_id: str | None = None,
    limit: int = 5,
    offset: int = 0,
) -> str:
    """List earlier runs, newest first, as a JSON envelope.

    Args:
        current_run_dir: The active turn's run directory (injected by the
            loop). It defines the session for ``scope="session"`` and is never
            listed.
        scope: ``session`` for the current session's runs, ``all`` for every run.
        run_id: Only this bare run directory name (validated by ``safe_run_id``).
        limit: Runs per page, 1..20.
        offset: Runs to skip (the previous page's ``next_offset``).

    Returns:
        JSON with ``runs`` (each with its ``run_dir`` and ``backtests``) and
        ``next_offset`` (``null`` on the last page).
    """
    if scope not in _SCOPES:
        return json.dumps(
            {"status": "error", "error": f"scope must be one of {list(_SCOPES)}"}
        )
    try:
        limit = min(max(int(limit), 1), _MAX_LIMIT)
        offset = max(int(offset), 0)
        runs = (
            iter([safe_run_id(run_id)])
            if run_id is not None
            else _candidates(get_runs_dir())
        )
    except (TypeError, ValueError) as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    current = Path(current_run_dir).resolve() if current_run_dir else None
    session = _session_of(current) if current and scope == "session" else None

    page: list[dict[str, Any]] = []
    skipped, more = 0, False
    for run_root in runs:
        if run_root == current or (session and _session_of(run_root) != session):
            continue
        entry = _run_summary(run_root)
        if not entry["backtests"]:
            continue
        if skipped < offset:
            skipped += 1
            continue
        if page and (
            len(page) == limit
            or len(json.dumps([*page, entry])) > TOOL_RESULT_LIMIT // 2
        ):
            more = True
            break
        page.append(entry)
    return json.dumps(
        {
            "status": "ok",
            "runs": page,
            "next_offset": offset + len(page) if more else None,
        },
        ensure_ascii=False,
        default=str,
    )


class BacktestRunsTool(BaseTool):
    """Discover the backtests earlier turns and sessions already ran."""

    name = "list_backtest_runs"
    description = (
        "List earlier backtest runs (newest first, paged) with the absolute run_dir of each "
        "backtest, its dates and headline metrics. Use it in a follow-up turn, or for a "
        "'[prev_run: ...]' marker, then read artifacts with read_run_artifact(run_dir=...) "
        "instead of re-running the backtest. Defaults to the current session; scope='all' lists every run."
    )
    parameters = {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": list(_SCOPES),
                "description": "session (default) or all",
            },
            "run_id": {
                "type": "string",
                "description": "Only this run id (e.g. from a [prev_run: ...] marker)",
            },
            "limit": {
                "type": "integer",
                "description": f"Runs per page [1, {_MAX_LIMIT}] (default 5)",
            },
            "offset": {
                "type": "integer",
                "description": "Runs to skip; use next_offset from the previous page",
            },
        },
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        return list_backtest_runs(
            current_run_dir=kwargs.get("run_dir"),
            scope=kwargs.get("scope") or "session",
            run_id=kwargs.get("run_id"),
            limit=kwargs.get("limit", 5),
            offset=kwargs.get("offset", 0),
        )
