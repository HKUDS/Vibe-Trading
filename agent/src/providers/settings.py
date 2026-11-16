"""Provider settings: private persistence and immutable per-client snapshots."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from pydantic import ConfigDict, Field, model_validator

from src.config.accessor import get_env_value, reset_env_config
from src.config.dotenv import _atomic_write_secret, _read_env_values, _write_env_values, render_env
from src.config.env_schema import LLMConfig, _numeric_type
from src.providers.registry import get_provider_capabilities, provider_catalog

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

logger = logging.getLogger(__name__)
CONFIG_LOCK = RLock()
AGENT_DIR = Path(__file__).resolve().parents[2]
_ENV_CANDIDATES = [Path.home() / ".vibe-trading" / ".env", AGENT_DIR / ".env", Path.cwd() / ".env"]
_ENV_LABELS = ("~/.vibe-trading/.env", "<AGENT_DIR>/.env", "<CWD>/.env")
_dotenv_loaded = False


class ModelOptions(LLMConfig):
    """Reuse the existing schema and defaults without reading ambient state."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY", default="", repr=False)

    @model_validator(mode="before")
    @classmethod
    def _load_from_env(cls, data):
        values = dict(data)
        for name, info in cls.model_fields.items():
            key = info.alias if info.alias in values else name
            numeric = _numeric_type(info.annotation)
            if key in values and numeric and isinstance(values[key], str):
                try:
                    values[key] = numeric(values[key])
                except ValueError:
                    values.pop(key)
        return values


@dataclass(frozen=True)
class ProviderConfig:
    """One resolved connection and generation snapshot; secrets never enter repr."""

    provider: str
    model: str
    backend: str
    base_url: str = field(repr=False)
    options: ModelOptions = field(repr=False)
    api_key: str = field(repr=False, default="")
    auth_token: str = field(repr=False, default="")
    environment: Mapping[str, str] = field(repr=False, default_factory=dict)


def resolve_config(*, model_name: str | None = None, environment: Mapping[str, str] | None = None) -> ProviderConfig:
    """Resolve once from supplied settings and, for custom providers, the vault.

    Args:
        model_name: Optional model override.
        environment: Complete connection settings, or None for current settings.

    Returns:
        An immutable config for one client and all of its subsequent requests.
    """
    with CONFIG_LOCK:
        if environment is None:
            _ensure_dotenv()
        values = dict(os.environ if environment is None else environment)
        options = ModelOptions(**values)
        provider = options.langchain_provider.strip().lower()
        model = model_name or options.langchain_model_name.strip()
        creds = get_llm_credentials(provider, model, environment=values)
        if provider == "custom":
            model = model_name or creds["model"]
        backend = get_provider_capabilities(provider).backend
        if backend == "anthropic":
            creds = {
                "api_key": values.get("ANTHROPIC_API_KEY", ""),
                "base_url": values.get("ANTHROPIC_BASE_URL")
                or values.get("ANTHROPIC_API_URL")
                or "https://api.anthropic.com",
            }
        if backend in {"openai_codex", "claude_cli"}:
            creds["api_key"] = ""
        if backend == "openai_codex":
            creds["base_url"] = options.openai_codex_base_url
        return ProviderConfig(
            provider,
            model,
            backend,
            creds["base_url"],
            options,
            creds["api_key"],
            values.get("ANTHROPIC_AUTH_TOKEN", ""),
            MappingProxyType(values),
        )


def _redact_env_source(loaded: Path | None) -> str:
    """Map a resolved `.env` candidate to a stable, leak-free label.

    Returns a symbolic slot label (never the absolute path) so a stale
    or shadowed `.env` stays diagnosable without exposing the OS
    username, home, or CWD (CWE-209). A candidate outside the fixed
    list (e.g. one injected by a test) collapses to a generic
    placeholder rather than echoing a real path.
    """
    if loaded is None:
        return "none (no .env file found)"
    for label, candidate in zip(_ENV_LABELS, _ENV_CANDIDATES):
        if loaded == candidate:
            return label
    return "<.env>"


