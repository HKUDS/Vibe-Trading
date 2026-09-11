"""Read-only + genuine-paper KIS connector via the official REST API.

Wraps Korea Investment & Securities' (한국투자증권) KIS Developers REST API for
account balance, positions, order history, quotes, and historical bars, plus
order placement/cancellation in the paper profile. No third-party SDK is
required — ``requests`` only, following the public API guide at
https://apiportal.koreainvestment.com and the official example repo
https://github.com/koreainvestment/open-trading-api.

Paper-vs-live is a REAL structural guard: paper (모의투자) and live (실전투자)
accounts are reached through entirely different hosts/ports, each issuing its
own OAuth token scoped to that host. A paper-declared config can therefore
never place an order against the live host — unlike Dhan/Upbit, this is not
an operator-trust convention, it is enforced by which URL the request goes to.

Caveat: TR_ID codes and field names below were sourced from the official KIS
example repository and public documentation, not verified against a live KIS
account (this connector was authored without KIS credentials). Verify against
https://apiportal.koreainvestment.com before relying on this in production.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import requests

from src.config.paths import get_runtime_root

#: KIS dates (order history, chart ranges) are Korea Standard Time, not the
#: machine's local clock.
_KST = ZoneInfo("Asia/Seoul")


def _kst_today() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")

CONFIG_FILENAME = "kis.json"

PROFILE_ENVIRONMENTS = {
    "paper": "paper",
    "live-readonly": "live",
}

#: Real per-environment hosts (the structural paper/live discriminator).
BASE_URLS = {
    "paper": "https://openapivts.koreainvestment.com:29443",
    "live": "https://openapi.koreainvestment.com:9443",
}

#: TR_ID transaction codes, per KIS Developers docs. Price/chart codes are
#: shared across both environments; trading codes are environment-specific.
_TR_BALANCE = {"paper": "VTTC8434R", "live": "TTTC8434R"}
_TR_ORDER_BUY = {"paper": "VTTC0012U", "live": "TTTC0012U"}
_TR_ORDER_SELL = {"paper": "VTTC0011U", "live": "TTTC0011U"}
_TR_ORDER_CANCEL = {"paper": "VTTC0013U", "live": "TTTC0013U"}
_TR_DAILY_CCLD = {"paper": "VTTC0081R", "live": "TTTC0081R"}
_TR_PRICE = "FHKST01010100"
_TR_CHART = "FHKST03010100"

#: KRX market division code used by every quotations call.
_MARKET_DIV_KRX = "J"
#: Exchange id division code required by order-cash since the 2024 API rev.
_EXCHANGE_ID_KRX = "KRX"

#: Safety margin subtracted from the token's reported TTL before it is
#: treated as expired, so a request never races an in-flight expiry.
_TOKEN_REFRESH_MARGIN_SECONDS = 120

#: Fallback token TTL when KIS's token response omits ``expires_in`` (should
#: not happen per the docs, but re-issuing on every call would blow through
#: KIS's once-per-minute token rate limit if it ever does).
_DEFAULT_TOKEN_TTL_SECONDS = 3600.0

#: Returned by order methods for any non-paper config. KIS's host separation
#: means live order placement is technically reachable, but this connector
#: deliberately does not wire a mandate-gated live-trade profile yet.
_LIVE_ORDER_ERROR = (
    "KIS live order placement is not wired in this connector yet (no "
    "kis-live-trade profile exists); use a kis-paper-* profile."
)

#: Safety cap on KIS's tr_cont continuation loop so a misbehaving or
#: adversarial response cannot page forever.
_MAX_CONTINUATION_PAGES = 20


class KISConfigError(RuntimeError):
    """Raised when the connector configuration is missing or invalid."""


class KISAPIError(RuntimeError):
    """Raised when KIS returns an auth, HTTP, network, or JSON error."""


@dataclass(frozen=True)
class KISConfig:
    """KIS connector connection settings.

    Args:
        app_key: KIS Developers App Key.
        app_secret: KIS Developers App Secret.
        account_no: 8-digit account number (CANO), e.g. ``"12345678"``.
        account_product_code: 2-digit account product code (ACNT_PRDT_CD),
            e.g. ``"01"``.
        profile: ``paper`` or ``live-readonly``.
        timeout: Network timeout in seconds.
        readonly: Whether order placement is disabled.
    """

    app_key: str = ""
    app_secret: str = ""
    account_no: str = ""
    account_product_code: str = "01"
    profile: str = "paper"
    timeout: float = 15.0
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "KISConfig":
        """Build a config from a JSON-like mapping."""
        payload = dict(data or {})
        profile = str(payload.get("profile") or "paper").strip().lower()
        if profile not in PROFILE_ENVIRONMENTS:
            raise KISConfigError("profile must be 'paper' or 'live-readonly'")
        return cls(
            app_key=str(payload.get("app_key") or "").strip(),
            app_secret=str(payload.get("app_secret") or "").strip(),
            account_no=str(payload.get("account_no") or "").strip(),
            account_product_code=str(payload.get("account_product_code") or "01").strip(),
            profile=profile,
            timeout=float(payload.get("timeout") or 15.0),
            readonly=bool(payload.get("readonly", True)),
        )

    def with_overrides(
        self,
        *,
        app_key: str | None = None,
        app_secret: str | None = None,
        account_no: str | None = None,
        account_product_code: str | None = None,
        profile: str | None = None,
    ) -> "KISConfig":
        """Return a copy with CLI/tool overrides applied."""
        payload = asdict(self)
        if app_key is not None:
            payload["app_key"] = app_key
        if app_secret is not None:
            payload["app_secret"] = app_secret
        if account_no is not None:
            payload["account_no"] = account_no
        if account_product_code is not None:
            payload["account_product_code"] = account_product_code
        if profile is not None:
            payload["profile"] = profile
        return KISConfig.from_mapping(payload)

    @property
    def environment(self) -> str:
        return PROFILE_ENVIRONMENTS.get(self.profile, "paper")

    @property
    def is_paper(self) -> bool:
        return self.environment == "paper"

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.environment]


#: ``profile`` is deliberately excluded: a per-call override could otherwise
#: flip a paper-declared profile to the live host/TR_ID without the service
#: layer noticing (see the structural guard in place_order/cancel_order below).
_OVERRIDE_KEYS = ("app_key", "app_secret", "account_no", "account_product_code")


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> "KISConfig":
    """Resolve config: saved file ← profile defaults ← CLI overrides."""
    base = asdict(load_config())
    for key, value in dict(profile_config or {}).items():
        if value is not None:
            base[key] = value
    cfg = KISConfig.from_mapping(base)
    clean = {
        k: v
        for k, v in dict(overrides or {}).items()
        if k in _OVERRIDE_KEYS and v not in (None, "")
    }
    return cfg.with_overrides(**clean) if clean else cfg


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> KISConfig:
    path = config_path()
    if not path.exists():
        return KISConfig()
    try:
        return KISConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise KISConfigError(f"invalid KIS config at {path}: {exc}") from exc


def save_config(config: KISConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


# ---------------------------------------------------------------------------
# Five read operations + order placement (paper only)
# ---------------------------------------------------------------------------


def check_status(config: KISConfig | None = None) -> dict[str, Any]:
    """Check REST readiness and config completeness without mutating broker state."""
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "requests", "installed": True},
        "host": cfg.base_url,
    }

    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"KIS connector not configured: missing {', '.join(missing)}."
        return report

    try:
        get_account_snapshot(cfg)  # connectivity probe; result unused
    except (KISConfigError, KISAPIError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report

    report["account"] = {"profile": cfg.profile, "is_paper": cfg.is_paper}
    return report


def get_account_snapshot(config: KISConfig | None = None) -> dict[str, Any]:
    """Fetch cash/valuation summary (account.summary, ``output2``) for the account."""
    cfg = config or load_config()
    payload = _balance(cfg)
    summary = _first_row(payload.get("output2"))

    return {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "host": cfg.base_url,
        "account": {
            "currency": "KRW",
            "cash": _as_float(summary.get("dnca_tot_amt")),
            "settlement_cash": _as_float(summary.get("prvs_rcdl_excc_amt")),
            "total_evaluation": _as_float(summary.get("tot_evlu_amt")),
            "purchase_amount": _as_float(summary.get("pchs_amt_smtl_amt")),
            "unrealized_pnl": _as_float(summary.get("evlu_pfls_smtl_amt")),
        },
    }


def get_positions(config: KISConfig | None = None) -> dict[str, Any]:
    """Fetch current KRX equity holdings (``output1``)."""
    cfg = config or load_config()
    payload = _balance(cfg)
    rows = []
    for item in _as_list(payload.get("output1")):
        quantity = _as_float(item.get("hldg_qty"))
        if quantity <= 0:
            continue
        rows.append({
            "symbol": item.get("pdno", ""),
            "name": item.get("prdt_name", ""),
            "quantity": quantity,
            "average_cost": _as_float(item.get("pchs_avg_pric")),
            "current_price": _as_float(item.get("prpr")),
            "unrealized_pnl": _as_float(item.get("evlu_pfls_amt")),
            "unrealized_pnl_rate": _as_float(item.get("evlu_pfls_rt")),
        })

    return {"status": "ok", "profile": cfg.profile, "is_paper": cfg.is_paper, "positions": rows}


def get_open_orders(
    config: KISConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    """Fetch today's orders, split into still-open vs already-executed."""
    cfg = config or load_config()
    today = _kst_today()
    payload = _get_paginated(
        cfg,
        "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        tr_id=_TR_DAILY_CCLD[cfg.environment],
        params={
            "CANO": cfg.account_no,
            "ACNT_PRDT_CD": cfg.account_product_code,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "INQR_DVSN": "00",
            "EXCG_ID_DVSN_CD": _EXCHANGE_ID_KRX,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
    )

    open_orders, executions = [], []
    for item in _as_list(payload.get("output1")):
        row = _order_to_dict(item)
        remaining = _as_float(item.get("rmn_qty"))
        if remaining > 0:
            open_orders.append(row)
        elif include_executions:
            executions.append(row)

    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "open_orders": open_orders,
    }
    if include_executions:
        result["executions"] = executions
    return result


