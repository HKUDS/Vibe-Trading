"""QVeris discovery and execution tools."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from src.agent.tools import BaseTool

SIGNUP_URL = "https://qveris.ai/?ref=Vyjjo5G_1cAHJA"
INVITE_CODE = "Vyjjo5G_1cAHJA"
DEFAULT_BASE_URL = "https://qveris.ai/api/v1"
QVERIS_CONFIG_PATH = Path.home() / ".vibe-trading" / "qveris.json"
VALID_MODES = {"free", "paid"}
_LEGACY_MODE_MAP = {
    "preview": "free",
    "allow_paid": "paid",
    "free": "free",
    "paid": "paid",
}

_SESSION_SPEND: dict[str, float] = {}
_SESSION_RESERVED: dict[str, float] = {}
_SESSION_BUDGET_LOCK = threading.Lock()


@dataclass
class QVerisConfig:
    """QVeris local configuration."""

    enabled: bool = False
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    mode: str = "free"
    budget_credits_per_session: float = 50.0


def _read_config_file() -> QVerisConfig:
    """Read the persisted QVeris config without env overrides."""
    if not QVERIS_CONFIG_PATH.exists():
        return QVerisConfig()
    try:
        raw = json.loads(QVERIS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return QVerisConfig()
    cfg = QVerisConfig()
    if isinstance(raw, dict):
        cfg.enabled = bool(raw.get("enabled", cfg.enabled))
        cfg.base_url = str(raw.get("base_url") or cfg.base_url)
        cfg.api_key = str(raw.get("api_key") or "")
        cfg.mode = normalize_qveris_mode(str(raw.get("mode") or cfg.mode))
        try:
            cfg.budget_credits_per_session = float(
                raw.get("budget_credits_per_session", cfg.budget_credits_per_session)
            )
        except (TypeError, ValueError):
            cfg.budget_credits_per_session = 50.0
        if cfg.budget_credits_per_session < 0:
            cfg.budget_credits_per_session = 0.0
    return cfg


def load_qveris_config() -> QVerisConfig:
    """Load QVeris config with environment overrides applied."""
    from src.config.accessor import get_env_config

    cfg = _read_config_file()
    env_key = get_env_config().data.qveris_api_key
    env_url = get_env_config().data.qveris_base_url
    if env_key:
        cfg.api_key = env_key.strip()
    if env_url:
        cfg.base_url = env_url.strip() or DEFAULT_BASE_URL
    return cfg


def save_qveris_config(config: QVerisConfig) -> QVerisConfig:
    """Persist QVeris config with atomic replace and 0600 permissions.

    Args:
        config: Configuration to persist.

    Returns:
        The normalized configuration that was written.
    """
    cfg = QVerisConfig(
        enabled=bool(config.enabled),
        base_url=(config.base_url or DEFAULT_BASE_URL).rstrip("/"),
        api_key=config.api_key or "",
        mode=normalize_qveris_mode(config.mode),
        budget_credits_per_session=max(float(config.budget_credits_per_session), 0.0),
    )
    QVERIS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".qveris.", suffix=".tmp", dir=str(QVERIS_CONFIG_PATH.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(cfg), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, QVERIS_CONFIG_PATH)
        os.chmod(QVERIS_CONFIG_PATH, 0o600)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return cfg


def mask_api_key(api_key: str) -> str:
    """Return a non-reversible display mask for an API key."""
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 7:
        return "***"
    return f"{key[:4]}…{key[-3:]}"


def normalize_qveris_mode(mode: str | None) -> str:
    """Normalize user-facing QVeris mode names."""
    return _LEGACY_MODE_MAP.get(str(mode or "").strip(), "free")


def has_qveris_credentials(config: QVerisConfig | None = None) -> bool:
    """Return whether a QVeris API key is saved or provided."""
    cfg = config or load_qveris_config()
    return bool(cfg.api_key.strip())


def is_qveris_configured(config: QVerisConfig | None = None) -> bool:
    """Return whether QVeris paid routing should be visible."""
    cfg = config or load_qveris_config()
    return has_qveris_credentials(cfg) and normalize_qveris_mode(cfg.mode) == "paid"


def _json_response(payload: dict[str, Any]) -> str:
    """Serialize a tool response."""
    return json.dumps(payload, ensure_ascii=False, default=str)


def _parse_expected_cost(value: Any) -> float | None:
    """Extract a numeric expected-cost hint from QVeris metadata."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return float(match.group(0))


def _quote_from_tool(tool: dict[str, Any] | None) -> dict[str, Any]:
    """Project quote fields from a QVeris tool descriptor."""
    tool = tool or {}
    return {
        "tool_id": tool.get("tool_id"),
        "name": tool.get("name"),
        "expected_cost": tool.get("expected_cost"),
        "billing_rule": tool.get("billing_rule"),
        "stats": tool.get("stats"),
    }


