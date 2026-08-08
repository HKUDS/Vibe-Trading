"""Agent tool for client-cash-flow-aware portfolio performance.

Read-only. It reports the time-weighted, Modified Dietz, and money-weighted
returns of an account whose owner moved money in and out mid-period, which the
backtest metric path cannot express because it is funded by a single scalar.
No order path exists here and none may be added: this is a research surface.
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any

from src.agent.tools import BaseTool
from src.entities.cashflow import CashFlow, CashFlowSeries
from src.entities.ingest import load_cashflows
from src.quantlib.performance import (
    DEFAULT_EXTERNAL_KINDS,
    DEFAULT_INTERNAL_KINDS,
    FLOW_TIMING_END,
    FLOW_TIMING_START,
    UnsolvableRateError,
    modified_dietz_return,
    money_weighted_return,
    time_weighted_return,
)

#: Upper bound on inline records, so one tool call cannot blow the context
#: window. Larger histories belong in a file and go through ``flows_path``.
_MAX_VALUATIONS = 4000
_MAX_INLINE_FLOWS = 4000

#: Decimal places used for every number in the envelope. Six is enough to carry
#: a return to a hundredth of a basis point without emitting float noise.
_ROUNDING = 6


class CashFlowPerformanceTool(BaseTool):
    """Report TWR, Modified Dietz, and money-weighted return for a client account."""

    name = "cashflow_performance"
    description = (
        "Measure the return of an account that received client contributions "
        "or paid out withdrawals mid-period. Takes a dated valuation series "
        "plus irregular cash flows (inline records or a CSV path) and returns "
        "the true time-weighted return (manager skill, immune to flow timing), "
        "the Modified Dietz day-weighted approximation, and the money-weighted "
        "XIRR (client experience). External flows are contributions, capital "
        "calls, subscriptions, transfers, distributions, redemptions and "
        "withdrawals; dividends, coupons, interest and fees are internal and "
        "already inside the valuations. Research only; places no orders."
    )
    repeatable = True
    is_readonly = True
    parameters = {
        "type": "object",
        "properties": {
            "valuations": {
                "type": "array",
                "minItems": 2,
                "maxItems": _MAX_VALUATIONS,
                "description": (
                    "Portfolio value on each valuation date, earliest first. "
                    "Two entries give a single-period answer; add interim "
                    "marks to make the time-weighted return exact."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "ISO-8601 date, e.g. 2024-06-30.",
                        },
                        "value": {"type": "number"},
                    },
                    "required": ["date", "value"],
                },
            },
            "flows": {
                "type": "array",
                "maxItems": _MAX_INLINE_FLOWS,
                "description": (
                    "Inline cash flows. Amounts are from the client's point of "
                    "view: a contribution is NEGATIVE (cash leaves the client) "
                    "and a distribution is POSITIVE. Mutually exclusive with "
                    "flows_path."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "amount": {"type": "number"},
                        "kind": {
                            "type": "string",
                            "description": (
                                "e.g. contribution, withdrawal, distribution, "
                                "capital_call, dividend."
                            ),
                        },
                        "currency": {
                            "type": "string",
                            "description": "Overrides the top-level currency.",
                        },
                    },
                    "required": ["date", "amount", "kind"],
                },
            },
            "flows_path": {
                "type": "string",
                "description": (
                    "Path to a delimited cash-flow file (.csv/.tsv/.txt). "
                    "Mutually exclusive with flows."
                ),
            },
            "currency": {
                "type": "string",
                "description": (
                    "Reporting currency. Required for inline flows that do not "
                    "carry their own, and for a file with no currency column."
                ),
            },
            "flows_default_kind": {
                "type": "string",
                "description": "Kind for file rows whose kind column is absent or blank.",
            },
            "flows_date_format": {
                "type": "string",
                "description": "strptime format for the file's date column, if not ISO-8601.",
            },
            "flows_columns": {
                "type": "object",
                "description": (
                    "Map canonical field to file column name, e.g. "
                    '{"date": "Payment Date", "amount": "Net"}.'
                ),
                "additionalProperties": {"type": "string"},
            },
            "flows_invert_sign": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Negate every file amount, for exports that report "
                    "contributions as positive."
                ),
            },
            "flow_timing": {
                "type": "string",
                "enum": [FLOW_TIMING_END, FLOW_TIMING_START],
                "default": FLOW_TIMING_END,
                "description": (
                    "Whether a flow dated on a valuation date settles after "
                    "that valuation ('end') or before the next interval "
                    "('start'). Affects the time-weighted return only."
                ),
            },
            "external_kinds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Override the default set of boundary-crossing kinds.",
            },
            "internal_kinds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Override the default set of inside-the-portfolio kinds.",
            },
        },
        "required": ["valuations"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Compute the three returns and package them in one envelope.

        Args:
            **kwargs: Inputs described by :attr:`parameters`.

        Returns:
            A JSON envelope with ``status``, ``inputs``, ``summary``,
            ``sub_periods``, per-measure detail, ``notes`` and ``limitations``.
            Invalid input returns a JSON error envelope; it never raises and
            never returns ``None``.
        """
        notes: list[str] = []
        try:
            valuations = _coerce_valuations(kwargs.get("valuations"))
            series = _resolve_flows(kwargs)
            flow_timing = _coerce_flow_timing(kwargs.get("flow_timing"))
            external_kinds = _coerce_kinds(kwargs.get("external_kinds"), "external_kinds")
            internal_kinds = _coerce_kinds(kwargs.get("internal_kinds"), "internal_kinds")

            twr = time_weighted_return(
                valuations,
                series,
                flow_timing=flow_timing,
                external_kinds=external_kinds,
                internal_kinds=internal_kinds,
            )
            dietz = modified_dietz_return(
                valuations,
                series,
                external_kinds=external_kinds,
                internal_kinds=internal_kinds,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return _error(str(exc))

        try:
            mwr = money_weighted_return(
                valuations,
                series,
                external_kinds=external_kinds,
                internal_kinds=internal_kinds,
            )
        except UnsolvableRateError as exc:
            # A one-directional stream has no IRR. That is a property of the
            # account, not a failure, so the other two measures still ship.
            mwr = None
            notes.append(f"money-weighted return not reported: {exc}")

        payload = {
            "status": "ok",
            "tool": self.name,
            "inputs": {
                "valuation_count": len(valuations),
                "flow_count": len(series) if series is not None else 0,
                "flow_source": (
                    "flows_path"
                    if kwargs.get("flows_path")
                    else "inline" if kwargs.get("flows") else "none"
                ),
                "flow_timing": flow_timing,
                "currency": series.currency if series is not None else kwargs.get("currency"),
                "external_kinds": sorted(external_kinds or DEFAULT_EXTERNAL_KINDS),
                "internal_kinds": sorted(internal_kinds or DEFAULT_INTERNAL_KINDS),
            },
            "summary": {
                "start_date": twr.start_date.isoformat(),
                "end_date": twr.end_date.isoformat(),
                "start_value": _rounded(twr.start_value),
                "end_value": _rounded(twr.end_value),
                "net_external_flow": _rounded(twr.net_external_flow),
                "time_weighted_return": _rounded(twr.total_return),
                "time_weighted_annualized": _rounded_or_none(twr.annualized_return),
                "modified_dietz_return": _rounded(dietz.total_return),
                "modified_dietz_annualized": _rounded_or_none(dietz.annualized_return),
                "money_weighted_return_annualized": (
                    None if mwr is None else _rounded(mwr.annualized_return)
                ),
                "money_weighted_return_period": (
                    None if mwr is None else _rounded(mwr.period_return)
                ),
            },
            "sub_periods": [
                {
                    "start": period.start.isoformat(),
                    "end": period.end.isoformat(),
                    "start_value": _rounded(period.start_value),
                    "end_value": _rounded(period.end_value),
                    "external_flow": _rounded(period.external_flow),
                    "return": _rounded(period.period_return),
                }
                for period in twr.sub_periods
            ],
            "modified_dietz": {
                "net_external_flow": _rounded(dietz.net_external_flow),
                "weighted_external_flow": _rounded(dietz.weighted_external_flow),
                "average_capital": _rounded(dietz.average_capital),
                "flow_weights": [
                    {
                        "date": when.isoformat(),
                        "amount": _rounded(amount),
                        "weight": _rounded(weight),
                    }
                    for when, amount, weight in dietz.flow_weights
                ],
            },
            "money_weighted": (
                None
                if mwr is None
                else {
                    "annualized_return": _rounded(mwr.annualized_return),
                    "period_return": _rounded(mwr.period_return),
                    "years": _rounded(mwr.years),
                    "solver_iterations": mwr.iterations,
                }
            ),
            "notes": notes,
            "limitations": [
                "Flow amounts are holder-perspective: a contribution is negative.",
                "Only contributions, withdrawals and transfers are treated as "
                "external; dividends, coupons and fees are assumed already "
                "inside the valuation series.",
                "Modified Dietz is a money-weighted approximation, not a "
                "cheaper time-weighted return.",
                "Returns are gross of any fee not already reflected in the "
                "valuations, and carry no tax or currency translation.",
            ],
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def _coerce_valuations(raw: Any) -> list[tuple[date, float]]:
    """Parse the raw valuation array into ``(date, value)`` pairs.

    Args:
        raw: Value supplied for the ``valuations`` parameter.

    Returns:
        Pairs in the order supplied; the library sorts and validates them.

    Raises:
        ValueError: If the array is missing, wrongly shaped, over the size cap,
            or an entry lacks a usable date or value.
    """
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("valuations must be an array of at least two {date, value} objects")
    if len(raw) > _MAX_VALUATIONS:
        raise ValueError(f"valuations may contain at most {_MAX_VALUATIONS} entries")

    pairs: list[tuple[date, float]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"valuations[{index}] must be an object with date and value")
        if "date" not in item or "value" not in item:
            raise ValueError(f"valuations[{index}] needs both 'date' and 'value'")
        try:
            value = float(item["value"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"valuations[{index}].value must be numeric") from exc
        if not math.isfinite(value):
            raise ValueError(f"valuations[{index}].value must be finite")
        pairs.append((item["date"], value))
    return pairs


def _resolve_flows(kwargs: dict[str, Any]) -> CashFlowSeries | None:
    """Build the cash-flow series from inline records or from a file.

    Args:
        kwargs: The tool's raw inputs.

    Returns:
        A ``CashFlowSeries``, or ``None`` when no flows were supplied.

    Raises:
        ValueError: If both sources were given, an inline record is malformed,
            or a currency is missing. File problems surface as
            ``CashFlowIngestError``, which is a ``ValueError``.
    """
    inline = kwargs.get("flows")
    path = kwargs.get("flows_path")
    if inline and path:
        raise ValueError("pass either flows or flows_path, not both")
    currency = kwargs.get("currency")

    if path:
        columns = kwargs.get("flows_columns")
        if columns is not None and not isinstance(columns, dict):
            raise ValueError("flows_columns must be an object mapping field to column name")
        return load_cashflows(
            str(path),
            columns=columns,
            currency=currency,
            default_kind=kwargs.get("flows_default_kind"),
            date_format=kwargs.get("flows_date_format"),
            invert_sign=bool(kwargs.get("flows_invert_sign", False)),
        )

    if not inline:
        return None
    if not isinstance(inline, list):
        raise ValueError("flows must be an array of {date, amount, kind} objects")
    if len(inline) > _MAX_INLINE_FLOWS:
        raise ValueError(f"flows may contain at most {_MAX_INLINE_FLOWS} entries")

    records: list[CashFlow] = []
    for index, item in enumerate(inline):
        if not isinstance(item, dict):
            raise ValueError(f"flows[{index}] must be an object")
        row_currency = item.get("currency") or currency
        if not row_currency:
            raise ValueError(
                f"flows[{index}] has no currency and no top-level currency was "
                "given; currency is never defaulted"
            )
        try:
            records.append(
                CashFlow(
                    date=item["date"],
                    amount=item["amount"],
                    kind=item["kind"],
                    currency=row_currency,
                )
            )
        except KeyError as exc:
            raise ValueError(f"flows[{index}] is missing {exc.args[0]!r}") from exc
        except ValueError as exc:
            raise ValueError(f"flows[{index}]: {exc}") from exc
    return CashFlowSeries(tuple(records))


def _coerce_flow_timing(raw: Any) -> str:
    """Validate the flow-timing token.

    Args:
        raw: Value supplied for ``flow_timing``; ``None`` selects the default.

    Returns:
        Either :data:`~src.quantlib.performance.FLOW_TIMING_END` or
        :data:`~src.quantlib.performance.FLOW_TIMING_START`.

    Raises:
        ValueError: If the token is not one of the two recognised values.
    """
    if raw is None or raw == "":
        return FLOW_TIMING_END
    token = str(raw).strip().lower()
    if token not in (FLOW_TIMING_END, FLOW_TIMING_START):
        raise ValueError(
            f"flow_timing must be {FLOW_TIMING_END!r} or {FLOW_TIMING_START!r}, "
            f"got {raw!r}"
        )
    return token


def _coerce_kinds(raw: Any, field_name: str) -> list[str] | None:
    """Validate an optional kind-classification override.

    Args:
        raw: Value supplied for ``external_kinds`` or ``internal_kinds``.
        field_name: Name used in the error message.

    Returns:
        The list of labels, or ``None`` to keep the module default.

    Raises:
        ValueError: If the value is not an array of non-empty strings.
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{field_name} must be a non-empty array of kind labels")
    labels: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} entries must be non-empty strings")
        labels.append(item)
    return labels


def _rounded(value: float) -> float:
    """Round a finite scalar for stable, compact JSON.

    Args:
        value: Number to round.

    Returns:
        The value rounded to :data:`_ROUNDING` decimal places.
    """
    return round(float(value), _ROUNDING)


def _rounded_or_none(value: float | None) -> float | None:
    """Round a scalar that may be deliberately absent.

    Args:
        value: Number to round, or ``None``.

    Returns:
        The rounded value, or ``None`` when the caller had nothing to report.
    """
    return None if value is None else _rounded(value)


def _error(message: str) -> str:
    """Build the tool's stable error envelope.

    Args:
        message: Operator-facing explanation.

    Returns:
        A JSON string with ``status`` set to ``"error"``.
    """
    return json.dumps(
        {"status": "error", "tool": CashFlowPerformanceTool.name, "error": message},
        ensure_ascii=False,
    )
