"""Validate the PM's final position basis before accepting its report."""

from decimal import Decimal, InvalidOperation
import re


TABLE_HEADER = "| Scenario | Position (% NAV) | Asset return (%) | NAV return (%) |"
POSITION_RISK_RULE = (
    "Include one final position-risk table using this exact header:\n"
    + TABLE_HEADER
    + "\n| --- | --- | --- | --- |\n"
    "Use signed numeric percentages in all three numeric columns (3 means 3%, "
    "not 0.03). Use the SAME PM-final position for every row, using the proposed "
    "allocation for a conditional entry and zero for a wait decision without a planned "
    "position. Label conditional scenarios. Include stop/base/bear scenarios as applicable. "
    "NAV return = position * asset return / 100. Recompute after changing the "
    "CRO's allocation. Put all final portfolio-impact estimates in this table; "
    "label upstream sizing separately and do not reuse its NAV numbers. "
    "The worker checks this table before marking the report complete."
)


def validate_position_risk_report(report: str) -> str | None:
    """Return an actionable error for a missing or inconsistent final risk table.

    Args:
        report: Final PM report, with percentages rounded as displayed.

    Returns:
        None on success, otherwise the correction the worker must request.
    """
    lines = report.splitlines()
    headers = [i for i, line in enumerate(lines) if line.strip() == TABLE_HEADER]
    if len(headers) != 1:
        return "Include exactly one final position-risk table. " + POSITION_RISK_RULE
    weight = None
    rows = 0
    for line in lines[headers[0] + 1:]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(cell and set(cell) <= set("-: ") for cell in cells):
            continue
        if len(cells) != 4 or not cells[0]:
            return "Position-risk table requires a scenario and three numeric percentages."
        try:
            values = [cell.replace("−", "-") for cell in cells[1:]]
            if not all(re.fullmatch(r"[+-]?\d{1,9}(?:\.\d{1,12})?%?", cell) for cell in values):
                raise InvalidOperation
            position, asset, nav = [Decimal(cell.rstrip("%")) for cell in values]
            if not all(value.is_finite() for value in (position, asset, nav)):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            return "Position-risk table percentages must be finite numbers, without prose."
        if weight is not None and position != weight:
            return "Position-risk rows mix allocations; recalculate every row at the PM-final position."
        weight = position
        expected = position * asset / 100
        # Respect written rounding, but never accept a whole-percent NAV
        # rounding that would hide the 0.50% versus 0.372% regression.
        tolerance = min(Decimal("0.005"), Decimal(10) ** nav.as_tuple().exponent / 2)
        if abs(nav - expected) > tolerance:
            return (
                f"Scenario {cells[0]!r}: {position}% position × {asset}% asset return "
                f"requires {expected}% NAV return, not {nav}%. Recalculate and rewrite report.md."
            )
        rows += 1
    return None if rows else "Position-risk table has no scenarios."
