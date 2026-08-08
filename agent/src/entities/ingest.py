"""Read irregular dated cash-flow files into a ``CashFlowSeries``.

This is the entry point a user's own file takes into the system. It is a
deliberately separate path from ``backtest/loaders``: that path requires an
OHLC bar and drops every column it does not recognise, which is precisely why a
capital call or a coupon schedule cannot get in through it.

Two rules govern this module:

* **Never return None.** A malformed or mis-mapped file raises
  ``CashFlowIngestError`` naming the file, the row, and the fix. The bar loader
  returns ``None`` for an unrecognised file and the caller sees "no data" with
  no idea why; that failure mode is not repeated here.
* **Never guess.** An ambiguous date format, an ambiguous decimal separator, a
  missing currency, or an unmappable kind is an error, not an inference.
  Guessing day-first vs month-first, or reading ``1.234,50`` as ``1.2345``,
  produces a plausible wrong answer that nothing downstream can detect.

Unmapped columns are preserved into ``CashFlow.metadata`` rather than dropped.
"""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from src.entities.cashflow import CashFlow, CashFlowSeries
from src.entities.cashflow import normalize_kind
from src.entities.models import normalize_date
from src.entities.models import normalize_currency

logger = logging.getLogger(__name__)

__all__ = [
    "CashFlowIngestError",
    "EntityPanel",
    "PanelIngestError",
    "PanelObservation",
    "load_cashflows",
    "load_panel",
]

#: Canonical field -> the column names accepted for it without an explicit
#: mapping. Matching is case-insensitive and ignores spaces and underscores.
DEFAULT_COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "date": ("date", "asof", "asofdate", "transactiondate", "valuedate", "paymentdate"),
    "amount": ("amount", "cashflow", "cash", "value", "net", "netamount"),
    "kind": ("kind", "type", "cashflowtype", "transactiontype", "category", "flowtype"),
    "currency": ("currency", "ccy", "curr", "currencycode"),
}

#: Delimiter inferred from the file suffix when the caller does not name one.
_DELIMITER_BY_SUFFIX: Mapping[str, str] = {".csv": ",", ".tsv": "\t", ".txt": ","}

#: Characters removed from a numeric field before parsing: whitespace (including
#: the non-breaking space used by many exports), the Swiss group separator, and
#: currency symbols. Note that ``,`` and ``.`` are deliberately absent -- which
#: one is the decimal separator is resolved per value in ``_parse_amount``,
#: because deleting the wrong one silently turns ``1.234,50`` into ``1.2345``.
_AMOUNT_SYMBOLS = frozenset(" \t\u00a0'$€£¥")

#: Decimal separators a caller may declare explicitly.
_DECIMAL_SEPARATORS = (".", ",")


class CashFlowIngestError(ValueError):
    """Raised when a cash-flow file cannot be read into a valid series."""


def _canonical(name: str) -> str:
    """Reduce a column header to its comparison form.

    Args:
        name: Raw header text.

    Returns:
        Lower-cased header with spaces, underscores, and hyphens removed.
    """
    return name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _resolve_columns(
    header: Sequence[str],
    columns: Mapping[str, str] | None,
    path: Path,
) -> dict[str, str]:
    """Map canonical field names onto this file's actual column headers.

    Args:
        header: Column names as they appear in the file.
        columns: Explicit overrides, canonical field -> file column name.
        path: File path, used only for error messages.

    Returns:
        Mapping of canonical field name to the file's column name, containing
        only fields that were actually found.

    Raises:
        CashFlowIngestError: If an explicit override names a column that the
            file does not contain, or overrides an unknown field.
    """
    resolved: dict[str, str] = {}
    lookup = {_canonical(col): col for col in header}

    if columns:
        for field_name, source_name in columns.items():
            if field_name not in DEFAULT_COLUMN_ALIASES:
                known = ", ".join(sorted(DEFAULT_COLUMN_ALIASES))
                raise CashFlowIngestError(
                    f"{path}: unknown column mapping {field_name!r}; "
                    f"mappable fields are: {known}"
                )
            if source_name not in header:
                raise CashFlowIngestError(
                    f"{path}: mapped column {source_name!r} for field "
                    f"{field_name!r} is not in the file. Columns present: "
                    f"{', '.join(header)}"
                )
            resolved[field_name] = source_name

    for field_name, aliases in DEFAULT_COLUMN_ALIASES.items():
        if field_name in resolved:
            continue
        for alias in aliases:
            if alias in lookup:
                resolved[field_name] = lookup[alias]
                break

    return resolved


def _to_plain_number(text: str, decimal_separator: str | None) -> str:
    """Reduce a grouped decimal string to a form ``float`` accepts.

    Args:
        text: Numeric text with symbols already removed, e.g. ``"1,234.50"``.
        decimal_separator: ``"."`` or ``","`` when the caller declared one,
            otherwise ``None`` to infer.

    Returns:
        The same number using ``.`` as the decimal separator and no grouping.

    Raises:
        ValueError: If the value uses a single comma whose role cannot be
            determined -- ``"1,234"`` is 1234 in a US export and 1.234 in a
            European one, and the data cannot say which.
    """
    if decimal_separator is not None:
        grouping = "," if decimal_separator == "." else "."
        return text.replace(grouping, "").replace(decimal_separator, ".")

    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        # The rightmost separator is the decimal one; the other groups digits.
        if text.rindex(".") > text.rindex(","):
            return text.replace(",", "")
        return text.replace(".", "").replace(",", ".")
    if has_comma:
        if text.count(",") > 1:
            return text.replace(",", "")  # 1,234,567 cannot be a decimal comma
        raise ValueError(
            f"{text!r} uses a single comma and could be either "
            f"{text.replace(',', '')} (comma groups thousands) or "
            f"{text.replace(',', '.')} (comma is the decimal separator); pass "
            "decimal_separator='.' or decimal_separator=',' to say which"
        )
    return text


