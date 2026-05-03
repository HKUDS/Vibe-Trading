"""Infer required A-share financial fields from prompt text and signal_engine source.

This module is intentionally narrow:

* Prompt inference returns registry-backed field candidates.
* Source inference extracts string-literal field references from Python AST.
* Final planning delegates ambiguity handling to the financial field registry.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Iterable, Mapping

from backtest.financials.contracts import FinancialFieldInferenceResult

from backtest.financials.ashare.field_registry import (
    FinancialQueryPlan,
    build_financial_query_plan,
    get_financial_field_registry,
)


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _sorted_by_text_order(text: str, positions: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name, _ in sorted(
            positions.items(),
            key=lambda item: (item[1], item[0]),
        )
    )


def _contains_non_ascii(text: str) -> bool:
    return any(ord(char) > 127 for char in text)


def _is_unit_like_suffix(text: str) -> bool:
    candidate = text.strip()
    if not candidate:
        return False
    if re.fullmatch(r"[%/A-Za-z0-9._+-]+", candidate):
        return True
    return candidate in {
        "元",
        "股",
        "天",
        "次",
        "倍",
        "年",
        "月",
        "日",
        "周",
        "万元",
        "亿元",
        "万股",
    }


def _normalize_description_alias(description: str) -> tuple[str, ...]:
    normalized = description.strip()
    aliases = [normalized]

    stripped = normalized
    for pattern in (r"（(.*?)）", r"\((.*?)\)"):
        match = re.search(pattern, stripped)
        if match and _is_unit_like_suffix(match.group(1)):
            stripped = re.sub(pattern, "", stripped).strip()
    if stripped and stripped not in aliases:
        aliases.append(stripped)

    unit_stripped = re.sub(r"[：:、，,。%/（）()元股\s]+", "", stripped or normalized).strip()
    if unit_stripped and unit_stripped not in aliases:
        aliases.append(unit_stripped)

    return tuple(alias for alias in aliases if alias)


def _iter_registry_descriptions() -> Iterable[tuple[str, str]]:
    registry = get_financial_field_registry()
    for table in registry.tables.values():
        for field in table.output_fields.values():
            description = (field.description or "").strip()
            if description:
                yield field.name, description


def infer_financial_fields_from_prompt(prompt: str) -> tuple[str, ...]:
    """Infer field candidates from free-form prompt text.

    The first version stays conservative:

    * field-code hits are exact token matches
    * Chinese description hits are exact substring matches
    * only fields present in the local registry are returned
    """
    text = (prompt or "").strip()
    if not text:
        return ()

    registry = get_financial_field_registry()
    prompt_lower = text.lower()
    matched_positions: dict[str, int] = {}

    for field_name in registry.field_to_tables:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(field_name.lower())}(?![A-Za-z0-9_])"
        match = re.search(pattern, prompt_lower)
        if match:
            matched_positions[field_name] = min(
                matched_positions.get(field_name, match.start()),
                match.start(),
            )

    for field_name, description in _iter_registry_descriptions():
        if not _contains_non_ascii(description):
            continue
        for alias in _normalize_description_alias(description):
            position = text.find(alias)
            if position >= 0:
                matched_positions[field_name] = min(
                    matched_positions.get(field_name, position),
                    position,
                )
                break

    return _sorted_by_text_order(text, matched_positions)


def _extract_string_constants(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def infer_financial_fields_from_source(source: str) -> tuple[str, ...]:
    """Infer field candidates from Python source.

    This version deliberately keys off string literals in the AST and filters
    them through the financial field registry. That covers the common patterns:

    * ``df["field"]``
    * ``row.get("field")``
    * ``fields = ["field_a", "field_b"]``
    * ``field = "field"`` followed by dynamic indexing
    """
    text = (source or "").strip()
    if not text:
        return ()

    tree = ast.parse(text)
    registry = get_financial_field_registry()

    matched_positions: dict[str, int] = {}
    for value in _extract_string_constants(tree):
        if not registry.has_field(value):
            continue
        position = text.find(value)
        matched_positions[value] = min(
            matched_positions.get(value, position),
            position,
        )
    return _sorted_by_text_order(text, matched_positions)


def infer_financial_fields_from_file(file_path: str | Path) -> tuple[str, ...]:
    """Infer field candidates from a Python source file."""
    path = Path(file_path)
    return infer_financial_fields_from_source(path.read_text(encoding="utf-8"))


def infer_financial_fields(
    *,
    prompt: str = "",
    source: str = "",
    preferred_tables: Mapping[str, str] | None = None,
    include_key_columns: bool = True,
) -> FinancialFieldInferenceResult:
    """Run prompt/source inference and build a registry-backed query plan.

    The result keeps prompt candidates and source hits separate so callers can
    decide whether to trust generated code over natural-language intent.
    """
    prompt_fields = infer_financial_fields_from_prompt(prompt)
    source_fields = infer_financial_fields_from_source(source)
    combined_fields = _dedupe((*prompt_fields, *source_fields))
    query_plan = build_financial_query_plan(
        combined_fields,
        preferred_tables=preferred_tables,
        include_key_columns=include_key_columns,
        strict=False,
    )
    return FinancialFieldInferenceResult(
        prompt_fields=prompt_fields,
        source_fields=source_fields,
        combined_fields=combined_fields,
        query_plan=query_plan,
    )