"""Read-only Futu (moomoo) connector via the official ``futu-api`` SDK.

This module wraps Futu's ``OpenSecTradeContext`` / ``OpenQuoteContext`` for the
five read operations the trading layer exposes (account / positions / orders /
quote / history). It holds no order-placement method and never calls
``unlock_trade`` — writes are introduced in a later layer behind the paper guard
and, for live, the mandate gate.

Architecture is a LOCAL OpenD gateway (default ``127.0.0.1:11111``), exactly
like IBKR's local TWS / IB Gateway: OpenD runs on the operator's machine, holds
the Futu login, and the SDK speaks to it over a local socket. Vibe-Trading never
sees Futu credentials. A TCP-port-open probe runs before every connect so a
missing gateway degrades to a clean error instead of an SDK stack trace.

Paper-vs-live identity guard (the documented Futu discriminator): every account
row from ``OpenSecTradeContext.get_acc_list()`` carries a ``trd_env`` field
(``SIMULATE`` for paper, ``REAL`` for live). The connector resolves the account
whose ``trd_env`` matches the selected profile's environment; if a non-zero
``acc_id`` is configured, that row's ``trd_env`` must match the profile or the
guard fails closed. This pins ``paper_guard="trd_env_acc_list"``.

Futu SDK calls return ``(ret_code, data)`` tuples (and ``request_history_kline``
returns a 3-tuple ``(ret, df, page_key)``); ``data`` is typically a pandas
DataFrame which we convert with ``to_dict("records")`` before field mapping.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "futu.json"

#: Default local OpenD gateway endpoint.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11111

#: Profiles this connector understands and their default account environment.
PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}

#: Maps the connector environment to the Futu ``TrdEnv`` enum member name.
_ENV_TO_TRD_ENV = {
    "paper": "SIMULATE",
    "live": "REAL",
}


class FutuDependencyError(RuntimeError):
    """Raised when the optional ``futu-api`` package is not installed."""


class FutuConfigError(RuntimeError):
    """Raised when the connector configuration is missing or invalid."""


class FutuProfileMismatchError(RuntimeError):
    """Raised when a profile's account does not match its declared environment."""


@dataclass(frozen=True)
class FutuConfig:
    """Futu connector connection settings.

    Args:
        host: Local host where the OpenD gateway listens.
        port: OpenD socket port (default 11111).
        profile: ``paper``, ``live-readonly`` or ``live``.
        security_firm: Futu security firm, e.g. ``FUTUSECURITIES``.
        filter_trdmarket: Trade market filter for the trade context, e.g. ``HK``.
        acc_id: Account id; ``0`` means resolve by ``trd_env``.
        timeout: Network/connect timeout in seconds.
        readonly: Always true for this layer; order methods are not exposed.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    profile: str = "paper"
    security_firm: str = "FUTUSECURITIES"
    filter_trdmarket: str = "HK"
    acc_id: int = 0
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "FutuConfig":
        """Build a config from a JSON-like mapping, normalizing the profile.

        Args:
            data: Mapping with any subset of config fields.

        Returns:
            A normalized :class:`FutuConfig`.

        Raises:
            FutuConfigError: If the profile is not a recognized value.
        """
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise FutuConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        return cls(
            host=str(payload.get("host") or DEFAULT_HOST).strip(),
            port=int(payload.get("port") or DEFAULT_PORT),
            profile=profile,
            security_firm=str(payload.get("security_firm") or "FUTUSECURITIES").strip().upper(),
            filter_trdmarket=str(payload.get("filter_trdmarket") or "HK").strip().upper(),
            acc_id=int(payload.get("acc_id") or 0),
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        profile: str | None = None,
        security_firm: str | None = None,
        filter_trdmarket: str | None = None,
        acc_id: int | None = None,
    ) -> "FutuConfig":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if host is not None:
            payload["host"] = host
        if port is not None:
            payload["port"] = port
        if profile is not None:
            payload["profile"] = profile
        if security_firm is not None:
            payload["security_firm"] = security_firm
        if filter_trdmarket is not None:
            payload["filter_trdmarket"] = filter_trdmarket
        if acc_id is not None:
            payload["acc_id"] = acc_id
        return FutuConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        """Return ``paper`` or ``live`` for this profile."""
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def trd_env_name(self) -> str:
        """Return the Futu ``TrdEnv`` member name (``SIMULATE`` or ``REAL``)."""
        return _ENV_TO_TRD_ENV.get(self.environment, "SIMULATE")


_OVERRIDE_KEYS = ("host", "port", "profile", "security_firm", "filter_trdmarket", "acc_id")


def build_config(profile_config: Mapping[str, Any] | None = None, overrides: Mapping[str, Any] | None = None) -> "FutuConfig":
    """Resolve the effective config: saved file ← profile defaults ← CLI overrides.

    Gateway endpoint and account settings come from the saved
    ``~/.vibe-trading/futu.json``; the selected connector profile supplies the
    ``profile`` / ``filter_trdmarket`` intent; CLI/tool overrides win last.

    Args:
        profile_config: The connector profile's ``config`` dict.
        overrides: Per-call overrides (only known config keys are applied).

    Returns:
        A normalized :class:`FutuConfig`.
    """
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = FutuConfig.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    """Return the user-level Futu config path."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> FutuConfig:
    """Load Futu settings from ``~/.vibe-trading/futu.json``."""
    path = config_path()
    if not path.exists():
        return FutuConfig()
    try:
        return FutuConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise FutuConfigError(f"invalid Futu config at {path}: {exc}") from exc


