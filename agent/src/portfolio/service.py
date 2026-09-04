"""Deterministic, read-only aggregation across configured trading profiles."""

from __future__ import annotations

import csv
import io
import json
import socket
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from src.portfolio.config import (
    PortfolioSettingsStore,
    PortfolioSource,
    source_catalog,
)
from src.portfolio.compatibility import (
    adapt_and_validate_payloads,
    ensure_supported_currencies,
    profile_compatibility,
)
from src.portfolio.normalization import (
    STABLECOINS,
    account_cash_usd,
    account_total_usd,
    auth_metadata,
    normalize_position,
    value_position,
)
from src.portfolio.store import PortfolioStore
from src.trading.profiles import profile_by_id
from src.trading.types import TradingProfile

# ``portfolio_risk_xray`` caps a basket at 50 symbols, and its loaders route on
# the market suffix: ``AAPL`` alone is read as an A-share code, ``AAPL.US`` is
# not (see ``src.market_data._SOURCE_PATTERNS``).
_RISK_XRAY_MAX_SYMBOLS = 50
PORTFOLIO_VALUATION_VERSION = 2
_LOADER_MARKET_SUFFIXES = frozenset({"US", "HK", "SZ", "SH", "BJ", "KS", "KQ", "NS", "BO", "TO", "V"})
_NON_EQUITY_ASSET_TYPES = frozenset({"crypto", "stablecoin", "cash"})


_AUTH_REQUIRED_MARKERS = (
    "not_authorized",
    "not authorized",
    "authorization required",
    "oauth authorization required",
    "invalid_grant",
    "token expired",
    "oauth token missing",
    "connector authorize",
)


def _authorization_required(payload: dict[str, Any]) -> bool:
    """Return whether a connector failure explicitly asks for OAuth renewal."""
    status = str(payload.get("status") or "").strip().lower()
    if status in {"not_authorized", "unauthorized"}:
        return True
    message = " ".join(
        str(payload.get(key) or "")
        for key in ("error", "error_code", "error_type")
    ).lower()
    return any(marker in message for marker in _AUTH_REQUIRED_MARKERS)


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        result = Decimal(str(value))
        return result if result.is_finite() else default
    except (InvalidOperation, ValueError, TypeError):
        return default


