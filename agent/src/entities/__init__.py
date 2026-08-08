"""Entity and irregular cash-flow spine for holdings that have no daily bar.

This package is a **parallel path** to ``backtest/``, not an extension of it.
The bar path is deliberately narrow: ``backtest.runner._PRICE_PANEL_COLUMNS``
fixes the panel to OHLCV-style fields and
``backtest.loaders.local_loader._normalize_columns`` rejects any file without
``{open, high, low, close}``. That narrowness is a safety property -- if a
``nav`` column were allowed to reach a bar engine it would be priced as a
close, producing a confident wrong answer.

So nothing here feeds a ``BaseEngine``. A ``CashFlowSeries`` is an ordered set
of dated amounts with a currency and a sign convention, consumed by
cash-flow-native analytics rather than by a bar simulator.
"""

from src.entities.cashflow import (
    CashFlow,
    CashFlowSeries,
    CurrencyMismatchError,
    KIND_DIRECTION,
    VALUATION_KINDS,
    normalize_kind,
)
from src.entities.ingest import CashFlowIngestError, load_cashflows
from src.entities.models import (
    Bond,
    Entity,
    EntityType,
    Fund,
    FundStructure,
    Instrument,
    Security,
    SecurityType,
    normalize_currency,
    normalize_date,
)

__all__ = [
    "Bond",
    "CashFlow",
    "CashFlowIngestError",
    "CashFlowSeries",
    "CurrencyMismatchError",
    "Entity",
    "EntityType",
    "Fund",
    "FundStructure",
    "Instrument",
    "KIND_DIRECTION",
    "Security",
    "SecurityType",
    "VALUATION_KINDS",
    "load_cashflows",
    "normalize_currency",
    "normalize_date",
    "normalize_kind",
]