def save_config(config: FutuConfig) -> Path:
    """Persist Futu settings with owner-only permissions."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def futu_available() -> bool:
    """Return whether the optional ``futu-api`` SDK can be imported."""
    try:
        _require_futu()
        return True
    except FutuDependencyError:
        return False


def check_status(config: FutuConfig | None = None) -> dict[str, Any]:
    """Check SDK readiness, gateway reachability, and account identity.

    Returns a JSON-serializable health report that degrades cleanly when the
    OpenD gateway is not running or ``futu-api`` is not installed. Does not place
    or mutate any broker state.

    Args:
        config: Optional target config; loaded from disk when omitted.

    Returns:
        A health report dict.
    """
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "futu-api", "installed": futu_available()},
        "paper_guard": "trd_env_acc_list",
        "trd_env": cfg.trd_env_name,
    }

    gateway_open = tcp_port_open(cfg.host, cfg.port)
    report["gateway"] = {"host": cfg.host, "port": cfg.port, "open": gateway_open}
    if not gateway_open:
        report["status"] = "error"
        report["error"] = (
            f"No Futu OpenD gateway is listening at {cfg.host}:{cfg.port}. "
            "Start OpenD, log in, and confirm the API port."
        )
        return report

    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install with `pip install futu-api`."
        return report

    try:
        snapshot = get_account_snapshot(cfg)
    except Exception as exc:  # noqa: BLE001 - health endpoint reports cleanly
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    report["account"] = {
        "profile": cfg.profile,
        "trd_env": cfg.trd_env_name,
        "acc_id": snapshot.get("acc_id"),
    }
    return report


def get_account_snapshot(config: FutuConfig | None = None) -> dict[str, Any]:
    """Fetch account funds/assets for the resolved account."""
    cfg = config or load_config()
    trade_ctx = _trade_ctx(cfg)
    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)
        rows = _records(_unwrap(trade_ctx.accinfo_query(trd_env=trd_env, acc_id=acc_id)))
        return {
            "status": "ok",
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
            "assets": [_account_to_dict(row) for row in rows],
        }
    finally:
        _close(trade_ctx)


def get_positions(config: FutuConfig | None = None) -> dict[str, Any]:
    """Fetch current positions for the resolved account."""
    cfg = config or load_config()
    trade_ctx = _trade_ctx(cfg)
    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)
        rows = _records(_unwrap(trade_ctx.position_list_query(trd_env=trd_env, acc_id=acc_id)))
        return {
            "status": "ok",
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
            "positions": [_position_to_dict(row) for row in rows],
        }
    finally:
        _close(trade_ctx)


def get_open_orders(config: FutuConfig | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    """Fetch open orders and, optionally, recent fills (deals)."""
    cfg = config or load_config()
    trade_ctx = _trade_ctx(cfg)
    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)
        orders = _records(_unwrap(trade_ctx.order_list_query(trd_env=trd_env, acc_id=acc_id)))
        result: dict[str, Any] = {
            "status": "ok",
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
            "open_orders": [_order_to_dict(row) for row in orders],
        }
        if include_executions:
            deals = _records(_unwrap(trade_ctx.deal_list_query(trd_env=trd_env, acc_id=acc_id)))
            result["executions"] = [_deal_to_dict(row) for row in deals]
        return result
    finally:
        _close(trade_ctx)


def get_quote(symbol: str, *, config: FutuConfig | None = None, **_: Any) -> dict[str, Any]:
    """Fetch a market-snapshot quote for ``symbol`` (e.g. ``HK.00700``)."""
    cfg = config or load_config()
    quote_ctx = _quote_ctx(cfg)
    try:
        code = symbol.strip().upper()
        rows = _records(_unwrap(quote_ctx.get_market_snapshot([code])))
        payload = _quote_to_dict(rows[0]) if rows else {}
        return {"status": "ok", "symbol": code, "quote": payload}
    finally:
        _close(quote_ctx)


#: Canonical period token → Futu ``KLType`` attribute name.
#: ``1H``/``4H``/``1D``/``1W`` alias the lowercase forms; ``1m`` vs ``1M`` stays
#: case-sensitive. ``4h``/``4H`` map to ``K_240M`` (not ``K_60M``).
_KLTYPE_MAP = {
    "1m": "K_1M",
    "5m": "K_5M",
    "15m": "K_15M",
    "30m": "K_30M",
    "1h": "K_60M",
    "1H": "K_60M",
    "4h": "K_240M",
    "4H": "K_240M",
    "1d": "K_DAY",
    "1D": "K_DAY",
    "1w": "K_WEEK",
    "1W": "K_WEEK",
    "1M": "K_MON",
}


def get_historical_bars(
    symbol: str,
    *,
    config: FutuConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    """Fetch historical K-line bars for ``symbol`` (e.g. ``US.AAPL``)."""
    cfg = config or load_config()
    futu = _require_futu()
    ktype_name = _KLTYPE_MAP.get(period.strip(), "K_DAY")
    ktype = getattr(futu.KLType, ktype_name, getattr(futu.KLType, "K_DAY"))
    quote_ctx = _quote_ctx(cfg)
    try:
        code = symbol.strip().upper()
        rows = _records(_unwrap(quote_ctx.request_history_kline(code, ktype=ktype, max_count=int(limit))))
        return {
            "status": "ok",
            "symbol": code,
            "period": period,
            "bars": [_bar_to_dict(row) for row in rows],
        }
    finally:
        _close(quote_ctx)


# ---------------------------------------------------------------------------
# Extended read-only data: rehab, capital flow, history deals, earnings
# calendar, account cash flow, and financial statements. All read-only, no
# order placement. These unlock fundamental analysis, attribution, and
# shadow-account workflows that the original five endpoints do not cover.
# ---------------------------------------------------------------------------


def get_rehab(
    symbol: str, *, config: FutuConfig | None = None, **_: Any
) -> dict[str, Any]:
    """Fetch dividend / split / rights-issue adjustment factors for ``symbol``.

    Args:
        symbol: Futu instrument code, e.g. ``HK.00700`` / ``US.AAPL``.
        config: Effective connector config; loaded from disk when omitted.

    Returns:
        Dict containing ``status`` and ``ex_dividend_events`` — a list of
        adjustment-factor rows (ex-date, cash dividend, share ratio, forward
        and backward adjustment factors A/B). Pass these into a backtest engine
        to compute forward-adjusted close prices and avoid dividend-driven gaps.
    """
    cfg = config or load_config()
    quote_ctx = _quote_ctx(cfg)
    try:
        code = symbol.strip().upper()
        rows = _records(_unwrap(quote_ctx.get_rehab(code)))
        return {
            "status": "ok",
            "symbol": code,
            "ex_dividend_events": rows,
        }
    finally:
        _close(quote_ctx)


def get_capital_flow(
    symbol: str,
    *,
    config: FutuConfig | None = None,
    period_type: str = "INTRADAY",
    **_: Any,
) -> dict[str, Any]:
    """Fetch historical capital flow for ``symbol``.

    Args:
        symbol: Futu instrument code, e.g. ``HK.00700``.
        period_type: ``INTRADAY`` / ``DAY`` / ``WEEK`` / ``MONTH``.
        config: Effective connector config; loaded from disk when omitted.

    Returns:
        Dict containing ``status``, ``symbol``, ``period_type``, and
        ``flows`` (a list of intraday/daily main-flow rows with super/big/mid/small
        inflow buckets). Use the ``super_in_flow`` + ``big_in_flow`` columns to
        gauge institutional activity.
    """
    cfg = config or load_config()
    quote_ctx = _quote_ctx(cfg)
    try:
        code = symbol.strip().upper()
        rows = _records(
            _unwrap(quote_ctx.get_capital_flow(code, period_type=period_type))
        )
        return {
            "status": "ok",
            "symbol": code,
            "period_type": period_type,
            "flows": rows,
        }
    finally:
        _close(quote_ctx)


def get_capital_distribution(
    symbol: str, *, config: FutuConfig | None = None, **_: Any
) -> dict[str, Any]:
    """Fetch today's live capital distribution snapshot for ``symbol``.

    Returns the latest in-flow vs out-flow split across super/big/mid/small
    buckets — useful for live "are institutions accumulating right now?" checks.
    """
    cfg = config or load_config()
    quote_ctx = _quote_ctx(cfg)
    try:
        code = symbol.strip().upper()
        rows = _records(_unwrap(quote_ctx.get_capital_distribution(code)))
        return {
            "status": "ok",
            "symbol": code,
            "distribution": rows,
        }
    finally:
        _close(quote_ctx)


def get_history_deals(
    start: str,
    end: str,
    *,
    config: FutuConfig | None = None,
    code: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Fetch historical FILL records (executed deals) for shadow-account analysis.

    Unlike ``history_order_list_query`` (which returns intent), this returns only
    orders that ACTUALLY filled, with fill price, qty, counter broker, fee, and
    settlement date. Required for true cost-basis reconstruction.

    Args:
        start: Start date string ``YYYY-MM-DD`` (Futu caps single-query window at
            360 days).
        end: End date string ``YYYY-MM-DD`` (inclusive). Pass empty string for
            "today".
        code: Optional Futu instrument code filter, e.g. ``HK.00700``. Empty
            string returns fills across all symbols.
        config: Effective connector config; loaded from disk when omitted.

    Returns:
        Dict containing ``status``, ``start``, ``end``, ``code``, and ``deals``
        — a list of fill records with deal_id, order_id, code, qty, price,
        trd_side, create_time, counter_broker_name.
    """
    cfg = config or load_config()
    trade_ctx = _trade_ctx(cfg)
    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)
        kwargs: dict[str, Any] = dict(trd_env=trd_env, acc_id=acc_id)
        if code:
            kwargs["code"] = code.strip().upper()
        else:
            kwargs["code"] = ""
        rows = _records(
            _unwrap(trade_ctx.history_deal_list_query(start=start, end=end, **kwargs))
        )
        return {
            "status": "ok",
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
            "start": start,
            "end": end,
            "deals": [_deal_to_dict(row) for row in rows],
        }
    finally:
        _close(trade_ctx)