def get_quote(symbol: str, *, config: KISConfig | None = None, **_: Any) -> dict[str, Any]:
    """Fetch the current price snapshot for a 6-digit KRX ticker."""
    cfg = config or load_config()
    ticker = str(symbol or "").strip().upper()

    try:
        payload = _get(
            cfg,
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id=_TR_PRICE,
            params={"FID_COND_MRKT_DIV_CODE": _MARKET_DIV_KRX, "FID_INPUT_ISCD": ticker},
        )
    except KISAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": ticker}

    row = payload.get("output") or {}
    return {
        "status": "ok",
        "symbol": ticker,
        "quote": {
            "last": _as_float(row.get("stck_prpr")),
            "open": _as_float(row.get("stck_oprc")),
            "high": _as_float(row.get("stck_hgpr")),
            "low": _as_float(row.get("stck_lwpr")),
            "prev_close": _as_float(row.get("stck_sdpr")),
            "change_rate": _as_float(row.get("prdy_ctrt")),
            "volume": _as_float(row.get("acml_vol")),
        },
    }


def get_historical_bars(
    symbol: str,
    *,
    config: KISConfig | None = None,
    period: str = "1d",
    limit: int = 100,
) -> dict[str, Any]:
    """Fetch daily/weekly/monthly OHLCV bars for a 6-digit KRX ticker.

    ``period`` tokens: ``1d``/``1D`` → daily, ``1w`` → weekly, ``1M`` →
    monthly. Intraday periods are not exposed by this endpoint and fail
    closed instead of silently substituting daily bars.
    """
    cfg = config or load_config()
    ticker = str(symbol or "").strip().upper()
    token = period.strip()
    period_code = {"1d": "D", "1D": "D", "1w": "W", "1M": "M"}.get(token)
    if period_code is None:
        return {
            "status": "error",
            "error": f"unsupported period: {period!r}; supported: ['1d', '1w', '1M']",
            "symbol": ticker,
        }

    end = _kst_today()
    try:
        payload = _get(
            cfg,
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id=_TR_CHART,
            params={
                "FID_COND_MRKT_DIV_CODE": _MARKET_DIV_KRX,
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": "19900101",
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": period_code,
                "FID_ORG_ADJ_PRC": "0",
            },
        )
    except KISAPIError as exc:
        return {"status": "error", "error": str(exc), "symbol": ticker}

    bars = [_bar_to_dict(item) for item in reversed(_as_list(payload.get("output2")))]
    capped = max(int(limit), 0)
    return {"status": "ok", "symbol": ticker, "period": period, "bars": bars[-capped:] if capped else []}


