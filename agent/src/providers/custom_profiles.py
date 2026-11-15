"""Custom provider profiles: connection testing, OS-vault storage and activation."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.config.accessor import get_env_config
from src.config.paths import get_runtime_root
from src.config.writer import _write_json_atomically
from src.providers.endpoint_guard import is_non_public_address, proxy_applies, public_only_async_client
from src.providers.settings import CONFIG_LOCK, SettingsStore
from src.trading.credentials import CredentialStore

CONFIG_FILENAME = "custom-llm-providers.json"
STORE_LOCK = RLock()

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CustomProviderStore:
    """Store custom-provider metadata on disk and API keys in the OS vault."""

    def __init__(self, path: Path | None = None, backend: Any = None) -> None:
        self.path = path or (get_runtime_root() / CONFIG_FILENAME)
        self.credentials = CredentialStore(backend)

    def list_public(self) -> list[dict[str, Any]]:
        payload = self._read()
        profiles = payload.get("profiles", {})
        return [
            {
                "id": profile_id,
                "label": str(item.get("label") or profile_id),
                "base_url": str(item.get("base_url") or ""),
                "model": str(item.get("model") or ""),
                "api_key_configured": self.credentials.status(
                    f"custom-provider:{profile_id}", ["api_key"]
                ).get("api_key", False),
                "active": (get_env_config().llm.langchain_provider == "custom" and payload.get("active_id") == profile_id),
                "last_tested_at": item.get("last_tested_at"),
            }
            for profile_id, item in sorted(profiles.items())
            if isinstance(item, dict)
        ]

    def save(
        self,
        *,
        profile_id: str,
        label: str,
        base_url: str,
        model: str,
        api_key: str,
        last_tested_at: str | None = None,
    ) -> dict[str, Any]:
        """Save tested metadata and vault credentials without changing an active profile."""
        with STORE_LOCK:
            profile_id = profile_id.strip().lower()
            if not _ID_RE.fullmatch(profile_id):
                raise ValueError("Provider id must use lowercase letters, numbers, dot, dash, or underscore")
            if not label.strip() or len(label.strip()) > 100:
                raise ValueError("Provider label must contain 1 to 100 characters")
            if not base_url.strip() or not model.strip() or not api_key.strip():
                raise ValueError("Provider base URL, model, and API key are required")
            payload = self._read()
            profiles = payload.setdefault("profiles", {})
            if payload.get("active_id") == profile_id:
                raise ValueError("Save changes under a new id before activating the updated profile")
            profiles[profile_id] = {
                "label": label.strip(),
                "base_url": base_url.strip().rstrip("/"),
                "model": model.strip(),
                "last_tested_at": last_tested_at or _now(),
            }
            self.credentials.save(f"custom-provider:{profile_id}", {"api_key": api_key.strip()})
            self._write(payload)
            return next(item for item in self.list_public() if item["id"] == profile_id)

    def get(self, profile_id: str) -> dict[str, Any]:
        profile_id = profile_id.strip().lower()
        item = self._read().get("profiles", {}).get(profile_id)
        if not isinstance(item, dict):
            raise ValueError(f"Unknown custom provider profile: {profile_id}")
        api_key = self.credentials.load(f"custom-provider:{profile_id}", ["api_key"]).get("api_key", "")
        if not api_key:
            raise ValueError(f"Custom provider profile has no API key: {profile_id}")
        return {"id": profile_id, **item, "api_key": api_key}

    def activate(self, profile_id: str) -> dict[str, Any]:
        profile = self.get(profile_id)
        payload = self._read()
        payload["active_id"] = profile_id.strip().lower()
        self._write(payload)
        return {key: value for key, value in profile.items() if key != "api_key"}

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}, "active_id": None}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid custom provider store: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), dict):
            raise ValueError("Invalid custom provider store: profiles must be an object")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        _write_json_atomically(self.path, payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_provider_credentials() -> dict[str, str] | None:
    store = CustomProviderStore()
    payload = store._read()
    active_id = str(payload.get("active_id") or "").strip()
    if not active_id:
        raise RuntimeError("No custom provider is active; select one in Settings")
    profile = store.get(active_id)
    return {key: str(profile[key]) for key in ("base_url", "model", "api_key")}


_PROVIDER_REQUEST_TIMEOUT_S = 60.0


def _validate_custom_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Provider base URL must be an HTTP(S) URL without embedded credentials")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
        raise ValueError("Provider base URL cannot target local or metadata services")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and is_non_public_address(address):
        raise ValueError("Provider base URL cannot target local or private network addresses")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return normalized


def _reject_private_dns_targets(base_url: str) -> None:
    hostname = urlsplit(base_url).hostname
    if not hostname:
        raise ValueError("Provider base URL must include a hostname")
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Provider hostname could not be resolved") from exc
    for result in results:
        address = ipaddress.ip_address(result[4][0])
        if is_non_public_address(address, resolved=True):
            raise ValueError("Provider hostname resolves to a local or private network address")


async def _perform_completion_test(*, base_url: str, model: str, api_key: str) -> dict[str, Any]:
    started = time.perf_counter()
    normalized_base_url = _validate_custom_base_url(base_url)
    import asyncio

    await asyncio.to_thread(_reject_private_dns_targets, normalized_base_url)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: PROVIDER_TEST_OK"}],
        "max_tokens": 32,
        "temperature": 0,
    }
    # Re-check direct connections at dial time, even after the DNS preflight.
    client_type = httpx.AsyncClient if proxy_applies(normalized_base_url) else public_only_async_client
    try:
        async with client_type(timeout=_PROVIDER_REQUEST_TIMEOUT_S, follow_redirects=False) as client:
            response = await client.post(f"{normalized_base_url}/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"Provider returned HTTP {exc.response.status_code}") from exc
    except httpx.ConnectError as exc:
        raise ValueError(f"Provider test failed: {exc}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError("Provider test failed: endpoint did not return valid JSON") from exc
    try:
        content = payload["choices"][0]["message"].get("content", "")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Provider test failed: response had no chat completion") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Provider test failed: response had no text")
    return {
        "response_preview": str(content).replace(api_key, "[redacted]").strip()[:500],
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def activate_custom_provider(
    profile_id: str, *, store: CustomProviderStore, settings: SettingsStore | None = None
) -> dict[str, Any]:
    """Activate one vault profile and roll back metadata if settings cannot persist."""
    settings = settings or SettingsStore()
    with CONFIG_LOCK, STORE_LOCK:
        profile = store.get(profile_id)
        updates = {"LANGCHAIN_PROVIDER": "custom", "LANGCHAIN_MODEL_NAME": profile["model"]}
        previous = store._read()
        store.activate(profile["id"])
        try:
            settings.persist(updates, apply=True)
        except Exception:
            store._write(previous)
            raise
    return {"status": "ok", "active_id": profile["id"], "model": profile["model"], "base_url": profile["base_url"]}
