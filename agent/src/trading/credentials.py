"""OS-backed secret storage for local trading connection instances."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

SERVICE_NAME = "Vibe-Trading"
_INSTALL_HINT = (
    "OS credential vault support is not installed. Install the optional extra: "
    'pip install "vibe-trading-ai[keyring]" (or pip install keyring).'
)


class CredentialBackend(Protocol):
    """Minimal subset of the ``keyring`` API used by :class:`CredentialStore`."""

    def get_password(self, service_name: str, username: str) -> str | None: ...
    def set_password(self, service_name: str, username: str, password: str) -> None: ...
    def delete_password(self, service_name: str, username: str) -> None: ...


class CredentialStore:
    """Store secrets in Keychain/Credential Manager/Secret Service via keyring.

    The ``keyring`` package is an optional extra: it is imported the first time
    a secret is actually read or written, so importing this module — and every
    module that only needs connection metadata — stays dependency-free.

    Args:
        backend: Optional backend implementing the ``keyring`` password API.
            Tests pass an in-memory double; production leaves it unset so the
            real OS vault is imported lazily.
    """

    def __init__(self, backend: CredentialBackend | None = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> CredentialBackend:
        """Return the credential backend, importing ``keyring`` on first use.

        Returns:
            The injected backend, otherwise the imported ``keyring`` module.

        Raises:
            RuntimeError: If ``keyring`` is not installed. The message names
                the optional extra that provides it.
        """
        if self._backend is None:
            try:
                import keyring
            except ModuleNotFoundError as exc:  # optional extra
                raise RuntimeError(_INSTALL_HINT) from exc

            self._backend = keyring
        return self._backend

    @staticmethod
    def reference(connection_id: str) -> str:
        """Return the opaque vault reference stored beside a connection.

        Args:
            connection_id: Identifier of the local connection instance.

        Returns:
            A ``keyring://`` reference that names where the secret lives; it
            never contains the secret itself.
        """
        return f"keyring://vibe-trading/{connection_id}"

    @staticmethod
    def _username(connection_id: str, field: str) -> str:
        return f"connection:{connection_id}:{field}"

    def save(self, connection_id: str, values: Mapping[str, str]) -> None:
        """Persist non-empty values; blank fields leave an existing secret unchanged.

        Args:
            connection_id: Identifier of the local connection instance.
            values: Mapping of credential field name to secret value. Empty or
                whitespace-only values are skipped so a partial form submission
                cannot erase a stored secret.

        Raises:
            RuntimeError: If the ``keyring`` extra is not installed.
        """
        for field, raw_value in values.items():
            value = str(raw_value or "").strip()
            if value:
                self.backend.set_password(
                    SERVICE_NAME,
                    self._username(connection_id, field),
                    value,
                )

    def load(self, connection_id: str, fields: Iterable[str]) -> dict[str, str]:
        """Read the stored secrets for a connection.

        Args:
            connection_id: Identifier of the local connection instance.
            fields: Credential field names declared by the connector manifest.

        Returns:
            Mapping of field name to secret value, omitting fields that have
            no stored value.

        Raises:
            RuntimeError: If the ``keyring`` extra is not installed.
        """
        values: dict[str, str] = {}
        for field in fields:
            value = self.backend.get_password(
                SERVICE_NAME,
                self._username(connection_id, field),
            )
            if value:
                values[field] = value
        return values

    def status(self, connection_id: str, fields: Iterable[str]) -> dict[str, bool]:
        """Report which credential fields have a stored value.

        Args:
            connection_id: Identifier of the local connection instance.
            fields: Credential field names declared by the connector manifest.

        Returns:
            Mapping of field name to a boolean presence flag. A field whose
            backend lookup fails is reported as missing rather than raising, so
            a locked vault cannot break the connection listing.

        Raises:
            RuntimeError: If the ``keyring`` extra is not installed.
        """
        field_names = tuple(fields)
        try:
            backend = self.backend
        except RuntimeError:
            return {field: False for field in field_names}
        result = {}
        for field in field_names:
            try:
                result[field] = bool(
                    backend.get_password(
                        SERVICE_NAME,
                        self._username(connection_id, field),
                    )
                )
            except Exception:
                result[field] = False
        return result

    def delete(self, connection_id: str, fields: Iterable[str]) -> None:
        """Remove the stored secrets for a connection.

        Args:
            connection_id: Identifier of the local connection instance.
            fields: Credential field names declared by the connector manifest.

        Raises:
            RuntimeError: If the ``keyring`` extra is not installed.
            Exception: Whatever the backend raises for a failure other than a
                missing entry, which is treated as already deleted.
        """
        backend = self.backend
        for field in fields:
            try:
                backend.delete_password(
                    SERVICE_NAME,
                    self._username(connection_id, field),
                )
            except Exception as exc:  # keyring backends differ on missing entries
                if "not found" not in str(exc).lower():
                    raise
