"""Raw Tushare financial statement loader for A-share backtests.

This loader intentionally stays narrow: it fetches raw per-table records using
the local financial field registry and does not yet perform point-in-time
projection onto trading calendars.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import pandas as pd

from backtest.financials.contracts import FinancialQueryPlan, FinancialTableParams
from backtest.financials.ashare.field_registry import (
    get_financial_field_registry,
)


TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}
_RESERVED_QUERY_PARAM_KEYS = frozenset({"ts_code", "period", "start_date", "end_date", "fields"})


def _normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.replace("-", "")


def _merge_extra_params(
    params: dict[str, Any],
    extra_params: Mapping[str, Any] | None,
) -> None:
    if not extra_params:
        return

    reserved_keys = sorted(
        key for key, value in extra_params.items()
        if value is not None and key in _RESERVED_QUERY_PARAM_KEYS
    )
    if reserved_keys:
        raise ValueError(
            "extra_params may not override reserved financial query keys: "
            f"{reserved_keys}"
        )

    params.update({key: value for key, value in extra_params.items() if value is not None})


class TushareFinancialLoader:
    """Fetch raw statement rows from Tushare by table and field plan."""

    def __init__(self, api: Any | None = None) -> None:
        self.registry = get_financial_field_registry()
        if api is not None:
            self.api = api
            return

        import tushare as ts

        token = os.getenv("TUSHARE_TOKEN", "")
        self.api = ts.pro_api(token)

    def is_available(self) -> bool:
        """Available when a non-placeholder TUSHARE_TOKEN is configured."""
        return os.getenv("TUSHARE_TOKEN", "").strip() not in TUSHARE_TOKEN_PLACEHOLDERS

    def fetch_table(
        self,
        table_name: str,
        *,
        ts_code: str | None = None,
        fields: list[str] | tuple[str, ...] | None = None,
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        use_vip: bool | None = None,
        extra_params: Mapping[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Fetch raw rows for a single financial table.

        Ordinary endpoints require ``ts_code``. Vip endpoints can be used for
        full-market slices when ``ts_code`` is absent.
        """
        table = self.registry.get_table(table_name)
        query_fields = self._validate_fields(table_name, fields)

        if use_vip is None:
            use_vip = ts_code is None
        if use_vip and not table.vip_api_name:
            raise ValueError(f"table '{table_name}' has no vip endpoint")
        if not use_vip and not ts_code:
            raise ValueError(f"table '{table_name}' requires ts_code when not using vip")

        method_name = table.vip_api_name if use_vip else table.api_name
        api_method = getattr(self.api, method_name)

        params: dict[str, Any] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if period:
            params["period"] = _normalize_date(period)
        normalized_start = _normalize_date(start_date)
        normalized_end = _normalize_date(end_date)
        if normalized_start:
            params["start_date"] = normalized_start
        if normalized_end:
            params["end_date"] = normalized_end
        if query_fields:
            params["fields"] = ",".join(query_fields)
        _merge_extra_params(params, extra_params)

        result = api_method(**params)
        if result is None:
            return pd.DataFrame(columns=list(query_fields))
        return result.copy()

    def fetch_for_codes(
        self,
        query_plan: FinancialQueryPlan,
        *,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
        table_params: FinancialTableParams | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch raw statement history for a concrete list of stock codes."""
        table_params = table_params or {}
        result: dict[str, pd.DataFrame] = {}
        for table_name, fields in query_plan.query_fields.items():
            frames: list[pd.DataFrame] = []
            for code in codes:
                frame = self.fetch_table(
                    table_name,
                    ts_code=code,
                    fields=fields,
                    start_date=start_date,
                    end_date=end_date,
                    use_vip=False,
                    extra_params=table_params.get(table_name),
                )
                if frame is not None and not frame.empty:
                    frames.append(frame)
            if frames:
                result[table_name] = pd.concat(frames, ignore_index=True)
            else:
                result[table_name] = pd.DataFrame(columns=list(fields))
        return result

    def fetch_for_period(
        self,
        query_plan: FinancialQueryPlan,
        *,
        period: str,
        table_params: FinancialTableParams | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch a full-market cross-section for a report period via vip APIs."""
        table_params = table_params or {}
        result: dict[str, pd.DataFrame] = {}
        for table_name, fields in query_plan.query_fields.items():
            result[table_name] = self.fetch_table(
                table_name,
                period=period,
                fields=fields,
                use_vip=True,
                extra_params=table_params.get(table_name),
            )
        return result

    def _validate_fields(
        self,
        table_name: str,
        fields: list[str] | tuple[str, ...] | None,
    ) -> tuple[str, ...] | None:
        if fields is None:
            return None

        table = self.registry.get_table(table_name)
        deduped = tuple(dict.fromkeys(fields))
        invalid = [field_name for field_name in deduped if field_name not in table.output_fields]
        if invalid:
            raise ValueError(
                f"fields {invalid!r} do not belong to financial table '{table_name}'"
            )
        return deduped