def get_acc_cash_flow(
    clearing_date: str,
    *,
    config: FutuConfig | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Fetch account cash-flow movements for a given clearing date ``YYYY-MM-DD``.

    Useful for capital management review: deposit, withdrawal, FX conversion,
    buy/sell settlement, margin interest, dividends received, fees, etc.
    """
    cfg = config or load_config()
    trade_ctx = _trade_ctx(cfg)
    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)
        rows = _records(
            _unwrap(
                trade_ctx.get_acc_cash_flow(
                    clearing_date=clearing_date, trd_env=trd_env, acc_id=acc_id
                )
            )
        )
        return {
            "status": "ok",
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
            "clearing_date": clearing_date,
            "cash_flows": rows,
        }
    finally:
        _close(trade_ctx)


def get_financials(
    symbol: str,
    *,
    config: FutuConfig | None = None,
    statement_type: str = "INCOME",
    num: int = 20,
    **_: Any,
) -> dict[str, Any]:
    """Fetch financial statements (income / balance / cash flow / key ratios) for ``symbol``.

    Args:
        symbol: Futu instrument code, e.g. ``HK.00700`` / ``US.AAPL``.
        statement_type: ``INCOME`` / ``BALANCE`` / ``CASH_FLOW``. Maps to
            Futu's integer statement_type codes (1/2/3). Default ``INCOME``.
        num: Maximum number of statements to return.
        config: Effective connector config; loaded from disk when omitted.

    Returns:
        Dict containing ``status``, ``symbol``, ``statement_type``, and
        ``structure_list`` + ``report_list`` — flat row dictionaries keyed by
        field name (e.g. ``"营业总收入"``) for O(1) lookups, plus a list of raw
        report dicts for full inspection.
    """
    cfg = config or load_config()
    quote_ctx = _quote_ctx(cfg)
    try:
        code = symbol.strip().upper()
        # statement_type token → integer code (Futu SDK uses int enums).
        st_int_map = {"INCOME": 1, "BALANCE": 2, "CASH_FLOW": 3, "KEY_RATIO": 4}
        st_value = st_int_map.get(statement_type.upper(), 1)
        ret_tuple = quote_ctx.get_financials_statements(
            code=code,
            statement_type=st_value,
            num=num,
        )
        # SDK returns (ret_code, dict) where dict carries next_key / structure_list /
        # report_list_*
        ok_code = ret_tuple[0]
        payload = (
            ret_tuple[1]
            if len(ret_tuple) > 1 and isinstance(ret_tuple[1], dict)
            else {}
        )
        structure_list = payload.get("structure_list", [])
        # Pull all reports across pages? For v1 we return the first page only;
        # caller can re-invoke with next_key for more.
        report_lists = [
            payload.get("report_list", []),
            payload.get("report_list_annual", []),
            payload.get("report_list_quarter", []),
        ]
        merged_reports: list[Any] = []
        for rl in report_lists:
            if rl:
                merged_reports.extend(rl)
        futu = _require_futu()
        return {
            "status": "ok" if ok_code == getattr(futu, "RET_OK", 0) else "error",
            "symbol": code,
            "statement_type": statement_type.upper(),
            "next_key": payload.get("next_key"),
            "structure_list": structure_list,
            "report_list": merged_reports,
        }
    finally:
        _close(quote_ctx)


def get_earnings_calendar(
    *,
    config: FutuConfig | None = None,
    market: str = "US",
    begin_date: str = "",
    end_date: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Fetch upcoming earnings-release dates and EPS / revenue consensus.

    Args:
        market: ``US`` / ``HK``.
        begin_date: Start ``YYYY-MM-DD``. Defaults to today.
        end_date: End ``YYYY-MM-DD``. Defaults to begin_date + 30 days.
        config: Effective connector config; loaded from disk when omitted.

    Returns:
        Dict with ``status``, ``market``, ``begin_date``, ``end_date``, and
        ``events`` — list of upcoming earnings with code, name, earnings_date,
        eps_predict, eps_actual, revenue_predict, revenue_actual, iv, iv_rank.
    """
    cfg = config or load_config()
    quote_ctx = _quote_ctx(cfg)
    try:
        futu = _require_futu()
        market_attr = "US" if market.upper() == "US" else "HK"
        m = getattr(futu.Market, market_attr)
        ret_tuple = quote_ctx.get_earnings_calendar(
            market=m,
            begin_date=begin_date or None,
            end_date=end_date or None,
        )
        ok_value = getattr(_require_futu(), "RET_OK", 0)
        ok = ret_tuple[0]
        events = ret_tuple[1] if len(ret_tuple) > 1 else []
        return {
            "status": "ok" if ok == ok_value else "error",
            "market": market.upper(),
            "begin_date": begin_date,
            "end_date": end_date,
            "events": events if events is not None else [],
        }
    finally:
        _close(quote_ctx)
# ---------------------------------------------------------------------------
# Order placement (paper SIMULATE + live REAL, fail-closed)
# ---------------------------------------------------------------------------

#: Env var holding the MD5 of the Futu trade password (required to unlock live).
LIVE_TRADE_PWD_ENV = "FUTU_TRADE_PWD_MD5"

#: side token → Futu ``TrdSide`` enum member name.
_SIDE_TO_TRD_SIDE = {"buy": "BUY", "sell": "SELL"}


def place_order(
    config: FutuConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | int | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Place a Futu order through the local OpenD gateway.

    Resolves the account by ``trd_env`` (paper = SIMULATE, live = REAL), unlocks
    the trade context for live profiles only, then submits a market or limit
    order. Fails closed: every error path returns ``{"status": "error", ...}``
    instead of raising. Futu has no notional-based order path, so a notional-only
    request is rejected.

    Args:
        config: Effective connector config; loaded from disk when omitted.
        symbol: Futu instrument code, e.g. ``HK.00700`` / ``US.AAPL`` (passed
            through uppercased).
        side: ``buy`` or ``sell``.
        quantity: Share quantity (required; coerced to ``int``).
        notional: Cash amount. Unsupported by Futu — present only to satisfy the
            shared contract; supplying it without ``quantity`` is an error.
        order_type: ``market`` or ``limit``. ``limit`` requires ``limit_price``.
        limit_price: Limit price; required when ``order_type`` is ``limit``.
        time_in_force: Accepted for contract parity; Futu's ``place_order`` does
            not take a TIF on this path, so it is echoed back only.

    Returns:
        On success ``{"status": "ok", "order_id", "symbol", "side", "profile",
        ...}``; on any failure ``{"status": "error", "error": ...}``.
    """
    cfg = config or load_config()

    side_key = str(side or "").strip().lower()
    if side_key not in _SIDE_TO_TRD_SIDE:
        return _order_error(cfg, "side must be 'buy' or 'sell'")

    order_kind = str(order_type or "").strip().lower()
    if order_kind not in ("market", "limit"):
        return _order_error(cfg, "order_type must be 'market' or 'limit'")

    if quantity is None:
        if notional is not None:
            return _order_error(
                cfg, "Futu requires an explicit quantity; notional-based orders are not supported"
            )
        return _order_error(cfg, "quantity is required")

    try:
        qty_int = int(quantity)
    except (TypeError, ValueError):
        return _order_error(cfg, "quantity must be a whole number of shares")
    if qty_int <= 0:
        return _order_error(cfg, "quantity must be a positive whole number of shares")

    price = 0.0
    if order_kind == "limit":
        if limit_price is None:
            return _order_error(cfg, "limit_price is required for a limit order")
        try:
            price = float(limit_price)
        except (TypeError, ValueError):
            return _order_error(cfg, "limit_price must be a number")
        if price <= 0:
            return _order_error(cfg, "limit_price must be a positive number")

    code = str(symbol or "").strip().upper()
    if not code:
        return _order_error(cfg, "symbol is required")

    try:
        futu = _require_futu()
    except FutuDependencyError as exc:
        return _order_error(cfg, str(exc))

    try:
        trade_ctx = _trade_ctx(cfg)
    except (FutuConfigError, FutuDependencyError) as exc:
        return _order_error(cfg, str(exc))

    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)

        unlock_error = _unlock_if_live(cfg, trade_ctx, futu)
        if unlock_error is not None:
            return _order_error(cfg, unlock_error)

        trd_side = getattr(futu.TrdSide, _SIDE_TO_TRD_SIDE[side_key])
        ftu_order_type = (
            futu.OrderType.MARKET if order_kind == "market" else futu.OrderType.NORMAL
        )
        ret, data = trade_ctx.place_order(
            price=price,
            qty=qty_int,
            code=code,
            trd_side=trd_side,
            order_type=ftu_order_type,
            trd_env=trd_env,
            acc_id=acc_id,
        )
        if ret != getattr(futu, "RET_OK", 0):
            return _order_error(cfg, f"Futu place_order rejected the order: {data}")

        rows = _records(data)
        order_id = str(_first(rows[0], ("order_id",), "")) if rows else ""
        if not order_id:
            return _order_error(cfg, f"Futu accepted the order but returned no order_id: {data}")

        return {
            "status": "ok",
            "order_id": order_id,
            "symbol": code,
            "side": side_key,
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
            "order_type": order_kind,
            "quantity": qty_int,
            "limit_price": price if order_kind == "limit" else None,
            "time_in_force": str(time_in_force or "day"),
        }
    except FutuProfileMismatchError as exc:
        return _order_error(cfg, str(exc))
    except Exception as exc:  # noqa: BLE001 - order path must fail closed
        return _order_error(cfg, str(exc))
    finally:
        _close(trade_ctx)


def cancel_order(
    config: FutuConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Cancel a Futu order through the local OpenD gateway.

    Resolves the account by ``trd_env`` and unlocks for live profiles only, then
    issues ``modify_order(ModifyOrderOp.CANCEL, ...)``. Fails closed: every error
    path returns ``{"status": "error", ...}``.

    Args:
        config: Effective connector config; loaded from disk when omitted.
        order_id: The Futu order id to cancel.
        symbol: Optional instrument code; echoed back for caller context (Futu
            cancels by ``order_id`` and does not require the symbol).

    Returns:
        On success ``{"status": "ok", "order_id", "symbol", "profile", ...}``;
        on any failure ``{"status": "error", "error": ...}``.
    """
    cfg = config or load_config()

    oid = str(order_id or "").strip()
    if not oid:
        return _order_error(cfg, "order_id is required")

    code = str(symbol or "").strip().upper() or None

    try:
        futu = _require_futu()
    except FutuDependencyError as exc:
        return _order_error(cfg, str(exc))

    try:
        trade_ctx = _trade_ctx(cfg)
    except (FutuConfigError, FutuDependencyError) as exc:
        return _order_error(cfg, str(exc))

    try:
        acc_id = _resolve_acc_id(cfg, trade_ctx)
        trd_env = _trd_env_enum(cfg)

        unlock_error = _unlock_if_live(cfg, trade_ctx, futu)
        if unlock_error is not None:
            return _order_error(cfg, unlock_error)

        ret, data = trade_ctx.modify_order(
            futu.ModifyOrderOp.CANCEL,
            oid,
            0,
            0,
            trd_env=trd_env,
            acc_id=acc_id,
        )
        if ret != getattr(futu, "RET_OK", 0):
            return _order_error(cfg, f"Futu cancel rejected: {data}")

        return {
            "status": "ok",
            "order_id": oid,
            "symbol": code,
            "profile": cfg.profile,
            "trd_env": cfg.trd_env_name,
            "acc_id": acc_id,
        }
    except FutuProfileMismatchError as exc:
        return _order_error(cfg, str(exc))
    except Exception as exc:  # noqa: BLE001 - cancel path must fail closed
        return _order_error(cfg, str(exc))
    finally:
        _close(trade_ctx)


def _unlock_if_live(cfg: FutuConfig, trade_ctx: Any, futu: ModuleType) -> str | None:
    """Unlock the trade context for live profiles; paper (SIMULATE) is a no-op.

    Live trading requires the MD5 of the Futu trade password, read from the
    :data:`LIVE_TRADE_PWD_ENV` environment variable. Paper accounts must never be
    unlocked.

    Args:
        cfg: Effective connector config.
        trade_ctx: An open ``OpenSecTradeContext``.
        futu: The imported ``futu`` module.

    Returns:
        ``None`` on success (or when no unlock is needed); an error message
        string when the live unlock cannot be completed.
    """
    if cfg.environment != "live":
        return None
    from src.config.accessor import get_env_config

    pwd_md5 = get_env_config().api.futu_trade_pwd_md5.strip()
    if not pwd_md5:
        return f"live order requires {LIVE_TRADE_PWD_ENV}"
    ret, data = trade_ctx.unlock_trade(password_md5=pwd_md5, is_unlock=True)
    if ret != getattr(futu, "RET_OK", 0):
        return f"Futu unlock_trade failed: {data}"
    return None


def _order_error(cfg: FutuConfig, message: str) -> dict[str, Any]:
    """Build a fail-closed order error envelope tagged with the profile."""
    return {"status": "error", "error": message, "profile": cfg.profile}


# ---------------------------------------------------------------------------
# SDK plumbing
# ---------------------------------------------------------------------------


def _require_futu() -> ModuleType:
    try:
        import futu  # type: ignore
    except ModuleNotFoundError as exc:
        raise FutuDependencyError("futu-api is not installed; run `pip install futu-api`.") from exc
    return futu


def tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return whether a TCP socket accepts connections."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _assert_gateway(cfg: FutuConfig) -> None:
    """Fail with a clean error when the local OpenD gateway is unreachable."""
    if not tcp_port_open(cfg.host, cfg.port):
        raise FutuConfigError(
            f"No Futu OpenD gateway is listening at {cfg.host}:{cfg.port}. "
            "Start OpenD, log in, and confirm the API port."
        )


def _trade_ctx(cfg: FutuConfig):
    """Open an ``OpenSecTradeContext`` against the local OpenD gateway."""
    _assert_gateway(cfg)
    futu = _require_futu()
    trd_market = getattr(futu.TrdMarket, cfg.filter_trdmarket, getattr(futu.TrdMarket, "HK"))
    security_firm = getattr(futu.SecurityFirm, cfg.security_firm, getattr(futu.SecurityFirm, "FUTUSECURITIES"))
    try:
        return futu.OpenSecTradeContext(
            filter_trdmarket=trd_market,
            host=cfg.host,
            port=cfg.port,
            security_firm=security_firm,
        )
    except TypeError:
        return futu.OpenSecTradeContext(host=cfg.host, port=cfg.port)


def _quote_ctx(cfg: FutuConfig):
    """Open an ``OpenQuoteContext`` against the local OpenD gateway."""
    _assert_gateway(cfg)
    futu = _require_futu()
    return futu.OpenQuoteContext(host=cfg.host, port=cfg.port)


def _trd_env_enum(cfg: FutuConfig):
    """Return the ``TrdEnv`` enum value for this profile's environment."""
    futu = _require_futu()
    return getattr(futu.TrdEnv, cfg.trd_env_name, futu.TrdEnv.SIMULATE)


def _resolve_acc_id(cfg: FutuConfig, trade_ctx: Any) -> int:
    """Resolve and guard the account id by its ``trd_env``.

    Calls ``get_acc_list()``, keeps rows whose ``trd_env`` matches the profile,
    and either confirms the configured ``acc_id`` (failing closed on mismatch) or
    selects the first matching account when ``acc_id`` is ``0``.

    Args:
        cfg: Effective connector config.
        trade_ctx: An open ``OpenSecTradeContext``.

    Returns:
        The resolved Futu account id.

    Raises:
        FutuProfileMismatchError: If the configured account's ``trd_env`` does
            not match the profile, or no account matches the profile env.
    """
    rows = _records(_unwrap(trade_ctx.get_acc_list()))
    want = cfg.trd_env_name
    matching = [row for row in rows if _trd_env_of(row) == want]

    if cfg.acc_id:
        target = next((row for row in rows if _acc_id_of(row) == cfg.acc_id), None)
        if target is None:
            raise FutuProfileMismatchError(
                f"Configured acc_id {cfg.acc_id} was not found in the OpenD account list."
            )
        if _trd_env_of(target) != want:
            raise FutuProfileMismatchError(
                f"Configured acc_id {cfg.acc_id} has trd_env {_trd_env_of(target)!r}, "
                f"but profile {cfg.profile!r} requires {want!r}. "
                "Select a profile that matches this account's environment."
            )
        return cfg.acc_id

    if not matching:
        raise FutuProfileMismatchError(
            f"No Futu account with trd_env {want!r} was found for profile {cfg.profile!r}. "
            "Confirm OpenD is logged into the expected account."
        )
    return _acc_id_of(matching[0])


def _close(ctx: Any) -> None:
    """Close an OpenD context, swallowing teardown errors."""
    try:
        ctx.close()
    except Exception:  # noqa: BLE001 - teardown must not mask the primary result
        pass


def _public_config(cfg: FutuConfig) -> dict[str, Any]:
    """Config snapshot with no secret material (local endpoint only)."""
    return asdict(cfg)


# ---------------------------------------------------------------------------
# Defensive (ret_code, data) handling + DataFrame field extraction
# ---------------------------------------------------------------------------


def _unwrap(result: Any) -> Any:
    """Return the data payload from a Futu ``(ret_code, data[, page_key])`` tuple.

    Futu read calls return ``(ret_code, data)``; ``request_history_kline``
    returns a 3-tuple ``(ret, df, page_key)``. On a non-``RET_OK`` return code we
    yield ``None`` so the caller degrades to an empty record set rather than
    surfacing a raw SDK error string.

    Args:
        result: The raw value returned by an SDK read call.

    Returns:
        The data payload (typically a pandas DataFrame), or ``None`` on error.
    """
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return result
    ret_code, data = result[0], result[1]
    futu = _require_futu()
    if ret_code != getattr(futu, "RET_OK", 0):
        return None
    return data


def _records(data: Any) -> list[dict[str, Any]]:
    """Normalize a Futu data payload to a list of row dicts.

    Handles a pandas DataFrame (via ``to_dict('records')``), an existing list of
    dicts, a single mapping, or ``None``.

    Args:
        data: The payload returned by :func:`_unwrap`.

    Returns:
        A list of plain row dicts (possibly empty).
    """
    if data is None:
        return []
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict) and hasattr(data, "columns"):
        try:
            return list(to_dict("records"))
        except Exception:  # noqa: BLE001 - fall through to generic handling
            pass
    if isinstance(data, Mapping):
        return [dict(data)]
    if isinstance(data, (list, tuple)):
        return [dict(item) if isinstance(item, Mapping) else {"value": item} for item in data]
    return []


def _row_get(row: Mapping[str, Any], name: str, default: Any = None) -> Any:
    if not isinstance(row, Mapping):
        return default
    return row.get(name, default)


def _first(row: Mapping[str, Any], names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        value = _row_get(row, name, None)
        if value is not None:
            return value
    return default


def _trd_env_of(row: Mapping[str, Any]) -> str:
    return str(_first(row, ("trd_env", "trdEnv"), "")).upper()


def _acc_id_of(row: Mapping[str, Any]) -> int:
    try:
        return int(_first(row, ("acc_id", "accId"), 0) or 0)
    except (TypeError, ValueError):
        return 0


def _account_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "power": _first(row, ("power",)),
        "total_assets": _first(row, ("total_assets",)),
        "cash": _first(row, ("cash",)),
        "market_val": _first(row, ("market_val",)),
        "available_funds": _first(row, ("available_funds",)),
        "securities_assets": _first(row, ("securities_assets",)),
    }


def _position_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": _first(row, ("code",)),
        "qty": _first(row, ("qty",)),
        "can_sell_qty": _first(row, ("can_sell_qty",)),
        "cost_price": _first(row, ("cost_price",)),
        "market_val": _first(row, ("market_val",)),
        "pl_ratio": _first(row, ("pl_ratio",)),
        "pl_val": _first(row, ("pl_val",)),
        "position_side": str(_first(row, ("position_side",), "")),
    }


