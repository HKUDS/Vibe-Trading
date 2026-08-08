"""Translate sparse SEC facts into PIT-safe daily fundamental panels.

The loader's core invariant is point-in-time safety: values become visible on
their SEC ``filed`` date, never on ``period_end``. Phase 1 implements the SEC
branch only. ``freq="ttm"`` uses a pragmatic Phase-1 approximation: known
income-statement and cash-flow concepts are rolling four-quarter sums keyed by
``period_end`` and anchored by the latest ``filed`` date in the rolling window;
balance-sheet and share-count concepts use the latest quarterly value. SEC
companyfacts can mix true-quarter, year-to-date, and annual facts, so upstream
schema normalization may still be needed for issuer-specific precision.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from typing import Any

import pandas as pd

from backtest.loaders import sec_edgar_client
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.sec_frames import ANNUAL_SPAN_DAYS, QUARTER_SPAN_DAYS

logger = logging.getLogger(__name__)

_VALID_FREQS = {"annual", "quarterly", "ttm"}
_ANNUAL_FORMS = {"10-K"}
_QUARTERLY_FORMS = {"10-Q", "10-K"}

_FLOW_CONCEPTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "CostOfGoodsAndServicesSold",
    "CostOfRevenue",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "ProfitLoss",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
}


def _extract_concept_series(
    facts: dict[str, Any],
    concepts: list[str],
    freq: str,
    *,
    pit: bool = True,
) -> pd.DataFrame:
    """Extract a sparse ``period_end``/``filed``/``value`` series.

    Args:
        facts: SEC companyfacts payload.
        concepts: Ordered us-gaap concept aliases to union.
        freq: ``"annual"``, ``"quarterly"``, or ``"ttm"``.
        pit: When true, duplicate ``period_end`` rows keep the earliest filing;
            when false, they keep the latest filing for research mode.

    Returns:
        DataFrame with ``period_end``, ``filed``, and ``value`` columns.

    Raises:
        ValueError: If ``freq`` is unsupported.
    """
    if freq not in _VALID_FREQS:
        raise ValueError(f"unsupported fundamental freq: {freq}")

    rows: list[dict[str, Any]] = []
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept_order, concept in enumerate(concepts):
        concept_node = us_gaap.get(concept, {})
        units = concept_node.get("units", {}) if isinstance(concept_node, dict) else {}
        if not isinstance(units, dict):
            continue
        for unit_items in units.values():
            if not isinstance(unit_items, list):
                continue
            for item in unit_items:
                if not isinstance(item, dict):
                    continue
                if not _form_allowed(str(item.get("form", "")), freq):
                    continue
                rows.append(
                    {
                        "period_start": item.get("start"),
                        "period_end": item.get("end"),
                        "filed": item.get("filed"),
                        "value": item.get("val"),
                        "_concept_order": concept_order,
                    }
                )

    columns = ["period_end", "filed", "value"]
    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    df["period_start"] = pd.to_datetime(df["period_start"], errors="coerce").dt.normalize()
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce").dt.normalize()
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce").dt.normalize()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["period_end", "filed", "value"])
    if df.empty:
        return pd.DataFrame(columns=columns)

    keep = "first" if pit else "last"
    if _is_flow_concept_series(concepts):
        # Duration entries mix true quarters, year-to-date frames sharing the
        # same end date, and full-year frames; summing them blindly double
        # counts. Select by (start, end) span before any dedupe or rolling.
        df = df.dropna(subset=["period_start"])
        df = df.sort_values(["period_start", "period_end", "filed", "_concept_order"])
        df = df.drop_duplicates(subset=["period_start", "period_end"], keep=keep)
        duration = (df["period_end"] - df["period_start"]).dt.days
        if freq == "annual":
            df = df[duration.between(*ANNUAL_SPAN_DAYS)]
        else:
            df = _quarterly_flow_frames(df, duration)
    else:
        df = df.sort_values(["period_end", "filed", "_concept_order"])

    df = df.drop_duplicates(subset=["period_end"], keep=keep).sort_values("period_end")

    if freq == "ttm" and _is_flow_concept_series(concepts):
        df = _to_ttm_flow_series(df)

    return df.loc[:, columns].sort_values("period_end").reset_index(drop=True)


def _quarterly_flow_frames(df: pd.DataFrame, duration: pd.Series) -> pd.DataFrame:
    """Return true-quarter flow frames, deriving fiscal Q4 from 10-K full years.

    Filers like AAPL report Q4 only inside the 10-K full-year frame, so a
    missing quarter ending at the fiscal year end is synthesized as
    ``FY - (Q1 + Q2 + Q3)``. The synthesized row is anchored on the 10-K
    ``filed`` date, which keeps it PIT-safe.
    """
    quarters = df[duration.between(*QUARTER_SPAN_DAYS)].copy()
    annuals = df[duration.between(*ANNUAL_SPAN_DAYS)]
    quarter_ends = set(quarters["period_end"])
    synthesized: list[dict[str, Any]] = []
    for annual in annuals.to_dict("records"):
        if annual["period_end"] in quarter_ends:
            continue
        inside = quarters[
            (quarters["period_start"] >= annual["period_start"])
            & (quarters["period_end"] < annual["period_end"])
        ]
        if len(inside) != 3:
            continue
        synthesized.append(
            {
                "period_start": inside["period_end"].max(),
                "period_end": annual["period_end"],
                "filed": max(annual["filed"], inside["filed"].max()),
                "value": annual["value"] - inside["value"].sum(),
                "_concept_order": annual["_concept_order"],
            }
        )
    if synthesized:
        quarters = pd.concat([quarters, pd.DataFrame(synthesized)], ignore_index=True)
    return quarters


def _ffill_pit(series: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill sparse values onto ``index`` using ``filed`` as the anchor.

    Args:
        series: DataFrame containing ``filed`` and ``value`` columns.
        index: Target dates.

    Returns:
        Dense Series indexed like ``index``.
    """
    target_index = pd.DatetimeIndex(index)
    if series.empty:
        return pd.Series(index=target_index, dtype="float64")

    sparse = series.copy()
    sparse["filed"] = pd.to_datetime(sparse["filed"], errors="coerce").dt.normalize()
    sparse["value"] = pd.to_numeric(sparse["value"], errors="coerce")
    sparse = sparse.dropna(subset=["filed", "value"]).sort_values("filed")
    if sparse.empty:
        return pd.Series(index=target_index, dtype="float64")

    values = sparse.set_index("filed")["value"].sort_index()
    values = values[~values.index.duplicated(keep="last")]
    aligned_index = values.index.union(target_index)
    return values.reindex(aligned_index).ffill().reindex(target_index)