def _load_env_file(path: Path) -> None:
    """Load a single .env file into os.environ without clobbering real vars.

    Exported environment variables are explicit operator intent and outrank
    the file; ``.env`` only fills the gaps (pinned by
    ``test_dispatch_connector_never_overrides_a_real_environment_variable``).
    """
    if load_dotenv is not None:
        load_dotenv(dotenv_path=path, override=False)
    else:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def _ensure_dotenv() -> None:
    """Load `.env` from the first found candidate path."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    loaded = None
    for candidate in _ENV_CANDIDATES:
        if candidate.exists():
            _load_env_file(candidate)
            loaded = candidate
            break
    if loaded is not None:
        reset_env_config()
    _dotenv_loaded = True
    logger.info("dotenv resolved from %s", _redact_env_source(loaded))


def _sync_provider_env() -> None:
    """Legacy initialization hook; no longer rewrites another provider's keys."""
    with CONFIG_LOCK:
        _ensure_dotenv()
        reset_env_config()


def get_llm_credentials(
    provider: str | None,
    model: str | None,
    *, environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve legacy-compatible credentials without changing process settings.

    Args:
        provider: Configured provider name.
        model: Configured model name, including legacy model-based inference.
        environment: Captured settings, or None for current environment/login.

    Returns:
        Provider, API key, endpoint and model. Custom profiles read the active
        credential vault; other providers retain the generic OPENAI_* fallback.
    """
    env = os.environ if environment is None else environment
    normalized_provider = (provider or "").strip().lower().replace("_", "-")
    if normalized_provider == "custom":
        from src.providers.custom_profiles import active_provider_credentials

        active = active_provider_credentials()
        return {"provider": "custom", **active}

    caps = get_provider_capabilities(provider, model)
    key_env, base_env = caps.api_key_env, caps.base_url_env

    api_key = (env.get(key_env, "") if key_env else "") or env.get("OPENAI_API_KEY", "")
    if key_env is None:
        api_key = api_key or "ollama"

    if caps.name == "copilot":
        from src.providers.copilot_auth import TOKEN_ENV_NAMES, is_supported_token, _gh_cli_token
        api_key = _gh_cli_token() if environment is None else next(
            (env[name].strip() for name in TOKEN_ENV_NAMES if is_supported_token(env.get(name, "").strip())),
            "",
        )

    base_url = (
        env.get(base_env, "")
        or env.get("OPENAI_BASE_URL", "")
        or env.get("OPENAI_API_BASE", "")
        or caps.default_base_url
    )
    if caps.name == "ollama":
        base_url = base_url.strip().rstrip("/")
        if base_url and not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

    return {
        "provider": (provider or "").strip().lower(),
        "api_key": api_key,
        "base_url": base_url,
        "model": model or "",
    }


def secret_names() -> set[str]:
    """Names whose values belong to the desktop credential store."""
    return {"TUSHARE_TOKEN", "GILDATA_TOKEN"} | {p["api_key_env"] for p in provider_catalog() if p.get("api_key_env")}


@dataclass(frozen=True)
class SettingsStore:
    """Canonical dotenv settings; paths can be supplied by an embedding host."""

    path: Path = field(default_factory=lambda: Path.home() / ".vibe-trading" / ".env")
    legacy: Path = AGENT_DIR / ".env"
    example: Path = AGENT_DIR / ".env.example"

    def read(self) -> dict[str, str]:
        """Read existing settings without creating files or exposing vault keys."""
        values = next((_read_env_values(p) for p in (self.path, self.legacy, self.example) if p.exists()), {})
        if get_env_value("VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS") == "1":
            for key in secret_names():
                if get_env_value(key):
                    values[key] = get_env_value(key)
                else:
                    values.pop(key, None)
        return values

    def persist(self, updates: Mapping[str, str], *, apply: bool = False, replace: bool = False) -> dict[str, str]:
        """Upsert settings, or replace them for an explicitly confirmed CLI reset."""
        with CONFIG_LOCK:
            merged = dict(updates)
            if not replace and not self.path.exists() and self.legacy != self.path and self.legacy.exists():
                merged = {**_read_env_values(self.legacy), **merged}
            if get_env_value("VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS") == "1":
                merged.update({key: "" for key in secret_names()})
            if replace:
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                _atomic_write_secret(self.path, render_env(merged), allow_in_place=False)
            else:
                _write_env_values(self.path, merged)
            if apply:
                self.apply(updates)
            return self.read()

    def apply(self, updates: Mapping[str, str]) -> None:
        """Change defaults for future clients; existing snapshots remain unchanged."""
        with CONFIG_LOCK:
            for key, value in updates.items():
                if value:
                    os.environ[key] = str(value)
                else:
                    os.environ.pop(key, None)
            reset_env_config()
