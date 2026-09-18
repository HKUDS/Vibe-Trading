"""Local-only API for read-only connection instances and plugin discovery."""

from __future__ import annotations

from dataclasses import replace

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.api.security import require_auth, require_settings_write_auth
from src.portfolio.compatibility import profile_compatibility
from src.portfolio.config import PortfolioSettingsStore
from src.trading.accounts import AccountListUnavailable, choose_account, connection_accounts
from src.trading.connections import (
    ConnectionStore,
    credential_fields,
    readonly_profile_catalog,
)
from src.trading.local_plugins import plugin_root
from src.trading.profiles import profile_by_id
from src.trading.service import check_connection


class ConnectionRequest(BaseModel):
    """Payload creating or renaming a read-only connection instance."""

    id: str = Field(min_length=1, max_length=80)
    profile_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)


class AccountSelectionRequest(BaseModel):
    """Payload selecting the broker account a connection reads; empty clears it."""

    account_ref: str = Field("", max_length=128)


class CredentialRequest(BaseModel):
    """Payload carrying credential values for one connection instance."""

    values: dict[str, str] = Field(default_factory=dict)


def register_connection_routes(app: FastAPI) -> None:
    """Register the auth-gated read-only connection endpoints.

    Every route is read-only with respect to the broker: the API exposes
    connection metadata, credential presence, and a connectivity check, and
    never reaches an order path.

    Args:
        app: FastAPI application the routes are attached to.
    """

    def store() -> ConnectionStore:
        return ConnectionStore()

    @app.get("/api/connections", dependencies=[Depends(require_auth)])
    def list_connections():
        """List connection instances, eligible profiles, and the plugin root."""
        connections = [
            {
                **row,
                "portfolio_compatibility": profile_compatibility(profile_by_id(row["profile_id"])),
            }
            for row in store().public_list()
        ]
        profiles = []
        for row in readonly_profile_catalog():
            if row.get("invalid_plugin"):
                profiles.append(row)
            else:
                profiles.append(
                    {
                        **row,
                        "portfolio_compatibility": profile_compatibility(profile_by_id(row["id"])),
                    }
                )
        return {
            "status": "ok",
            "connections": connections,
            "profiles": profiles,
            "plugin_directory": str(plugin_root()),
        }

    @app.post(
        "/api/connections",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def create_connection(payload: ConnectionRequest):
        """Create one connection instance from an eligible read-only profile."""
        try:
            instance = store().create(payload.id, payload.profile_id, payload.label)
            return {"status": "ok", "connection": instance.to_dict()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put(
        "/api/connections/{connection_id}",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def update_connection(connection_id: str, payload: ConnectionRequest):
        """Rename a connection instance; its id and profile are immutable."""
        if payload.id.strip().lower() != connection_id.strip().lower():
            raise HTTPException(status_code=400, detail="connection id cannot be changed")
        try:
            instance = store()
            current = instance.get(connection_id)
            if payload.profile_id.strip().lower() != current.profile_id:
                raise ValueError("connection profile cannot be changed")
            # replace() keeps every field the rename does not name, including
            # the selected account.
            updated = instance.save(replace(current, label=payload.label))
            return {"status": "ok", "connection": updated.to_dict()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get(
        "/api/connections/{connection_id}/accounts",
        dependencies=[Depends(require_auth)],
    )
    def list_connection_accounts(connection_id: str):
        """List the broker accounts a connection's login can reach."""
        try:
            connection = store().get(connection_id)
            accounts = connection_accounts(connection)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AccountListUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "status": "ok",
            "connection_id": connection.id,
            "account_ref": connection.account_ref,
            "accounts": accounts,
        }

    @app.put(
        "/api/connections/{connection_id}/account",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def select_connection_account(connection_id: str, payload: AccountSelectionRequest):
        """Scope a connection's reads to one account from the broker's own list."""
        account_ref = payload.account_ref.strip()
        try:
            instance = store()
            connection = instance.get(connection_id)
            if account_ref:
                choose_account(connection_accounts(connection), account_ref)
            updated = instance.select_account(connection.id, account_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AccountListUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok", "connection": updated.to_dict()}

    @app.post(
        "/api/connections/{connection_id}/credentials",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def save_connection_credentials(connection_id: str, payload: CredentialRequest):
        """Store credentials in the OS vault and return presence flags only."""
        try:
            instance = store()
            connection = instance.get(connection_id)
            allowed = set(credential_fields(connection.profile_id))
            if not set(payload.values).issubset(allowed):
                raise ValueError("credential payload contains fields not declared by the connector")
            instance.credentials.save(connection.id, payload.values)
            return {
                "status": "ok",
                "credential_status": instance.credentials.status(
                    connection.id,
                    allowed,
                ),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(
        "/api/connections/{connection_id}/check",
        dependencies=[Depends(require_auth)],
    )
    def check_local_connection(connection_id: str):
        """Run the connector's read-only status check for one connection."""
        try:
            connection = store().get(connection_id)
            report = check_connection(
                connection.profile_id,
                connection_id=connection.id,
            )
            return {
                "status": "ok",
                "connection_id": connection.id,
                "report": report,
            }
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.delete(
        "/api/connections/{connection_id}",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def delete_connection(connection_id: str):
        """Delete a connection and its secrets once no portfolio source uses it."""
        try:
            selected = {source.connection_id for source in PortfolioSettingsStore().load().sources}
            if connection_id.strip().lower() in selected:
                raise ValueError("remove this connection from the portfolio before deleting it")
            store().delete(connection_id)
            return {"status": "ok", "deleted": connection_id}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