def _parse_amount(
    raw: str,
    path: Path,
    row_number: int,
    decimal_separator: str | None = None,
) -> float:
    """Parse a numeric amount from a file field.

    Handles currency symbols, digit grouping, and the accounting convention
    where parentheses or a trailing minus denote a negative number, e.g.
    ``(1,234.50)``.

    Args:
        raw: Raw cell text.
        path: File path, used only for error messages.
        row_number: 1-based data row number, used only for error messages.
        decimal_separator: Declared decimal separator, or ``None`` to infer.

    Returns:
        The parsed float, negated when the cell was parenthesised or carried a
        trailing minus.

    Raises:
        CashFlowIngestError: If the cell is blank, not numeric, or ambiguously
            grouped.
    """
    text = (raw or "").strip()
    if not text:
        raise CashFlowIngestError(
            f"{path} row {row_number}: amount is blank. A missing amount must be "
            "fixed at the source; it is not treated as zero."
        )

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = "".join(ch for ch in text if ch not in _AMOUNT_SYMBOLS).strip()
    if text.endswith("-"):  # trailing-minus exports
        text = "-" + text[:-1]

    try:
        value = float(_to_plain_number(text, decimal_separator))
    except ValueError as exc:
        raise CashFlowIngestError(
            f"{path} row {row_number}: amount {raw!r} is not usable: {exc}"
        ) from exc
    return -value if negative else value


def _parse_date(
    raw: str,
    date_format: str | None,
    path: Path,
    row_number: int,
) -> date:
    """Parse a date cell, using an explicit format when one is supplied.

    Args:
        raw: Raw cell text.
        date_format: ``strptime`` format, or ``None`` to require ISO-8601.
        path: File path, used only for error messages.
        row_number: 1-based data row number, used only for error messages.

    Returns:
        The parsed ``datetime.date``.

    Raises:
        CashFlowIngestError: If the cell is blank or does not parse.
    """
    text = (raw or "").strip()
    if not text:
        raise CashFlowIngestError(f"{path} row {row_number}: date is blank")
    if date_format:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError as exc:
            raise CashFlowIngestError(
                f"{path} row {row_number}: date {raw!r} does not match "
                f"date_format={date_format!r}"
            ) from exc
    try:
        return normalize_date(text)
    except ValueError as exc:
        raise CashFlowIngestError(
            f"{path} row {row_number}: date {raw!r} is not ISO-8601 "
            "(YYYY-MM-DD). Pass date_format=... explicitly; regional formats "
            "are not guessed because day-first and month-first cannot be told "
            "apart from the data."
        ) from exc


