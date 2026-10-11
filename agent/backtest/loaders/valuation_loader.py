"""CN valuation panel loader from Tushare ``daily_basic``.

Supplies the ``val:*`` panel namespace (proposal §4 Tier 2): daily valuation
multiples keyed by ``trade_date``. Unlike the ``fund:*`` XBRL/statement panel
these are daily market data — PIT-safe by construction, with no filing lag to
anchor. Missing dates and non-CN symbols stay NaN; nothing is fabricated.

Field whitelist: only the ``daily_basic`` columns already proven by the
``extra_fields`` merge in ``backtest/loaders/tushare.py`` are served
(``pe``, ``pe_ttm``, ``pb``, ``ps_ttm``, ``dv_ttm``). Any other ``val:`` field
is rejected with a ``ValueError`` at load time rather than silently NaN-ed, so
a factor declaring an unsupported field fails loudly.

US/HK supply is deferred (proposal §4 Tier 2 note): non-CN symbols simply get
no data here, and factors declaring ``val:`` columns SkipAlpha on universes
without CN supply.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from backtest.loaders._symbol_utils import _is_etf_listed
from backtest.loaders.tushare import (
    TUSHARE_TOKEN_PLACEHOLDERS,
    _call_with_backoff,
    _is_index,
)

logger = logging.getLogger(__name__)

#: ``daily_basic`` columns the ``val:`` namespace serves. ``dv_ttm`` is in
#: percent units (股息率TTM, %); consumers z-score it, which is scale-invariant.
VALUATION_FIELDS: tuple[str, ...] = ("pe", "pe_ttm", "pb", "ps_ttm", "dv_ttm")

#: A-share exchange suffixes covered by ``daily_basic``.
_CN_EQUITY_SUFFIXES = (".SH", ".SZ", ".BJ")


def validate_valuation_fields(fields: Iterable[str]) -> list[str]:
    """Validate and de-duplicate requested ``val:`` field names.

    Args:
        fields: Field names with the ``val:`` prefix already stripped.

    Returns:
        Stable, de-duplicated field list.

    Raises:
        ValueError: If any field is outside :data:`VALUATION_FIELDS`.
    """
    unknown = [field for field in fields if field not in VALUATION_FIELDS]
    if unknown:
        raise ValueError(
            f"unsupported val: field(s) {unknown}; the valuation namespace "
            f"serves only tushare daily_basic columns {list(VALUATION_FIELDS)}"
        )
    return list(dict.fromkeys(fields))


def _is_cn_equity(code: str) -> bool:
    """Detect A-share equity symbols served by ``daily_basic``.

    ``daily_basic`` is stock-only: indices and listed funds are excluded even
    though they carry a ``.SH``/``.SZ`` suffix.
    """
    if not code.upper().endswith(_CN_EQUITY_SUFFIXES):
        return False
    return not (_is_etf_listed(code) or _is_index(code))


def _build_api() -> Any:
    """Build a Tushare pro API client from the configured token.

    Raises:
        RuntimeError: If ``TUSHARE_TOKEN`` is unset or a placeholder.
    """
    import tushare as ts

    from src.config.accessor import get_env_config

    token = get_env_config().data.tushare_token.strip()
    if token in TUSHARE_TOKEN_PLACEHOLDERS:
        raise RuntimeError(
            "TUSHARE_TOKEN not configured; required for val:* valuation columns"
        )
    return ts.pro_api(token)


def load_valuation_panel(
    *,
    symbols: Sequence[str],
    fields: Iterable[str],
    start: str,
    end: str,
    index: pd.DatetimeIndex,
    api: Any | None = None,
) -> dict[str, pd.DataFrame]:
    """Load whitelisted ``daily_basic`` valuation fields as wide panels.

    Args:
        symbols: Panel symbols; only CN A-share equities are fetched, the rest
            stay NaN.
        fields: Requested field names (``val:`` prefix stripped).
        start: Start date (YYYY-MM-DD).
        end: End date (YYYY-MM-DD).
        index: Price-panel index to align to.
        api: Optional pre-built Tushare pro API (tests inject fakes here).

    Returns:
        ``field -> dates x symbols`` frames aligned to ``index``/``symbols``.
        Every validated field is present; symbols or dates ``daily_basic`` did
        not serve are NaN.

    Raises:
        ValueError: If a field is outside :data:`VALUATION_FIELDS`.
        RuntimeError: If no API is injected and ``TUSHARE_TOKEN`` is missing.
    """
    checked = validate_valuation_fields(fields)
    if not checked:
        return {}

    def _nan_frame(per_code: dict[str, pd.Series] | None = None) -> pd.DataFrame:
        if not per_code:
            return pd.DataFrame(float("nan"), index=index, columns=list(symbols))
        return pd.DataFrame(per_code).reindex(index=index, columns=list(symbols))

    cn_symbols = [code for code in symbols if _is_cn_equity(code)]
    if not cn_symbols:
        return {field: _nan_frame() for field in checked}
    if api is None:
        api = _build_api()

    sd = start.replace("-", "")
    ed = end.replace("-", "")
    series_by_field: dict[str, dict[str, pd.Series]] = {field: {} for field in checked}

    for code in cn_symbols:
        try:
            basic = _call_with_backoff(
                api.daily_basic,
                ts_code=code,
                start_date=sd,
                end_date=ed,
                fields="ts_code,trade_date," + ",".join(checked),
            )
        except Exception as exc:  # noqa: BLE001 - one bad fetch must not raise
            logger.warning("daily_basic valuation fetch failed for %s: %s", code, exc)
            continue
        if basic is None or basic.empty:
            logger.warning("daily_basic returned empty valuation data for %s", code)
            continue
        basic = basic.copy()
        basic["trade_date"] = pd.to_datetime(basic["trade_date"], errors="coerce")
        basic = basic.dropna(subset=["trade_date"]).set_index("trade_date").sort_index()
        for field in checked:
            if field in basic.columns:
                series_by_field[field][code] = pd.to_numeric(
                    basic[field], errors="coerce"
                )

    return {field: _nan_frame(per_code) for field, per_code in series_by_field.items()}
