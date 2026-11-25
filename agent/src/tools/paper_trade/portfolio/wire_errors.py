"""Portfolio wire fault machinery: the INTERNAL-only error and code mapping.

:class:`PortfolioWireError` is a transport/engine fault, never a public
in-band envelope; ``_reject`` is its single raise site. The deterministic
hash fallbacks and the exception-to-code mapping share this module because
they all serve the error boundary rather than the success document.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NoReturn

from .models import JsonValue
from .orchestrator import OrchestrationError, OrchestrationCode
from .schema import PortfolioRequestError
from .sessions import PortfolioSessionError


@dataclass(frozen=True, slots=True)
class PortfolioWireError(ValueError):
    """One stable serialization/identity fault; never a public error envelope.

    ``code`` is always ``INTERNAL``: these failures mean the engine produced a
    document or an exception class the public pt-v2.0 contract cannot publish
    in-band. The tool layer must surface them as a transport/engine fault,
    exactly like the legacy pt-v1.x wire raises rather than shipping a document
    an auditor cannot route.
    """

    reason: str
    path: str = "$"
    bucket_id: str | None = None
    detail: str = ""

    @property
    def code(self) -> str:
        return "INTERNAL"

    def __str__(self) -> str:
        return f"{self.code}:{self.reason}:{self.path}"


def _reject(
    reason: str,
    path: str,
    *,
    bucket_id: str | None = None,
    detail: str = "",
) -> NoReturn:
    raise PortfolioWireError(reason=reason, path=path or "$", bucket_id=bucket_id, detail=detail)


def _fallback_text(value: str) -> str:
    """Replace lone surrogates with deterministic escape text for hashing."""
    return value.encode("utf-8", "backslashreplace").decode("utf-8")


def _fallback_json(value: Any) -> JsonValue:
    """Normalize a non-JSON-native value into a deterministic hashable shape.

    Used only by :func:`compute_raw_input_hash` when the raw input contains a
    non-finite float, ``Decimal`` or other value JCS refuses. The fallback is
    intentionally tagged and total so the error path can still echo an input
    hash instead of raising a second fault.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "<float:nan>"
        if math.isinf(value):
            return "<float:infinity>" if value > 0 else "<float:-infinity>"
        return repr(value)
    if isinstance(value, str):
        return _fallback_text(value)
    if isinstance(value, Decimal):
        return f"<decimal:{value}>"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes:{bytes(value).hex()}>"
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            text = key if isinstance(key, str) else f"<key:{type(key).__name__}:{key!r}>"
            normalized[_fallback_text(text)] = _fallback_json(item)
        return normalized
    if isinstance(value, (set, frozenset)):
        return [_fallback_json(item) for item in sorted(value, key=repr)]
    if isinstance(value, Sequence):
        return [_fallback_json(item) for item in value]
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def error_code_for_exception(exc: BaseException) -> OrchestrationCode:
    """Return the stable code an exception class maps to, including ``INTERNAL``."""
    if isinstance(exc, PortfolioSessionError):
        return exc.code
    if isinstance(exc, PortfolioRequestError):
        return "INVALID_REQUEST"
    if isinstance(exc, OrchestrationError):
        return exc.code
    return "INTERNAL"