def _read_rows(
    path: Path, delimiter: str | None, encoding: str
) -> tuple[list[str], list[dict[str, str]]]:
    """Read a delimited text file into a header and a list of row mappings.

    Args:
        path: File to read.
        delimiter: Field delimiter, or ``None`` to infer from the suffix.
        encoding: Text encoding.

    Returns:
        Tuple of (header column names, list of row dicts).

    Raises:
        CashFlowIngestError: If the file is missing, unreadable, has an
            unsupported suffix, or has no header row.
    """
    if not path.exists():
        raise CashFlowIngestError(f"cash-flow file not found: {path}")

    if delimiter is None:
        suffix = path.suffix.lower()
        delimiter = _DELIMITER_BY_SUFFIX.get(suffix)
        if delimiter is None:
            supported = ", ".join(sorted(_DELIMITER_BY_SUFFIX))
            raise CashFlowIngestError(
                f"{path}: unsupported file type {suffix!r}; supported suffixes "
                f"are {supported}. Pass delimiter=... to read another format."
            )

    try:
        with open(path, "r", encoding=encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            header = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except UnicodeDecodeError as exc:
        raise CashFlowIngestError(
            f"{path}: cannot decode as {encoding!r}; pass encoding=... "
            "(exports from Chinese brokers are often 'gbk')"
        ) from exc
    except OSError as exc:
        raise CashFlowIngestError(f"{path}: cannot read file: {exc}") from exc

    if not header:
        raise CashFlowIngestError(f"{path}: file has no header row")
    return header, rows


def load_cashflows(
    path: str | Path,
    *,
    columns: Mapping[str, str] | None = None,
    currency: str | None = None,
    default_kind: str | None = None,
    date_format: str | None = None,
    decimal_separator: str | None = None,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    invert_sign: bool = False,
    pre_translated: bool = False,
    metadata_columns: Iterable[str] | None = None,
) -> CashFlowSeries:
    """Load an irregular dated cash-flow file into a ``CashFlowSeries``.

    The file needs a date column and an amount column. Currency and kind may
    come either from a column or from an argument, but must come from
    somewhere: neither is defaulted, because a wrong currency or a bucket
    labelled "unknown" silently corrupts every figure computed downstream.

    Columns that are not mapped to a canonical field are preserved verbatim in
    each ``CashFlow.metadata``.

    Args:
        path: Path to the file. ``.csv``, ``.tsv``, and ``.txt`` are recognised;
            any other suffix requires an explicit ``delimiter``.
        columns: Explicit mapping of canonical field to file column name, e.g.
            ``{"date": "Payment Date", "amount": "Net"}``. Canonical fields are
            ``date``, ``amount``, ``kind``, and ``currency``. Unmapped fields
            fall back to the aliases in ``DEFAULT_COLUMN_ALIASES``.
        currency: Currency for every row. Required when the file has no
            currency column; when both are present this argument names the
            series' reporting currency and the column supplies each row's.
        default_kind: Kind for rows whose kind column is absent or blank.
        date_format: ``strptime`` format for the date column. Omit only when
            the dates are ISO-8601.
        decimal_separator: ``"."`` or ``","``. Needed only for values whose
            grouping is genuinely ambiguous, such as a bare ``"1,234"``.
        delimiter: Field delimiter; inferred from the suffix when omitted.
        encoding: Text encoding of the file.
        invert_sign: Negate every amount after parsing. Use for files that
            report calls as positive, so the holder-perspective convention in
            ``src.entities.cashflow`` is restored at the boundary rather than
            by each caller downstream.
        pre_translated: Assert that a multi-currency file has already been
            converted into ``currency``. Requires ``currency``.
        metadata_columns: Restrict preserved metadata to these columns. By
            default every unmapped column is preserved.

    Returns:
        A ``CashFlowSeries`` ordered by date. An input file with a header but
        no data rows yields an empty series rather than an error.

    Raises:
        CashFlowIngestError: If the file is missing or unreadable, a required
            column is absent, currency or kind cannot be determined, or any row
            fails to parse or violates the sign convention. Never returns None.
        CurrencyMismatchError: If the file's rows span several currencies and
            ``pre_translated`` was not set.
        ValueError: If ``decimal_separator`` is neither ``"."`` nor ``","``.
    """
    if decimal_separator is not None and decimal_separator not in _DECIMAL_SEPARATORS:
        raise ValueError(
            f"decimal_separator must be one of {_DECIMAL_SEPARATORS}, "
            f"got {decimal_separator!r}"
        )

    path = Path(path).expanduser()
    header, rows = _read_rows(path, delimiter, encoding)
    resolved = _resolve_columns(header, columns, path)

    for required in ("date", "amount"):
        if required not in resolved:
            aliases = ", ".join(DEFAULT_COLUMN_ALIASES[required])
            raise CashFlowIngestError(
                f"{path}: required column {required!r} not found. Columns "
                f"present: {', '.join(header)}. Recognised names: {aliases}. "
                f"Pass columns={{{required!r}: '<your column>'}} to map it."
            )

    currency_column = resolved.get("currency")
    if currency_column is None and currency is None:
        raise CashFlowIngestError(
            f"{path}: no currency column found and no currency=... given. "
            "Currency is required; it is never defaulted, because summing "
            "across currencies produces a plausible wrong number."
        )

    kind_column = resolved.get("kind")
    if kind_column is None and default_kind is None:
        raise CashFlowIngestError(
            f"{path}: no kind column found and no default_kind=... given. "
            f"Columns present: {', '.join(header)}."
        )

    mapped_columns = set(resolved.values())
    if metadata_columns is None:
        extra_columns = [col for col in header if col not in mapped_columns]
    else:
        wanted = set(metadata_columns)
        missing = wanted - set(header)
        if missing:
            raise CashFlowIngestError(
                f"{path}: metadata_columns not in file: {', '.join(sorted(missing))}"
            )
        extra_columns = [col for col in header if col in wanted]

    flows: list[CashFlow] = []
    for offset, row in enumerate(rows):
        row_number = offset + 1
        if all(not (value or "").strip() for value in row.values()):
            continue  # trailing blank line

        amount = _parse_amount(
            row.get(resolved["amount"], ""), path, row_number, decimal_separator
        )
        if invert_sign:
            amount = -amount

        row_currency = currency
        if currency_column is not None:
            raw_currency = (row.get(currency_column) or "").strip()
            if raw_currency:
                row_currency = raw_currency
        if not row_currency:
            raise CashFlowIngestError(
                f"{path} row {row_number}: currency is blank and no currency=... "
                "fallback was given"
            )

        row_kind = default_kind
        if kind_column is not None:
            raw_kind = (row.get(kind_column) or "").strip()
            if raw_kind:
                row_kind = raw_kind
        if not row_kind:
            raise CashFlowIngestError(
                f"{path} row {row_number}: kind is blank and no default_kind=... "
                "fallback was given"
            )

        metadata: dict[str, Any] = {
            col: row[col] for col in extra_columns if (row.get(col) or "").strip()
        }
        metadata["source_file"] = str(path)
        metadata["source_row"] = row_number

        try:
            flows.append(
                CashFlow(
                    date=_parse_date(
                        row.get(resolved["date"], ""), date_format, path, row_number
                    ),
                    amount=amount,
                    kind=row_kind,
                    currency=row_currency,
                    metadata=metadata,
                )
            )
        except CashFlowIngestError:
            raise
        except ValueError as exc:
            raise CashFlowIngestError(f"{path} row {row_number}: {exc}") from exc

    logger.info("loaded %d cash flows from %s", len(flows), path)
    return CashFlowSeries(
        flows=tuple(flows),
        currency=currency,
        pre_translated=pre_translated,
    )


# ─────────────────────────────────────────────────────────────────────────
# Entity x date x metric panels: the non-bar counterpart to load_cashflows
# for data that is not a signed cash movement (a NAV series, an exposure or
# headcount table, any per-entity time series a bar engine cannot hold).
# This path never touches ``backtest/loaders`` or ``backtest/runner`` -- see
# the module docstring and the ``src.entities`` package note on staying
# parallel to the bar engines.
# ─────────────────────────────────────────────────────────────────────────


class PanelIngestError(ValueError):
    """Raised when an entity x date x metric panel file cannot be read.

    Mirrors ``CashFlowIngestError``'s contract: never return ``None`` or a
    silently-empty result to mean "could not read this"; name the file, the
    row or column, and the fix.
    """


#: Canonical panel field -> column-name aliases accepted without an explicit
#: mapping. Reuses ``DEFAULT_COLUMN_ALIASES`` wherever the concept already
#: exists there (``date``, ``currency``, and ``value``/"amount"), so date and
#: currency columns are recognised by the exact same names as in
#: ``load_cashflows``.
_PANEL_ENTITY_ALIASES: tuple[str, ...] = (
    "entity",
    "entityid",
    "id",
    "ticker",
    "symbol",
    "instrument",
    "instrumentid",
)
_PANEL_METRIC_ALIASES: tuple[str, ...] = ("metric", "field", "measure", "item")
_PANEL_UNIT_ALIASES: tuple[str, ...] = ("unit", "units", "uom")

_PANEL_COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "entity": _PANEL_ENTITY_ALIASES,
    "date": DEFAULT_COLUMN_ALIASES["date"],
    "metric": _PANEL_METRIC_ALIASES,
    "value": DEFAULT_COLUMN_ALIASES["amount"],
    "currency": DEFAULT_COLUMN_ALIASES["currency"],
    "unit": _PANEL_UNIT_ALIASES,
}

