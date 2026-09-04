"""Credential-free registry of user-owned trading connection instances."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root
from src.trading.credentials import CredentialStore
from src.trading.local_plugins import discover_plugins
from src.trading.onboarding import onboarding_dict, onboarding_for_profile
from src.trading.profiles import list_profiles, profile_by_id
from src.trading.types import TradingProfile

CONFIG_FILENAME = "connections.json"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
REQUIRED_READ_CAPABILITIES = frozenset({"account.read", "positions.read"})


def is_portfolio_connection_profile(profile: TradingProfile) -> bool:
    """Report whether a profile can back a read-only portfolio connection.

    A profile qualifies only when it is read-only and declares both
    ``account.read`` and ``positions.read``. A profile that advertises tool
    discovery alone cannot serve a holdings read, so it is not eligible even
    though it is read-only.

    Args:
        profile: Built-in or operator-installed trading profile.

    Returns:
        True when the profile can serve account and position reads.
    """
    return bool(profile.readonly) and REQUIRED_READ_CAPABILITIES.issubset(profile.capabilities)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credential_reference(profile_id: str, connection_id: str) -> str:
    """Return the credential locator implied by a profile's transport.

    Args:
        profile_id: Profile backing the connection instance.
        connection_id: Identifier of the connection instance.

    Returns:
        An opaque reference naming where the credentials live. SDK profiles
        and local plugins use the OS vault; OAuth and local-session transports
        retain their own stores.

    Raises:
        ValueError: If the profile id is unknown.
    """
    profile = profile_by_id(profile_id)
    if profile.transport in {"broker_sdk", "local_plugin"}:
        return CredentialStore.reference(connection_id)
    if profile.transport == "remote_mcp":
        return f"oauth-cache://{profile.connector}"
    if profile.transport == "local_tws":
        return f"local-session://{profile.connector}"
    return f"connector-config://{profile.connector}"


@dataclass(frozen=True)
class TradingConnection:
    """One user-configured connection instance.

    Attributes:
        id: Lowercase identifier, unique within the registry.
        profile_id: Trading profile the connection reads through.
        label: Human-readable name shown in the UI.
        credential_ref: Opaque locator for the credentials; never a secret.
        created_at: ISO-8601 UTC creation timestamp.
    """

    id: str
    profile_id: str
    label: str
    credential_ref: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        """Return the connection as a JSON-serializable mapping.

        Returns:
            A mapping of the metadata fields; it carries no secret values.
        """
        return asdict(self)


class ConnectionStore:
    """Owner-only metadata store; secret values live in the OS credential vault.

    Args:
        path: Registry file path. Defaults to ``connections.json`` under the
            user runtime root.
        credential_store: Credential vault used for local plugin secrets.
            Defaults to the OS-backed store.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.path = path or (get_runtime_root() / CONFIG_FILENAME)
        self.credentials = credential_store or CredentialStore()

    def list(self) -> list[TradingConnection]:
        """Read every stored connection.

        Returns:
            The validated connections, or an empty list when no registry file
            exists yet.

        Raises:
            ValueError: If the registry file is unreadable, is not valid JSON,
                or holds a row that fails validation.
        """
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid local connection registry: {exc}") from exc
        rows = payload.get("connections", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise ValueError("invalid local connection registry: connections must be a list")
        return [self._parse(row) for row in rows]

    def get(self, connection_id: str) -> TradingConnection:
        """Look up one stored connection by id.

        Args:
            connection_id: Identifier to resolve; case and surrounding
                whitespace are normalized before matching.

        Returns:
            The matching connection.

        Raises:
            ValueError: If no stored connection has that id.
        """
        target = str(connection_id or "").strip().lower()
        for connection in self.list():
            if connection.id == target:
                return connection
        raise ValueError(f"unknown local connection: {target or '?'}")

    def save(self, connection: TradingConnection) -> TradingConnection:
        """Validate and persist a connection, replacing any row with its id.

        Args:
            connection: Connection to store.

        Returns:
            The validated connection as it was written.

        Raises:
            ValueError: If the connection fails validation, for example an
                invalid id, an ineligible profile, or an unusable label.
        """
        validated = self._parse(connection.to_dict())
        rows = [row for row in self.list() if row.id != validated.id]
        rows.append(validated)
        self._write(sorted(rows, key=lambda row: (row.created_at, row.id)))
        return validated

    def create(self, connection_id: str, profile_id: str, label: str) -> TradingConnection:
        """Create a new connection instance.

        Args:
            connection_id: Identifier for the new connection.
            profile_id: Read-only profile the connection reads through.
            label: Human-readable name.

        Returns:
            The stored connection.

        Raises:
            ValueError: If the id is already used, or the connection fails
                validation.
        """
        normalized_id = str(connection_id or "").strip().lower()
        if any(row.id == normalized_id for row in self.list()):
            raise ValueError(f"local connection already exists: {normalized_id}")
        return self.save(
            TradingConnection(
                id=normalized_id,
                profile_id=profile_id,
                label=label,
                credential_ref=_credential_reference(profile_id, normalized_id),
                created_at=_now(),
            )
        )

    def ensure(self, connection_id: str, profile_id: str, label: str) -> TradingConnection:
        """Return an existing connection, creating it when absent.

        Args:
            connection_id: Identifier to resolve or create.
            profile_id: Read-only profile the connection must use.
            label: Human-readable name used only when creating.

        Returns:
            The existing or newly created connection.

        Raises:
            ValueError: If an existing connection with that id uses a
                different profile, or creation fails validation.
        """
        try:
            existing = self.get(connection_id)
        except ValueError:
            return self.create(connection_id, profile_id, label)
        if existing.profile_id != str(profile_id or "").strip().lower():
            raise ValueError(f"local connection {existing.id} already uses profile {existing.profile_id}")
        return existing

    def delete(self, connection_id: str) -> None:
        """Delete a connection and any secrets stored for it.

        Args:
            connection_id: Identifier of the connection to remove.

        Raises:
            ValueError: If no stored connection has that id.
        """
        connection = self.get(connection_id)
        fields = credential_fields(connection.profile_id)
        self.credentials.delete(connection.id, fields)
        self._write([row for row in self.list() if row.id != connection.id])

    def public_list(self) -> list[dict[str, Any]]:
        """Return UI-facing rows for every stored connection.

        Returns:
            One mapping per connection, enriched with its profile metadata and
            a per-field boolean credential status. Secret values are never
            included.

        Raises:
            ValueError: If the registry holds a row that fails validation.
        """
        result = []
        for connection in self.list():
            profile = profile_by_id(connection.profile_id)
            fields = credential_fields(profile.id)
            required_fields = tuple(
                str(field["name"]) for field in credential_field_catalog(profile.id) if field.get("required", True)
            )
            field_status = self.credentials.status(connection.id, fields) if fields else {}
            result.append(
                {
                    **connection.to_dict(),
                    "connector": profile.connector,
                    "environment": profile.environment,
                    "transport": profile.transport,
                    "readonly": profile.readonly,
                    "capabilities": list(profile.capabilities),
                    "supports_reconnect": profile.transport == "remote_mcp",
                    "credential_fields": credential_field_catalog(profile.id),
                    "credential_status": field_status,
                    "credentials_configured": bool(required_fields)
                    and all(field_status.get(field, False) for field in required_fields),
                    "onboarding": onboarding_dict(profile),
                }
            )
        return result

    @staticmethod
    def _parse(raw: object) -> TradingConnection:
        """Validate one registry row.

        Args:
            raw: Decoded registry row.

        Returns:
            The validated connection.

        Raises:
            ValueError: If the row is not an object, carries an invalid id or
                label, names an unknown or ineligible profile, or claims a
                credential reference that does not match its transport.
        """
        if not isinstance(raw, dict):
            raise ValueError("each local connection must be an object")
        connection_id = str(raw.get("id") or "").strip().lower()
        if not _ID_RE.fullmatch(connection_id):
            raise ValueError(f"invalid local connection id: {connection_id or '?'}")
        profile_id = str(raw.get("profile_id") or "").strip().lower()
        profile = profile_by_id(profile_id)
        if not is_portfolio_connection_profile(profile):
            raise ValueError(f"connection profile is not eligible for read-only portfolios: {profile_id}")
        label = str(raw.get("label") or profile.label).strip()
        if not label or len(label) > 80 or any(ord(character) < 32 for character in label):
            raise ValueError("connection label must contain 1 to 80 printable characters")
        expected_ref = _credential_reference(profile.id, connection_id)
        credential_ref = str(raw.get("credential_ref") or expected_ref)
        legacy_sdk_ref = f"connector-config://{profile.connector}"
        if profile.transport == "broker_sdk" and credential_ref == legacy_sdk_ref:
            credential_ref = expected_ref
        if credential_ref != expected_ref:
            raise ValueError("connection credential_ref does not match its local transport")
        return TradingConnection(
            id=connection_id,
            profile_id=profile.id,
            label=label,
            credential_ref=credential_ref,
            created_at=str(raw.get("created_at") or _now()),
        )

    def _write(self, connections: list[TradingConnection]) -> None:
        """Atomically rewrite the registry file with owner-only permissions.

        Args:
            connections: Full set of connections to persist.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".connections-",
            suffix=".json",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "connections": [row.to_dict() for row in connections],
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def credential_field_catalog(profile_id: str) -> list[dict[str, Any]]:
    """Return the credential fields a profile declares.

    Args:
        profile_id: Profile to inspect.

    Returns:
        Field metadata declared by a local plugin or built-in SDK onboarding
        contract. OAuth and local-session transports return an empty list.

    Raises:
        ValueError: If the profile id is unknown, or names a local plugin that
            is not installed.
    """
    profile = profile_by_id(profile_id)
    return [field.to_dict() for field in onboarding_for_profile(profile).credential_fields]


def credential_fields(profile_id: str) -> tuple[str, ...]:
    """Return the credential field names a profile declares.

    Args:
        profile_id: Profile to inspect.

    Returns:
        The declared field names, empty when the transport stores its own
        credentials.

    Raises:
        ValueError: If the profile id is unknown, or names a local plugin that
            is not installed.
    """
    return tuple(str(row["name"]) for row in credential_field_catalog(profile_id))


def readonly_profile_catalog() -> list[dict[str, Any]]:
    """Return the profiles that can back a read-only portfolio connection.

    Returns:
        One row per eligible profile, sorted by connector, environment and
        label, followed by one ``invalid_plugin`` diagnostic row per installed
        plugin directory whose manifest failed validation.
    """
    plugins, errors = discover_plugins()
    plugin_ids = {plugin.profile.id for plugin in plugins}
    rows = []
    for profile in list_profiles():
        if not is_portfolio_connection_profile(profile):
            continue
        rows.append(
            {
                "id": profile.id,
                "connector": profile.connector,
                "label": profile.label,
                "environment": profile.environment,
                "transport": profile.transport,
                "capabilities": list(profile.capabilities),
                "readonly": profile.readonly,
                "notes": profile.notes,
                "local_plugin": profile.id in plugin_ids,
                "credential_fields": credential_field_catalog(profile.id),
                "supports_reconnect": profile.transport == "remote_mcp",
                "onboarding": onboarding_dict(profile),
            }
        )
    return sorted(rows, key=lambda row: (row["connector"], row["environment"], row["label"])) + [
        {"invalid_plugin": True, **error} for error in errors
    ]
