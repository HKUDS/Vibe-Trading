"""A-share financial data helpers for backtest runtimes."""

from __future__ import annotations

from functools import lru_cache

from backtest.financials.contracts import MarketFinancialRuntime
from backtest.financials.ashare.field_inference import (
	infer_financial_fields,
	infer_financial_fields_from_file,
	infer_financial_fields_from_prompt,
	infer_financial_fields_from_source,
)
from backtest.financials.ashare.field_registry import get_financial_field_registry
from backtest.financials.ashare.pit_assembler import assemble_pit_frame, enrich_data_map_with_financials
from backtest.financials.ashare.tushare_loader import TushareFinancialLoader


@lru_cache(maxsize=1)
def get_ashare_financial_runtime() -> MarketFinancialRuntime:
	"""Return the A-share implementation bundle for the shared financial boundary."""
	return MarketFinancialRuntime(
		market="a_share",
		registry=get_financial_field_registry(),
		infer_fields_from_prompt=infer_financial_fields_from_prompt,
		infer_fields_from_source=infer_financial_fields_from_source,
		infer_fields_from_file=infer_financial_fields_from_file,
		infer_fields=infer_financial_fields,
		loader_factory=TushareFinancialLoader,
		assemble_pit_frame=assemble_pit_frame,
		enrich_data_map=enrich_data_map_with_financials,
	)


__all__ = ["get_ashare_financial_runtime"]
