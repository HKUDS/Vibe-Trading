"""Config resolution and the signed HTTP client for the Exness Trader API.

Host model: the per-user Gateway URL (Key Management DNS widget) resolves the
account's Access Point once (``GET /v1/trading/access-point``); every account
call and WebSocket handshake then goes to that Access Point. Both hosts are
pinned to ``https`` Exness domains and redirects are never followed, so signed
headers cannot be forwarded to a third party.

Retry policy: none. A 429 surfaces ``retry_after`` to the caller and mutations
are never re-sent automatically — the caller re-submits with the SAME
idempotency key if it wants an exactly-once retry.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlsplit

import requests

from src.config.accessor import get_env_config
from src.config.paths import get_runtime_root
from src.tools.redaction import redact_text
from src.trading.connectors.exness._signing import ExnessKeyError, build_headers, load_private_key

CONFIG_FILENAME = "exness.json"
#: Recorded in every payload: there is no paper path to separate, so every
#: profile is live and writes are mandate-gated.
GUARD_MARKER = "live_only_no_paper_environment"
PROFILE_ENVIRONMENTS = {"live-readonly": "live", "live": "live"}
TRUSTED_HOST_SUFFIXES = ("exness.com", "exness-api.com")
USER_AGENT = "vibe-trading-exness-connector/1"
ACCESS_POINT_PATH = "/v1/trading/access-point"
_ERROR_TEXT_LIMIT = 200
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MAX_READ_RETRY_WAIT_SECONDS = 2.0
_sleep = time.sleep
MAX_OPERATION_WAIT_SECONDS = 30.0
DEFAULT_DEVIATION_POINTS = 10
MAX_DEVIATION_POINTS = 1000

Transport = Callable[..., Any]


class ExnessConfigError(RuntimeError):
    """Connector configuration is missing, invalid or points at an untrusted host."""


class ExnessAPIError(RuntimeError):
    """The Exness API (or the network) returned an error.

    Attributes:
        status: HTTP status (``None`` for network errors).
        code: Exness numeric error code when the body carried one.
        error_message: Exness stable error name (e.g. ``AUTH_PERMISSION_DENIED``).
        retry_after: Seconds to wait when the server sent ``Retry-After``.
    """

    def __init__(self, message: str, *, status: int | None = None, code: int | None = None,
                 error_message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.error_message = error_message
        self.retry_after = retry_after


@dataclass(frozen=True)
class ExnessConfig:
    """Exness Trader API connection settings.

    Args:
        api_key: ``exnsk-…`` key id from Key Management.
        private_key: Ed25519 signing key (128 hex chars or unencrypted PKCS#8 PEM).
        account_id: Numeric trading account id the key is scoped to.
        gateway_url: Per-user Gateway base URL from the Key Management DNS widget.
        profile: ``live-readonly`` or ``live``. There is no paper profile.
        timeout: Network timeout in seconds.
        max_order_volume: Connector-level cap on lots per order (defense in depth).
        max_order_notional_usd: Connector-level USD cap per order; unpriceable → refused.
        operation_wait_seconds: How long ``place_order`` polls the async operation status.
        deviation_points: Max slippage (instrument points) accepted on instant-execution
            instruments; beyond it Exness requotes instead of filling worse.
    """

    api_key: str = field(default="", repr=False)
    private_key: str = field(default="", repr=False)
    account_id: str = field(default="", repr=False)
    gateway_url: str = ""
    profile: str = "live-readonly"
    timeout: float = 15.0
    max_order_volume: float = 1.0
    max_order_notional_usd: float = 10_000.0
    operation_wait_seconds: float = 5.0
    deviation_points: int = DEFAULT_DEVIATION_POINTS

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "ExnessConfig":
        """Build a config from a JSON-like mapping, validating profile and account id.

        Raises:
            ExnessConfigError: Unknown profile or non-numeric ``account_id``.
        """
        payload = dict(data or {})
        profile = str(payload.get("profile") or "live-readonly").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise ExnessConfigError("profile must be 'live-readonly' or 'live' (Exness has no paper environment)")
        account_id = str(payload.get("account_id") or "").strip()
        if account_id and not account_id.isdigit():
            raise ExnessConfigError("account_id must be the numeric Exness trading account id")
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            private_key=str(payload.get("private_key") or "").strip(),
            account_id=account_id,
            gateway_url=str(payload.get("gateway_url") or "").strip().rstrip("/"),
            profile=profile,
            timeout=_positive(payload.get("timeout"), 15.0),
            max_order_volume=_positive(payload.get("max_order_volume"), 1.0),
            max_order_notional_usd=_positive(payload.get("max_order_notional_usd"), 10_000.0),
            operation_wait_seconds=min(MAX_OPERATION_WAIT_SECONDS,
                                       max(0.0, float(payload.get("operation_wait_seconds", 5.0) or 0.0))),
            deviation_points=_deviation(payload.get("deviation_points")),
        )

    @property
    def environment(self) -> str:
        """Always ``live``: the API has no paper environment."""
        return PROFILE_ENVIRONMENTS[self.profile]

    @property
    def is_readonly(self) -> bool:
        """Whether this config's profile forbids order entry."""
        return self.profile != "live"


def _deviation(value: Any) -> int:
    """Validate ``deviation_points``: a whole number in 1..MAX (fail closed, never silently widened)."""
    if value is None or value == "":
        return DEFAULT_DEVIATION_POINTS
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if not (1 <= number <= MAX_DEVIATION_POINTS) or number != int(number):
        raise ExnessConfigError(f"deviation_points must be a whole number between 1 and {MAX_DEVIATION_POINTS}")
    return int(number)


def _positive(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


#: Per-call overrides arrive from MCP tool arguments / REST bodies. Only the
#: confirmation wait (capped at ``MAX_OPERATION_WAIT_SECONDS``) is accepted:
#: credentials, account, hosts, profile and slippage come only from the user's
#: file, env or OS vault, never from a model-supplied argument.
_OVERRIDE_KEYS: tuple[str, ...] = ("operation_wait_seconds",)


def _environment_values() -> dict[str, str]:
    data = get_env_config().data
    return {
        "api_key": str(data.exness_api_key or "").strip(),
        "private_key": str(data.exness_private_key or "").strip(),
        "account_id": str(data.exness_account_id or "").strip(),
        "gateway_url": str(data.exness_gateway_url or "").strip(),
    }


def config_path():
    """Return the user-level Exness config path (``~/.vibe-trading/exness.json``)."""
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> ExnessConfig:
    """Load settings from ``exness.json`` overlaid with ``EXNESS_*`` env values."""
    path = config_path()
    base: dict[str, Any] = {}
    if path.exists():
        try:
            base = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExnessConfigError(f"invalid Exness config at {path}: {type(exc).__name__}") from None
        if not isinstance(base, dict):
            raise ExnessConfigError(f"invalid Exness config at {path}: expected a JSON object")
    for key, value in _environment_values().items():
        if value:
            base[key] = value
    return ExnessConfig.from_mapping(base)


def save_config(config: ExnessConfig):
    """Persist settings with owner-only permissions; returns the path."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def build_config(profile_config: Mapping[str, Any] | None = None,
                 overrides: Mapping[str, Any] | None = None) -> ExnessConfig:
    """Resolve config: saved file/env ← profile defaults (caller overrides are dropped)."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    clean = {k: v for k, v in dict(overrides or {}).items() if k in _OVERRIDE_KEYS and v not in (None, "")}
    base.update(clean)
    return ExnessConfig.from_mapping(base)


def _missing_fields(cfg: ExnessConfig) -> list[str]:
    return [name for name in ("api_key", "private_key", "account_id", "gateway_url") if not getattr(cfg, name)]


def missing_credential_code(cfg: ExnessConfig) -> str:
    """``credentials_partial`` when some fields are set, else ``credentials_missing``."""
    return "credentials_partial" if len(_missing_fields(cfg)) < 4 else "credentials_missing"


def credential_source() -> str | None:
    """Where credentials come from (``environment`` / ``runtime_file``) for runtime UI metadata."""
    if any(_environment_values().values()):
        return "environment"
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(data, dict) and any(str(data.get(k) or "").strip() for k in ("api_key", "private_key")):
            return "runtime_file"
    return None


def public_config(cfg: ExnessConfig) -> dict[str, Any]:
    """Config safe to return to callers: booleans for secrets, no account id."""
    return {
        "profile": cfg.profile,
        "environment": cfg.environment,
        "readonly": cfg.is_readonly,
        "timeout": cfg.timeout,
        "api_key_configured": bool(cfg.api_key),
        "private_key_configured": bool(cfg.private_key),
        "account_configured": bool(cfg.account_id),
        "gateway_configured": bool(cfg.gateway_url),
        "max_order_volume": cfg.max_order_volume,
        "max_order_notional_usd": cfg.max_order_notional_usd,
        "deviation_points": cfg.deviation_points,
        "guard": GUARD_MARKER,
    }


def new_idempotency_key() -> str:
    """Fresh ``EXN-IDEMPOTENCY-KEY`` (``vt-`` + 32 hex chars; within the 5–128 charset rule)."""
    return f"vt-{uuid.uuid4().hex}"


def trusted_base_url(url: str, *, label: str) -> str:
    """Return ``scheme://host`` when ``url`` is an https Exness host, else raise.

    Raises:
        ExnessConfigError: Non-https scheme, userinfo, or a host outside
            ``TRUSTED_HOST_SUFFIXES``.
    """
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower()
    trusted = any(host == suffix or host.endswith("." + suffix) for suffix in TRUSTED_HOST_SUFFIXES)
    if parts.scheme != "https" or not host or parts.username or parts.password or not trusted:
        raise ExnessConfigError(f"{label} must be an https:// URL on an Exness domain ({', '.join(TRUSTED_HOST_SUFFIXES)})")
    return f"https://{parts.netloc.lower()}"


#: Discovery is rate limited (``AUTH_RATE_LIMIT``) and every CLI command is a
#: new process, so the resolved host is also kept on disk for a few hours.
#: The file holds only host names (no credentials) and every entry is
#: re-validated against ``TRUSTED_HOST_SUFFIXES`` on load.
ACCESS_POINT_CACHE_FILENAME = "exness-access-point.json"
ACCESS_POINT_TTL_SECONDS = 6 * 3600
_ACCESS_POINT_CACHE: dict[tuple[str, str], str] = {}


def reset_access_point_cache() -> None:
    """Forget in-process resolved Access Points (tests; or after a key/account change)."""
    _ACCESS_POINT_CACHE.clear()


def _disk_cache_path():
    return get_runtime_root() / ACCESS_POINT_CACHE_FILENAME


def _read_disk_cache() -> dict[str, Any]:
    try:
        data = json.loads(_disk_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cached_access_point(gateway: str, account_id: str) -> str | None:
    entry = _read_disk_cache().get(f"{gateway}|{account_id}")
    if not isinstance(entry, dict):
        return None
    try:
        age = time.time() - float(entry.get("resolved_at") or 0)
        base = trusted_base_url(str(entry.get("access_point") or ""), label="access point")
    except (TypeError, ValueError, ExnessConfigError):
        return None
    return base if 0 <= age < ACCESS_POINT_TTL_SECONDS else None


def _store_access_point(gateway: str, account_id: str, base: str) -> None:
    data = _read_disk_cache()
    data[f"{gateway}|{account_id}"] = {"access_point": base, "resolved_at": time.time()}
    path = _disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass  # best effort: the in-process cache still applies


class ExnessClient:
    """Signed REST client bound to one config. ``transport`` is injectable for tests."""

    def __init__(self, cfg: ExnessConfig, transport: Transport | None = None) -> None:
        self.cfg = cfg
        self._transport = transport or requests.request
        self._key = None

    # -- public verbs -------------------------------------------------------

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """Signed GET against the account's Access Point."""
        return self._send("GET", path, params=params)

    def post(self, path: str, body: Mapping[str, Any], *, idempotency_key: str) -> Any:
        """Signed POST (mutation; requires a non-empty idempotency key)."""
        return self._send("POST", path, body=body, idempotency_key=_require_key(idempotency_key))

    def patch(self, path: str, body: Mapping[str, Any], *, idempotency_key: str) -> Any:
        """Signed PATCH (mutation)."""
        return self._send("PATCH", path, body=body, idempotency_key=_require_key(idempotency_key))

    def delete(self, path: str, params: Mapping[str, Any] | None = None, *, idempotency_key: str) -> Any:
        """Signed DELETE (mutation)."""
        return self._send("DELETE", path, params=params, idempotency_key=_require_key(idempotency_key))

    def account_path(self, section: str, *parts: str) -> str:
        """``/v1/<section>/accounts/<account_id>[/parts…]``.

        The account id is validated numeric at config time; each extra segment
        (instrument names, order/position ids — some server-provided) must match
        the API's ``[A-Za-z0-9._-]`` identifier shape and may not be ``.``/``..``.

        Raises:
            ExnessAPIError: A segment could alter the request path.
        """
        for part in parts:
            if not _SAFE_SEGMENT_RE.match(part) or part in (".", ".."):
                raise ExnessAPIError(f"refusing unsafe path segment {part[:40]!r}")
        tail = "".join(f"/{p}" for p in parts)
        return f"/v1/{section}/accounts/{self.cfg.account_id}{tail}"

    # -- internals ------------------------------------------------------------

    def _signing_key(self):
        if self._key is None:
            try:
                self._key = load_private_key(self.cfg.private_key)
            except ExnessKeyError as exc:
                raise ExnessConfigError(str(exc)) from None
        return self._key

    def _access_point(self) -> str:
        gateway = trusted_base_url(self.cfg.gateway_url, label="gateway_url")
        cache_key = (gateway, self.cfg.account_id)
        cached = _ACCESS_POINT_CACHE.get(cache_key) or _cached_access_point(gateway, self.cfg.account_id)
        if cached:
            _ACCESS_POINT_CACHE[cache_key] = cached
            return cached
        payload =self._request(gateway, "GET", ACCESS_POINT_PATH, params={"account_id": self.cfg.account_id})
        raw = payload.get("access_point") if isinstance(payload, dict) else None
        try:
            base = trusted_base_url(str(raw or ""), label="access point")
        except ExnessConfigError:
            raise ExnessAPIError("discovered access point is not an https Exness host; refusing to use it") from None
        _ACCESS_POINT_CACHE[cache_key] = base
        _store_access_point(gateway, self.cfg.account_id, base)
        return base

    def _send(self, method: str, path: str, *, params: Mapping[str, Any] | None = None,
              body: Mapping[str, Any] | None = None, idempotency_key: str = "") -> Any:
        missing = _missing_fields(self.cfg)
        if missing:
            raise ExnessConfigError(f"Exness connector not configured: missing {', '.join(missing)}")
        trusted_base_url(self.cfg.gateway_url, label="gateway_url")
        self._signing_key()
        return self._request(self._access_point(), method, path, params=params, body=body,
                             idempotency_key=idempotency_key)

    def _request(self, base: str, method: str, path: str, *, params: Mapping[str, Any] | None = None,
                 body: Mapping[str, Any] | None = None, idempotency_key: str = "") -> Any:
        query = urlencode([(k, v) for k, v in dict(params or {}).items() if v is not None])
        target = path + (f"?{query}" if query else "")
        raw_body = b"" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        try:
            return self._signed_call(base, method, target, raw_body, idempotency_key)
        except ExnessAPIError as exc:
            # One bounded retry, reads only: a GET is side-effect free, and the
            # per-endpoint limits are per second. Mutations are never re-sent.
            wait = exc.retry_after if exc.retry_after is not None else 1.0
            if method != "GET" or exc.status != 429 or wait > _MAX_READ_RETRY_WAIT_SECONDS:
                raise
            _sleep(max(0.0, wait))
            return self._signed_call(base, method, target, raw_body, idempotency_key)

    def _signed_call(self, base: str, method: str, target: str, raw_body: bytes, idempotency_key: str) -> Any:
        headers = build_headers(
            method=method, path=target, body=raw_body, api_key=self.cfg.api_key,
            private_key=self._signing_key(), idempotency_key=idempotency_key,
            timestamp_ms=int(time.time() * 1000),
        )
        headers["Accept"] = "application/json"
        headers["User-Agent"] = USER_AGENT
        try:
            response = self._transport(method, base + target, headers=headers, data=raw_body or None,
                                       timeout=self.cfg.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise ExnessAPIError(f"network error: {type(exc).__name__}") from None
        return _parse_response(response)


def _require_key(idempotency_key: str) -> str:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("mutating Exness requests require a non-empty idempotency key")
    return key


def _parse_response(response: Any) -> Any:
    status = int(getattr(response, "status_code", 0) or 0)
    if 300 <= status < 400:
        raise ExnessAPIError(f"HTTP {status}: redirect refused (signed requests are never forwarded)", status=status)
    if status >= 400:
        code, name, detail = _error_fields(response)
        retry_after = _retry_after(response)
        message = f"HTTP {status}: {name or detail}" + (f" (code {code})" if code is not None else "")
        raise ExnessAPIError(message, status=status, code=code, error_message=name, retry_after=retry_after)
    if not getattr(response, "content", b""):
        return {}
    try:
        return response.json()
    except ValueError:
        raise ExnessAPIError(f"HTTP {status}: invalid JSON response", status=status) from None


def _error_fields(response: Any) -> tuple[int | None, str, str]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        code = payload.get("code")
        name = str(payload.get("error_message") or "").strip()
        description = redact_text(str(payload.get("description") or ""))
        return (int(code) if isinstance(code, int) else None), name[:_ERROR_TEXT_LIMIT], description[:_ERROR_TEXT_LIMIT]
    text = redact_text(str(getattr(response, "text", "") or "").strip())[:_ERROR_TEXT_LIMIT]
    return None, "", f"non-JSON response (possibly an edge/WAF block): {text}"


def _retry_after(response: Any) -> float | None:
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    if raw is None:
        try:
            body = response.json()
            raw = body.get("retry_after") if isinstance(body, dict) else None
        except ValueError:
            raw = None
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _build_default_client(cfg: ExnessConfig) -> ExnessClient:
    return ExnessClient(cfg)


_client_factory: Callable[[ExnessConfig], ExnessClient] = _build_default_client


def make_client(cfg: ExnessConfig) -> ExnessClient:
    """Build the REST client for ``cfg`` (tests override via :func:`set_client_factory`)."""
    return _client_factory(cfg)


def set_client_factory(factory: Callable[[ExnessConfig], ExnessClient] | None = None) -> None:
    """Override or reset the client factory (unit-test seam)."""
    global _client_factory
    _client_factory = factory or _build_default_client
