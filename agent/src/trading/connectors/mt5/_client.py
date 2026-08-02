"""MT5 config, session lifecycle, identity guard, and USD sizing helpers.

The ``MetaTrader5`` Python API is process-global and stateful: one
``initialize()`` per process, module-level functions, ``shutdown()`` to
detach. Every operation therefore runs inside :func:`_session` — a lock,
initialize, bidirectional profile/identity verification, work, shutdown —
so no read or write can ever execute against the wrong account class.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator, Mapping

from src.config.paths import get_runtime_root
from src.trading.connectors.mt5.symbols import normalize_base

CONFIG_FILENAME = "mt5.json"

#: Profiles this connector understands and their account environment.
PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
    "live": "live",
}

#: Guard marker recorded on every payload: the demo/live discriminator is
#: re-verified from the terminal on every session (trade_mode) and the login
#: is pinned against the configured one.
GUARD_MARKER = "terminal_trade_mode+login_pin"


class MT5DependencyError(RuntimeError):
    """Raised when the optional Windows-only ``MetaTrader5`` package is missing."""


class MT5ConfigError(RuntimeError):
    """Raised when the connector configuration or a symbol is missing/invalid."""


class MT5ConnectionError(RuntimeError):
    """Raised when the local MT5 terminal cannot be attached or queried."""


class MT5ProfileMismatchError(RuntimeError):
    """Raised when the terminal account does not match the selected profile."""


@dataclass(frozen=True)
class MT5Config:
    """MT5 connector connection settings (persisted in ``~/.vibe-trading/mt5.json``).

    Args:
        login: Terminal account number; pinned against ``account_info().login``.
        password: Account password (redacted in every public payload).
        server: Broker server name, e.g. ``"Exness-MT5Trial8"``.
        terminal_path: Optional path to ``terminal64.exe`` when several
            terminals are installed.
        profile: ``paper``, ``live-readonly`` or ``live``. ``paper`` means the
            broker's DEMO account.
        symbol_suffix: Broker account-type suffix appended verbatim to base
            symbols (Exness: ``"m"`` → ``EURUSDm``).
        deviation_points: Max market-order slippage in points.
        max_order_volume: Connector-level per-order lot ceiling (demo AND live).
        max_order_notional_usd: Connector-level per-order USD ceiling (demo AND
            live) — defense-in-depth under the live mandate gate.
        timeout: Terminal attach timeout in seconds.
        readonly: Interface symmetry with the other SDK connectors.
    """

    login: int = 0
    password: str = ""
    server: str = ""
    terminal_path: str = ""
    profile: str = "paper"
    symbol_suffix: str = ""
    deviation_points: int = 20
    max_order_volume: float = 1.0
    max_order_notional_usd: float = 10_000.0
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "MT5Config":
        """Build a config from a JSON-like mapping, normalizing the profile."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise MT5ConfigError("profile must be 'paper', 'live-readonly' or 'live'")
        return cls(
            login=int(payload.get("login") or 0),
            password=str(payload.get("password") or ""),
            server=str(payload.get("server") or "").strip(),
            terminal_path=str(payload.get("terminal_path") or "").strip(),
            profile=profile,
            symbol_suffix=str(payload.get("symbol_suffix") or "").strip(),
            deviation_points=int(payload.get("deviation_points") or 20),
            max_order_volume=float(payload.get("max_order_volume") or 1.0),
            max_order_notional_usd=float(payload.get("max_order_notional_usd") or 10_000.0),
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(self, **overrides: Any) -> "MT5Config":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        for key, value in overrides.items():
            if value is not None:
                payload[key] = value
        return MT5Config.from_mapping(payload)

    @property
    def environment(self) -> str:
        """Return ``paper`` or ``live`` for this profile."""
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def is_demo(self) -> bool:
        """Return whether this profile targets the broker's demo account."""
        return self.environment == "paper"


_OVERRIDE_KEYS = ("login", "password", "server", "terminal_path", "profile", "symbol_suffix")


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> "MT5Config":
    """Resolve config: saved file ← profile defaults ← CLI overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = MT5Config.from_mapping(base)
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    """Return the user-level MT5 config path."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> MT5Config:
    """Load MT5 settings from ``~/.vibe-trading/mt5.json``."""
    path = config_path()
    if not path.exists():
        return MT5Config()
    try:
        return MT5Config.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise MT5ConfigError(f"invalid MT5 config at {path}: {exc}") from exc


def save_config(config: MT5Config) -> Path:
    """Persist MT5 settings with owner-only permissions (best-effort on Windows)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def mt5_available() -> bool:
    """Return whether the optional ``MetaTrader5`` package can be imported."""
    try:
        _require_mt5()
        return True
    except MT5DependencyError:
        return False


def _require_mt5() -> ModuleType:
    """Import the Windows-only ``MetaTrader5`` package or fail with an install hint."""
    try:
        import MetaTrader5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MT5DependencyError(
            "MetaTrader5 is not installed (Windows-only). Install the extra with "
            '`pip install "vibe-trading-ai[mt5]"` and run a local MT5 terminal.'
        ) from exc
    return MetaTrader5


def _missing_fields(cfg: MT5Config) -> list[str]:
    """Fields the connector cannot operate without (login pin is mandatory)."""
    missing = []
    if not cfg.login:
        missing.append("login")
    if not cfg.password:
        missing.append("password")
    if not cfg.server:
        missing.append("server")
    return missing


def _public_config(cfg: MT5Config) -> dict[str, Any]:
    """Redacted config for health/error payloads (never leaks secrets)."""
    login_text = str(cfg.login) if cfg.login else ""
    return {
        "login": (login_text[:2] + "***") if login_text else "",
        "password": "***redacted***" if cfg.password else "",
        "server": cfg.server,
        "terminal_path": cfg.terminal_path,
        "profile": cfg.profile,
        "environment": cfg.environment,
        "is_demo": cfg.is_demo,
        "symbol_suffix": cfg.symbol_suffix,
        "deviation_points": cfg.deviation_points,
        "max_order_volume": cfg.max_order_volume,
        "max_order_notional_usd": cfg.max_order_notional_usd,
        "paper_guard": GUARD_MARKER,
    }


#: The MetaTrader5 API is process-global; sessions must never interleave.
_MT5_LOCK = threading.Lock()


def _last_error(mt5: Any) -> str:
    """Best-effort ``last_error()`` text for diagnostics."""
    try:
        return str(mt5.last_error())
    except Exception:  # noqa: BLE001 - diagnostics must never mask the real error
        return "unknown"


@contextmanager
def _session(cfg: MT5Config) -> Iterator[Any]:
    """Attach to the terminal, verify identity, yield the module, detach.

    Raises:
        MT5DependencyError: The ``MetaTrader5`` package is not installed.
        MT5ConnectionError: The terminal is not running/reachable or the
            account cannot be read.
        MT5ProfileMismatchError: The terminal account's trade mode or login
            does not match the selected profile (fail-closed, bidirectional).
    """
    mt5 = _require_mt5()
    with _MT5_LOCK:
        kwargs: dict[str, Any] = {
            "login": cfg.login,
            "password": cfg.password,
            "server": cfg.server,
            "timeout": int(cfg.timeout * 1000),
        }
        args = (cfg.terminal_path,) if cfg.terminal_path else ()
        if not mt5.initialize(*args, **kwargs):
            raise MT5ConnectionError(
                f"MT5 initialize failed ({_last_error(mt5)}); is the MT5 terminal "
                "installed, running, and logged in to the configured server?"
            )
        try:
            account = mt5.account_info()
            if account is None:
                raise MT5ConnectionError(f"MT5 account_info unavailable ({_last_error(mt5)})")
            _assert_profile(cfg, account, mt5)
            yield mt5
        finally:
            try:
                mt5.shutdown()
            except Exception:  # noqa: BLE001 - detach must never mask the result
                pass


def _assert_profile(cfg: MT5Config, account: Any, mt5: Any) -> None:
    """Hard bidirectional identity guard, run inside every session.

    Paper profiles require a DEMO account; live profiles require a REAL
    account; contest accounts are rejected everywhere (fail-closed). The
    configured login is pinned against the terminal's actual login.
    """
    trade_mode = getattr(account, "trade_mode", None)
    demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
    real_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2)
    if cfg.environment == "paper" and trade_mode != demo_mode:
        raise MT5ProfileMismatchError(
            f"paper profile {cfg.profile!r} requires a DEMO account, but the terminal "
            f"is logged in to trade_mode={trade_mode!r} — refusing (fail-closed)."
        )
    if cfg.environment == "live" and trade_mode != real_mode:
        raise MT5ProfileMismatchError(
            f"live profile {cfg.profile!r} requires a REAL account, but the terminal "
            f"is logged in to trade_mode={trade_mode!r} — refusing (fail-closed)."
        )
    terminal_login = getattr(account, "login", None)
    if cfg.login and terminal_login is not None and int(terminal_login) != cfg.login:
        raise MT5ProfileMismatchError(
            "login pin mismatch: profile is configured for a different account than "
            "the terminal's — refusing (fail-closed)."
        )


def _resolve_symbol(mt5: Any, cfg: MT5Config, symbol: str) -> str:
    """Resolve a project symbol to the broker's Market Watch name.

    Tries the configured suffix first, then the bare base, then discovers
    suffixed variants via ``symbols_get`` (shortest match wins, which picks
    ``EURUSDm`` over ``EURUSDz`` deterministically on Exness).
    """
    base = normalize_base(symbol)
    if not base:
        raise MT5ConfigError("symbol is required")
    candidates = []
    if cfg.symbol_suffix:
        candidates.append(base + cfg.symbol_suffix)
    candidates.append(base)
    name = next((c for c in candidates if mt5.symbol_info(c) is not None), None)
    if name is None:
        matches = sorted(
            (getattr(info, "name", "") for info in (mt5.symbols_get(group=f"{base}*") or ())),
            key=len,
        )
        matches = [m for m in matches if m]
        if not matches:
            raise MT5ConfigError(f"symbol {symbol!r} not offered by this broker (no match for {base}*)")
        name = matches[0]
    if not mt5.symbol_select(name, True):
        raise MT5ConfigError(f"symbol {name!r} could not be selected in Market Watch")
    return name


def _tick_mid(mt5: Any, name: str) -> float | None:
    """Mid price from the current tick, ``None`` when unpriceable."""
    tick = mt5.symbol_info_tick(name)
    if tick is None:
        return None
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    last = float(getattr(tick, "last", 0.0) or 0.0)
    return last if last > 0 else None


def _usd_contract_value(mt5: Any, cfg: MT5Config, name: str, lots: float) -> float | None:
    """USD value of ``lots`` of broker symbol ``name``, ``None`` on any failure.

    1 lot == ``trade_contract_size`` units of the base currency. Quote-USD
    pairs price via the tick mid; base-USD pairs are exact; crosses convert
    the base through its ``<BASE>USD``/``USD<BASE>`` pair when the broker
    offers one (suffix-aware). Unresolvable → ``None`` (fail-closed).
    """
    info = mt5.symbol_info(name)
    if info is None:
        return None
    size = float(getattr(info, "trade_contract_size", 0.0) or 0.0)
    if size <= 0 or lots <= 0:
        return None
    base = str(getattr(info, "currency_base", "") or "").upper()
    profit = str(getattr(info, "currency_profit", "") or "").upper()
    if base == "USD":
        return lots * size
    if profit == "USD":
        mid = _tick_mid(mt5, name)
        return lots * size * mid if mid is not None else None
    # Cross: convert the base currency through a USD pair.
    direct_candidates = [base + "USD" + cfg.symbol_suffix, base + "USD"] if cfg.symbol_suffix else [base + "USD"]
    for conv in direct_candidates:
        if mt5.symbol_info(conv) is not None:
            mid = _tick_mid(mt5, conv)
            return lots * size * mid if mid is not None else None
    inverse_candidates = ["USD" + base + cfg.symbol_suffix, "USD" + base] if cfg.symbol_suffix else ["USD" + base]
    for conv in inverse_candidates:
        if mt5.symbol_info(conv) is not None:
            mid = _tick_mid(mt5, conv)
            return lots * size / mid if mid else None
    return None
