"""Server-side bridge for the installed Iwencai SkillHub search skills.

SkillHub's ``install`` CLI installs skills; the installed skill scripts are
the query CLIs.  This module deliberately invokes those scripts in a child
process so the browser never sees the API key or the provider request.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unicodedata import normalize

from src.config.accessor import get_env_config


_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_SKILL_ROOT = Path.home() / ".iwencai-skillhub" / "skills"


class IwencaiSkillError(RuntimeError):
    """Raised when an installed Iwencai search skill cannot return data."""


def _api_key() -> str:
    configured = get_env_config().data.vibe_trading_iwencai_key.strip()
    return configured or os.getenv("IWENCAI_API_KEY", "").strip()


def _skill_root() -> Path:
    configured = os.getenv("IWENCAI_SKILL_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _DEFAULT_SKILL_ROOT


def _script_path(skill: str) -> Path:
    script_name = f"{skill.replace('-', '_')}.py"
    candidates = [
        _skill_root() / skill / "scripts" / script_name,
        Path(__file__).resolve().parents[2] / "skills" / skill / "scripts" / script_name,
    ]
    for candidate in candidates:
        try:
            readable = candidate.is_file()
        except OSError:
            # A user-level install can be present but unreadable when the API
            # server runs under a service account; try the project install.
            readable = False
        if readable:
            return candidate
    raise IwencaiSkillError(
        f"Iwencai skill {skill!r} is not installed; expected {candidates[0]}"
    )


def _run_skill(skill: str, query: str, *, size: int) -> dict[str, Any]:
    api_key = _api_key()
    if not api_key:
        raise IwencaiSkillError(
            "Iwencai API key is not configured; set VIBE_TRADING_IWENCAI_KEY "
            "or IWENCAI_API_KEY"
        )
    script = _script_path(skill)
    env = os.environ.copy()
    # The official scripts intentionally read the credential from this name.
    # Populate it from the application's existing supported alias as needed,
    # while never putting the key in command-line arguments.
    env["IWENCAI_API_KEY"] = api_key
    try:
        completed = subprocess.run(
            [sys.executable, str(script), query, "--size", str(max(1, min(size, 100)))],
            capture_output=True,
            check=False,
            env=env,
            timeout=int(os.getenv("IWENCAI_SKILL_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IwencaiSkillError(f"Iwencai {skill} CLI failed: {exc}") from exc

    raw = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise IwencaiSkillError(
            f"Iwencai {skill} CLI returned {completed.returncode}: {detail[:500]}"
        )
    if not raw:
        raise IwencaiSkillError(f"Iwencai {skill} CLI returned an empty response")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IwencaiSkillError(f"Iwencai {skill} CLI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise IwencaiSkillError(f"Iwencai {skill} CLI returned an invalid payload")
    if payload.get("status_code") not in (None, 0):
        raise IwencaiSkillError(
            f"Iwencai {skill} search failed: {payload.get('status_msg') or payload.get('status_code')}"
        )
    return payload


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (payload.get("data") or []) if isinstance(item, dict)]


def _publish_date(row: dict[str, Any]) -> str:
    value = row.get("publish_date") or row.get("publishDate")
    if value:
        return str(value)
    timestamp = row.get("publish_time") or row.get("publishTime")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return ""


def _stock_query(canonical: str, kind: str) -> str:
    code, _, market = canonical.upper().partition(".")
    market_code = f"{code}.{market}" if market else code
    return f"{code} {market_code} 近一年{kind}"


def _normalize_report(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    publish_date = _publish_date(row)
    return {
        "title": row.get("title") or "",
        "summary": row.get("summary") or row.get("source_original") or "",
        "publishDate": publish_date,
        "publish_time": row.get("publish_time"),
        "orgSName": extra.get("organization") or extra.get("publish_source") or "",
        "rating": extra.get("rating") or "",
        "author": extra.get("author") or "",
        "url": row.get("url") or "",
        "source": "同花顺问财",
        "iwencai_id": row.get("uid") or str(row.get("id") or "").rsplit("_", 1)[0],
    }


def _normalize_news(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    publish_date = _publish_date(row)
    return {
        "title": row.get("title") or "",
        "summary": row.get("summary") or row.get("source_original") or "",
        "content": row.get("summary") or row.get("source_original") or "",
        "time": publish_date,
        "published": publish_date,
        "source": extra.get("real_publish_source") or extra.get("publish_source") or "同花顺问财",
        "url": row.get("url") or "",
        "iwencai_id": row.get("uid") or str(row.get("id") or "").rsplit("_", 1)[0],
    }


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse provider chunks and cross-source copies while preserving order."""
    seen: set[tuple[str, ...]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        title = re.sub(r"\s+", " ", normalize("NFKC", str(item.get("title") or "")).strip()).lower()
        published = str(item.get("publishDate") or item.get("time") or item.get("published") or "")[:10]
        keys: list[tuple[str, ...]] = []
        identifier = str(item.get("iwencai_id") or "").strip()
        url = str(item.get("url") or "").strip().rstrip("/")
        if identifier:
            keys.append(("id", identifier))
        if url:
            keys.append(("url", url))
        if title:
            keys.append(("title", title, published))
        if any(key in seen for key in keys):
            continue
        seen.update(keys)
        unique.append(item)
    return unique


def search_stock_reports(canonical: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Query the installed report-search skill for one A-share."""

    payload = _run_skill("report-search", _stock_query(canonical, "研报"), size=limit)
    return _dedupe_items([_normalize_report(row) for row in _rows(payload)])[:limit]


def search_stock_news(canonical: str, *, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
    """Query the installed news-search skill and emulate page-based REST data."""

    page_index = max(1, int(page))
    size = page_index * max(1, int(page_size))
    payload = _run_skill("news-search", _stock_query(canonical, "新闻"), size=size)
    rows = _dedupe_items([_normalize_news(row) for row in _rows(payload)])
    start = (page_index - 1) * page_size
    return rows[start : start + page_size]


__all__ = ["IwencaiSkillError", "search_stock_news", "search_stock_reports"]
