"""Generic local MiniQMT connector through the XtQuant Python API.

The adapter deliberately contains no broker name or broker-specific endpoint.
The broker's QMT build, ``userdata_mini`` directory, account id, and account
type are operator configuration.  XtQuant is optional and imported lazily so
the base application remains usable without a QMT installation.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator, Mapping

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "qmt.json"
GUARD_MARKER = "userdata_mini+account_pin"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
}

ACCOUNT_TYPES = frozenset(
    {
        "STOCK",
        "CREDIT",
        "FUTURE",
        "STOCK_OPTION",
        "HUGANGTONG",
        "SHENGANGTONG",
    }
)

PERIOD_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1mon": "1mon",
}


class QMTDependencyError(RuntimeError):
    """Raised when the optional XtQuant package is unavailable."""


class QMTConfigError(RuntimeError):
    """Raised when QMT configuration is invalid or incomplete."""


class QMTConnectionError(RuntimeError):
    """Raised when the local MiniQMT session cannot be established."""


@dataclass(frozen=True)
class QMTConfig:
    """Settings for a broker-provided MiniQMT terminal."""

    userdata_mini: str = ""
    account_id: str = ""
    account_type: str = "STOCK"
    profile: str = "paper"
    session_id: int = 9051
    strategy_name: str = "vibe-trading"
    order_remark: str = "vibe-trading"
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "QMTConfig":
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise QMTConfigError("profile must be 'paper' or 'live-readonly'")
        account_type = str(payload.get("account_type") or "STOCK").strip().upper()
        if account_type not in ACCOUNT_TYPES:
            raise QMTConfigError(f"unsupported account_type: {account_type}")
        return cls(
            userdata_mini=str(payload.get("userdata_mini") or "").strip(),
            account_id=str(payload.get("account_id") or "").strip(),
            account_type=account_type,
            profile=profile,
            session_id=int(payload.get("session_id") or 9051),
            strategy_name=str(payload.get("strategy_name") or "vibe-trading").strip(),
            order_remark=str(payload.get("order_remark") or "vibe-trading").strip(),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(self, **overrides: Any) -> "QMTConfig":
        payload = asdict(self)
        for key, value in overrides.items():
            if value is not None:
                payload[key] = value
        return QMTConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS[self.profile]


_OVERRIDE_KEYS = (
    "userdata_mini",
    "account_id",
    "account_type",
    "profile",
    "session_id",
    "strategy_name",
    "order_remark",
)


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> QMTConfig:
    """Resolve saved config, profile defaults, then call overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = QMTConfig.from_mapping(base)
    clean = {
        key: value
        for key, value in dict(overrides or {}).items()
        if key in _OVERRIDE_KEYS and value not in (None, "")
    }
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> QMTConfig:
    path = config_path()
    if not path.exists():
        return QMTConfig()
    try:
        return QMTConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise QMTConfigError(f"invalid QMT config at {path}: {exc}") from exc


