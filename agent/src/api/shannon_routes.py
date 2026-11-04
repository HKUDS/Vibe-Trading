"""Optional, read-only Shannon portfolio analysis; independent of the agent loop."""
from __future__ import annotations

from datetime import date as Date
import math

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.config.accessor import get_env_config
from src.tools.gildata_srv import call_srv_arguments


class Holding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    weight: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Date | None = None
    holdings: list[Holding] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_holdings(self):
        from backtest.loaders.gildata_loader import _is_cn_index

        if len({h.code for h in self.holdings}) != len(self.holdings):
            raise ValueError("持仓不能有重复股票 / Duplicate holdings")
        if any(_is_cn_index(h.code) for h in self.holdings):
            raise ValueError("请填写A股股票，不要填写指数 / Stocks only, not indices")
        supplied = [h.weight is not None for h in self.holdings]
        if any(supplied) and not all(supplied):
            raise ValueError("权重请全部填写，或全部留空按等权估算 / Supply all weights or none")
        if all(supplied) and not math.isclose(sum(h.weight for h in self.holdings), 1, abs_tol=1e-6):
            raise ValueError("权重合计必须为100%，不自动排除现金 / Weights must total 100%")
        return self

    def positions(self, day: str) -> list[dict]:
        return [{"date": day, "holdings": [{"code": h.code, "weight": h.weight if h.weight is not None else 1 / len(self.holdings)} for h in self.holdings]}]


def configured() -> bool:
    return get_env_config().data.gildata_token.strip() not in {"", "your-gildata-token"}


def invoke(arguments: dict) -> dict:
    if not configured():
        raise HTTPException(503, "请先配置聚源Token / Configure GILDATA_TOKEN first")
    try:
        return call_srv_arguments("ShannonAnalyze", arguments)
    except Exception:
        raise HTTPException(502, "香农分析暂不可用，请检查服务权限或稍后重试 / Shannon unavailable; check entitlement or retry") from None


def effective_date(requested: Date | None) -> str:
    if requested:
        return requested.isoformat()
    result = invoke({"intent": "catalog"})
    universes = (result.get("data") or {}).get("universes", [])
    latest = next((u.get("current_as_of") for u in universes if u.get("id") == "all" and u.get("ready")), None)
    try:
        return Date.fromisoformat(latest).isoformat()
    except (ValueError, TypeError):
        raise HTTPException(502, "暂无可用分析日期 / No published analysis date") from None


def check_dates(payload: dict, requested: str) -> None:
    """Never silently use future observations for a historical request."""
    meta = payload.get("meta") or {}
    # as_of can name the publication version, rather than an observation date.
    for key in ("actual_factor_date", "risk_as_of", "actual_as_of"):
        actual = meta.get(key)
        if actual:
            try:
                if Date.fromisoformat(actual) > Date.fromisoformat(requested):
                    raise HTTPException(502, "返回数据晚于请求日期，未作为历史诊断展示 / Data is later than requested")
            except (ValueError, TypeError):
                raise HTTPException(502, "分析日期格式不可核验 / Invalid analysis date") from None


def register_shannon_routes(app: FastAPI, require_auth) -> None:
    @app.get("/api/shannon/status", dependencies=[Depends(require_auth)])
    def status():
        return {"configured": configured()}

    @app.get("/api/shannon/catalog", dependencies=[Depends(require_auth)])
    def catalog():
        return invoke({"intent": "catalog"})

    @app.post("/api/shannon/diagnosis", dependencies=[Depends(require_auth)])
    def diagnosis(request: Snapshot):
        day = effective_date(request.date)
        payload = invoke({"intent": "portfolio_diagnosis", "date": day, "universe": "all", "positions": request.positions(day)})
        if payload.get("status") != "completed" or not isinstance(payload.get("data"), dict):
            raise HTTPException(502, "未取得完整诊断 / No completed diagnosis")
        check_dates(payload, day)
        if not (payload.get("meta") or {}).get("actual_factor_date"):
            raise HTTPException(502, "未返回实际诊断日期 / Actual diagnosis date missing")
        return {**payload, "requested_date": day,
                "weight_assumption": "equal" if request.holdings[0].weight is None else "custom"}
