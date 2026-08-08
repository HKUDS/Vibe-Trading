"""Shared input discipline for every valuation model in this package.

The modules here -- DCF, comps, three-statement -- deliberately own their own
result types and share almost nothing. What they DO share is the one rule that
decides whether a valuation is a measurement or a story:

    **A missing input makes the model NOT RUNNABLE. It never becomes an
    assumption chosen by the code.**

A discounted cash flow whose tax rate was quietly defaulted to 21%, or whose
terminal growth was quietly defaulted to 2.5%, produces a per-share number that
looks exactly like one built from filed statements. Nothing downstream can tell
them apart, and the reader has no way to know which assumptions were theirs.
:func:`require_inputs` and :class:`MissingInputError` exist so that outcome is
unreachable: the model stops and names every field it lacked.

An assumption that the CALLER makes is a different thing and is welcome -- but
it arrives as an :class:`Assumption` carrying its own justification, and it
shows up in the result so it can be argued with.

WHY NOT DEFAULTS
----------------
Every default in a valuation model is an opinion wearing a constant's clothes.
A 2.5% terminal growth rate is a view on long-run GDP; a 21% tax rate is a view
on jurisdiction and on permanence of current law. Those views may well be right,
but they belong to whoever signs the valuation, not to this package.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.entities.models import normalize_currency

__all__ = [
    "Assumption",
    "MissingInputError",
    "ValuationError",
    "normalize_currency",
    "require_inputs",
    "require_positive",
]


class ValuationError(ValueError):
    """Base class for every refusal a valuation model makes."""


class MissingInputError(ValuationError):
    """Raised when a model cannot run because inputs are absent.

    Carries the full list rather than the first one found, so a caller
    assembling data from filings learns everything still needed in one round
    trip instead of one field per attempt.

    Attributes:
        missing: Names of the absent fields, in the order they were required.
        model: Name of the model that refused.
    """

    def __init__(self, missing: Iterable[str], model: str) -> None:
        self.missing = tuple(missing)
        self.model = model
        joined = ", ".join(self.missing)
        super().__init__(
            f"{model} is not runnable: missing {len(self.missing)} required "
            f"input(s): {joined}. Supply them or report the model as not "
            f"runnable -- do not substitute an assumed value."
        )


@dataclass(frozen=True)
class Assumption:
    """A caller-supplied judgement, carried through to the result.

    Attributes:
        name: What is being assumed, e.g. ``"terminal_growth"``.
        value: The assumed value.
        basis: Why this value. Free text, but required and non-empty: an
            assumption whose justification nobody wrote down cannot be reviewed,
            and an unreviewable assumption in a valuation is indistinguishable
            from a guess.
        source: Optional pointer to where the basis came from -- a filing, a
            data tool call, a named analyst view.

    Raises:
        ValueError: If ``name`` or ``basis`` is empty or blank.
    """

    name: str
    value: Any
    basis: str
    source: str | None = None

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("an assumption must be named")
        if not str(self.basis).strip():
            raise ValueError(
                f"assumption {self.name!r} has no basis; state why this value was "
                "chosen, or do not make the assumption"
            )


def require_inputs(
    supplied: Mapping[str, Any],
    required: Iterable[str],
    model: str,
) -> None:
    """Refuse to run unless every required input is present and usable.

    A key that is absent, ``None``, or an empty string counts as missing. Zero
    and ``False`` do NOT: they are legitimate values for a line item, and
    treating them as missing is the mirror-image bug of defaulting.

    Args:
        supplied: The inputs the caller provided.
        required: Field names the model cannot run without.
        model: Name used in the error message.

    Raises:
        MissingInputError: If any required field is absent or unusable, naming
            all of them.
    """
    missing = [
        field
        for field in required
        if field not in supplied
        or supplied[field] is None
        or (isinstance(supplied[field], str) and not supplied[field].strip())
    ]
    if missing:
        raise MissingInputError(missing, model)


def require_positive(value: float, name: str, model: str) -> float:
    """Check a value that is meaningless at or below zero.

    Args:
        value: The value to check, e.g. a share count or a discount rate.
        name: Field name for the error message.
        model: Model name for the error message.

    Returns:
        ``value`` as a float.

    Raises:
        ValuationError: If the value is not a finite number greater than zero.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValuationError(f"{model}: {name} must be a number, got {value!r}") from exc
    if not numeric > 0.0 or numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValuationError(
            f"{model}: {name} must be a finite positive number, got {numeric}"
        )
    return numeric