def load_fundamental_panel(
    symbols: list[str],
    fields: list[str],
    start: str,
    end: str,
    freq: str = "ttm",
    pit: bool = True,
    source: str = "auto",
    index: pd.DatetimeIndex | None = None,
) -> dict[str, pd.DataFrame]:
    """Load SEC fundamental fields as dense date-by-symbol panels.

    Args:
        symbols: Tickers to load.
        fields: Unified schema field names, raw or derived.
        start: Inclusive start date.
        end: Inclusive end date.
        freq: ``"annual"``, ``"quarterly"``, or ``"ttm"``.
        pit: True keeps first filed facts per period; false keeps latest filed.
        source: ``"auto"`` or ``"sec"``. Phase 1 routes both to SEC.
        index: Optional target date index. When omitted, calendar days from
            ``start`` through ``end`` are used.

    Returns:
        Mapping ``field -> DataFrame(index=dates, columns=symbols)``.

    Raises:
        ValueError: If source or frequency is unsupported.
        RuntimeError: If the fundamental schema module is unavailable.
    """
    validate_date_range(start, end)
    if freq not in _VALID_FREQS:
        raise ValueError(f"unsupported fundamental freq: {freq}")
    if source not in {"auto", "sec"}:
        raise ValueError("Phase 1 fundamentals loader supports source='auto' or 'sec' only")

    target_index = _target_index(start, end, index)
    schema = _load_schema()
    requested_fields = [_resolve_field_name(schema, field) for field in fields]
    raw_fields = sorted(_collect_raw_fields(schema, requested_fields))
    symbol_list = list(symbols)

    ciks = _resolve_ciks(symbol_list)
    symbol_raw_frames = {
        symbol: _load_symbol_raw_frame(
            symbol=symbol,
            cik=ciks.get(symbol),
            raw_fields=raw_fields,
            schema=schema,
            start=start,
            end=end,
            freq=freq,
            pit=pit,
            index=target_index,
        )
        for symbol in symbol_list
    }

    panels: dict[str, pd.DataFrame] = {}
    for field in raw_fields:
        panels[field] = pd.DataFrame(
            {symbol: symbol_raw_frames[symbol][field] for symbol in symbol_list},
            index=target_index,
            columns=symbol_list,
        )

    def panel_for(field: str) -> pd.DataFrame:
        if field in panels:
            return panels[field]
        derived = _derived_field(schema, field)
        if derived is None:
            panels[field] = _empty_panel(target_index, symbol_list)
            return panels[field]
        deps = {
            _resolve_field_name(schema, dep): panel_for(_resolve_field_name(schema, dep))
            for dep in _derived_dependencies(derived)
        }
        computed = _compute_derived(derived, deps)
        panels[field] = computed.reindex(index=target_index, columns=symbol_list)
        return panels[field]

    return {field: panel_for(field) for field in requested_fields}


