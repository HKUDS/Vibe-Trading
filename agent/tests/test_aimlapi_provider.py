"""AI/ML API provider wiring and attribution-header scoping.

The attribution headers are worth their own file because every failure mode
here is silent: a malformed partner id, a header that never leaves, or a header
that leaves for the wrong host all return HTTP 200 and look exactly like a
working integration.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import cli
from cli.onboard import PROVIDERS as ONBOARD_PROVIDERS
from src.config.accessor import reset_env_config
from src.providers.capabilities import (
    AIMLAPI_ATTRIBUTION_HEADERS,
    AIMLAPI_ATTRIBUTION_HOSTS,
    get_llm_credentials,
    get_provider_capabilities,
)
from src.providers.llm import build_llm
from src.swarm.models import _PUBLIC_PROVIDERS

# Backend contract for the partner id. A value that does not match is accepted
# by the gateway and then dropped, so a typo is invisible at runtime.
_PARTNER_ID_PATTERN = re.compile(r"^part_[A-Za-z0-9]{1,64}$")

_BASE_ENV = {
    "LANGCHAIN_PROVIDER": "aimlapi",
    "AIMLAPI_API_KEY": "aimlapi-test-key",
    "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
}


def _build_and_capture(env: dict[str, str]) -> dict:
    """Build an LLM with ``env`` applied and return the ChatOpenAI kwargs."""
    import src.providers.llm as llm_mod

    captured: dict = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    try:
        with patch.object(llm_mod, "_dotenv_loaded", True):
            with patch.dict(os.environ, env, clear=True):
                with patch.object(llm_mod, "ChatOpenAIWithReasoning", _FakeChatOpenAI):
                    build_llm()
    finally:
        reset_env_config()
    return captured


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_capabilities_match_the_live_wire_behaviour() -> None:
    """AI/ML API is an OpenAI-compatible gateway with its own key namespace."""
    caps = get_provider_capabilities("aimlapi", "deepseek/deepseek-v4-pro")

    assert caps.name == "aimlapi"
    assert caps.api_key_env == "AIMLAPI_API_KEY"
    assert caps.base_url_env == "AIMLAPI_BASE_URL"
    assert caps.capture_reasoning is True
    assert caps.top_level_reasoning_effort is True
    # ``extra_body.reasoning`` is an OpenRouter relay option, not a wire
    # standard: this gateway takes the top-level field instead.
    assert caps.openrouter_reasoning_body is False
    assert caps.send_reasoning_content is False


def test_registered_in_every_provider_surface() -> None:
    """A provider missing from one surface is unreachable from that surface."""
    providers_path = (
        Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    )
    catalog = {
        item["name"]: item
        for item in json.loads(providers_path.read_text(encoding="utf-8"))
    }
    entry = catalog["aimlapi"]
    onboard = next(item for item in ONBOARD_PROVIDERS if item.key == "aimlapi")
    legacy = next(
        item for item in cli._PROVIDER_CHOICES if item["provider"] == "aimlapi"
    )

    assert entry["default_base_url"] == onboard.base_url == legacy["base_url"]
    assert entry["api_key_env"] == onboard.key_env == legacy["key_env"]
    assert entry["base_url_env"] == onboard.base_env == legacy["base_env"]
    assert entry["default_model"] == onboard.default_model == legacy["model"]
    assert "aimlapi" in _PUBLIC_PROVIDERS


def test_display_name_is_the_vendor_domain() -> None:
    """Every user-facing surface shows the vendor's own name."""
    providers_path = (
        Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    )
    catalog = {
        item["name"]: item
        for item in json.loads(providers_path.read_text(encoding="utf-8"))
    }
    onboard = next(item for item in ONBOARD_PROVIDERS if item.key == "aimlapi")
    legacy = next(
        item for item in cli._PROVIDER_CHOICES if item["provider"] == "aimlapi"
    )

    assert catalog["aimlapi"]["label"] == "aimlapi.com"
    assert onboard.label == "aimlapi.com"
    assert str(legacy["label"]).startswith("aimlapi.com")


def test_base_url_falls_back_to_the_catalog_default() -> None:
    """A key alone must be enough; no *_BASE_URL should mean api.aimlapi.com."""
    with patch.dict(os.environ, _BASE_ENV, clear=True):
        creds = get_llm_credentials("aimlapi", "deepseek/deepseek-v4-pro")

    assert creds["base_url"] == "https://api.aimlapi.com/v1"


# ---------------------------------------------------------------------------
# Attribution headers
# ---------------------------------------------------------------------------


