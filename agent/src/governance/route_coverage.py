"""Helpers for route-level governance coverage.

These helpers keep entrypoint wiring checks small and explicit: production
builders can wrap a concrete ToolRegistry once, while tests can assert the
resulting route carries the expected governance surface.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.agent.tools import ToolRegistry
from src.governance.decision_recorder import DecisionRecorder
from src.governance.runtime import GovernedToolRegistry, RuntimeContext

_DENIED_SUBPROCESS_SECRET_FRAGMENTS = (
    "OPENAI",
    "ANTHROPIC",
    "LANGCHAIN",
    "DASHSCOPE",
    "MOONSHOT",
    "LLM",
    "BROKER",
    "LIVE",
    "MANDATE",
    "ORDER",
    "ROBINHOOD",
    "IBKR",
    "ALPACA_SECRET",
    "BINANCE_SECRET",
    "FUTU_SECRET",
    "LONGPORT_SECRET",
    "TIGER_SECRET",
)

_RUNNER_FORCED_ENV_KEYS = frozenset({"PYTHONUNBUFFERED", "PYTHONIOENCODING", "PYTHONUTF8"})


class RouteGovernanceCoverage(BaseModel):
    """Result of checking one entrypoint route for governance wrapping."""

    schema_version: str = "1.2.1"
    route_name: str
    uses_governed_registry: bool
    expected_surface: str | None = None
    actual_surface: str | None = None
    documented_equivalent: bool = False
    details: list[str] = Field(default_factory=list)


def build_governed_tool_registry(
    inner: ToolRegistry | GovernedToolRegistry,
    *,
    surface: str,
    mode: str = "observe",
    run_id: str | None = None,
    session_id: str | None = None,
    trial_id: str | None = None,
    protocol_hash: str | None = None,
    policy: Any | None = None,
    decision_recorder: DecisionRecorder | None = None,
) -> GovernedToolRegistry:
    """Wrap a ToolRegistry with governance for a concrete runtime surface."""
    if isinstance(inner, GovernedToolRegistry):
        return inner
    return GovernedToolRegistry(
        inner,
        policy=policy,
        decision_recorder=decision_recorder,
        context=RuntimeContext(
            mode=mode,  # type: ignore[arg-type]
            surface=surface,
            run_id=run_id,
            session_id=session_id,
            trial_id=trial_id,
            protocol_hash=protocol_hash,
        ),
    )


def assert_registry_governed(
    registry: Any,
    *,
    route_name: str,
    expected_surface: str | None = None,
    allow_documented_equivalent: bool = False,
    documented_equivalent: bool = False,
) -> RouteGovernanceCoverage:
    """Assert that an entrypoint constructed a governed registry or equivalent."""
    uses_governed = isinstance(registry, GovernedToolRegistry)
    actual_surface = getattr(getattr(registry, "context", None), "surface", None)
    details: list[str] = []

    if not uses_governed and not (allow_documented_equivalent and documented_equivalent):
        raise AssertionError(f"{route_name} does not use GovernedToolRegistry")
    if expected_surface is not None and uses_governed and actual_surface != expected_surface:
        raise AssertionError(
            f"{route_name} uses governance surface {actual_surface!r}, expected {expected_surface!r}"
        )
    if uses_governed:
        details.append("registry is GovernedToolRegistry")
    if documented_equivalent:
        details.append("documented equivalent governance wrapper accepted")

    return RouteGovernanceCoverage(
        route_name=route_name,
        uses_governed_registry=uses_governed,
        expected_surface=expected_surface,
        actual_surface=actual_surface,
        documented_equivalent=bool(documented_equivalent),
        details=details,
    )


def assert_backtest_env_uses_allowlist(env: dict[str, str]) -> dict[str, Any]:
    """Return a compact audit of generated-subprocess environment safety."""
    from src.core.runner import _is_runtime_env_key_allowed

    disallowed_keys = sorted(
        key
        for key in env
        if key not in _RUNNER_FORCED_ENV_KEYS and not _is_runtime_env_key_allowed(key)
    )
    secret_keys_present = sorted(key for key in env if _is_denied_subprocess_secret_key(key))
    if secret_keys_present:
        raise AssertionError(f"subprocess env contains denied secret keys: {secret_keys_present}")
    return {
        "allowlist_enforced": not disallowed_keys,
        "disallowed_keys": disallowed_keys,
        "secret_keys_present": secret_keys_present,
    }


def _is_denied_subprocess_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(fragment in upper for fragment in _DENIED_SUBPROCESS_SECRET_FRAGMENTS)
