"""Editable, credential-free settings for the portfolio dashboard."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root
from src.portfolio.compatibility import profile_compatibility
from src.trading.connections import (
    ConnectionStore,
    is_portfolio_connection_profile,
)
from src.trading.profiles import list_profiles, profile_by_id
from src.trading.types import TradingProfile

CONFIG_FILENAME = "portfolio.json"
_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class PortfolioSource:
    """One enabled or disabled local connection selected for aggregation."""

    connection_id: str
    label: str
    enabled: bool = True
    order: int = 0
    include_cash: bool = True

    @property
    def id(self) -> str:
        """Return the source identity used by snapshots and refresh progress.

        Returns:
            The underlying local connection id.
        """
        return self.connection_id

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy of this source.

        Returns:
            A plain dict with the same fields as the dataclass.
        """
        return asdict(self)


@dataclass(frozen=True)
class PortfolioSettings:
    """Portfolio display preferences and selected read-only sources."""

    display_currency: str = "USD"
    sources: tuple[PortfolioSource, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy of these settings.

        Returns:
            A dict with ``display_currency`` and a list of source dicts.
        """
        return {
            "display_currency": self.display_currency,
            "sources": [source.to_dict() for source in self.sources],
        }


def eligible_profiles() -> list[TradingProfile]:
    """Return profiles that are structurally safe for portfolio reads.

    Eligibility is decided by
    :func:`src.trading.connections.is_portfolio_connection_profile` so the
    settings gate and the connection registry can never drift apart: a profile
    qualifies only when it is read-only *and* declares both ``account.read``
    and ``positions.read``. A profile that merely advertises remote tool
    discovery (``mcp.read.discovery``) cannot serve either read, so selecting
    it would produce a source that always fails to refresh.

    Returns:
        Eligible profiles sorted by connector, environment and label.
    """
    return sorted(
        (profile for profile in list_profiles() if is_portfolio_connection_profile(profile)),
        key=lambda profile: (profile.connector, profile.environment, profile.label),
    )


def source_catalog(
    settings: PortfolioSettings,
    connection_store: ConnectionStore | None = None,
) -> list[dict[str, Any]]:
    """Describe configured local connections without exposing secret values.

    Args:
        settings: The currently persisted portfolio settings.
        connection_store: Local connection registry; a default store is used
            when omitted.

    Returns:
        One row per registered local connection, each carrying the public
        connection fields plus ``selected`` and ``source_id``.
    """
    store = connection_store or ConnectionStore()
    selected = {source.connection_id: source for source in settings.sources}
    rows = []
    for connection in store.public_list():
        source = selected.get(connection["id"])
        profile = profile_by_id(connection["profile_id"])
        rows.append(
            {
                **connection,
                "connection_id": connection["id"],
                "selected": source is not None,
                "source_id": source.id if source is not None else None,
                "portfolio_compatibility": profile_compatibility(profile),
            }
        )
    return rows


def parse_settings(
    payload: dict[str, Any],
    connection_store: ConnectionStore | None = None,
) -> PortfolioSettings:
    """Validate untrusted Web settings against the local connection registry.

    Args:
        payload: Raw settings dict from the Web UI, CLI or a settings file.
        connection_store: Local connection registry; a default store is used
            when omitted.

    Returns:
        Validated, order-normalized settings.

    Raises:
        ValueError: If the display currency, the source list, a connection id,
            a label, or a referenced profile's eligibility is invalid.
    """
    store = connection_store or ConnectionStore()
    currency = str(payload.get("display_currency") or "USD").strip().upper()
    if currency not in {"USD", "CNY"}:
        raise ValueError("display_currency must be USD or CNY")

    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be a list")
    if len(raw_sources) > 50:
        raise ValueError("at most 50 portfolio sources are allowed")

    seen_ids: set[str] = set()
    sources: list[PortfolioSource] = []
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            raise ValueError("each portfolio source must be an object")
        connection_id = str(raw.get("connection_id") or raw.get("id") or "").strip().lower()
        if not _SOURCE_ID_RE.fullmatch(connection_id):
            raise ValueError(f"invalid portfolio connection id: {connection_id or '?'}")
        legacy_profile_id = str(raw.get("profile_id") or "").strip().lower()
        if legacy_profile_id:
            legacy_profile = profile_by_id(legacy_profile_id)
            connection = store.ensure(
                connection_id,
                legacy_profile.id,
                str(raw.get("label") or legacy_profile.label),
            )
        else:
            connection = store.get(connection_id)
        profile = profile_by_id(connection.profile_id)
        if profile not in eligible_profiles():
            raise ValueError(f"connection is not eligible for read-only portfolios: {connection_id}")
        if connection_id in seen_ids:
            raise ValueError("portfolio connection ids must be unique")
        label = str(raw.get("label") or connection.label).strip()
        if not label or len(label) > 80 or any(ord(character) < 32 for character in label):
            raise ValueError("portfolio source labels must contain 1 to 80 printable characters")
        seen_ids.add(connection_id)
        sources.append(
            PortfolioSource(
                connection_id=connection_id,
                label=label,
                enabled=bool(raw.get("enabled", True)),
                order=int(raw.get("order", index)),
                include_cash=bool(raw.get("include_cash", True)),
            )
        )
    return PortfolioSettings(
        display_currency=currency,
        sources=tuple(sorted(sources, key=lambda item: (item.order, item.id))),
    )


class PortfolioSettingsStore:
    """Owner-only JSON store containing no broker credentials."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        connection_store: ConnectionStore | None = None,
    ) -> None:
        """Bind the store to a settings file and its connection registry.

        Args:
            path: Settings file path. Defaults to ``portfolio.json`` under the
                runtime root (``~/.vibe-trading``).
            connection_store: Local connection registry. When omitted, one is
                created next to ``path`` so tests stay isolated from the
                user's real registry.
        """
        self.path = path or (get_runtime_root() / CONFIG_FILENAME)
        connection_path = self.path.with_name("connections.json") if path is not None else None
        self.connection_store = connection_store or ConnectionStore(connection_path)

    def load(self) -> PortfolioSettings:
        """Read persisted settings, creating an empty file on first use.

        Returns:
            The validated settings currently on disk.

        Raises:
            ValueError: If the file is unreadable, is not a JSON object, or
                fails validation.
        """
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid portfolio settings: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("invalid portfolio settings: root must be an object")
            settings = parse_settings(payload, self.connection_store)
            if any("profile_id" in source for source in payload.get("sources", [])):
                self.save(settings)
            return settings

        settings = PortfolioSettings()
        self.save(settings)
        return settings

    def save(self, settings: PortfolioSettings | dict[str, Any]) -> PortfolioSettings:
        """Validate and atomically persist settings with owner-only permissions.

        Args:
            settings: Settings object or raw dict to validate and store.

        Returns:
            The validated settings that were written.

        Raises:
            ValueError: If validation fails; nothing is written in that case.
        """
        validated = (
            parse_settings(settings, self.connection_store)
            if isinstance(settings, dict)
            else parse_settings(settings.to_dict(), self.connection_store)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".portfolio-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(validated.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return validated
