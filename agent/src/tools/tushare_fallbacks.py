"""Optional Tushare fallback adapters for China-market flow tools.

The public Eastmoney endpoints are free and remain the primary source for these
tools.  When they are unavailable, a configured Tushare token can recover the
same research workflow through a separate provider with a compatible envelope.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.config.accessor import get_env_config

_TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}


class TushareFallbackUnavailable(RuntimeError):
    """Raised when the optional Tushare fallback cannot be used."""


def _pro_api() -> Any:
    token = get_env_config().data.tushare_token.strip()
    if token in _TUSHARE_TOKEN_PLACEHOLDERS:
        raise TushareFallbackUnavailable("TUSHARE_TOKEN is not configured")
    try:
        import tushare as ts
    except Exception as exc:  # noqa: BLE001 - import errors vary by install
        raise TushareFallbackUnavailable(f"tushare import failed: {exc}") from exc
    return ts.pro_api(token)


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if bool(getattr(frame, "empty", False)):
        return []
    if hasattr(frame, "to_dict"):
        rows = frame.to_dict("records")
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(frame, list):
        return [row for row in frame if isinstance(row, dict)]
    return []


def _compact_date(value: str) -> str:
    digits = str(value).strip().replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        raise TushareFallbackUnavailable(f"invalid date for tushare fallback: {value!r}")
    return digits


def _dashed_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = str(value).strip().replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return str(value)[:10] if value else None


def _date_window(days: int) -> tuple[str, str]:
    end = date.today()
    # Market holidays/weekends mean calendar days need slack to recover the
    # requested number of trading rows.
    start = end - timedelta(days=max(days * 3, 10))
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _to_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _net_amount(row: dict[str, Any], buy_key: str, sell_key: str) -> float | None:
    buy = _to_float(row.get(buy_key))
    sell = _to_float(row.get(sell_key))
    if buy is None and sell is None:
        return None
    # Tushare moneyflow amount fields are in 10k CNY; the Eastmoney tool emits
    # CNY, so convert to keep the existing bucket units.
    return ((buy or 0.0) - (sell or 0.0)) * 10_000


def _ts_code(code: str) -> str:
    token = code.strip().upper()
    if "." in token:
        bare, suffix = token.split(".", 1)
        if suffix in {"SH", "SZ", "BJ"} and len(bare) == 6 and bare.isdigit():
            return f"{bare}.{suffix}"
        raise TushareFallbackUnavailable(f"unsupported Tushare symbol: {code}")
    for prefix in ("SH", "SZ", "BJ"):
        if token.startswith(prefix):
            token = token[len(prefix) :]
            break
    if len(token) != 6 or not token.isdigit():
        raise TushareFallbackUnavailable(f"unsupported Tushare symbol: {code}")
    if token.startswith(("5", "6", "9")):
        suffix = "SH"
    elif token.startswith(("0", "2", "3")):
        suffix = "SZ"
    elif token.startswith(("4", "8")):
        suffix = "BJ"
    else:
        raise TushareFallbackUnavailable(f"unsupported Tushare symbol: {code}")
    return f"{token}.{suffix}"


def fetch_fund_flow(symbol: str, *, days: int) -> dict[str, Any]:
    ts_code = _ts_code(symbol)
    start_date, end_date = _date_window(days)
    rows = _records(
        _pro_api().moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
    )
    parsed: list[dict[str, Any]] = []
    for row in rows:
        parsed.append(
            {
                "timestamp": _dashed_date(row.get("trade_date")),
                "main": (_to_float(row.get("net_mf_amount")) or 0.0) * 10_000,
                "small": _net_amount(row, "buy_sm_amount", "sell_sm_amount"),
                "medium": _net_amount(row, "buy_md_amount", "sell_md_amount"),
                "large": _net_amount(row, "buy_lg_amount", "sell_lg_amount"),
                "super_large": _net_amount(row, "buy_elg_amount", "sell_elg_amount"),
            }
        )
    parsed.sort(key=lambda item: item.get("timestamp") or "")
    parsed = parsed[-days:]
    return {"symbol": symbol, "ts_code": ts_code, "source": "tushare", "rows": parsed}


def fetch_dragon_tiger(trade_date: str, code: str | None) -> dict[str, Any]:
    compact = _compact_date(trade_date)
    ts_code = _ts_code(code) if code else None
    pro = _pro_api()
    kwargs: dict[str, str] = {"trade_date": compact}
    if ts_code:
        kwargs["ts_code"] = ts_code
    appearances_raw = _records(pro.top_list(**kwargs))
    appearances = [
        {
            "code": str(row.get("ts_code", "")).split(".", 1)[0] or None,
            "name": row.get("name"),
            "close": row.get("close"),
            "change_pct": row.get("pct_change"),
            "net_buy": row.get("net_amount"),
            "buy_amount": row.get("l_buy"),
            "sell_amount": row.get("l_sell"),
            "turnover": row.get("amount"),
            "reason": row.get("reason"),
        }
        for row in appearances_raw
    ]

    data: dict[str, Any] = {
        "date": _dashed_date(compact),
        "count": len(appearances_raw),
        "appearances": appearances,
    }
    if ts_code:
        seats_raw = _records(pro.top_inst(trade_date=compact, ts_code=ts_code))
        data["code"] = ts_code.split(".", 1)[0]
        data["seats"] = [
            {
                "seat": row.get("exalter"),
                "side": row.get("side"),
                "buy": row.get("buy"),
                "sell": row.get("sell"),
                "net": row.get("net_buy"),
                "rank": None,
            }
            for row in seats_raw
        ]
    return data


def fetch_northbound_flow(*, lookback_days: int) -> dict[str, Any]:
    start_date, end_date = _date_window(lookback_days)
    rows = _records(_pro_api().moneyflow_hsgt(start_date=start_date, end_date=end_date))
    history: list[dict[str, Any]] = []
    for row in rows:
        shanghai = _to_float(row.get("hgt"))
        shenzhen = _to_float(row.get("sgt"))
        total = _to_float(row.get("north_money"))
        history.append(
            {
                "trade_date": _dashed_date(row.get("trade_date")),
                "shanghai_connect": shanghai * 100 if shanghai is not None else None,
                "shenzhen_connect": shenzhen * 100 if shenzhen is not None else None,
                "total": total * 100 if total is not None else None,
            }
        )
    history.sort(key=lambda item: item.get("trade_date") or "")
    history = history[-lookback_days:]
    latest = history[-1] if history else {}
    return {
        "unit": "10k CNY",
        "lookback_days": lookback_days,
        "realtime": {
            "shanghai_connect": latest.get("shanghai_connect"),
            "shenzhen_connect": latest.get("shenzhen_connect"),
            "total": latest.get("total"),
        },
        "history": history,
    }


def fetch_margin_trading(code: str, *, days: int) -> dict[str, Any]:
    ts_code = _ts_code(code)
    start_date, end_date = _date_window(days)
    rows = _records(
        _pro_api().margin_detail(ts_code=ts_code, start_date=start_date, end_date=end_date)
    )
    normalized = [
        {
            "trade_date": _dashed_date(row.get("trade_date")),
            "financing_balance": _to_float(row.get("rzye")),
            "financing_buy": _to_float(row.get("rzmre")),
            "financing_repay": _to_float(row.get("rzche")),
            "short_balance": _to_float(row.get("rqye")),
            "short_volume": _to_float(row.get("rqyl")),
            "margin_total_balance": _to_float(row.get("rzrqye")),
        }
        for row in rows
    ]
    normalized.sort(key=lambda item: item.get("trade_date") or "", reverse=True)
    return {"code": ts_code.split(".", 1)[0], "ts_code": ts_code, "rows": normalized[:days]}
