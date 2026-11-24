"""Choosing a provider, model and reasoning effort among the server's own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.providers.discovery import LLMProviderOption
from src.providers.registry import get_provider_capabilities, provider_catalog
from src.providers.settings import ModelOptions, ProviderConfig, current_settings, resolve_config

SESSION_CONFIG_KEY = "model_selection"
SELECTION_FIELDS = ("provider", "model", "reasoning_effort")
LLM_API_KEY_PLACEHOLDERS = frozenset({"", "sk-or-v1-your-key-here", "sk-xxx", "xxx", "gsk_xxx"})
LLM_PROVIDERS = [LLMProviderOption(**item) for item in provider_catalog()]
LLM_PROVIDER_BY_NAME = {provider.name: provider for provider in LLM_PROVIDERS}
# Keep a session’s selected provider credentials isolated from the server default.
_GENERIC_SETTINGS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE")


class ModelSelectionError(ValueError):
    """A provider, model or effort the server will not use."""


@dataclass(frozen=True)
class ModelSelection:
    """A provider/model choice with an optional explicit reasoning effort."""

    provider: str
    model: str
    reasoning_effort: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return the persisted form."""
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }


def is_configured_secret(value: str, placeholders: set[str] | frozenset[str]) -> bool:
    """Return True when a secret is set and not a documented placeholder."""
    normalized = value.strip().strip('"').strip("'")
    if not normalized:
        return False
    return normalized.lower() not in {p.lower() for p in placeholders}


def custom_provider_option(active: Mapping[str, str]) -> LLMProviderOption:
    """Describe the active custom profile as a provider option."""
    return LLMProviderOption(
        name="custom",
        label="Custom (credential vault)",
        api_key_env=None,
        base_url_env="OPENAI_BASE_URL",
        default_model=active["model"],
        default_base_url=active["base_url"],
        auth_type="credential_vault",
        reasoning_efforts=[],
    )


def check_provider_choice(
    provider: str, model: str, reasoning_effort: str | None
) -> tuple[LLMProviderOption, str, str]:
    """Apply the catalog's rules to a provider, model and effort."""
    name = provider.strip().lower()
    model_name = model.strip()
    if name == "custom":
        from src.providers.custom_profiles import active_provider_credentials

        try:
            active = active_provider_credentials()
        except (RuntimeError, KeyError) as exc:
            raise ModelSelectionError(str(exc) or "No custom provider is active") from exc
        if model_name != active["model"]:
            raise ModelSelectionError(
                "Edit and test a custom provider in the provider manager before activating it"
            )
        option = custom_provider_option(active)
    else:
        option = LLM_PROVIDER_BY_NAME.get(name)
        if option is None:
            raise ModelSelectionError("Unsupported LLM provider")
    if not model_name:
        raise ModelSelectionError("Model name is required")
    effort = (reasoning_effort or "").strip().lower()
    if effort and effort not in option.reasoning_efforts:
        raise ModelSelectionError(
            f"Reasoning effort must be one of {', '.join(option.reasoning_efforts)}, "
            "or empty to leave it unset"
        )
    return option, model_name, effort


def credential_status(option: LLMProviderOption, api_key: str) -> tuple[bool, Optional[str]]:
    """Report whether a provider has usable credentials on this server."""
    if option.auth_type == "oauth":
        try:
            from src.providers.openai_codex import get_openai_codex_login_status

            return bool(get_openai_codex_login_status()), None
        except Exception:
            return False, None
    if option.auth_type in {"gh_cli", "claude_cli"}:
        try:
            if option.auth_type == "gh_cli":
                from src.providers.copilot_auth import get_copilot_auth_status as login_status
            else:
                from src.providers.claude_cli import get_claude_cli_auth_status as login_status

            authenticated, auth_status = login_status()
        except Exception:
            return False, None
        return authenticated, auth_status if authenticated else None
    return is_configured_secret(api_key, LLM_API_KEY_PLACEHOLDERS), None


def parse_model_selection(raw: Any) -> ModelSelection:
    """Check a selection's shape without consulting the server's settings."""
    if not isinstance(raw, Mapping):
        raise ModelSelectionError("A model selection must be an object")
    extra = sorted(str(key) for key in raw if key not in SELECTION_FIELDS)
    if extra:
        raise ModelSelectionError(
            f"A model selection accepts only {', '.join(SELECTION_FIELDS)}; "
            f"{', '.join(extra)} cannot be set per session. Endpoints, keys and "
            "headers come from the server's provider settings."
        )
    provider, model = raw.get("provider"), raw.get("model")
    effort = raw.get("reasoning_effort")
    if not isinstance(provider, str) or not isinstance(model, str):
        raise ModelSelectionError("provider and model must be strings")
    if effort is not None and not isinstance(effort, str):
        raise ModelSelectionError("reasoning_effort must be a string")
    return ModelSelection(provider, model, effort or "")


def selection_settings(selection: ModelSelection, base: Mapping[str, str]) -> dict[str, str]:
    """Return the server's settings with a selection applied, as a private copy."""
    values = dict(base)
    configured = ModelOptions(**values).langchain_provider.strip().lower()
    values["LANGCHAIN_PROVIDER"] = selection.provider
    values["LANGCHAIN_MODEL_NAME"] = selection.model
    values["LANGCHAIN_REASONING_EFFORT"] = selection.reasoning_effort
    if selection.provider not in {configured, "custom"}:
        caps = get_provider_capabilities(selection.provider, selection.model)
        own = {caps.api_key_env, caps.base_url_env}
        if "OPENAI_BASE_URL" in own:
            own.add("OPENAI_API_BASE")
        for key in _GENERIC_SETTINGS:
            if key not in own:
                values.pop(key, None)
    return values


def validate_model_selection(
    raw: Any, *, settings: Mapping[str, str] | None = None
) -> tuple[ModelSelection, ProviderConfig]:
    """Validate a selection and resolve the connection it would use."""
    written = parse_model_selection(raw)
    option, model, effort = check_provider_choice(
        written.provider, written.model, written.reasoning_effort
    )
    selection = ModelSelection(option.name, model, effort)
    base = current_settings() if settings is None else settings
    keyless = option.auth_type == "api_key" and not option.api_key_required
    configured_provider = ModelOptions(**base).langchain_provider.strip().lower()
    if keyless and option.name != configured_provider and not str(
        base.get(option.base_url_env, "") or ""
    ).strip():
        # Require explicit setup when a provider has no credential to prove it.
        raise ModelSelectionError(
            f"Provider {option.name} needs no key, so it can be selected only after "
            f"the server sets {option.base_url_env}"
        )
    values = selection_settings(selection, base)
    try:
        config = resolve_config(environment=values)
    except (RuntimeError, KeyError, ValueError) as exc:
        raise ModelSelectionError(f"Provider {option.name} is not usable: {exc}") from exc
    configured, _hint = credential_status(option, config.api_key)
    if not configured and (option.api_key_required or option.auth_type != "api_key"):
        raise ModelSelectionError(
            f"Provider {option.name} has no credentials configured on this server"
        )
    return selection, config


def configured_selection(settings: Mapping[str, str] | None = None) -> ModelSelection:
    """Return the server's own provider/model/effort, without reading secrets."""
    options = ModelOptions(**(current_settings() if settings is None else settings))
    return ModelSelection(
        options.langchain_provider.strip().lower(),
        options.langchain_model_name.strip(),
        options.langchain_reasoning_effort.strip().lower(),
    )