def test_partner_id_matches_the_gateway_pattern() -> None:
    """A malformed partner id is dropped server-side without an error."""
    partner_id = AIMLAPI_ATTRIBUTION_HEADERS["X-AIMLAPI-Partner-ID"]

    assert _PARTNER_ID_PATTERN.match(partner_id)


def test_referer_and_title_identify_this_project() -> None:
    """HTTP-Referer / X-Title name the calling app, not the gateway."""
    assert AIMLAPI_ATTRIBUTION_HEADERS["HTTP-Referer"] == (
        "https://github.com/HKUDS/Vibe-Trading"
    )
    assert AIMLAPI_ATTRIBUTION_HEADERS["X-Title"] == "Vibe-Trading"
    assert AIMLAPI_ATTRIBUTION_HEADERS["X-AIMLAPI-Source"] == "agent/vibe-trading"


def test_headers_reach_the_client_on_the_default_endpoint() -> None:
    captured = _build_and_capture(dict(_BASE_ENV))
    headers = captured["default_headers"]

    assert headers["X-AIMLAPI-Partner-ID"] == (
        AIMLAPI_ATTRIBUTION_HEADERS["X-AIMLAPI-Partner-ID"]
    )
    assert headers["X-AIMLAPI-Source"] == "agent/vibe-trading"
    assert headers["HTTP-Referer"] == "https://github.com/HKUDS/Vibe-Trading"
    assert headers["X-Title"] == "Vibe-Trading"


def test_shared_constant_is_never_mutated() -> None:
    """Each build gets its own dict; the module constant stays pristine."""
    before = dict(AIMLAPI_ATTRIBUTION_HEADERS)

    captured = _build_and_capture(dict(_BASE_ENV))
    captured["default_headers"]["X-Title"] = "mutated"
    captured["default_headers"]["X-Injected"] = "mutated"

    assert dict(AIMLAPI_ATTRIBUTION_HEADERS) == before
    assert _build_and_capture(dict(_BASE_ENV))["default_headers"]["X-Title"] == (
        "Vibe-Trading"
    )


def test_headers_do_not_ride_to_another_provider() -> None:
    """Attribution belongs to one gateway; OpenRouter must not carry it."""
    captured = _build_and_capture(
        {
            "LANGCHAIN_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "sk-or-test",
            "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
            "LANGCHAIN_MODEL_NAME": "deepseek/deepseek-v4-pro",
        }
    )

    assert "default_headers" not in captured


def test_lookalike_hosts_get_no_attribution() -> None:
    """The check is the resolved host, not a substring of the base URL.

    ``api.aimlapi.com.evil.io`` contains the real host as a prefix and
    ``notaimlapi.com`` contains the vendor name; neither is the vendor, and a
    partner header sent to either leaks an identifier to a third party.
    """
    for base_url in (
        "https://api.aimlapi.com.evil.io/v1",
        "https://notaimlapi.com/v1",
        "https://aimlapi.com.evil.io/v1",
        "https://proxy.internal/aimlapi/v1",
    ):
        env = dict(_BASE_ENV, AIMLAPI_BASE_URL=base_url)
        captured = _build_and_capture(env)

        assert "default_headers" not in captured, base_url


def test_explicit_vendor_host_still_gets_attribution() -> None:
    """A pinned but legitimate endpoint keeps its attribution."""
    for base_url in (
        "https://api.aimlapi.com/v1",
        "https://API.AIMLAPI.COM/v1",
        "https://aimlapi.com/v1",
    ):
        env = dict(_BASE_ENV, AIMLAPI_BASE_URL=base_url)
        captured = _build_and_capture(env)

        assert captured["default_headers"]["X-AIMLAPI-Source"] == (
            "agent/vibe-trading"
        ), base_url


def test_attribution_hosts_are_exact_names() -> None:
    """Guard the host allowlist against a wildcard creeping in."""
    assert AIMLAPI_ATTRIBUTION_HOSTS == frozenset({"api.aimlapi.com", "aimlapi.com"})
    assert all("*" not in host for host in AIMLAPI_ATTRIBUTION_HOSTS)


def test_reasoning_effort_is_sent_top_level_not_in_extra_body() -> None:
    """The gateway accepts the OpenAI field; the OpenRouter relay is not used."""
    env = dict(_BASE_ENV, LANGCHAIN_REASONING_EFFORT="low")
    captured = _build_and_capture(env)

    assert captured["reasoning_effort"] == "low"
    assert captured["extra_body"] is None