def _form_allowed(form: str, freq: str) -> bool:
    if freq == "annual":
        return form in _ANNUAL_FORMS
    if freq in {"quarterly", "ttm"}:
        return form in _QUARTERLY_FORMS
    return False


def _is_flow_concept_series(concepts: Iterable[str]) -> bool:
    return any(concept in _FLOW_CONCEPTS for concept in concepts)


def _to_ttm_flow_series(df: pd.DataFrame) -> pd.DataFrame:
    ttm = df.sort_values("period_end").copy()
    ttm["value"] = ttm["value"].rolling(window=4, min_periods=4).sum()
    filed_values = list(ttm["filed"])
    ttm["filed"] = [
        pd.NaT if pos < 3 else max(filed_values[pos - 3 : pos + 1])
        for pos in range(len(filed_values))
    ]
    return ttm.dropna(subset=["filed", "value"])


def _target_index(
    start: str,
    end: str,
    index: pd.DatetimeIndex | None,
) -> pd.DatetimeIndex:
    if index is not None:
        return pd.DatetimeIndex(index)
    return pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")


def _load_schema() -> Any:
    try:
        return importlib.import_module("backtest.loaders._fundamental_schema")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "backtest.loaders._fundamental_schema is required for fundamentals loading"
        ) from exc


def _resolve_field_name(schema: Any, field: str) -> str:
    normalized = str(field).removeprefix("fund:")
    resolver = getattr(schema, "resolve_field", None)
    if not callable(resolver):
        return normalized
    resolved = resolver(normalized)
    if isinstance(resolved, str):
        return resolved.removeprefix("fund:")
    name = getattr(resolved, "name", None)
    if isinstance(name, str):
        return name.removeprefix("fund:")
    return normalized


def _collect_raw_fields(schema: Any, fields: Iterable[str]) -> set[str]:
    raw: set[str] = set()
    visiting: set[str] = set()

    def visit(field: str) -> None:
        if field in visiting:
            raise ValueError(f"cyclic derived fundamental field: {field}")
        derived = _derived_field(schema, field)
        if derived is None:
            raw.add(field)
            return
        visiting.add(field)
        for dep in _derived_dependencies(derived):
            visit(_resolve_field_name(schema, dep))
        visiting.remove(field)

    for field in fields:
        visit(field)
    return raw


def _derived_field(schema: Any, field: str) -> Any | None:
    return getattr(schema, "DERIVED_FIELDS", {}).get(field)


def _spec_get(derived: Any, key: str) -> Any:
    """Read a derived-field spec entry from either a mapping or an object."""
    if isinstance(derived, dict):
        return derived.get(key)
    return getattr(derived, key, None)