#: Layouts ``load_panel`` recognises; see its docstring for each shape.
_PANEL_LAYOUTS: tuple[str, ...] = ("long", "wide_dates_rows", "wide_entities_rows")


@dataclass(frozen=True)
class PanelObservation:
    """One (entity, date, metric) observation in a non-bar data panel.

    The generic counterpart to ``CashFlow``: instead of a signed settled
    amount it carries an arbitrary metric value (a NAV level, an exposure, a
    headcount) for a named entity on a date. It has no ``open``/``high``/
    ``low``/``close`` fields and is not shaped like an OHLC bar, so it cannot
    be mistaken for one by a bar engine.

    Attributes:
        entity_id: Identifier of the entity or instrument this value belongs
            to, e.g. a fund id or a ticker.
        date: Observation date.
        metric: Canonical metric label, e.g. ``"nav"`` or ``"exposure"``.
            Normalized via ``normalize_kind`` so ``"NAV"``/``"Nav"``/``"nav"``
            are recognised as the same metric.
        value: The observed numeric value.
        currency: Required currency code for the value, normalized to
            uppercase.
        unit: Required free-form unit label, e.g. ``"USD"``, ``"shares"``,
            ``"pct"``, ``"headcount"``. An exposure or NAV figure with no
            unit label is exactly the kind of ambiguous number this loader
            refuses to produce.
        metadata: Unmapped source columns, preserved verbatim.
    """

    entity_id: str
    date: date
    metric: str
    value: float
    currency: str
    unit: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize every field and validate the required ones are present.

        Raises:
            PanelIngestError: If ``entity_id``, ``currency``, or ``unit`` is
                blank, or ``value`` is not a finite number.
            ValueError: If ``date`` is unsupported or ``metadata`` is not a
                mapping.
        """
        entity = self.entity_id.strip() if isinstance(self.entity_id, str) else ""
        if not entity:
            raise PanelIngestError("entity_id is required and cannot be empty")
        object.__setattr__(self, "entity_id", entity)
        object.__setattr__(self, "date", normalize_date(self.date))
        object.__setattr__(self, "metric", normalize_kind(self.metric))

        try:
            value = float(self.value)
        except (TypeError, ValueError) as exc:
            raise PanelIngestError(f"value must be numeric, got {self.value!r}") from exc
        if not math.isfinite(value):
            raise PanelIngestError(
                f"value must be a finite number, got {self.value!r}; a missing "
                "value must be fixed at the source, not carried as NaN"
            )
        object.__setattr__(self, "value", value)

        currency = self.currency.strip() if isinstance(self.currency, str) else ""
        if not currency:
            raise PanelIngestError("currency is required and cannot be empty")
        object.__setattr__(self, "currency", normalize_currency(currency))

        unit = self.unit.strip() if isinstance(self.unit, str) else ""
        if not unit:
            raise PanelIngestError("unit is required and cannot be empty")
        object.__setattr__(self, "unit", unit)

        if not isinstance(self.metadata, Mapping):
            raise ValueError(
                f"metadata must be a mapping, got {type(self.metadata).__name__}"
            )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class EntityPanel:
    """An immutable, ordered collection of ``PanelObservation``.

    The panel counterpart to ``CashFlowSeries``, on the same non-bar
    ingestion path. Deliberately not a ``pandas.DataFrame`` shaped like an
    OHLC bar frame -- nothing in this class or ``load_panel`` reaches into
    ``backtest/loaders`` or ``backtest/runner``.

    Attributes:
        observations: The observations, ordered by ``(entity_id, date,
            metric)``.
    """

    observations: tuple[PanelObservation, ...] = ()

    def __post_init__(self) -> None:
        """Validate membership and impose a stable (entity, date) order.

        Raises:
            PanelIngestError: If a member is not a ``PanelObservation``.
        """
        obs = tuple(self.observations)
        for item in obs:
            if not isinstance(item, PanelObservation):
                raise PanelIngestError(
                    f"EntityPanel members must be PanelObservation, got "
                    f"{type(item).__name__}"
                )
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(obs, key=lambda o: (o.entity_id, o.date, o.metric))),
        )

    def __iter__(self) -> Iterable[PanelObservation]:
        """Iterate the observations in ``(entity_id, date, metric)`` order.

        Returns:
            An iterator over ``PanelObservation``.
        """
        return iter(self.observations)

    def __len__(self) -> int:
        """Return the number of observations.

        Returns:
            Count of observations, zero for an empty panel.
        """
        return len(self.observations)

    @property
    def is_empty(self) -> bool:
        """Whether the panel holds no observations.

        Returns:
            True when there are zero observations.
        """
        return not self.observations

    def entities(self) -> tuple[str, ...]:
        """Return the distinct entity ids present, sorted.

        Returns:
            Tuple of entity ids; empty for an empty panel.
        """
        return tuple(sorted({o.entity_id for o in self.observations}))

    def metrics(self) -> tuple[str, ...]:
        """Return the distinct metric labels present, sorted.

        Returns:
            Tuple of canonical metric labels; empty for an empty panel.
        """
        return tuple(sorted({o.metric for o in self.observations}))


def _resolve_panel_long_columns(
    header: Sequence[str],
    columns: Mapping[str, str] | None,
    path: Path,
) -> dict[str, str]:
    """Map canonical panel fields onto a long-layout file's column headers.

    Mirrors ``_resolve_columns``'s matching strategy (case-insensitive alias
    lookup via ``_canonical``, with explicit overrides taking precedence) for
    the panel's own field set. ``_resolve_columns`` itself is hard-wired to
    ``DEFAULT_COLUMN_ALIASES`` and cash-flow's ``date``/``amount``/``kind``/
    ``currency`` fields, so it cannot be reused directly for ``entity`` and
    ``metric``.

    Args:
        header: Column names as they appear in the file.
        columns: Explicit overrides, canonical field -> file column name.
        path: File path, used only for error messages.

    Returns:
        Mapping of canonical field name to the file's column name, containing
        only fields that were actually found.

    Raises:
        PanelIngestError: If an explicit override names a column the file
            does not contain, or overrides an unknown field.
    """
    resolved: dict[str, str] = {}
    lookup = {_canonical(col): col for col in header}

    if columns:
        for field_name, source_name in columns.items():
            if field_name not in _PANEL_COLUMN_ALIASES:
                known = ", ".join(sorted(_PANEL_COLUMN_ALIASES))
                raise PanelIngestError(
                    f"{path}: unknown column mapping {field_name!r}; "
                    f"mappable fields are: {known}"
                )
            if source_name not in header:
                raise PanelIngestError(
                    f"{path}: mapped column {source_name!r} for field "
                    f"{field_name!r} is not in the file. Columns present: "
                    f"{', '.join(header)}"
                )
            resolved[field_name] = source_name

    for field_name, aliases in _PANEL_COLUMN_ALIASES.items():
        if field_name in resolved:
            continue
        for alias in aliases:
            if alias in lookup:
                resolved[field_name] = lookup[alias]
                break

    return resolved


def _looks_like_date(text: str, date_format: str | None) -> bool:
    """Best-effort probe for whether a header cell parses as a date.

    Used only during layout inference, by reusing ``_parse_date`` itself
    rather than a second date-parsing routine. A parse failure here means
    "not a date" for inference purposes, not an error to surface.

    Args:
        text: Candidate header cell.
        date_format: ``strptime`` format to try, or ``None`` for ISO-8601.

    Returns:
        True if the text parses as a date under the given format.
    """
    try:
        _parse_date(text, date_format, Path("<layout-inference>"), 0)
        return True
    except CashFlowIngestError:
        return False


def _infer_panel_layout(header: Sequence[str], date_format: str | None, path: Path) -> str:
    """Infer a panel file's layout from its header, or raise if ambiguous.

    A header naming entity/date/metric/value columns is read as ``"long"``.
    Otherwise, a header whose first column is date-like and whose remaining
    columns are not all dates is read as ``"wide_dates_rows"``; a header
    whose first column is entity-like and whose remaining columns are all
    parseable dates is read as ``"wide_entities_rows"``. A header naming a
    ``metric`` column is never read as wide, since a wide table has nowhere
    to put a metric column. Any header that does not unambiguously match one
    shape raises rather than guessing, since silently picking the wrong
    layout mislabels every value with the wrong entity or date.

    Args:
        header: Column names as they appear in the file.
        date_format: ``strptime`` format used to probe header cells for
            ``wide_entities_rows``, or ``None`` to require ISO-8601 there.
        path: File path, used only for error messages.

    Returns:
        One of ``_PANEL_LAYOUTS``.

    Raises:
        PanelIngestError: If the header matches none of the recognised
            shapes.
    """
    date_aliases = {_canonical(a) for a in DEFAULT_COLUMN_ALIASES["date"]}
    entity_aliases = {_canonical(a) for a in _PANEL_ENTITY_ALIASES}
    metric_aliases = {_canonical(a) for a in _PANEL_METRIC_ALIASES}
    value_aliases = {_canonical(a) for a in DEFAULT_COLUMN_ALIASES["amount"]}

    lookup = {_canonical(col) for col in header}
    has_entity = bool(lookup & entity_aliases)
    has_date = bool(lookup & date_aliases)
    has_metric = bool(lookup & metric_aliases)
    has_value = bool(lookup & value_aliases)
    if has_entity and has_date and has_metric and has_value:
        return "long"

    first = _canonical(header[0])
    rest = list(header[1:])
    first_is_date_like = first in date_aliases
    first_is_entity_like = first in entity_aliases
    rest_are_dates = bool(rest) and all(_looks_like_date(col, date_format) for col in rest)

    if first_is_date_like and rest and not rest_are_dates and not has_metric:
        return "wide_dates_rows"
    if first_is_entity_like and rest and rest_are_dates and not has_metric:
        return "wide_entities_rows"

    raise PanelIngestError(
        f"{path}: could not infer a panel layout from the header "
        f"({', '.join(header)}); pass layout='long', layout='wide_dates_rows', "
        "or layout='wide_entities_rows' explicitly"
    )


def _parse_panel_amount(
    raw: str, path: Path, row_number: int, decimal_separator: str | None
) -> float:
    """Parse a panel value cell, reusing ``_parse_amount``.

    Args:
        raw: Raw cell text.
        path: File path, used only for error messages.
        row_number: 1-based data row number, used only for error messages.
        decimal_separator: Declared decimal separator, or ``None`` to infer.

    Returns:
        The parsed float.

    Raises:
        PanelIngestError: If the cell is blank, not numeric, or ambiguously
            grouped -- normalizes ``_parse_amount``'s ``CashFlowIngestError``
            so every error ``load_panel`` raises shares one type.
    """
    try:
        return _parse_amount(raw, path, row_number, decimal_separator)
    except CashFlowIngestError as exc:
        raise PanelIngestError(str(exc)) from exc


def _parse_panel_date(
    raw: str, date_format: str | None, path: Path, row_number: int
) -> date:
    """Parse a panel date cell, reusing ``_parse_date``.

    Args:
        raw: Raw cell text.
        date_format: ``strptime`` format, or ``None`` to require ISO-8601.
        path: File path, used only for error messages.
        row_number: 1-based data row number, used only for error messages.

    Returns:
        The parsed ``datetime.date``.

    Raises:
        PanelIngestError: If the cell is blank or does not parse --
            normalizes ``_parse_date``'s ``CashFlowIngestError`` so every
            error ``load_panel`` raises shares one type.
    """
    try:
        return _parse_date(raw, date_format, path, row_number)
    except CashFlowIngestError as exc:
        raise PanelIngestError(str(exc)) from exc


def _load_panel_long(
    path: Path,
    header: list[str],
    rows: list[dict[str, str]],
    *,
    columns: Mapping[str, str] | None,
    entity: str | None,
    metric: str | None,
    currency: str | None,
    unit: str | None,
    date_format: str | None,
    decimal_separator: str | None,
    metadata_columns: Iterable[str] | None,
) -> "EntityPanel":
    """Parse a long-layout (entity, date, metric, value) panel file.

    Args:
        path: File path, used only for error messages.
        header: Column names as they appear in the file.
        rows: Row dicts as read by ``_read_rows``.
        columns: Explicit column-name overrides; see ``load_panel``.
        entity: Fallback entity id for rows with no entity column.
        metric: Fallback metric label for rows with no metric column.
        currency: Fallback currency for rows with no currency column.
        unit: Fallback unit for rows with no unit column.
        date_format: ``strptime`` format for the date column.
        decimal_separator: Declared decimal separator, or ``None`` to infer.
        metadata_columns: Restrict preserved metadata to these columns.

    Returns:
        An ``EntityPanel``.

    Raises:
        PanelIngestError: If a required column/argument is missing or a row
            fails to parse.
    """
    resolved = _resolve_panel_long_columns(header, columns, path)

    for required in ("date", "value"):
        if required not in resolved:
            raise PanelIngestError(
                f"{path}: required column {required!r} not found. Columns "
                f"present: {', '.join(header)}. Pass columns={{{required!r}: "
                "'<your column>'}} to map it."
            )

    entity_column = resolved.get("entity")
    if entity_column is None and entity is None:
        raise PanelIngestError(
            f"{path}: no entity column found and no entity=... given. "
            f"Columns present: {', '.join(header)}."
        )

    metric_column = resolved.get("metric")
    if metric_column is None and metric is None:
        raise PanelIngestError(
            f"{path}: no metric column found and no metric=... given. "
            f"Columns present: {', '.join(header)}."
        )

    currency_column = resolved.get("currency")
    if currency_column is None and currency is None:
        raise PanelIngestError(
            f"{path}: no currency column found and no currency=... given. "
            "Currency is required; it is never defaulted, because an "
            "unlabelled figure silently corrupts every downstream use."
        )

    unit_column = resolved.get("unit")
    if unit_column is None and unit is None:
        raise PanelIngestError(
            f"{path}: no unit column found and no unit=... given. Unit is "
            "required; it is never defaulted, because an unlabelled figure "
            "silently corrupts every downstream use."
        )

    mapped_columns = set(resolved.values())
    if metadata_columns is None:
        extra_columns = [col for col in header if col not in mapped_columns]
    else:
        wanted = set(metadata_columns)
        missing = wanted - set(header)
        if missing:
            raise PanelIngestError(
                f"{path}: metadata_columns not in file: {', '.join(sorted(missing))}"
            )
        extra_columns = [col for col in header if col in wanted]

    observations: list[PanelObservation] = []
    for offset, row in enumerate(rows):
        row_number = offset + 1
        if all(not (value or "").strip() for value in row.values()):
            continue  # trailing blank line

        row_entity = entity
        if entity_column is not None:
            raw_entity = (row.get(entity_column) or "").strip()
            if raw_entity:
                row_entity = raw_entity
        if not row_entity:
            raise PanelIngestError(
                f"{path} row {row_number}: entity is blank and no entity=... "
                "fallback was given"
            )

        row_metric = metric
        if metric_column is not None:
            raw_metric = (row.get(metric_column) or "").strip()
            if raw_metric:
                row_metric = raw_metric
        if not row_metric:
            raise PanelIngestError(
                f"{path} row {row_number}: metric is blank and no metric=... "
                "fallback was given"
            )

        row_currency = currency
        if currency_column is not None:
            raw_currency = (row.get(currency_column) or "").strip()
            if raw_currency:
                row_currency = raw_currency
        if not row_currency:
            raise PanelIngestError(
                f"{path} row {row_number}: currency is blank and no "
                "currency=... fallback was given"
            )

        row_unit = unit
        if unit_column is not None:
            raw_unit = (row.get(unit_column) or "").strip()
            if raw_unit:
                row_unit = raw_unit
        if not row_unit:
            raise PanelIngestError(
                f"{path} row {row_number}: unit is blank and no unit=... "
                "fallback was given"
            )

        value = _parse_panel_amount(
            row.get(resolved["value"], ""), path, row_number, decimal_separator
        )

        metadata: dict[str, Any] = {
            col: row[col] for col in extra_columns if (row.get(col) or "").strip()
        }
        metadata["source_file"] = str(path)
        metadata["source_row"] = row_number

        try:
            observations.append(
                PanelObservation(
                    entity_id=row_entity,
                    date=_parse_panel_date(
                        row.get(resolved["date"], ""), date_format, path, row_number
                    ),
                    metric=row_metric,
                    value=value,
                    currency=row_currency,
                    unit=row_unit,
                    metadata=metadata,
                )
            )
        except PanelIngestError:
            raise
        except ValueError as exc:
            raise PanelIngestError(f"{path} row {row_number}: {exc}") from exc

    logger.info("loaded %d panel observations from %s (layout=long)", len(observations), path)
    return EntityPanel(observations=tuple(observations))


def _load_panel_wide(
    path: Path,
    header: list[str],
    rows: list[dict[str, str]],
    *,
    layout: str,
    metric: str | None,
    currency: str | None,
    unit: str | None,
    date_format: str | None,
    decimal_separator: str | None,
) -> "EntityPanel":
    """Parse a wide-layout panel file.

    ``layout="wide_dates_rows"``: the first column is the observation date
    and every other column is an entity id. ``layout="wide_entities_rows"``:
    the first column is the entity id and every other column header is
    itself a date. A blank cell is treated as "no observation for that
    entity/date", not as zero or an error -- a wide grid legitimately has
    holes, and fabricating a value for one would be worse than omitting it.

    Args:
        path: File path, used only for error messages.
        header: Column names as they appear in the file.
        rows: Row dicts as read by ``_read_rows``.
        layout: ``"wide_dates_rows"`` or ``"wide_entities_rows"``.
        metric: The single metric label every cell in this file represents.
        currency: The currency for every value in this file.
        unit: The unit for every value in this file.
        date_format: ``strptime`` format for date cells/headers.
        decimal_separator: Declared decimal separator, or ``None`` to infer.

    Returns:
        An ``EntityPanel``.

    Raises:
        PanelIngestError: If ``metric``/``currency``/``unit`` is missing, the
            file has fewer than two columns, a column header in
            ``wide_entities_rows`` is not a usable date, or a cell fails to
            parse.
    """
    if metric is None:
        raise PanelIngestError(
            f"{path}: layout={layout!r} needs metric=... -- a wide table has "
            "nowhere to put a metric label; every cell already shares its "
            "row's and column's identity"
        )
    if currency is None:
        raise PanelIngestError(
            f"{path}: layout={layout!r} needs currency=... -- a wide table "
            "has no currency column, and currency is never defaulted"
        )
    if unit is None:
        raise PanelIngestError(
            f"{path}: layout={layout!r} needs unit=... -- a wide table has "
            "no unit column, and unit is never defaulted"
        )
    if len(header) < 2:
        raise PanelIngestError(
            f"{path}: layout={layout!r} needs at least one column besides "
            f"the first (row-label) column. Columns present: {', '.join(header)}"
        )

    row_label_column = header[0]
    series_columns = list(header[1:])

    column_dates: dict[str, date] = {}
    if layout == "wide_entities_rows":
        for column_name in series_columns:
            try:
                column_dates[column_name] = _parse_panel_date(
                    column_name, date_format, path, row_number=0
                )
            except PanelIngestError as exc:
                raise PanelIngestError(
                    f"{path}: column header {column_name!r} is not a usable "
                    f"date ({exc}); wide_entities_rows requires every column "
                    "after the first to be a date, or pass layout='long' "
                    "with columns=... instead"
                ) from exc

    observations: list[PanelObservation] = []
    for offset, row in enumerate(rows):
        row_number = offset + 1
        if all(not (value or "").strip() for value in row.values()):
            continue  # trailing blank line

        row_label_raw = (row.get(row_label_column) or "").strip()
        if not row_label_raw:
            raise PanelIngestError(f"{path} row {row_number}: {row_label_column!r} is blank")

        row_date = (
            _parse_panel_date(row_label_raw, date_format, path, row_number)
            if layout == "wide_dates_rows"
            else None
        )
        row_entity = row_label_raw if layout == "wide_entities_rows" else None

        for column_name in series_columns:
            raw_value = row.get(column_name, "")
            if not (raw_value or "").strip():
                continue  # hole in the grid: no observation, not zero

            value = _parse_panel_amount(raw_value, path, row_number, decimal_separator)
            entity_id = column_name.strip() if layout == "wide_dates_rows" else row_entity
            obs_date = row_date if layout == "wide_dates_rows" else column_dates[column_name]

            metadata = {"source_file": str(path), "source_row": row_number}
            try:
                observations.append(
                    PanelObservation(
                        entity_id=entity_id,
                        date=obs_date,
                        metric=metric,
                        value=value,
                        currency=currency,
                        unit=unit,
                        metadata=metadata,
                    )
                )
            except PanelIngestError:
                raise
            except ValueError as exc:
                raise PanelIngestError(f"{path} row {row_number}: {exc}") from exc

    logger.info(
        "loaded %d panel observations from %s (layout=%s)", len(observations), path, layout
    )
    return EntityPanel(observations=tuple(observations))


def load_panel(
    path: str | Path,
    *,
    layout: str | None = None,
    columns: Mapping[str, str] | None = None,
    entity: str | None = None,
    metric: str | None = None,
    currency: str | None = None,
    unit: str | None = None,
    date_format: str | None = None,
    decimal_separator: str | None = None,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    metadata_columns: Iterable[str] | None = None,
) -> EntityPanel:
    """Load an entity x date x metric panel file into an ``EntityPanel``.

    The ingest module's generic counterpart to ``load_cashflows``, for data
    that is not a signed cash movement -- a NAV series, an exposure or
    headcount table, any per-entity time series a bar engine cannot
    represent. It shares every parsing rule with ``load_cashflows``: dates
    must be ISO-8601 or given an explicit ``date_format``, numeric grouping
    that is genuinely ambiguous must be resolved with ``decimal_separator``,
    and a required field that is missing raises rather than returning
    ``None`` or a silently empty result.

    Three layouts are supported and never guessed silently:

    * ``"long"``: one row per (entity, date, metric[, currency, unit])
      observation, with a column for each.
    * ``"wide_dates_rows"``: one row per date, one column per entity, every
      value sharing a single ``metric`` (required via the ``metric``
      argument, since a wide table has nowhere to put a metric label).
    * ``"wide_entities_rows"``: one row per entity, one column per date,
      values sharing a single ``metric`` in the same way.

    When ``layout`` is omitted, it is inferred from the header -- see
    ``_infer_panel_layout``. Layout inference looks only at the raw header,
    not at ``columns=...``; a file with exotic column names should pass
    ``layout="long"`` explicitly together with ``columns=...`` rather than
    rely on inference.

    A wide layout's blank cell means "no observation for that entity/date"
    and is skipped, not treated as zero: a grid legitimately has holes.

    Args:
        path: Path to the file. ``.csv``, ``.tsv``, and ``.txt`` are
            recognised; any other suffix requires an explicit ``delimiter``.
        layout: ``"long"``, ``"wide_dates_rows"``, or ``"wide_entities_rows"``.
            ``None`` to infer from the header.
        columns: Explicit mapping of canonical field to file column name for
            the ``"long"`` layout. Canonical fields are ``entity``, ``date``,
            ``metric``, ``value``, ``currency``, ``unit``.
        entity: Fallback entity id for ``"long"`` rows with no entity column.
            Not used by the wide layouts, where each row/column already
            names its own entity.
        metric: Fallback metric label for ``"long"`` rows with no metric
            column; required for both wide layouts.
        currency: Currency for every row. Required when the file has no
            currency column (``"long"``) or always (wide layouts).
        unit: Unit label for every row. Required when the file has no unit
            column (``"long"``) or always (wide layouts).
        date_format: ``strptime`` format for date cells -- the date column in
            ``"long"``/``"wide_dates_rows"``, or the date-valued column
            headers in ``"wide_entities_rows"``. Omit only when the dates are
            ISO-8601.
        decimal_separator: ``"."`` or ``","``; needed only for ambiguous
            grouped numbers such as a bare ``"1,234"``.
        delimiter: Field delimiter; inferred from the suffix when omitted.
        encoding: Text encoding of the file.
        metadata_columns: Restrict preserved metadata to these ``"long"``
            columns. By default every unmapped column is preserved. Not
            applicable to wide layouts, which have no unmapped columns.

    Returns:
        An ``EntityPanel`` ordered by ``(entity_id, date, metric)``. A
        ``"long"`` file with a header but no data rows yields an empty panel,
        matching ``load_cashflows``.

    Raises:
        PanelIngestError: If the file is missing, unreadable, or has no
            header row; the layout cannot be determined or is invalid; a
            required column or argument is absent; or any cell fails to
            parse.
        ValueError: If ``decimal_separator`` is neither ``"."`` nor ``","``.
    """
    if decimal_separator is not None and decimal_separator not in _DECIMAL_SEPARATORS:
        raise ValueError(
            f"decimal_separator must be one of {_DECIMAL_SEPARATORS}, "
            f"got {decimal_separator!r}"
        )
    if layout is not None and layout not in _PANEL_LAYOUTS:
        raise PanelIngestError(f"layout must be one of {_PANEL_LAYOUTS}, got {layout!r}")

    path = Path(path).expanduser()
    try:
        header, rows = _read_rows(path, delimiter, encoding)
    except CashFlowIngestError as exc:
        raise PanelIngestError(str(exc)) from exc

    resolved_layout = layout or _infer_panel_layout(header, date_format, path)

    if resolved_layout == "long":
        return _load_panel_long(
            path,
            header,
            rows,
            columns=columns,
            entity=entity,
            metric=metric,
            currency=currency,
            unit=unit,
            date_format=date_format,
            decimal_separator=decimal_separator,
            metadata_columns=metadata_columns,
        )
    return _load_panel_wide(
        path,
        header,
        rows,
        layout=resolved_layout,
        metric=metric,
        currency=currency,
        unit=unit,
        date_format=date_format,
        decimal_separator=decimal_separator,
    )
