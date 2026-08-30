"""Persistent metadata and OS-vault secrets for custom LLM providers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root
from src.trading.credentials import CredentialStore

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CustomProviderStore:
    """Store custom-provider metadata on disk and API keys in the OS vault."""

    def __init__(self, path: Path | None = None, backend: Any = None) -> None:
        self.path = path or (get_runtime_root() / "custom-llm-providers.json")
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
                    profile_id, ["api_key"]
                ).get("api_key", False),
                "active": payload.get("active_id") == profile_id,
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
        profile_id = profile_id.strip().lower()
        if not _ID_RE.fullmatch(profile_id):
            raise ValueError("Provider id must use lowercase letters, numbers, dot, dash, or underscore")
        if not label.strip() or len(label.strip()) > 100:
            raise ValueError("Provider label must contain 1 to 100 characters")
        if not base_url.strip() or not model.strip() or not api_key.strip():
            raise ValueError("Provider base URL, model, and API key are required")
        payload = self._read()
        profiles = payload.setdefault("profiles", {})
        profiles[profile_id] = {
            "label": label.strip(),
            "base_url": base_url.strip().rstrip("/"),
            "model": model.strip(),
            "last_tested_at": last_tested_at or _now(),
        }
        self.credentials.save(profile_id, {"api_key": api_key.strip()})
        self._write(payload)
        return next(item for item in self.list_public() if item["id"] == profile_id)

    def get(self, profile_id: str) -> dict[str, Any]:
        profile_id = profile_id.strip().lower()
        item = self._read().get("profiles", {}).get(profile_id)
        if not isinstance(item, dict):
            raise ValueError(f"Unknown custom provider profile: {profile_id}")
        api_key = self.credentials.load(profile_id, ["api_key"]).get("api_key", "")
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
        return payload if isinstance(payload, dict) else {"profiles": {}, "active_id": None}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_provider_credentials() -> dict[str, str] | None:
    try:
        store = CustomProviderStore()
        payload = store._read()
        active_id = str(payload.get("active_id") or "").strip()
        if not active_id:
            return None
        profile = store.get(active_id)
        return {
            "base_url": str(profile["base_url"]),
            "model": str(profile["model"]),
            "api_key": str(profile["api_key"]),
        }
    except (RuntimeError, ValueError, OSError):
        return None
