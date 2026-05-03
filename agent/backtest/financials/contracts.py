"""Shared contracts for market-scoped financial data integrations.

These contracts define the smallest cross-market boundary that the runtime
cares about today:

* registry-backed field lookup and query planning
* prompt/source inference outputs
* raw financial loading
* point-in-time projection back onto price frames

Market packages such as ``backtest.financials.ashare`` implement these
contracts and expose a single runtime bundle so future markets can slot in
without depending on A-share module names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, TypeAlias, runtime_checkable

import pandas as pd


FinancialDataMap: TypeAlias = Mapping[str, pd.DataFrame]
FinancialTableMap: TypeAlias = Mapping[str, pd.DataFrame]
FinancialTableParams: TypeAlias = Mapping[str, Mapping[str, Any]]
ReportTypePriorities: TypeAlias = Mapping[str, Mapping[Any, int]]


@dataclass(frozen=True)
class FinancialQueryPlan:
    """Minimal grouped query plan for requested financial fields."""

    requested_fields: dict[str, tuple[str, ...]]
    query_fields: dict[str, tuple[str, ...]]
    auto_included_keys: dict[str, tuple[str, ...]]
    ambiguous_fields: dict[str, tuple[str, ...]]
    unknown_fields: tuple[str, ...]


@dataclass(frozen=True)
class FinancialFieldInferenceResult:
    """Inference result from prompt text and/or source analysis."""

    prompt_fields: tuple[str, ...]
    source_fields: tuple[str, ...]
    combined_fields: tuple[str, ...]
    query_plan: FinancialQueryPlan


@dataclass(frozen=True)
class FinancialCrossSectionCapability:
    """Capability summary for VIP period cross-sectional financial queries."""

    supported_tables: tuple[str, ...]
    unsupported_tables: tuple[str, ...]
    required_points_by_table: dict[str, int]
    required_points: int

    @property
    def supported(self) -> bool:
        return not self.unsupported_tables


@runtime_checkable
class FinancialFieldRegistryProtocol(Protocol):
    """Minimal registry contract shared by market-specific implementations."""

    @property
    def tables(self) -> Mapping[str, Any]: ...

    @property
    def field_to_tables(self) -> Mapping[str, tuple[str, ...]]: ...

    def get_table(self, table_name: str) -> Any: ...

    def has_field(self, field_name: str) -> bool: ...

    def get_field_tables(self, field_name: str) -> tuple[str, ...]: ...

    def assess_cross_sectional_query(
        self,
        query_plan: FinancialQueryPlan,
    ) -> FinancialCrossSectionCapability: ...

    def build_query_plan(
        self,
        fields: Iterable[str],
        *,
        preferred_tables: Mapping[str, str] | None = None,
        include_key_columns: bool = True,
        strict: bool = True,
    ) -> FinancialQueryPlan: ...


@runtime_checkable
class RawFinancialLoaderProtocol(Protocol):
    """Minimal raw-loader contract for market-scoped financial records."""

    def fetch_for_codes(
        self,
        query_plan: FinancialQueryPlan,
        *,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
        table_params: FinancialTableParams | None = None,
    ) -> dict[str, pd.DataFrame]: ...

    def fetch_for_period(
        self,
        query_plan: FinancialQueryPlan,
        *,
        period: str,
        table_params: FinancialTableParams | None = None,
    ) -> dict[str, pd.DataFrame]: ...


class PromptFieldInferencerProtocol(Protocol):
    """Callable contract for prompt-to-field inference."""

    def __call__(self, prompt: str) -> tuple[str, ...]: ...


class SourceFieldInferencerProtocol(Protocol):
    """Callable contract for source-to-field inference."""

    def __call__(self, source: str) -> tuple[str, ...]: ...


class FileFieldInferencerProtocol(Protocol):
    """Callable contract for file-to-field inference."""

    def __call__(self, file_path: str | Path) -> tuple[str, ...]: ...


class CombinedFieldInferencerProtocol(Protocol):
    """Callable contract for combined prompt/source inference."""

    def __call__(
        self,
        *,
        prompt: str = "",
        source: str = "",
        preferred_tables: Mapping[str, str] | None = None,
        include_key_columns: bool = True,
    ) -> FinancialFieldInferenceResult: ...


class PitFrameAssemblerProtocol(Protocol):
    """Callable contract for projecting raw statement rows onto trade dates."""

    def __call__(
        self,
        trade_index: pd.DatetimeIndex,
        records: pd.DataFrame,
        *,
        fields: list[str] | tuple[str, ...],
        report_type_priority: Mapping[Any, int] | None = None,
    ) -> pd.DataFrame: ...


class FinancialDataMapEnricherProtocol(Protocol):
    """Callable contract for injecting financial columns into price data maps."""

    def __call__(
        self,
        data_map: FinancialDataMap,
        raw_tables: FinancialTableMap,
        query_plan: FinancialQueryPlan,
        *,
        report_type_priorities: ReportTypePriorities | None = None,
    ) -> dict[str, pd.DataFrame]: ...


FinancialLoaderFactory: TypeAlias = Callable[..., RawFinancialLoaderProtocol]


@dataclass(frozen=True)
class MarketFinancialRuntime:
    """Market-scoped bundle of the financial integration boundary."""

    market: str
    registry: FinancialFieldRegistryProtocol
    infer_fields_from_prompt: PromptFieldInferencerProtocol
    infer_fields_from_source: SourceFieldInferencerProtocol
    infer_fields_from_file: FileFieldInferencerProtocol
    infer_fields: CombinedFieldInferencerProtocol
    loader_factory: FinancialLoaderFactory
    assemble_pit_frame: PitFrameAssemblerProtocol
    enrich_data_map: FinancialDataMapEnricherProtocol