def place_order(
    config: KISConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Place an order against the account matching ``config``'s environment.

    Paper-vs-live is structural in two ways: the very first check refuses any
    non-paper config (this connector wires no live-trade profile yet, see
    ``_LIVE_ORDER_ERROR`), and — for the paper case that does proceed —
    :func:`_get`/:func:`_post` send the request to ``config.base_url``, the
    real KIS paper host.

    Args:
        symbol: 6-digit KRX ticker, e.g. ``"005930"``.
        side: ``buy`` or ``sell``.
        quantity: Share quantity (KIS trades whole shares only).
        order_type: ``market`` or ``limit``.
        limit_price: Required for limit orders (whole KRW won only).
    """
    cfg = config or load_config()

    # ---- HARD GUARD: no live-trade profile wired yet (must run first) ----
    if not cfg.is_paper:
        return {"status": "error", "error": _LIVE_ORDER_ERROR}

    ticker = str(symbol or "").strip().upper()
    if not ticker:
        return {"status": "error", "error": "symbol is required"}

    side_token = str(side or "").strip().lower()
    if side_token not in ("buy", "sell"):
        return {"status": "error", "error": "side must be 'buy' or 'sell'"}

    type_token = str(order_type or "").strip().lower()
    if type_token not in ("market", "limit"):
        return {"status": "error", "error": "order_type must be 'market' or 'limit'"}

    if notional is not None:
        return {"status": "error", "error": "KIS requires a share quantity; notional-based sizing is not supported"}
    if quantity is None or float(quantity) < 1:
        return {"status": "error", "error": "quantity must be a positive whole number of shares"}
    if float(quantity) != int(float(quantity)):
        return {"status": "error", "error": "quantity must be a whole number of shares"}
    qty = int(quantity)

    if type_token == "limit" and limit_price is None:
        return {"status": "error", "error": "limit order requires limit_price"}
    if type_token == "limit" and float(limit_price) != int(float(limit_price)):
        return {"status": "error", "error": "limit_price must be a whole KRW amount"}

    ord_dvsn = "00" if type_token == "limit" else "01"  # 00=지정가, 01=시장가
    unit_price = str(int(limit_price)) if type_token == "limit" else "0"
    tr_id = (_TR_ORDER_BUY if side_token == "buy" else _TR_ORDER_SELL)[cfg.environment]

    payload = _post(
        cfg,
        "/uapi/domestic-stock/v1/trading/order-cash",
        tr_id=tr_id,
        body={
            "CANO": cfg.account_no,
            "ACNT_PRDT_CD": cfg.account_product_code,
            "PDNO": ticker,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": unit_price,
            "EXCG_ID_DVSN_CD": _EXCHANGE_ID_KRX,
        },
    )

    output = payload.get("output") or {}
    return {
        "status": "ok" if str(payload.get("rt_cd")) == "0" else "error",
        "error": None if str(payload.get("rt_cd")) == "0" else str(payload.get("msg1") or "order rejected"),
        "order_id": output.get("ODNO", ""),
        "order_branch": output.get("KRX_FWDG_ORD_ORGNO", ""),
        "symbol": ticker,
        "side": side_token,
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "order_type": type_token,
        "quantity": qty,
        "limit_price": float(limit_price) if type_token == "limit" else None,
    }


def cancel_order(
    config: KISConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
    order_branch: str = "",
    quantity: float | None = None,
) -> dict[str, Any]:
    """Cancel a resting order via the KIS order-modify/cancel endpoint.

    Args:
        order_id: The broker order number (``ODNO``) from :func:`place_order`.
        order_branch: The branch code (``KRX_FWDG_ORD_ORGNO``) returned
            alongside ``order_id`` by :func:`place_order` — KIS requires it to
            identify which order to cancel. When omitted, it is looked up from
            today's order list (:func:`get_open_orders`) by ``order_id``, so a
            caller that only has the id (e.g. a later agent turn) can still
            cancel.
        quantity: Quantity to cancel; omit or ``0`` to cancel the full
            remaining quantity (``전량``).
    """
    cfg = config or load_config()

    # ---- HARD GUARD: no live-trade profile wired yet (must run first) ----
    if not cfg.is_paper:
        return {"status": "error", "error": _LIVE_ORDER_ERROR}

    clean_id = str(order_id or "").strip()
    if not clean_id:
        return {"status": "error", "error": "order_id is required"}
    if quantity is not None and 0 < float(quantity) < 1:
        return {"status": "error", "error": "quantity must be 0 (cancel all) or a whole number of shares"}

    branch = str(order_branch or "").strip()
    if not branch:
        branch = _lookup_order_branch(cfg, clean_id)
    if not branch:
        return {
            "status": "error",
            "error": (
                f"could not find order_branch (KRX_FWDG_ORD_ORGNO) for order_id "
                f"{clean_id!r} in today's order list; pass order_branch explicitly"
            ),
        }

    qty = int(float(quantity)) if quantity else 0
    payload = _post(
        cfg,
        "/uapi/domestic-stock/v1/trading/order-rvsecncl",
        tr_id=_TR_ORDER_CANCEL[cfg.environment],
        body={
            "CANO": cfg.account_no,
            "ACNT_PRDT_CD": cfg.account_product_code,
            "KRX_FWDG_ORD_ORGNO": branch,
            "ORGN_ODNO": clean_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "N" if qty else "Y",
            "EXCG_ID_DVSN_CD": _EXCHANGE_ID_KRX,
        },
    )

    ok = str(payload.get("rt_cd")) == "0"
    return {
        "status": "ok" if ok else "error",
        "error": None if ok else str(payload.get("msg1") or "cancel rejected"),
        "order_id": clean_id,
        "symbol": symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None,
        "profile": cfg.profile,
        "is_paper": cfg.is_paper,
        "cancelled": ok,
    }


# ---------------------------------------------------------------------------
# SDK plumbing
# ---------------------------------------------------------------------------


def _lookup_order_branch(cfg: KISConfig, order_id: str) -> str:
    """Resolve ``KRX_FWDG_ORD_ORGNO`` for ``order_id`` from today's order list.

    ``place_order`` returns the branch code directly, but a caller that only
    kept the order id (e.g. a later agent turn) has no other way to recover
    it, and KIS requires it to identify which order ``cancel_order`` targets.
    """
    try:
        orders = get_open_orders(cfg, include_executions=True)
    except (KISAPIError, KISConfigError):
        return ""
    for row in (*orders.get("open_orders", []), *orders.get("executions", [])):
        if str(row.get("order_id") or "") == order_id:
            return str(row.get("order_branch") or "")
    return ""


def _balance(cfg: KISConfig) -> dict[str, Any]:
    return _get_paginated(
        cfg,
        "/uapi/domestic-stock/v1/trading/inquire-balance",
        tr_id=_TR_BALANCE[cfg.environment],
        params={
            "CANO": cfg.account_no,
            "ACNT_PRDT_CD": cfg.account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
    )


def _token_cache_path(cfg: KISConfig) -> Path:
    return get_runtime_root() / f"kis-token-{cfg.environment}.json"


def _access_token(cfg: KISConfig) -> str:
    """Return a cached or freshly issued OAuth token for ``cfg``'s host.

    KIS rate-limits token issuance to once per minute, so a valid cached token
    (keyed by the configured app_key, with a safety margin before its reported
    expiry) is always preferred over a fresh call.
    """
    path = _token_cache_path(cfg)
    now = time.time()
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                cached.get("app_key") == cfg.app_key
                and float(cached.get("expires_at", 0)) > now
            ):
                return str(cached["access_token"])
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            pass

    try:
        response = requests.post(
            f"{cfg.base_url}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": cfg.app_key, "appsecret": cfg.app_secret},
            headers={"content-type": "application/json; charset=utf-8"},
            timeout=cfg.timeout,
        )
    except requests.RequestException as exc:
        raise KISAPIError(f"KIS token request failed: {exc}") from exc
    if response.status_code >= 400:
        raise KISAPIError(f"KIS token issuance returned HTTP {response.status_code}: {_error_message(response)}")

    body = response.json()
    token = str(body.get("access_token") or "")
    if not token:
        raise KISAPIError(f"KIS token issuance returned no access_token: {body}")
    expires_in = float(body.get("expires_in") or 0) or _DEFAULT_TOKEN_TTL_SECONDS

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "app_key": cfg.app_key,
            "access_token": token,
            "expires_at": now + max(expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 0),
        }),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _headers(cfg: KISConfig, tr_id: str, tr_cont: str) -> dict[str, str]:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {_access_token(cfg)}",
        "appkey": cfg.app_key,
        "appsecret": cfg.app_secret,
        "tr_id": tr_id,
        "tr_cont": tr_cont,
        "custtype": "P",
    }


def _get(cfg: KISConfig, path: str, *, tr_id: str, params: Mapping[str, Any]) -> dict[str, Any]:
    body, _headers_out = _request(cfg, "GET", path, tr_id=tr_id, params=params)
    return body


def _post(cfg: KISConfig, path: str, *, tr_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    payload, _headers_out = _request(cfg, "POST", path, tr_id=tr_id, body=body)
    return payload


def _get_paginated(
    cfg: KISConfig,
    path: str,
    *,
    tr_id: str,
    params: Mapping[str, Any],
    rows_key: str = "output1",
) -> dict[str, Any]:
    """Follow KIS's ``tr_cont`` continuation protocol, merging every page's rows.

    A response ``tr_cont`` header of ``F`` (first page, more follows) or ``M``
    (middle page, more follows) means another page exists; the client echoes
    that response's ``ctx_area_fk100``/``ctx_area_nk100`` into the next
    request and sends request header ``tr_cont: "N"`` on every call after the
    first, per the official ``inquire_balance``/``inquire_daily_ccld``
    examples. Anything else (``D``/``E``, or an absent header) is the last
    page. Capped at :data:`_MAX_CONTINUATION_PAGES` so a misbehaving response
    cannot page forever.
    """
    rows: list[Any] = []
    last_body: dict[str, Any] = {}
    tr_cont = ""
    page_params = dict(params)
    for _ in range(_MAX_CONTINUATION_PAGES):
        body, headers = _request(cfg, "GET", path, tr_id=tr_id, params=page_params, tr_cont=tr_cont)
        last_body = body
        rows.extend(_as_list(body.get(rows_key)))
        if str(headers.get("tr_cont", "")) not in ("F", "M"):
            break
        page_params = dict(params)
        page_params["CTX_AREA_FK100"] = body.get("ctx_area_fk100", "")
        page_params["CTX_AREA_NK100"] = body.get("ctx_area_nk100", "")
        tr_cont = "N"
    merged = dict(last_body)
    merged[rows_key] = rows
    return merged


def _request(
    cfg: KISConfig,
    method: str,
    path: str,
    *,
    tr_id: str,
    params: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    tr_cont: str = "",
) -> tuple[dict[str, Any], Mapping[str, str]]:
    missing = _missing_fields(cfg)
    if missing:
        raise KISConfigError(f"KIS connector not configured: missing {', '.join(missing)}.")

    try:
        response = requests.request(
            method.upper(),
            f"{cfg.base_url}{path}",
            headers=_headers(cfg, tr_id, tr_cont),
            params=dict(params or {}),
            json=dict(body) if body is not None else None,
            timeout=cfg.timeout,
        )
    except requests.RequestException as exc:
        raise KISAPIError(f"KIS request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise KISAPIError("KIS API authentication failed: check app_key/app_secret.")
    if response.status_code >= 400:
        raise KISAPIError(f"KIS API returned HTTP {response.status_code}: {_error_message(response)}")
    try:
        return response.json(), response.headers
    except ValueError as exc:
        raise KISAPIError("KIS API returned invalid JSON.") from exc


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason or "request failed"
    if isinstance(payload, Mapping):
        for key in ("msg1", "error_description", "message"):
            value = payload.get(key)
            if value:
                return str(value)
    return str(payload)


def _missing_fields(cfg: KISConfig) -> list[str]:
    missing = []
    if not cfg.app_key:
        missing.append("app_key")
    if not cfg.app_secret:
        missing.append("app_secret")
    if not cfg.account_no:
        missing.append("account_no")
    return missing


def _public_config(cfg: KISConfig) -> dict[str, Any]:
    data = asdict(cfg)
    if data.get("app_key"):
        data["app_key"] = data["app_key"][:6] + "***"
    if data.get("app_secret"):
        data["app_secret"] = "***redacted***"
    return data


def _first_row(value: Any) -> dict[str, Any]:
    rows = _as_list(value)
    return dict(rows[0]) if rows and isinstance(rows[0], Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _order_to_dict(item: Any) -> dict[str, Any]:
    return {
        "order_id": item.get("odno", ""),
        "order_branch": item.get("ord_gno_brno", ""),
        "symbol": item.get("pdno", ""),
        "name": item.get("prdt_name", ""),
        "side": "buy" if str(item.get("sll_buy_dvsn_cd_name", "")).find("매수") >= 0 else "sell",
        "order_type": item.get("ord_dvsn_name", ""),
        "quantity": _as_float(item.get("ord_qty")),
        "filled_quantity": _as_float(item.get("tot_ccld_qty")),
        "remaining_quantity": _as_float(item.get("rmn_qty")),
        "price": _as_float(item.get("ord_unpr")),
        "avg_fill_price": _as_float(item.get("avg_prvs")),
        "ordered_at": item.get("ord_tmd", ""),
    }


def _bar_to_dict(item: Any) -> dict[str, Any]:
    return {
        "time": item.get("stck_bsop_date"),
        "open": _as_float(item.get("stck_oprc")),
        "high": _as_float(item.get("stck_hgpr")),
        "low": _as_float(item.get("stck_lwpr")),
        "close": _as_float(item.get("stck_clpr")),
        "volume": _as_float(item.get("acml_vol")),
    }
