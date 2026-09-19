"""Broker account listing and selection for account-scoped connections.

One OAuth grant can reach several broker accounts (Robinhood). Portfolio reads
and live trading both name the account explicitly, and both choose it from the
broker's own account list, never from a default or the first row.
"""

from __future__ import annotations

from typing import Any, Callable

from src.trading.connections import TradingConnection, requires_account_selection
from src.trading.profiles import profile_by_id


class AccountListUnavailable(RuntimeError):
    """The broker's account list could not be read or mapped."""


def connection_accounts(
    connection: TradingConnection,
    *,
    get_accounts: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read the accounts a connection's login can reach.

    Args:
        connection: A connection whose profile requires an account.
        get_accounts: Account reader; defaults to
            ``src.trading.service.get_accounts``.

    Returns:
        Picker rows (``account_ref``, ``label``, ``is_default``,
        ``agentic_allowed``, ``deactivated``).

    Raises:
        ValueError: If the connection's profile takes no account.
        AccountListUnavailable: If the read failed, needs authorization, or
            its reply could not be mapped.
    """
    profile = profile_by_id(connection.profile_id)
    if not requires_account_selection(profile):
        raise ValueError(f"connection profile does not take an account: {profile.id}")
    if get_accounts is None:
        from src.trading.service import get_accounts
    envelope = get_accounts(profile.id, interactive_oauth=False)
    if str(envelope.get("status") or "").lower() not in {"ok", "success"}:
        raise AccountListUnavailable(str(envelope.get("error") or f"{profile.connector} account list read failed"))
    if envelope.get("mapping_error"):
        raise AccountListUnavailable(f"account list could not be mapped: {envelope['mapping_error']}")
    accounts = envelope.get("accounts")
    if not isinstance(accounts, list):
        raise AccountListUnavailable(f"{profile.connector} account list read returned no accounts list")
    return accounts


def choose_account(
    choices: list[dict[str, Any]],
    account_ref: str,
    *,
    require_agentic: bool = False,
) -> dict[str, Any]:
    """Return the chosen account after checking it is usable.

    Args:
        choices: Picker rows from the broker's account list.
        account_ref: The account the user picked.
        require_agentic: Also require the broker to allow agentic trading on
            the account (a live mandate needs this; a read does not).

    Returns:
        The matching picker row.

    Raises:
        ValueError: If the account is not in the list, is deactivated, or does
            not allow agentic trading when that is required.
    """
    match = next((row for row in choices if row.get("account_ref") == account_ref), None)
    if match is None:
        raise ValueError("that account is not one of the accounts this login can reach")
    if match.get("deactivated"):
        raise ValueError("that account is deactivated")
    if require_agentic and not match.get("agentic_allowed"):
        raise ValueError("the broker does not allow agentic trading on that account")
    return match
