"""In-band error-envelope validation and build for the public pt-v2.0 wire.

Only ``INVALID_REQUEST`` and ``PAPER_DATA_NOT_READY`` may become public
envelopes; ``INTERNAL`` is deliberately refused here and raised as a
transport fault so the caller keeps the engine-fault distinction.
"""

from __future__ import annotations

from typing import Any

from .models import JsonObject
from .orchestrator import OrchestrationError, OrchestrationCode
from .schema import PortfolioRequestError
from .sessions import PortfolioSessionError
from .wire_contract import PUBLIC_ERROR_CODES, WIRE_MODE, WIRE_SCHEMA_VERSION, WIRE_TOOL
from .wire_errors import _reject, error_code_for_exception
from .wire_identity import _raw_account_id, _wire_text, _with_input_hash


def build_error_payload(
    raw_input: Any,
    *,
    code: OrchestrationCode,
    reason: str,
    path: str = "$",
    detail: str = "",
    bucket_id: str | None = None,
) -> JsonObject:
    """Serialize one stable in-band pt-v2.0 error envelope.

    The document contains exactly the packaged error-envelope fields and never
    a ledger/fill member. ``INTERNAL`` is deliberately refused: it is an engine
    fault, not a public in-band code, so :class:`PortfolioWireError` is raised
    and the caller keeps the transport/internal distinction. Every error detail
    ends with ``input_sha256=<digest>`` from :func:`compute_raw_input_hash`.
    """
    if code == "INTERNAL":
        _reject(
            "internal_error_not_in_band",
            path,
            bucket_id=bucket_id,
            detail="INTERNAL faults are transport/engine errors, not pt-v2.0 envelopes",
        )
    if code not in PUBLIC_ERROR_CODES:
        _reject("invalid_error_code", path, detail=f"unsupported public error code {code!r}")
    stable_reason = (
        _wire_text(reason) if isinstance(reason, str) and reason else "invalid_request"
    )
    stable_path = _wire_text(path) if isinstance(path, str) and path else "$"
    stable_detail = (
        _wire_text(detail) if isinstance(detail, str) and detail else stable_reason
    )
    issue: JsonObject = {
        "reason": stable_reason,
        "path": stable_path,
        "detail": _with_input_hash(stable_detail, raw_input),
    }
    if isinstance(bucket_id, str) and bucket_id:
        issue["bucket_id"] = _wire_text(bucket_id)
    payload: JsonObject = {
        "status": "error",
        "tool": WIRE_TOOL,
        "schema_version": WIRE_SCHEMA_VERSION,
        "mode": WIRE_MODE,
        "account_id": _wire_text(_raw_account_id(raw_input)),
        "code": code,
        "error": issue,
    }
    return payload


def build_error_from_exception(
    raw_input: Any,
    exc: BaseException,
    *,
    path: str | None = None,
    detail: str | None = None,
) -> JsonObject:
    """Map a known request/data exception to an in-band error document.

    ``PortfolioRequestError`` -> ``INVALID_REQUEST``; ``PortfolioSessionError``
    keeps its declared code; ``OrchestrationError`` keeps its code but an
    ``INTERNAL`` stage fault is re-raised as :class:`PortfolioWireError` rather
    than masked as a public envelope.
    """
    code = error_code_for_exception(exc)
    if isinstance(exc, (PortfolioRequestError, PortfolioSessionError, OrchestrationError)):
        reason = exc.reason
        resolved_path = path if path is not None else exc.path
        resolved_detail = detail if detail is not None else (exc.detail or str(exc))
        bucket_id = exc.bucket_id
    else:
        reason = "internal_wire_failure"
        resolved_path = path if path is not None else "$"
        resolved_detail = detail if detail is not None else f"{type(exc).__name__}: {exc}"[:200]
        bucket_id = None
        code = "INTERNAL"
    return build_error_payload(
        raw_input,
        code=code,
        reason=reason,
        path=resolved_path,
        detail=resolved_detail,
        bucket_id=bucket_id,
    )
