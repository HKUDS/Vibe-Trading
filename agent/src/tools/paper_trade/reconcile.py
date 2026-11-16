"""Independent ledger reconciliation for a ``paper_trade_step`` result.

The input is the initial account state and the returned success document. This
module replays fills with Decimal arithmetic and checks fees, cash, positions,
T+1 availability and NAV identities. It deliberately does not call the matching
engine's fill mutator: reconciliation must be able to catch that code's mistakes.

Market prices are absent from the result, so ``position_value`` is checked only
as a finite non-negative number and in the NAV identity. Received-state hashes,
engine fingerprints and duplicate fills without stable order ids are explicitly
outside this ledger-only proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .rules import MarketRules, money, quantize_money
from .schema import parse_account_state

_Q4 = Decimal("0.0001")
_ZERO = Decimal("0")


@dataclass(slots=True)
class _Position:
    qty: Decimal
    avg_cost: Decimal


@dataclass(frozen=True, slots=True)
class _Fill:
    date: str
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True)
class _Nav:
    date: str
    nav: Decimal
    cash: Decimal
    position_value: Decimal


def _number(value: Any, path: str, *, minimum: Decimal | None = None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a JSON number")
    try:
        number = money(value)
    except ArithmeticError as exc:
        raise ValueError(f"{path} must be finite") from exc
    if not number.is_finite():
        raise ValueError(f"{path} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{path} must be at least {minimum}")
    return number


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _fills(raw: Any) -> list[_Fill]:
    if not isinstance(raw, list):
        raise ValueError("result.fills must be an array")
    rows = []
    for index, item in enumerate(raw):
        path = f"result.fills[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{path} must be an object")
        side = _text(item.get("side"), f"{path}.side")
        if side not in ("buy", "sell"):
            raise ValueError(f"{path}.side must be buy or sell")
        rows.append(
            _Fill(
                date=_text(item.get("trade_date"), f"{path}.trade_date"),
                symbol=_text(item.get("symbol"), f"{path}.symbol"),
                side=side,
                qty=_number(
                    item.get("qty"), f"{path}.qty", minimum=Decimal("0.00000001")
                ),
                price=_number(
                    item.get("price"), f"{path}.price", minimum=Decimal("0.00000001")
                ),
                fee=_number(item.get("fee"), f"{path}.fee", minimum=_ZERO),
            )
        )
    return rows


def _nav_rows(raw: Any) -> list[_Nav]:
    if not isinstance(raw, list):
        raise ValueError("result.nav_series must be an array")
    rows = []
    for index, item in enumerate(raw):
        path = f"result.nav_series[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{path} must be an object")
        rows.append(
            _Nav(
                date=_text(item.get("date"), f"{path}.date"),
                nav=_number(item.get("nav"), f"{path}.nav"),
                cash=_number(item.get("cash"), f"{path}.cash"),
                position_value=_number(
                    item.get("position_value"), f"{path}.position_value"
                ),
            )
        )
    return rows


def _merge_position(
    positions: dict[str, _Position], symbol: str, qty: Decimal, avg_cost: Decimal
) -> None:
    existing = positions.get(symbol)
    if existing is None:
        positions[symbol] = _Position(
            qty, avg_cost.quantize(_Q4, rounding=ROUND_HALF_UP)
        )
        return
    new_qty = existing.qty + qty
    basis = (
        (existing.qty * existing.avg_cost + qty * avg_cost) / new_qty
        if new_qty
        else avg_cost
    )
    positions[symbol] = _Position(new_qty, basis.quantize(_Q4, rounding=ROUND_HALF_UP))


def _issue(
    issues: list[dict[str, Any]], code: str, path: str, expected: Any, actual: Any
) -> None:
    issues.append({"code": code, "path": path, "expected": expected, "actual": actual})


def _cash_at(cash_by_date: dict[str, Decimal], date: str, initial: Decimal) -> Decimal:
    eligible = [day for day in cash_by_date if day <= date]
    return cash_by_date[max(eligible)] if eligible else initial


def reconcile_document(account_state: Any, result: Any) -> dict[str, Any]:
    """Return a JSON-ready reconciliation report or raise for malformed input."""
    if (
        not isinstance(result, dict)
        or result.get("tool") != "paper_trade_step"
        or result.get("status") not in (None, "ok")
    ):
        raise ValueError("result must be a successful paper_trade_step document")
    market = _text(result.get("market"), "result.market")
    fee_model = result.get("effective_fee_model")
    if not isinstance(fee_model, dict):
        raise ValueError("result.effective_fee_model must be an object")
    for key, value in fee_model.items():
        _text(key, "result.effective_fee_model key")
        _number(value, f"result.effective_fee_model.{key}")
    rules = MarketRules(market, fee_model)
    initial = parse_account_state(account_state)
    actual_end = parse_account_state(result.get("end_state"), "result.end_state")
    fills = _fills(result.get("fills"))
    nav_rows = _nav_rows(result.get("nav_series"))

    initial_cash = quantize_money(money(initial.cash))
    cash = initial_cash
    positions: dict[str, _Position] = {}
    for position in initial.positions:
        _merge_position(
            positions, position.symbol, money(position.qty), money(position.avg_cost)
        )
    bought_today: dict[str, Decimal] = {}
    cash_by_date: dict[str, Decimal] = {}
    issues: list[dict[str, Any]] = []
    current_date: str | None = None

    for index, fill in enumerate(fills):
        path = f"fills[{index}]"
        if current_date != fill.date:
            if current_date is not None:
                cash_by_date[current_date] = cash
                if fill.date < current_date:
                    _issue(
                        issues,
                        "fill_order",
                        path,
                        f"dates after {current_date}",
                        fill.date,
                    )
            current_date = fill.date
            bought_today = {}
        expected_fee = rules.fee(fill.side, float(fill.qty), float(fill.price))
        if fill.fee != expected_fee:
            _issue(
                issues,
                "fee_mismatch",
                f"{path}.fee",
                float(expected_fee),
                float(fill.fee),
            )
        notional = quantize_money(fill.qty * fill.price)
        total = positions[fill.symbol].qty if fill.symbol in positions else _ZERO
        bought = bought_today.get(fill.symbol, _ZERO)
        violation = rules.sell_position_rejection(fill.side, fill.qty, total, bought)
        if violation == "t_plus_1":
            _issue(
                issues,
                "t_plus_1_violation",
                f"{path}.qty",
                float(total - bought),
                float(fill.qty),
            )
        elif violation == "insufficient_position":
            _issue(
                issues,
                "insufficient_position",
                f"{path}.qty",
                float(total),
                float(fill.qty),
            )

        if fill.side == "buy":
            cash = quantize_money(cash - notional - fill.fee)
            existing = positions.get(fill.symbol)
            if existing is None or existing.qty == 0:
                basis = fill.price
            else:
                basis = (existing.qty * existing.avg_cost + fill.qty * fill.price) / (
                    existing.qty + fill.qty
                )
            positions[fill.symbol] = _Position(
                (
                    fill.qty
                    if existing is None or existing.qty == 0
                    else existing.qty + fill.qty
                ),
                basis.quantize(_Q4, rounding=ROUND_HALF_UP),
            )
            bought_today[fill.symbol] = bought + fill.qty
        else:
            cash = quantize_money(cash + notional - fill.fee)
            existing = positions.get(fill.symbol, _Position(_ZERO, _ZERO))
            positions[fill.symbol] = _Position(
                existing.qty - fill.qty, existing.avg_cost
            )
        if cash < 0:
            _issue(issues, "negative_cash", path, ">= 0", float(cash))
    if current_date is not None:
        cash_by_date[current_date] = cash

    _issue_end_state(issues, actual_end, cash, positions)
    _issue_nav(issues, nav_rows, cash_by_date, initial_cash)
    expected_positions = [
        {
            "symbol": symbol,
            "qty": float(position.qty),
            "avg_cost": float(position.avg_cost),
        }
        for symbol, position in sorted(positions.items())
        if position.qty != 0
    ]
    return {
        "status": "ok",
        "tool": "paper_trade_reconcile",
        "reconciled": not issues,
        "summary": {
            "fills_checked": len(fills),
            "nav_rows_checked": len(nav_rows),
            "issue_count": len(issues),
        },
        "expected_end_state": {"cash": float(cash), "positions": expected_positions},
        "issues": issues,
        "not_verified": [
            "Market prices behind nav_series[].position_value are absent and were not recomputed.",
            "received_state_hash and engine_fingerprint are outside ledger reconciliation.",
            "Duplicate fills cannot be detected without stable order ids in the result.",
        ],
    }


def _issue_end_state(
    issues: list[dict[str, Any]],
    actual_end: Any,
    cash: Decimal,
    positions: dict[str, _Position],
) -> None:
    if money(actual_end.cash) != cash:
        _issue(
            issues, "end_cash_mismatch", "end_state.cash", float(cash), actual_end.cash
        )
    actual_positions: dict[str, Any] = {}
    for position in actual_end.positions:
        if position.symbol in actual_positions:
            _issue(
                issues,
                "duplicate_end_position",
                f"end_state.positions[{position.symbol}]",
                "one row",
                "duplicate",
            )
        else:
            actual_positions[position.symbol] = position
        if position.qty == 0:
            _issue(
                issues,
                "zero_end_position",
                f"end_state.positions[{position.symbol}].qty",
                "nonzero or omitted",
                0,
            )
    for symbol, expected in sorted(positions.items()):
        actual = actual_positions.get(symbol)
        path = f"end_state.positions[{symbol}]"
        if expected.qty == 0:
            if actual is not None and actual.qty != 0:
                _issue(
                    issues,
                    "position_qty_mismatch",
                    f"{path}.qty",
                    0.0,
                    actual.qty,
                )
            continue
        if actual is None:
            _issue(issues, "missing_end_position", path, float(expected.qty), None)
            continue
        if money(actual.qty) != expected.qty:
            _issue(
                issues,
                "position_qty_mismatch",
                f"{path}.qty",
                float(expected.qty),
                actual.qty,
            )
        if money(actual.avg_cost) != expected.avg_cost:
            _issue(
                issues,
                "position_avg_cost_mismatch",
                f"{path}.avg_cost",
                float(expected.avg_cost),
                actual.avg_cost,
            )
    for symbol, actual in sorted(actual_positions.items()):
        if symbol not in positions and actual.qty != 0:
            _issue(
                issues,
                "unexpected_end_position",
                f"end_state.positions[{symbol}]",
                None,
                actual.qty,
            )


def _issue_nav(
    issues: list[dict[str, Any]],
    rows: list[_Nav],
    cash_by_date: dict[str, Decimal],
    initial_cash: Decimal,
) -> None:
    seen: set[str] = set()
    previous_date: str | None = None
    for index, row in enumerate(rows):
        path = f"nav_series[{index}]"
        if row.date in seen:
            _issue(issues, "duplicate_nav_date", f"{path}.date", "unique", row.date)
        if previous_date is not None and row.date < previous_date:
            _issue(issues, "nav_order", f"{path}.date", f">= {previous_date}", row.date)
        seen.add(row.date)
        previous_date = row.date
        expected_cash = _cash_at(cash_by_date, row.date, initial_cash)
        if row.cash != expected_cash:
            _issue(
                issues,
                "nav_cash_mismatch",
                f"{path}.cash",
                float(expected_cash),
                float(row.cash),
            )
        expected_nav = quantize_money(row.cash + row.position_value)
        if row.nav != expected_nav:
            _issue(
                issues,
                "nav_identity_mismatch",
                f"{path}.nav",
                float(expected_nav),
                float(row.nav),
            )
        if row.position_value < 0:
            _issue(
                issues,
                "negative_position_value",
                f"{path}.position_value",
                ">= 0",
                float(row.position_value),
            )
