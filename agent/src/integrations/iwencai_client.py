"""Small server-side client for the iWenCai query2data gateway.

The frontend must not receive or forward the iWenCai credential.  This module
keeps the gateway contract in one place for REST routes that expose the
bundled basic-info and event-query skills.
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Any

from src.config.accessor import get_env_config


DEFAULT_QUERY_URL = "https://openapi.iwencai.com/v1/query2data"
DEFAULT_TIMEOUT_SECONDS = 30


class IwencaiError(RuntimeError):
    """Base error for an iWenCai gateway request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class IwencaiNotConfigured(IwencaiError):
    """Raised when the server has no iWenCai credential."""


def _api_key() -> str:
    configured = get_env_config().data.vibe_trading_iwencai_key.strip()
    return configured or os.getenv("IWENCAI_API_KEY", "").strip()


def _trace_id() -> str:
    return secrets.token_hex(32)


def _headers(api_key: str, trace_id: str, skill_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": skill_id,
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": trace_id,
    }


def query2data(
    query: str,
    *,
    page: int = 1,
    limit: int = 10,
    skill_id: str = "hithink-rest-query",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Query iWenCai and return the gateway JSON body unchanged where possible."""

    api_key = _api_key()
    if not api_key:
        raise IwencaiNotConfigured(
            "iWenCai API key is not configured; set VIBE_TRADING_IWENCAI_KEY "
            "or IWENCAI_API_KEY"
        )

    base_url = os.getenv("IWENCAI_BASE_URL", "https://openapi.iwencai.com").rstrip("/")
    endpoint = os.getenv("IWENCAI_QUERY2DATA_URL", f"{base_url}/v1/query2data")
    trace_id = _trace_id()
    body = json.dumps(
        {
            "query": query,
            "page": str(page),
            "limit": str(limit),
            "is_cache": "1",
            "expand_index": "true",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers=_headers(api_key, trace_id, skill_id),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise IwencaiError(
            f"iWenCai gateway returned HTTP {exc.code}: {detail[:500] or exc.reason}",
            status_code=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IwencaiError(f"iWenCai gateway request failed: {exc}") from exc

    if not raw.strip():
        return {"datas": [], "code_count": 0, "chunks_info": {}, "trace_id": trace_id}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IwencaiError("iWenCai gateway returned non-JSON content") from exc
    if isinstance(payload, dict):
        payload.setdefault("trace_id", trace_id)
        return payload
    if isinstance(payload, list):
        return {"datas": payload, "code_count": len(payload), "trace_id": trace_id}
    return {"text_response": str(payload), "trace_id": trace_id}


def normalize_query_response(payload: dict[str, Any], *, query: str, page: int, limit: int) -> dict[str, Any]:
    """Expose a stable REST envelope while retaining the gateway result fields."""

    datas = payload.get("datas")
    if not isinstance(datas, list):
        datas = []
    try:
        code_count = int(payload.get("code_count") or len(datas))
    except (TypeError, ValueError):
        code_count = len(datas)
    result = dict(payload)
    result.update(
        {
            "ok": True,
            "source": "iwencai",
            "query": query,
            "page": page,
            "limit": limit,
            "code_count": code_count,
            "returned_count": len(datas),
            "has_more": page * limit < code_count,
            "datas": datas,
        }
    )
    return result