def _derived_dependencies(derived: Any) -> list[str]:
    deps = _spec_get(derived, "dependencies") or ()
    return [str(dep) for dep in deps]


def _compute_derived(derived: Any, dependencies: dict[str, pd.DataFrame]) -> pd.DataFrame:
    compute = _spec_get(derived, "compute")
    if not callable(compute):
        raise ValueError(f"derived field has no callable compute: {derived!r}")
    try:
        result = compute(dependencies)
    except TypeError:
        result = compute(**dependencies)
    if not isinstance(result, pd.DataFrame):
        result = pd.DataFrame(result)
    return result


def _resolve_ciks(symbols: list[str]) -> dict[str, str | None]:
    """Map each symbol to its SEC CIK.

    Args:
        symbols: Requested symbols.

    Returns:
        A symbol -> CIK mapping; the value is ``None`` for a symbol the SEC
        ticker table does not carry.

    Raises:
        ValueError: If no symbol resolves. Returning an all-null panel here
            reads as "this issuer reports nothing" rather than "this loader
            cannot serve this market", which is the more damaging of the two.
    """
    ciks: dict[str, str | None] = {}
    missing: list[str] = []
    for symbol in symbols:
        cik = sec_edgar_client.cik_for(symbol)
        ciks[symbol] = cik
        if cik is None:
            missing.append(symbol)
    if missing:
        logger.warning("No SEC CIK for symbols: %s", ", ".join(missing))
    if symbols and len(missing) == len(symbols):
        raise ValueError(
            f"no SEC CIK resolved for any of: {', '.join(missing)}. The "
            "fundamentals loader is US-only (SEC XBRL); pass a US ticker with "
            "or without a .US suffix, e.g. 'AAPL' or 'AAPL.US'."
        )
    return ciks


def _load_symbol_raw_frame(
    *,
    symbol: str,
    cik: str | None,
    raw_fields: list[str],
    schema: Any,
    start: str,
    end: str,
    freq: str,
    pit: bool,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    if cik is None:
        return _empty_field_frame(index, raw_fields)

    def fetch() -> pd.DataFrame:
        return _fetch_symbol_raw_frame(
            symbol=symbol,
            cik=cik,
            raw_fields=raw_fields,
            schema=schema,
            freq=freq,
            pit=pit,
            index=index,
        )

    cached = cached_loader_fetch(
        source="sec_fundamentals",
        symbol=symbol,
        timeframe=f"{freq}:pit={int(pit)}",
        start_date=start,
        end_date=end,
        fields=raw_fields,
        fetch=fetch,
    )
    if cached is None:
        return _empty_field_frame(index, raw_fields)
    return cached.reindex(index=index, columns=raw_fields)


def _fetch_symbol_raw_frame(
    *,
    symbol: str,
    cik: str,
    raw_fields: list[str],
    schema: Any,
    freq: str,
    pit: bool,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    try:
        facts = sec_edgar_client.get_company_facts(cik)
    except Exception as exc:  # noqa: BLE001 - one bad symbol should not abort the panel
        logger.warning("SEC companyfacts failed for %s: %s", symbol, exc)
        return _empty_field_frame(index, raw_fields)

    frame = _empty_field_frame(index, raw_fields)
    concept_map = getattr(schema, "SEC_CONCEPT_MAP", {})
    for field in raw_fields:
        concepts = list(concept_map.get(field, ()))
        if not concepts:
            logger.warning("SEC concept miss for %s field %s: no aliases configured", symbol, field)
            continue
        sparse = _extract_concept_series(facts, concepts, freq, pit=pit)
        if sparse.empty:
            logger.warning(
                "SEC concept miss for %s field %s: aliases=%s",
                symbol,
                field,
                ",".join(concepts),
            )
            continue
        frame[field] = _ffill_pit(sparse, index)
    return frame


def _empty_field_frame(index: pd.DatetimeIndex, fields: list[str]) -> pd.DataFrame:
    return pd.DataFrame(index=index, columns=fields, dtype="float64")


def _empty_panel(index: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(index=index, columns=symbols, dtype="float64")
