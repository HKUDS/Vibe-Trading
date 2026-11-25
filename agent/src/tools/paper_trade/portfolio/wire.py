"""Public pt-v2.0 portfolio wire serialization and bucket-aware errors.

This module is the independent public boundary over the internal Decimal
step. It owns two document shapes, both matching the packaged
``paper_trade_step-v2.0.json`` contract:

* a success result containing the status/tool/schema/mode header, the
  opening, post-conversion and ending ledgers, the caller plan, per-bucket
  valuations, fills/reject/cancel rows linked to their ``bucket_id`` and
  ``plan_order_id``, conversions, sessions, warnings, the ``complete`` verdict
  and the four-layer hashes;
* a stable in-band error envelope with ``INVALID_REQUEST`` or
  ``PAPER_DATA_NOT_READY``, the reason/path/detail/bucket id, and a
  deterministic ``input_sha256=...`` echo of the raw request so an auditor can
  correlate the failure without receiving a fabricated end ledger or fills.

Every public numeric is a canonical fixed-point string; quantities remain JSON
integers. The serializer rejects floats, ``Decimal`` values, NaN/Infinity,
non-string mapping keys and invalid UTF-8 rather than coercing them. Internal
wire faults raise :class:`PortfolioWireError`; they are never serialized as one
of the two public error codes, so the ``INTERNAL`` distinction stays visible
to the caller.

The module is dependency-free beyond the standard library and the existing
portfolio models: no jsonschema runtime import, no clock, no randomness, no
network, and no legacy ``paper_trade.wire`` behaviour is touched.

The implementation lives in focused sibling modules (``wire_contract``,
``wire_errors``, ``wire_identity``, ``wire_normalize``, ``wire_analytics``,
``wire_success``, ``wire_validation``, ``wire_serialize``); this facade keeps
every historic ``wire.<symbol>`` binding path importable unchanged. The
submodules import the contract and each other, never this facade, so the
import graph stays acyclic.
"""

from __future__ import annotations

from .wire_analytics import (
    _analytics_sum as _analytics_sum,
    _assert_attribution as _assert_attribution,
    _assert_benchmark as _assert_benchmark,
    _canonical_money as _canonical_money,
    _canonical_ratio as _canonical_ratio,
    _decimal_value as _decimal_value,
    _exact_change as _exact_change,
    _exact_difference as _exact_difference,
)
from .wire_contract import (
    INPUT_HASH_MARKER,
    PUBLIC_ERROR_CODES,
    WIRE_MODE as WIRE_MODE,
    WIRE_SCHEMA_VERSION as WIRE_SCHEMA_VERSION,
    WIRE_TOOL as WIRE_TOOL,
    _BUCKET_REQUIRED_KEYS as _BUCKET_REQUIRED_KEYS,
    _CURRENCY_VALUES as _CURRENCY_VALUES,
    _DECIMAL_KEYS as _DECIMAL_KEYS,
    _DECIMAL_PATTERN as _DECIMAL_PATTERN,
    _HASH_PATTERN as _HASH_PATTERN,
    _INPUT_HASH_SUFFIX as _INPUT_HASH_SUFFIX,
    _OPTIONAL_SUCCESS_KEYS as _OPTIONAL_SUCCESS_KEYS,
    _PLAN_LINE_FIELDS as _PLAN_LINE_FIELDS,
    _REQUIRED_SUCCESS_KEYS as _REQUIRED_SUCCESS_KEYS,
    _SUCCESS_KEYS as _SUCCESS_KEYS,
    _PlanLine as _PlanLine,
)
from .wire_errors import (
    PortfolioWireError,
    _fallback_json as _fallback_json,
    _fallback_text as _fallback_text,
    _reject as _reject,
    error_code_for_exception,
)
from .wire_identity import (
    _raw_account_id as _raw_account_id,
    _strip_input_hash_suffix as _strip_input_hash_suffix,
    _wire_text as _wire_text,
    _with_input_hash as _with_input_hash,
    compute_raw_input_hash,
)
from .wire_normalize import (
    _MISSING_IDENTITY_REASONS as _MISSING_IDENTITY_REASONS,
    _PYDANTIC_FIELD_REASONS as _PYDANTIC_FIELD_REASONS,
    _UNION_TAGS as _UNION_TAGS,
    _assert_decimal_strings as _assert_decimal_strings,
    _first_result_error as _first_result_error,
    _location_path as _location_path,
    _normalize_json as _normalize_json,
    _pydantic_reason as _pydantic_reason,
)
from .wire_serialize import dumps_payload, serialize_error, serialize_success
from .wire_success import (
    _assert_analytics as _assert_analytics,
    _assert_plan_divergence as _assert_plan_divergence,
    _assert_required_nested_members as _assert_required_nested_members,
    _assert_result_model as _assert_result_model,
    _assert_success_header as _assert_success_header,
    _assert_success_links as _assert_success_links,
    _bucket_ids as _bucket_ids,
    _coerce_success as _coerce_success,
    _dump_result as _dump_result,
    _explicit_plan_lines as _explicit_plan_lines,
    _internal_plan_lines as _internal_plan_lines,
    _plan_line as _plan_line,
    _require_list as _require_list,
    _require_mapping as _require_mapping,
    _target_plan_keys as _target_plan_keys,
    build_success_payload,
)
from .wire_validation import build_error_from_exception, build_error_payload

__all__ = [
    "INPUT_HASH_MARKER",
    "PUBLIC_ERROR_CODES",
    "PortfolioWireError",
    "build_error_from_exception",
    "build_error_payload",
    "build_success_payload",
    "compute_raw_input_hash",
    "dumps_payload",
    "error_code_for_exception",
    "serialize_error",
    "serialize_success",
]
