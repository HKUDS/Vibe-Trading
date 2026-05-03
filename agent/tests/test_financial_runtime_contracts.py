"""Tests for the shared market-scoped financial runtime contracts."""

from __future__ import annotations

from unittest.mock import MagicMock

from backtest.financials.ashare import get_ashare_financial_runtime
from backtest.financials.contracts import (
    FinancialFieldRegistryProtocol,
    RawFinancialLoaderProtocol,
)


class TestAshareFinancialRuntime:
    def test_exposes_minimal_runtime_bundle(self) -> None:
        runtime = get_ashare_financial_runtime()

        assert runtime.market == "a_share"
        assert isinstance(runtime.registry, FinancialFieldRegistryProtocol)
        assert runtime.infer_fields_from_prompt("资产总计、有形资产") == (
            "total_assets",
            "tangible_asset",
        )

        loader = runtime.loader_factory(api=MagicMock())
        assert isinstance(loader, RawFinancialLoaderProtocol)
        assert callable(runtime.assemble_pit_frame)
        assert callable(runtime.enrich_data_map)