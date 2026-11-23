"""Carry unambiguous user date ranges into market-data execution."""

from dataclasses import dataclass
from datetime import date
import re

from src.agent.instrument_identity import _normalize_symbol, _scan_symbols

_DATE = r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"
_RANGE = re.compile(rf"({_DATE})\s*(?:至|到|to\b|through\b|[~～–—]|\.{{2,3}})\s*({_DATE})", re.I)


@dataclass(frozen=True)
class UserDataWindow:
    """One explicit range for canonical instruments in the current user turn."""

    start: str
    end: str
    symbols: frozenset[str]

    @classmethod
    def parse(cls, message: str):
        """Read a literal ISO range, leaving ambiguous/multiple windows alone.

        Args:
            message: Current user text, never tool output or assistant history.

        Returns:
            A constraint for one valid range and explicit canonical symbols,
            or None. No relative-date, task-type or warmup inference is made.
        """
        dates = re.findall(_DATE, message)
        ranges = list(_RANGE.finditer(message))
        symbols = _scan_symbols(message)
        if len(dates) != 2 or len(ranges) != 1 or not symbols:
            return None
        start, end = ranges[0].groups()
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                return None
        except ValueError:
            return None
        return cls(start, end, frozenset(symbols))

    def normalize(self, arguments: dict) -> dict:
        """Remove padding from overlapping reads of the explicitly named symbols.

        Args:
            arguments: Model's market-data arguments; never mutated in place.

        Returns:
            Effective arguments with an auditable correction when needed.
            Disjoint comparison windows, new instruments and invalid arguments
            are unchanged. Explicit warmup is separate from the analysis dates
            and remains available to the market tool after normalization.
        """
        codes = arguments.get("codes")
        if not isinstance(codes, list) or not codes or any(
            not isinstance(code, str) or _normalize_symbol(code) not in self.symbols for code in codes
        ):
            return arguments
        start, end = arguments.get("start_date"), arguments.get("end_date")
        if not all(isinstance(d, str) and re.fullmatch(_DATE, d) for d in (start, end)):
            return arguments
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                return arguments
        except ValueError:
            return arguments
        if start > self.end or end < self.start:
            return arguments
        effective_start, effective_end = max(start, self.start), min(end, self.end)
        if (start, end) == (effective_start, effective_end):
            return arguments
        return {
            **arguments, "start_date": effective_start, "end_date": effective_end,
            "_user_date_window": {
                "user_start": self.start, "user_end": self.end,
                "model_start": start, "model_end": end,
                "reason": "explicit_user_range; use warmup_start_date for calculation history",
            },
        }