class QVerisClient:
    """Small synchronous client for the QVeris REST API."""

    def __init__(
        self,
        config: QVerisConfig | None = None,
        *,
        client: httpx.Client | None = None,
        min_interval_seconds: float = 0.5,
        max_429_retries: int = 3,
    ) -> None:
        """Initialize the client.

        Args:
            config: Optional config; defaults to :func:`load_qveris_config`.
            client: Injectable HTTP client for tests.
            min_interval_seconds: Minimum spacing between requests.
            max_429_retries: Maximum retries for HTTP 429 responses.
        """
        self.config = config or load_qveris_config()
        self.base_url = self.config.base_url.rstrip("/")
        self._client = client or httpx.Client(follow_redirects=True, timeout=60.0)
        self._min_interval_seconds = max(float(min_interval_seconds), 0.0)
        self._max_429_retries = max(int(max_429_retries), 0)
        self._last_request_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    def _wait_for_slot(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        """Send a JSON request with spacing and 429 Retry-After handling."""
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        attempts = 0
        while True:
            self._wait_for_slot()
            response = self._client.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=self._headers() if auth else None,
            )
            self._last_request_at = time.monotonic()
            if response.status_code == 429 and attempts < self._max_429_retries:
                attempts += 1
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    delay = max(float(retry_after), 0.0)
                except ValueError:
                    delay = 1.0
                time.sleep(delay)
                continue
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    def _download_full_content(self, url: str) -> Any:
        payload = self._request("GET", url, auth=False)
        return payload

    def _hydrate_truncated_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result")
        if not isinstance(result, dict):
            return payload
        full_url = result.get("full_content_file_url")
        if not isinstance(full_url, str) or not full_url:
            return payload
        try:
            result["full_content"] = self._download_full_content(full_url)
            result["full_content_downloaded"] = True
        except Exception as exc:  # noqa: BLE001 - preserve the paid response.
            result["full_content_download_error"] = str(exc)
        return payload

    def search(
        self, query: str, *, limit: int = 20, session_id: str | None = None
    ) -> dict[str, Any]:
        """Call ``POST /search``."""
        body: dict[str, Any] = {"query": query, "limit": min(max(int(limit), 1), 100)}
        if session_id:
            body["session_id"] = session_id
        return self._request("POST", "/search", json_body=body)

    def inspect(
        self,
        tool_ids: list[str],
        *,
        search_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Call ``POST /tools/by-ids``."""
        body: dict[str, Any] = {"tool_ids": tool_ids}
        if search_id:
            body["search_id"] = search_id
        if session_id:
            body["session_id"] = session_id
        return self._request("POST", "/tools/by-ids", json_body=body)

    def execute(
        self,
        tool_id: str,
        *,
        parameters: dict[str, Any],
        search_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        max_response_size: int = 20480,
    ) -> dict[str, Any]:
        """Call ``POST /tools/execute`` and hydrate truncated results."""
        body: dict[str, Any] = {
            "parameters": parameters,
            "max_response_size": max_response_size,
        }
        if search_id:
            body["search_id"] = search_id
        if session_id:
            body["session_id"] = session_id
        if model:
            body["model"] = model
        payload = self._request(
            "POST",
            "/tools/execute",
            json_body=body,
            params={"tool_id": tool_id},
        )
        return self._hydrate_truncated_result(payload)

    def usage_history(self, **params: Any) -> dict[str, Any]:
        """Call ``GET /auth/usage/history/v2``."""
        return self._request("GET", "/auth/usage/history/v2", params=params)

    def credits_ledger(self, **params: Any) -> dict[str, Any]:
        """Call ``GET /auth/credits/ledger``."""
        return self._request("GET", "/auth/credits/ledger", params=params)


class _QVerisBaseTool(BaseTool):
    """Shared availability and client helpers for QVeris tools."""

    @classmethod
    def check_available(cls) -> bool:
        """Hide QVeris tools until explicitly enabled and keyed."""
        return is_qveris_configured()

    def _client(self) -> QVerisClient:
        return QVerisClient()


class QVerisSearchTool(_QVerisBaseTool):
    """Discover QVeris capabilities."""

    name = "qveris_search"
    description = (
        "Search QVeris premium data/tool capabilities. Discover/inspect calls "
        "are free; choose tools by expected_cost and stats.success_rate."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Capability search query."},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 20,
            },
            "session_id": {"type": "string"},
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        if not is_qveris_configured():
            return _json_response({"ok": False, "error": "QVeris is not configured"})
        payload = self._client().search(
            str(kwargs["query"]),
            limit=int(kwargs.get("limit", 20)),
            session_id=kwargs.get("session_id"),
        )
        return _json_response({"ok": True, **payload})


class QVerisInspectTool(_QVerisBaseTool):
    """Inspect full QVeris tool parameter schemas."""

    name = "qveris_inspect"
    description = "Inspect QVeris tools by id before executing a paid call."
    parameters = {
        "type": "object",
        "properties": {
            "tool_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "QVeris tool ids from qveris_search.",
            },
            "search_id": {"type": "string"},
            "session_id": {"type": "string"},
        },
        "required": ["tool_ids"],
    }

    def execute(self, **kwargs: Any) -> str:
        if not is_qveris_configured():
            return _json_response({"ok": False, "error": "QVeris is not configured"})
        payload = self._client().inspect(
            list(kwargs["tool_ids"]),
            search_id=kwargs.get("search_id"),
            session_id=kwargs.get("session_id"),
        )
        return _json_response({"ok": True, **payload})


class QVerisExecuteTool(_QVerisBaseTool):
    """Execute a selected QVeris capability behind paid-mode budget gates."""

    name = "qveris_execute"
    description = (
        "Execute a QVeris tool when paid QVeris routing is enabled. Enforces "
        "the per-session credit budget before sending a billable request."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string"},
            "parameters": {"type": "object"},
            "search_id": {"type": "string"},
            "session_id": {"type": "string"},
            "model": {"type": "string"},
            "max_response_size": {"type": "integer", "default": 20480},
            "expected_cost": {
                "description": "Optional quote copied from qveris_search/inspect.",
            },
            "billing_rule": {"type": "object"},
        },
        "required": ["tool_id", "parameters"],
    }

    def _quote(
        self, client: QVerisClient, tool_id: str, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        quote = {
            "tool_id": tool_id,
            "expected_cost": kwargs.get("expected_cost"),
            "billing_rule": kwargs.get("billing_rule"),
        }
        if quote["expected_cost"] is not None or quote["billing_rule"] is not None:
            return quote
        inspected = client.inspect(
            [tool_id],
            search_id=kwargs.get("search_id"),
            session_id=kwargs.get("session_id"),
        )
        results = inspected.get("results") if isinstance(inspected, dict) else None
        first = results[0] if isinstance(results, list) and results else None
        return _quote_from_tool(first)

    def execute(self, **kwargs: Any) -> str:
        cfg = load_qveris_config()
        if not is_qveris_configured(cfg):
            return _json_response({"ok": False, "error": "QVeris is not configured"})
        client = self._client()
        tool_id = str(kwargs["tool_id"])
        quote = self._quote(client, tool_id, kwargs)
        session_id = str(kwargs.get("session_id") or "default")
        budget = max(float(cfg.budget_credits_per_session), 0.0)
        expected = _parse_expected_cost(quote.get("expected_cost"))
        with _SESSION_BUDGET_LOCK:
            spent = _SESSION_SPEND.get(session_id, 0.0)
            reserved = _SESSION_RESERVED.get(session_id, 0.0)
            valid_quote = (
                expected is not None and math.isfinite(expected) and expected >= 0.0
            )
            if (
                not valid_quote
                or spent >= budget
                or spent + reserved + expected > budget
            ):
                return _json_response(
                    {
                        "ok": False,
                        "status": "budget_exceeded",
                        "spent_credits": spent,
                        "budget_credits_per_session": budget,
                        "quote": quote,
                    }
                )
            _SESSION_RESERVED[session_id] = reserved + expected

        try:
            payload = client.execute(
                tool_id,
                parameters=dict(kwargs["parameters"]),
                search_id=kwargs.get("search_id"),
                session_id=kwargs.get("session_id"),
                model=kwargs.get("model"),
                max_response_size=int(kwargs.get("max_response_size", 20480)),
            )
        except Exception:
            with _SESSION_BUDGET_LOCK:
                remaining = _SESSION_RESERVED.get(session_id, 0.0) - expected
                if remaining > 1e-12:
                    _SESSION_RESERVED[session_id] = remaining
                else:
                    _SESSION_RESERVED.pop(session_id, None)
            raise

        try:
            cost = float(payload.get("cost"))
        except (TypeError, ValueError):
            cost = expected
        if not math.isfinite(cost) or cost < 0.0:
            cost = expected

        with _SESSION_BUDGET_LOCK:
            remaining = _SESSION_RESERVED.get(session_id, 0.0) - expected
            if remaining > 1e-12:
                _SESSION_RESERVED[session_id] = remaining
            else:
                _SESSION_RESERVED.pop(session_id, None)
            _SESSION_SPEND[session_id] = _SESSION_SPEND.get(session_id, 0.0) + cost
            session_spent = _SESSION_SPEND[session_id]

        payload["cost"] = cost
        payload["remaining_credits"] = payload.get("remaining_credits")
        payload["session_spent_credits"] = session_spent
        return _json_response({"ok": True, **payload})
