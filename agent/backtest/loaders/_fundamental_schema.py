"""Unified fundamental field schema and SEC XBRL concept aliases.

This module is deliberately metadata-only. Callers use ``SEC_CONCEPT_MAP`` to
extract sparse reported facts; when no concept hits, the caller must emit NaN
for that field and log the missing alias coverage. This module does not log or
fabricate fallback values.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import pandas as pd

FieldKind = Literal["raw", "derived"]
RawFieldSpec = dict[str, object]
DerivedCompute = Callable[[dict[str, pd.Series]], pd.Series]
DerivedFieldSpec = dict[str, object]


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide two aligned series, returning NaN where the denominator is zero."""
    clean_denominator = denominator.astype("float64").mask(denominator == 0)
    return numerator.astype("float64") / clean_denominator


RAW_FIELDS: dict[str, RawFieldSpec] = {
    "revenue": {
        "statement": "IS",
        "description": "Revenue / net sales.",
    },
    "cogs": {
        "statement": "IS",
        "description": "Cost of goods sold or cost of revenue.",
    },
    "gross_profit": {
        "statement": "IS",
        "description": "Gross profit; derived as revenue minus cogs when not directly reported.",
        "dependencies": ["revenue", "cogs"],
        "compute": lambda data: data["revenue"] - data["cogs"],
    },
    "operating_income": {
        "statement": "IS",
        "description": "Operating income or loss.",
    },
    "net_income": {
        "statement": "IS",
        "description": "Net income or loss attributable to the reporting entity.",
    },
    "total_assets": {
        "statement": "BS",
        "description": "Total assets.",
    },
    "total_equity": {
        "statement": "BS",
        "description": "Total shareholders' equity.",
    },
    "total_debt": {
        "statement": "BS",
        "description": "Interest-bearing debt; aggregate debt concept when present, otherwise loader may union current and noncurrent debt concepts.",
    },
    "cash": {
        "statement": "BS",
        "description": "Cash and cash equivalents.",
    },
    "shares_diluted": {
        "statement": "IS/cover",
        "description": "Weighted-average diluted shares outstanding.",
    },
    "cfo": {
        "statement": "CF",
        "description": "Net cash provided by or used in operating activities.",
    },
    "capex": {
        "statement": "CF",
        "description": "Capital expenditures for property, plant, equipment, and similar productive assets.",
    },
}


# Ordered by priority. SEC extraction should union concepts across aliases, then
# keep the first filed value per period_end for PIT safety. The revenue order is
# intentionally new-standard first: recent AAPL filings report revenue under
# RevenueFromContractWithCustomer... rather than the old Revenues concept.
SEC_CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "cogs": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "total_assets": [
        "Assets",
    ],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    # US-GAAP has both aggregate and split debt concepts. Prefer aggregate debt
    # when reported; otherwise a future loader should combine current and
    # noncurrent concepts instead of treating one leg as total debt.
    "total_debt": [
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
    ],
    # Cash concept choice varies by industry and restricted-cash presentation.
    # The first concept is the common operating-company aggregate; the rest keep
    # banks and restricted-cash filers from hard-missing in Phase 1.
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "Cash",
        "CashAndDueFromBanks",
    ],
    "shares_diluted": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageDilutedSharesOutstanding",
    ],
    "cfo": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    # Capex is usually reported as PPE purchases. Some filers include broader
    # productive-asset or PPE-plus-intangibles concepts; they are lower priority
    # because they may not be strictly comparable to plain PPE capex.
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
    ],
}


DERIVED_FIELDS: dict[str, DerivedFieldSpec] = {
    "roe": {
        "dependencies": ["net_income", "total_equity"],
        "compute": lambda data: _safe_divide(data["net_income"], data["total_equity"]),
    },
    "roa": {
        "dependencies": ["net_income", "total_assets"],
        "compute": lambda data: _safe_divide(data["net_income"], data["total_assets"]),
    },
    "gross_profitability": {
        "dependencies": ["gross_profit", "total_assets"],
        "compute": lambda data: _safe_divide(data["gross_profit"], data["total_assets"]),
    },
    # Annual semantics: input is one observation per annual period_end, sorted by
    # period_end. Growth is period-over-period, value / value.shift(1) - 1.
    # Quarterly or TTM callers must pre-aggregate before applying this formula.
    "asset_growth": {
        "dependencies": ["total_assets"],
        "compute": lambda data: (
            data["total_assets"].astype("float64") / data["total_assets"].astype("float64").shift(1) - 1
        ),
    },
    "accruals": {
        "dependencies": ["net_income", "cfo", "total_assets"],
        "compute": lambda data: _safe_divide(
            data["net_income"] - data["cfo"],
            data["total_assets"],
        ),
    },
    "leverage": {
        "dependencies": ["total_debt", "total_equity"],
        "compute": lambda data: _safe_divide(data["total_debt"], data["total_equity"]),
    },
}

# Price-dependent value factors need market_cap = price * shares and therefore
# live in factor files after fundamental and price panels have been aligned.
# Do not add earnings_yield or book_to_market to DERIVED_FIELDS here.


def resolve_field(field: str) -> tuple[FieldKind, RawFieldSpec | DerivedFieldSpec]:
    """Resolve a supported fundamental field to its schema entry.

    Args:
        field: Unified fundamental field name.

    Returns:
        A ``("raw", spec)`` or ``("derived", spec)`` tuple.

    Raises:
        ValueError: If ``field`` is not part of the unified schema.
    """
    if field in RAW_FIELDS:
        return "raw", RAW_FIELDS[field]
    if field in DERIVED_FIELDS:
        return "derived", DERIVED_FIELDS[field]
    raise ValueError(f"unknown fundamental field: {field}")


def list_supported_fields() -> list[str]:
    """Return all supported raw and schema-derived fundamental field names."""
    return sorted(set(RAW_FIELDS) | set(DERIVED_FIELDS))


__all__ = [
    "DERIVED_FIELDS",
    "RAW_FIELDS",
    "SEC_CONCEPT_MAP",
    "list_supported_fields",
    "resolve_field",
]
