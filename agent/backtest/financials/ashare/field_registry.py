"""Registry for Tushare A-share financial statement fields.

The registry is built from bundled local Tushare markdown reference files so
it does not depend on live web docs. It provides three things:

1. Table-level API metadata for the five supported statement tables.
2. Field-to-table ownership lookup, including ambiguous shared fields.
3. A minimal query-plan helper that groups requested fields by table.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Iterable, Mapping

from backtest.financials.contracts import FinancialCrossSectionCapability, FinancialQueryPlan


SUPPORTED_FINANCIAL_TABLES = (
    "income",
    "balancesheet",
    "cashflow",
    "express",
    "fina_indicator",
)

_REFERENCE_FILES = {
    "income": "利润表.md",
    "balancesheet": "资产负债表.md",
    "cashflow": "现金流量表.md",
    "express": "业绩快报.md",
    "fina_indicator": "财务指标数据.md",
}

_KEY_COLUMN_ORDER = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "period",
    "report_type",
    "comp_type",
    "end_type",
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENT_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_ROOT = _AGENT_ROOT / "src" / "skills"
_REFERENCE_ROOT = _SKILLS_ROOT / "tushare" / "references" / "股票数据" / "财务数据"


class FinancialFieldRegistryError(RuntimeError):
    """Base error for financial field registry issues."""


class UnknownFinancialFieldError(KeyError):
    """Raised when a requested field is absent from the registry."""


class AmbiguousFinancialFieldError(ValueError):
    """Raised when a field belongs to multiple tables and no preference exists."""


@dataclass(frozen=True)
class ParameterMetadata:
    """Input-parameter metadata for a Tushare table."""

    name: str
    param_type: str
    required: bool
    description: str


@dataclass(frozen=True)
class FieldMetadata:
    """Output-field metadata for a Tushare table."""

    name: str
    field_type: str
    description: str
    default_visible: bool | None


@dataclass(frozen=True)
class TableMetadata:
    """Interface metadata for a supported Tushare financial table."""

    name: str
    api_name: str
    vip_api_name: str | None
    description: str
    min_points: int | None
    vip_min_points: int | None
    reference_path: Path
    repo_path: str
    mcp_read_file_path: str
    input_parameters: dict[str, ParameterMetadata]
    output_fields: dict[str, FieldMetadata]
    key_columns: tuple[str, ...]

    @property
    def supports_cross_sectional_query(self) -> bool:
        """Whether a quarterly full-market query requires a vip endpoint."""
        return self.vip_api_name is not None


@dataclass(frozen=True)
class FinancialFieldRegistry:
    """Loaded financial-field registry."""

    tables: dict[str, TableMetadata]
    field_to_tables: dict[str, tuple[str, ...]]

    def get_table(self, table_name: str) -> TableMetadata:
        """Return metadata for a single table."""
        try:
            return self.tables[table_name]
        except KeyError as exc:
            known = ", ".join(sorted(self.tables))
            raise KeyError(f"Unknown financial table '{table_name}'. Known: {known}") from exc

    def has_field(self, field_name: str) -> bool:
        """Return whether a field exists in any supported table."""
        return field_name in self.field_to_tables

    def get_field_tables(self, field_name: str) -> tuple[str, ...]:
        """Return all owner tables for a field."""
        return self.field_to_tables.get(field_name, ())

    def assess_cross_sectional_query(
        self,
        query_plan: FinancialQueryPlan,
    ) -> FinancialCrossSectionCapability:
        """Summarize whether a query plan can run via VIP period cross-sections."""
        supported_tables: list[str] = []
        unsupported_tables: list[str] = []
        required_points_by_table: dict[str, int] = {}

        for table_name in query_plan.query_fields:
            table = self.get_table(table_name)
            if not table.supports_cross_sectional_query:
                unsupported_tables.append(table_name)
                continue

            supported_tables.append(table_name)
            required_points_by_table[table_name] = table.vip_min_points or table.min_points or 0

        return FinancialCrossSectionCapability(
            supported_tables=tuple(supported_tables),
            unsupported_tables=tuple(unsupported_tables),
            required_points_by_table=required_points_by_table,
            required_points=max(required_points_by_table.values(), default=0),
        )

    def get_field_metadata(
        self,
        field_name: str,
        *,
        table_name: str | None = None,
    ) -> FieldMetadata:
        """Return field metadata, requiring a table for ambiguous fields."""
        owner_table = table_name
        if owner_table is None:
            owners = self.get_field_tables(field_name)
            if not owners:
                raise UnknownFinancialFieldError(field_name)
            if len(owners) > 1:
                raise AmbiguousFinancialFieldError(
                    f"Field '{field_name}' belongs to multiple tables: {', '.join(owners)}"
                )
            owner_table = owners[0]

        table = self.get_table(owner_table)
        try:
            return table.output_fields[field_name]
        except KeyError as exc:
            raise UnknownFinancialFieldError(
                f"Field '{field_name}' is not present in table '{owner_table}'"
            ) from exc

    def build_query_plan(
        self,
        fields: Iterable[str],
        *,
        preferred_tables: Mapping[str, str] | None = None,
        include_key_columns: bool = True,
        strict: bool = True,
    ) -> FinancialQueryPlan:
        """Group fields by table and attach key columns for each query.

        Args:
            fields: Requested financial fields.
            preferred_tables: Optional per-field override for ambiguous fields.
            include_key_columns: Whether to prepend each table's key columns.
            strict: Whether to raise on unknown or ambiguous fields.
        """
        preferred_tables = preferred_tables or {}
        deduped_fields = tuple(dict.fromkeys(field for field in fields if field))

        requested_fields: dict[str, list[str]] = {}
        ambiguous_fields: dict[str, tuple[str, ...]] = {}
        unknown_fields: list[str] = []

        for field_name in deduped_fields:
            owners = self.get_field_tables(field_name)
            if not owners:
                unknown_fields.append(field_name)
                continue

            preferred_table = preferred_tables.get(field_name)
            if preferred_table is not None:
                if preferred_table not in owners:
                    raise AmbiguousFinancialFieldError(
                        f"Preferred table '{preferred_table}' does not own field '{field_name}'. "
                        f"Owners: {', '.join(owners)}"
                    )
                chosen_table = preferred_table
            elif len(owners) == 1:
                chosen_table = owners[0]
            else:
                ambiguous_fields[field_name] = owners
                continue

            requested_fields.setdefault(chosen_table, []).append(field_name)

        if strict and unknown_fields:
            raise UnknownFinancialFieldError(
                f"Unknown financial field(s): {', '.join(unknown_fields)}"
            )
        if strict and ambiguous_fields:
            rendered = "; ".join(
                f"{name} -> {', '.join(tables)}" for name, tables in ambiguous_fields.items()
            )
            raise AmbiguousFinancialFieldError(
                f"Ambiguous financial field(s): {rendered}"
            )

        requested_tuples = {
            table_name: tuple(values)
            for table_name, values in requested_fields.items()
        }

        auto_included_keys: dict[str, tuple[str, ...]] = {}
        query_fields: dict[str, tuple[str, ...]] = {}
        for table_name, requested in requested_tuples.items():
            table = self.get_table(table_name)
            if include_key_columns:
                keys = tuple(key for key in table.key_columns if key not in requested)
            else:
                keys = ()
            auto_included_keys[table_name] = keys
            query_fields[table_name] = (*keys, *requested)

        return FinancialQueryPlan(
            requested_fields=requested_tuples,
            query_fields=query_fields,
            auto_included_keys=auto_included_keys,
            ambiguous_fields=ambiguous_fields,
            unknown_fields=tuple(unknown_fields),
        )


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _split_markdown_row(line)
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _extract_markdown_table(text: str, section_title: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    try:
        start_index = next(
            index for index, line in enumerate(lines) if line.strip() == section_title
        )
    except StopIteration as exc:
        raise FinancialFieldRegistryError(
            f"Section '{section_title}' not found in local reference"
        ) from exc

    index = start_index + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return []

    headers = _split_markdown_row(lines[index])
    index += 1

    rows: list[dict[str, str]] = []
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            break
        if "|" not in line:
            break
        if _is_separator_row(line):
            index += 1
            continue

        cells = _split_markdown_row(line)
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        row = {header: cells[pos] for pos, header in enumerate(headers)}
        rows.append(row)
        index += 1

    return rows


def _parse_points(text: str) -> int | None:
    match = re.search(r"(?:积分|权限)：.*?至少(\d+)积分", text)
    if match:
        return int(match.group(1))
    return None


def _parse_vip_points(text: str) -> int | None:
    match = re.search(r"需积(?:攒)?(\d+)积分", text)
    if match:
        return int(match.group(1))
    return None


def _parse_table_metadata(table_name: str, reference_path: Path) -> TableMetadata:
    text = reference_path.read_text(encoding="utf-8")

    api_match = re.search(r"接口：([a-zA-Z_][a-zA-Z0-9_]*)", text)
    if api_match is None:
        raise FinancialFieldRegistryError(
            f"Could not parse api name from reference: {reference_path}"
        )
    api_name = api_match.group(1)

    description_match = re.search(r"描述：(.+)", text)
    description = description_match.group(1).strip() if description_match else ""

    vip_match = re.search(r"请使用([a-zA-Z_][a-zA-Z0-9_]*)接口", text)
    vip_api_name = vip_match.group(1) if vip_match else None

    input_rows = _extract_markdown_table(text, "**输入参数**")
    output_rows = _extract_markdown_table(text, "**输出参数**")

    input_parameters = {
        row["名称"]: ParameterMetadata(
            name=row["名称"],
            param_type=row.get("类型", ""),
            required=row.get("必选", "").upper() == "Y",
            description=row.get("描述", ""),
        )
        for row in input_rows
        if row.get("名称")
    }

    output_fields = {
        row["名称"]: FieldMetadata(
            name=row["名称"],
            field_type=row.get("类型", ""),
            description=row.get("描述", ""),
            default_visible=(
                None
                if "默认显示" not in row
                else row.get("默认显示", "").upper() == "Y"
            ),
        )
        for row in output_rows
        if row.get("名称")
    }

    key_columns = tuple(
        column for column in _KEY_COLUMN_ORDER if column in output_fields
    )
    repo_path = reference_path.relative_to(_REPO_ROOT).as_posix()
    skills_relative = reference_path.relative_to(_SKILLS_ROOT).as_posix()

    return TableMetadata(
        name=table_name,
        api_name=api_name,
        vip_api_name=vip_api_name,
        description=description,
        min_points=_parse_points(text),
        vip_min_points=_parse_vip_points(text),
        reference_path=reference_path,
        repo_path=repo_path,
        mcp_read_file_path=f"skills/{skills_relative}",
        input_parameters=input_parameters,
        output_fields=output_fields,
        key_columns=key_columns,
    )


def _build_registry() -> FinancialFieldRegistry:
    tables: dict[str, TableMetadata] = {}
    field_to_tables: dict[str, list[str]] = {}

    for table_name in SUPPORTED_FINANCIAL_TABLES:
        reference_path = _REFERENCE_ROOT / _REFERENCE_FILES[table_name]
        if not reference_path.exists():
            raise FinancialFieldRegistryError(
                f"Local reference not found for table '{table_name}': {reference_path}"
            )

        table_metadata = _parse_table_metadata(table_name, reference_path)
        tables[table_name] = table_metadata

        for field_name in table_metadata.output_fields:
            owners = field_to_tables.setdefault(field_name, [])
            owners.append(table_name)

    return FinancialFieldRegistry(
        tables=tables,
        field_to_tables={
            field_name: tuple(owners)
            for field_name, owners in field_to_tables.items()
        },
    )


@lru_cache(maxsize=1)
def get_financial_field_registry() -> FinancialFieldRegistry:
    """Load and cache the financial field registry."""
    return _build_registry()


def get_table_metadata(table_name: str) -> TableMetadata:
    """Convenience wrapper for table metadata lookup."""
    return get_financial_field_registry().get_table(table_name)


def get_field_tables(field_name: str) -> tuple[str, ...]:
    """Convenience wrapper for field ownership lookup."""
    return get_financial_field_registry().get_field_tables(field_name)


def build_financial_query_plan(
    fields: Iterable[str],
    *,
    preferred_tables: Mapping[str, str] | None = None,
    include_key_columns: bool = True,
    strict: bool = True,
) -> FinancialQueryPlan:
    """Convenience wrapper for grouped query planning."""
    return get_financial_field_registry().build_query_plan(
        fields,
        preferred_tables=preferred_tables,
        include_key_columns=include_key_columns,
        strict=strict,
    )


def assess_cross_sectional_query_capability(
    query_plan: FinancialQueryPlan,
) -> FinancialCrossSectionCapability:
    """Convenience wrapper for VIP period cross-sectional capability checks."""
    return get_financial_field_registry().assess_cross_sectional_query(query_plan)