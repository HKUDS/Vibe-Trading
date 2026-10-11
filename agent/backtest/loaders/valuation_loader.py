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

#: Fields the free baostock fallback can serve, mapped to their
#: ``query_history_k_data_plus`` column names (#1789 follow-up #3).
#: ``pe`` (dynamic) and ``dv_ttm`` have no baostock counterpart and stay NaN
#: when the fallback is the only source.
BAOSTOCK_VALUATION_FIELDS: dict[str, str] = {"pe_ttm": "peTTM", "pb": "pbMRQ", "ps_ttm": "psTTM"}

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


def _resolve_tushare_api(api: Any | None) -> Any | None:
    """Return an injectable API unchanged; build from token or None.

    A missing token returns None (the free baostock fallback serves those
    fields) instead of raising, and a tushare import/config failure also
    returns None so a broken tushare install degrades rather than kills the
    valuation panel.
    """
    if api is not None:
        return api
    try:
        return _build_api()
    except Exception as exc:  # noqa: BLE001 - missing token falls back, never raises
        logger.info("tushare unavailable for val:* (%s); trying baostock fallback", exc)
        return None


def _baostock_available() -> bool:
    """True if the baostock package is importable."""
    try:
        import baostock  # noqa: F401

        return True
    except ImportError:
        return False


def _to_baostock_code(code: str) -> str | None:
    """Map a panel symbol to baostock's ``sh.``/``sz.`` code, if A-share."""
    lower = code.lower()
    if lower.startswith(("sh.", "sz.")):
        return lower
    if code.upper().endswith((".SH", ".SZ")):
        symbol, _, suffix = code.upper().rpartition(".")
        return f"{suffix.lower()}.{symbol}"
    return None


def _load_baostock_valuation(
    cn_symbols: Sequence[str],
    fields: Sequence[str],
    start: str,
    end: str,
    index: pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    """Serve ``val:*`` fields from free, no-auth baostock daily bars.

    Fallback for users without a TUSHARE_TOKEN (#1789 follow-up #3):
    ``query_history_k_data_plus`` exposes per-day valuation columns
    (``peTTM``/``pbMRQ``/``psTTM``) on the same daily bars the OHLCV loader
    already uses. Fields without a baostock counterpart (``pe`` dynamic,
    ``dv_ttm``) are returned as NaN frames rather than fabricated, and a
    baostock outage degrades to NaN frames instead of raising.

    Args:
        cn_symbols: CN A-share symbols to fetch.
        fields: Requested field names (``val:`` prefix stripped).
        start: Start date (YYYY-MM-DD).
        end: End date (YYYY-MM-DD).
        index: Price-panel index to align to.

    Returns:
        ``field -> dates x symbols`` frames aligned to ``index``/``cn_symbols``.
    """
    from backtest.loaders.baostock_loader import _baostock_socket_guard, _read_timeout

    wanted = [field for field in fields if field in BAOSTOCK_VALUATION_FIELDS]
    nan_frames = {
        field: pd.DataFrame(float("nan"), index=index, columns=list(cn_symbols))
        for field in fields
    }
    if not wanted:
        return nan_frames

    import baostock as bs

    columns = "date," + ",".join(BAOSTOCK_VALUATION_FIELDS[field] for field in wanted)
    series_by_field: dict[str, dict[str, pd.Series]] = {field: {} for field in wanted}
    with _baostock_socket_guard(_read_timeout()) as acquired:
        if not acquired:
            return nan_frames
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning("baostock login failed: %s; valuation fallback stays NaN", lg.error_msg)
            return nan_frames
        try:
            for code in cn_symbols:
                bs_code = _to_baostock_code(code)
                if bs_code is None:
                    continue
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        columns,
                        start_date=start,
                        end_date=end,
                        frequency="d",
                    )
                except Exception as exc:  # noqa: BLE001 - one bad fetch must not raise
                    logger.warning("baostock valuation fetch failed for %s: %s", code, exc)
                    continue
                if rs.error_code != "0":
                    logger.warning("baostock valuation query failed for %s: %s", code, rs.error_msg)
                    continue
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                frame = pd.DataFrame(rows, columns=columns.split(","))
                frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
                frame = frame.dropna(subset=["date"]).set_index("date").sort_index()
                for field in wanted:
                    source_column = BAOSTOCK_VALUATION_FIELDS[field]
                    if source_column in frame.columns:
                        series_by_field[field][code] = pd.to_numeric(
                            frame[source_column], errors="coerce"
                        )
        finally:
            bs.logout()

    for field in wanted:
        per_code = series_by_field[field]
        if per_code:
            frame = pd.DataFrame(per_code).reindex(index=index, columns=list(cn_symbols))
            nan_frames[field] = frame
    return nan_frames


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
        not serve are NaN, and fields tushare could not serve (no token, or
        no data returned) are retried against the free baostock fallback
        (:func:`_load_baostock_valuation`) before degrading to NaN.

    Raises:
        ValueError: If a field is outside :data:`VALUATION_FIELDS`.
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

    api = _resolve_tushare_api(api)

    sd = start.replace("-", "")
    ed = end.replace("-", "")
    series_by_field: dict[str, dict[str, pd.Series]] = {field: {} for field in checked}

    if api is not None:
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

    tushare_served = {field for field, per_code in series_by_field.items() if per_code}
    fallback_fields = [field for field in checked if field not in tushare_served]
    if fallback_fields and _baostock_available():
        logger.info(
            "val:%s not served by tushare; trying the free baostock fallback",
            fallback_fields,
        )
        fallback = _load_baostock_valuation(cn_symbols, fallback_fields, start, end, index)
        for field, frame in fallback.items():
            if frame.notna().any().any():
                series_by_field[field] = {
                    code: frame[code] for code in frame.columns if frame[code].notna().any()
                }

    return {field: _nan_frame(per_code) for field, per_code in series_by_field.items()}