def _number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.00000001")))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_callback_port_available(port: int) -> None:
    """Fail cleanly before an embedded OAuth callback server tries to bind."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError(
            f"OAuth callback port {port} is already in use; close the old authorization flow and retry"
        ) from exc


def _contains_system_exit(error: BaseException) -> bool:
    """Return whether an exception or nested exception group contains SystemExit."""
    if isinstance(error, SystemExit):
        return True
    nested = getattr(error, "exceptions", ())
    return any(_contains_system_exit(item) for item in nested if isinstance(item, BaseException))


def _quote_price(payload: dict[str, Any]) -> Decimal | None:
    quote = payload.get("quote") or {}
    for key in ("last", "close"):
        price = _decimal(quote.get(key))
        if price > 0:
            return price
    bid, ask = _decimal(quote.get("bid")), _decimal(quote.get("ask"))
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return bid if bid > 0 else ask if ask > 0 else None


class PortfolioService:
    """Aggregate every enabled read-only source into one immutable snapshot.

    The service reads; it never places or cancels an order. A source that
    cannot be read contributes nothing at all — see :meth:`refresh`.
    """

    def __init__(
        self,
        store: PortfolioStore | None = None,
        *,
        settings_store: PortfolioSettingsStore | None = None,
        get_account: Callable[..., dict[str, Any]] | None = None,
        get_positions: Callable[..., dict[str, Any]] | None = None,
        get_quote: Callable[..., dict[str, Any]] | None = None,
        get_longbridge_quotes: Callable[..., dict[str, Any]] | None = None,
        fx_fetcher: Callable[[], tuple[Decimal, Decimal, str]] | None = None,
        progress_callback: Callable[[str, str, str | None], None] | None = None,
    ) -> None:
        """Wire the service to its stores and connector read functions.

        Args:
            store: Snapshot/FX database. Defaults to the runtime-root store.
            settings_store: Editable portfolio settings. Defaults to the
                runtime-root store.
            get_account: Account reader. Defaults to
                ``src.trading.service.get_account``.
            get_positions: Positions reader. Defaults to
                ``src.trading.service.get_positions``.
            get_quote: Single-symbol quote reader. Defaults to
                ``src.trading.service.get_quote``.
            get_longbridge_quotes: Optional batch quote reader used only for
                Longbridge positions the connector reports without a price.
            fx_fetcher: Returns ``(usd_cny, usd_hkd, fetched_at)``. Defaults to
                the built-in HTTPS fetch.
            progress_callback: Called as ``(source_id, status, error)`` while a
                refresh walks its sources.
        """
        self._use_connection_scoped_reads = get_account is None and get_positions is None
        self._use_connection_scoped_quotes = get_quote is None
        self._use_longbridge_worker = self._use_connection_scoped_reads
        if get_account is None or get_positions is None or get_quote is None:
            from src.trading import service as trading

            get_account = get_account or trading.get_account
            get_positions = get_positions or trading.get_positions
            get_quote = get_quote or trading.get_quote
        self.store = store or PortfolioStore()
        self._get_account = get_account
        self._get_positions = get_positions
        self._get_quote = get_quote
        self._get_longbridge_quotes = get_longbridge_quotes
        self._fx_fetcher = fx_fetcher or self._fetch_fx
        self._progress_callback = progress_callback
        self.settings_store = settings_store or PortfolioSettingsStore()

    def settings(self) -> dict[str, Any]:
        """Return credential-free editable settings.

        Returns:
            The persisted display currency and source selection.
        """
        return self.settings_store.load().to_dict()

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist editable settings.

        Args:
            payload: Untrusted settings from the Web UI or API.

        Returns:
            The validated settings that were written.

        Raises:
            ValueError: If the payload fails validation; nothing is written.
        """
        return self.settings_store.save(payload).to_dict()

    def sources(self) -> list[dict[str, Any]]:
        """Return local read-only connections eligible for this portfolio.

        Returns:
            One catalog row per registered connection, flagged as selected or
            not, and free of secret values.
        """
        return source_catalog(
            self.settings_store.load(),
            self.settings_store.connection_store,
        )

    def _connection_profile(self, source: PortfolioSource):
        """Resolve one configured source to its connection and profile.

        Args:
            source: The configured portfolio source.

        Returns:
            A ``(connection, profile)`` pair.
        """
        connection = self.settings_store.connection_store.get(source.connection_id)
        return connection, profile_by_id(connection.profile_id)

    def refresh(self) -> dict[str, Any]:
        """Read every enabled source once and persist an immutable snapshot.

        A source that fails contributes nothing: no positions, no combined
        holdings, and no value in the totals. Its account row carries the
        error and the timestamp of its last healthy read, and the snapshot is
        marked incomplete. A partial read is an error to be surfaced, never a
        quietly shorter portfolio.

        Returns:
            The snapshot envelope that was stored.

        Raises:
            RuntimeError: If no source is enabled, or if FX rates can neither
                be fetched nor loaded from cache.
        """
        settings = self.settings_store.load()
        sources = [source for source in settings.sources if source.enabled]
        if not sources:
            raise RuntimeError("Add and enable at least one read-only account on the Portfolio page before refreshing")
        usd_cny, usd_hkd, fx_at, fx_stale = self._rates()
        refreshed_at = _now()
        results: dict[str, dict[str, Any]] = {}
        # The Longbridge Python SDK wraps a native runtime whose contexts are
        # not safe to create inside this refresh thread pool on macOS. Keep the
        # manual refresh deterministic and sequential; a failed broker remains
        # isolated and never prevents the other accounts from refreshing.
        for source in sources:
            if self._progress_callback is not None:
                self._progress_callback(source.id, "refreshing", None)
            try:
                results[source.id] = self._collect_source(source)
                if self._progress_callback is not None:
                    self._progress_callback(source.id, "ok", None)
            except Exception as exc:  # read failures are isolated per connector
                try:
                    _, failed_profile = self._connection_profile(source)
                    auth_required = failed_profile.transport == "remote_mcp" and _authorization_required(
                        {"error": str(exc)}
                    )
                except Exception:
                    auth_required = False
                results[source.id] = {
                    "status": "error",
                    "error_code": type(exc).__name__,
                    "error": str(exc)[:300],
                    "failure_kind": "authorization" if auth_required else "transient",
                    "reconnect_required": auth_required,
                }
                if self._progress_callback is not None:
                    self._progress_callback(source.id, "error", str(exc)[:160])

        positions: list[dict[str, Any]] = []
        accounts: list[dict[str, Any]] = []
        for source in sources:
            result = results[source.id]
            connection, profile = self._connection_profile(source)
            broker = profile.connector
            if result["status"] != "ok":
                accounts.append(self._failed_account(source, connection.profile_id, profile, result))
                continue
            broker_positions = [value_position(row, usd_hkd=usd_hkd, usd_cny=usd_cny) for row in result["positions"]]
            priced_total = sum(
                (_decimal(row.get("market_value_usd")) for row in broker_positions),
                Decimal("0"),
            )
            account_total = account_total_usd(
                broker,
                result["account"],
                usd_hkd,
                usd_cny,
                priced_total,
            )
            if broker == "binance":
                account_total = priced_total
            cash_total = min(
                account_total,
                account_cash_usd(broker, result["account"], usd_hkd, usd_cny),
            )
            if not source.include_cash:
                account_total = max(Decimal("0"), account_total - cash_total)
                cash_total = Decimal("0")
            unpriced_or_other = max(Decimal("0"), account_total - priced_total - cash_total)
            priced_count = sum(1 for row in broker_positions if row.get("priced"))
            accounts.append(
                {
                    "source_id": source.id,
                    "profile_id": connection.profile_id,
                    "label": source.label,
                    "broker": broker,
                    "status": "ok",
                    "last_success_at": refreshed_at,
                    "total_usd": _number(account_total),
                    "total_cny": _number(account_total * usd_cny),
                    "priced_value_usd": _number(priced_total),
                    "cash_usd": _number(cash_total),
                    "unpriced_or_other_usd": _number(unpriced_or_other),
                    "position_count": len(broker_positions),
                    "priced_position_count": priced_count,
                    "unpriced_position_count": len(broker_positions) - priced_count,
                    "auth": auth_metadata(profile),
                    "portfolio_compatibility": profile_compatibility(profile),
                }
            )
            positions.extend(broker_positions)

        total_usd = sum((_decimal(row.get("total_usd")) for row in accounts), Decimal("0"))
        # Every enabled source produces exactly one account row, so a snapshot
        # is complete only when none of them failed.
        complete = all(row["status"] == "ok" for row in accounts)
        priced_usd = sum((_decimal(row.get("priced_value_usd")) for row in accounts), Decimal("0"))
        cash_usd = sum((_decimal(row.get("cash_usd")) for row in accounts), Decimal("0"))
        unpriced_usd = sum(
            (_decimal(row.get("unpriced_or_other_usd")) for row in accounts),
            Decimal("0"),
        )
        identified_usd = priced_usd + cash_usd
        payload = {
            "snapshot_id": uuid.uuid4().hex,
            "valuation_version": PORTFOLIO_VALUATION_VERSION,
            "created_at": refreshed_at,
            "complete": complete,
            "display_currency": settings.display_currency,
            "totals": {"usd": _number(total_usd), "cny": _number(total_usd * usd_cny)},
            "valuation": {
                "priced_usd": _number(priced_usd),
                "cash_usd": _number(cash_usd),
                "unpriced_or_other_usd": _number(unpriced_usd),
                "identified_coverage": (_number(identified_usd / total_usd) if total_usd > 0 else 0.0),
            },
            "fx": {
                "usd_cny": _number(usd_cny),
                "usd_hkd": _number(usd_hkd),
                "fetched_at": fx_at,
                "stale": fx_stale,
            },
            "accounts": accounts,
            "positions": sorted(
                positions,
                key=lambda row: _decimal(row.get("market_value_usd")),
                reverse=True,
            ),
            "combined_holdings": self._combine_holdings(positions),
            "warnings": self._warnings(accounts, positions, fx_stale),
        }
        self.store.save_snapshot(payload)
        return payload

    def _failed_account(
        self,
        source: PortfolioSource,
        profile_id: str,
        profile: TradingProfile,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the account row for a source that could not be read.

        The row is deliberately valueless: totals are ``None`` and no position
        is contributed, so a failed source can never be mistaken for an account
        that is genuinely worth less. ``last_success_at`` still reports when the
        source was last healthy, when such a snapshot exists.

        Args:
            source: The configured source that failed.
            profile_id: The connection's connector profile id.
            profile: The resolved connector profile.
            result: The captured failure carrying ``error`` and ``error_code``.

        Returns:
            An account row with status ``error`` and no monetary value.
        """
        cached = self.store.latest_successful_source(source.id)
        return {
            "source_id": source.id,
            "profile_id": profile_id,
            "label": source.label,
            "broker": profile.connector,
            "status": "error",
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "failure_kind": result.get("failure_kind", "transient"),
            "reconnect_required": bool(result.get("reconnect_required")),
            "last_success_at": cached["created_at"] if cached is not None else None,
            "total_usd": None,
            "total_cny": None,
            "position_count": 0,
            "auth": auth_metadata(profile),
            "portfolio_compatibility": profile_compatibility(profile),
        }

    def latest(self) -> dict[str, Any] | None:
        """Return the newest snapshot, but only if it covers today's selection.

        Returns:
            The snapshot envelope, or ``None`` when no snapshot exists or the
            stored one was taken over a different set of enabled sources.
        """
        snapshot = self.store.latest()
        if snapshot is None:
            return None
        if snapshot.get("valuation_version") != PORTFOLIO_VALUATION_VERSION:
            return None
        settings = self.settings_store.load()
        enabled_sources = [source for source in settings.sources if source.enabled]
        enabled = {source.id for source in enabled_sources}
        observed = {str(account.get("source_id") or account.get("broker")) for account in snapshot.get("accounts", [])}
        if not enabled or observed != enabled:
            return None

        compatibility_by_source = {}
        for source in enabled_sources:
            try:
                _, profile = self._connection_profile(source)
            except ValueError:
                continue
            compatibility_by_source[source.id] = profile_compatibility(profile)
        snapshot["accounts"] = [
            {
                **account,
                "portfolio_compatibility": account.get("portfolio_compatibility")
                or compatibility_by_source.get(str(account.get("source_id") or account.get("broker"))),
            }
            for account in snapshot.get("accounts", [])
        ]
        return snapshot

    def reconnect_source(self, source_id: str) -> dict[str, Any]:
        """Run a source's interactive OAuth flow on explicit user request.

        This is the only interactive path in the portfolio feature; an ordinary
        refresh always reads non-interactively so it can never open a browser.

        Args:
            source_id: The configured source to re-authorize.

        Returns:
            The authorization result and the read tools the server exposes.

        Raises:
            RuntimeError: If the source is unknown, does not use OAuth, or its
                MCP server is not configured.
        """
        from src.config.accessor import get_env_config
        from src.tools.mcp import MCPServerAdapter

        source, profile, server = self.reconnect_target(source_id)
        authorize_timeout = float(get_env_config().agent_tuning.vibe_live_authorize_timeout_s or 300)
        if hasattr(server, "model_copy"):
            updates = {}
            if float(server.init_timeout or 0) < authorize_timeout:
                updates["init_timeout"] = authorize_timeout
            if float(server.tool_timeout or 0) < authorize_timeout:
                updates["tool_timeout"] = authorize_timeout
            if updates:
                server = server.model_copy(update=updates)
        callback_port = server.auth.callback_port if server.auth is not None else None
        if callback_port is not None:
            _ensure_callback_port_available(callback_port)
        try:
            tools = MCPServerAdapter(
                profile.connector,
                server,
                max_list_tools_attempts=1,
                interactive_oauth=True,
            ).discover_tools()
        except BaseException as exc:
            if not _contains_system_exit(exc):
                raise
            raise RuntimeError("OAuth callback startup failed; authorization stopped safely") from exc
        return {
            "status": "ok",
            "authorized": True,
            "source_id": source.id,
            "enabled_read_tools": [item.remote_name for item in tools],
        }

    def reconnect_target(self, source_id: str):
        """Validate and return the local-only configuration for an OAuth source."""
        from src.config.loader import load_agent_config

        source = next(
            (item for item in self.settings_store.load().sources if item.id == source_id),
            None,
        )
        if source is None:
            raise RuntimeError(f"unknown portfolio source: {source_id}")
        _, profile = self._connection_profile(source)
        if profile.transport != "remote_mcp":
            raise RuntimeError("this source does not use OAuth; no reconnect is needed")
        server = (load_agent_config().mcp_servers or {}).get(profile.connector)
        if server is None:
            raise RuntimeError(f"the {profile.connector} MCP connection is not configured")
        if server.auth is None:
            raise RuntimeError(f"the {profile.connector} MCP connection does not configure OAuth")
        return source, profile, server

    def history(self, limit: int = 180) -> list[dict[str, Any]]:
        """Return the value series built only from complete snapshots.

        Incomplete snapshots are excluded because a source that failed
        contributes nothing to the total; charting them beside complete ones
        would draw a drop in portfolio value that never happened.

        Args:
            limit: Maximum number of snapshots to return, oldest first.

        Returns:
            One row per complete snapshot with its id, timestamp and totals.
        """
        return self.store.history(
            limit,
            complete_only=True,
            valuation_version=PORTFOLIO_VALUATION_VERSION,
        )

    def export_csv(self) -> str:
        """Render the latest snapshot's positions as CSV.

        Returns:
            The CSV text, or an empty string when no usable snapshot exists.
        """
        snapshot = self.latest()
        if snapshot is None:
            return ""
        fields = [
            "source_id",
            "source_label",
            "profile_id",
            "broker",
            "symbol",
            "name",
            "asset_type",
            "market",
            "currency",
            "quantity",
            "cost_price",
            "market_price",
            "market_value_usd",
            "market_value_cny",
            "unrealized_pnl_usd",
            "priced",
            "updated_at",
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(snapshot["positions"])
        return output.getvalue()

    def analysis_context(self) -> dict[str, Any] | None:
        """Return a credential/account-id-free snapshot suitable for an LLM.

        The context also carries ``risk_xray_args`` — the ``symbols`` and
        ``weights`` arguments for the existing ``portfolio_risk_xray`` tool.
        The portfolio supplies that tool's arguments; it does not reimplement
        or alter the analysis.

        Returns:
            The sanitized context, or ``None`` when no usable snapshot exists.
        """
        snapshot = self.latest()
        if snapshot is None:
            return None
        total = _decimal(snapshot["totals"]["usd"])
        holdings = []
        for row in snapshot.get("combined_holdings", []):
            market_value = _decimal(row.get("market_value_usd"))
            holdings.append(
                {
                    "symbol": row["symbol"],
                    "asset_type": row["asset_type"],
                    "markets": row["markets"],
                    "brokers": row["brokers"],
                    "market_value_usd": row["market_value_usd"],
                    "weight": _number(market_value / total) if total > 0 else 0.0,
                    "unrealized_pnl_usd": row["unrealized_pnl_usd"],
                }
            )
        return {
            "as_of": snapshot["created_at"],
            "complete": snapshot["complete"],
            "totals": snapshot["totals"],
            "account_allocation": [
                {
                    "broker_alias": f"account_{index + 1}",
                    "asset_provider_type": row["broker"],
                    "status": row["status"],
                    "total_usd": row.get("total_usd"),
                }
                for index, row in enumerate(snapshot["accounts"])
            ],
            "holdings": holdings,
            "risk_xray_args": self._risk_xray_args(snapshot.get("positions", [])),
            "warnings": snapshot["warnings"],
            "privacy": "No account numbers, credentials, order IDs, names, or local paths included.",
        }

    @staticmethod
    def _risk_xray_symbol(position: dict[str, Any]) -> str | None:
        """Map one held position onto a symbol the market-data loaders accept.

        The loader chain routes on the market suffix, so the connector-reported
        ticker is used as-is when it already carries one (``700.HK``,
        ``600519.SH``) and is qualified from the position's currency/market
        otherwise (IBKR reports a bare ``AAPL``, which would be read as an
        A-share code). A symbol whose market cannot be established is not
        guessed at.

        Args:
            position: A valued position row from a stored snapshot.

        Returns:
            A loader-routable symbol, or ``None`` when the market is unknown.
        """
        symbol = str(position.get("symbol") or "").strip().upper()
        if not symbol:
            return None
        head, _, suffix = symbol.rpartition(".")
        if head and suffix in _LOADER_MARKET_SUFFIXES:
            return symbol
        currency = str(position.get("price_currency") or position.get("currency") or "").upper()
        market = str(position.get("market") or "").upper()
        if currency == "HKD" or market == "HK":
            return f"{symbol}.HK" if symbol.isdigit() else None
        if currency == "USD" and symbol.isalpha():
            return f"{symbol}.US"
        return None

    @classmethod
    def _risk_xray_args(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the ``portfolio_risk_xray`` arguments for the held equities.

        Crypto, stablecoin and cash rows are dropped because the risk x-ray
        prices a long-only equity basket through the daily-bar loaders; so are
        unpriced rows and non-positive values, which carry no weight. The
        remaining positions are merged per symbol across sources and their
        weights renormalized to sum to 1.

        Args:
            positions: The valued positions of a stored snapshot.

        Returns:
            ``{"symbols": [...], "weights": {symbol: weight}}``, empty when the
            snapshot holds no priced equity position.
        """
        values: dict[str, Decimal] = {}
        for position in positions:
            if str(position.get("asset_type") or "").lower() in _NON_EQUITY_ASSET_TYPES:
                continue
            if not position.get("priced"):
                continue
            value = _decimal(position.get("market_value_usd"))
            if value <= 0:
                continue
            symbol = cls._risk_xray_symbol(position)
            if symbol is None:
                continue
            values[symbol] = values.get(symbol, Decimal("0")) + value
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        ranked = ranked[:_RISK_XRAY_MAX_SYMBOLS]
        total = sum((value for _, value in ranked), Decimal("0"))
        if total <= 0:
            return {"symbols": [], "weights": {}}
        return {
            "symbols": [symbol for symbol, _ in ranked],
            "weights": {symbol: _number(value / total) for symbol, value in ranked},
        }

    @staticmethod
    def _combine_holdings(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge the same instrument held at several sources into one row.

        Args:
            positions: Valued positions from every successfully read source.

        Returns:
            Holdings sorted by USD value, each flagged when it is held at more
            than one broker.
        """
        grouped: dict[str, dict[str, Any]] = {}
        for row in positions:
            symbol = str(row.get("symbol") or "").upper()
            currency = str(row.get("currency") or "").upper()
            market = str(row.get("market") or "").upper()
            if symbol.endswith(".US"):
                canonical = symbol[:-3]
            elif symbol.endswith(".HK"):
                canonical = symbol[:-3].lstrip("0") or "0"
            else:
                canonical = symbol
            region = (
                "HK"
                if currency == "HKD" or market == "HK" or symbol.endswith(".HK")
                else ("CRYPTO" if row.get("asset_type") in {"crypto", "stablecoin"} else "US")
            )
            key = f"{region}:{canonical}"
            item = grouped.setdefault(
                key,
                {
                    "canonical_id": key,
                    "symbol": canonical,
                    "asset_type": row.get("asset_type"),
                    "brokers": [],
                    "sources": [],
                    "markets": [],
                    "market_value_usd": Decimal("0"),
                    "market_value_cny": Decimal("0"),
                    "unrealized_pnl_usd": Decimal("0"),
                },
            )
            if row.get("broker") not in item["brokers"]:
                item["brokers"].append(row.get("broker"))
            source_label = row.get("source_label") or row.get("broker")
            if source_label not in item["sources"]:
                item["sources"].append(source_label)
            if row.get("market") not in item["markets"]:
                item["markets"].append(row.get("market"))
            item["market_value_usd"] += _decimal(row.get("market_value_usd"))
            item["market_value_cny"] += _decimal(row.get("market_value_cny"))
            item["unrealized_pnl_usd"] += _decimal(row.get("unrealized_pnl_usd"))
        result = []
        for item in grouped.values():
            item["brokers"].sort()
            item["sources"].sort()
            item["markets"] = sorted(str(value) for value in item["markets"] if value)
            item["duplicate_across_brokers"] = len(item["brokers"]) > 1
            for key in ("market_value_usd", "market_value_cny", "unrealized_pnl_usd"):
                item[key] = _number(item[key])
            result.append(item)
        return sorted(result, key=lambda row: _decimal(row["market_value_usd"]), reverse=True)

    def _collect_source(self, source: PortfolioSource) -> dict[str, Any]:
        """Read one source's account and positions, pricing what the connector omits.

        Args:
            source: The enabled source to read.

        Returns:
            ``{"source_id", "profile_id", "label", "broker", "status",
            "account", "positions"}`` for a successful read.

        Raises:
            RuntimeError: If the profile is not read-only, or either connector
                read returns a non-success status.
        """
        connection, profile = self._connection_profile(source)
        if not profile.readonly:
            raise RuntimeError("portfolio sources must use a read-only connector profile")
        broker = profile.connector
        profile_id = profile.id
        longbridge_batch: dict[str, Any] | None = None
        if broker == "longbridge" and profile_id == "longbridge-live-sdk-readonly" and self._use_longbridge_worker:
            isolated = self._read_longbridge_isolated(connection.id)
            account = isolated["account"]
            positions_payload = isolated["positions"]
            longbridge_batch = isolated.get("quotes")
        else:
            read_options: dict[str, Any] = {}
            if profile.transport == "remote_mcp":
                # A dashboard refresh must never open a browser. reconnect_source()
                # is the one explicit interactive path.
                read_options["interactive_oauth"] = False
            elif profile.transport in {"broker_sdk", "local_plugin"} and (
                profile.transport == "local_plugin" or self._use_connection_scoped_reads
            ):
                read_options["connection_id"] = connection.id
            account = self._get_account(profile_id, **read_options)
            positions_payload = self._get_positions(profile_id, **read_options)
        for label, payload in (("account", account), ("positions", positions_payload)):
            if str(payload.get("status") or "ok").lower() not in {"ok", "success"}:
                raise RuntimeError(
                    str(payload.get("error") or f"{broker} {label} read failed")
                )
        account, positions_payload = adapt_and_validate_payloads(broker, account, positions_payload)
        normalized_rows = [normalize_position(broker, raw) for raw in positions_payload.get("positions", [])]
        for row in normalized_rows:
            row.update(
                source_id=source.id,
                profile_id=connection.profile_id,
                source_label=source.label,
            )
        longbridge_prices: dict[str, Decimal] | None = None
        longbridge_price_error: str | None = None
        if broker == "longbridge" and longbridge_batch is not None:
            longbridge_prices = {
                str(item.get("symbol") or "").upper(): _decimal(item.get("last"))
                for item in longbridge_batch.get("quotes", [])
                if _decimal(item.get("last")) > 0
            }
            if str(longbridge_batch.get("status") or "ok").lower() not in {
                "ok",
                "success",
            }:
                longbridge_price_error = str(longbridge_batch.get("error") or "Longbridge quote read failed")[:160]
        elif broker == "longbridge" and self._get_longbridge_quotes is not None:
            try:
                batch = self._get_longbridge_quotes([str(row["quote_symbol"]) for row in normalized_rows])
                longbridge_prices = {
                    str(item.get("symbol") or "").upper(): _decimal(item.get("last"))
                    for item in batch.get("quotes", [])
                    if _decimal(item.get("last")) > 0
                }
            except Exception as exc:
                longbridge_prices = {}
                longbridge_price_error = str(exc)[:160]

        rows = []
        for normalized in normalized_rows:
            quantity = _decimal(normalized["quantity"])
            if quantity == 0:
                continue
            try:
                if broker in {"binance", "okx"} and normalized["symbol"] in STABLECOINS:
                    normalized["market_price"] = 1.0
                    normalized["price_currency"] = "USD"
                    normalized["pricing_basis"] = "USDT/USD proxy"
                elif _decimal(normalized.get("market_price")) > 0:
                    normalized["price_currency"] = normalized["currency"]
                    normalized["pricing_basis"] = f"{broker} position snapshot"
                elif broker == "longbridge" and longbridge_prices is not None:
                    price = longbridge_prices.get(str(normalized["quote_symbol"]).upper())
                    normalized["market_price"] = _number(price) if price else None
                    normalized["price_currency"] = normalized["currency"]
                    normalized["pricing_basis"] = (
                        "Longbridge official quote" if longbridge_batch is not None else "Fallback market quote"
                    )
                    if not price and longbridge_price_error:
                        normalized["price_error"] = longbridge_price_error
                else:
                    quote_symbol = normalized["quote_symbol"]
                    quote = self._get_quote(
                        quote_symbol,
                        profile_id,
                        exchange=normalized.get("exchange") or "SMART",
                        currency=normalized["currency"],
                        sec_type="STK",
                        **(
                            {"connection_id": connection.id}
                            if profile.transport == "local_plugin"
                            or (profile.transport == "broker_sdk" and self._use_connection_scoped_quotes)
                            else {}
                        ),
                    )
                    price = _quote_price(quote)
                    normalized["market_price"] = _number(price) if price else None
                    normalized["price_currency"] = normalized["currency"]
            except Exception as exc:
                normalized["price_error"] = str(exc)[:160]
            rows.append(normalized)
        ensure_supported_currencies(rows, account)
        return {
            "source_id": source.id,
            "profile_id": connection.profile_id,
            "label": source.label,
            "broker": broker,
            "status": "ok",
            "account": account,
            "positions": rows,
        }

    @staticmethod
    def _read_longbridge_isolated(connection_id: str) -> dict[str, Any]:
        """Read Longbridge in a throwaway subprocess and parse its payload.

        Returns:
            The worker's account/positions/quotes payload.

        Raises:
            RuntimeError: If the worker emitted no payload, reported an error,
                or returned an incomplete payload.
        """
        marker = "VIBE_PORTFOLIO_JSON="
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.portfolio.longbridge_worker",
                connection_id,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=40,
        )
        payload: dict[str, Any] | None = None
        for line in reversed(process.stdout.splitlines()):
            if line.startswith(marker):
                parsed = json.loads(line[len(marker) :])
                if isinstance(parsed, dict):
                    payload = parsed
                break
        if payload is None:
            raise RuntimeError("Longbridge isolated reader returned no payload")
        if payload.get("error"):
            raise RuntimeError(f"Longbridge isolated reader failed: {payload['error']}")
        if "account" not in payload or "positions" not in payload:
            raise RuntimeError("Longbridge isolated reader returned an incomplete payload")
        return payload

    def _rates(self) -> tuple[Decimal, Decimal, str, bool]:
        """Return the USD/CNY and USD/HKD rates used to value this snapshot.

        Returns:
            ``(usd_cny, usd_hkd, fetched_at, stale)`` where ``stale`` marks a
            fall back to the cached rates.

        Raises:
            RuntimeError: If the fetch fails and no cached pair exists.
        """
        try:
            usd_cny, usd_hkd, fetched_at = self._fx_fetcher()
            self.store.save_fx("USD", "CNY", str(usd_cny), fetched_at)
            self.store.save_fx("USD", "HKD", str(usd_hkd), fetched_at)
            return usd_cny, usd_hkd, fetched_at, False
        except Exception:
            cny = self.store.load_fx("USD", "CNY")
            hkd = self.store.load_fx("USD", "HKD")
            if cny is None or hkd is None:
                raise RuntimeError("FX service unavailable and no prior USD/CNY + USD/HKD cache exists")
            return _decimal(cny[0]), _decimal(hkd[0]), min(cny[1], hkd[1]), True

    @staticmethod
    def _fetch_fx() -> tuple[Decimal, Decimal, str]:
        """Fetch USD/CNY and USD/HKD from the public reference-rate endpoint.

        Returns:
            ``(usd_cny, usd_hkd, fetched_at)``.
        """
        url = "https://api.frankfurter.app/latest?from=USD&to=CNY,HKD"
        request = urllib.request.Request(url, headers={"User-Agent": "Vibe-Trading/portfolio"})
        with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310 - fixed HTTPS host
            payload = json.load(response)
        return (
            _decimal(payload["rates"]["CNY"]),
            _decimal(payload["rates"]["HKD"]),
            _now(),
        )

    @staticmethod
    def _warnings(accounts: list[dict[str, Any]], positions: list[dict[str, Any]], fx_stale: bool) -> list[str]:
        """Describe every reason this snapshot must be read with caution.

        Args:
            accounts: The per-source account rows of this snapshot.
            positions: The valued positions that were actually aggregated.
            fx_stale: Whether cached FX rates were used instead of fresh ones.

        Returns:
            English warning strings, safe to render verbatim in any UI.
        """
        warnings = []
        if fx_stale:
            warnings.append(
                "Exchange-rate service unavailable; valued with the last "
                "successfully fetched USD/CNY and USD/HKD rates."
            )
        failed = [str(row.get("label") or row["broker"]) for row in accounts if row["status"] != "ok"]
        if failed:
            warnings.append(
                "These sources failed to refresh and their value is excluded "
                "from the totals, positions and combined holdings, so the "
                "portfolio shown here is incomplete: " + ", ".join(failed) + "."
            )
        unpriced = [f"{row['broker']}:{row['symbol']}" for row in positions if not row.get("priced")]
        if unpriced:
            warnings.append("No price available for these positions: " + ", ".join(unpriced[:20]))
        experimental = [
            str(row.get("label") or row.get("broker"))
            for row in accounts
            if row.get("portfolio_compatibility", {}).get("level") == "experimental"
        ]
        if experimental:
            warnings.append(
                "Experimental portfolio connectors require broker-specific "
                "verification: " + ", ".join(experimental) + "."
            )
        crypto_proxies = sorted(
            {str(row.get("broker")) for row in positions if row.get("broker") in {"binance", "okx"}}
        )
        if crypto_proxies:
            warnings.append(", ".join(crypto_proxies) + " spot balances are valued with USDT treated as 1 USD.")
        return warnings