def save_config(config: QMTConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _require_xtquant() -> SimpleNamespace:
    try:
        from xtquant import xtconstant, xtdata, xttrader, xttype  # type: ignore[import-not-found]
        from xtquant.xttrader import XtQuantTrader  # type: ignore[import-not-found]
        from xtquant.xttype import StockAccount  # type: ignore[import-not-found]
    except ImportError as exc:
        raise QMTDependencyError(
            "XtQuant is not installed. Install the broker/迅投-provided xtquant "
            "wheel and run a local MiniQMT terminal."
        ) from exc
    return SimpleNamespace(
        xtconstant=xtconstant,
        xtdata=xtdata,
        xttrader=xttrader,
        xttype=xttype,
        XtQuantTrader=XtQuantTrader,
        StockAccount=StockAccount,
    )


def qmt_available() -> bool:
    try:
        _require_xtquant()
        return True
    except QMTDependencyError:
        return False


def _missing_fields(cfg: QMTConfig) -> list[str]:
    missing: list[str] = []
    if not cfg.userdata_mini:
        missing.append("userdata_mini")
    if not cfg.account_id:
        missing.append("account_id")
    return missing


def _public_config(cfg: QMTConfig) -> dict[str, Any]:
    return {
        "userdata_mini": cfg.userdata_mini,
        "account_id": (cfg.account_id[:2] + "***") if cfg.account_id else "",
        "account_type": cfg.account_type,
        "profile": cfg.profile,
        "environment": cfg.environment,
        "session_id": cfg.session_id,
        "paper_guard": GUARD_MARKER,
    }


def _make_account(deps: SimpleNamespace, cfg: QMTConfig) -> Any:
    try:
        return deps.StockAccount(cfg.account_id, cfg.account_type)
    except TypeError:
        # Older XtQuant builds accepted only the account id for STOCK accounts.
        if cfg.account_type != "STOCK":
            raise
        return deps.StockAccount(cfg.account_id)


_QMT_LOCK = threading.RLock()


@contextmanager
def _session(cfg: QMTConfig, *, subscribe: bool = True) -> Iterator[tuple[SimpleNamespace, Any, Any]]:
    deps = _require_xtquant()
    if _missing_fields(cfg):
        raise QMTConfigError("missing required QMT config: " + ", ".join(_missing_fields(cfg)))
    path = Path(cfg.userdata_mini).expanduser()
    if not path.is_dir():
        raise QMTConfigError(f"userdata_mini directory does not exist: {path}")

    with _QMT_LOCK:
        trader = deps.XtQuantTrader(str(path), cfg.session_id)
        started = False
        try:
            start_result = trader.start()
            started = True
            if start_result not in (None, 0):
                raise QMTConnectionError(f"MiniQMT start failed: {start_result}")
            connect_result = trader.connect()
            if connect_result not in (None, 0):
                raise QMTConnectionError(f"MiniQMT connect failed: {connect_result}")
            account = _make_account(deps, cfg)
            if subscribe:
                subscribe_result = trader.subscribe(account)
                if subscribe_result not in (None, 0):
                    raise QMTConnectionError(f"MiniQMT account subscribe failed: {subscribe_result}")
            identity_probe = getattr(trader, "query_stock_asset", None)
            if callable(identity_probe):
                identity_asset = identity_probe(account)
                if identity_asset is None:
                    raise QMTConnectionError("MiniQMT returned no account asset for the configured account")
                _assert_account_identity(identity_asset, cfg)
            yield deps, trader, account
        finally:
            if started:
                stop = getattr(trader, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:  # noqa: BLE001 - cleanup must not mask the result
                        pass


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict(orient="records")
        except TypeError:
            result = to_dict()
        return _serialize(result)
    try:
        return {
            key: _serialize(getattr(value, key))
            for key in vars(value)
            if not key.startswith("_") and not callable(getattr(value, key))
        }
    except TypeError:
        result: dict[str, Any] = {}
        for key in dir(value):
            if key.startswith("_"):
                continue
            try:
                item = getattr(value, key)
            except Exception:  # noqa: BLE001 - optional SDK properties may throw
                continue
            if not callable(item) and isinstance(item, (str, int, float, bool, type(None), list, tuple, dict)):
                result[key] = _serialize(item)
        return result or str(value)


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        result = getattr(value, name, None)
        if result is not None:
            return result
    return default


def _asset_payload(asset: Any, cfg: QMTConfig) -> dict[str, Any]:
    return {
        "account_id": _field(asset, "account_id", "m_strAccountID", default=cfg.account_id),
        "account_type": _field(asset, "account_type", "m_nAccountType", default=cfg.account_type),
        "cash": _field(asset, "cash", "m_dCash"),
        "frozen_cash": _field(asset, "frozen_cash", "m_dFrozenCash"),
        "market_value": _field(asset, "market_value", "m_dMarketValue"),
        "total_asset": _field(asset, "total_asset", "m_dTotalAsset"),
        "fetch_balance": _field(asset, "fetch_balance", "m_dFetchBalance"),
    }


def _assert_account_identity(asset: Any, cfg: QMTConfig) -> None:
    actual_id = _field(asset, "account_id", "m_strAccountID")
    if actual_id not in (None, "") and str(actual_id).strip() != cfg.account_id:
        raise QMTConnectionError(
            f"MiniQMT account mismatch: configured {cfg.account_id!r}, returned {actual_id!r}"
        )
    actual_type = _field(asset, "account_type", "m_nAccountType")
    if isinstance(actual_type, str) and actual_type.strip().upper() != cfg.account_type:
        raise QMTConnectionError(
            f"MiniQMT account type mismatch: configured {cfg.account_type!r}, returned {actual_type!r}"
        )


def _ok(**payload: Any) -> dict[str, Any]:
    return {"status": "ok", **payload}


def _error(exc: Exception) -> dict[str, Any]:
    return {"status": "error", "error": str(exc)}


def _prepare_data(deps: SimpleNamespace, cfg: QMTConfig) -> None:
    missing = _missing_fields(cfg)
    if missing:
        raise QMTConfigError("missing required QMT config: " + ", ".join(missing))
    path = Path(cfg.userdata_mini).expanduser()
    if not path.is_dir():
        raise QMTConfigError(f"userdata_mini directory does not exist: {path}")
    # XtData normally discovers this through the running terminal. Setting it
    # explicitly prevents a second QMT installation from supplying data.
    try:
        deps.xtdata.data_dir = str(path)
    except Exception:  # noqa: BLE001 - older builds may expose a read-only property
        pass


def check_status(config: QMTConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "xtquant", "installed": qmt_available()},
        "paper_guard": GUARD_MARKER,
    }
    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"QMT connector not configured: missing {', '.join(missing)}."
        return report
    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install the XtQuant wheel."
        return report
    try:
        with _session(cfg) as (_deps, trader, account):
            asset = trader.query_stock_asset(account)
            if asset is None:
                raise QMTConnectionError("MiniQMT returned no account asset for the configured account")
            _assert_account_identity(asset, cfg)
            report["account"] = _asset_payload(asset, cfg)
    except Exception as exc:  # noqa: BLE001 - health endpoint must be serializable
        report["status"] = "error"
        report["error"] = str(exc)
    return report


def get_account_snapshot(config: QMTConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    try:
        with _session(cfg) as (_deps, trader, account):
            asset = trader.query_stock_asset(account)
            if asset is None:
                raise QMTConnectionError("MiniQMT returned no account asset")
            _assert_account_identity(asset, cfg)
            return _ok(account=_asset_payload(asset, cfg), raw=_serialize(asset))
    except Exception as exc:  # noqa: BLE001 - connector operations return envelopes
        return _error(exc)


def get_positions(config: QMTConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    try:
        with _session(cfg) as (_deps, trader, account):
            positions = trader.query_stock_positions(account) or []
            return _ok(positions=_serialize(positions))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def get_open_orders(config: QMTConfig | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    cfg = config or load_config()
    try:
        with _session(cfg) as (_deps, trader, account):
            orders = trader.query_stock_orders(account) or []
            payload: dict[str, Any] = {"orders": _serialize(orders)}
            if include_executions:
                payload["executions"] = _serialize(trader.query_stock_trades(account) or [])
            return _ok(**payload)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def _normalize_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if value.startswith(("SH.", "SZ.", "BJ.")):
        market, code = value.split(".", 1)
        return f"{code}.{market}"
    if "." in value:
        return value
    if value.startswith(("4", "8")):
        return f"{value}.BJ"
    if value.startswith(("6",)):
        return f"{value}.SH"
    if value.startswith(("0", "2", "3")):
        return f"{value}.SZ"
    return value


def get_quote(symbol: str, *, config: QMTConfig | None = None, **_: Any) -> dict[str, Any]:
    cfg = config or load_config()
    clean_symbol = _normalize_symbol(symbol)
    try:
        deps = _require_xtquant()
        _prepare_data(deps, cfg)
        if not callable(getattr(deps.xtdata, "get_full_tick", None)):
            raise QMTDependencyError("installed XtQuant build has no xtdata.get_full_tick")
        ticks = deps.xtdata.get_full_tick([clean_symbol]) or {}
        tick = ticks.get(clean_symbol) or ticks.get(symbol)
        if tick is None and ticks:
            tick = next(iter(ticks.values()))
        if tick is None:
            raise QMTConnectionError(f"MiniQMT returned no quote for {clean_symbol}")
        return _ok(symbol=clean_symbol, quote=_serialize(tick), raw=_serialize(tick))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def _extract_bars(data: Any, symbol: str) -> list[dict[str, Any]]:
    if isinstance(data, Mapping):
        data = data.get(symbol, data)
    if hasattr(data, "to_dict") and callable(data.to_dict):
        try:
            data = data.to_dict(orient="records")
        except TypeError:
            data = data.to_dict()
    if isinstance(data, list):
        return [_serialize(item) for item in data]
    if isinstance(data, Mapping):
        values = {key: value for key, value in data.items()}
        lengths = [len(value) for value in values.values() if hasattr(value, "__len__") and not isinstance(value, str)]
        if lengths:
            length = min(lengths)
            return [
                {
                    str(key): _serialize(value[index])
                    for key, value in values.items()
                    if hasattr(value, "__len__") and not isinstance(value, str)
                }
                for index in range(length)
            ]
    return []


def get_historical_bars(
    symbol: str,
    *,
    config: QMTConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    cfg = config or load_config()
    clean_symbol = _normalize_symbol(symbol)
    token = PERIOD_MAP.get(str(period or "").strip().lower())
    if token is None:
        return _error(QMTConfigError(f"unsupported period: {period!r}; supported: {sorted(PERIOD_MAP)}"))
    try:
        deps = _require_xtquant()
        _prepare_data(deps, cfg)
        download = getattr(deps.xtdata, "download_history_data", None)
        if callable(download):
            download(clean_symbol, token, "", "")
        getter = getattr(deps.xtdata, "get_market_data_ex", None)
        if not callable(getter):
            raise QMTDependencyError("installed XtQuant build has no xtdata.get_market_data_ex")
        data = getter(
            ["time", "open", "high", "low", "close", "volume"],
            [clean_symbol],
            period=token,
            count=max(1, int(limit)),
            dividend_type="none",
            fill_data=False,
        )
        return _ok(symbol=clean_symbol, period=token, bars=_extract_bars(data, clean_symbol))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def _constant(constants: ModuleType | Any, name: str) -> Any:
    value = getattr(constants, name, None)
    if value is None:
        raise QMTConfigError(f"installed XtQuant build is missing constant {name}")
    return value


def place_order(
    config: QMTConfig,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Place a paper order only.

    QMT does not expose a reliable generic paper/live discriminator through
    XtQuant.  Live order placement therefore remains deliberately unavailable
    until a terminal-specific identity guard is added.
    """
    if config.environment != "paper":
        return _error(QMTConfigError("QMT live order placement is disabled; use the live read-only profile"))
    if config.readonly:
        return _error(QMTConfigError("QMT profile is read-only; use qmt-paper-trade for paper orders"))
    if quantity is None:
        return _error(QMTConfigError("QMT order quantity is required; notional sizing is unsupported"))
    try:
        volume = int(quantity)
    except (TypeError, ValueError) as exc:
        return _error(QMTConfigError("QMT order quantity must be an integer number of shares"))
    if volume <= 0 or float(quantity) != volume:
        return _error(QMTConfigError("QMT order quantity must be a positive integer number of shares"))
    clean_symbol = _normalize_symbol(symbol)
    side_token = str(side or "").strip().lower()
    order_token = str(order_type or "").strip().lower()
    try:
        with _session(config) as (deps, trader, account):
            side_name = "STOCK_BUY" if side_token == "buy" else "STOCK_SELL" if side_token == "sell" else ""
            if not side_name:
                raise QMTConfigError("QMT side must be 'buy' or 'sell'")
            order_side = _constant(deps.xtconstant, side_name)
            if order_token == "limit":
                if limit_price is None or float(limit_price) <= 0:
                    raise QMTConfigError("QMT limit orders require a positive limit_price")
                price_type = _constant(deps.xtconstant, "FIX_PRICE")
                price = float(limit_price)
            elif order_token == "market":
                price_type = _constant(deps.xtconstant, "LATEST_PRICE")
                price = -1
            else:
                raise QMTConfigError("QMT order_type must be 'market' or 'limit'")
            order_id = trader.order_stock(
                account,
                clean_symbol,
                order_side,
                volume,
                price_type,
                price,
                config.strategy_name,
                config.order_remark,
            )
            if order_id is None or int(order_id) <= 0:
                return _error(QMTConnectionError(f"MiniQMT rejected order: {order_id}"))
            return _ok(
                order_id=int(order_id),
                symbol=clean_symbol,
                side=side_token,
                quantity=volume,
                order_type=order_token,
                limit_price=float(limit_price) if limit_price is not None else None,
                time_in_force=time_in_force,
            )
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def cancel_order(config: QMTConfig, order_id: str, *, symbol: str | None = None) -> dict[str, Any]:
    """Cancel a paper order; live cancellation stays disabled with live writes."""
    if config.environment != "paper":
        return _error(QMTConfigError("QMT live order cancellation is disabled; use the live read-only profile"))
    if config.readonly:
        return _error(QMTConfigError("QMT profile is read-only; use qmt-paper-trade for paper cancellations"))
    try:
        numeric_id = int(order_id)
    except (TypeError, ValueError):
        return _error(QMTConfigError("QMT order_id must be an integer"))
    try:
        with _session(config) as (_deps, trader, account):
            result = trader.cancel_order_stock(account, numeric_id)
            if result not in (None, 0):
                return _error(QMTConnectionError(f"MiniQMT rejected cancellation: {result}"))
            return _ok(order_id=numeric_id, symbol=_normalize_symbol(symbol) if symbol else None)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)