def _order_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": _first(row, ("order_id",)),
        "code": _first(row, ("code",)),
        "stock_name": _first(row, ("stock_name",)),
        "trd_side": str(_first(row, ("trd_side",), "")),
        "order_type": str(_first(row, ("order_type",), "")),
        "order_status": str(_first(row, ("order_status",), "")),
        "qty": _first(row, ("qty",)),
        "price": _first(row, ("price",)),
        "dealt_qty": _first(row, ("dealt_qty",)),
        "dealt_avg_price": _first(row, ("dealt_avg_price",)),
        "create_time": str(_first(row, ("create_time",), "")),
    }


def _deal_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "deal_id": _first(row, ("deal_id",)),
        "order_id": _first(row, ("order_id",)),
        "code": _first(row, ("code",)),
        "qty": _first(row, ("qty",)),
        "price": _first(row, ("price",)),
        "trd_side": str(_first(row, ("trd_side",), "")),
        "create_time": str(_first(row, ("create_time",), "")),
    }


def _quote_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": _first(row, ("code",)),
        "last": _first(row, ("last_price",)),
        "open": _first(row, ("open_price",)),
        "high": _first(row, ("high_price",)),
        "low": _first(row, ("low_price",)),
        "prev_close": _first(row, ("prev_close_price",)),
        "volume": _first(row, ("volume",)),
        "ask": _first(row, ("ask_price",)),
        "bid": _first(row, ("bid_price",)),
        "time": str(_first(row, ("update_time",), "")),
    }


def _bar_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": _first(row, ("code",)),
        "time": str(_first(row, ("time_key",), "")),
        "open": _first(row, ("open",)),
        "close": _first(row, ("close",)),
        "high": _first(row, ("high",)),
        "low": _first(row, ("low",)),
        "volume": _first(row, ("volume",)),
        "turnover": _first(row, ("turnover",)),
    }
