"""The CLI settings view reads provider credentials from the catalog, not a second copy."""

import pytest

from cli.commands.providers import _provider_env
from src.providers.registry import _catalog, get_provider_capabilities


@pytest.mark.parametrize(
    "label",
    sorted(
        name
        for row in _catalog()
        for name in (row["name"], *row.get("aliases", ()), *row.get("runtime_variants", {}))
    ),
)
def test_every_catalog_name_shows_the_env_names_the_runtime_reads(label: str) -> None:
    key_env, base_env, _ = _provider_env(label)
    caps = get_provider_capabilities(label)
    assert (key_env, base_env) == (caps.api_key_env, caps.base_url_env)


def test_providers_that_were_missing_from_the_old_table_are_known() -> None:
    assert _provider_env("anthropic") == ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", True)
    assert _provider_env("Nvidia_NIM")[0] == "NVIDIA_API_KEY"
    assert _provider_env("copilot")[2] is False
    assert _provider_env("claude-cli")[2] is False


def test_unknown_provider_is_reported_as_unknown() -> None:
    assert _provider_env("unknown-xyz") == (None, None, True)
    assert _provider_env("custom") == (None, None, True)
